import type { Edge, Node } from "@xyflow/react";

/**
 * 自包含 HTML 导出：把当前画布渲染成零外部依赖的单文件 HTML。
 *
 * 历史教训（为什么不用 React Flow UMD + CDN）：
 *   1. @xyflow/react@12 的 UMD 全局名是 ReactFlow 而非 XyFlow，旧导出脚本
 *      引用 XyFlow.* 直接抛 ReferenceError → 白屏；
 *   2. CDN 依赖在隔离内网环境不可达（本工具的典型部署环境），必死。
 * 现方案：内联 SVG 静态快照（布局坐标取自 React Flow 实时状态，含用户拖拽
 * 后的位置）+ 原生 JS 滚轮缩放/拖拽平移/双击复位。无任何网络请求。
 *
 * 节点尺寸与 LineageGraph 的两行显示规则保持一致：
 * schema 副行 + 表名主行；宽度按字符数估算（与 CSS fit-content 近似）。
 */

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

// 与 LineageGraph 保持一致的几何常量
const MIN_W = 150;
const MAX_W = 300;
const H_SINGLE = 40;
const H_DOUBLE = 52;
// 13px semibold ASCII 字符的近似宽度（px），用于估算 CSS fit-content 的结果
const CHAR_W = 7.8;
const PADDING = 30;

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

interface NodeBox {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  schema: string | null;
  label: string;
  full: string;
  type: string;
}

function buildBoxes(nodes: Node[]): NodeBox[] {
  return nodes.map((n) => {
    const d = n.data as {
      label?: string;
      schema?: string;
      fullName?: string;
      nodeType?: string;
    };
    // 展开态节点（node-sync effect 会把 maxWidth 设为 none + label 换全名）单行显示
    const expanded = (n.style as { maxWidth?: string } | undefined)?.maxWidth === "none";
    const full = d.fullName ?? String(d.label ?? n.id);
    const twoLine = !expanded && !!d.schema;
    const display = expanded ? full : String(d.label ?? full);
    const displayLen = Math.max(display.length, twoLine ? (d.schema ?? "").length : 0);
    const w = Math.min(MAX_W, Math.max(MIN_W, Math.round(displayLen * CHAR_W) + PADDING));
    return {
      id: n.id,
      x: n.position.x,
      y: n.position.y,
      w,
      h: twoLine ? H_DOUBLE : H_SINGLE,
      schema: twoLine ? (d.schema ?? null) : null,
      label: display,
      full,
      type: d.nodeType ?? "",
    };
  });
}

function edgeStroke(e: Edge): string {
  const st = e.style as { stroke?: string } | undefined;
  return st?.stroke || "#8c8c8c";
}

function edgeWidth(e: Edge): number {
  const st = e.style as { strokeWidth?: number } | undefined;
  return st?.strokeWidth || 2;
}

function edgeLabelFill(e: Edge): string {
  const ls = e.labelStyle as { fill?: string } | undefined;
  return ls?.fill || "#333";
}

/** 三次贝塞尔 t=0.5 处的坐标（React Flow 默认边形） */
function bezierMid(p0: number, c1: number, c2: number, p3: number): number {
  return (p0 + 3 * c1 + 3 * c2 + p3) / 8;
}

