import React, { useMemo } from "react";
import { AutoComplete } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import type { VisNode, ColumnMapping } from "../types";

/**
 * 搜索框：模糊匹配表名和字段名，选中后聚焦+高亮对应节点或边。
 *
 * 关键设计：不使用自定义 <Input> 子元素（antd issue #52551：自定义 Input 时
 * AutoComplete wrapper 保持固定高度，size/CSS 高度都压不住）。改用 options 模式，
 * AutoComplete 用内置输入框，高度由 antd 默认 size=middle 控制（32px，和按钮一致）。
 */

export interface SearchTarget {
  type: "node" | "edge";
  id: string;
}

/** 带业务元数据的 option（antd option 的扩展） */
interface SearchOption {
  value: string;        // 模糊匹配 + 选中后的值（表名或字段名）
  label: React.ReactNode;
  target: SearchTarget; // 选中后聚焦目标
  key: string;
}

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
  const options = useMemo<SearchOption[]>(() => {
    const opts: SearchOption[] = [];
    const seen = new Set<string>();

    for (const n of nodes) {
      const key = `table:${n.id}`;
      if (!seen.has(key)) {
        seen.add(key);
        opts.push({
          key,
          value: n.id,
          label: (
            <span>
              <span style={{ color: "#52c41a", marginRight: 6 }}>●</span>
              {n.id}
            </span>
          ),
          target: { type: "node", id: n.id },
        });
      }
    }

    for (const e of edges) {
      const edgeId = e._edgeId || `${e.source}->${e.target}`;
      for (const m of e.column_mappings || []) {
        if (m.target_column) {
          const k = `col:t:${m.target_table}.${m.target_column}`;
          if (!seen.has(k)) {
            seen.add(k);
            opts.push({
              key: k,
              value: m.target_column,
              label: (
                <span>
                  <span style={{ color: "#1890ff", marginRight: 6 }}>◆</span>
                  {m.target_table}.{m.target_column}
                </span>
              ),
              target: { type: "edge", id: edgeId },
            });
          }
        }
        for (const sc of m.source_columns) {
          const k = `col:s:${m.source_table}.${sc}`;
          if (sc && !seen.has(k)) {
            seen.add(k);
            opts.push({
              key: k,
              value: sc,
              label: (
                <span>
                  <span style={{ color: "#722ed1", marginRight: 6 }}>◇</span>
                  {m.source_table}.{sc}
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
      {/*
        深色 Header 适配：只调颜色，高度交给 antd 默认（middle=32px）。
        不用自定义 <Input> 子元素（#52551 会导致 wrapper 高度固定不可调）。
        suffixIcon 放搜索图标。
      */}
      <style>{`
        .header-search .ant-select-selector {
          background: rgba(255,255,255,0.08) !important;
          border: 1px solid rgba(255,255,255,0.3) !important;
        }
        .header-search .ant-select-selection-search-input {
          color: #fff !important;
        }
        .header-search .ant-select-selection-placeholder {
          color: rgba(255,255,255,0.45) !important;
        }
        .header-search .ant-select-arrow {
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
        suffixIcon={<SearchOutlined />}
        placeholder="搜索表名/字段名"
        filterOption={(input, option) => {
          if (!input) return true;
          const val = String((option as SearchOption).value).toLowerCase();
          return val.includes(input.toLowerCase());
        }}
        onSelect={(_, option) => {
          const target = (option as unknown as { target?: SearchTarget }).target;
          if (target) onSelectTarget(target);
        }}
        allowClear
      />
    </>
  );
};

export default SearchBox;
