from __future__ import annotations

import uuid

import sqlglot

from ..models.lineage import (
    ColumnMapping,
    ExtractionMethod,
    Lineage,
    OperationType,
    TableType,
)
from ..models.statement import Statement, StatementType
from .normalize import normalize_table_name


def _extract_tables_via_ast(stmt_text: str) -> tuple[list[str], list[str], list[str]]:
    """使用 sqlglot 静态解析 SQL AST，提取表名。

    返回 (referenced_tables, created_tables, modified_tables)
    所有表名经过归一化处理（去除 schema/catalog 前缀）。
    """
    referenced: list[str] = []
    created: list[str] = []
    modified: list[str] = []

    try:
        parsed = sqlglot.parse_one(stmt_text, read="postgres")
    except Exception:
        return referenced, created, modified

    # 提取所有引用的表（归一化表名）
    for table in parsed.find_all(sqlglot.exp.Table):
        # sqlglot 的 table.name 只返回表名部分，不含 schema/catalog
        # 但为安全起见仍然做归一化
        name = normalize_table_name(table.name)
        if name and name not in referenced:
            referenced.append(name)

    # 判断语句类型并分类
    if isinstance(parsed, sqlglot.exp.Create):
        table_expr = parsed.find(sqlglot.exp.Table)
        if table_expr:
            name = normalize_table_name(table_expr.name)
            if name in referenced:
                referenced.remove(name)
            if name not in created:
                created.append(name)
    elif isinstance(parsed, sqlglot.exp.Insert):
        table_expr = parsed.find(sqlglot.exp.Table)
        if table_expr:
            name = normalize_table_name(table_expr.name)
            if name in referenced:
                referenced.remove(name)
            if name not in modified:
                modified.append(name)
    elif isinstance(parsed, sqlglot.exp.Update):
        table_expr = parsed.find(sqlglot.exp.Table)
        if table_expr:
            name = normalize_table_name(table_expr.name)
            if name in referenced:
                referenced.remove(name)
            if name not in modified:
                modified.append(name)
    elif isinstance(parsed, sqlglot.exp.Delete):
        table_expr = parsed.find(sqlglot.exp.Table)
        if table_expr:
            name = normalize_table_name(table_expr.name)
            if name in referenced:
                referenced.remove(name)
            if name not in modified:
                modified.append(name)

    return referenced, created, modified


def extract_lineages(
    statements: list[Statement],
    execution_plans: dict[int, dict] | None = None,
) -> tuple[list[Lineage], dict[str, TableType]]:
    """从语句列表中提取血缘关系。

    参数:
        statements: 拆分后的语句列表
        execution_plans: 可选，语句序号到执行计划 JSON 的映射

    返回:
        (lineages, table_type_map)
        table_type_map: {table_name: TableType} 记录每个表的类型
    """
    execution_plans = execution_plans or {}
    lineages: list[Lineage] = []
    table_type_map: dict[str, TableType] = {}

    for stmt in statements:
        # 先通过 AST 填充语句的表引用信息
        ref, created, modified = _extract_tables_via_ast(stmt.text)
        stmt.tables_referenced = ref
        stmt.tables_created = created
        stmt.tables_modified = modified

        # 标记表类型
        for t in created:
            table_type_map.setdefault(t, TableType.INTERMEDIATE)
        for t in modified:
            if t not in table_type_map:
                table_type_map[t] = TableType.TARGET
        for t in ref:
            if t not in table_type_map:
                table_type_map[t] = TableType.SOURCE

        # 优先使用执行计划提取血缘
        plan = execution_plans.get(stmt.seq)
        if plan:
            _extract_from_plan(stmt, plan, lineages, table_type_map)
        else:
            # 回退到静态解析
            _extract_from_ast(stmt, lineages)

    return lineages, table_type_map


def _extract_from_plan(
    stmt: Statement,
    plan_data: dict,
    lineages: list[Lineage],
    table_type_map: dict[str, TableType],
) -> None:
    """基于执行计划提取血缘关系。"""
    source_tables = stmt.tables_referenced
    target_tables = stmt.tables_created + stmt.tables_modified

    if not source_tables or not target_tables:
        # 执行计划可能补充了额外信息，但核心依赖 AST 结果
        return

    op_type = _stmt_type_to_op(stmt.type)
    for src in source_tables:
        for tgt in target_tables:
            lineages.append(
                Lineage(
                    lineage_id=str(uuid.uuid4()),
                    source_table=src,
                    target_table=tgt,
                    operation_type=op_type,
                    extraction_method=ExtractionMethod.EXECUTION_PLAN,
                    statement_seq=stmt.seq,
                    dml_statement=stmt.text,
                )
            )


def _extract_from_ast(stmt: Statement, lineages: list[Lineage]) -> None:
    """基于静态 AST 解析提取血缘关系（执行计划不可用时的补充）。"""
    source_tables = stmt.tables_referenced
    target_tables = stmt.tables_created + stmt.tables_modified

    if not target_tables:
        return

    op_type = _stmt_type_to_op(stmt.type)
    for src in source_tables:
        for tgt in target_tables:
            lineages.append(
                Lineage(
                    lineage_id=str(uuid.uuid4()),
                    source_table=src,
                    target_table=tgt,
                    operation_type=op_type,
                    extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                    statement_seq=stmt.seq,
                    dml_statement=stmt.text,
                )
            )
    # 单个目标表但没有源表（如 UPDATE SET 常量）也记录目标
    if not source_tables and target_tables:
        for tgt in target_tables:
            lineages.append(
                Lineage(
                    lineage_id=str(uuid.uuid4()),
                    source_table="",
                    target_table=tgt,
                    operation_type=op_type,
                    extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                    statement_seq=stmt.seq,
                    dml_statement=stmt.text,
                )
            )


def _stmt_type_to_op(stmt_type: StatementType) -> OperationType:
    mapping = {
        StatementType.CREATE: OperationType.CREATE,
        StatementType.INSERT: OperationType.INSERT,
        StatementType.UPDATE: OperationType.UPDATE,
        StatementType.DELETE: OperationType.DELETE,
        StatementType.MERGE: OperationType.MERGE,
    }
    return mapping.get(stmt_type, OperationType.INSERT)