export function buildStandaloneHtml(nodes: Node[], edges: Edge[], vertical: boolean): string {
  const boxes = buildBoxes(nodes);

  // --- 视口（包围盒 + 留白） ---
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const b of boxes) {
    minX = Math.min(minX, b.x);
    minY = Math.min(minY, b.y);
    maxX = Math.max(maxX, b.x + b.w);
    maxY = Math.max(maxY, b.y + b.h);
  }
  for (const e of edges) {
    const s = boxes.find((b) => b.id === e.source);
    const t = boxes.find((b) => b.id === e.target);
    if (s) { minX = Math.min(minX, s.x); minY = Math.min(minY, s.y); maxX = Math.max(maxX, s.x + s.w); maxY = Math.max(maxY, s.y + s.h); }
    if (t) { minX = Math.min(minX, t.x); minY = Math.min(minY, t.y); maxX = Math.max(maxX, t.x + t.w); maxY = Math.max(maxY, t.y + t.h); }
  }
  const PAD = 60;
  if (!isFinite(minX)) { minX = 0; minY = 0; maxX = 800; maxY = 400; }
  const vx = minX - PAD, vy = minY - PAD;
  const vw = maxX - minX + PAD * 2, vh = maxY - minY + PAD * 2;

  // --- 边（画在节点下层；标签单独分组画在节点上层，避免长标签被节点盖住） ---
  // 每种描边色一个箭头 marker（SVG marker 不继承 stroke）。
  // userSpaceOnUse 固定尺寸：默认 strokeWidth 单位会让高亮粗边(strokeWidth 3)
  // 的箭头放大成大三角
  const strokeColors = [...new Set(edges.map(edgeStroke))];
  const markerIdx = new Map(strokeColors.map((c, i) => [c, i]));
  const markerDefs = strokeColors.map((c, i) =>
    `<marker id="ar${i}" markerWidth="12" markerHeight="12" refX="8.5" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker>`,
  ).join("");

  const edgePaths: string[] = [];
  const edgeLabels: string[] = [];
  for (const e of edges) {
    const s = boxes.find((b) => b.id === e.source);
    const t = boxes.find((b) => b.id === e.target);
    if (!s || !t) continue;
    // 连接点与布局方向一致：TB 源底/目标顶，LR 源右/目标左
    const sx = vertical ? s.x + s.w / 2 : s.x + s.w;
    const sy = vertical ? s.y + s.h : s.y + s.h / 2;
    const tx = vertical ? t.x + t.w / 2 : t.x;
    const ty = vertical ? t.y : t.y + t.h / 2;
    const dist = vertical ? Math.abs(ty - sy) : Math.abs(tx - sx);
    const k = Math.max(30, dist * 0.35);
    // 回边（TB 目标在源上方 / LR 目标在源左侧）控制方向翻转，避免贝塞尔绕成 U 形钩
    const dir = vertical ? (ty >= sy ? 1 : -1) : (tx >= sx ? 1 : -1);
    const c1x = vertical ? sx : sx + k * dir;
    const c1y = vertical ? sy + k * dir : sy;
    const c2x = vertical ? tx : tx - k * dir;
    const c2y = vertical ? ty - k * dir : ty;
    const color = edgeStroke(e);
    const mi = markerIdx.get(color) ?? 0;
    edgePaths.push(
      `<path d="M${sx.toFixed(1)},${sy.toFixed(1)} C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${tx.toFixed(1)},${ty.toFixed(1)}" ` +
      `fill="none" stroke="${color}" stroke-width="${edgeWidth(e)}" marker-end="url(#ar${mi})"/>`,
    );
    const lbl = typeof e.label === "string" ? e.label : "";
    if (lbl) {
      const mx = bezierMid(sx, c1x, c2x, tx);
      const my = bezierMid(sy, c1y, c2y, ty);
      const lw = Math.round(lbl.length * 6.4 + 10);
      const fill = edgeLabelFill(e);
      edgeLabels.push(
        `<rect x="${(mx - lw / 2).toFixed(1)}" y="${(my - 9).toFixed(1)}" width="${lw}" height="18" rx="3" fill="#fff" fill-opacity="0.9"/>` +
        `<text x="${mx.toFixed(1)}" y="${(my + 3.5).toFixed(1)}" text-anchor="middle" font-size="10" font-weight="600" fill="${fill}">${esc(lbl)}</text>`,
      );
    }
  }
  const edgeSvg = edgePaths.join("");
  const edgeLabelSvg = edgeLabels.join("");

  // --- 节点 ---
  const nodeSvg = boxes.map((b) => {
    const fill = NODE_COLORS[b.type] || "#d9d9d9";
    const border = NODE_BORDER_COLORS[b.type] || "#8c8c8c";
    const cx = b.x + b.w / 2;
    let text: string;
    if (b.schema) {
      text =
        `<text x="${cx.toFixed(1)}" y="${(b.y + 19).toFixed(1)}" text-anchor="middle" font-size="10" font-weight="500" fill="rgba(255,255,255,0.85)">${esc(b.schema)}</text>` +
        `<text x="${cx.toFixed(1)}" y="${(b.y + 38).toFixed(1)}" text-anchor="middle" font-size="13" font-weight="600" fill="#fff">${esc(b.label)}</text>`;
    } else {
      text = `<text x="${cx.toFixed(1)}" y="${(b.y + b.h / 2 + 4.5).toFixed(1)}" text-anchor="middle" font-size="13" font-weight="600" fill="#fff">${esc(b.label)}</text>`;
    }
    return (
      `<g><title>${esc(b.full)}</title>` +
      `<rect x="${b.x.toFixed(1)}" y="${b.y.toFixed(1)}" width="${b.w}" height="${b.h}" rx="6" fill="${fill}" stroke="${border}" stroke-width="2"/>` +
      text + `</g>`
    );
  }).join("");

  const ts = new Date().toISOString().slice(0, 19).replace("T", " ");

  return `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LineagePuzzle 血缘图</title>
<style>
  html, body { margin: 0; height: 100%; background: #fff; overflow: hidden;
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
  #bar { position: fixed; top: 0; left: 0; right: 0; z-index: 10; box-sizing: border-box;
    padding: 6px 14px; background: #001529; color: rgba(255,255,255,0.85); font-size: 12px;
    display: flex; align-items: center; gap: 12px; user-select: none; }
  #bar button { background: transparent; color: #fff; border: 1px solid rgba(255,255,255,0.4);
    border-radius: 4px; padding: 1px 10px; font-size: 12px; cursor: pointer; }
  #g { position: absolute; inset: 34px 0 0 0; width: calc(100% ); height: calc(100% - 34px);
    cursor: grab; }
  #g:active { cursor: grabbing; }
</style>
</head>
<body>
<div id="bar"><strong>LineagePuzzle 血缘图</strong><span>${boxes.length} 张表 · ${edges.length} 条血缘 · 导出于 ${ts}</span><span style="opacity:0.55">滚轮缩放 · 拖拽平移 · 双击复位</span><button id="reset">复位</button></div>
<svg id="g" xmlns="http://www.w3.org/2000/svg" viewBox="${vx.toFixed(1)} ${vy.toFixed(1)} ${vw.toFixed(1)} ${vh.toFixed(1)}" preserveAspectRatio="xMidYMid meet">
  <defs>${markerDefs}</defs>
  ${edgeSvg}
  ${nodeSvg}
  ${edgeLabelSvg}
</svg>
<script>
(function () {
  var svg = document.getElementById('g');
  var base = svg.viewBox.baseVal;
  var init = { x: base.x, y: base.y, w: base.width, h: base.height };
  var vb = { x: init.x, y: init.y, w: init.w, h: init.h };
  function apply() { svg.setAttribute('viewBox', vb.x + ' ' + vb.y + ' ' + vb.w + ' ' + vb.h); }
  function reset() { vb = { x: init.x, y: init.y, w: init.w, h: init.h }; apply(); }
  svg.addEventListener('wheel', function (e) {
    e.preventDefault();
    var r = svg.getBoundingClientRect();
    var fx = (e.clientX - r.left) / r.width;
    var fy = (e.clientY - r.top) / r.height;
    var k = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    var nw = vb.w * k, nh = vb.h * k;
    vb.x += fx * (vb.w - nw);
    vb.y += fy * (vb.h - nh);
    vb.w = nw; vb.h = nh;
    apply();
  }, { passive: false });
  var drag = null;
  svg.addEventListener('mousedown', function (e) { drag = { x: e.clientX, y: e.clientY }; e.preventDefault(); });
  window.addEventListener('mousemove', function (e) {
    if (!drag) return;
    var r = svg.getBoundingClientRect();
    vb.x -= (e.clientX - drag.x) * vb.w / r.width;
    vb.y -= (e.clientY - drag.y) * vb.h / r.height;
    drag = { x: e.clientX, y: e.clientY };
    apply();
  });
  window.addEventListener('mouseup', function () { drag = null; });
  svg.addEventListener('dblclick', reset);
  document.getElementById('reset').addEventListener('click', reset);
})();
</script>
</body>
</html>`;
}
