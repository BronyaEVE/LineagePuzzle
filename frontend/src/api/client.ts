import type {
  AnalysisResult, AnalyzeRequest,
  ScriptSummary, GlobalGraph, ImpactAnalysis,
} from "../types";

const API_BASE = "/api";

// 默认请求超时（ms）。后端卡住时前端不会永久 pending，超时后抛错让调用方提示用户。
const DEFAULT_TIMEOUT = 15000;

/**
 * 统一的 fetch 封装：带超时 + 统一错误信息解析。
 *
 * - 超时：通过 AbortController 实现，到期中断请求。
 * - 错误：解析后端返回的 {detail: "..."}（FastAPI HTTPException 格式），
 *   提取具体原因而非泛化提示。S1 修复后 script_id 非法会返回 400+detail。
 * - signal：可选，调用方可传入自己的 AbortSignal（如页面切换时取消请求）。
 */
async function request<T>(
  url: string,
  options: RequestInit & { timeout?: number } = {},
): Promise<T> {
  const { timeout = DEFAULT_TIMEOUT, ...init } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, { ...init, signal: controller.signal });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `请求失败（${res.status}）`);
    }
    // 无响应体的请求（DELETE 等）
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  } catch (e: unknown) {
    if (e instanceof Error && e.name === "AbortError") {
      throw new Error("请求超时，请稍后重试");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// === 分析 ===

export async function submitAnalysis(payload: AnalyzeRequest): Promise<AnalysisResult> {
  return request<AnalysisResult>(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// === 脚本管理 ===

export async function listScripts(): Promise<ScriptSummary[]> {
  return request<ScriptSummary[]>(`${API_BASE}/scripts`);
}

export async function getScript(id: string): Promise<AnalysisResult> {
  return request<AnalysisResult>(`${API_BASE}/scripts/${id}`);
}

export async function deleteScript(id: string): Promise<void> {
  await request<void>(`${API_BASE}/scripts/${id}`, { method: "DELETE" });
}

export async function renameScript(id: string, name: string): Promise<void> {
  await request<void>(`${API_BASE}/scripts/${id}/name?name=${encodeURIComponent(name)}`, {
    method: "PUT",
  });
}

// === 全局图谱 ===

export async function getGlobalGraph(): Promise<GlobalGraph> {
  return request<GlobalGraph>(`${API_BASE}/global-graph`);
}

// === 参数映射 ===

export async function getParamMapping(): Promise<Record<string, string>> {
  return request<Record<string, string>>(`${API_BASE}/param-mapping`);
}

export async function setParamMapping(mapping: Record<string, string>): Promise<Record<string, string>> {
  return request<Record<string, string>>(`${API_BASE}/param-mapping`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mapping),
  });
}

// === 导入导出 ===

export async function exportData(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`${API_BASE}/export`);
}

export async function importData(payload: Record<string, unknown>): Promise<void> {
  await request<void>(`${API_BASE}/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// === 影响分析 ===

export async function impactAnalysis(table: string): Promise<ImpactAnalysis> {
  return request<ImpactAnalysis>(`${API_BASE}/impact-analysis/${encodeURIComponent(table)}`);
}
