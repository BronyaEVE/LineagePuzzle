"""表名归一化工具。

将表名规范化为 `schema.table` 全限定名形式，作为全局注册表的唯一主键。
裸表名（不带 schema 前缀）一律视为 public schema。

规则:
  - "orders"              → "public.orders"   （裸表名补 public）
  - "public.orders"       → "public.orders"
  - "mydb.public.orders"  → "public.orders"   （catalog 去掉，保留 schema.table）
  - "reporting.fact_sales"→ "reporting.fact_sales"（保留非 public schema）
  - '"Orders"'            → "public.Orders"   （保留大小写）
  - '"public"."Orders"'   → "public.Orders"
  - "a.b.c.d.target"      → "d.target"        （长链取最后两段作 schema.table）
  - ""                    → ""

这样设计是为了区分 public.orders 与 reporting.orders 等跨 schema 同名表，
避免在全局注册表中互相覆盖。
"""
from __future__ import annotations

DEFAULT_SCHEMA = "public"


def normalize_table_name(name: str) -> str:
    """将表名归一化为 `schema.table` 全限定名形式。

    裸表名（不含 schema 前缀）补默认 schema `public`。
    带完整前缀的取最后两段（schema.table），catalog/database 前缀被丢弃。
    """
    if not name:
        return ""

    # 去除首尾空白
    name = name.strip()

    # 按点号拆分（正确处理引号内的点号）
    parts = _split_identifier(name)

    # 去除每段的引号
    parts = [_unquote(p) for p in parts if _unquote(p)]

    if not parts:
        return ""

    # 取最后两段作为 schema.table
    if len(parts) >= 2:
        schema, table = parts[-2], parts[-1]
    else:
        schema, table = DEFAULT_SCHEMA, parts[-1]

    return f"{schema}.{table}"


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
