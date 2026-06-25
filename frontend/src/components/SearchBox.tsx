import React, { useMemo } from "react";
import { AutoComplete, Input } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import type { VisNode, ColumnMapping } from "../types";

/**
 * 搜索框：模糊匹配表名和字段名，选中后聚焦+高亮对应节点或边。
 *
 * 数据拍平：
 *   - 每个 node（表）生成一条「表」备选项
 *   - 每条 edge 的 column_mappings 里的 target_column / source_columns 生成「字段」备选项
 * 选中表 → 聚焦该节点；选中字段 → 聚焦该字段所在边（source+target 两端）
 */

/** 搜索选中后的目标（由 App 传给 LineageGraph 执行聚焦+高亮） */
export interface SearchTarget {
  type: "node" | "edge";
  id: string;  // node: node.id；edge: `${source}->${target}` 组合标识
}

interface Option {
  value: string;       // 模糊匹配用的文本（表名或字段名）
  label: React.ReactNode;
  target: SearchTarget;
}

/** SearchBox 需要的边结构（VisEdge/GlobalEdge 的共同子集 + 可选 _edgeId） */
interface SearchEdge {
  source: string;
  target: string;
  column_mappings?: ColumnMapping[];
  _edgeId?: string;
}

interface Props {
  nodes: VisNode[];
  edges: SearchEdge[];
  onSelectTarget: (target: SearchTarget) => void;
}

const SearchBox: React.FC<Props> = ({ nodes, edges, onSelectTarget }) => {
  // 拍平数据成备选项，按 value 去重
  const options = useMemo<Option[]>(() => {
    const opts: Option[] = [];
    const seen = new Set<string>();

    // 表节点
    for (const n of nodes) {
      const key = `table:${n.id}`;
      if (!seen.has(key)) {
        seen.add(key);
        opts.push({
          value: n.id,
          label: (
            <span>
              <span style={{ color: "#52c41a" }}>●</span> 表 {n.id}
            </span>
          ),
          target: { type: "node", id: n.id },
        });
      }
    }

    // 字段（从 edges 的 column_mappings 收集）
    for (const e of edges) {
      const edgeId = e._edgeId || `${e.source}->${e.target}`;
      const mappings = e.column_mappings || [];
      for (const m of mappings) {
        // target_column
        const tgtKey = `col:${m.target_table}.${m.target_column}`;
        if (m.target_column && !seen.has(tgtKey)) {
          seen.add(tgtKey);
          opts.push({
            value: m.target_column,
            label: (
              <span>
                <span style={{ color: "#1890ff" }}>◆</span> 列 {m.target_table}.{m.target_column}
              </span>
            ),
            target: { type: "edge", id: edgeId },
          });
        }
        // source_columns
        for (const sc of m.source_columns) {
          const srcKey = `col:${m.source_table}.${sc}`;
          if (sc && !seen.has(srcKey)) {
            seen.add(srcKey);
            opts.push({
              value: sc,
              label: (
                <span>
                  <span style={{ color: "#722ed1" }}>◇</span> 列 {m.source_table}.{sc}
                </span>
              ),
              target: { type: "edge", id: edgeId },
            });
          }
        }
      }
    }

    return opts;
  }, [nodes, edges]);

  return (
    <>
      {/* 深色 Header 下的样式：钉成和按钮一样高（32px），用 flex 居中避免 line-height 错位 */}
      <style>{`
        /* 约束整个 AutoComplete 外层及各层高度，和按钮（32px）一致 */
        .header-search.ant-select {
          height: 32px !important;
        }
        .header-search .ant-select-selector {
          background: rgba(255,255,255,0.08) !important;
          border-color: rgba(255,255,255,0.3) !important;
          height: 32px !important;
          min-height: 32px !important;
          padding-top: 0 !important;
          padding-bottom: 0 !important;
          display: flex !important;
          align-items: center !important;
        }
        .header-search .ant-select-selection-search,
        .header-search .ant-select-selection-search-input {
          height: 30px !important;
          margin: 0 !important;
          display: flex !important;
          align-items: center !important;
        }
        .header-search .ant-select-selection-placeholder {
          color: rgba(255,255,255,0.45) !important;
          display: flex !important;
          align-items: center !important;
          height: 30px !important;
        }
        .header-search input {
          color: #fff !important;
          height: 30px !important;
        }
        .header-search .ant-select-suffix {
          color: rgba(255,255,255,0.5) !important;
          align-self: center !important;
        }
        .header-search .anticon-search {
          color: rgba(255,255,255,0.5) !important;
        }
        .header-search:hover .ant-select-selector {
          border-color: rgba(255,255,255,0.5) !important;
        }
      `}</style>
    <AutoComplete
      style={{ width: 220 }}
      rootClassName="header-search"
      options={options}
      // 大小写不敏感子串匹配
      filterOption={(input, option) => {
        if (!input || !option) return true;
        const val = (option.value as string).toLowerCase();
        return val.includes(input.toLowerCase());
      }}
      onSelect={(_, option) => {
        const target = (option as unknown as { target?: SearchTarget }).target;
        if (target) onSelectTarget(target);
      }}
      allowClear
      // 下拉面板用默认白底（避免被 Header 深色背景影响）
      popupClassName="search-dropdown"
      >
      <Input
        prefix={<SearchOutlined />}
        placeholder="搜索表名/字段名"
      />
    </AutoComplete>
    </>
  );
};

export default SearchBox;
