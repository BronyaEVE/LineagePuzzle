from __future__ import annotations

import json
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..models.lineage import ColumnInfo, TableInfo, TableType


class DBConnector:
    """与 PVC 数据库交互，提供表结构信息和执行计划获取两个子模块。"""

    def __init__(self, host: str, port: int, database: str, username: str, password: str):
        url = f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database}"
        self._engine: Engine = create_engine(url, pool_pre_ping=True)

    @contextmanager
    def _connect(self):
        with self._engine.connect() as conn:
            yield conn

    # ===================== 子模块 A: 表结构信息获取 =====================

    def get_table_columns(self, schema: str = "public") -> dict[str, list[ColumnInfo]]:
        """查询 INFORMATION_SCHEMA 获取指定 schema 下所有表的列信息。

        返回 {table_name: [ColumnInfo, ...]}
        """
        with self._connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                    ORDER BY table_name, ordinal_position
                    """
                ),
                {"schema": schema},
            ).fetchall()

        result: dict[str, list[ColumnInfo]] = {}
        for table_name, col_name, data_type in rows:
            result.setdefault(table_name, []).append(
                ColumnInfo(name=col_name, type=data_type)
            )
        return result

    def get_tables_info(self, schema: str = "public") -> list[TableInfo]:
        """获取指定 schema 下所有表的完整信息。"""
        columns_map = self.get_table_columns(schema)
        tables = []
        for table_name, columns in columns_map.items():
            tables.append(
                TableInfo(
                    schema_name=schema,
                    table_name=table_name,
                    table_type=TableType.SOURCE,
                    source="database",
                    columns=columns,
                )
            )
        return tables

    def table_exists(self, table_name: str, schema: str = "public") -> bool:
        """检查表是否存在于数据库中。"""
        with self._connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = :schema AND table_name = :name
                    """
                ),
                {"schema": schema, "name": table_name},
            ).fetchone()
        return row is not None

    # ===================== 子模块 B: 执行计划获取 =====================

    def get_execution_plan(self, sql: str) -> dict:
        """对 SQL 语句执行 EXPLAIN (FORMAT JSON)，返回执行计划 JSON。

        注意：不会实际执行 DML 语句，EXPLAIN 只生成计划。
        """
        explain_sql = f"EXPLAIN (FORMAT JSON) {sql.rstrip(';')}"
        with self._connect() as conn:
            result = conn.execute(text(explain_sql)).fetchone()
        if result is None:
            return {}
        # PostgreSQL 返回的 JSON 可能是字符串
        plan_data = result[0]
        if isinstance(plan_data, str):
            return json.loads(plan_data)
        return plan_data

    def extract_tables_from_plan(self, plan_data: dict | list) -> tuple[list[str], list[str]]:
        """从执行计划 JSON 中递归提取源表和目标表。

        返回 (source_tables, target_tables)
        """
        source_tables: list[str] = []
        target_tables: list[str] = []

        if isinstance(plan_data, list):
            for item in plan_data:
                s, t = self.extract_tables_from_plan(item)
                source_tables.extend(s)
                target_tables.extend(t)
            return source_tables, target_tables

        if not isinstance(plan_data, dict):
            return source_tables, target_tables

        plan = plan_data.get("Plan", plan_data)

        # 提取表名
        node_type = plan.get("Node Type", "")
        relation_name = plan.get("Relation Name")
        # 某些节点用 Alias
        alias = plan.get("Alias")

        if relation_name:
            table = relation_name
        elif alias and node_type in ("Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan"):
            table = alias
        else:
            table = None

        if table:
            # 判断是读还是写
            if node_type in ("ModifyTable", "Insert", "Update", "Delete"):
                operation = plan.get("Operation", "").upper()
                if operation in ("INSERT", "UPDATE", "DELETE") or node_type == "ModifyTable":
                    target_tables.append(table)
                else:
                    source_tables.append(table)
            else:
                source_tables.append(table)

        # 递归处理子计划
        for sub in ("Plans", "SubPlans", "InitPlan"):
            children = plan.get(sub, [])
            if isinstance(children, list):
                for child in children:
                    s, t = self.extract_tables_from_plan(child)
                    source_tables.extend(s)
                    target_tables.extend(t)

        # 去重
        return list(dict.fromkeys(source_tables)), list(dict.fromkeys(target_tables))

    def dispose(self):
        self._engine.dispose()
