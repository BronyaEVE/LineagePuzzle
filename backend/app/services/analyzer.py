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


def analyze(script: str, db_config: DatabaseConfig) -> AnalysisResult:
    """完整分析编排：预处理 → 拆分 → 数据库连接 → 血缘提取 → 结果组装。"""

    # 步骤1+2: 预处理和拆分
    cleaned = preprocess(script)
    group = split_statements(cleaned, original_script=script)

    # 步骤3: 连接数据库
    db: DBConnector | None = None
    execution_plans: dict[int, dict] = {}
    db_tables: list[TableInfo] = []

    try:
        db = DBConnector(
            host=db_config.host,
            port=db_config.port,
            database=db_config.database,
            username=db_config.username,
            password=db_config.password,
        )

        # 子模块 A: 获取表结构
        db_tables = db.get_tables_info()

        # 子模块 B: 获取执行计划
        for stmt in group.statements:
            if stmt.type.value in ("INSERT", "UPDATE", "DELETE", "MERGE"):
                try:
                    plan = db.get_execution_plan(stmt.text)
                    if plan:
                        execution_plans[stmt.seq] = plan
                except Exception:
                    pass  # 执行计划获取失败不影响整体流程
    except Exception:
        pass  # 数据库连接失败时，仍可通过静态解析进行基本分析
    finally:
        if db:
            db.dispose()

    # 步骤4: 提取血缘关系
    lineages, table_type_map = extract_lineages(group.statements, execution_plans)

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
            )
        )

    return Visualization(nodes=list(node_set.values()), edges=edges)
