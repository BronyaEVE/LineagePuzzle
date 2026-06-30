import React, { useMemo, useState, useRef, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type ReactFlowInstance,
  MarkerType,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Card, Empty, Tooltip, Drawer, Tag, Typography, Button, message } from "antd";
import { ColumnWidthOutlined, ColumnHeightOutlined, FileImageOutlined, FileOutlined } from "@ant-design/icons";
import { toPng } from "html-to-image";
import type { GlobalGraph, GlobalEdge, Visualization, ColumnMapping } from "../types";
import { impactAnalysis as fetchImpactAnalysis } from "../api/client";

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

const NODE_H = 40;
// 节点宽度自适应：短表名收缩到最小，超长表名上限封顶 + 省略号
const NODE_MIN_W = 120;
const NODE_MAX_W = 260;

// 布局参数（TB 和 LR 几何语义不同，分开定义避免混用导致重叠）：
//   TB（垂直）：层间沿 y 轴（垂直），层内沿 x 轴（水平）→ 层内按节点【宽度】算间距
//   LR（水平）：层间沿 x 轴（水平），层内沿 y 轴（垂直）→ 层内按节点【高度】算间距
const LAYER_GAP_TB = 110;   // TB 层与层之间的垂直间距（y 轴）
const INTRA_GAP_TB = 120;   // TB 层内节点之间的水平间距（x 轴，按宽度）
const LAYER_GAP_LR = 300;   // LR 层与层之间的水平间距（x 轴，需 ≥ 节点宽度 + 箭头空间）
const INTRA_GAP_LR = 30;    // LR 层内节点之间的垂直间距（y 轴，按高度）

type LayoutDir = "TB" | "LR";

/**
 * 节点样式：宽度自适应（fit-content）但有上下限。
 * 短名（orders）收缩到 NODE_MIN_W；长名（staging.tmp_order_detail）
 * 增长到 NODE_MAX_W 封顶，label 用 ellipsis 截断。
 * label 文字包一层带 overflow 的 span，超出 maxWidth 显示省略号。
 */
// 表名显示截断阈值：超过则在 schema 名后省略，保证节点宽度可控
// 完整名仍存在 node.data.fullName，避免 CSS ellipsis 在 React Flow
// 嵌套结构里失效导致节点撑破 maxWidth 进而重叠
const LABEL_MAX_CHARS = 24;

function truncateLabel(label: string): string {
  if (label.length <= LABEL_MAX_CHARS) return label;
  // schema.table 格式：保留 schema + 前几个字符 + 省略号
  const dotIdx = label.indexOf(".");
  if (dotIdx > 0 && dotIdx < LABEL_MAX_CHARS - 3) {
    const schema = label.slice(0, dotIdx + 1);
    const rest = label.slice(dotIdx + 1, LABEL_MAX_CHARS - schema.length - 1);
    return `${schema}${rest}…`;
  }
  return label.slice(0, LABEL_MAX_CHARS - 1) + "…";
}

