/* Typed API client. Token lives in localStorage; company_id is NEVER sent
   by the client — the backend derives the tenant from the session. */

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export interface User {
  id: number;
  name: string;
  email: string;
  role: "COMPANY_ADMIN" | "ENGINEER" | "TECHNICIAN";
  company_id: number;
}

export interface Equipment {
  id: number;
  code: string;
  name: string;
  type: string;
  manufacturer: string;
  model: string;
  serial_number: string;
  location: string;
  criticality: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  status: "OPERATIONAL" | "DEGRADED" | "UNDER_MAINTENANCE" | "DECOMMISSIONED";
  installed_at: string | null;
  commissioned_at: string | null;
  metadata: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export function getToken(): string | null {
  return localStorage.getItem("ix_token");
}

export interface KBDocument {
  id: number;
  company_id: number;
  equipment_id: number | null;
  equipment_code: string | null;
  uploaded_by: number | null;
  uploader_name: string | null;
  original_filename: string;
  file_type: string;
  mime_type: string;
  file_size: number;
  sha256_hash: string;
  version: number;
  parent_document_id: number | null;
  processing_status: string;
  processing_started_at: string | null;
  processing_completed_at: string | null;
  processing_error: string | null;
  processing_note: string | null;
  page_count: number | null;
  ocr_used: boolean;
  is_archived: boolean;
  index_status: string;
  indexed_version: number | null;
  indexed_at: string | null;
  index_error: string | null;
  chunk_count: number;
  embedding_model: string | null;
  created_at: string;
  updated_at: string;
  text_preview: string;
  duplicate?: boolean;
}

export interface KBPreview {
  id: number;
  processing_status: string;
  ocr_used: boolean;
  page_count: number | null;
  extracted_text: string;
  sections: { type: string; text: string; page?: number; source?: string }[];
}

export async function authedBlob(path: string): Promise<Blob> {  const t = getToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: t ? { Authorization: `Bearer ${t}` } : {},
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `Request failed (${res.status})`);
  }
  return res.blob();
}

/** Real upload with progress (fetch has no upload progress → XHR). */
export function uploadDocument(
  file: File, equipmentId: number | null, onProgress: (pct: number) => void
): Promise<KBDocument> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/api/documents`);
    const t = getToken();
    if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(data as KBDocument);
        else reject(new Error((data as { detail?: string }).detail ?? `Upload failed (${xhr.status})`));
      } catch {
        reject(new Error(`Upload failed (${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed (network)"));
    const fd = new FormData();
    fd.append("file", file);
    if (equipmentId) fd.append("equipment_id", String(equipmentId));
    xhr.send(fd);
  });
}

export function setToken(t: string | null) {
  if (t) localStorage.setItem("ix_token", t);
  else localStorage.removeItem("ix_token");
}

async function req<T>(path: string, opts: RequestInit = {}, auth = true): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) {
    const t = getToken();
    if (t) headers["Authorization"] = `Bearer ${t}`;
  }
  const res = await fetch(`${BASE}${path}`, { ...opts, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((data as { detail?: string }).detail ?? `Request failed (${res.status})`);
  }
  return data as T;
}

export interface Citation {
  document_id: number;
  document_version: number;
  chunk_id: string;
  filename: string;
  page: number | null;
  section: string | null;
  equipment_id: number | null;
  excerpt: string;
  semantic_score: number;
  lexical_score: number;
  combined_score: number;
  initial_rank: number | null;
  final_rank: number;
  retrieval_method: string;
  why_retrieved: string[];
}

export interface SearchResult {
  status: "OK" | "INSUFFICIENT_EVIDENCE";
  original_query: string;
  normalized_query: string;
  citations: Citation[];
  count: number;
  mode: string;
  context?: string;
  context_chars?: number;
  context_truncated?: boolean;
  chunks_used?: number;
  candidates?: number;
  best_score?: number | null;
  minimum_relevance_score?: number;
  reason?: string;
}

export interface KBHealth {
  documents_total: number;
  documents_ready: number;
  indexed: number;
  indexing: number;
  stale: number;
  failed: number;
  not_indexed: number;
  chunks_total: number;
  chunks_active: number;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimension: number;
  embedding_models_in_store: string[];
  vector_db: string;
  last_indexed_at: string | null;
}

