import { useEffect, useState } from "react";
import { api } from "../api";
import { useRole } from "../components/equipment";

interface ReportItem {
  id: number;
  case_number: string;
  title: string;
  status: string;
  generated_at: string;
  format: string;
}

export default function ReportsPage() {
  const { canWrite } = useRole();
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");
  const [page, setPage] = useState(1);

  function load() {
    api.caseList9({ page, page_size: 20, status: "CLOSED" }).then(r => {
      const cases = (r.cases as unknown as ReportItem[]) || [];
      setReports(cases); setTotal((r.total as number) || 0); setErr("");
    }).catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [page]);

  async function generateReport(cid: number) {
    try {
      const r = await api.caseReports9(cid, { format: "PDF" });
      alert(`Report generated: ${(r as Record<string, unknown>).report_id || (r as Record<string, unknown>).id || "OK"}`);
    } catch (e: any) { alert(e.message); }
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Reports</h1>
          <p className="page-sub">Generated case reports · {total} report{total === 1 ? "" : "s"}</p>
        </div>
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">TOTAL REPORTS</div><div className="stat-num">{total}</div></div>
      </div>
      <table className="table">
        <thead><tr><th>Case #</th><th>Title</th><th>Status</th><th>Generated</th><th>Actions</th></tr></thead>
        <tbody>
          {reports.map((r) => (
            <tr key={r.id}>
              <td>{r.case_number}</td>
              <td>{r.title || "—"}</td>
              <td>{r.status || "—"}</td>
              <td>{r.generated_at.slice(0, 10)}</td>
              <td><button className="btn btn-ghost" onClick={() => generateReport(r.id)}>Generate Report</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {reports.length === 0 && !err && <div className="panel" style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>No reports found</div>}
    </div>
  );
}
