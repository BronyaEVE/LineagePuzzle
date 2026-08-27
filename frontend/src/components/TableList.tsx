import React, { useMemo, useState } from "react";
import { Card, List, Typography, Button, Input, Tag, Checkbox, Popover, Empty } from "antd";
import {
  GlobalOutlined, TableOutlined, SearchOutlined, FilterOutlined,
  ArrowUpOutlined, ArrowDownOutlined,
} from "@ant-design/icons";
import type { GlobalEdge, TagSchema, VisNode } from "../types";
import { GLOBAL_ID } from "../types";

/**
 * 左栏表列表（实体为中心的导航入口）。
 *
 * 表为中心改造后：脚本不再是主导航单元，左栏列出全局图谱里的表。
 * 每项显示角色（source/intermediate/target，配色与血缘图一致）和
 * 直接上游/下游边数；点击选中 → 中栏显示该表的邻域子图。
 * 置顶「全局图谱」虚拟项保留全局视图入口。
 *
 * 标签筛选：脚本标签投影到表 —— 表被任一命中脚本读写即命中（近似：表
 * 显示所有贡献脚本标签的并集语义，用于灰显而非精确过滤）。
 */

const { Text } = Typography;

// 角色 → 配色（与血缘图节点一致：source 绿 / intermediate 橙 / target 蓝）
const ROLE_COLOR: Record<string, string> = {
  source: "green",
  intermediate: "orange",
  target: "blue",
};
const ROLE_LABEL: Record<string, string> = {
  source: "源",
  intermediate: "中间",
  target: "目标",
};

interface Props {
  nodes: VisNode[];
  edges: GlobalEdge[];
  /** 当前选中的表集合（多表分析）。 */
  selectedTables: string[];
  /** 点击表 → App 切换该表的选中态（toggle）；GLOBAL_ID → 全局图谱。 */
  onSelect: (id: string) => void;
  /** 清空多选（回到空态，不进全局）。 */
  onClearSelection: () => void;
  /** 全局图谱是否激活（选中集为空且显式打开全局时）。 */
  globalActive: boolean;
  tagSchema: TagSchema;
  selectedTags: string[];
  onSelectedTagsChange: (tags: string[]) => void;
  /** 命中筛选的脚本 id 集合（App 计算；投影到表用于灰显）。 */
  hitScriptIds: Set<string>;
}

