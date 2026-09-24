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
  type: "node" | "edge" | "field";
  id: string;
  // field 类型：该字段命中的全部边 id（全局视图的 ge-N 编号）
  edgeIds?: string[];
  // field 类型：命中的 (source,target) 对。边 id 编号随视图不同（全局 ge-N /
  // 子图 e-M），(source,target) 对才是视图无关的标识；两路都带上，命中其一即可
  edgePairs?: [string, string][];
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
  /** 只搜字段（表.列）。表搜索由左侧表列表负责——顶部再搜表是重复入口 */
  fieldsOnly?: boolean;
  onSelectTarget: (target: SearchTarget) => void;
}

const SearchBox: React.FC<Props> = ({ nodes, edges, fieldsOnly, onSelectTarget }) => {
  const options = useMemo<SearchOption[]>(() => {
    const opts: SearchOption[] = [];
    const seen = new Set<string>();

    if (!fieldsOnly) {
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
    }

    // 字段搜索：按「表.列」聚合（血缘最小语义单位是具体的列，不是裸列名）。
    // orders.id 和 users.id 是两个不同的字段，必须分开；但 orders.id 流转到
    // 多张表（作为多条边的源列）时合并为一个结果，高亮全部相关边。
    // fieldMap 键 = `${table}.${col}`，值 = { table, col, 命中的边 }
    interface FieldAgg {
      table: string;
      col: string;
      edges: Set<string>;
      pairs: Set<string>;
    }
    const fieldMap = new Map<string, FieldAgg>();
    const addField = (table: string, col: string, edgeId: string, pair: [string, string]) => {
      if (!col) return;
      const key = `${table}.${col}`;
      let agg = fieldMap.get(key);
      if (!agg) { agg = { table, col, edges: new Set(), pairs: new Set() }; fieldMap.set(key, agg); }
      agg.edges.add(edgeId);
      agg.pairs.add(`${pair[0]}|${pair[1]}`);
    };
    for (const e of edges) {
      const edgeId = e._edgeId || `${e.source}->${e.target}`;
      const pair: [string, string] = [e.source, e.target];
      for (const m of e.column_mappings || []) {
        if (m.target_column) addField(m.target_table, m.target_column, edgeId, pair);
        for (const sc of m.source_columns) {
          addField(m.source_table, sc, edgeId, pair);
        }
      }
    }
    for (const [, agg] of fieldMap) {
      const key = `field:${agg.table}.${agg.col}`;
      const cnt = agg.edges.size;
      // value 用完整 table.col：选中后输入框回填完整名（与 label 一致），
      // 模糊匹配 filterOption 用 includes，输列名/表名/全名都能命中。
      const qualified = `${agg.table}.${agg.col}`;
      const pairs: [string, string][] = [...agg.pairs].map((p) => {
        const i = p.indexOf("|");
        return [p.slice(0, i), p.slice(i + 1)];
      });
      opts.push({
        key,
        value: qualified,
        label: (
          <span>
            <span style={{ color: "#722ed1", marginRight: 6 }}>◇</span>
            {qualified}
            {cnt > 1 && (
              <span style={{ color: "#999", marginLeft: 6, fontSize: 12 }}>
                ({cnt} 条流转)
              </span>
            )}
          </span>
        ),
        target: { type: "field", id: qualified, edgeIds: [...agg.edges], edgePairs: pairs },
      });
    }
    return opts;
  }, [nodes, edges, fieldsOnly]);

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
        placeholder={fieldsOnly ? "搜索字段（表.列）" : "搜索表名/字段名"}
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
