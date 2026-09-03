import { useAuth } from "../auth";

export function useKBRole() {
  const { user } = useAuth();
  return {
    canUpload: true, // all authenticated roles may upload
    canRetry: user?.role === "COMPANY_ADMIN" || user?.role === "ENGINEER",
    canArchive: user?.role === "COMPANY_ADMIN",
  };
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
