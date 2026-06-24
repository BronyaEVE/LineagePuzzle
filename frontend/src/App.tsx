import { useState, useEffect, useCallback } from "react";
import { ConfigProvider, Layout, Button, Modal, message, Tag, Space } from "antd";
import { PlusOutlined, SettingOutlined } from "@ant-design/icons";
import ScriptList from "./components/ScriptList";
import ScriptEditor from "./components/ScriptEditor";
import DatabaseConfigForm from "./components/DatabaseConfig";
import StatementPanel from "./components/StatementPanel";
import LineageGraph from "./components/LineageGraph";
import ParamMappingConfig from "./components/ParamMappingConfig";
import {
  submitAnalysis, listScripts, getScript, deleteScript,
  renameScript, getGlobalGraph, getParamMapping, setParamMapping,
} from "./api/client";
import type {
  DatabaseConfig as DatabaseConfigType, AnalysisResult,
  ScriptSummary, GlobalGraph,
} from "./types";

const { Header, Content } = Layout;

function App() {
  // === 状态 ===
  const [scripts, setScripts] = useState<ScriptSummary[]>([]);
  const [globalGraph, setGlobalGraph] = useState<GlobalGraph | null>(null);
  const [selectedScriptId, setSelectedScriptId] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<AnalysisResult | null>(null);
  const [highlightSeq, setHighlightSeq] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  // 新建分析的表单状态
  const [script, setScript] = useState("");
  const [dbConfig, setDbConfig] = useState<DatabaseConfigType>({
    host: "localhost", port: 5432, database: "", username: "", password: "",
  });

  // 参数映射配置（${param} → 实际值，全局生效）
  // paramMapping 是本地编辑草稿，setParamMappingDraft 更新草稿；
  // 保存时调 import 的 setParamMapping（API）推送到后端
  const [paramModalOpen, setParamModalOpen] = useState(false);
  const [paramMapping, setParamMappingDraft] = useState<Record<string, string>>({});
  const [paramLoading, setParamLoading] = useState(false);

  // === 加载数据 ===
  const refreshAll = useCallback(async () => {
    const [s, g] = await Promise.all([listScripts(), getGlobalGraph()]);
    setScripts(s);
    setGlobalGraph(g);
  }, []);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  // === 选中脚本 ===
  const handleSelectScript = useCallback(async (id: string | null) => {
    setSelectedScriptId(id);
    setHighlightSeq(null);
    if (id) {
      const result = await getScript(id);
      setSelectedResult(result);
    } else {
      setSelectedResult(null);
    }
  }, []);

  // === 新建分析 ===
  const handleAnalyze = async () => {
    setLoading(true);
    try {
      // 库名为空 → 离线模式（纯 AST 分析，不连数据库）
      // 库名是连库的最小必要条件（host 有默认 localhost，但库名必须用户指定）
      const hasDbConfig = Boolean(dbConfig.database?.trim());
      const result = await submitAnalysis({
        script,
        database_config: hasDbConfig ? dbConfig : null,
      });
      message.success(
        result.extraction_mode === "ast_only"
          ? "分析完成（离线模式）"
          : "分析完成（已连接数据库校验）"
      );
      setScript("");
      setModalOpen(false);
      await refreshAll();
    } catch (e: any) {
      message.error(e.message || "分析失败");
    } finally {
      setLoading(false);
    }
  };

  // === 删除脚本 ===
  const handleDelete = async (id: string) => {
    try {
      await deleteScript(id);
      message.success("已删除");
      if (selectedScriptId === id) {
        setSelectedScriptId(null);
        setSelectedResult(null);
      }
      await refreshAll();
    } catch (e: any) {
      message.error(e.message);
    }
  };

  // === 重命名 ===
  const handleRename = async (id: string, name: string) => {
    try {
      await renameScript(id, name);
      await refreshAll();
    } catch (e: any) {
      message.error(e.message);
    }
  };

  // === 参数映射：打开时拉取，保存时推送 ===
  const handleOpenParamMapping = async () => {
    setParamModalOpen(true);
    try {
      const mapping = await getParamMapping();
      setParamMappingDraft(mapping);
    } catch (e: any) {
      message.error(e.message || "获取参数映射失败");
    }
  };

  const handleSaveParamMapping = async () => {
    setParamLoading(true);
    try {
      await setParamMapping(paramMapping);
      message.success("参数映射已保存");
      setParamModalOpen(false);
    } catch (e: any) {
      message.error(e.message || "保存参数映射失败");
    } finally {
      setParamLoading(false);
    }
  };

  // === 状态栏统计 ===
  const tableCount = globalGraph?.nodes.length ?? 0;
  const edgeCount = globalGraph?.edges.length ?? 0;
  const scriptCount = scripts.length;

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#1890ff" } }}>
      <Layout style={{ minHeight: "100vh" }}>
        <Header style={{ background: "#001529", padding: "0 24px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ color: "#fff", fontSize: 18, fontWeight: 600 }}>
            DataLineage Visualizer
          </div>
          <Space>
            <Button
              icon={<SettingOutlined />}
              onClick={handleOpenParamMapping}
              style={{ background: "transparent", color: "#fff", borderColor: "rgba(255,255,255,0.3)" }}
            >
              参数映射
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setModalOpen(true)}
            >
              新建分析
            </Button>
          </Space>
        </Header>

        <Content style={{ padding: 12, background: "#f5f5f5", flex: 1 }}>
          <div style={{ display: "flex", gap: 12, height: "calc(100vh - 100px)" }}>
            {/* 左栏：脚本列表 */}
            <div style={{ width: 240, flexShrink: 0 }}>
              <ScriptList
                scripts={scripts}
                selectedId={selectedScriptId}
                onSelect={handleSelectScript}
                onDelete={handleDelete}
                onRename={handleRename}
              />
            </div>

            {/* 中栏：全局血缘图 */}
            <div style={{ flex: 1 }}>
              <LineageGraph
                globalGraph={globalGraph}
                visualization={selectedResult?.visualization ?? null}
                highlightScriptId={selectedScriptId}
                highlightSeq={highlightSeq}
                onEdgeSelectSeq={setHighlightSeq}
              />
            </div>

            {/* 右栏：语句分段 */}
            <div style={{ width: 320, flexShrink: 0 }}>
              <StatementPanel
                statementGroup={selectedResult?.statement_group ?? null}
                highlightSeq={highlightSeq}
                onStatementClick={setHighlightSeq}
              />
            </div>
          </div>

          {/* 状态栏 */}
          <div style={{
            marginTop: 8, padding: "6px 12px", background: "#fff",
            borderRadius: 4, fontSize: 12, color: "#666",
            display: "flex", gap: 16,
          }}>
            <Tag color="green">{tableCount} 张表</Tag>
            <Tag color="blue">{edgeCount} 条血缘</Tag>
            <Tag color="orange">{scriptCount} 个脚本</Tag>
          </div>
        </Content>
      </Layout>

      {/* 新建分析弹窗 */}
      <Modal
        title="新建分析"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={800}
        destroyOnHidden
      >
        <DatabaseConfigForm value={dbConfig} onChange={setDbConfig} />
        <ScriptEditor
          value={script}
          onChange={setScript}
          onAnalyze={handleAnalyze}
          loading={loading}
        />
      </Modal>

      {/* 参数映射弹窗 */}
      <Modal
        title="参数映射配置"
        open={paramModalOpen}
        onCancel={() => setParamModalOpen(false)}
        onOk={handleSaveParamMapping}
        confirmLoading={paramLoading}
        okText="保存"
        cancelText="取消"
        width={560}
        destroyOnHidden
      >
        <ParamMappingConfig value={paramMapping} onChange={setParamMappingDraft} />
      </Modal>
    </ConfigProvider>
  );
}

export default App;
