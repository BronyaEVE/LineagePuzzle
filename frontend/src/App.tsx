import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { ConfigProvider, Layout, Button, Modal, message, Tag, Space, Popconfirm, Segmented } from "antd";
import { PlusOutlined, SettingOutlined, DownloadOutlined, UploadOutlined, TagsOutlined, FolderOpenOutlined } from "@ant-design/icons";
import TableList from "./components/TableList";
import TableDetail from "./components/TableDetail";
import ScriptManagerModal from "./components/ScriptManagerModal";
import ScriptEditor from "./components/ScriptEditor";
import DatabaseConfigForm from "./components/DatabaseConfig";
import LineageGraph from "./components/LineageGraph";
import type { FocusTarget } from "./components/LineageGraph";
import ColumnTrace from "./components/ColumnTrace";
import SearchBox, { type SearchTarget } from "./components/SearchBox";
import PreprocessRulesConfig from "./components/PreprocessRulesConfig";
import TagSchemaConfig from "./components/TagSchemaConfig";
import BatchImport from "./components/BatchImport";
import {
  submitAnalysis, listScripts, deleteScript,
  renameScript, getGlobalGraph, getPreprocessRules, setPreprocessRules,
  exportData, importData,
  getTagSchema, setTagSchema as apiSetTagSchema,
  setScriptTags as apiSetScriptTags, batchSetScriptTags,
} from "./api/client";
import type {
  DatabaseConfig as DatabaseConfigType,
  ScriptSummary, GlobalGraph, PreprocessRule, GlobalEdge, Visualization,
  TagSchema, TagDimension,
} from "./types";
import { GLOBAL_ID } from "./types";

const { Header, Content } = Layout;

/** 从 catch 块的 unknown 值安全提取错误消息，兜底返回默认文案。 */
function errMsg(e: unknown, fallback: string): string {
  return e instanceof Error ? (e.message || fallback) : fallback;
}

