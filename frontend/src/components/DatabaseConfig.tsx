import React from "react";
import { Form, Input, InputNumber, Card } from "antd";
import type { DatabaseConfig as DatabaseConfigType } from "../types";

interface Props {
  value: DatabaseConfigType;
  onChange: (val: DatabaseConfigType) => void;
}

const DatabaseConfigForm: React.FC<Props> = ({ value, onChange }) => {
  const handleChange = (field: keyof DatabaseConfigType, val: string | number) => {
    onChange({ ...value, [field]: val });
  };

  return (
    <Card title="数据库配置" size="small" style={{ marginBottom: 12 }}>
      <Form layout="inline" size="small">
        <Form.Item label="主机">
          <Input
            value={value.host}
            onChange={(e) => handleChange("host", e.target.value)}
            style={{ width: 120 }}
          />
        </Form.Item>
        <Form.Item label="端口">
          <InputNumber
            value={value.port}
            onChange={(v) => handleChange("port", v ?? 5432)}
            style={{ width: 80 }}
          />
        </Form.Item>
        <Form.Item label="数据库">
          <Input
            value={value.database}
            onChange={(e) => handleChange("database", e.target.value)}
            style={{ width: 120 }}
          />
        </Form.Item>
        <Form.Item label="用户名">
          <Input
            value={value.username}
            onChange={(e) => handleChange("username", e.target.value)}
            style={{ width: 100 }}
          />
        </Form.Item>
        <Form.Item label="密码">
          <Input.Password
            value={value.password}
            onChange={(e) => handleChange("password", e.target.value)}
            style={{ width: 100 }}
          />
        </Form.Item>
      </Form>
    </Card>
  );
};

export default DatabaseConfigForm;
