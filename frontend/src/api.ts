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
};