function App() {
  // === 状态 ===
  const [scripts, setScripts] = useState<ScriptSummary[]>([]);
  const [globalGraph, setGlobalGraph] = useState<GlobalGraph | null>(null);
  // 表为中心导航（多表分析）：选中的表集合；空 = 空态/全局。脚本不再是导航单元。
  const [selectedTables, setSelectedTables] = useState<string[]>([]);
  // 全局图谱显式开关：null = 未定（图加载后按规模自动决定：小图默认全局，大图空态）
  const [showGlobal, setShowGlobal] = useState<boolean | null>(null);
  // 表邻域子图深度（跳数）
  const [subgraphDepth, setSubgraphDepth] = useState<number>(2);
  // 脚本管理弹窗（上传/重命名/删除/打标的归置地）
  const [scriptMgrOpen, setScriptMgrOpen] = useState(false);

  // 搜索框选中后聚焦目标（传给 LineageGraph 执行 fitView + 高亮）
  const [focusTarget, setFocusTarget] = useState<FocusTarget | null>(null);
  // 中栏视图：血缘图（节点-连线）/ 列级追溯（文本树，question-driven）
  const [view, setView] = useState<"graph" | "trace">("graph");
  const [modalOpen, setModalOpen] = useState(false);
  // 新建分析弹窗的输入模式：手动粘贴 SQL / 批量导入文件
  const [analyzeMode, setAnalyzeMode] = useState<"manual" | "batch">("manual");
  const [loading, setLoading] = useState(false);

  // 新建分析的表单状态
  const [script, setScript] = useState("");
  const [dbConfig, setDbConfig] = useState<DatabaseConfigType>({
    host: "localhost", port: 5432, database: "", username: "", password: "",
  });

  // 预处理规则配置（参数映射 + 自定义清洗，统一为正则替换规则）
  // preprocessRules 是本地编辑草稿；保存时调 setPreprocessRules（API）推送到后端
  const [rulesModalOpen, setRulesModalOpen] = useState(false);
  const [preprocessRules, setPreprocessRulesDraft] = useState<PreprocessRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(false);

  // 标签维度定义 + 选中筛选标签（扁平集合）。
  // 维度信息外置在 tagSchema，脚本只存扁平 tags 数组，筛选时按维度分组做命中判断。
  const [tagSchema, setTagSchema] = useState<TagSchema>({ dimensions: [] });
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  // 标签维度设置弹窗的编辑草稿 + 开关
  const [tagSchemaModalOpen, setTagSchemaModalOpen] = useState(false);
  const [tagSchemaDraft, setTagSchemaDraft] = useState<TagDimension[]>([]);
  const [tagSchemaSaving, setTagSchemaSaving] = useState(false);

  // === 加载数据 ===
  const refreshAll = useCallback(async () => {
    try {
      const [s, g, ts] = await Promise.all([listScripts(), getGlobalGraph(), getTagSchema()]);
      setScripts(s);
      setGlobalGraph(g);
      setTagSchema(ts);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "加载数据失败";
      message.error(msg);
    }
  }, []);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  // 搜索聚焦 token：每次搜索选中递增，附加到 FocusTarget 上保证 effect 重跑，
  // 解决连续两次搜同一目标（值相同）时不重新聚焦的问题。
  const focusTokenRef = useRef(0);

  // === 选中表（主导航动作，多选 toggle）===
  // GLOBAL_ID → 全局图谱（清空选择，显式打开全局）
  // 表 id → toggle 选中态（多表分析：合并邻域子图）；任一表选中即退出全局
  const handleSelectTable = useCallback((id: string) => {

    setFocusTarget(null);
    if (id === GLOBAL_ID) {
      setSelectedTables([]);
      setShowGlobal(true);
      return;
    }
    setSelectedTables((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]
    );
    setShowGlobal(false);
  }, []);

  // 清空多选（回到空态，不进全局）
  const handleClearSelection = useCallback(() => {
    setSelectedTables([]);
    setShowGlobal(false);

    setFocusTarget(null);
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

  // === 标签：单个脚本打标 ===
  const handleSetScriptTags = async (id: string, tags: string[]) => {
    try {
      await apiSetScriptTags(id, tags);
      // 本地更新 scripts 的 tags（避免整页 refresh）
      setScripts((prev) => prev.map((s) => s.analysis_id === id ? { ...s, tags } : s));
    } catch (e: unknown) {
      message.error(errMsg(e, "打标签失败"));
    }
  };

  // === 标签：批量打标 ===
  const handleBatchSetTags = async (ids: string[], tags: string[]) => {
    try {
      const result = await batchSetScriptTags(ids, tags);
      // 本地更新命中的脚本 tags
      const updatedSet = new Set(result.updated);
      setScripts((prev) => prev.map((s) => updatedSet.has(s.analysis_id) ? { ...s, tags } : s));
      if (result.failed.length > 0) {
        message.warning(`${result.updated.length} 个成功，${result.failed.length} 个失败`);
      } else {
        message.success(`已为 ${result.updated.length} 个脚本打标`);
      }
    } catch (e: unknown) {
      message.error(errMsg(e, "批量打标失败"));
    }
  };

  // isGlobalView：未选表且显式打开全局（全局图谱已降级为非默认视图）
  const isGlobalView = selectedTables.length === 0 && showGlobal === true;

  // 智能落地视图：图加载后未显式选择时 —— 小图（≤50 节点，可读）默认全局，
  // 大图默认空态（全局大图是发面饼，不该作为落地视图）
  useEffect(() => {
    if (showGlobal === null && globalGraph !== null) {
      setShowGlobal(globalGraph.nodes.length <= 50);
    }
  }, [globalGraph, showGlobal]);

  // 筛选命中脚本 id 集合（语义丙：维度内 OR、维度间 AND）。
  // 有筛选标签时计算；无筛选时返回空 Set（调用方据此判断「不筛选」）。
  // 实现思路：把选中的扁平标签按维度分组（查 tagSchema 得到每个标签所属维度），
  // 对每个维度，脚本须含该维度下任意一个选中标签；所有维度都满足才命中。
  const hitScriptIds = useMemo(() => {
    if (selectedTags.length === 0) return new Set<string>();
    // 标签值 → 所属维度名（一个标签值只属一个维度；若跨维度重名，取第一个）
    const tagToDim = new Map<string, string>();
    for (const dim of tagSchema.dimensions) {
      for (const v of dim.values) {
        if (!tagToDim.has(v)) tagToDim.set(v, dim.name);
      }
    }
    // 选中的标签按维度分组
    const selectedByDim = new Map<string, Set<string>>();
    for (const t of selectedTags) {
      const dim = tagToDim.get(t);
      if (!dim) continue; // 孤儿标签（维度已删），忽略
      let set = selectedByDim.get(dim);
      if (!set) { set = new Set(); selectedByDim.set(dim, set); }
      set.add(t);
    }
    const requiredDims = [...selectedByDim.keys()];
    if (requiredDims.length === 0) return new Set<string>();
    const hit = new Set<string>();
    for (const s of scripts) {
      // 每个维度内：脚本的 tags 与该维度选中标签有交集即满足
      const allDimsSatisfied = requiredDims.every((dim) => {
        const wanted = selectedByDim.get(dim)!;
        return s.tags.some((t) => wanted.has(t));
      });
      if (allDimsSatisfied) hit.add(s.analysis_id);
    }
    return hit;
  }, [scripts, selectedTags, tagSchema]);

  // === 预处理规则：打开时拉取，保存时推送 ===
  const handleOpenRules = async () => {
    setRulesModalOpen(true);
    try {
      const rules = await getPreprocessRules();
      setPreprocessRulesDraft(rules);
    } catch (e: unknown) {
      message.error(errMsg(e, "获取预处理规则失败"));
    }
  };

  const handleSaveRules = async () => {
    setRulesLoading(true);
    try {
      await setPreprocessRules(preprocessRules);
      message.success({
        content: "预处理规则已保存。重新分析脚本后，新规则才会生效（已有脚本的节点不会自动更新）",
        duration: 5,
      });
      setRulesModalOpen(false);
    } catch (e: unknown) {
      message.error(errMsg(e, "保存预处理规则失败"));
    } finally {
      setRulesLoading(false);
    }
  };

  // === 标签维度定义：打开时拉取当前 schema 作为草稿，保存时推送 ===
  const handleOpenTagSchema = async () => {
    setTagSchemaModalOpen(true);
    // 用已加载的 tagSchema 作为草稿初值（App 启动时已 refreshAll 拉过）
    setTagSchemaDraft(tagSchema.dimensions.map((d) => ({ ...d, values: [...d.values] })));
    // 兜底：再拉一次最新值（避免本地 tagSchema 是旧缓存）
    try {
      const fresh = await getTagSchema();
      setTagSchemaDraft(fresh.dimensions.map((d) => ({ ...d, values: [...d.values] })));
    } catch (e: unknown) {
      // 拉取失败不阻塞，用本地缓存值
    }
  };

  const handleSaveTagSchema = async () => {
    setTagSchemaSaving(true);
    try {
      const updated = await apiSetTagSchema({ dimensions: tagSchemaDraft });
      setTagSchema(updated);
      // 维度变更后，已有但失效的筛选标签（孤儿）清掉，避免命中集合异常
      const validTags = new Set<string>();
      for (const dim of updated.dimensions) for (const v of dim.values) validTags.add(v);
      setSelectedTags((prev) => prev.filter((t) => validTags.has(t)));
      message.success("标签维度已保存");
      setTagSchemaModalOpen(false);
    } catch (e: unknown) {
      message.error(errMsg(e, "保存标签维度失败"));
    } finally {
      setTagSchemaSaving(false);
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

  // === 表邻域子图（多表分析：选中集合的合并邻域）===
  // 选中表集合 → emphasizedNodes（useMemo：内联 new Set 会让每次 App 渲染
  // 都产生新引用，击穿 LineageGraph 的 node-sync effect 引用稳定优化）
  const emphasizedTables = useMemo(() => new Set(selectedTables), [selectedTables]);

  // 客户端 BFS：每张选中表的上游祖先 + 下游后代，限深 subgraphDepth 跳，取并集。
  // 单表是 N=1 特例。全局边数 ~2.5k，BFS 开销可忽略；
  // 复用 LineageGraph 的 visualization 渲染模式。
  const tableSubgraph = useMemo<Visualization | null>(() => {
    if (!globalGraph || selectedTables.length === 0) return null;
    const edges = globalGraph.edges as GlobalEdge[];
    // 邻接表
    const outMap = new Map<string, GlobalEdge[]>();
    const inMap = new Map<string, GlobalEdge[]>();
    for (const e of edges) {
      let a = outMap.get(e.source); if (!a) { a = []; outMap.set(e.source, a); } a.push(e);
      let b = inMap.get(e.target); if (!b) { b = []; inMap.set(e.target, b); } b.push(e);
    }
    // BFS 收集 depth 跳内的祖先/后代节点（多根并集）
    const included = new Set<string>(selectedTables);
    const bfs = (start: string, map: Map<string, GlobalEdge[]>) => {
      let frontier = [start];
      for (let d = 0; d < subgraphDepth && frontier.length > 0; d++) {
        const next: string[] = [];
        for (const t of frontier) {
          for (const e of map.get(t) ?? []) {
            const n = e.source === t ? e.target : e.source;
            if (!included.has(n)) { included.add(n); next.push(n); }
          }
        }
        frontier = next;
      }
    };
    for (const root of selectedTables) {
      bfs(root, outMap); // 下游
      bfs(root, inMap);  // 上游
    }
    // 节点：从全局图取角色；边：两端都在集合内的全局边（完整展示子图内交叉血缘）
    const nodeById = new Map(globalGraph.nodes.map((n) => [n.id, n]));
    const nodes = [...included]
      .filter((id) => nodeById.has(id))
      .map((id) => nodeById.get(id)!);
    const subEdges = edges
      .filter((e) => included.has(e.source) && included.has(e.target))
      .map((e) => ({
        source: e.source,
        target: e.target,
        label: e.operation,
        statement_seq: e.statement_seq,
        column_mappings: e.column_mappings,
      }));
    return { nodes, edges: subEdges };
  }, [globalGraph, selectedTables, subgraphDepth]);

  // 搜索框的节点/边数据（始终全局图；表为中心后无单脚本视图）。
  // 边加 _edgeId 前缀，与 LineageGraph 全局视图渲染的边 id 一致。
  const searchNodes = useMemo(() => globalGraph?.nodes ?? [], [globalGraph]);
  const searchEdges = useMemo(
    () => globalGraph?.edges?.map((e, i) => ({ ...e, _edgeId: `ge-${i}` })) ?? [],
    [globalGraph],
  );

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#1890ff" } }}>
      <Layout style={{ minHeight: "100vh" }}>
        <Header style={{ background: "#001529", padding: "0 24px", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
          <div style={{ color: "#fff", fontSize: 18, fontWeight: 600 }}>
            LineagePuzzle
          </div>
          <Space>
            <Segmented
              value={view}
              onChange={(v) => setView(v as "graph" | "trace")}
              options={[
                { label: "血缘图", value: "graph" },
                { label: "列级追溯", value: "trace" },
              ]}
            />
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
                // 递增 token：即使连续两次搜同一目标，新 FocusTarget 引用不同，
                // effect [focusTarget] 也会重跑，避免「重复搜索无反馈」。
                const focusToken = ++focusTokenRef.current;
                if (t.type === "node") {
                  // 搜表 = 导航动作：直接选中该表（进入其邻域子图）并聚焦
                  setSelectedTables((prev) => (prev.includes(t.id) ? prev : [...prev, t.id]));
                  setShowGlobal(false);
                } else if (!isGlobalView && selectedTables.length === 0) {
                  // 边/字段目标需要完整图上下文：空态时切到全局视图
                  setShowGlobal(true);
                }
                setFocusTarget({
                  type: t.type,
                  id: t.id,
                  focusToken,
                  edgeIds: t.edgeIds,
                });
              }}
            />
            <Button
              icon={<SettingOutlined />}
              onClick={handleOpenRules}
              style={{ background: "transparent", color: "#fff", borderColor: "rgba(255,255,255,0.3)" }}
            >
              预处理规则
            </Button>
            <Button
              icon={<TagsOutlined />}
              onClick={handleOpenTagSchema}
              style={{ background: "transparent", color: "#fff", borderColor: "rgba(255,255,255,0.3)" }}
            >
              标签维度
            </Button>
            <Button
              icon={<FolderOpenOutlined />}
              onClick={() => setScriptMgrOpen(true)}
              style={{ background: "transparent", color: "#fff", borderColor: "rgba(255,255,255,0.3)" }}
            >
              脚本管理
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
            {/* 左栏：表列表（表为中心导航，多表分析） */}
            <div style={{ width: 260, flexShrink: 0 }}>
              <TableList
                nodes={globalGraph?.nodes ?? []}
                edges={globalGraph?.edges ?? []}
                selectedTables={selectedTables}
                onSelect={handleSelectTable}
                onClearSelection={handleClearSelection}
                globalActive={isGlobalView}
                tagSchema={tagSchema}
                selectedTags={selectedTags}
                onSelectedTagsChange={setSelectedTags}
                hitScriptIds={hitScriptIds}
              />
            </div>

            {/* 中栏：血缘图 / 列级追溯（视图切换） */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
              {/* 子图深度选择（有选中表 + 血缘图模式） */}
              {selectedTables.length > 0 && view === "graph" && (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Segmented
                    size="small"
                    value={subgraphDepth}
                    onChange={(v) => setSubgraphDepth(v as number)}
                    options={[
                      { label: "1 跳", value: 1 },
                      { label: "2 跳", value: 2 },
                      { label: "3 跳", value: 3 },
                    ]}
                  />
                  <span style={{ fontSize: 12, color: "#999" }}>
                    {selectedTables.length === 1
                      ? `${selectedTables[0]} 的邻域子图（上游 + 下游）`
                      : `${selectedTables.length} 张表的合并邻域子图`}
                  </span>
                </div>
              )}
              <div style={{ flex: 1, minHeight: 0 }}>
                {view === "trace" ? (
                  <ColumnTrace
                    initialTable={selectedTables.length > 0 ? selectedTables[selectedTables.length - 1] : null}
                  />
                ) : isGlobalView ? (
                  <LineageGraph
                    globalGraph={globalGraph}
                    visualization={null}
                    viewMode={"global" as const}
                    focusTarget={focusTarget}
                    // 标签筛选：仅全局视图 + 有筛选标签时传命中脚本集合，否则 null（不过滤）
                    tagFilteredScriptIds={selectedTags.length > 0 ? hitScriptIds : null}
                  />
                ) : selectedTables.length > 0 ? (
                  <LineageGraph
                    globalGraph={null}
                    visualization={tableSubgraph}
                    viewMode={"subgraph" as const}
                    focusTarget={focusTarget}
                    emphasizedNodes={emphasizedTables}
                  />
                ) : (
                  <div style={{
                    height: "100%", display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center", gap: 8,
                    background: "#fafafa", borderRadius: 4,
                  }}>
                    <div style={{ fontSize: 15, color: "#555" }}>从左侧选择一张或多张表开始分析</div>
                    <div style={{ fontSize: 12, color: "#999" }}>
                      多选可查看合并邻域（表间关联）；大图请用搜索定位
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* 右栏：表详情（角色/上下游计数/相关脚本下钻；多表为汇总） */}
            <div style={{ width: 320, flexShrink: 0 }}>
              <TableDetail
                tables={selectedTables}
                nodes={globalGraph?.nodes ?? []}
                edges={globalGraph?.edges ?? []}
                scripts={scripts}
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
        {/* DB 配置对两种输入模式共用 */}
        <DatabaseConfigForm value={dbConfig} onChange={setDbConfig} />

        {/* 输入模式切换：手动粘贴 / 批量导入 */}
        <div style={{ margin: "12px 0 8px" }}>
          <Segmented
            value={analyzeMode}
            onChange={(v) => setAnalyzeMode(v as "manual" | "batch")}
            options={[
              { label: "手动粘贴 SQL", value: "manual" },
              { label: "批量导入文件", value: "batch" },
            ]}
            block
          />
        </div>

        {analyzeMode === "manual" ? (
          <ScriptEditor
            value={script}
            onChange={setScript}
            onAnalyze={handleAnalyze}
            loading={loading}
          />
        ) : (
          <BatchImport
            dbConfig={dbConfig}
            tagSchema={tagSchema}
            onSuccess={async () => {
              setModalOpen(false);
              await refreshAll();
            }}
          />
        )}
      </Modal>

      {/* 预处理规则弹窗 */}
      <Modal
        title="预处理规则配置"
        open={rulesModalOpen}
        onCancel={() => setRulesModalOpen(false)}
        onOk={handleSaveRules}
        confirmLoading={rulesLoading}
        okText="保存"
        cancelText="取消"
        width={760}
        destroyOnHidden
      >
        <PreprocessRulesConfig value={preprocessRules} onChange={setPreprocessRulesDraft} />
      </Modal>

      {/* 标签维度定义弹窗（管理员维护维度名 + 可选标签值）*/}
      <Modal
        title="标签维度定义"
        open={tagSchemaModalOpen}
        onCancel={() => setTagSchemaModalOpen(false)}
        onOk={handleSaveTagSchema}
        confirmLoading={tagSchemaSaving}
        okText="保存"
        cancelText="取消"
        width={640}
        destroyOnHidden
      >
        <TagSchemaConfig value={tagSchemaDraft} onChange={setTagSchemaDraft} />
      </Modal>

      {/* 脚本管理弹窗（表为中心改造后：上传/重命名/删除/打标收拢于此） */}
      <ScriptManagerModal
        open={scriptMgrOpen}
        onClose={() => setScriptMgrOpen(false)}
        scripts={scripts}
        onDelete={handleDelete}
        onRename={handleRename}
        tagSchema={tagSchema}
        onSetScriptTags={handleSetScriptTags}
        onBatchSetTags={handleBatchSetTags}
      />
    </ConfigProvider>
  );
}

export default App;
