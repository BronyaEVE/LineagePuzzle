import { useEffect, useMemo, useState } from "react";
import { Card, Select, Space, Empty, Spin, Typography, message } from "antd";
import { getColumnMappings } from "../api/client";
import type { ColumnMappingTrace } from "../types";

/**
 * 列级追溯（prototype）。
 *
 * 思路：节点-连线图在大规模血缘下不可读（边交叉、表名拥挤）——这是表示方式的
 * 固有上限，不是性能问题。本视图把「这个列从哪儿来」这个问题，用类似 SQL
 * EXPLAIN 的文本树来表达：选一个目标表/列，递归展开其上游列，变换以 ‹...› 标注。
 *
 * 数据：全局 edges 不含列级映射，由后端 /api/column-mappings 从各脚本 lineages
 * 聚合摊平返回；前端在客户端建索引并按列做递归上游追溯（带环检测 + 深度上限）。
 */

const MAX_DEPTH = 30;

/** 追溯树节点。leaf=无进一步上游；cycle=与祖先重复（已截断）。 */
interface TraceNode {
  table: string;
  column: string;
  transformation: string | null;
  children: TraceNode[];
  leaf: boolean;
  cycle: boolean;
}

/** 从 (target_table, target_column) 出发递归构建上游追溯树。 */
function buildTrace(
  rootTable: string,
  rootColumn: string,
  index: Map<string, ColumnMappingTrace[]>,
): TraceNode {
  const build = (
    table: string,
    column: string,
    transformation: string | null,
    path: Set<string>,
    depth: number,
  ): TraceNode => {
    const key = `${table}||${column}`;
    if (path.has(key)) {
      return { table, column, transformation, children: [], leaf: false, cycle: true };
    }
    const node: TraceNode = {
      table, column, transformation, children: [], leaf: false, cycle: false,
    };
    if (depth > MAX_DEPTH) {
      node.leaf = true;
      return node;
    }
    const srcs = index.get(key);
    if (!srcs || srcs.length === 0) {
      node.leaf = true;
      return node;
    }
    const childPath = new Set(path);
    childPath.add(key);
    for (const m of srcs) {
      const t = m.transformation;
      if (!m.source_table || m.source_columns.length === 0) {
        // 常量 / 纯表达式（无表来源）
        node.children.push({
          table: "",
          column: t || "(常量/表达式)",
          transformation: t,
          children: [],
          leaf: true,
          cycle: false,
        });
      } else {
        for (const sc of m.source_columns) {
          node.children.push(build(m.source_table, sc, t, childPath, depth + 1));
        }
      }
    }
    return node;
  };
  return build(rootTable, rootColumn, null, new Set(), 0);
}

/** 递归渲染一个追溯节点（EXPLAIN 风格缩进树）。 */
function TraceNodeView({ node, depth }: { node: TraceNode; depth: number }) {
  const isRoot = depth === 0;
  return (
    <div style={{ paddingLeft: depth * 22, lineHeight: 1.8 }}>
      {depth > 0 && <span style={{ color: "#bfbfbf" }}>← </span>}
      <span
        style={{
          fontWeight: isRoot ? 700 : 400,
          color: isRoot ? "#1890ff" : "#333",
        }}
      >
        {node.table ? `${node.table}.${node.column}` : node.column}
      </span>
      {node.transformation && depth > 0 && (
        <span style={{ color: "#fa8c16", fontFamily: "monospace", fontSize: 12 }}>
          {"  ‹"}{node.transformation}{"›"}
        </span>
      )}
      {node.cycle && (
        <span style={{ color: "#f5222d", fontSize: 12 }}>{"  ↻ 环引用"}</span>
      )}
      {node.leaf && depth > 0 && node.children.length === 0 && !node.transformation && (
        <span style={{ color: "#bfbfbf", fontSize: 11 }}>{"  (原始列)"}</span>
      )}
      {node.children.map((c, i) => (
        <TraceNodeView key={i} node={c} depth={depth + 1} />
      ))}
    </div>
  );
}

