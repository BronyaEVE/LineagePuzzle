import { useState } from "react";
import { ConfigProvider, Layout, message, Alert } from "antd";
import DatabaseConfigForm from "./components/DatabaseConfig";
import ScriptEditor from "./components/ScriptEditor";
import StatementPanel from "./components/StatementPanel";
import LineageGraph from "./components/LineageGraph";
import { submitAnalysis } from "./api/client";
import type { DatabaseConfig as DatabaseConfigType, AnalysisResult } from "./types";

const { Header, Content } = Layout;

function App() {
  const [script, setScript] = useState("");
  const [dbConfig, setDbConfig] = useState<DatabaseConfigType>({
    host: "localhost",
    port: 5432,
    database: "",
    username: "",
    password: "",
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [highlightSeq, setHighlightSeq] = useState<number | null>(null);

  const handleAnalyze = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await submitAnalysis({ script, database_config: dbConfig });
      setResult(res);
      message.success("分析完成");
    } catch (e: any) {
      setError(e.message || "分析失败");
      message.error(e.message || "分析失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#1890ff" } }}>
      <Layout style={{ minHeight: "100vh" }}>
        <Header style={{ background: "#001529", padding: "0 24px" }}>
          <div style={{ color: "#fff", fontSize: 18, fontWeight: 600, lineHeight: "64px" }}>
            DataLineage Visualizer
          </div>
        </Header>
        <Content style={{ padding: 16, background: "#f5f5f5" }}>
          {/* 上半部分：配置 + 脚本输入 */}
          <DatabaseConfigForm value={dbConfig} onChange={setDbConfig} />
          <ScriptEditor
            value={script}
            onChange={setScript}
            onAnalyze={handleAnalyze}
            loading={loading}
          />

          {error && (
            <Alert
              message="分析错误"
              description={error}
              type="error"
              closable
              style={{ marginTop: 12 }}
              onClose={() => setError(null)}
            />
          )}

          {/* 下半部分：血缘图 + 语句面板 */}
          {result && (
            <div style={{ display: "flex", gap: 12, marginTop: 12 }}>
              <div style={{ flex: 2 }}>
                <LineageGraph
                  visualization={result.visualization}
                  highlightSeq={highlightSeq}
                />
              </div>
              <div style={{ flex: 1, maxHeight: "calc(100vh - 420px)", overflow: "auto" }}>
                <StatementPanel
                  statementGroup={result.statement_group}
                  highlightSeq={highlightSeq}
                  onStatementClick={setHighlightSeq}
                />
              </div>
            </div>
          )}
        </Content>
      </Layout>
    </ConfigProvider>
  );
}

export default App;
