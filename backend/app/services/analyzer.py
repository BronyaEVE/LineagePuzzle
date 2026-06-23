from __future__ import annotations

import uuid
from datetime import datetime

from ..models.analysis import AnalysisResult, DatabaseInfo, VisEdge, VisNode, Visualization
from ..models.lineage import ColumnInfo, TableInfo, TableType
from ..models.statement import StatementGroup
from ..schemas.requests import DatabaseConfig
from .db_connector import DBConnector
from .lineage_extractor import extract_lineages
from .preprocessor import preprocess
from .splitter import split_statements


def analyze(script: str, db_config: DatabaseConfig | None) -> AnalysisResult:
    """完整分析编排：预处理 → 拆分 → 血缘提取（AST）→ DB 校验（可选）→ 结果组装。

    DESIGN.v2 §3.1/§5.5：血缘提取统一走 sqlglot AST，无外部依赖、可离线运行。
    db_config 为 None 时进入纯 AST 模式（ast_only），不连接数据库。

    db_config 提供时，DB 连接仅用于读 INFORMATION_SCHEMA 校验表存在性 / 补充列信息，
    不参与血缘提取（不再执行 EXPLAIN）。DB 连接失败时降级为 ast_only。
    """

    # 步骤1+2: 预处理和拆分
    cleaned = preprocess(script)
    group = split_statements(cleaned, original_script=script)

    # 步骤3: 提取血缘关系（纯 AST，不依赖 DB）
    lineages, table_type_map = extract_lineages(group.statements)

    # 步骤4: 可选的 DB 校验（仅读表结构，不执行 EXPLAIN）
    db_tables: list[TableInfo] = []
    extraction_mode = "ast_only"
    if db_config is not None:
        db: DBConnector | None = None
        try:
            db = DBConnector(
                host=db_config.host,
                port=db_config.port,
                database=db_config.database,
                username=db_config.username,
                password=db_config.password,
            )
            # 子模块 A: 获取表结构（用于校验表存在性 + 补充列信息）
            db_tables = db.get_tables_info()
            extraction_mode = "ast_with_db_validation"
        except Exception:
            # 数据库连接失败时降级为纯 AST 模式，仍返回血缘结果
            extraction_mode = "ast_only"
        finally:
            if db:
                db.dispose()

    # 补充脚本中新建表的信息
    script_tables = _build_script_tables(group, table_type_map)

    # 步骤5: 组装可视化数据
    visualization = _build_visualization(lineages, table_type_map)

    return AnalysisResult(
        analysis_id=str(uuid.uuid4()),
        created_at=datetime.now(),
        input_script=script,
        database_info=DatabaseInfo(
            tables_from_db=db_tables,
            tables_from_script=script_tables,
        ),
        statement_group=group,
        lineages=lineages,
        visualization=visualization,
        extraction_mode=extraction_mode,
    )


def _build_script_tables(
    group: StatementGroup, table_type_map: dict[str, TableType]
) -> list[TableInfo]:
    """从脚本 CREATE 语句中构建新表信息。"""
    script_tables: list[TableInfo] = []
    for stmt in group.statements:
        for table_name in stmt.tables_created:
            script_tables.append(
                TableInfo(
                    table_name=table_name,
                    table_type=table_type_map.get(table_name, TableType.INTERMEDIATE),
                    source="script_created",
                    columns=[],  # 列信息在数据库中可查询时补充
                )
            )
    return script_tables


def _build_visualization(
    lineages: list, table_type_map: dict[str, TableType]
) -> Visualization:
    """根据血缘关系构建可视化节点和边。"""
    node_set: dict[str, VisNode] = {}
    edges: list[VisEdge] = []

    for lin in lineages:
        if lin.source_table and lin.source_table not in node_set:
            node_set[lin.source_table] = VisNode(
                id=lin.source_table,
                label=lin.source_table,
                type=table_type_map.get(lin.source_table, TableType.SOURCE),
            )
        if lin.target_table not in node_set:
            node_set[lin.target_table] = VisNode(
                id=lin.target_table,
                label=lin.target_table,
                type=table_type_map.get(lin.target_table, TableType.TARGET),
            )
        edges.append(
            VisEdge(
                source=lin.source_table or "",
                target=lin.target_table,
                label=lin.operation_type.value,
                statement_seq=lin.statement_seq,
                column_mappings=lin.column_mappings,
            )
        )

    return Visualization(nodes=list(node_set.values()), edges=edges)
