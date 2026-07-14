#!/usr/bin/env python
"""血缘图谱复杂度分析工具。

用法：
  # 方式1：分析导出的 JSON 文件
  python analyze_complexity.py export.json

  # 方式2：直接分析当前 data 目录（无需导出）
  python analyze_complexity.py

  # 方式3：指定 data 目录路径
  python analyze_complexity.py --data /path/to/data

输出指标：
  - 基础规模：节点数、边数、脚本数
  - 密度指标：平均度数、最大度数、密度
  - 拓扑结构：孤立子图数、是否有环、最大链路深度
  - 枢纽节点：入度/出度 Top 10（改这些表影响最大）
  - 复杂结构：菱形依赖数、多源汇聚节点
  - 分层统计：source / intermediate / target 各多少
"""
import sys
import os
import json
from pathlib import Path
from collections import Counter

import networkx as nx


def load_graph_from_export(export_path: str) -> tuple[nx.DiGraph, dict]:
    """从导出的 JSON 加载图。"""
    with open(export_path, encoding="utf-8") as f:
        data = json.load(f)
    G = nx.DiGraph()
    tables = data.get("tables", {})
    for table_name in tables:
        G.add_node(table_name)
    for edge in data.get("edges", []):
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src and tgt:
            G.add_edge(src, tgt, **{k: v for k, v in edge.items() if k in ("operation", "script_id", "statement_seq")})
    meta = {
        "script_count": len(data.get("scripts", {})),
        "version": data.get("version", "?"),
    }
    return G, meta


def load_graph_from_data(data_dir: str) -> tuple[nx.DiGraph, dict]:
    """直接从 data 目录加载（无需导出）。"""
    data_path = Path(data_dir)
    tables_file = data_path / "tables.json"
    edges_file = data_path / "edges.jsonl"
    scripts_dir = data_path / "scripts"

    G = nx.DiGraph()
    if tables_file.exists():
        tables = json.loads(tables_file.read_text(encoding="utf-8"))
        for t in tables:
            G.add_node(t)

    if edges_file.exists():
        for line in edges_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            edge = json.loads(line)
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src and tgt:
                G.add_edge(src, tgt)

    script_count = 0
    if scripts_dir.exists():
        script_count = len(list(scripts_dir.glob("*.json")))

    return G, {"script_count": script_count}


def find_diamond_dependencies(G: nx.DiGraph) -> int:
    """统计菱形依赖数量：A→B→C 且 A→C（间接依赖 + 直接依赖并存）。

    这种结构会让影响分析的路径数爆炸（all_simple_paths）。
    """
    count = 0
    for a in G.nodes:
        successors = set(G.successors(a))
        for b in successors:
            # b 的后继里有没有同时是 a 的后继的（即 a→b→c 且 a→c）
            b_successors = set(G.successors(b))
            common = successors & b_successors
            count += len(common)
    return count


def analyze_edge_density(raw_edges: list) -> None:
    """分析边数高的成因：重复边、JOIN 扇入。

    raw_edges: 原始边列表（含可能的重复），每条是 dict 或 tuple。
    """
    if not raw_edges:
        return

    # 统一提取 (source, target) 对
    pairs = []
    for e in raw_edges:
        if isinstance(e, dict):
            src = e.get("source", "")
            tgt = e.get("target", "")
        else:
            src, tgt = e[0], e[1]
        if src and tgt:
            pairs.append((src, tgt))

    if not pairs:
        return

    total = len(pairs)
    unique_pairs = len(set(pairs))
    dup_pairs = total - unique_pairs

    print("\n🔍 边数成因分析")
    print(f"   总边数:          {total}")
    print(f"   唯一 source→target: {unique_pairs}")
    print(f"   重复边数:        {dup_pairs} ({dup_pairs*100//total}%)")

    if dup_pairs > 0:
        from collections import Counter
        pair_counts = Counter(pairs)
        dups = {p: c for p, c in pair_counts.items() if c > 1}
        print(f"   有重复的对数:    {len(dups)}")
        print(f"\n   重复最多的 Top 5（同对表在多个脚本里关联）:")
        for (src, tgt), cnt in sorted(dups.items(), key=lambda x: -x[1])[:5]:
            print(f"     {cnt}次: {src} → {tgt}")
        print(f"\n   💡 去重后真实关系数: {unique_pairs}（当前显示 {total} 含重复）")


