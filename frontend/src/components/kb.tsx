import { useAuth } from "../auth";

export function useKBRole() {
  const { user } = useAuth();
  const staff = user?.role === "COMPANY_ADMIN" || user?.role === "ENGINEER";
  return {
    canUpload: true, // all authenticated roles may upload
    canRetry: staff,
    canArchive: user?.role === "COMPANY_ADMIN",
    canIndex: staff,
  };
}

export function indexDot(status: string) {
  if (status === "INDEXED") return "dot-online";
  if (status === "INDEX_FAILED") return "dot-offline";
  if (status === "STALE") return "dot-warn";
  return "dot-warn";
}

export function statusDot(status: string) {
  if (status === "COMPLETED") return "dot-online";
  if (status === "FAILED") return "dot-offline";
  return "dot-warn";
}

export function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export const SUPPORTED_LABELS = ["PDF", "DOCX", "TXT", "CSV", "XLSX", "JPG", "JPEG", "PNG"];
