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

async function reqBlob(path: string): Promise<Blob> {
  const t = getToken();
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
  equipmentQr: (id: number) => reqBlob(`/api/equipment/${id}/qr`),
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
  kbDownload: (id: number) => reqBlob(`/api/documents/${id}/download`),
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
};