def analyze_case_sensitivity(G: nx.DiGraph) -> None:
    """检测大小写重复表名（ORDERS vs orders 算成两张表的场景）。

    PostgreSQL 语义：不带引号的标识符折叠成小写，所以 ORDERS == orders。
    若归一化未折叠，会导致节点/边数虚高。
    """
    from collections import defaultdict
    lower_groups = defaultdict(list)
    for name in G.nodes:
        lower_groups[name.lower()].append(name)
    conflicts = {k: v for k, v in lower_groups.items() if len(v) > 1}

    print("\n🔤 大小写重复检测")
    if not conflicts:
        print("   ✓ 无大小写冲突，所有表名大小写一致")
        return

    dup_count = sum(len(v) - 1 for v in conflicts.values())
    print(f"   ⚠️  发现 {len(conflicts)} 组大小写冲突（同一表的不同写法被当成多张表）")
    print(f"   因大小写重复多算的表数: ~{dup_count}")
    print(f"   去重后实际表数: ~{G.number_of_nodes() - dup_count}")
    print(f"\n   冲突明细（Top 20）:")
    for lower, variants in sorted(conflicts.items())[:20]:
        print(f"     {' / '.join(variants)}")
    if len(conflicts) > 20:
        print(f"     ... 还有 {len(conflicts) - 20} 组")
    print(f"\n   💡 这些表在 PostgreSQL 里其实是同一张（不带引号折叠小写）。")
    print(f"      表名大小写不一致导致血缘断裂：ORDERS→rpt 和 orders→rpt 被算成两条独立链路。")


