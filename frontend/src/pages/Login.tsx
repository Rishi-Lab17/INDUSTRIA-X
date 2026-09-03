import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const { login } = useAuth();
  const nav = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await login(email.trim(), password);
      nav("/");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="panel auth-card">
        <div className="brand" style={{ border: "none", paddingBottom: 8 }}>
          <div className="brand-mark">IX</div>
          <div>
            <div className="brand-name">INDUSTRIA-X</div>
            <div className="brand-sub">SOVEREIGN AI WORKBENCH</div>
          </div>
        </div>
        <h1>Engineer Login</h1>
        <p>Confidential on-premise investigation console.</p>
        {err && <div className="alert alert-error">{err}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <label>EMAIL</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
          </div>
          <div className="field">
            <label>PASSWORD</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </div>
          <button className="btn" disabled={busy}>{busy ? "Authenticating…" : "Login"}</button>
        </form>
        <div className="auth-switch">
          No company yet? <Link to="/register">Register company</Link> ·{" "}
          <Link to="/verify">Verify OTP</Link>
        </div>
        <LiveProbe />
      </div>
    </div>
  );
}

function LiveProbe() {
  const [txt, setTxt] = useState("probing backend…");
  useEffect(() => {
    api.health()
      .then((h) => setTxt(`backend ${h.status.toLowerCase()} · kimi ${h.services.kimi.status.toLowerCase()}`))
      .catch(() => setTxt("backend unreachable"));
  }, []);
  return <div style={{ marginTop: 14, fontSize: 12, color: "var(--muted)", textAlign: "center" }}>{txt}</div>;
}
