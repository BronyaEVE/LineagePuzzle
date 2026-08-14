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
  /** 选中表名；GLOBAL_ID/空 表示全局视图（无详情）。 */
  table: string;
  nodes: VisNode[];
  edges: GlobalEdge[];
  scripts: ScriptSummary[];
}

const TableDetail: React.FC<Props> = ({ table, nodes, edges, scripts }) => {
  const [drawerScriptId, setDrawerScriptId] = useState<string | null>(null);
  const [drawerResult, setDrawerResult] = useState<AnalysisResult | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  // 竞态防护：只采纳最新一次请求
  const fetchTokenRef = useRef(0);

  const node = nodes.find((n) => n.id === table);

  // 相关脚本：读写该表的脚本（去重，保持边序）
  const relatedScripts = React.useMemo(() => {
    const ids: string[] = [];
    const seen = new Set<string>();
    for (const e of edges) {
      if (e.source !== table && e.target !== table) continue;
      if (!seen.has(e.script_id)) {
        seen.add(e.script_id);
        ids.push(e.script_id);
      }
    }
    const byId = new Map(scripts.map((s) => [s.analysis_id, s]));
    return ids.map((id) => byId.get(id) ?? {
      analysis_id: id, name: id, created_at: "", statement_count: 0, table_count: 0, tags: [],
    });
  }, [edges, scripts, table]);

  const upstreamCount = edges.filter((e) => e.target === table).length;
  const downstreamCount = edges.filter((e) => e.source === table).length;

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

  return (
    <Card
      title={<span style={{ fontSize: 14 }}>表详情</span>}
      size="small"
      style={{ height: "100%", overflow: "auto" }}
      styles={{ body: { padding: 12 } }}
    >
      {!table ? (
        <Empty description="全局视图：在左侧选择一张表查看详情" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 40 }} />
      ) : (
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

          <div style={{ borderTop: "1px solid #f0f0f0", paddingTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              相关脚本（{relatedScripts.length}）— 读写该表的脚本
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