const TableList: React.FC<Props> = ({
  nodes, edges, selectedTables, onSelect, onClearSelection, globalActive,
  tagSchema, selectedTags, onSelectedTagsChange, hitScriptIds,
}) => {
  const [keyword, setKeyword] = useState("");

  // 每张表的直接上游（入边）/下游（出边）计数
  const counts = useMemo(() => {
    const c = new Map<string, { up: number; down: number }>();
    for (const n of nodes) c.set(n.id, { up: 0, down: 0 });
    for (const e of edges) {
      const t = c.get(e.target);
      if (t) t.up += 1;
      const s = c.get(e.source);
      if (s) s.down += 1;
    }
    return c;
  }, [nodes, edges]);

  // 标签投影：命中脚本读写的表集合（无筛选时为空 → 不灰显）
  const hitTableIds = useMemo(() => {
    if (selectedTags.length === 0 || hitScriptIds.size === 0) return new Set<string>();
    const s = new Set<string>();
    for (const e of edges) {
      if (hitScriptIds.has(e.script_id)) {
        s.add(e.source);
        s.add(e.target);
      }
    }
    return s;
  }, [edges, hitScriptIds, selectedTags.length]);

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    const list = kw
      ? nodes.filter((n) => n.id.toLowerCase().includes(kw))
      : nodes;
    return list;
  }, [nodes, keyword]);

  const toggleFilterTag = (tag: string) => {
    if (selectedTags.includes(tag)) {
      onSelectedTagsChange(selectedTags.filter((t) => t !== tag));
    } else {
      onSelectedTagsChange([...selectedTags, tag]);
    }
  };

  const renderFilterContent = () => (
    <div style={{ width: 240, maxHeight: 320, overflowY: "auto", padding: "4px 0" }}>
      {tagSchema.dimensions.map((dim) => (
        <div key={dim.name} style={{ marginBottom: 8, padding: "0 8px" }}>
          <div style={{ fontSize: 12, color: "#666", marginBottom: 4, fontWeight: 600 }}>{dim.name}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 8px" }}>
            {dim.values.map((v) => (
              <Checkbox
                key={v}
                checked={selectedTags.includes(v)}
                onChange={() => toggleFilterTag(v)}
                style={{ fontSize: 12 }}
              >
                {v}
              </Checkbox>
            ))}
          </div>
        </div>
      ))}
    </div>
  );

  const hasFilter = selectedTags.length > 0;

  return (
    <Card
      title={
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>
            表列表 ({nodes.length})
            {selectedTables.length > 0 && (
              <Tag color="blue" style={{ marginLeft: 6, fontSize: 11 }}>已选 {selectedTables.length}</Tag>
            )}
          </span>
          <span>
            {selectedTables.length > 0 && (
              <Button size="small" type="text" onClick={onClearSelection} style={{ fontSize: 12, color: "#999", marginRight: 4 }}>
                清空
              </Button>
            )}
            {tagSchema.dimensions.length > 0 && (
              <Popover content={renderFilterContent()} trigger="click" placement="bottomLeft">
                <Button
                  size="small"
                  type="text"
                  icon={<FilterOutlined />}
                  style={{ color: hasFilter ? "#1890ff" : "#999", fontSize: 12 }}
                >
                  筛选{hasFilter ? ` (${selectedTags.length})` : ""}
                </Button>
              </Popover>
            )}
          </span>
        </div>
      }
      size="small"
      style={{ height: "100%", overflow: "auto" }}
      styles={{ body: { padding: 0 } }}
    >
      {/* 搜索框 */}
      <div style={{ padding: "8px 12px", borderBottom: "1px solid #f0f0f0" }}>
        <Input
          size="small"
          allowClear
          prefix={<SearchOutlined style={{ color: "#999" }} />}
          placeholder="搜索表名（schema.table）"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        {hasFilter && (
          <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: 2 }}>
            {selectedTags.map((t) => (
              <Tag
                key={t}
                color="purple"
                closable
                onClose={() => toggleFilterTag(t)}
                style={{ fontSize: 10, margin: 0 }}
              >
                {t}
              </Tag>
            ))}
          </div>
        )}
      </div>

      {/* 全局图谱虚拟项（置顶，非默认：显式点击进入；小图默认全局） */}
      <List.Item
        onClick={() => onSelect(GLOBAL_ID)}
        style={{
          cursor: "pointer", padding: "8px 12px",
          background: globalActive ? "#e6f7ff" : undefined,
        }}
      >
        <List.Item.Meta
          avatar={<GlobalOutlined style={{ color: "#1890ff", fontSize: 18, marginTop: 4 }} />}
          title={<Text strong={globalActive} style={{ fontSize: 13 }}>全局图谱</Text>}
          description={
            <Text type="secondary" style={{ fontSize: 11 }}>
              {nodes.length} 张表 · {edges.length} 条血缘
            </Text>
          }
        />
      </List.Item>

      {nodes.length === 0 ? (
        <Empty description="暂无表" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 40 }} />
      ) : (
        <List
          size="small"
          dataSource={filtered}
          style={{ maxHeight: "calc(100vh - 320px)", overflow: "auto" }}
          renderItem={(item) => {
            // 多选语义：点击 toggle 选中态；已选项加序号徽标
            const selIdx = selectedTables.indexOf(item.id);
            const isSelected = selIdx >= 0;
            const dimmed = hasFilter && !hitTableIds.has(item.id);
            const c = counts.get(item.id) ?? { up: 0, down: 0 };
            return (
              <List.Item
                onClick={() => onSelect(item.id)}
                style={{
                  cursor: "pointer", padding: "7px 12px",
                  background: isSelected ? "#e6f7ff" : undefined,
                  opacity: dimmed ? 0.4 : 1,
                }}
              >
                <List.Item.Meta
                  avatar={<TableOutlined style={{ color: "#8c8c8c", fontSize: 16, marginTop: 3 }} />}
                  title={
                    <Text strong={isSelected} style={{ fontSize: 12 }} ellipsis={{ tooltip: item.id }}>
                      {isSelected && (
                        <Tag color="blue" style={{ fontSize: 10, margin: 0, marginRight: 4, lineHeight: "16px" }}>
                          {selIdx + 1}
                        </Tag>
                      )}
                      {item.id}
                    </Text>
                  }
                  description={
                    <span style={{ fontSize: 11 }}>
                      <Tag color={ROLE_COLOR[item.type] ?? "default"} style={{ fontSize: 10, margin: 0, marginRight: 6 }}>
                        {ROLE_LABEL[item.type] ?? item.type}
                      </Tag>
                      <span style={{ color: "#8c8c8c", marginRight: 8 }} title="直接上游表数">
                        <ArrowUpOutlined /> {c.up}
                      </span>
                      <span style={{ color: "#8c8c8c" }} title="直接下游表数">
                        <ArrowDownOutlined /> {c.down}
                      </span>
                    </span>
                  }
                />
              </List.Item>
            );
          }}
        />
      )}
    </Card>
  );
};

export default TableList;
