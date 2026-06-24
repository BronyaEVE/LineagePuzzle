import React, { useEffect } from "react";
import { Form, Input, Button, Typography, Space } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";

/**
 * 参数映射配置组件（动态表格行）。
 *
 * 管理 {param_name: actual_value} 映射，用于分析时把 SQL 里的 ${param}
 * 占位符替换成实际值（如 ${icl_schema}.orders → ods.orders）。
 *
 * 受控组件：value 是 Record<string,string>，onChange 回传修改后的 Record。
 * 内部把 Record 转成 [{key, value}] 数组供 Form.List 编辑。
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
  const [form] = Form.useForm();

  // Record → 行数组（key 排序，便于稳定展示）
  const rows: Row[] = Object.entries(value)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => ({ key: k, value: v }));

  // 外部 value 变化时同步到表单（如初次加载从后端拉取）
  useEffect(() => {
    form.setFieldsValue({ mappings: rows });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // 行变化时：把整个表单的行数组转回 Record，通知父组件
  const emitChange = (newRows: Row[]) => {
    const mapping: Record<string, string> = {};
    for (const r of newRows) {
      const k = (r.key || "").trim();
      const v = (r.value || "").trim();
      if (k) mapping[k] = v;  // 跳过空 key
    }
    onChange(mapping);
  };

  const updateRow = (index: number, field: keyof Row, val: string) => {
    const newRows = rows.map((r, i) => (i === index ? { ...r, [field]: val } : r));
    emitChange(newRows);
  };

  const addRow = () => {
    emitChange([...rows, { key: "", value: "" }]);
  };

  const removeRow = (index: number) => {
    emitChange(rows.filter((_, i) => i !== index));
  };

  return (
    <div>
      <Typography.Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
        💡 配置 SQL 中 <code>{"${param}"}</code> 占位符的实际值。例如配置
        <code> icl_schema = ods </code>后，分析时
        <code> {"${icl_schema}.orders"} </code>会被替换成<code> ods.orders</code>。
        未配置的参数保留参数名本身作为标识符。
      </Typography.Text>

      <Form form={form} layout="vertical">
        <Form.List name="mappings">
          {(fields) => (
            <>
              {fields.map((field, idx) => (
                <Space key={field.key} style={{ display: "flex", marginBottom: 8 }} align="center">
                  <Form.Item
                    {...field}
                    name={[field.name, "key"]}
                    style={{ marginBottom: 0 }}
                    rules={[
                      { pattern: /^\w*$/, message: "仅允许字母数字下划线" },
                    ]}
                  >
                    <Input
                      placeholder="参数名（如 icl_schema）"
                      style={{ width: 200 }}
                      onChange={(e) => updateRow(idx, "key", e.target.value)}
                    />
                  </Form.Item>
                  <span style={{ color: "#999" }}>=</span>
                  <Form.Item
                    {...field}
                    name={[field.name, "value"]}
                    style={{ marginBottom: 0 }}
                  >
                    <Input
                      placeholder="实际值（如 ods）"
                      style={{ width: 200 }}
                      onChange={(e) => updateRow(idx, "value", e.target.value)}
                    />
                  </Form.Item>
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => removeRow(idx)}
                    disabled={fields.length === 0}
                  />
                </Space>
              ))}
              <Button type="dashed" onClick={addRow} icon={<PlusOutlined />} style={{ width: "100%" }}>
                添加映射
              </Button>
            </>
          )}
        </Form.List>
      </Form>

      {Object.keys(value).length === 0 && (
        <Typography.Text type="secondary" style={{ display: "block", marginTop: 12, fontSize: 12 }}>
          （当前无映射，所有 {"${param}"} 将保留参数名作为标识符）
        </Typography.Text>
      )}
    </div>
  );
};

export default ParamMappingConfig;
