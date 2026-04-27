import re


def preprocess(script: str) -> str:
    """对 DML 脚本进行预处理：去注释、去多余空格、去空白行。

    注意：不会移除 CREATE TABLE / CREATE TEMP TABLE 语句。
    """
    # 去除多行注释 /* ... */
    text = re.sub(r"/\*.*?\*/", "", script, flags=re.DOTALL)
    # 去除单行注释 --
    text = re.sub(r"--[^\n]*", "", text)
    # 压缩连续空格（保留换行，方便后续按行处理）
    text = re.sub(r"[^\S\n]+", " ", text)
    # 去除每行首尾空白
    lines = [line.strip() for line in text.splitlines()]
    # 移除空行
    lines = [line for line in lines if line]
    return "\n".join(lines)
