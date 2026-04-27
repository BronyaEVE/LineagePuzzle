import React from "react";
import MonacoEditor from "@monaco-editor/react";
import { Button, Card, Space, Spin } from "antd";

interface Props {
  value: string;
  onChange: (val: string) => void;
  onAnalyze: () => void;
  loading: boolean;
}

const ScriptEditor: React.FC<Props> = ({ value, onChange, onAnalyze, loading }) => {
  return (
    <Card
      title="DML 脚本"
      size="small"
      extra={
        <Space>
          <Button type="primary" onClick={onAnalyze} loading={loading} disabled={!value.trim()}>
            分析血缘
          </Button>
        </Space>
      }
    >
      <MonacoEditor
        height="200px"
        language="sql"
        theme="vs-dark"
        value={value}
        onChange={(v) => onChange(v ?? "")}
        options={{
          minimap: { enabled: false },
          fontSize: 13,
          lineNumbers: "on",
          scrollBeyondLastLine: false,
          wordWrap: "on",
        }}
      />
    </Card>
  );
};

export default ScriptEditor;
