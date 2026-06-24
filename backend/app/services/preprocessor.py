import re


def replace_params(text: str, mapping: dict[str, str] | None = None) -> str:
    """把 SQL 里的 ${param} 占位符替换成实际值或参数名。

    sqlglot 无法解析 ${name} 这种 ETL 模板占位符（会 ParseError），
    必须在解析前替换成合法标识符。

    替换规则：
      - mapping 有该参数 → 替换成映射值（如 ${icl_schema}=ods → ods）
      - mapping 没有该参数 → 保留参数名当标识符（${icl_schema} → icl_schema）
      - 参数拼接 ${schema}_${env}.report → schema_env.report（各自替换后自然拼接）

    时间/值类参数（如 ${batch_date}）也会被替换成 batch_date，
    在 WHERE 条件里被当列名——对血缘无影响（血缘不关心 WHERE 的值）。
    """
    if not mapping:
        mapping = {}

    def repl(m: re.Match) -> str:
        name = m.group(1)
        return mapping.get(name, name)

    # \w+ 匹配参数名（字母数字下划线）；${schema}_${env} 各自匹配，拼接成单标识符
    return re.sub(r"\$\{(\w+)\}", repl, text)


def preprocess(script: str, param_mapping: dict[str, str] | None = None) -> str:
    """对 DML 脚本进行预处理：参数替换、去注释、去多余空格、去空白行。

    步骤：
      1. 替换 ${param} 占位符（必须在最前，否则后续正则可能误伤）
      2. 去除多行注释 /* ... */
      3. 去除单行注释 --
      4. 压缩空格、去空白行

    注意：不会移除 CREATE TABLE / CREATE TEMP TABLE 语句。
    """
    # 1. 替换参数占位符（${param} → 实际值或参数名）
    text = replace_params(script, param_mapping)
    # 2. 去除多行注释 /* ... */
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # 3. 去除单行注释 --
    text = re.sub(r"--[^\n]*", "", text)
    # 4. 压缩连续空格（保留换行，方便后续按行处理）
    text = re.sub(r"[^\S\n]+", " ", text)
    # 5. 去除每行首尾空白
    lines = [line.strip() for line in text.splitlines()]
    # 6. 移除空行
    lines = [line for line in lines if line]
    return "\n".join(lines)
