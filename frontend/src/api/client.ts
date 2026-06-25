import type {
  AnalysisResult, AnalyzeRequest, CorrectStatementRequest,
  ScriptSummary, GlobalGraph, StatementGroup,
} from "../types";

const API_BASE = "/api";

// === 分析 ===

export async function submitAnalysis(request: AnalyzeRequest): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "分析失败");
  }
  return res.json();
}

// === 脚本管理 ===

export async function listScripts(): Promise<ScriptSummary[]> {
  const res = await fetch(`${API_BASE}/scripts`);
  if (!res.ok) throw new Error("获取脚本列表失败");
  return res.json();
}

export async function getScript(id: string): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/scripts/${id}`);
  if (!res.ok) throw new Error("获取脚本详情失败");
  return res.json();
}

export async function deleteScript(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/scripts/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("删除失败");
}

export async function renameScript(id: string, name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/scripts/${id}/name?name=${encodeURIComponent(name)}`, {
    method: "PUT",
  });
  if (!res.ok) throw new Error("重命名失败");
}

export async function getStatements(scriptId: string): Promise<StatementGroup> {
  const res = await fetch(`${API_BASE}/scripts/${scriptId}/statements`);
  if (!res.ok) throw new Error("获取语句分段失败");
  return res.json();
}

export async function correctStatement(
  scriptId: string, seq: number, request: CorrectStatementRequest
): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/scripts/${scriptId}/statements/${seq}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) throw new Error("修正失败");
  return res.json();
}

// === 全局图谱 ===

export async function getGlobalGraph(): Promise<GlobalGraph> {
  const res = await fetch(`${API_BASE}/global-graph`);
  if (!res.ok) throw new Error("获取全局图谱失败");
  return res.json();
}

export async function getTables(): Promise<Record<string, any>> {
  const res = await fetch(`${API_BASE}/tables`);
  if (!res.ok) throw new Error("获取表列表失败");
  return res.json();
}

// === 参数映射 ===

export async function getParamMapping(): Promise<Record<string, string>> {
  const res = await fetch(`${API_BASE}/param-mapping`);
  if (!res.ok) throw new Error("获取参数映射失败");
  return res.json();
}

export async function setParamMapping(mapping: Record<string, string>): Promise<Record<string, string>> {
  const res = await fetch(`${API_BASE}/param-mapping`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mapping),
  });
  if (!res.ok) throw new Error("保存参数映射失败");
  return res.json();
}

// === 导入导出 ===

export async function exportData(): Promise<Record<string, any>> {
  const res = await fetch(`${API_BASE}/export`);
  if (!res.ok) throw new Error("导出失败");
  return res.json();
}

export async function importData(payload: Record<string, any>): Promise<void> {
  const res = await fetch(`${API_BASE}/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("导入失败");
}
