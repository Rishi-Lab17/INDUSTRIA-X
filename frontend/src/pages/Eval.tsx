import { useState } from "react";
import { api, type EvalReport } from "../api";

/** Internal retrieval-evaluation view (dev/admin tool, not a production metric).
 * Scores come from the live retrieval system — nothing is hardcoded. */
export default function Eval() {
  const [report, setReport] = useState<EvalReport | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function run() {
    setErr("");
    setBusy(true);
    try {
      setReport(await api.kbEval());
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Evaluation failed");
      setReport(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Retrieval Evaluation</h1>
          <p className="page-sub">
            Synthetic Pump P-204 question set executed against live retrieval.
            Requires the EVAL-P204 corpus indexed (see docs/stage4.md).
          </p>
        </div>
        <button className="btn btn-ghost" onClick={run} disabled={busy}>
          {busy ? "Evaluating…" : "Run evaluation"}
        </button>
      </div>

      {err && <div className="alert alert-error">{err}</div>}

      {report && (
        <>
          <div className="grid grid-3" style={{ marginBottom: 16 }}>
            <div className="panel"><div className="stat-num">{(report.summary.pass_rate * 100).toFixed(0)}%</div><div className="stat-label">PASS RATE @ {report.k}</div></div>
            <div className="panel"><div className="stat-num">{report.summary.mean_mrr.toFixed(2)}</div><div className="stat-label">MEAN MRR</div></div>
            <div className="panel"><div className="stat-num">{report.summary.mean_latency_ms}ms</div><div className="stat-label">MEAN LATENCY</div></div>
          </div>
          <div className="panel" style={{ padding: 8 }}>
            <table className="table">
              <thead>
                <tr><th>Query</th><th>Expected</th><th>Got</th><th>Rank</th><th>MRR</th><th>P@K</th><th>ms</th><th>Result</th></tr>
              </thead>
              <tbody>
                {report.queries.map((q, i) => (
                  <tr key={i}>
                    <td style={{ maxWidth: 280 }}>{q.query}</td>
                    <td>{q.expected ?? "(insufficient)"}</td>
                    <td style={{ maxWidth: 220 }}>{q.got.join(", ") || "—"}</td>
                    <td>{q.rank ?? "—"}</td>
                    <td>{q.mrr.toFixed(2)}</td>
                    <td>{q.precision_at_k.toFixed(2)}</td>
                    <td>{q.latency_ms}</td>
                    <td>{q.pass
                      ? <span className="badge"><span className="dot dot-online" />PASS</span>
                      : <span className="badge"><span className="dot dot-offline" />FAIL</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
