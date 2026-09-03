import { useEffect, useState } from "react";
import { api, type User } from "../api";
import { useAuth } from "../auth";

export default function Workspace() {
  const { user } = useAuth();
  const isAdmin = user?.role === "COMPANY_ADMIN";
  const [data, setData] = useState<{
    company: { id: number; name: string; settings: Record<string, unknown>; created_at: string };
    members: (User & { is_active: number; created_at: string })[];
    stats: { members: number; equipment: number };
  } | null>(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [name, setName] = useState("");
  const [tz, setTz] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api.company()
      .then((d) => {
        setData(d);
        setName(d.company.name);
        setTz(String(d.company.settings.timezone ?? ""));
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }

  useEffect(load, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setOk("");
    setBusy(true);
    try {
      const r = await api.updateCompany({
        name: name.trim(),
        settings: { ...(data?.company.settings ?? {}), timezone: tz.trim() || undefined },
      });
      setData((d) => (d ? { ...d, company: r.company } : d));
      setOk("Company profile updated.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <div>{err ? <div className="alert alert-error">{err}</div> : "Loading workspace…"}</div>;

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">{data.company.name}</h1>
          <p className="page-sub">Company workspace · tenant #{data.company.id} · your data is isolated per company.</p>
        </div>
      </div>

      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-num">{data.stats.members}</div><div className="stat-label">MEMBERS</div></div>
        <div className="panel"><div className="stat-num">{data.stats.equipment}</div><div className="stat-label">EQUIPMENT ASSETS</div></div>
        <div className="panel"><div className="stat-num">{user?.role}</div><div className="stat-label">YOUR ROLE</div></div>
      </div>

      <div className="grid grid-2">
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Company Profile</h3>
          {err && <div className="alert alert-error">{err}</div>}
          {ok && <div className="alert alert-ok">{ok}</div>}
          {!isAdmin ? (
            <>
              <div className="kv"><span>NAME</span><span>{data.company.name}</span></div>
              <div className="kv"><span>TIMEZONE</span><span>{String(data.company.settings.timezone ?? "—")}</span></div>
              <div className="kv"><span>CREATED</span><span>{data.company.created_at}</span></div>
              <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>
                Only COMPANY_ADMIN can edit the profile.
              </div>
            </>
          ) : (
            <form onSubmit={save}>
              <div className="field">
                <label>COMPANY NAME</label>
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="field">
                <label>TIMEZONE</label>
                <input value={tz} onChange={(e) => setTz(e.target.value)} placeholder="Asia/Kolkata" />
              </div>
              <button className="btn" disabled={busy}>{busy ? "Saving…" : "Save profile"}</button>
            </form>
          )}
        </div>

        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Members ({data.members.length})</h3>
          <table className="table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th></tr></thead>
            <tbody>
              {data.members.map((m) => (
                <tr key={m.id}>
                  <td>{m.name}</td><td>{m.email}</td><td>{m.role}</td>
                  <td>{m.is_active ? "active" : "unverified"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