export interface EvalReport {
  queries: {
    query: string; expected: string | null; got: string[];
    rank: number | null; mrr: number; precision_at_k: number;
    recall_at_k: number; latency_ms: number; pass: boolean;
  }[];
  k: number;
  summary: { pass_rate: number; mean_mrr: number; mean_latency_ms: number; evaluated_at: string };
}

export interface AISession {
  id: number;
  equipment_id: number | null;
  title: string;
  provider: string;
  model: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface AIMessage {
  id: number;
  role: "USER" | "ASSISTANT" | "SYSTEM" | "TOOL";
  content: string;
  model: string | null;
  created_at: string;
}

export interface AIRun {
  id: number;
  status: string;
  task_type: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  sources_count: number;
  tools_used: string[];
  error_category: string | null;
}

export interface AIModel {
  id: string;
  provider: string;
  display_name: string;
  local: boolean;
  is_test: boolean;
  capabilities: Record<string, { supported: boolean; verified_live: boolean }>;
  context_limit: number | null;
  status: string;
  error: string | null;
}

export interface AIHealth {
  provider: string;
  display: string;
  is_test: boolean;
  local: boolean;
  status: string;
  latency_ms: number;
  detail: string;
  model: string;
  runs_total: number;
  runs_completed: number;
  runs_failed: number;
  avg_latency_ms: number | null;
  last_error: { error_category: string; created_at: string } | null;
  tool_invocations: number;
}

export interface SensorDataset {
  id: number;
  equipment_id: number;
  equipment_code: string | null;
  name: string;
  source_filename: string;
  sha256_hash: string;
  channels: { name: string; unit: string | null }[];
  row_count: number;
  time_start: number;
  time_end: number;
  sample_interval_s: number | null;
  quality_status: string;
  quality_score: number | null;
  created_at: string;
}

export interface VisionAsset {
  id: number;
  equipment_id: number;
  equipment_code: string | null;
  filename: string;
  mime_type: string;
  file_size: number;
  width: number;
  height: number;
  sha256_hash: string;
  quality_status: string;
  quality_detail: Record<string, unknown>;
  ocr_status: string;
  ocr_text: string;
  created_at: string;
}

export interface VisionAnnotation {
  id: number;
  asset_id: number;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  note: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface Investigation {
  id: number;
  company_id: number;
  workspace_id: number | null;
  equipment_id: number;
  title: string;
  problem_statement: string;
  category: string;
  severity: string;
  priority: number;
  status: string;
  created_by: number | null;
  assigned_to: number | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface CaseEvidence {
  id: number;
  investigation_id: number;
  equipment_id: number | null;
  type: string;
  source: string;
  title: string;
  description: string;
  content: string;
  confidence: number | null;
  reliability: number | null;
  timestamp: number | null;
  created_by: number | null;
  metadata: Record<string, unknown>;
  provenance: Record<string, unknown>;
  created_at: string;
  is_active: number;
}

export interface CaseHypothesis {
  id: number;
  title: string;
  description: string;
  category: string;
  status: string;
  support_score: number;
  contradiction_score: number;
  completeness: number;
  confidence_band: string;
  rank: number;
  supporting: CaseEvidenceLite[];
  contradicting: CaseEvidenceLite[];
  neutral: CaseEvidenceLite[];
  expected_slots: string[];
  created_at: string;
  updated_at: string;
}

export interface CaseEvidenceLite {
  id: number;
  type: string;
  title: string;
  quality: number;
  freshness_band: string;
}

export const api = {
  register: (b: { company_name: string; name: string; email: string; password: string; mobile_number?: string }) =>
    req<{ message: string; email_masked: string; dev_mode: boolean }>(
      "/api/auth/register", { method: "POST", body: JSON.stringify(b) }, false),
  verifyOtp: (b: { email: string; code: string }) =>
    req<{ message: string }>("/api/auth/verify-otp", { method: "POST", body: JSON.stringify(b) }, false),
  resendOtp: (b: { email: string }) =>
    req<{ message: string; email_masked?: string; dev_mode?: boolean }>("/api/auth/resend-otp", {
      method: "POST", body: JSON.stringify(b) }, false),
  linkPhone: (b: { id_token: string }) =>
    req<{ message: string; phone_masked: string }>("/api/auth/phone/link", {
      method: "POST", body: JSON.stringify(b) }),
  login: (b: { email: string; password: string }) =>
    req<{ access_token: string; user: User }>("/api/auth/login", {
      method: "POST", body: JSON.stringify(b) }, false),
  logout: () => req("/api/auth/logout", { method: "POST" }),
  me: () => req<{ user: User; company: { id: number; name: string } }>("/api/auth/me"),
  users: () => req<{ users: User[] }>("/api/auth/users"),
  health: () => req<{ status: string; services: Record<string, { status: string; detail: string }> }>(
    "/api/health", {}, false),
  sovereignty: () => req<Record<string, string | boolean>>("/api/sovereignty", {}, false),
  company: () => req<{ company: { id: number; name: string; settings: Record<string, unknown>; created_at: string };
                       members: (User & { is_active: number; created_at: string })[];
                       stats: { members: number; equipment: number } }>("/api/company"),
  updateCompany: (b: { name?: string; settings?: Record<string, unknown> }) =>
    req<{ company: { id: number; name: string; settings: Record<string, unknown>; created_at: string } }>(
      "/api/company", { method: "PATCH", body: JSON.stringify(b) }),
  equipmentList: (q?: string) =>
    req<{ equipment: Equipment[] }>(`/api/equipment${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  equipmentGet: (id: number) => req<Equipment>(`/api/equipment/${id}`),
  equipmentCreate: (b: Record<string, unknown>) =>
    req<Equipment>("/api/equipment", { method: "POST", body: JSON.stringify(b) }),
  equipmentUpdate: (id: number, b: Record<string, unknown>) =>
    req<Equipment>(`/api/equipment/${id}`, { method: "PATCH", body: JSON.stringify(b) }),
  equipmentDelete: (id: number) =>
    req<{ message: string }>(`/api/equipment/${id}`, { method: "DELETE" }),
  equipmentQr: (id: number) => authedBlob(`/api/equipment/${id}/qr`),
  equipmentHistory: (id: number) =>
    req<{ history: { id: number; user_id: number; action: string; detail: string; created_at: string }[] }>(
      `/api/equipment/${id}/history`),
  kbList: (params: Record<string, string | number | boolean | undefined>) => {
    const q = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    return req<{ documents: KBDocument[]; total: number; page: number; page_size: number }>(
      `/api/documents${q ? `?${q}` : ""}`);
  },
  kbGet: (id: number) => req<KBDocument>(`/api/documents/${id}`),
  kbPreview: (id: number) => req<KBPreview>(`/api/documents/${id}/preview`),
  kbDownload: (id: number) => authedBlob(`/api/documents/${id}/download`),
  kbArchive: (id: number) =>
    req<{ message: string }>(`/api/documents/${id}/archive`, { method: "POST" }),
  kbRetry: (id: number) =>
    req<KBDocument>(`/api/documents/${id}/retry`, { method: "POST" }),
  kbDelete: (id: number) =>
    req<{ message: string }>(`/api/documents/${id}`, { method: "DELETE" }),
  kbIndex: (id: number) =>
    req<{ document_id: number; status: string; detail: string; chunks: number }>(
      `/api/knowledge/documents/${id}/index`, { method: "POST" }),
  kbIndexStatus: (id: number) =>
    req<{ id: number; index_status: string; indexed_version: number | null;
          indexed_at: string | null; index_error: string | null;
          chunk_count: number; embedding_model: string | null;
          version: number; processing_status: string }>(
      `/api/knowledge/documents/${id}/index-status`),
  kbReindex: (id: number) =>
    req<{ document_id: number; status: string; detail: string; chunks: number }>(
      `/api/knowledge/documents/${id}/reindex`, { method: "POST" }),
  kbReindexCompany: (equipmentId?: number) =>
    req<{ reindexed: number; results: unknown[] }>("/api/knowledge/reindex", {
      method: "POST", body: JSON.stringify(
        equipmentId ? { equipment_id: equipmentId } : {}) }),
  kbHealth: () => req<KBHealth>("/api/knowledge/health"),
  kbSearch: (b: { query: string; equipment_id?: number; document_id?: number;
                  source_types?: string[]; top_k?: number;
                  include_historical?: boolean }) =>
    req<SearchResult>("/api/knowledge/search", {
      method: "POST", body: JSON.stringify(b) }),
  kbEval: () => req<EvalReport>("/api/knowledge/eval"),
  aiModels: () => req<{ models: AIModel[] }>("/api/ai/models"),
  aiHealth: () => req<AIHealth>("/api/ai/health"),
  aiTools: () => req<{ tools: { name: string; description: string }[] }>("/api/ai/tools"),
  aiSessions: () => req<{ sessions: AISession[] }>("/api/ai/sessions"),
  aiCreateSession: (b: { equipment_id?: number; title?: string; task_type?: string }) =>
    req<AISession>("/api/ai/sessions", { method: "POST", body: JSON.stringify(b) }),
  aiGetSession: (id: number) =>
    req<{ session: AISession; messages: AIMessage[]; runs: AIRun[] }>(`/api/ai/sessions/${id}`),
  aiDeleteSession: (id: number) =>
    req<{ message: string }>(`/api/ai/sessions/${id}`, { method: "DELETE" }),
  aiSendMessage: (id: number, b: { content: string }) =>
    req<{ run_id: number; status: string; answer: string;
          citations: Citation[]; plan: string[]; duration_ms: number | null;
          sources_count: number; tools_used: string[]; streamed: boolean;
          error?: string; error_category?: string | null }>(
      `/api/ai/sessions/${id}/messages`, { method: "POST", body: JSON.stringify(b) }),
  aiGetRun: (id: number) =>
    req<{ run: AIRun & { provider: string; model: string; prompt_template: string;
                         prompt_version: string; tokens_in: number | null;
                         tokens_out: number | null };
          tool_runs: { tool_name: string; status: string; error: string | null;
                       duration_ms: number | null; created_at: string }[] }>(
      `/api/ai/runs/${id}`),
  aiCancelRun: (id: number) =>
    req<{ run_id: number; status: string; cancelled: boolean }>(
      `/api/ai/runs/${id}/cancel`, { method: "POST" }),
  sensorUpload: (file: File, equipmentId: number, name?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("equipment_id", String(equipmentId));
    if (name) fd.append("name", name);
    const t = getToken();
    const headers: Record<string, string> = t ? { Authorization: `Bearer ${t}` } : {};
    return fetch(`${BASE}/api/sensors/upload`, {
      method: "POST", headers, body: fd,
    }).then(async (res) => {
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error((data as { detail?: string }).detail ?? `Upload failed (${res.status})`);
      }
      return data as SensorDataset & { quality: Record<string, unknown> };
    });
  },
  sensorList: (equipmentId?: number) =>
    req<{ datasets: SensorDataset[] }>(
      `/api/sensors${equipmentId ? `?equipment_id=${equipmentId}` : ""}`),
  sensorGet: (id: number) => req<SensorDataset>(`/api/sensors/${id}`),
  sensorQuality: (id: number) =>
    req<Record<string, unknown>>(`/api/sensors/${id}/quality`),
  sensorAnalyze: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/sensors/${id}/analyze`, {
      method: "POST", body: JSON.stringify(b) }),
  sensorTrend: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/sensors/${id}/trend`, {
      method: "POST", body: JSON.stringify(b) }),
  sensorAnomalies: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/sensors/${id}/anomalies`, {
      method: "POST", body: JSON.stringify(b) }),
  sensorFrequency: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/sensors/${id}/frequency`, {
      method: "POST", body: JSON.stringify(b) }),
  sensorCorrelate: (b: Record<string, unknown>) =>
    req<Record<string, unknown>>("/api/sensors/correlation", {
      method: "POST", body: JSON.stringify(b) }),
  sensorSeries: (id: number, channel: string, start?: number, end?: number) =>
    req<{ dataset_id: number; channel: string; times: number[]; values: number[];
          downsampled: boolean; stride?: number; original_n?: number }>(
      `/api/sensors/${id}/series?channel=${encodeURIComponent(channel)}` +
      `${start !== undefined ? `&start=${start}` : ""}${end !== undefined ? `&end=${end}` : ""}`),
  sensorExportUrl: (id: number) => `${BASE}/api/sensors/${id}/export`,
  visionUpload: (file: File, equipmentId: number) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("equipment_id", String(equipmentId));
    const t = getToken();
    const headers: Record<string, string> = t ? { Authorization: `Bearer ${t}` } : {};
    return fetch(`${BASE}/api/vision/images`, {
      method: "POST", headers, body: fd,
    }).then(async (res) => {
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error((data as { detail?: string }).detail ?? `Upload failed (${res.status})`);
      }
      return data as VisionAsset;
    });
  },
  visionList: (equipmentId?: number) =>
    req<{ images: VisionAsset[] }>(
      `/api/vision/images${equipmentId ? `?equipment_id=${equipmentId}` : ""}`),
  visionGet: (id: number) => req<VisionAsset>(`/api/vision/images/${id}`),
  visionFileUrl: (id: number) => `${BASE}/api/vision/images/${id}/file`,
  visionQuality: (id: number) =>
    req<VisionAsset>(`/api/vision/images/${id}/quality`, { method: "POST" }),
  visionOcr: (id: number) =>
    req<{ asset_id: number; ocr_status: string; ocr_text: string; note: string }>(
      `/api/vision/images/${id}/ocr`, { method: "POST" }),
  visionAnalyze: (id: number) =>
    req<Record<string, unknown>>(`/api/vision/images/${id}/analyze`, { method: "POST" }),
  visionAnnotations: (id: number) =>
    req<{ annotations: VisionAnnotation[] }>(`/api/vision/images/${id}/annotations`),
  visionAnnotate: (id: number, b: Record<string, unknown>) =>
    req<VisionAnnotation>(`/api/vision/images/${id}/annotations`, {
      method: "POST", body: JSON.stringify(b) }),
  visionAnnotUpdate: (id: number, annId: number, b: Record<string, unknown>) =>
    req<VisionAnnotation>(`/api/vision/images/${id}/annotations/${annId}`, {
      method: "PATCH", body: JSON.stringify(b) }),
  visionAnnotDelete: (id: number, annId: number) =>
    req<{ message: string }>(`/api/vision/images/${id}/annotations/${annId}`, {
      method: "DELETE" }),
  mmRun: (b: Record<string, unknown>) =>
    req<Record<string, unknown>>("/api/investigations/multimodal", {
      method: "POST", body: JSON.stringify(b) }),
  mmList: (equipmentId?: number) =>
    req<{ investigations: { id: number; equipment_id: number; question: string;
                            created_at: string; updated_at: string }[] }>(
      `/api/investigations${equipmentId ? `?equipment_id=${equipmentId}` : ""}`),
  mmGet: (id: number) =>
    req<{ id: number; equipment_id: number; question: string;
          config: Record<string, unknown>; results: Record<string, unknown>;
          created_at: string; updated_at: string }>(`/api/investigations/${id}`),
  mmSnapshot: (b: Record<string, unknown>) =>
    req<{ investigation_id: number; message: string }>("/api/investigations/snapshot", {
      method: "POST", body: JSON.stringify(b) }),
  caseWorkspaces: () =>
    req<{ workspaces: { id: number; name: string }[] }>("/api/cases/workspaces"),
  caseList: (params: Record<string, string | number | undefined>) => {
    const q = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    return req<{ investigations: Investigation[]; total: number; page: number; page_size: number }>(
      `/api/cases${q ? `?${q}` : ""}`);
  },
  caseCreate: (b: Record<string, unknown>) =>
    req<Investigation>("/api/cases", { method: "POST", body: JSON.stringify(b) }),
  caseGet: (id: number) =>
    req<{ investigation: Investigation; equipment: Equipment | null;
          counts: { evidence: number; hypotheses: number } }>(`/api/cases/${id}`),
  casePatch: (id: number, b: Record<string, unknown>) =>
    req<Investigation>(`/api/cases/${id}`, { method: "PATCH", body: JSON.stringify(b) }),
  caseStatus: (id: number, status: string) =>
    req<Investigation>(`/api/cases/${id}/status`, {
      method: "POST", body: JSON.stringify({ status }) }),
  caseEvidenceList: (id: number, params: Record<string, string | undefined> = {}) => {
    const q = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    return req<{ evidence: CaseEvidence[]; total: number }>(
      `/api/cases/${id}/evidence${q ? `?${q}` : ""}`);
  },
  caseEvidenceAdd: (id: number, b: Record<string, unknown>) =>
    req<CaseEvidence>(`/api/cases/${id}/evidence`, {
      method: "POST", body: JSON.stringify(b) }),
  caseEvidencePatch: (id: number, eid: number, b: Record<string, unknown>) =>
    req<CaseEvidence>(`/api/cases/${id}/evidence/${eid}`, {
      method: "PATCH", body: JSON.stringify(b) }),
  caseEvidenceArchive: (id: number, eid: number) =>
    req<{ message: string }>(`/api/cases/${id}/evidence/${eid}/archive`, { method: "POST" }),
  caseHypotheses: (id: number) =>
    req<{ hypotheses: CaseHypothesis[] }>(`/api/cases/${id}/hypotheses`),
  caseHypothesisCreate: (id: number, b: Record<string, unknown>) =>
    req<CaseHypothesis>(`/api/cases/${id}/hypotheses`, {
      method: "POST", body: JSON.stringify(b) }),
  caseHypothesisGenerate: (id: number, aiSessionId?: number) =>
    req<{ created: { id: number; title: string }[]; notes: string[];
          hypotheses: CaseHypothesis[];
          ai: { available: boolean; note: string | null; suggestions: unknown[] } }>(
      `/api/cases/${id}/hypotheses/generate`, {
        method: "POST",
        body: JSON.stringify(aiSessionId ? { ai_session_id: aiSessionId } : {}) }),
  caseHypothesisStatus: (id: number, hid: number, status: string) =>
    req<CaseHypothesis>(`/api/cases/${id}/hypotheses/${hid}`, {
      method: "PATCH", body: JSON.stringify({ status }) }),
  caseLink: (id: number, hid: number, b: Record<string, unknown>) =>
    req<{ hypotheses: CaseHypothesis[] }>(
      `/api/cases/${id}/hypotheses/${hid}/links`, {
        method: "POST", body: JSON.stringify(b) }),
  caseUnlink: (id: number, hid: number, eid: number) =>
    req<{ hypotheses: CaseHypothesis[] }>(
      `/api/cases/${id}/hypotheses/${hid}/links/${eid}`, { method: "DELETE" }),
  caseRescore: (id: number) =>
    req<{ hypotheses: CaseHypothesis[] }>(`/api/cases/${id}/rescore`, { method: "POST" }),
  caseGraph: (id: number) =>
    req<{ nodes: { id: string; kind: string; label: string; [k: string]: unknown }[];
          edges: { from: string; to: string; relation: string }[];
          counts: { nodes: number; edges: number } }>(
      `/api/cases/${id}/evidence-graph`),
  caseRelate: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/cases/${id}/relations`, {
      method: "POST", body: JSON.stringify(b) }),
  caseMissing: (id: number) =>
    req<{ missing: { hypothesis_id: number; hypothesis: string; slot: string;
                     title: string; kind: string; priority: string }[] }>(
      `/api/cases/${id}/missing-evidence`),
  caseNBE: (id: number) =>
    req<{ recommendations: { id: number; rank: number; title: string; kind: string;
                             priority: string; effort: string; safety: string;
                             expected_value: string; discriminative_value: number;
                             rationale: Record<string, string>; status: string }[] }>(
      `/api/cases/${id}/next-best-evidence`),
  caseRecoStatus: (id: number, rid: number, status: string) =>
    req<Record<string, unknown>>(`/api/cases/${id}/recommendations/${rid}`, {
      method: "PATCH", body: JSON.stringify({ status }) }),
  caseSimulate: (id: number, b: Record<string, unknown>) =>
    req<{ hypothesis_id: number; slot: string; outcome: string;
          deltas: Record<string, number>; completeness: Record<string, number>;
          ranks_before: Record<string, number>; ranks_after: Record<string, number> }>(
      `/api/cases/${id}/simulate`, { method: "POST", body: JSON.stringify(b) }),
  caseConfidence: (id: number) =>
    req<{ history: { hypothesis_id: number; title: string; support_score: number;
                     contradiction_score: number; completeness: number;
                     confidence_band: string; trigger: string }[] }>(
      `/api/cases/${id}/confidence-history`),
  caseSimilar: (id: number) =>
    req<{ cases: { id: number; title: string; status: string; category: string;
                   similarity: number }[]; note: string | null }>(
      `/api/cases/${id}/similar-cases`),
  caseAssumptions: (id: number) =>
    req<{ assumptions: { id: number; text: string; status: string }[] }>(
      `/api/cases/${id}/assumptions`),
  caseAssumptionStatus: (id: number, aid: number, status: string) =>
    req<{ id: number; status: string }>(`/api/cases/${id}/assumptions/${aid}`, {
      method: "PATCH", body: JSON.stringify({ status }) }),
  caseConflicts: (id: number) =>
    req<{ conflicts: { id: number; evidence_a_id: number; evidence_b_id: number;
                       description: string; recommendation: string; status: string }[];
          new?: number }>(`/api/cases/${id}/conflicts`),
  caseConflictsRefresh: (id: number) =>
    req<{ conflicts: { id: number; description: string; status: string }[]; new: number }>(
      `/api/cases/${id}/conflicts/refresh`, { method: "POST" }),
  caseConflictStatus: (id: number, cid: number, status: string) =>
    req<{ id: number; status: string }>(`/api/cases/${id}/conflicts/${cid}`, {
      method: "PATCH", body: JSON.stringify({ status }) }),
  caseHealth: (id: number) =>
    req<{ coverage: number; quality: number; separation: number; freshness: number;
          reliability: number; critical_gaps: number; overall: number;
          readiness: string }>(`/api/cases/${id}/health`),
  caseReadiness: (id: number) =>
    req<{ ready: boolean; state: string; reasons: string[] }>(
      `/api/cases/${id}/readiness`),
  caseCopilot: (id: number, question: string) =>
    req<{ answer: string; references: { id: number; title: string; type: string }[];
          grounded: boolean }>(`/api/cases/${id}/copilot`, {
      method: "POST", body: JSON.stringify({ question }) }),
  caseTimeline: (id: number) =>
    req<{ events: { action: string; detail: Record<string, unknown>;
                    user_id: number | null; created_at: string }[];
          total: number }>(`/api/cases/${id}/timeline`),
  // Stage 8: verification + safety gate + technician workflow + human approval
  verificationList: (params: Record<string, string | number | undefined> = {}) => {
    const q = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    return req<{ verifications: Record<string, unknown>[]; total: number; page: number; page_size: number }>(
      `/api/verifications${q ? `?${q}` : ""}`);
  },
  verificationCreate: (b: Record<string, unknown>) =>
    req<Record<string, unknown>>("/api/verifications", {
      method: "POST", body: JSON.stringify(b) }),
  verificationGet: (id: number) =>
    req<Record<string, unknown>>(`/api/verifications/${id}`),
  verificationUpdateStatus: (id: number, status: string) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/status`, {
      method: "PATCH", body: JSON.stringify({ status }) }),
  verificationAssign: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/assign`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationAssignReviewer: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/reviewer`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationStart: (id: number) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/start`, {
      method: "POST" }),
  verificationVerifyEvidence: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/evidence-verify`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationAddObservation: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/observations`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationAddMeasurement: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/measurements`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationCreateChecklist: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/checklists`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationChecklists: (id: number) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/checklists`),
  verificationCompleteChecklistItem: (vid: number, cid: number, iid: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${vid}/checklists/${cid}/items/${iid}`, {
      method: "PATCH", body: JSON.stringify(b) }),
  verificationCreateSafetyAssessment: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/safety-assessment`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationSafety: (id: number) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/safety`),
  verificationEvaluateSafetyGate: (id: number) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/safety-gate/evaluate`, {
      method: "POST" }),
  verificationSafetyGate: (id: number) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/safety-gate`),
  verificationRequestApproval: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/request-approval`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationApprove: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/approve`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationReject: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/reject`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationEscalate: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/escalate`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationCreateIsolation: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/isolation`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationCreatePermit: (id: number, b: Record<string, unknown>) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/permit`, {
      method: "POST", body: JSON.stringify(b) }),
  verificationScorecard: (id: number) =>
    req<Record<string, unknown>>(`/api/verifications/${id}/scorecard`),
  verificationApprovals: (params: Record<string, string | number | undefined> = {}) => {
    const q = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    return req<{ approvals: Record<string, unknown>[]; total: number }>(
      `/api/verifications/approvals${q ? `?${q}` : ""}`);
  },
  verificationSafetyCenter: () =>
    req<Record<string, unknown>>("/api/verifications/safety-center"),
  verificationDashboard: () =>
    req<Record<string, unknown>>("/api/verifications/dashboard"),
  verificationDecisions: (id: number) =>
    req<{ decisions: Record<string, unknown>[] }>(`/api/verifications/${id}/decisions`),
   verificationEscalations: (id: number) =>
     req<{ escalations: Record<string, unknown>[] }>(`/api/verifications/${id}/escalations`),
   // Stage 9: case management
   caseCreate9: (b: Record<string, unknown>) =>
     req<Record<string, unknown>>("/api/case", { method: "POST", body: JSON.stringify(b) }),
   caseList9: (params: Record<string, string | number | undefined> = {}) => {
     const q = Object.entries(params)
       .filter(([, v]) => v !== undefined && v !== "")
       .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
       .join("&");
     return req<{ cases: Record<string, unknown>[]; total: number; page: number; page_size: number }>(
       `/api/case${q ? `?${q}` : ""}`);
   },
   caseGet9: (id: number) =>
     req<Record<string, unknown>>(`/api/case/${id}`),
   casePatch9: (id: number, b: Record<string, unknown>) =>
     req<Record<string, unknown>>(`/api/case/${id}`, { method: "PATCH", body: JSON.stringify(b) }),
   caseClose9: (id: number, b: Record<string, unknown>) =>
     req<Record<string, unknown>>(`/api/case/${id}/close`, { method: "POST", body: JSON.stringify(b) }),
   caseReopen9: (id: number, b: Record<string, unknown>) =>
     req<Record<string, unknown>>(`/api/case/${id}/reopen`, { method: "POST", body: JSON.stringify(b) }),
   caseArchive9: (id: number) =>
     req<Record<string, unknown>>(`/api/case/${id}/archive`, { method: "POST" }),
   caseTimeline9: (id: number) =>
     req<{ events: Record<string, unknown>[] }>(`/api/case/${id}/timeline`),
   caseActions9: (id: number, b: Record<string, unknown>) =>
     req<Record<string, unknown>>(`/api/case/${id}/actions`, { method: "POST", body: JSON.stringify(b) }),
   caseMemory9: (b: Record<string, unknown>) =>
     req<Record<string, unknown>>("/api/case/memory", { method: "POST", body: JSON.stringify(b) }),
   caseMemoryFeedback9: (mid: number, b: Record<string, unknown>) =>
     req<Record<string, unknown>>(`/api/case/memory/${mid}/feedback`, { method: "POST", body: JSON.stringify(b) }),
   caseMemoryList9: (params: Record<string, string | number | undefined> = {}) => {
     const q = Object.entries(params)
       .filter(([, v]) => v !== undefined && v !== "")
       .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
       .join("&");
     return req<{ memories: Record<string, unknown>[]; total: number }>(
       `/api/case/memory${q ? `?${q}` : ""}`);
   },
   caseLineage9: (id: number, b: Record<string, unknown>) =>
     req<Record<string, unknown>>(`/api/case/${id}/lineage`, { method: "POST", body: JSON.stringify(b) }),
   caseLineageEdge9: (id: number, b: Record<string, unknown>) =>
     req<Record<string, unknown>>(`/api/case/${id}/lineage/edge`, { method: "POST", body: JSON.stringify(b) }),
   caseLineageGet9: (id: number) =>
     req<Record<string, unknown>>(`/api/case/${id}/lineage`),
   caseAudit9: (params: Record<string, string | number | undefined> = {}) => {
     const q = Object.entries(params)
       .filter(([, v]) => v !== undefined && v !== "")
       .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
       .join("&");
     return req<Record<string, unknown>>(`/api/case/audit${q ? `?${q}` : ""}`);
   },
   caseSovereignty9: () =>
     req<Record<string, unknown>>("/api/case/sovereignty"),
   caseSovereigntyUpdate9: (b: Record<string, unknown>) =>
     req<Record<string, unknown>>("/api/case/sovereignty", { method: "PUT", body: JSON.stringify(b) }),
   caseDashboard9: () =>
     req<Record<string, unknown>>("/api/case/dashboard"),
   caseSafetyCenter9: () =>
     req<Record<string, unknown>>("/api/case/safety-center"),
   caseReports9: (id: number, b: Record<string, unknown>) =>
     req<Record<string, unknown>>(`/api/case/${id}/reports`, { method: "POST", body: JSON.stringify(b) }),
   caseReportsList9: (id: number) =>
     req<Record<string, unknown>>(`/api/case/${id}/reports`),
};
