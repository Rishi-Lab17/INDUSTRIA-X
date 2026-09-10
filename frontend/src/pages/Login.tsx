import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
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
    <div className="login-root">
      {/* Left visual panel */}
      <div className="login-visual">
        <div className="login-visual-bg">
          <div className="login-grid-lines" />
          <div className="login-glow-orb login-glow-1" />
          <div className="login-glow-orb login-glow-2" />
          <div className="login-glow-orb login-glow-3" />
        </div>
        <div className="login-visual-content">
          <div className="login-visual-badge">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            LOCAL-FIRST AI
          </div>
          <h1 className="login-visual-title">
            <span className="login-title-line">REAL</span>
            <span className="login-title-line login-title-accent">INDUSTRY</span>
            <span className="login-title-line">REAL</span>
            <span className="login-title-line login-title-accent">EVIDENCE</span>
          </h1>
          <p className="login-visual-sub">
            Transforming industrial operations with sovereign AI intelligence.
            Your data. Your control. Safer tomorrows.
          </p>
          <div className="login-visual-stats">
            <div className="login-stat">
              <div className="login-stat-value">92%</div>
              <div className="login-stat-label">Performance</div>
            </div>
            <div className="login-stat-divider" />
            <div className="login-stat">
              <div className="login-stat-value">68&deg;C</div>
              <div className="login-stat-label">Temperature</div>
            </div>
            <div className="login-stat-divider" />
            <div className="login-stat">
              <div className="login-stat-value">5.2 bar</div>
              <div className="login-stat-label">Pressure</div>
            </div>
          </div>
        </div>
        <div className="login-visual-footer">
          <div className="login-footer-item">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            <span>Data Sovereignty Guaranteed</span>
          </div>
          <div className="login-footer-item">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>
            <span>Audit Ready Compliance</span>
          </div>
        </div>
      </div>

      {/* Right form panel */}
      <div className="login-form-panel">
        <div className="login-form-container">
          {/* Brand */}
          <div className="login-brand">
            <div className="login-brand-mark">
              <svg width="22" height="22" viewBox="0 0 48 48" fill="none">
                <rect x="16" y="16" width="16" height="16" rx="3" fill="#04121c"/>
                <path d="M22 22v4m4-4v4m-6 0h8" stroke="#0EA5E9" strokeWidth="2.5" strokeLinecap="round"/>
              </svg>
            </div>
            <div>
              <div className="login-brand-name">INDUSTRIA-X</div>
              <div className="login-brand-tagline">Intelligence for a Safer Tomorrow</div>
            </div>
          </div>

          {/* Heading */}
          <div className="login-heading">
            <h2>Welcome back</h2>
            <p>Sign in to your account to continue</p>
          </div>

          {/* Error */}
          {err && <div className="login-alert">{err}</div>}

          {/* Form */}
          <form onSubmit={submit} className="login-form">
            <div className="login-field">
              <label>Email Address</label>
              <div className="login-input-wrap">
                <svg className="login-field-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 7L13.03 12.7a1.94 1.94 0 01-2.06 0L2 7"/></svg>
                <input
                  type="email"
                  placeholder="name@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="username"
                  required
                />
              </div>
            </div>

            <div className="login-field">
              <label>Password</label>
              <div className="login-input-wrap">
                <svg className="login-field-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
                <input
                  type={showPassword ? "text" : "password"}
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  className="login-eye"
                  onClick={() => setShowPassword(!showPassword)}
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                  ) : (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  )}
                </button>
              </div>
            </div>

            <button type="submit" className="login-submit" disabled={busy}>
              {busy ? (
                <>
                  <span className="login-spinner" />
                  Signing in...
                </>
              ) : (
                <>
                  Sign In
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                </>
              )}
            </button>
          </form>

          {/* Divider */}
          <div className="login-or">
            <span>New here?</span>
          </div>

          {/* Register */}
          <Link to="/register" className="login-register-btn">
            Create Company Account
          </Link>

          {/* Footer */}
          <div className="login-form-footer">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            <span>Secured with local-first encryption. Your data never leaves your infrastructure.</span>
          </div>
        </div>
      </div>

      <style>{`
        .login-root {
          display: flex;
          min-height: 100vh;
          background: #0F172A;
        }

        /* === LEFT VISUAL PANEL === */
        .login-visual {
          flex: 1;
          position: relative;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          padding: 48px;
          overflow: hidden;
          background: linear-gradient(135deg, #0F172A 0%, #0C1929 50%, #0F172A 100%);
        }

        .login-visual-bg {
          position: absolute;
          inset: 0;
          overflow: hidden;
        }

        .login-grid-lines {
          position: absolute;
          inset: 0;
          background-image:
            linear-gradient(rgba(14, 165, 233, 0.05) 1px, transparent 1px),
            linear-gradient(90deg, rgba(14, 165, 233, 0.05) 1px, transparent 1px);
          background-size: 60px 60px;
          mask-image: radial-gradient(ellipse at 30% 50%, black 30%, transparent 70%);
          -webkit-mask-image: radial-gradient(ellipse at 30% 50%, black 30%, transparent 70%);
        }

        .login-glow-orb {
          position: absolute;
          border-radius: 50%;
          filter: blur(80px);
          opacity: 0.4;
        }

        .login-glow-1 {
          width: 400px;
          height: 400px;
          background: radial-gradient(circle, rgba(14, 165, 233, 0.3), transparent 70%);
          top: 10%;
          left: 5%;
          animation: float 8s ease-in-out infinite;
        }

        .login-glow-2 {
          width: 300px;
          height: 300px;
          background: radial-gradient(circle, rgba(56, 189, 248, 0.2), transparent 70%);
          bottom: 20%;
          right: 10%;
          animation: float 10s ease-in-out infinite reverse;
        }

        .login-glow-3 {
          width: 200px;
          height: 200px;
          background: radial-gradient(circle, rgba(14, 165, 233, 0.15), transparent 70%);
          top: 60%;
          left: 40%;
          animation: float 12s ease-in-out infinite;
        }

        @keyframes float {
          0%, 100% { transform: translate(0, 0); }
          33% { transform: translate(20px, -20px); }
          66% { transform: translate(-15px, 15px); }
        }

        .login-visual-content {
          position: relative;
          z-index: 1;
          max-width: 480px;
        }

        .login-visual-badge {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 6px 14px;
          background: rgba(14, 165, 233, 0.1);
          border: 1px solid rgba(14, 165, 233, 0.25);
          border-radius: 999px;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 1.5px;
          color: #38BDF8;
          margin-bottom: 32px;
        }

        .login-visual-title {
          margin: 0 0 24px;
          line-height: 1.05;
        }

        .login-title-line {
          display: block;
          font-size: 52px;
          font-weight: 800;
          color: #F8FAFC;
          letter-spacing: -1px;
        }

        .login-title-accent {
          color: #0EA5E9;
          text-shadow: 0 0 40px rgba(14, 165, 233, 0.4);
        }

        .login-visual-sub {
          font-size: 15px;
          line-height: 1.7;
          color: #94A3B8;
          margin: 0 0 40px;
          max-width: 400px;
        }

        .login-visual-stats {
          display: flex;
          align-items: center;
          gap: 24px;
          padding: 20px 24px;
          background: rgba(14, 165, 233, 0.06);
          border: 1px solid rgba(14, 165, 233, 0.12);
          border-radius: 16px;
          backdrop-filter: blur(12px);
        }

        .login-stat {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .login-stat-value {
          font-size: 22px;
          font-weight: 800;
          color: #F8FAFC;
        }

        .login-stat-label {
          font-size: 11px;
          color: #64748B;
          letter-spacing: 0.5px;
        }

        .login-stat-divider {
          width: 1px;
          height: 36px;
          background: rgba(14, 165, 233, 0.2);
        }

        .login-visual-footer {
          position: relative;
          z-index: 1;
          display: flex;
          gap: 32px;
        }

        .login-footer-item {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 12px;
          color: #64748B;
        }

        .login-footer-item svg { color: #0EA5E9; }

        /* === RIGHT FORM PANEL === */
        .login-form-panel {
          width: 520px;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 48px;
          background: linear-gradient(180deg, #111D2E 0%, #0F172A 100%);
          border-left: 1px solid rgba(14, 165, 233, 0.1);
        }

        .login-form-container {
          width: 100%;
          max-width: 380px;
        }

        .login-brand {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 40px;
        }

        .login-brand-mark {
          width: 42px;
          height: 42px;
          border-radius: 12px;
          background: linear-gradient(135deg, #0EA5E9, #38BDF8);
          display: grid;
          place-items: center;
          box-shadow: 0 0 20px rgba(14, 165, 233, 0.4);
        }

        .login-brand-name {
          font-size: 16px;
          font-weight: 800;
          color: #F8FAFC;
          letter-spacing: 1.5px;
        }

        .login-brand-tagline {
          font-size: 10px;
          color: #64748B;
          letter-spacing: 0.5px;
          margin-top: 2px;
        }

        .login-heading {
          margin-bottom: 32px;
        }

        .login-heading h2 {
          font-size: 28px;
          font-weight: 700;
          color: #F8FAFC;
          margin: 0 0 8px;
        }

        .login-heading p {
          font-size: 14px;
          color: #94A3B8;
          margin: 0;
        }

        .login-alert {
          padding: 12px 16px;
          border-radius: 10px;
          margin-bottom: 20px;
          font-size: 13px;
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid rgba(239, 68, 68, 0.3);
          color: #FCA5A5;
        }

        .login-form {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }

        .login-field label {
          display: block;
          font-size: 12px;
          font-weight: 600;
          color: #94A3B8;
          margin-bottom: 8px;
          letter-spacing: 0.3px;
        }

        .login-input-wrap {
          position: relative;
          display: flex;
          align-items: center;
        }

        .login-field-icon {
          position: absolute;
          left: 14px;
          color: #64748B;
          pointer-events: none;
          transition: color 0.2s;
        }

        .login-input-wrap:focus-within .login-field-icon {
          color: #0EA5E9;
        }

        .login-input-wrap input {
          width: 100%;
          padding: 14px 14px 14px 44px;
          border: 1px solid #334155;
          border-radius: 12px;
          font-size: 14px;
          background: rgba(15, 23, 42, 0.6);
          color: #F8FAFC;
          outline: none;
          transition: all 0.2s;
        }

        .login-input-wrap input:focus {
          border-color: #0EA5E9;
          box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
          background: rgba(15, 23, 42, 0.8);
        }

        .login-input-wrap input::placeholder {
          color: #475569;
        }

        .login-eye {
          position: absolute;
          right: 14px;
          background: none;
          border: none;
          cursor: pointer;
          color: #64748B;
          padding: 4px;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: color 0.2s;
        }

        .login-eye:hover { color: #94A3B8; }

        .login-submit {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          width: 100%;
          padding: 14px;
          margin-top: 4px;
          background: linear-gradient(135deg, #0EA5E9, #0284C7);
          color: #FFFFFF;
          border: none;
          border-radius: 12px;
          font-size: 15px;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.2s;
          box-shadow: 0 4px 16px rgba(14, 165, 233, 0.3);
          letter-spacing: 0.3px;
        }

        .login-submit:hover:not(:disabled) {
          background: linear-gradient(135deg, #38BDF8, #0EA5E9);
          box-shadow: 0 6px 24px rgba(14, 165, 233, 0.45);
          transform: translateY(-1px);
        }

        .login-submit:active:not(:disabled) { transform: translateY(0); }
        .login-submit:disabled { opacity: 0.6; cursor: not-allowed; }

        .login-spinner {
          width: 18px;
          height: 18px;
          border: 2px solid rgba(255,255,255,0.3);
          border-top-color: #fff;
          border-radius: 50%;
          animation: spin 0.6s linear infinite;
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        .login-or {
          display: flex;
          align-items: center;
          margin: 28px 0;
          color: #64748B;
          font-size: 13px;
        }

        .login-or::before,
        .login-or::after {
          content: '';
          flex: 1;
          border-bottom: 1px solid #1E293B;
        }

        .login-or span { padding: 0 16px; }

        .login-register-btn {
          display: block;
          width: 100%;
          padding: 14px;
          background: transparent;
          color: #F8FAFC;
          border: 1px solid #334155;
          border-radius: 12px;
          font-size: 14px;
          font-weight: 600;
          text-align: center;
          text-decoration: none;
          transition: all 0.2s;
        }

        .login-register-btn:hover {
          background: rgba(14, 165, 233, 0.06);
          border-color: #0EA5E9;
          color: #38BDF8;
        }

        .login-form-footer {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          margin-top: 32px;
          padding-top: 20px;
          border-top: 1px solid #1E293B;
          font-size: 11px;
          color: #475569;
          line-height: 1.5;
        }

        .login-form-footer svg {
          flex-shrink: 0;
          margin-top: 1px;
          color: #334155;
        }

        /* === RESPONSIVE === */
        @media (max-width: 1024px) {
          .login-visual { display: none; }
          .login-form-panel {
            width: 100%;
            border-left: none;
          }
        }

        @media (max-width: 768px) {
          .login-form-panel { padding: 24px; }
          .login-title-line { font-size: 36px; }
        }
      `}</style>
    </div>
  );
}
