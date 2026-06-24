import React, { useState, useEffect } from "react";
import { Input, Button, Typography, Space } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";

/**
 * 参数映射配置组件（动态表格行）。
 *
 * 管理 {param_name: actual_value} 映射，用于分析时把 SQL 里的 ${param}
 * 占位符替换成实际值（如 ${icl_schema}.orders → ods.orders）。
 *
 * 设计要点：组件内部用 rows[]（行数组）持有编辑状态，而非直接受控于
 * 父组件的 Record。原因：Record 无法表示"空 key 的草稿行"（空 key 会被
 * 过滤），导致"添加映射"按钮点击后新行被吞掉。改为本地 state 持有完整
 * 行数组（含空行），只在加载时从 Record 初始化、保存时转回 Record。
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

  // 外部 value 变化时（如初次加载从后端拉取）同步到本地 rows
  // 用 value 的序列化做依赖，避免对象引用变化导致重复重置（丢失用户正在编辑的草稿）
  const valueKey = JSON.stringify(value);
  useEffect(() => {
    const newRows = Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => ({ key: k, value: v }));
    setRows(newRows);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valueKey]);

  // 任意行变化时：更新本地 rows + 把有效行（非空 key）转成 Record 通知父组件
  const syncChange = (newRows: Row[]) => {
    setRows(newRows);
    const mapping: Record<string, string> = {};
    for (const r of newRows) {
      const k = (r.key || "").trim();
      const v = (r.value || "").trim();
      if (k) mapping[k] = v;  // 只把有效行（非空 key）传给父组件
    }
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
