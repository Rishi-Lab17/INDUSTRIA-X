import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useRole } from "../components/equipment";

export default function ApprovalInbox() {
  const { canWrite } = useRole();
  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.verificationApprovals().then((r) => {
      setItems(r.approvals); setTotal(r.total); setErr("");
    }).catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }, []);

  if (err) return <div className="alert alert-error">{err}</div>;
  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Approval Inbox</h1>
          <p className="page-sub">{total} approval{total === 1 ? "" : "s"} pending review</p>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="panel">No pending approvals.</div>
      ) : (
        <div className="panel" style={{ padding: 8 }}>
          <table className="table">
            <thead><tr><th>Verification</th><th>Equipment</th><th>Priority</th><th>Level</th><th>Requested</th><th>Action</th></tr></thead>
            <tbody>
              {items.map((a: Record<string, unknown>) => (
                <tr key={(a.id as number)}>
                  <td><Link to={`/verifications/${(a.verification_id as number)}`}>#{a.verification_id as number}</Link></td>
                  <td style={{ fontSize: 12 }}>{(a.equipment_name as string) || "—"}</td>
                  <td><b>{(a.priority as string)}</b></td>
                  <td>{(a.approval_level as string)}</td>
                  <td style={{ fontSize: 12 }}>{(a.created_at as string)?.slice(0, 10)}</td>
                  <td>
                    {canWrite && (
                      <>
                        <Link to={`/verifications/${a.verification_id}`}>Review</Link>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="panel" style={{ marginTop: 16 }}>
        <h3 style={{ marginTop: 0 }}>Separation of Duties</h3>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          The person who generates an AI recommendation cannot automatically become the final approver.
          AI = decision support. Human = final authority. Safety gate = blocking control.
        </div>
      </div>
    </div>
  );
}
