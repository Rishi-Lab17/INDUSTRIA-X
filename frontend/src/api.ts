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

export function getToken(): string | null {
  return localStorage.getItem("ix_token");
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
};
