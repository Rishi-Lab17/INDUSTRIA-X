import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";

export default function Register() {
  const [companyName, setCompanyName] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const r = await api.register({
        company_name: companyName.trim(), name: name.trim(),
        email: email.trim(), password,
      });
      // Local-dev: backend returns the OTP so the demo works without email.
      nav("/verify", { state: { email: email.trim(), devOtp: r.dev_otp } });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="panel auth-card">
        <h1>Register Company</h1>
        <p>Creates an isolated tenant with a COMPANY_ADMIN account.</p>
        {err && <div className="alert alert-error">{err}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <label>COMPANY NAME</label>
            <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
          </div>
          <div className="field">
            <label>ADMIN NAME</label>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label>ADMIN EMAIL</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
          </div>
          <div className="field">
            <label>PASSWORD (MIN 8 CHARS)</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          </div>
          <button className="btn" disabled={busy}>{busy ? "Registering…" : "Register company"}</button>
        </form>
        <div className="auth-switch">
          <Link to="/login">Back to login</Link> · <Link to="/verify">Verify OTP</Link>
        </div>
      </div>
    </div>
  );
}
