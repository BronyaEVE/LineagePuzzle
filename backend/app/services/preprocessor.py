import re


# PL/pgSQL 控制结构关键字 —— DO block 内部这些行不是 DML，需在提取时丢弃
# （IF/LOOP/FOR/WHILE 等流程控制内的 DML 仍可能被保留，但绝大多数生产脚本只在
#   直线流程里写 DML，足够覆盖）
_PL_CONTROL_KEYWORDS = re.compile(
    r"^\s*(BEGIN|END|EXCEPTION|WHEN|THEN|RAISE|IF|THEN|ELSE|ELSIF|LOOP|FOR|WHILE|"
    r"RETURN|PERFORM|EXECUTE|DECLARE|LANGUAGE|NULL)\b",
    re.IGNORECASE,
)

# 匹配 DO $$...$$ / DO $tag$...$tag$  —— PostgreSQL 匿名块（dollar-quote）
# 用反向引用 \1 确保开头和结尾的 tag 一致（$$ 或 $body$ 等）
_DO_BLOCK_PATTERN = re.compile(
    r"DO\s+(\$\w*\$)([\s\S]*?)\1\s*;",
    re.IGNORECASE,
)


def extract_dml_from_do_blocks(text: str) -> str:
    """把 DO $$ ... $$ 匿名块替换成内部的 DML 语句。

    生产脚本常用 DO $$ BEGIN ... EXCEPTION WHEN OTHERS THEN RAISE ... END $$;
    包裹 DML 做异常处理。sqlglot 无法解析 PL/pgSQL（降级为 Command，表血缘丢失）。

    做法：用 dollar-quote 边界把 DO block 内容抠出来，按行过滤掉
    PL/pgSQL 控制关键字（BEGIN/END/EXCEPTION/RAISE 等），只保留真正的 DML。
    这样后续 splitter / lineage_extractor 像处理裸 SQL 一样处理它们。

    局限：EXECUTE 'INSERT...' 这种动态 SQL 内的表名是运行时拼接的，
    静态分析无法识别（EXECUTE 行会被丢弃）。生产脚本绝大多数是静态 DML。

    支持 $$ 和 $tag$（如 $body$、$func$）两种 dollar-quote 形式。
    """
    def repl(m: re.Match) -> str:
        body = m.group(2)
        kept: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _PL_CONTROL_KEYWORDS.match(line):
                continue
            kept.append(stripped)
        return "\n".join(kept)

    return _DO_BLOCK_PATTERN.sub(repl, text)


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
    """对 DML 脚本进行预处理：参数替换、去注释、DO block 提取、事务关键字补分号、去多余空格、去空白行。

    步骤：
      1. 替换 ${param} 占位符（必须在最前，否则后续正则可能误伤）
      2. 去除多行注释 /* ... */
      3. 去除单行注释 --
      4. 从 DO $$...$$ 匿名块提取内部 DML（去掉 PL/pgSQL 控制结构）
      5. 给行首事务关键字（BEGIN/START TRANSACTION/COMMIT/ROLLBACK）补分号，
         避免裸 BEGIN 无分号时把后续 DML 粘进同一段被 splitter 丢弃
      6. 压缩空格、去空白行

    注意：不会移除 CREATE TABLE / CREATE TEMP TABLE 语句。
    注意：不碰 END 关键字。END 在 SQL 中既是 CASE WHEN...END 的表达式结束符，
    也可能是事务块/过程块结束符，纯正则无法区分。曾经尝试剥离行首 END 导致
    所有 CASE...END 被插入分号切断（CASE 表达式常用换行书写，END 顶格）。
    PostgreSQL 事务用 BEGIN...COMMIT 闭合，不依赖 END，故不需要处理 END。
    """
    # 1. 替换参数占位符（${param} → 实际值或参数名）
    text = replace_params(script, param_mapping)
    # 2. 去除多行注释 /* ... */
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # 3. 去除单行注释 --
    text = re.sub(r"--[^\n]*", "", text)
    # 4. 从 DO $$...$$ 匿名块提取 DML（去掉外壳 + PL/pgSQL 控制关键字）
    text = extract_dml_from_do_blocks(text)
    # 5. 给行首事务关键字补分号（裸 BEGIN 无分号时，避免把后续 DML 粘进同一段被 _should_keep 丢弃）
    #    不碰 END —— END 在 CASE WHEN...END 中合法，误补分号会切断 CASE 表达式
    text = re.sub(
        r"(?im)^(?=\s*(?:BEGIN(?:\s+TRANSACTION)?|START\s+TRANSACTION|COMMIT|ROLLBACK)\b)([^;\n]*)$",
        lambda m: m.group(1) if ";" in m.group(1) else m.group(1).rstrip() + ";",
        text,
    )
    # 6. 压缩连续空格（保留换行，方便后续按行处理）
    text = re.sub(r"[^\S\n]+", " ", text)
    # 7. 去除每行首尾空白
    lines = [line.strip() for line in text.splitlines()]
    # 8. 移除空行
    lines = [line for line in lines if line]
    return "\n".join(lines)