export default function ColumnTrace({ initialTable }: { initialTable?: string | null }) {
  const [mappings, setMappings] = useState<ColumnMappingTrace[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTable, setSelectedTable] = useState<string | null>(initialTable ?? null);
  const [selectedColumn, setSelectedColumn] = useState<string | null>(null);

  // 左栏选表变化时同步预选（表为中心导航：切到列级追溯时带入当前表）
  useEffect(() => {
    if (initialTable) {
      setSelectedTable(initialTable);
      setSelectedColumn(null);
    }
  }, [initialTable]);

  useEffect(() => {
    let cancelled = false;
    getColumnMappings()
      .then((m) => {
        if (cancelled) return;
        setMappings(m);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoading(false);
        message.error(e instanceof Error ? e.message : "加载列级映射失败");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // (target_table || target_column) -> 该列的所有来源映射
  const indexMap = useMemo(() => {
    const map = new Map<string, ColumnMappingTrace[]>();
    for (const m of mappings) {
      if (!m.target_table || !m.target_column) continue;
      const k = `${m.target_table}||${m.target_column}`;
      const arr = map.get(k);
      if (arr) arr.push(m);
      else map.set(k, [m]);
    }
    return map;
  }, [mappings]);

  const targetTables = useMemo(
    () =>
      Array.from(
        new Set(mappings.map((m) => m.target_table).filter(Boolean)),
      ).sort(),
    [mappings],
  );

  const columnsForTable = useMemo(
    () =>
      Array.from(
        new Set(
          mappings
            .filter((m) => m.target_table === selectedTable)
            .map((m) => m.target_column)
            .filter(Boolean),
        ),
      ).sort(),
    [mappings, selectedTable],
  );

  const tree = useMemo(
    () =>
      selectedTable && selectedColumn
        ? buildTrace(selectedTable, selectedColumn, indexMap)
        : null,
    [selectedTable, selectedColumn, indexMap],
  );

  // 首次加载后默认选中第一个目标表
  useEffect(() => {
    if (selectedTable === null && targetTables.length > 0) {
      setSelectedTable(targetTables[0]);
    }
  }, [targetTables, selectedTable]);

  const filter = (input: string, option?: { label: string }) =>
    (option?.label ?? "").toLowerCase().includes(input.toLowerCase());

  return (
    <Card
      size="small"
      style={{ height: "100%", display: "flex", flexDirection: "column" }}
      styles={{ body: { flex: 1, overflow: "auto", padding: 12 } }}
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          showSearch
          placeholder="选择目标表"
          style={{ width: 300 }}
          value={selectedTable ?? undefined}
          onChange={(v: string) => {
            setSelectedTable(v);
            setSelectedColumn(null);
          }}
          options={targetTables.map((t) => ({ label: t, value: t }))}
          filterOption={filter}
        />
        <Select
          showSearch
          placeholder="选择列"
          style={{ width: 220 }}
          value={selectedColumn ?? undefined}
          onChange={setSelectedColumn}
          options={columnsForTable.map((c) => ({ label: c, value: c }))}
          disabled={!selectedTable}
          filterOption={filter}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {mappings.length.toLocaleString()} 条列级映射 · {targetTables.length} 个目标表
        </Typography.Text>
      </Space>

      {loading ? (
        <div style={{ textAlign: "center", marginTop: 60 }}>
          <Spin />
        </div>
      ) : mappings.length === 0 ? (
        <Empty description="暂无列级血缘数据，请先分析脚本" />
      ) : selectedTable && columnsForTable.length === 0 ? (
        <Empty description="该表无列级血缘（SELECT * 或未解析）" />
      ) : !selectedColumn ? (
        <Typography.Text type="secondary">
          该表有 {columnsForTable.length} 个可追溯列，请在上方选择一个。
        </Typography.Text>
      ) : tree && tree.leaf && tree.children.length === 0 ? (
        <Empty description="该列无列级血缘（SELECT * 或未解析）" />
      ) : tree ? (
        <div style={{ fontFamily: "monospace", fontSize: 13 }}>
          <TraceNodeView node={tree} depth={0} />
        </div>
      ) : null}
    </Card>
  );
}
