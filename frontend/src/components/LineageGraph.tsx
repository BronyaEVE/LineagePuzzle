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
import { Card, Empty, Tooltip } from "antd";
import { ColumnWidthOutlined, ColumnHeightOutlined } from "@ant-design/icons";
import type { Visualization } from "../types";

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
const LAYER_GAP_TB = 100;   // 垂直布局层间距
const NODE_GAP_TB = 70;     // 垂直布局同层间距
const LAYER_GAP_LR = 200;   // 水平布局层间距
const NODE_GAP_LR = 70;     // 水平布局同层间距

type LayoutDir = "TB" | "LR";

/**
 * 按拓扑层级自动布局
 * TB = 从上到下（默认），LR = 从左到右
 */
function autoLayout(nodes: Node[], edges: Edge[], dir: LayoutDir): Node[] {
  if (nodes.length === 0) return nodes;

  const isVertical = dir === "TB";

  // 邻接表 + 入度
  const outEdges: Record<string, string[]> = {};
  const inDegree: Record<string, number> = {};
  for (const n of nodes) { outEdges[n.id] = []; inDegree[n.id] = 0; }
  for (const e of edges) {
    if (outEdges[e.source]) outEdges[e.source].push(e.target);
    if (inDegree[e.target] !== undefined) inDegree[e.target]++;
  }

  // BFS 分层
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

  // 分配坐标
  const layerGap = isVertical ? LAYER_GAP_TB : LAYER_GAP_LR;
  const nodeGap = isVertical ? NODE_GAP_TB : NODE_GAP_LR;
  const nodeSize = isVertical ? NODE_H : NODE_W;  // 沿排列方向的节点尺寸
  const posMap: Record<string, { x: number; y: number }> = {};

  layers.forEach((layer, li) => {
    const span = layer.length * (nodeSize + nodeGap) - nodeGap;
    const start = -span / 2;
    layer.forEach((id, ni) => {
      const offset = start + ni * (nodeSize + nodeGap);
      if (isVertical) {
        // 层沿 Y 轴排列，同层节点沿 X 轴居中分布
        posMap[id] = { x: offset, y: li * layerGap };
      } else {
        // 层沿 X 轴排列，同层节点沿 Y 轴居中分布
        posMap[id] = { x: li * layerGap, y: offset };
      }
    });
  });

  return nodes.map((node) => ({
    ...node,
    position: posMap[node.id] || { x: 0, y: 0 },
    // 连接点方向与布局方向一致
    sourcePosition: isVertical ? Position.Bottom : Position.Right,
    targetPosition: isVertical ? Position.Top : Position.Left,
  }));
}

interface Props {
  visualization: Visualization | null;
  highlightSeq: number | null;
}

const LineageGraph: React.FC<Props> = ({ visualization, highlightSeq }) => {
  const [layoutDir, setLayoutDir] = useState<LayoutDir>("TB");
  const isVertical = layoutDir === "TB";

  const { laidNodes, laidEdges } = useMemo(() => {
    if (!visualization) return { laidNodes: [], laidEdges: [] };

    const nodes: Node[] = visualization.nodes.map((n) => ({
      id: n.id,
      data: { label: n.label, nodeType: n.type },
      position: { x: 0, y: 0 },
      style: {
        background: NODE_COLORS[n.type] || "#d9d9d9",
        border: `2px solid ${NODE_BORDER_COLORS[n.type] || "#8c8c8c"}`,
        borderRadius: 6,
        padding: "8px 16px",
        fontSize: 13,
        fontWeight: 600,
        color: "#fff",
        width: NODE_W,
        textAlign: "center" as const,
      },
    }));

    const edges: Edge[] = visualization.edges.map((e, i) => ({
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      label: e.label,
      data: { statement_seq: e.statement_seq },
      animated: true,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: "#8c8c8c", strokeWidth: 2 },
      labelStyle: { fontSize: 11, fontWeight: 600, fill: "#333" },
      labelBgStyle: { fill: "#fff", fillOpacity: 0.85 },
      labelBgPadding: [4, 8] as [number, number],
      labelBgBorderRadius: 3,
    }));

    return { laidNodes: autoLayout(nodes, edges, layoutDir), laidEdges: edges };
  }, [visualization, layoutDir]);

  const [nodes, setNodes, onNodesChange] = useNodesState(laidNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(laidEdges);

  // 高亮联动
  React.useEffect(() => {
    setEdges((eds) =>
      eds.map((e) => {
        const seq = e.data?.statement_seq;
        const hl = highlightSeq !== null && seq === highlightSeq;
        return {
          ...e,
          animated: hl,
          style: { ...e.style, stroke: hl ? "#1890ff" : "#8c8c8c", strokeWidth: hl ? 3 : 2 },
          labelStyle: { ...e.labelStyle, fill: hl ? "#1890ff" : "#333", fontWeight: hl ? 700 : 600 },
        };
      })
    );
  }, [highlightSeq, setEdges]);

  // visualization 或方向变化时重新布局
  React.useEffect(() => {
    setNodes(laidNodes);
    setEdges(laidEdges);
  }, [laidNodes, laidEdges, setNodes, setEdges]);

  if (!visualization || !visualization.nodes.length) {
    return (
      <Card title="血缘关系图" size="small" style={{ height: "100%" }}>
        <Empty description="暂无血缘数据" />
      </Card>
    );
  }

  return (
    <Card
      title="血缘关系图"
      size="small"
      style={{ height: "100%" }}
      extra={
        <Tooltip title={isVertical ? "切换为水平布局" : "切换为垂直布局"}>
          <button
            onClick={() => setLayoutDir(isVertical ? "LR" : "TB")}
            style={{
              background: "transparent",
              border: "1px solid #d9d9d9",
              borderRadius: 4,
              padding: "2px 8px",
              cursor: "pointer",
              fontSize: 14,
              color: "#666",
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            {isVertical ? <ColumnWidthOutlined /> : <ColumnHeightOutlined />}
            {isVertical ? "水平" : "垂直"}
          </button>
        </Tooltip>
      }
    >
      <div style={{ height: "calc(100vh - 420px)", minHeight: 300 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.3}
          maxZoom={2}
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
    </Card>
  );
};

export default LineageGraph;
