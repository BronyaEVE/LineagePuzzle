import React, { useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  MarkerType,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Card, Empty, Tooltip, Drawer, Tag, Typography } from "antd";
import { ColumnWidthOutlined, ColumnHeightOutlined } from "@ant-design/icons";
import type { GlobalGraph, GlobalEdge, Visualization, ColumnMapping } from "../types";

const NODE_COLORS: Record<string, string> = {
  source: "#52c41a",
  intermediate: "#faad14",
  target: "#1890ff",
};

const NODE_BORDER_COLORS: Record<string, string> = {
  source: "#389e0d",
  intermediate: "#d48806",
  target: "#096dd9",
};

const NODE_W = 160;
const NODE_H = 40;
const LAYER_GAP_TB = 100;
const NODE_GAP_TB = 70;
const LAYER_GAP_LR = 200;
const NODE_GAP_LR = 70;

type LayoutDir = "TB" | "LR";

function autoLayout(nodes: Node[], edges: Edge[], dir: LayoutDir): Node[] {
  if (nodes.length === 0) return nodes;
  const isVertical = dir === "TB";

  const outEdges: Record<string, string[]> = {};
  const inDegree: Record<string, number> = {};
  for (const n of nodes) { outEdges[n.id] = []; inDegree[n.id] = 0; }
  for (const e of edges) {
    if (outEdges[e.source]) outEdges[e.source].push(e.target);
    if (inDegree[e.target] !== undefined) inDegree[e.target]++;
  }

  const layers: string[][] = [];
  const assigned = new Set<string>();
  let queue = nodes.filter((n) => inDegree[n.id] === 0).map((n) => n.id);
  if (queue.length === 0) queue = nodes.map((n) => n.id);

  while (queue.length > 0) {
    layers.push([...queue]);
    for (const id of queue) assigned.add(id);
    const next: string[] = [];
    for (const id of queue) {
      for (const target of outEdges[id]) {
        if (!assigned.has(target)) {
          inDegree[target]--;
          if (inDegree[target] <= 0) next.push(target);
        }
      }
    }
    queue = [...new Set(next)];
  }
  const remaining = nodes.filter((n) => !assigned.has(n.id)).map((n) => n.id);
  if (remaining.length > 0) layers.push(remaining);

  const layerGap = isVertical ? LAYER_GAP_TB : LAYER_GAP_LR;
  const nodeGap = isVertical ? NODE_GAP_TB : NODE_GAP_LR;
  const nodeSize = isVertical ? NODE_H : NODE_W;
  const posMap: Record<string, { x: number; y: number }> = {};

  layers.forEach((layer, li) => {
    const span = layer.length * (nodeSize + nodeGap) - nodeGap;
    const start = -span / 2;
    layer.forEach((id, ni) => {
      const offset = start + ni * (nodeSize + nodeGap);
      if (isVertical) {
        posMap[id] = { x: offset, y: li * layerGap };
      } else {
        posMap[id] = { x: li * layerGap, y: offset };
      }
    });
  });

  return nodes.map((node) => ({
    ...node,
    position: posMap[node.id] || { x: 0, y: 0 },
    sourcePosition: isVertical ? Position.Bottom : Position.Right,
    targetPosition: isVertical ? Position.Top : Position.Left,
  }));
}

interface Props {
  globalGraph: GlobalGraph | null;
  visualization: Visualization | null;
  highlightScriptId: string | null;
  highlightSeq: number | null;
  // 点边时反向高亮对应语句（列级场景：点边→右栏语句高亮）
  onEdgeSelectSeq?: (seq: number | null) => void;
}

