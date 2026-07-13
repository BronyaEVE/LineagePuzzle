"""端到端血缘对照测试。

跟其他测试文件的区别：
  - test_lineage_extractor.py / test_column_lineage.py 测的是单元层（单条 SQL）的输出，
    输入是手工构造的 Statement 对象，绕过了 preprocess/split。
  - 本文件测的是「完整脚本 → analyze() → 端到端结果」，验证整条链路：
    preprocess + split + AST 提取 + 列级解析 串联后，
    源表 / 中间表 / 目标表 / 节点分类 / 列级映射 是否都符合预期。

  本文件覆盖此前缺少端到端对照的场景：
    - CASE WHEN INSERT（含列级映射）
    - 跨 schema + ${param} 真实脚本
    - 事务包裹（BEGIN...COMMIT）
    - DO $$...$$ 匿名块（生产脚本常见）
    - 完整链路：源 → 临时表 → 目标
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analyzer import analyze


# ============================================================
# 工具：把 Lineage 列表转成 (src, tgt) 集合，便于对照
# ============================================================

def _pairs(lineages) -> set[tuple[str, str]]:
    """提取所有非空 source 的 (src, tgt) 对"""
    return {(l.source_table, l.target_table) for l in lineages if l.source_table}


def _mappings_by_target(lineage) -> dict[str, set]:
    """把一个 lineage 的 column_mappings 整理成 {target_col: {(src_table, *src_cols)}}"""
    out = {}
    for m in lineage.column_mappings:
        key = (m.source_table, tuple(sorted(m.source_columns)))
        out.setdefault(m.target_column, set()).add(key)
    return out


# ============================================================
# CASE WHEN 端到端对照
# ============================================================

class TestCaseWhenE2E:
    """CASE WHEN 的端到端血缘对照（这是本次回归 bug 的核心场景）"""

    def test_case_when_insert_source_table(self):
        """CASE WHEN 的 INSERT 必须正确识别源表，不能只剩目标表"""
        sql = (
            "INSERT INTO report (label) "
            "SELECT CASE WHEN s.status = 1 THEN 'paid' ELSE 'unpaid' END AS label "
            "FROM source_t s;"
        )
        result = analyze(sql, None)

        # 关键断言：必须有源表 → 目标表的边（bug 现象是只剩目标表）
        assert ("public.source_t", "public.report") in _pairs(result.lineages), \
            f"CASE WHEN 丢了源表! pairs={_pairs(result.lineages)}"

    def test_case_when_column_mapping(self):
        """CASE WHEN 的列级映射应包含 CASE 引用的所有源列"""
        sql = (
            "INSERT INTO report (label) "
            "SELECT CASE WHEN s.status = 1 THEN 'paid' ELSE 'unpaid' END AS label "
            "FROM source_t s;"
        )
        result = analyze(sql, None)
        assert len(result.lineages) == 1
        lin = result.lineages[0]

        # CASE WHEN s.status 中的 status 应映射到 label
        by_target = _mappings_by_target(lin)
        assert "label" in by_target
        sources = by_target["label"]
        # 源列 status 必须映射到 public.source_t
        assert any(t == "public.source_t" and "status" in cols
                   for t, cols in sources), f"CASE 列映射错: {sources}"

    def test_multiple_case_when_all_sources(self):
        """多个 CASE WHEN 的 INSERT：所有 CASE 的源列都要识别（用户真实场景）"""
        sql = (
            "INSERT INTO target_t (a, b) "
            "SELECT "
            "  CASE WHEN s.x = 1 THEN s.v1 ELSE s.v2 END AS a, "
            "  CASE WHEN s.y = 2 THEN s.v3 ELSE s.v4 END AS b "
            "FROM source_t s;"
        )
        result = analyze(sql, None)
        assert ("public.source_t", "public.target_t") in _pairs(result.lineages)

        # 两个 CASE 的所有源列 v1,v2,v3,v4 都应在列级映射中
        all_src_cols = set()
        for lin in result.lineages:
            for m in lin.column_mappings:
                all_src_cols.update(m.source_columns)
        assert {"v1", "v2", "v3", "v4"} <= all_src_cols, \
            f"CASE 列映射不完整: {all_src_cols}"

    def test_case_when_with_line_breaks(self):
        """CASE 的 END 换行顶格写（真实 ETL 习惯）—— END 不能被切断"""
        sql = (
            "INSERT INTO t (lbl)\n"
            "SELECT\n"
            "  CASE WHEN s.x = 1 THEN 'a'\n"
            "  ELSE 'b'\n"
            "  END AS lbl\n"
            "FROM src s;"
        )
        result = analyze(sql, None)
        # 关键：FROM src 不能被 END 切断
        assert ("public.src", "public.t") in _pairs(result.lineages), \
            "CASE 的 END 换行被切断，FROM 丢失!"


# ============================================================
# 跨 schema + ${param} 真实脚本
# ============================================================

class TestCrossSchemaParamScript:
    """模拟生产真实脚本：${schema} 占位符 + 跨 schema 引用"""

    def test_param_schema_resolution(self):
        """${icl_schema}.t / ${iol_schema}.s 应正确替换为参数名作 schema"""
        # 注意：analyze 会读 store.get_param_mapping()，测试环境可能残留映射，
        # 所以用未配置过的参数名（无映射时 replace_params 保留参数名本身当标识符）
        sql = (
            "INSERT INTO ${fresh_schema_a}.target_t (id) "
            "SELECT id FROM ${fresh_schema_b}.source_t;"
        )
        result = analyze(sql, None)
        # 两个不同 schema 的表都要识别（无映射时参数名作为 schema 名）
        pairs = _pairs(result.lineages)
        # 源表 schema 不等于目标表 schema（证明两个 ${} 分别解析）
        for src, tgt in pairs:
            assert src.startswith("fresh_schema_b.")
            assert tgt.startswith("fresh_schema_a.")

    def test_full_cross_schema_chain_with_case_when(self):
        """完整链路：${schema} + 临时表 + CASE WHEN"""
        sql = (
            "CREATE TEMP TABLE ${s}.tmp AS "
            "SELECT t.id, CASE WHEN t.cur='CNY' THEN t.amt ELSE 0 END AS cny "
            "FROM ${s}.raw t;\n"
            "INSERT INTO ${s}.rpt (id, amount) "
            "SELECT id, cny FROM ${s}.tmp;"
        )
        result = analyze(sql, None)
        pairs = _pairs(result.lineages)
        # 临时表链路：raw → tmp → rpt
        assert ("s.raw", "s.tmp") in pairs
        assert ("s.tmp", "s.rpt") in pairs

        # 节点类型分类正确
        node_types = {n.id: n.type for n in result.visualization.nodes}
        assert node_types.get("s.raw") == "source"
        assert node_types.get("s.tmp") == "intermediate"
        assert node_types.get("s.rpt") == "target"


# ============================================================
# 事务包裹（BEGIN...COMMIT）
# ============================================================

class TestTransactionWrappedE2E:
    """事务包裹脚本的端到端血缘对照"""

    def test_begin_commit_preserves_lineage(self):
        """BEGIN;...COMMIT; 包裹的 DML 血缘不能丢"""
        sql = (
            "BEGIN;\n"
            "INSERT INTO t SELECT * FROM src;\n"
            "COMMIT;"
        )
        result = analyze(sql, None)
        assert ("public.src", "public.t") in _pairs(result.lineages)

    def test_transaction_multi_dml(self):
        """事务内多条 DML 全部保留，血缘数量正确"""
        sql = (
            "BEGIN;\n"
            "INSERT INTO t1 SELECT * FROM s1;\n"
            "INSERT INTO t2 SELECT * FROM s2;\n"
            "COMMIT;"
        )
        result = analyze(sql, None)
        pairs = _pairs(result.lineages)
        assert ("public.s1", "public.t1") in pairs
        assert ("public.s2", "public.t2") in pairs

    def test_transaction_with_case_when(self):
        """事务内 CASE WHEN（两个特性叠加不能互相破坏）"""
        sql = (
            "BEGIN;\n"
            "INSERT INTO r (lbl) "
            "SELECT CASE WHEN s.x=1 THEN 'a' ELSE 'b' END AS lbl FROM src s;\n"
            "COMMIT;"
        )
        result = analyze(sql, None)
        assert ("public.src", "public.r") in _pairs(result.lineages)


# ============================================================
# DO $$...$$ 匿名块
# ============================================================

class TestDoBlockE2E:
    """DO block 端到端对照（生产脚本核心场景）"""

    def test_do_block_with_exception_lineage(self):
        """DO $$ BEGIN ... EXCEPTION ... END $$ 内的 DML 必须有血缘"""
        sql = (
            "DO $$\n"
            "BEGIN\n"
            "  INSERT INTO t (a) SELECT id FROM src;\n"
            "EXCEPTION WHEN OTHERS THEN\n"
            "  RAISE NOTICE 'sqlstate:%', sqlstate;\n"
            "END\n"
            "$$;"
        )
        result = analyze(sql, None)
        # 关键：DML 血缘必须生成，不能被 EXCEPTION 吞掉
        assert ("public.src", "public.t") in _pairs(result.lineages), \
            f"DO block 内 DML 血缘丢失! pairs={_pairs(result.lineages)}"

    def test_do_block_case_when_preserved(self):
        """DO block 内的 CASE WHEN...END 必须完整，不能被当作块 END"""
        sql = (
            "DO $$\n"
            "BEGIN\n"
            "  INSERT INTO r (lbl) "
            "  SELECT CASE WHEN s.x=1 THEN 'a' ELSE 'b' END AS lbl "
            "  FROM src s;\n"
            "END\n"
            "$$;"
        )
        result = analyze(sql, None)
        assert ("public.src", "public.r") in _pairs(result.lineages)

    def test_mixed_bare_sql_and_do_block(self):
        """生产真实场景：裸 SQL + DO block 混合，所有 DML 血缘都要保留"""
        sql = (
            "INSERT INTO a SELECT * FROM s1;\n"
            "DO $$\n"
            "BEGIN\n"
            "  INSERT INTO b SELECT * FROM s2;\n"
            "EXCEPTION WHEN OTHERS THEN\n"
            "  RAISE NOTICE 'e';\n"
            "END\n"
            "$$;\n"
            "INSERT INTO c SELECT * FROM s3;"
        )
        result = analyze(sql, None)
        pairs = _pairs(result.lineages)
        assert ("public.s1", "public.a") in pairs
        assert ("public.s2", "public.b") in pairs
        assert ("public.s3", "public.c") in pairs


# ============================================================
# 完整链路：源 → 临时表 → 目标 + 列级映射
# ============================================================

class TestFullChainE2E:
    """端到端：完整数据流转链路 + 表类型分类 + 列级映射三重对照"""

    def test_two_hop_chain_node_classification(self):
        """源 → 中间 → 目标，节点类型必须正确分类"""
        sql = (
            "CREATE TEMP TABLE tmp AS SELECT id, amount FROM orders;\n"
            "INSERT INTO report (order_id, total) SELECT id, amount FROM tmp;"
        )
        result = analyze(sql, None)

        # 表级链路
        pairs = _pairs(result.lineages)
        assert ("public.orders", "public.tmp") in pairs
        assert ("public.tmp", "public.report") in pairs

        # 节点类型
        types = {n.id: n.type for n in result.visualization.nodes}
        assert types["public.orders"] == "source"
        assert types["public.tmp"] == "intermediate"
        assert types["public.report"] == "target"

    def test_two_hop_chain_column_passthrough(self):
        """两跳链路的列级映射：列应能追溯到第一跳的源表"""
        sql = (
            "CREATE TEMP TABLE tmp AS SELECT id, amount FROM orders;\n"
            "INSERT INTO report (order_id, total) SELECT id, amount FROM tmp;"
        )
        result = analyze(sql, None)

        # 第二跳：report.order_id <- tmp.id, report.total <- tmp.amount
        second_hop = [l for l in result.lineages
                      if l.target_table == "public.report" and l.source_table == "public.tmp"][0]
        by_tgt = _mappings_by_target(second_hop)
        assert by_tgt["order_id"] == {("public.tmp", ("id",))}
        assert by_tgt["total"] == {("public.tmp", ("amount",))}

    def test_join_two_sources_to_one_target(self):
        """JOIN 双源表：两条边都要生成"""
        sql = (
            "INSERT INTO summary (oid, cust) "
            "SELECT o.id, c.name FROM orders o JOIN customers c ON o.cid = c.id;"
        )
        result = analyze(sql, None)
        pairs = _pairs(result.lineages)
        assert ("public.orders", "public.summary") in pairs
        assert ("public.customers", "public.summary") in pairs

        # 列级映射各归各的源表
        for lin in result.lineages:
            if lin.source_table == "public.orders":
                by_tgt = _mappings_by_target(lin)
                assert by_tgt["oid"] == {("public.orders", ("id",))}
            elif lin.source_table == "public.customers":
                by_tgt = _mappings_by_target(lin)
                assert by_tgt["cust"] == {("public.customers", ("name",))}
