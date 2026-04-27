import type { AnalysisResult, AnalyzeRequest, CorrectStatementRequest } from "../types";

const API_BASE = "/api";

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

export async function getAnalysis(id: string): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/analyses/${id}`);
  if (!res.ok) throw new Error("获取分析结果失败");
  return res.json();
}

export async function getAnalyses(page = 1, pageSize = 20): Promise<{ items: AnalysisResult[]; total: number }> {
  const res = await fetch(`${API_BASE}/analyses?page=${page}&page_size=${pageSize}`);
  if (!res.ok) throw new Error("获取历史记录失败");
  return res.json();
}

export async function getStatements(analysisId: string): Promise<StatementGroup> {
  const res = await fetch(`${API_BASE}/analyses/${analysisId}/statements`);
  if (!res.ok) throw new Error("获取语句分段失败");
  return res.json();
}

export async function correctStatement(
  analysisId: string,
  seq: number,
  request: CorrectStatementRequest
): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/analyses/${analysisId}/statements/${seq}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) throw new Error("修正失败");
  return res.json();
}
