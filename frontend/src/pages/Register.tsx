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
    <div className="auth-wrap" style={{ background: "linear-gradient(135deg, #0F172A 0%, #1E293B 50%, #0F172A 100%)" }}>
      <div className="panel auth-card" style={{ 
        background: "linear-gradient(180deg, rgba(30, 41, 59, 0.98), rgba(15, 23, 42, 0.98))",
        border: "1px solid #334155",
        boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.5)"
      }}>
        <h1 style={{ color: "#F8FAFC", fontSize: 22, fontWeight: 700 }}>Register Company</h1>
        <p style={{ color: "#94A3B8" }}>Creates an isolated tenant with a COMPANY_ADMIN account.</p>
        {err && <div className="alert alert-error">{err}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <label style={{ color: "#94A3B8" }}>COMPANY NAME</label>
            <input 
              value={companyName} 
              onChange={(e) => setCompanyName(e.target.value)}
              style={{
                background: "#0F172A",
                border: "1px solid #334155",
                color: "#F8FAFC"
              }}
            />
          </div>
          <div className="field">
            <label style={{ color: "#94A3B8" }}>ADMIN NAME</label>
            <input 
              value={name} 
              onChange={(e) => setName(e.target.value)}
              style={{
                background: "#0F172A",
                border: "1px solid #334155",
                color: "#F8FAFC"
              }}
            />
          </div>
          <div className="field">
            <label style={{ color: "#94A3B8" }}>ADMIN EMAIL</label>
            <input 
              value={email} 
              onChange={(e) => setEmail(e.target.value)} 
              autoComplete="username"
              style={{
                background: "#0F172A",
                border: "1px solid #334155",
                color: "#F8FAFC"
              }}
            />
          </div>
          <div className="field">
            <label style={{ color: "#94A3B8" }}>MOBILE NUMBER (OPTIONAL, E.G. +919876543210)</label>
            <input 
              value={mobile} 
              onChange={(e) => setMobile(e.target.value)} 
              autoComplete="tel" 
              placeholder="+91..."
              style={{
                background: "#0F172A",
                border: "1px solid #334155",
                color: "#F8FAFC"
              }}
            />
          </div>
          <div className="field">
            <label style={{ color: "#94A3B8" }}>PASSWORD (MIN 8 CHARS)</label>
            <input 
              type="password" 
              value={password} 
              onChange={(e) => setPassword(e.target.value)} 
              autoComplete="new-password"
              style={{
                background: "#0F172A",
                border: "1px solid #334155",
                color: "#F8FAFC"
              }}
            />
          </div>
          <button 
            className="btn" 
            disabled={busy}
            style={{
              background: "linear-gradient(135deg, #0EA5E9, #38BDF8)",
              color: "#0F172A",
              fontWeight: 700
            }}
          >
            {busy ? "Registering..." : "Register company"}
          </button>
        </form>
        <div className="auth-switch" style={{ color: "#94A3B8" }}>
          <Link to="/login" style={{ color: "#0EA5E9" }}>Back to login</Link>
        </div>
      </div>
    </div>
  );
}
