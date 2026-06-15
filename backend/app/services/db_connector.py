from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..models.lineage import ColumnInfo, TableInfo, TableType


class DBConnector:
    """与 PostgreSQL 数据库交互，仅用于表结构校验与列信息补充。

    DESIGN.v2 §5.4：本模块不执行 EXPLAIN 来提取血缘，血缘提取统一走
    sqlglot AST（见 lineage_extractor）。DB 连接仅提供：
      - 表是否存在（INFORMATION_SCHEMA.TABLES）
      - 列信息补充（INFORMATION_SCHEMA.COLUMNS）
    """

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

    def dispose(self):
        self._engine.dispose()