function nodeStyle(nodeType: string): React.CSSProperties {
  return {
    background: NODE_COLORS[nodeType] || "#d9d9d9",
    border: `2px solid ${NODE_BORDER_COLORS[nodeType] || "#8c8c8c"}`,
    borderRadius: 6,
    padding: "8px 12px",
    fontSize: 13,
    fontWeight: 600,
    color: "#fff",
    minWidth: NODE_MIN_W,
    maxWidth: NODE_MAX_W,
    width: "fit-content",
    textAlign: "center" as const,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  };
}

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

  // 层间间距（层与层之间）：TB 沿 y 轴，LR 沿 x 轴
  const layerGap = isVertical ? LAYER_GAP_TB : LAYER_GAP_LR;
  // 层内间距（同层节点之间）：TB 沿 x 轴（水平，按宽度），LR 沿 y 轴（垂直，按高度）
  const intraGap = isVertical ? INTRA_GAP_TB : INTRA_GAP_LR;
  // 层内排列方向的节点尺寸：TB 按宽度（节点宽 120-260），LR 按高度（40）
  const intraSize = isVertical ? NODE_MAX_W : NODE_H;
  const posMap: Record<string, { x: number; y: number }> = {};

  layers.forEach((layer, li) => {
    // TB：offset 是 x（层内水平排列），y 是层间距
    // LR：offset 是 y（层内垂直排列），x 是层间距
    const span = layer.length * (intraSize + intraGap) - intraGap;
    const start = -span / 2;
    layer.forEach((id, ni) => {
      const offset = start + ni * (intraSize + intraGap);
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

/** 搜索/程序化聚焦目标：node 聚焦单个节点，edge 聚焦 source+target 两端 */
export interface FocusTarget {
  type: "node" | "edge";
  id: string;  // node: node.id；edge: 边的 id（React Flow 生成的 e-${i}/ge-${i}）
}

interface Props {
  globalGraph: GlobalGraph | null;
  visualization: Visualization | null;
  highlightScriptId: string | null;
  highlightSeq: number | null;
  // 点边时反向高亮对应语句（列级场景：点边→右栏语句高亮）
  onEdgeSelectSeq?: (seq: number | null) => void;
  // 搜索选中后聚焦+高亮（由 App/Header 的搜索框驱动）
  focusTarget?: FocusTarget | null;
  // 影响分析触发时通知 App（脚本视图需切回全局图）
  onImpactTrigger?: () => void;
}

const LineageGraph: React.FC<Props> = ({
  globalGraph, visualization, highlightScriptId, highlightSeq, onEdgeSelectSeq, focusTarget, onImpactTrigger,
}) => {
  const [layoutDir, setLayoutDir] = useState<LayoutDir>("TB");
  const isVertical = layoutDir === "TB";
  // React Flow 实例（onInit 时获取，替代 useReactFlow——后者要求在 Provider 内调用，
  // 而 LineageGraph 本身就是渲染 <ReactFlow> 的组件，不是其子组件，直接调 useReactFlow 会白屏）
  const reactFlowRef = React.useRef<ReactFlowInstance | null>(null);
  // 包裹 ReactFlow 的 div，用于 html-to-image 截图（PNG 导出）
  const wrapperRef = React.useRef<HTMLDivElement>(null);
  // 选中的边（点边弹 Drawer 展示列级映射）
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  // 单边高亮 id（点边时只高亮这一条，区别于 seq 高亮——一条 JOIN 语句可能有多条边共享 seq）
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  // 展开的节点 id：点击节点时记录，该节点显示完整名（不限长），其他节点保持截断
  const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);
  // 影响分析高亮的边 id 集合：downstream 橙色、upstream 青色（单击节点触发）
  const [impactDownstreamEdges, setImpactDownstreamEdges] = useState<Set<string>>(new Set());
  const [impactUpstreamEdges, setImpactUpstreamEdges] = useState<Set<string>>(new Set());
  // 影响分析请求竞态防护：每次点击节点递增 token，只有最新请求的响应被采纳。
  // 避免快速连点多个节点时，先返回的响应覆盖最终结果。
  const impactTokenRef = useRef(0);
  // 组件是否仍挂载，防止卸载后 setState（请求未完成就切走）
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  const hasImpactHighlight = impactDownstreamEdges.size > 0 || impactUpstreamEdges.size > 0;

  // 当选中脚本时，使用脚本自己的 visualization；否则用全局图
  const { laidNodes, laidEdges } = useMemo(() => {
    // 选了脚本 → 用脚本级别的 visualization
    if (highlightScriptId && visualization && visualization.nodes.length > 0) {
      const nodes: Node[] = visualization.nodes.map((n) => {
        const expanded = expandedNodeId === n.id;
        return {
          id: n.id,
          data: { label: expanded ? n.label : truncateLabel(n.label), fullName: n.label, nodeType: n.type },
          position: { x: 0, y: 0 },
          style: expanded
            ? { ...nodeStyle(n.type), maxWidth: "none", border: "3px solid #fff", boxShadow: "0 0 8px rgba(255,255,255,0.8)" }
            : nodeStyle(n.type),
        };
      });
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

    const nodes: Node[] = globalGraph.nodes.map((n) => {
      const expanded = expandedNodeId === n.id;
      return {
        id: n.id,
        data: { label: expanded ? n.label : truncateLabel(n.label), fullName: n.label, nodeType: n.type },
        position: { x: 0, y: 0 },
        style: expanded
          ? { ...nodeStyle(n.type), maxWidth: "none", border: "3px solid #fff", boxShadow: "0 0 8px rgba(255,255,255,0.8)" }
          : nodeStyle(n.type),
      };
    });
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
  }, [globalGraph, visualization, highlightScriptId, layoutDir, expandedNodeId]);

  const [nodes, setNodes, onNodesChange] = useNodesState(laidNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(laidEdges);

  // 高亮逻辑：单边（点边）> 影响分析（上下游双色）> 语句级（点语句）> 脚本级 > 默认
  //
  // 关键：本 effect 直接以 laidEdges 为基底重算（而非读当前 state 的 eds），
  // 且依赖 laidEdges。这样切换布局 / 展开节点导致 laidEdges 变化时，高亮会基于
  // 新边重新应用，不会因「重置 effect(362) 覆盖高亮」而丢失（B5 修复）。
  React.useEffect(() => {
    setEdges(laidEdges.map((e) => {
      // 最高优先级：点边单条高亮（用 edge.id 定位，避免同 seq 多边被误点亮）
      if (selectedEdgeId !== null) {
        const hl = e.id === selectedEdgeId;
        return {
          ...e, animated: hl,
          style: { ...e.style, stroke: hl ? "#1890ff" : "#d9d9d9", strokeWidth: hl ? 3 : 1.5 },
          labelStyle: { ...e.labelStyle, fill: hl ? "#1890ff" : "#999" },
        };
      }
      // 影响分析高亮：下游橙 #fa8c16，上游青 #13c2c2，无关边灰
      if (hasImpactHighlight) {
        const isDown = impactDownstreamEdges.has(e.id);
        const isUp = impactUpstreamEdges.has(e.id);
        if (isDown) {
          return {
            ...e, animated: true,
            style: { ...e.style, stroke: "#fa8c16", strokeWidth: 3 },
            labelStyle: { ...e.labelStyle, fill: "#fa8c16" },
          };
        }
        if (isUp) {
          return {
            ...e, animated: true,
            style: { ...e.style, stroke: "#13c2c2", strokeWidth: 3 },
            labelStyle: { ...e.labelStyle, fill: "#13c2c2" },
          };
        }
        // 无关边：灰、不流动
        return {
          ...e, animated: false,
          style: { ...e.style, stroke: "#d9d9d9", strokeWidth: 1 },
          labelStyle: { ...e.labelStyle, fill: "#bbb" },
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
      // 默认：全部正常显示（恢复流动动画，和初始化状态一致）
      return { ...e, animated: true, style: { ...e.style, stroke: "#8c8c8c", strokeWidth: 2 },
        labelStyle: { ...e.labelStyle, fill: "#333" } };
    }));
  }, [laidEdges, highlightSeq, highlightScriptId, selectedEdgeId, hasImpactHighlight, impactDownstreamEdges, impactUpstreamEdges, setEdges]);

  // 搜索选中后聚焦+高亮（由 App 的 focusTarget 驱动）
  React.useEffect(() => {
    if (!focusTarget || !reactFlowRef.current) return;
    const rf = reactFlowRef.current;
    if (focusTarget.type === "node") {
      // 聚焦单个节点 + 展开表名 + 清边高亮
      rf.fitView({ nodes: [{ id: focusTarget.id }], padding: 0.5, duration: 400, maxZoom: 1.5 });
      setExpandedNodeId(focusTarget.id);
      setSelectedEdgeId(null);
      setSelectedEdge(null);
    } else {
      // 聚焦边的两端节点 + 单边高亮
      const found = edges.find((e) => e.id === focusTarget.id);
      if (found) {
        rf.fitView({
          nodes: [{ id: found.source }, { id: found.target }],
          padding: 0.5, duration: 400, maxZoom: 1.5,
        });
        setSelectedEdgeId(found.id);
        setSelectedEdge(found);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusTarget]);

  // 节点布局变化时同步（边由上面的高亮 effect 基于 laidEdges 统一接管，
  // 这里只更新节点，避免两个 effect 互相覆盖边样式导致高亮丢失）。
  React.useEffect(() => {
    setNodes(laidNodes);
  }, [laidNodes, setNodes]);

  const hasData = laidNodes.length > 0;
  const isScriptView = !!highlightScriptId && !!visualization?.nodes.length;

  // === 图形导出 ===
  const handleExportPng = async () => {
    if (!wrapperRef.current) return;
    try {
      // 先重置视口到全图，确保截图覆盖所有节点
      reactFlowRef.current?.fitView({ padding: 0.2, duration: 0 });
      // 等一帧让 React Flow 完成重置
      await new Promise((r) => setTimeout(r, 100));
      const dataUrl = await toPng(wrapperRef.current!, {
        backgroundColor: "#fff",
        filter: (node) => {
          // 排除 React Flow 的控件（Controls/MiniMap），只截图画
          const cls = (node as HTMLElement).className;
          return typeof cls !== "string" || (!cls.includes("react-flow__controls") && !cls.includes("react-flow__minimap"));
        },
      });
      const a = document.createElement("a");
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      a.href = dataUrl;
      a.download = `lineage-${ts}.png`;
      a.click();
    } catch {
      message.error("导出 PNG 失败");
    }
  };

  const handleExportHtml = () => {
    // 导出自包含 HTML：nodes/edges JSON + React Flow CDN，打开是可缩放只读图
    const data = JSON.stringify({ nodes: laidNodes, edges: laidEdges }, null, 2);
    const html = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>DataLineage 血缘图</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xyflow/react@12/dist/style.css">
<script src="https://cdn.jsdelivr.net/npm/react@18/umd/react.production.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xyflow/react@12/dist/umd/index.js"></script>
<style>
  body { margin: 0; }
  #app { width: 100vw; height: 100vh; }
</style>
</head>
<body>
<div id="app"></div>
<script>
  var graphData = ${data};
  var e = React.createElement;
  var app = e(XyFlow.ReactFlow,
    { nodes: graphData.nodes, edges: graphData.edges, fitView: true,
      proOptions: { hideAttribution: true } },
    e(XyFlow.Background, { gap: 16 }),
    e(XyFlow.Controls),
    e(XyFlow.MiniMap)
  );
  ReactDOM.createRoot(document.getElementById('app')).render(app);
</script>
</body>
</html>`;
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    a.href = url;
    a.download = `lineage-${ts}.html`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card
      title={isScriptView ? "脚本血缘图" : "全局血缘图谱"}
      size="small"
      style={{ height: "100%" }}
      extra={
        hasData ? (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
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
            <Tooltip title="导出为 PNG 图片">
              <Button size="small" icon={<FileImageOutlined />} onClick={handleExportPng}>PNG</Button>
            </Tooltip>
            <Tooltip title="导出为自包含 HTML（可缩放，需联网打开）">
              <Button size="small" icon={<FileOutlined />} onClick={handleExportHtml}>HTML</Button>
            </Tooltip>
          </div>
        ) : null
      }
    >
      {hasData ? (
        <div ref={wrapperRef} style={{ height: "calc(100vh - 160px)", minHeight: 300 }}>
          <ReactFlow
            nodes={nodes} edges={edges}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onInit={(inst) => { reactFlowRef.current = inst; }}
            onNodeClick={(_, node) => {
              // 再次点同一节点：收起表名 + 取消影响分析高亮
              if (expandedNodeId === node.id) {
                setExpandedNodeId(null);
                setImpactDownstreamEdges(new Set());
                setImpactUpstreamEdges(new Set());
                impactTokenRef.current++; // 作废可能还在途的请求
                return;
              }
              // 展开表名
              setExpandedNodeId(node.id);
              // 触发影响分析（脚本视图下先切回全局图）
              if (onImpactTrigger) onImpactTrigger();
              // 竞态防护：本次点击的 token，响应回来时校验是否仍是最新点击
              const myToken = ++impactTokenRef.current;
              // 把路径数组展开成边 id 集合的工具
              const buildEdgeSet = (
                pathsArr: Record<string, string[]>,
                edgeIndex: Map<string, string>,
              ): Set<string> => {
                const ids = new Set<string>();
                for (const path of Object.values(pathsArr)) {
                  for (let i = 0; i < path.length - 1; i++) {
                    const eid = edgeIndex.get(`${path[i]}→${path[i + 1]}`);
                    if (eid) ids.add(eid);
                  }
                }
                return ids;
              };
              fetchImpactAnalysis(node.id).then((result) => {
                // 过期响应（用户又点了别的节点）或组件已卸载 → 丢弃
                if (myToken !== impactTokenRef.current || !mountedRef.current) return;
                if (result.error || (!result.downstream.length && !result.upstream.length)) {
                  setImpactDownstreamEdges(new Set());
                  setImpactUpstreamEdges(new Set());
                  return;
                }
                // 建 (src→tgt) → edgeId 索引。
                // 边 id 前缀随视图不同：全局图 ge-${i}，脚本视图 e-${i}。
                // 用当前实际渲染的边建索引，保证高亮 id 与渲染边 id 一致。
                const edgeIndex = new Map<string, string>();
                edges.forEach((e) => {
                  edgeIndex.set(`${e.source}→${e.target}`, e.id);
                });
                // 下游路径 → 边 id 集合（橙色）
                const downIds = buildEdgeSet(result.paths, edgeIndex);
                // 上游路径 → 边 id 集合（青色）。用后端返回的 upstream_paths，
                // 精确给出「上游表 → 当前表」的真实链路，无需前端 O(n²) 推算。
                const upIds = result.upstream_paths
                  ? buildEdgeSet(result.upstream_paths, edgeIndex)
                  : new Set<string>();
                setImpactDownstreamEdges(downIds);
                setImpactUpstreamEdges(upIds);
              }).catch(() => {
                if (myToken !== impactTokenRef.current || !mountedRef.current) return;
                setImpactDownstreamEdges(new Set());
                setImpactUpstreamEdges(new Set());
              });
            }}
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
