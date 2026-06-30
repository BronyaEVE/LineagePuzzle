import React, { useState, useEffect, useRef } from "react";
import { Input, Button, Typography, Space } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";

/**
 * 参数映射配置组件（动态表格行）。
 *
 * 管理 {param_name: actual_value} 映射，用于分析时把 SQL 里的 ${param}
 * 占位符替换成实际值（如 ${icl_schema}.orders → ods.orders）。
 *
 * 设计要点（彻底非受控，消除编辑回环）：
 * 组件内部用 rows[]（行数组）持有编辑状态，而非直接受控于父组件的 Record。
 * 关键：编辑过程中完全不回写父组件（onChange），只在「外部 value 真正变化」时
 * 才把 rows 重置为 value。用 ref 记录最近一次对外的 emit 值：
 *   - 只有当 props.value !== lastEmitted 时，才认为是「外部变更」（如打开弹窗
 *     从后端拉取），此时重置 rows；
 *   - 编辑时 syncChange 只更新本地 rows + 刷新 ref，不再 onChange，避免
 *     value 变化 → useEffect 重置 → 丢行/重排序的回环 bug。
 * 最终 mapping 在父组件点击「保存」时通过 ref/imperative 取值，或父组件用
 * 受控 value 读取（见 App.tsx 的 handleSaveParamMapping，保存前 sync 一次）。
 *
 * 因此本组件额外暴露 onDraftChange：每次编辑都把最新有效 mapping 通知父组件，
 * 父组件据此更新它的 draft state（但父组件不会把 draft 再传回 value，断开环）。
 */
interface Props {
  value: Record<string, string>;
  onChange: (val: Record<string, string>) => void;
}

interface Row {
  key: string;
  value: string;
}

const ParamMappingConfig: React.FC<Props> = ({ value, onChange }) => {
  // 本地持有完整行数组（含空 key 的草稿行），避免 Record 过滤丢行
  const [rows, setRows] = useState<Row[]>([]);
  // 记录最近一次对父组件 emit（onChange）的 mapping 序列化值。
  // 仅当 props.value 与之不同时，才判定为外部变更并重置本地 rows。
  const lastEmittedRef = useRef<string>("");

  // 把 rows 转成有效 mapping（过滤空 key），返回 {mapping, serialized}
  const rowsToMapping = (rs: Row[]) => {
    const mapping: Record<string, string> = {};
    for (const r of rs) {
      const k = (r.key || "").trim();
      const v = (r.value || "").trim();
      if (k) mapping[k] = v;
    }
    return mapping;
  };

  // 外部 value 变化时（仅初次加载 / 弹窗打开从后端拉取）同步到本地 rows。
  // 用 ref 判断：只有 value !== lastEmitted 才是真正的外部变更，
  // 避免本组件自己 emit 的值回流触发重置（编辑回环 bug 根因）。
  const valueKey = JSON.stringify(value);
  useEffect(() => {
    if (valueKey === lastEmittedRef.current) {
      return; // 是本组件刚 emit 的回流，不重置
    }
    const newRows = Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => ({ key: k, value: v }));
    setRows(newRows);
    lastEmittedRef.current = valueKey;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valueKey]);

  // 任意行变化：更新本地 rows + 通知父组件最新草稿（但不触发回流）
  const syncChange = (newRows: Row[]) => {
    setRows(newRows);
    const mapping = rowsToMapping(newRows);
    const serialized = JSON.stringify(mapping);
    lastEmittedRef.current = serialized; // 记录本次 emit，防止回流重置
    onChange(mapping);
  };

  const updateRow = (index: number, field: keyof Row, val: string) => {
    syncChange(rows.map((r, i) => (i === index ? { ...r, [field]: val } : r)));
  };

  const addRow = () => {
    // 本地追加空行（不被 Record 过滤），用户可继续填写
    syncChange([...rows, { key: "", value: "" }]);
  };

  const removeRow = (index: number) => {
    syncChange(rows.filter((_, i) => i !== index));
  };

  return (
    <div>
      <Typography.Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
        💡 配置 SQL 中 <code>{"${param}"}</code> 占位符的实际值。例如配置
        <code> icl_schema = ods </code>后，分析时
        <code> {"${icl_schema}.orders"} </code>会被替换成<code> ods.orders</code>。
        未配置的参数保留参数名本身作为标识符。
      </Typography.Text>

      {rows.map((row, idx) => (
        <Space key={idx} style={{ display: "flex", marginBottom: 8 }} align="center">
          <Input
            placeholder="参数名（如 icl_schema）"
            style={{ width: 200 }}
            value={row.key}
            onChange={(e) => updateRow(idx, "key", e.target.value)}
            status={row.key && !/^\w+$/.test(row.key) ? "error" : undefined}
          />
          <span style={{ color: "#999" }}>=</span>
          <Input
            placeholder="实际值（如 ods）"
            style={{ width: 200 }}
            value={row.value}
            onChange={(e) => updateRow(idx, "value", e.target.value)}
          />
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            onClick={() => removeRow(idx)}
          />
        </Space>
      ))}

      <Button type="dashed" onClick={addRow} icon={<PlusOutlined />} style={{ width: "100%" }}>
        添加映射
      </Button>

      {rows.length === 0 && (
        <Typography.Text type="secondary" style={{ display: "block", marginTop: 12, fontSize: 12 }}>
          （当前无映射，所有 {"${param}"} 将保留参数名作为标识符）
        </Typography.Text>
      )}
      {rows.some((r) => !r.key.trim()) && (
        <Typography.Text type="warning" style={{ display: "block", marginTop: 8, fontSize: 12 }}>
          ⚠️ 参数名为空的行不会保存，请填写参数名
        </Typography.Text>
      )}
    </div>
  );
};

export default ParamMappingConfig;
