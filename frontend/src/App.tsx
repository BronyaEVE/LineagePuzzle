import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { ConfigProvider, Layout, Button, Modal, message, Tag, Space, Popconfirm } from "antd";
import { PlusOutlined, SettingOutlined, DownloadOutlined, UploadOutlined } from "@ant-design/icons";
import ScriptList from "./components/ScriptList";
import ScriptEditor from "./components/ScriptEditor";
import DatabaseConfigForm from "./components/DatabaseConfig";
import StatementPanel from "./components/StatementPanel";
import LineageGraph from "./components/LineageGraph";
import type { FocusTarget } from "./components/LineageGraph";
import SearchBox, { type SearchTarget } from "./components/SearchBox";
import ParamMappingConfig from "./components/ParamMappingConfig";
import {
  submitAnalysis, listScripts, getScript, deleteScript,
  renameScript, getGlobalGraph, getParamMapping, setParamMapping,
  exportData, importData,
} from "./api/client";
import type {
  DatabaseConfig as DatabaseConfigType, AnalysisResult,
  ScriptSummary, GlobalGraph,
} from "./types";

const { Header, Content } = Layout;

/** 从 catch 块的 unknown 值安全提取错误消息，兜底返回默认文案。 */
function errMsg(e: unknown, fallback: string): string {
  return e instanceof Error ? (e.message || fallback) : fallback;
}

function App() {
  // === 状态 ===
  const [scripts, setScripts] = useState<ScriptSummary[]>([]);
  const [globalGraph, setGlobalGraph] = useState<GlobalGraph | null>(null);
  const [selectedScriptId, setSelectedScriptId] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<AnalysisResult | null>(null);
  const [highlightSeq, setHighlightSeq] = useState<number | null>(null);

  // 搜索框选中后聚焦目标（传给 LineageGraph 执行 fitView + 高亮）
  const [focusTarget, setFocusTarget] = useState<FocusTarget | null>(null);
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
    try {
      const [s, g] = await Promise.all([listScripts(), getGlobalGraph()]);
      setScripts(s);
      setGlobalGraph(g);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "加载数据失败";
      message.error(msg);
    }
  }, []);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  // 选中脚本的请求竞态防护：每次点击递增 token，只有最新请求的响应会被采纳
  const selectTokenRef = useRef(0);

  // === 选中脚本 ===
  const handleSelectScript = useCallback(async (id: string | null) => {
    setSelectedScriptId(id);
    setHighlightSeq(null);
    // 立即清空旧结果，避免切换过程中显示上一个脚本的数据（视觉错乱）
    setSelectedResult(null);
    if (!id) {
      return;
    }
    const myToken = ++selectTokenRef.current;
    try {
      const result = await getScript(id);
      // 过期响应丢弃：用户可能已点了另一个脚本
      if (myToken !== selectTokenRef.current) return;
      setSelectedResult(result);
    } catch (e: unknown) {
      if (myToken !== selectTokenRef.current) return;
      const msg = e instanceof Error ? e.message : "加载脚本失败";
      message.error(msg);
      // 加载失败，回滚选中状态
      setSelectedScriptId(null);
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
    } catch (e: unknown) {
      message.error(errMsg(e, "分析失败"));
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
    } catch (e: unknown) {
      message.error(errMsg(e, "删除脚本失败"));
    }
  };

  // === 重命名 ===
  const handleRename = async (id: string, name: string) => {
    try {
      await renameScript(id, name);
      await refreshAll();
    } catch (e: unknown) {
      message.error(errMsg(e, "重命名失败"));
    }
  };

  // === 参数映射：打开时拉取，保存时推送 ===
  const handleOpenParamMapping = async () => {
    setParamModalOpen(true);
    try {
      const mapping = await getParamMapping();
      setParamMappingDraft(mapping);
    } catch (e: unknown) {
      message.error(errMsg(e, "获取参数映射失败"));
    }
  };

  const handleSaveParamMapping = async () => {
    setParamLoading(true);
    try {
      await setParamMapping(paramMapping);
      message.success({
        content: "参数映射已保存。重新分析脚本后，新映射才会生效（已有脚本的节点不会自动更新）",
        duration: 5,
      });
      setParamModalOpen(false);
    } catch (e: unknown) {
      message.error(errMsg(e, "保存参数映射失败"));
    } finally {
      setParamLoading(false);
    }
  };

  // === 导入导出 ===
  const handleExport = async () => {
    try {
      const data = await exportData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      a.href = url;
      a.download = `lineage-export-${ts}.json`;
      a.click();
      URL.revokeObjectURL(url);
      message.success("导出成功");
    } catch (e: unknown) {
      message.error(errMsg(e, "导出失败"));
    }
  };

  const handleImport = async (file: File) => {
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      await importData(payload);
      message.success("导入成功，数据已覆盖");
      await refreshAll();
    } catch (e: unknown) {
      message.error(errMsg(e, "导入失败，请检查文件格式"));
    }
  };

  // === 状态栏统计 ===
  const tableCount = globalGraph?.nodes.length ?? 0;
  const edgeCount = globalGraph?.edges.length ?? 0;
  const scriptCount = scripts.length;

  // 搜索框的节点/边数据（useMemo 化，避免每次渲染重建数组击穿 SearchBox 内部 useMemo）。
  // 边加 _edgeId 前缀（e- 脚本视图 / ge- 全局视图），与 LineageGraph 实际渲染的边 id 一致。
  const searchNodes = useMemo(
    () => (selectedScriptId ? selectedResult?.visualization.nodes : globalGraph?.nodes) || [],
    [selectedScriptId, selectedResult, globalGraph],
  );
  const searchEdges = useMemo(
    () =>
      (selectedScriptId
        ? selectedResult?.visualization.edges?.map((e, i) => ({ ...e, _edgeId: `e-${i}` }))
        : globalGraph?.edges?.map((e, i) => ({ ...e, _edgeId: `ge-${i}` }))) || [],
    [selectedScriptId, selectedResult, globalGraph],
  );

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#1890ff" } }}>
      <Layout style={{ minHeight: "100vh" }}>
        <Header style={{ background: "#001529", padding: "0 24px", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
          <div style={{ color: "#fff", fontSize: 18, fontWeight: 600 }}>
            DataLineage Visualizer
          </div>
          <Space>
            <Button
              icon={<DownloadOutlined />}
              onClick={handleExport}
              style={{ background: "transparent", color: "#fff", borderColor: "rgba(255,255,255,0.3)" }}
            >
              导出
            </Button>
            <Popconfirm
              title="导入会覆盖当前所有数据"
              description="确定继续吗？"
              onConfirm={() => {
                // 触发隐藏的 file input
                document.getElementById("import-file-input")?.click();
              }}
              okText="确定覆盖"
              cancelText="取消"
            >
              <Button
                icon={<UploadOutlined />}
                style={{ background: "transparent", color: "#fff", borderColor: "rgba(255,255,255,0.3)" }}
              >
                导入
              </Button>
            </Popconfirm>
            {/* 隐藏的文件选择器，由 Popconfirm 确认后触发 */}
            <input
              id="import-file-input"
              type="file"
              accept=".json"
              style={{ display: "none" }}
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) await handleImport(f);
                e.target.value = "";  // 重置，允许重复选同一文件
              }}
            />
            <SearchBox
              nodes={searchNodes}
              edges={searchEdges}
              onSelectTarget={(t: SearchTarget) => {
                setFocusTarget(t);
              }}
            />
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
                focusTarget={focusTarget}
                onImpactTrigger={() => handleSelectScript(null)}
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
