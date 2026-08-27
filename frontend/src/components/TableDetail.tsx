import React, { useEffect, useRef, useState } from "react";
import { Card, Typography, Tag, List, Empty, Drawer, Spin, message } from "antd";
import { FileTextOutlined, ArrowUpOutlined, ArrowDownOutlined } from "@ant-design/icons";
import StatementPanel from "./StatementPanel";
import { getScript } from "../api/client";
import type { AnalysisResult, GlobalEdge, ScriptSummary, VisNode } from "../types";

/**
 * 右栏表详情面板（表为中心导航的配套）。
 *
 * 显示选中表的角色 / 直接上下游计数，以及「相关脚本」——由全局边按
 * source/target 匹配收集 script_id（表为中心改造后，脚本从导航单元降级
 * 为边的溯源信息，从这里下钻）。点击相关脚本 → Drawer 内复用
 * StatementPanel 查看该脚本的语句分段。
 */

const { Text } = Typography;

const ROLE_COLOR: Record<string, string> = {
  source: "green",
  intermediate: "orange",
  target: "blue",
};
const ROLE_LABEL: Record<string, string> = {
  source: "源表",
  intermediate: "中间表",
  target: "目标表",
};

interface Props {
  /** 选中的表集合（多表分析）。空数组 = 空态/全局视图。 */
  tables: string[];
  nodes: VisNode[];
  edges: GlobalEdge[];
  scripts: ScriptSummary[];
}

