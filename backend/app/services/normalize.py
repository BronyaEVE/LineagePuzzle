"""表名归一化工具。

处理 schema/database 前缀，确保 "public.orders"、"mydb.public.orders" 和 "orders"
在全局注册表中被视为同一张表。
"""
from __future__ import annotations

import re


def normalize_table_name(name: str) -> str:
    """将表名归一化为不含 schema/catalog 前缀的纯表名。

    规则:
      - "orders"              → "orders"
      - "public.orders"       → "orders"
      - "mydb.public.orders"  → "orders"
      - '"Public"."Orders"'   → "Orders"   （带引号的标识符，保留大小写）
      -空字符串               → ""

    始终返回最后一部分（即实际的表名），并去除引号。
    """
    if not name:
        return ""

    # 去除首尾空白
    name = name.strip()

    # 按点号拆分（处理 catalog.schema.table 格式）
    # 需要处理引号内的点号，如 "my.schema".table
    parts = _split_identifier(name)

    # 取最后一部分作为表名
    table_part = parts[-1] if parts else name

    # 去除引号
    table_part = _unquote(table_part)

    return table_part


def _split_identifier(name: str) -> list[str]:
    """按点号拆分标识符，正确处理引号内的点号。

    例: 'mydb."public.schema".orders' → ['mydb', '"public.schema"', 'orders']
    """
    parts: list[str] = []
    current = []
    in_quotes = False

    for ch in name:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif ch == '.' and not in_quotes:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)

    if current:
        parts.append(''.join(current))

    return parts


def _unquote(identifier: str) -> str:
    """去除 SQL 标识符两侧的引号。

    '"Orders"' → 'Orders'
    'orders'   → 'orders'
    """
    if len(identifier) >= 2 and identifier[0] == '"' and identifier[-1] == '"':
        return identifier[1:-1]
    return identifier
