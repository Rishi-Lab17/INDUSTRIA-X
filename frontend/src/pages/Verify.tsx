import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";

export default function Verify() {
  const loc = useLocation() as { state?: { email?: string; devOtp?: string } };
  const [email, setEmail] = useState(loc.state?.email ?? "");
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setOk("");
    setBusy(true);
    try {
      const r = await api.verifyOtp({ email: email.trim(), code: code.trim() });
      setOk(r.message + " Redirecting to login…");
      setTimeout(() => nav("/login"), 1200);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="panel auth-card">
        <h1>Verify OTP</h1>
        <p>Enter the 6-digit code for your admin account.</p>
        {loc.state?.devOtp && (
          <div className="alert alert-warn">
            Local demo mode — your OTP is <b>{loc.state.devOtp}</b>
          </div>
        )}
        {err && <div className="alert alert-error">{err}</div>}
        {ok && <div className="alert alert-ok">{ok}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <label>EMAIL</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label>6-DIGIT CODE</label>
            <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={6} />
          </div>
          <button className="btn" disabled={busy}>{busy ? "Verifying…" : "Verify"}</button>
        </form>
        <div className="auth-switch">
          <Link to="/login">Back to login</Link>
        </div>
      </div>
    </div>
  );
}