const TableDetail: React.FC<Props> = ({ tables, nodes, edges, scripts }) => {
  const [drawerScriptId, setDrawerScriptId] = useState<string | null>(null);
  const [drawerResult, setDrawerResult] = useState<AnalysisResult | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  // 竞态防护：只采纳最新一次请求
  const fetchTokenRef = useRef(0);

  // 单表快捷引用；多表时逐表统计
  const table = tables.length === 1 ? tables[0] : "";
  const node = table ? nodes.find((n) => n.id === table) : undefined;

  // 相关脚本：读写任一选中表的脚本（去重，保持边序；多表取并集）
  const relatedScripts = React.useMemo(() => {
    if (tables.length === 0) return [];
    const selected = new Set(tables);
    const ids: string[] = [];
    const seen = new Set<string>();
    for (const e of edges) {
      if (!selected.has(e.source) && !selected.has(e.target)) continue;
      if (!seen.has(e.script_id)) {
        seen.add(e.script_id);
        ids.push(e.script_id);
      }
    }
    const byId = new Map(scripts.map((s) => [s.analysis_id, s]));
    return ids.map((id) => byId.get(id) ?? {
      analysis_id: id, name: id, created_at: "", statement_count: 0, table_count: 0, tags: [],
    });
  }, [edges, scripts, tables]);

  // 每张选中表的直接上下游计数（多表模式逐表展示）。
  // 单趟扫边建度数索引：O(E) 一次，替代逐表 filter 的 O(表数×边数)。
  const degreeIndex = React.useMemo(() => {
    const inDeg = new Map<string, number>();
    const outDeg = new Map<string, number>();
    for (const e of edges) {
      inDeg.set(e.target, (inDeg.get(e.target) ?? 0) + 1);
      outDeg.set(e.source, (outDeg.get(e.source) ?? 0) + 1);
    }
    return { inDeg, outDeg };
  }, [edges]);

  const perTableCounts = React.useMemo(() => {
    return tables.map((t) => ({
      table: t,
      node: nodes.find((n) => n.id === t),
      up: degreeIndex.inDeg.get(t) ?? 0,
      down: degreeIndex.outDeg.get(t) ?? 0,
    }));
  }, [tables, nodes, degreeIndex]);

  const upstreamCount = degreeIndex.inDeg.get(table) ?? 0;
  const downstreamCount = degreeIndex.outDeg.get(table) ?? 0;

  // 打开 Drawer 时拉取脚本详情（语句分段）
  useEffect(() => {
    if (!drawerScriptId) {
      setDrawerResult(null);
      return;
    }
    const token = ++fetchTokenRef.current;
    setDrawerLoading(true);
    setDrawerResult(null);
    getScript(drawerScriptId)
      .then((r) => {
        if (token === fetchTokenRef.current) setDrawerResult(r);
      })
      .catch((e: unknown) => {
        if (token !== fetchTokenRef.current) return;
        message.error(e instanceof Error ? e.message : "加载脚本失败");
      })
      .finally(() => {
        if (token === fetchTokenRef.current) setDrawerLoading(false);
      });
  }, [drawerScriptId]);

  // 相关脚本区块（单表/多表共用；多表为并集）
  const relatedScriptsSection = (
    <div style={{ borderTop: "1px solid #f0f0f0", paddingTop: 8 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>
        相关脚本（{relatedScripts.length}）— 读写{tables.length > 1 ? "任一选中表" : "该表"}的脚本
      </Text>
      {relatedScripts.length === 0 ? (
        <Empty description="无边关联（表仅登记未入边）" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 24 }} />
      ) : (
        <List
          size="small"
          dataSource={relatedScripts}
          style={{ marginTop: 4 }}
          renderItem={(s) => (
            <List.Item
              style={{ cursor: "pointer", padding: "6px 4px" }}
              onClick={() => setDrawerScriptId(s.analysis_id)}
            >
              <List.Item.Meta
                avatar={<FileTextOutlined style={{ color: "#1890ff", fontSize: 15, marginTop: 3 }} />}
                title={<Text style={{ fontSize: 12 }}>{s.name}</Text>}
                description={
                  <span style={{ fontSize: 11, color: "#8c8c8c" }}>
                    {s.statement_count} 条语句
                    {s.tags.length > 0 && ` · ${s.tags.join(", ")}`}
                  </span>
                }
              />
            </List.Item>
          )}
        />
      )}
    </div>
  );

  return (
    <Card
      title={<span style={{ fontSize: 14 }}>表详情{tables.length > 1 ? `（${tables.length} 表）` : ""}</span>}
      size="small"
      style={{ height: "100%", overflow: "auto" }}
      styles={{ body: { padding: 12 } }}
    >
      {tables.length === 0 ? (
        <Empty description="空态：在左侧选择一张或多张表开始分析" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 40 }} />
      ) : tables.length === 1 ? (
        <>
          <Text strong style={{ fontSize: 13, wordBreak: "break-all" }}>{table}</Text>
          <div style={{ marginTop: 8, marginBottom: 12, display: "flex", gap: 12 }}>
            <Tag color={ROLE_COLOR[node?.type ?? ""] ?? "default"}>
              {ROLE_LABEL[node?.type ?? ""] ?? node?.type ?? "未知"}
            </Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              <ArrowUpOutlined /> 上游 {upstreamCount}
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              <ArrowDownOutlined /> 下游 {downstreamCount}
            </Text>
          </div>
          {relatedScriptsSection}
        </>
      ) : (
        <>
          {/* 多表分析：逐表角色 + 直接上下游计数 */}
          <List
            size="small"
            dataSource={perTableCounts}
            renderItem={(t) => (
              <List.Item style={{ padding: "5px 0" }}>
                <div style={{ width: "100%" }}>
                  <Text strong style={{ fontSize: 12, wordBreak: "break-all" }}>{t.table}</Text>
                  <div style={{ marginTop: 2, display: "flex", gap: 10 }}>
                    <Tag color={ROLE_COLOR[t.node?.type ?? ""] ?? "default"} style={{ fontSize: 10, margin: 0 }}>
                      {ROLE_LABEL[t.node?.type ?? ""] ?? t.node?.type ?? "未知"}
                    </Tag>
                    <Text type="secondary" style={{ fontSize: 11 }}><ArrowUpOutlined /> {t.up}</Text>
                    <Text type="secondary" style={{ fontSize: 11 }}><ArrowDownOutlined /> {t.down}</Text>
                  </div>
                </div>
              </List.Item>
            )}
          />
          {relatedScriptsSection}
        </>
      )}

      <Drawer
        title={drawerResult?.name ?? "脚本语句"}
        placement="right"
        width={420}
        open={Boolean(drawerScriptId)}
        onClose={() => setDrawerScriptId(null)}
      >
        {drawerLoading ? (
          <div style={{ textAlign: "center", marginTop: 60 }}><Spin /></div>
        ) : drawerResult ? (
          <StatementPanel
            statementGroup={drawerResult.statement_group}
            highlightSeq={null}
            onStatementClick={() => {}}
          />
        ) : (
          <Empty description="无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Drawer>
    </Card>
  );
};

export default TableDetail;
