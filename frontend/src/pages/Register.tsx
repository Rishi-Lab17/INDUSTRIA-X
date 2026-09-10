import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";

export default function Register() {
  const [companyName, setCompanyName] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [mobile, setMobile] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await api.register({
        company_name: companyName.trim(), name: name.trim(),
        email: email.trim(), password,
        mobile_number: mobile.trim() || undefined,
      });
      nav("/login");
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
            <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="Acme Industries" required />
          </div>
          <div className="field">
            <label>ADMIN NAME</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Alex Kumar" required />
          </div>
          <div className="field">
            <label>ADMIN EMAIL</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" placeholder="alex@acme.test" required />
          </div>
          <div className="field">
            <label>MOBILE NUMBER (OPTIONAL)</label>
            <input value={mobile} onChange={(e) => setMobile(e.target.value)} autoComplete="tel" placeholder="+91..." />
          </div>
          <div className="field">
            <label>PASSWORD (MIN 8 CHARS)</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" placeholder="••••••••" required />
          </div>
          <button className="btn" disabled={busy}>{busy ? "Registering..." : "Register company"}</button>
        </form>
        <div className="auth-switch"><Link to="/login">Back to login</Link></div>
      </div>
    </div>
  );
}
