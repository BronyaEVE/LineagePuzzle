import React, { useMemo } from "react";
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
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Card, Empty } from "antd";
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

const NODE_WIDTH = 160;
const NODE_HEIGHT = 40;
const LAYER_GAP = 200;    // 层间距（水平）
const NODE_GAP = 70;      // 同层节点间距（垂直）

/**
 * 按拓扑层级自动布局：源表 → 中间表 → 目标表
 * 同层节点垂直均匀分布
 */
function autoLayout(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return nodes;

  // 构建邻接表：source → [targets]
  const outEdges: Record<string, string[]> = {};
  const inDegree: Record<string, number> = {};
  for (const n of nodes) {
    outEdges[n.id] = [];
    inDegree[n.id] = 0;
  }
  for (const e of edges) {
    if (outEdges[e.source]) outEdges[e.source].push(e.target);
    if (inDegree[e.target] !== undefined) inDegree[e.target]++;
  }

  // 拓扑排序分层（BFS）
  const layers: string[][] = [];
  const assigned = new Set<string>();
  let queue = nodes.filter((n) => inDegree[n.id] === 0).map((n) => n.id);

  // 如果没有入度为 0 的节点（存在环），从所有节点开始
  if (queue.length === 0) queue = nodes.map((n) => n.id);

  while (queue.length > 0) {
    layers.push([...queue]);
    for (const id of queue) assigned.add(id);
    const next: string[] = [];
    for (const id of queue) {
      for (const target of outEdges[id]) {
        if (!assigned.has(target)) {
          inDegree[target]--;
          if (inDegree[target] <= 0) {
            next.push(target);
          }
        }
      }
    }
    queue = [...new Set(next)];
  }

  // 未被分配的节点放到最后一层
  const remaining = nodes.filter((n) => !assigned.has(n.id)).map((n) => n.id);
  if (remaining.length > 0) layers.push(remaining);

  // 按层分配坐标
  const posMap: Record<string, { x: number; y: number }> = {};
  const maxLayerSize = Math.max(...layers.map((l) => l.length));

  layers.forEach((layer, li) => {
    const layerHeight = layer.length * (NODE_HEIGHT + NODE_GAP) - NODE_GAP;
    const startY = -layerHeight / 2;
    layer.forEach((id, ni) => {
      posMap[id] = {
        x: li * LAYER_GAP,
        y: startY + ni * (NODE_HEIGHT + NODE_GAP),
      };
    });
  });

  return nodes.map((node) => ({
    ...node,
    position: posMap[node.id] || { x: 0, y: 0 },
  }));
}

interface Props {
  visualization: Visualization | null;
  highlightSeq: number | null;
}

const LineageGraph: React.FC<Props> = ({ visualization, highlightSeq }) => {
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
        width: NODE_WIDTH,
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

    return { laidNodes: autoLayout(nodes, edges), laidEdges: edges };
  }, [visualization]);

  const [nodes, setNodes, onNodesChange] = useNodesState(laidNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(laidEdges);

  React.useEffect(() => {
    setEdges((eds) =>
      eds.map((e) => {
        const seq = e.data?.statement_seq;
        const hl = highlightSeq !== null && seq === highlightSeq;
        return {
          ...e,
          animated: hl,
          style: {
            ...e.style,
            stroke: hl ? "#1890ff" : "#8c8c8c",
            strokeWidth: hl ? 3 : 2,
          },
          labelStyle: {
            ...e.labelStyle,
            fill: hl ? "#1890ff" : "#333",
            fontWeight: hl ? 700 : 600,
          },
        };
      })
    );
  }, [highlightSeq, setEdges]);

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
    <Card title="血缘关系图" size="small" style={{ height: "100%" }}>
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