const LineageGraph: React.FC<Props> = ({
  globalGraph, visualization, highlightScriptId, highlightSeq, onEdgeSelectSeq,
}) => {
  const [layoutDir, setLayoutDir] = useState<LayoutDir>("TB");
  const isVertical = layoutDir === "TB";
  // 选中的边（点边弹 Drawer 展示列级映射）
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  // 单边高亮 id（点边时只高亮这一条，区别于 seq 高亮——一条 JOIN 语句可能有多条边共享 seq）
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  // 当选中脚本时，使用脚本自己的 visualization；否则用全局图
  const { laidNodes, laidEdges } = useMemo(() => {
    // 选了脚本 → 用脚本级别的 visualization
    if (highlightScriptId && visualization && visualization.nodes.length > 0) {
      const nodes: Node[] = visualization.nodes.map((n) => ({
        id: n.id,
        data: { label: n.label, nodeType: n.type },
        position: { x: 0, y: 0 },
        style: {
          background: NODE_COLORS[n.type] || "#d9d9d9",
          border: `2px solid ${NODE_BORDER_COLORS[n.type] || "#8c8c8c"}`,
          borderRadius: 6, padding: "8px 16px", fontSize: 13, fontWeight: 600,
          color: "#fff", width: NODE_W, textAlign: "center" as const,
        },
      }));
      const edges: Edge[] = visualization.edges.map((e, i) => ({
        id: `e-${i}`,
        source: e.source,
        target: e.target,
        label: e.label,
        data: {
          statement_seq: e.statement_seq,
          column_mappings: e.column_mappings || [],  // 列级血缘，点边时展示
        },
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: "#8c8c8c", strokeWidth: 2 },
        labelStyle: { fontSize: 11, fontWeight: 600, fill: "#333" },
        labelBgStyle: { fill: "#fff", fillOpacity: 0.85 },
        labelBgPadding: [4, 8] as [number, number],
        labelBgBorderRadius: 3,
      }));
      return { laidNodes: autoLayout(nodes, edges, layoutDir), laidEdges: edges };
    }

    // 全局图
    if (!globalGraph || globalGraph.nodes.length === 0) {
      return { laidNodes: [], laidEdges: [] };
    }

    const nodes: Node[] = globalGraph.nodes.map((n) => ({
      id: n.id,
      data: { label: n.label, nodeType: n.type },
      position: { x: 0, y: 0 },
      style: {
        background: NODE_COLORS[n.type] || "#d9d9d9",
        border: `2px solid ${NODE_BORDER_COLORS[n.type] || "#8c8c8c"}`,
        borderRadius: 6, padding: "8px 16px", fontSize: 13, fontWeight: 600,
        color: "#fff", width: NODE_W, textAlign: "center" as const,
      },
    }));
    const edges: Edge[] = globalGraph.edges.map((e: GlobalEdge, i: number) => ({
      id: `ge-${i}`,
      source: e.source,
      target: e.target,
      label: e.operation,
      data: {
        script_id: e.script_id,
        statement_seq: e.statement_seq,
        column_mappings: e.column_mappings || [],  // 列级血缘，点边时展示
      },
      animated: true,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: "#8c8c8c", strokeWidth: 2 },
      labelStyle: { fontSize: 11, fontWeight: 600, fill: "#333" },
      labelBgStyle: { fill: "#fff", fillOpacity: 0.85 },
      labelBgPadding: [4, 8] as [number, number],
      labelBgBorderRadius: 3,
    }));

    return { laidNodes: autoLayout(nodes, edges, layoutDir), laidEdges: edges };
  }, [globalGraph, visualization, highlightScriptId, layoutDir]);

  const [nodes, setNodes, onNodesChange] = useNodesState(laidNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(laidEdges);

  // 高亮逻辑：单边（点边）> 语句级（点语句）> 脚本级（全局图选中脚本）
  React.useEffect(() => {
    setEdges((eds) =>
      eds.map((e) => {
        // 最高优先级：点边单条高亮（用 edge.id 定位，避免同 seq 多边被误点亮）
        if (selectedEdgeId !== null) {
          const hl = e.id === selectedEdgeId;
          return {
            ...e, animated: hl,
            style: { ...e.style, stroke: hl ? "#1890ff" : "#d9d9d9", strokeWidth: hl ? 3 : 1.5 },
            labelStyle: { ...e.labelStyle, fill: hl ? "#1890ff" : "#999" },
          };
        }
        // 语句级别高亮（右栏点语句：该 seq 的所有边，多条是期望行为）
        if (highlightSeq !== null) {
          const seq = e.data?.statement_seq;
          const hl = seq === highlightSeq;
          return {
            ...e, animated: hl,
            style: { ...e.style, stroke: hl ? "#1890ff" : "#d9d9d9", strokeWidth: hl ? 3 : 1.5 },
            labelStyle: { ...e.labelStyle, fill: hl ? "#1890ff" : "#999" },
          };
        }
        // 全局图：选中脚本时高亮该脚本（script_id）的边，其他灰
        if (highlightScriptId !== null) {
          const sid = (e.data as { script_id?: string } | undefined)?.script_id;
          const hl = sid === highlightScriptId;
          return {
            ...e, animated: hl,
            style: { ...e.style, stroke: hl ? "#1890ff" : "#d9d9d9", strokeWidth: hl ? 2.5 : 1 },
            labelStyle: { ...e.labelStyle, fill: hl ? "#1890ff" : "#bbb" },
          };
        }
        // 默认：全部正常显示
        return { ...e, animated: false, style: { ...e.style, stroke: "#8c8c8c", strokeWidth: 2 },
          labelStyle: { ...e.labelStyle, fill: "#333" } };
      })
    );
  }, [highlightSeq, highlightScriptId, selectedEdgeId, setEdges]);

  React.useEffect(() => {
    setNodes(laidNodes);
    setEdges(laidEdges);
  }, [laidNodes, laidEdges, setNodes, setEdges]);

  const hasData = laidNodes.length > 0;
  const isScriptView = !!highlightScriptId && !!visualization?.nodes.length;

  return (
    <Card
      title={isScriptView ? "脚本血缘图" : "全局血缘图谱"}
      size="small"
      style={{ height: "100%" }}
      extra={
        hasData ? (
          <Tooltip title={isVertical ? "切换为水平布局" : "切换为垂直布局"}>
            <button
              onClick={() => setLayoutDir(isVertical ? "LR" : "TB")}
              style={{
                background: "transparent", border: "1px solid #d9d9d9", borderRadius: 4,
                padding: "2px 8px", cursor: "pointer", fontSize: 14, color: "#666",
                display: "inline-flex", alignItems: "center", gap: 4,
              }}
            >
              {isVertical ? <ColumnWidthOutlined /> : <ColumnHeightOutlined />}
              {isVertical ? "水平" : "垂直"}
            </button>
          </Tooltip>
        ) : null
      }
    >
      {hasData ? (
        <div style={{ height: "calc(100vh - 160px)", minHeight: 300 }}>
          <ReactFlow
            nodes={nodes} edges={edges}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onEdgeClick={(_, edge) => {
              setSelectedEdge(edge);
              setSelectedEdgeId(edge.id);  // 单边高亮（只这一条，不用 seq 避免 JOIN 多边误亮）
            }}
            fitView fitViewOptions={{ padding: 0.2 }}
            proOptions={{ hideAttribution: true }}
            minZoom={0.2} maxZoom={2}
          >
            <Background gap={16} size={1} />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                const t = (n.data as { nodeType?: string })?.nodeType;
                return NODE_COLORS[t || ""] || "#d9d9d9";
              }}
              maskColor="rgba(0,0,0,0.1)"
            />
          </ReactFlow>
        </div>
      ) : (
        <Empty description={isScriptView ? "该脚本无血缘数据" : "提交第一个脚本开始构建血缘图谱"} style={{ marginTop: 80 }} />
      )}

      {/* 列级血缘映射抽屉：点边展示目标列←源列 + transform */}
      <Drawer
        title="列级血缘映射"
        open={!!selectedEdge}
        onClose={() => { setSelectedEdge(null); setSelectedEdgeId(null); if (onEdgeSelectSeq) onEdgeSelectSeq(null); }}
        width={440}
        size="default"
      >
        {selectedEdge ? (
          <>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
              <strong>{selectedEdge.source}</strong> → <strong>{selectedEdge.target}</strong>
              <span style={{ marginLeft: 8 }}>
                操作：<Tag color="blue">{selectedEdge.label}</Tag>
                语句 #{(selectedEdge.data as { statement_seq?: number })?.statement_seq}
              </span>
            </Typography.Paragraph>
            {(() => {
              const mappings = (selectedEdge.data as { column_mappings?: ColumnMapping[] })?.column_mappings || [];
              if (mappings.length === 0) {
                return (
                  <Empty
                    description="该边无列级映射（可能为 SELECT * 或纯表级血缘）"
                    style={{ marginTop: 40 }}
                  />
                );
              }
              return mappings.map((m, i) => (
                <div
                  key={i}
                  style={{
                    padding: "10px 12px", marginBottom: 8,
                    background: "#fafafa", border: "1px solid #f0f0f0", borderRadius: 4,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <Tag color="blue">{m.target_column}</Tag>
                    <span style={{ color: "#999" }}>←</span>
                    {m.source_columns.length > 0 ? (
                      m.source_columns.map((c, ci) => (
                        <Tag key={ci} color="green">
                          {m.source_table ? `${m.source_table}.${c}` : c}
                        </Tag>
                      ))
                    ) : (
                      <Tag>常量</Tag>
                    )}
                  </div>
                  {m.transformation && (
                    <div style={{ marginTop: 6, fontSize: 12, color: "#fa8c16" }}>
                      变换：{m.transformation}
                    </div>
                  )}
                </div>
              ));
            })()}
          </>
        ) : null}
      </Drawer>
    </Card>
  );
};

export default LineageGraph;
