"""列级血缘提取（v2.1）。

基于 sqlglot AST 静态解析，从 DML 语句中提取「目标列 ← 源列」的映射。
与表级血缘解耦：表级血缘照常生成（保底），列级是增强层。
SELECT * 等无法解析的构造降级为空 column_mappings（不影响表级边）。

能力边界（详见 DESIGN.v2 §6.4）：
  ✅ 显式列 INSERT INTO t(a,b) SELECT x,y
  ✅ JOIN + 别名  o.id, c.name
  ✅ 聚合/表达式  SUM(amount), price*qty
  ✅ CTAS         CREATE TABLE t AS SELECT a,b
  ✅ 子查询       SELECT ... FROM (SELECT ...) sub
  ⚠️ 无显式目标列  target 退化用 projection 列名/别名
  ❌ SELECT *     无表结构，降级（留空 column_mappings）
  ❌ CTE 列定义展开  source_table 标记为 cte 名，不递归
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

from ..models.lineage import ColumnMapping
from ..models.statement import Statement


def _qualified_name_from_table(table_expr: exp.Table) -> str:
    """复用 lineage_extractor 的全限定名重建逻辑（避免循环 import）。

    sqlglot 的 table.name 只返回纯表名，schema 在 table.db。
    db 为空时裸表名补 public。
    """
    from .normalize import normalize_table_name

    table_name = table_expr.name
    schema = table_expr.db
    raw = f"{schema}.{table_name}" if schema else table_name
    return normalize_table_name(raw)


def _build_alias_map(parsed: exp.Expression) -> dict[str, str]:
    """构建 {alias 或表名 → 全限定表名} 映射。

    用于把 SELECT projection 里的 column.table（可能是别名）解析回全限定表名。
    - 带 alias 的表: {alias: qualified_name}（如 o → public.orders）
    - 无 alias 的表: {name: qualified_name}
    """
    mapping: dict[str, str] = {}
    for t in parsed.find_all(exp.Table):
        qname = _qualified_name_from_table(t)
        if t.alias:
            mapping[t.alias] = qname
        else:
            mapping[t.name] = qname
    return mapping


def _get_target_table_and_columns(parsed: exp.Expression) -> tuple[str, list[str]]:
    """提取目标表全限定名 + 目标列名列表。

    INSERT INTO t (a,b,c): 从 Schema.expressions（Identifier 列表）取目标列
    INSERT INTO t (无显式列): 返回空列表，后续用 projection 列名/别名对齐
    CREATE TABLE t AS SELECT: 目标列 = projection 列名（CTAS 无显式列声明）
    UPDATE t SET: 单独处理，这里返回 (表名, [])

    返回 (qualified_target_table, [target_col_names])
    """
    target_table = ""
    target_cols: list[str] = []

    if isinstance(parsed, exp.Insert):
        # INSERT 的 this 通常是 Schema（带列声明）或 Table（不带）
        target = parsed.this
        if isinstance(target, exp.Schema):
            # Schema 包裹一个 Table + 列声明
            tbl = target.find(exp.Table)
            if tbl:
                target_table = _qualified_name_from_table(tbl)
            for e in target.expressions:
                if isinstance(e, (exp.Identifier, exp.Column)):
                    target_cols.append(e.name)
        elif isinstance(target, exp.Table):
            target_table = _qualified_name_from_table(target)
            # 无显式列，target_cols 留空
    elif isinstance(parsed, exp.Create):
        tbl = parsed.find(exp.Table)
        if tbl:
            target_table = _qualified_name_from_table(tbl)
        # CTAS 目标列 = projection 列名，留空让调用方用 projection 对齐
    elif isinstance(parsed, exp.Update):
        tbl = parsed.this if isinstance(parsed.this, exp.Table) else parsed.find(exp.Table)
        if isinstance(tbl, exp.Table):
            target_table = _qualified_name_from_table(tbl)

    return target_table, target_cols


def _is_star_projection(proj: exp.Expression) -> bool:
    """判断 projection 是否为 SELECT *（含 t.*）。"""
    if isinstance(proj, exp.Star):
        return True
    # t.* 形式
    if isinstance(proj, exp.Column) and isinstance(proj.this, exp.Star):
        return True
    return False


def _projection_alias_or_name(proj: exp.Expression) -> str:
    """projection 无显式目标列对齐时，用它的别名或列名作 target。"""
    if hasattr(proj, "alias") and proj.alias:
        return proj.alias
    if isinstance(proj, exp.Column):
        return proj.name
    return proj.sql()


def _extract_column_mappings_select(
    parsed: exp.Expression,
    target_table: str,
    target_cols: list[str],
    alias_map: dict[str, str],
) -> list[ColumnMapping]:
    """从 INSERT/CTAS 的 SELECT 部分提取列级映射。

    按位置对齐 target_cols[i] ← projection[i]。
    无显式目标列时，target 用 projection 的列名/别名。
    """
    sel = parsed.find(exp.Select)
    if not sel:
        return []

    # 单表无别名时（SELECT x FROM src），列的 table 属性为空，
    # 需要回退到该 SELECT 唯一的物理源表。
    # candidate_sources = alias_map 中排除目标表后的物理表
    candidate_sources = [v for k, v in alias_map.items() if v != target_table]
    single_source = candidate_sources[0] if len(candidate_sources) == 1 else ""

    projections = sel.expressions
    mappings: list[ColumnMapping] = []

    for i, proj in enumerate(projections):
        # SELECT * → 无法解析，跳过（降级为表级）
        if _is_star_projection(proj):
            continue

        # 确定目标列名
        if i < len(target_cols):
            tgt_col = target_cols[i]
        else:
            tgt_col = _projection_alias_or_name(proj)

        # 判断是否纯列引用（无 transform）
        is_simple = isinstance(proj, exp.Column)
        transform = None if is_simple else proj.sql()

        # 找 projection 引用的所有源列
        source_cols = list(proj.find_all(exp.Column))
        if not source_cols:
            # 常量 projection（如 SELECT 1, 'x'），无源列
            mappings.append(ColumnMapping(
                target_table=target_table,
                target_column=tgt_col,
                source_table="",
                source_columns=[],
                transformation=transform,
            ))
            continue

        # 按源表分组：同一表的列合并到一条 mapping
        by_table: dict[str, list[str]] = {}
        for c in source_cols:
            tbl_alias = c.table  # 可能是别名 o、表名 orders、或空
            if tbl_alias:
                resolved = alias_map.get(tbl_alias, tbl_alias)
            elif single_source:
                # 无别名前缀 + 单源表 → 回退到唯一源表
                resolved = single_source
            else:
                resolved = ""
            by_table.setdefault(resolved, []).append(c.name)

        for src_table, cols in by_table.items():
            mappings.append(ColumnMapping(
                target_table=target_table,
                target_column=tgt_col,
                source_table=src_table,
                source_columns=cols,
                transformation=transform,
            ))

    return mappings


def _extract_column_mappings_update(
    parsed: exp.Update,
    target_table: str,
    alias_map: dict[str, str],
) -> list[ColumnMapping]:
    """从 UPDATE SET 子句提取列级映射。

    SET total = total * 1.1:
      - total（左）= 目标列
      - total * 1.1（右表达式）的源列 = [total]
      - transformation = total * 1.1
    SET status = 'paid':
      - status = 目标列，源列为空（常量），transformation = 'paid'
    """
    mappings: list[ColumnMapping] = []
    set_expr = parsed.args.get("expressions")  # SET 子句是 EQ 表达式列表
    if not set_expr:
        return mappings

    for eq in set_expr:
        if not isinstance(eq, exp.EQ):
            continue
        # eq.this 是左操作数（被赋值的列），eq.expression 是右表达式
        left = eq.this
        right = eq.expression
        if not isinstance(left, exp.Column):
            continue
        tgt_col = left.name

        source_cols = list(right.find_all(exp.Column))
        is_simple = isinstance(right, exp.Column)
        transform = None if is_simple else right.sql()

        if not source_cols:
            mappings.append(ColumnMapping(
                target_table=target_table,
                target_column=tgt_col,
                source_table="",
                source_columns=[],
                transformation=transform,
            ))
        else:
            by_table: dict[str, list[str]] = {}
            for c in source_cols:
                resolved = alias_map.get(c.table, "") if c.table else ""
                by_table.setdefault(resolved, []).append(c.name)
            for src_table, cols in by_table.items():
                mappings.append(ColumnMapping(
                    target_table=target_table,
                    target_column=tgt_col,
                    source_table=src_table,
                    source_columns=cols,
                    transformation=transform,
                ))

    return mappings


def extract_column_mappings(stmt: Statement) -> list[ColumnMapping]:
    """从单条 DML 语句提取列级血缘映射。

    入口函数。无法解析的语句返回空列表（降级为表级血缘，不影响保底）。
    """
    try:
        parsed = sqlglot.parse_one(stmt.text, read="postgres")
    except Exception:
        return []

    alias_map = _build_alias_map(parsed)
    target_table, target_cols = _get_target_table_and_columns(parsed)

    if not target_table:
        return []

    if isinstance(parsed, exp.Update):
        return _extract_column_mappings_update(parsed, target_table, alias_map)

    return _extract_column_mappings_select(parsed, target_table, target_cols, alias_map)