def analyze(G: nx.DiGraph, meta: dict) -> None:
    """打印完整复杂度报告。"""
    nodes = G.number_of_nodes()
    edges = G.number_of_edges()
    scripts = meta.get("script_count", 0)

    print("=" * 60)
    print("  血缘图谱复杂度分析报告")
    print("=" * 60)

    # 大小写重复检测（放最前面，因为它会影响后续所有指标的准确性）
    analyze_case_sensitivity(G)

    # === 基础规模 ===
    print("\n📊 基础规模")
    print(f"   节点数（表）:  {nodes}")
    print(f"   边数（血缘）:  {edges}")
    print(f"   脚本数:        {scripts}")
    if nodes > 0:
        print(f"   平均每脚本:    {nodes/scripts:.1f} 表, {edges/scripts:.1f} 边")

    if nodes == 0:
        print("\n   ⚠️  图为空，无数据可分析")
        return

    # === 密度指标 ===
    avg_degree = (edges * 2) / nodes if nodes else 0
    density = nx.density(G)
    print("\n🔗 密度指标")
    print(f"   平均度数:      {avg_degree:.2f}（每个表平均连 {avg_degree:.1f} 条关系）")
    print(f"   图密度:        {density:.4f}（0=稀疏, 1=完全连通）")

    # 度数分布
    in_degrees = dict(G.in_degree())
    out_degrees = dict(G.out_degree())
    max_in = max(in_degrees.values()) if in_degrees else 0
    max_out = max(out_degrees.values()) if out_degrees else 0
    print(f"   最大入度:      {max_in}（被最多表汇聚的节点）")
    print(f"   最大出度:      {max_out}（扇出最多的节点）")

    # === 拓扑结构 ===
    print("\n🌳 拓扑结构")
    # 弱连通分量（忽略方向的连通块）
    components = list(nx.weakly_connected_components(G))
    print(f"   连通子图数:    {len(components)}（独立的数据域）")
    if len(components) > 1:
        sizes = sorted([len(c) for c in components], reverse=True)
        print(f"   各子图规模:    {sizes[:10]}{'...' if len(sizes) > 10 else ''}")

    # 环检测
    cycles = list(nx.simple_cycles(G))
    has_cycle = len(cycles) > 0
    print(f"   是否有环:      {'⚠️ 是（' + str(len(cycles)) + '个环）' if has_cycle else '否（DAG，无循环依赖）'}")

    # 最大链路深度（仅 DAG 有意义）
    if not has_cycle:
        try:
            longest = nx.dag_longest_path(G)
            print(f"   最大链路深度:  {len(longest)} 层（最长 source→target 路径）")
            if len(longest) <= 8:
                print(f"   最长链路:      {' → '.join(longest)}")
        except nx.NetworkXError:
            print(f"   最大链路深度:  无法计算（图非 DAG）")
    else:
        print(f"   最大链路深度:  跳过（有环图不适用）")

    # === 枢纽节点（改它们影响最大）===
    print("\n⭐ 枢纽节点（高扇出 = 改它影响下游一大片）")
    top_out = sorted(out_degrees.items(), key=lambda x: x[1], reverse=True)[:10]
    for name, deg in top_out:
        if deg > 0:
            print(f"   出度 {deg:>3}  ←  {name}")

    print("\n🎯 汇聚节点（高扇入 = 依赖很多上游表）")
    top_in = sorted(in_degrees.items(), key=lambda x: x[1], reverse=True)[:10]
    for name, deg in top_in:
        if deg > 0:
            print(f"   入度 {deg:>3}  ←  {name}")

    # === 复杂结构 ===
    print("\n💎 复杂结构")
    diamonds = find_diamond_dependencies(G)
    print(f"   菱形依赖数:    {diamonds}（A→B→C 且 A→C，影响分析路径会爆炸）")
    if diamonds > 0:
        print(f"   ⚠️  存在菱形依赖，影响分析时路径数可能较多（已有上限保护）")

    # 多源汇聚（入度>=3 的节点）
    multi_source = [(n, d) for n, d in in_degrees.items() if d >= 3]
    print(f"   多源汇聚节点:  {len(multi_source)} 个（入度≥3，数据来自≥3个上游表）")

    # === 复杂度评级 ===
    print("\n" + "=" * 60)
    print("  复杂度评级")
    print("=" * 60)
    score = 0
    reasons = []
    if nodes > 100:
        score += 2; reasons.append(f"节点数 {nodes} > 100")
    elif nodes > 50:
        score += 1; reasons.append(f"节点数 {nodes} > 50")
    if edges > 200:
        score += 2; reasons.append(f"边数 {edges} > 200")
    elif edges > 100:
        score += 1; reasons.append(f"边数 {edges} > 100")
    if avg_degree > 4:
        score += 1; reasons.append(f"平均度数 {avg_degree:.1f} > 4")
    if len(components) > 5:
        score += 1; reasons.append(f"连通子图 {len(components)} > 5")
    if diamonds > 10:
        score += 2; reasons.append(f"菱形依赖 {diamonds} > 10")
    elif diamonds > 0:
        score += 1; reasons.append(f"菱形依赖 {diamonds}")

    levels = [
        (0, "🟢 简单", "血缘清晰，维护成本低"),
        (3, "🟡 中等", "有一定复杂度，注意枢纽节点"),
        (6, "🟠 复杂", "建议关注枢纽节点和菱形依赖"),
        (9, "🔴 高度复杂", "改一个源表可能波及大片下游"),
    ]
    level_name, level_desc = levels[0][1], levels[0][2]
    for threshold, name, desc in levels:
        if score >= threshold:
            level_name, level_desc = name, desc

    print(f"\n  评级: {level_name}")
    print(f"  说明: {level_desc}")
    print(f"  评分: {score} 分（基于节点/边/度数/子图/菱形依赖）")
    if reasons:
        print(f"  依据:")
        for r in reasons:
            print(f"    - {r}")

    print("\n" + "=" * 60)


def main():
    args = sys.argv[1:]
    data_dir = None
    export_path = None

    i = 0
    while i < len(args):
        if args[i] == "--data" and i + 1 < len(args):
            data_dir = args[i + 1]
            i += 2
        elif args[i].endswith(".json"):
            export_path = args[i]
            i += 1
        else:
            # 默认当 data 目录
            data_dir = args[i]
            i += 1

    if export_path:
        if not os.path.exists(export_path):
            print(f"错误: 文件不存在: {export_path}")
            sys.exit(1)
        G, meta = load_graph_from_export(export_path)
    else:
        # 默认 data 目录
        if data_dir is None:
            data_dir = Path(__file__).resolve().parent / "data"
        if not Path(data_dir).exists():
            print(f"错误: data 目录不存在: {data_dir}")
            print("用法: python analyze_complexity.py [export.json | --data /path/to/data]")
            sys.exit(1)
        G, meta = load_graph_from_data(data_dir)

    analyze(G, meta)


if __name__ == "__main__":
    main()
