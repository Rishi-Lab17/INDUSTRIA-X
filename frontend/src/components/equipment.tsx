import { useAuth } from "../auth";
import type { Equipment } from "../api";

export function critColor(c: Equipment["criticality"]) {
  if (c === "CRITICAL") return "var(--critical)";
  if (c === "HIGH") return "var(--warning)";
  if (c === "MEDIUM") return "var(--accent)";
  return "var(--success)";
}

export function statusColor(s: Equipment["status"]) {
  if (s === "OPERATIONAL") return "dot-online";
  if (s === "DECOMMISSIONED") return "dot-offline";
  return "dot-warn";
}

export function useRole() {
  const { user } = useAuth();
  return {
    role: user?.role,
    canWrite: user?.role === "COMPANY_ADMIN" || user?.role === "ENGINEER",
    canDelete: user?.role === "COMPANY_ADMIN",
    canHistory: user?.role === "COMPANY_ADMIN" || user?.role === "ENGINEER",
  };
}
