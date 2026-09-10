import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import loginHero from "../assets/login-hero.jpg";

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
      {/* LEFT — visual with supplied reference image */}
      <div className="login-visual">
        <img src={loginHero} alt="Industrial plant with engineer using INDUSTRIA-X tablet" className="login-hero-img" />
        <div className="login-hero-overlay" />
        <div className="login-visual-inner">
          {/* Top brand row */}
          <div className="login-topbar">
            <div className="login-brand-left">
              <div className="login-ix">IX</div>
              <div>
                <div className="login-brand-title">INDUSTRIA-X</div>
                <div className="login-brand-sub">SOVEREIGN AI WORKBENCH</div>
              </div>
            </div>
            <div className="login-trusted">
              <div>Trusted by Engineers.</div>
              <div>Built for a Safer Tomorrow.</div>
              <div className="login-underline" />
            </div>
          </div>

          {/* Headline */}
          <div className="login-headline">
            <h1>
              From<br />
              <span className="login-headline-blue">Industrial Data</span><br />
              to Real Answers
            </h1>
            <p className="login-headline-sub">Evidence-driven. Safety-aware.<br />Human in control.</p>
          </div>

          {/* Feature bullets — matches reference */}
          <div className="login-features">
            <div className="login-feature">
              <div className="login-feature-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 17V11M12 17V9M15 17V13" /></svg>
              </div>
              <div>
                <div className="login-feature-title">Investigate</div>
                <div className="login-feature-desc">Find the real cause</div>
              </div>
            </div>
            <div className="login-feature">
              <div className="login-feature-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="M9 12l2 2 4-4" /></svg>
              </div>
              <div>
                <div className="login-feature-title">Ensure Safety</div>
                <div className="login-feature-desc">Follow proven processes</div>
              </div>
            </div>
            <div className="login-feature">
              <div className="login-feature-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></svg>
              </div>
              <div>
                <div className="login-feature-title">Maintain Sovereignty</div>
                <div className="login-feature-desc">Your data. Your control.</div>
              </div>
            </div>
            <div className="login-feature">
              <div className="login-feature-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2"><path d="M9.5 2A7.5 7.5 0 002 9.5c0 4.2 3.3 7.5 7.5 7.5S17 13.7 17 9.5 13.7 2 9.5 2z" /><path d="M17 9.5c0 4.2-3.3 7.5-7.5 7.5M17 9.5c0-4.2 3.3-7.5 7.5-7.5M2 9.5h15" /><path d="M14.5 2a7.5 7.5 0 017.5 7.5c0 4.2-3.3 7.5-7.5 7.5" /></svg>
              </div>
              <div>
                <div className="login-feature-title">AI-Powered Insights</div>
                <div className="login-feature-desc">Turn evidence into action</div>
              </div>
            </div>
          </div>

          {/* Bottom tagline (visible on large screens) */}
          <div className="login-bottom-tagline">
            <div className="login-bottom-line" />
            <div>SAFER INDUSTRIES<br />SMARTER INVESTIGATIONS<br />A MORE RESILIENT TOMORROW</div>
          </div>
        </div>
      </div>

      {/* RIGHT — login form */}
      <div className="login-form-panel">
        <div className="login-form-card">
          {err && <div className="alert alert-error" role="alert">{err}</div>}
          <form onSubmit={submit} noValidate>
            <div className="field">
              <label htmlFor="login-email">Email</label>
              <div className="login-input-wrap">
                <svg className="login-field-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#64748B" strokeWidth="2"><rect x="2" y="4" width="20" height="16" rx="2" /><path d="M22 7L13.03 12.7a1.94 1.94 0 01-2.06 0L2 7" /></svg>
                <input
                  id="login-email"
                  type="email"
                  placeholder="Enter your email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="username"
                  required
                />
              </div>
            </div>

            <div className="field">
              <label htmlFor="login-password">Password</label>
              <div className="login-input-wrap">
                <svg className="login-field-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#64748B" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0110 0v4" /></svg>
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
                <button type="button" className="login-eye" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? "Hide password" : "Show password"} tabIndex={-1}>
                  {showPassword ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#64748B" strokeWidth="2"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24" /><line x1="1" y1="1" x2="23" y2="23" /></svg>
                  ) : (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#64748B" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>
                  )}
                </button>
              </div>
            </div>

            <div className="login-forgot">
              <a href="#" onClick={(e) => e.preventDefault()} tabIndex={-1}>Forgot password?</a>
            </div>

            <button type="submit" className="btn login-submit" disabled={busy} aria-busy={busy}>
              {busy ? <><span className="login-spinner" aria-hidden /> Signing in...</> : <>Sign In <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7" /></svg></>}
            </button>
          </form>

          <div className="login-or"><span>or</span></div>

          <div className="login-create-wrap">
            <div className="login-create-label">New to INDUSTRIA-X?</div>
            <Link to="/register" className="login-create-btn">Create an Account</Link>
          </div>

          <div className="login-card-footer">
            <div className="login-footer-nav">
              <span>INVESTIGATE</span><span className="dot">·</span><span>VERIFY</span><span className="dot">·</span><span>ENSURE</span><span className="dot">·</span><span>EVOLVE</span>
            </div>
            <div className="login-footer-underline" />
            <div className="login-powered">Powered by Trusted AI. Secured by You.</div>
          </div>
        </div>
      </div>

      <style>{`
        .login-root {
          display: flex;
          min-height: 100vh;
          background: #F0F9FF;
        }
        /* LEFT */
        .login-visual {
          position: relative;
          flex: 1.35;
          overflow: hidden;
          display: flex;
          background: #E0F2FE;
        }
        .login-hero-img {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          object-fit: cover;
          object-position: center 30%;
        }
        .login-hero-overlay {
          position: absolute;
          inset: 0;
          background: linear-gradient(180deg, rgba(240,249,255,0.55) 0%, rgba(240,249,255,0.15) 45%, rgba(15,23,42,0.08) 100%);
        }
        .login-visual-inner {
          position: relative;
          z-index: 1;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          padding: 28px 36px 24px;
          width: 100%;
          min-height: 100vh;
        }
        .login-topbar {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 16px;
        }
        .login-brand-left {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .login-ix {
          width: 44px;
          height: 44px;
          border-radius: 12px;
          background: linear-gradient(135deg, #0284C7, #38BDF8);
          display: grid;
          place-items: center;
          color: white;
          font-weight: 800;
          font-size: 18px;
          letter-spacing: 1px;
          box-shadow: 0 4px 12px rgba(2,132,199,0.25);
        }
        .login-brand-title {
          font-size: 22px;
          font-weight: 800;
          letter-spacing: 1.5px;
          color: #0F172A;
          line-height: 1;
        }
        .login-brand-sub {
          font-size: 10px;
          letter-spacing: 1.8px;
          color: #475569;
          font-weight: 600;
          margin-top: 2px;
        }
        .login-trusted {
          text-align: right;
          font-size: 11px;
          line-height: 1.4;
          color: #334155;
          font-weight: 600;
        }
        .login-underline {
          margin-top: 6px;
          margin-left: auto;
          width: 48px;
          height: 3px;
          background: #0284C7;
          border-radius: 2px;
        }
        .login-headline {
          margin-top: 36px;
          max-width: 520px;
        }
        .login-headline h1 {
          margin: 0;
          font-size: 42px;
          font-weight: 800;
          line-height: 1.05;
          color: #0F172A;
          letter-spacing: -0.8px;
        }
        .login-headline-blue { color: #0284C7; }
        .login-headline-sub {
          margin: 12px 0 0;
          font-size: 15px;
          color: #334155;
          line-height: 1.4;
          font-weight: 500;
        }
        .login-features {
          margin-top: 28px;
          display: grid;
          gap: 10px;
          max-width: 380px;
        }
        .login-feature {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 12px;
          background: rgba(255,255,255,0.92);
          border: 1px solid rgba(226,232,240,0.9);
          border-radius: 12px;
          box-shadow: 0 2px 8px rgba(15,23,42,0.06);
          backdrop-filter: blur(6px);
        }
        .login-feature-icon {
          width: 36px;
          height: 36px;
          border-radius: 10px;
          background: #0284C7;
          display: grid;
          place-items: center;
          flex-shrink: 0;
        }
        .login-feature-title { font-size: 13px; font-weight: 700; color: #0F172A; }
        .login-feature-desc { font-size: 12px; color: #64748B; }
        .login-bottom-tagline {
          margin-top: 24px;
          display: flex;
          gap: 12px;
          align-items: flex-start;
          font-size: 11px;
          letter-spacing: 1.4px;
          line-height: 1.5;
          color: #F8FAFC;
          font-weight: 700;
          text-shadow: 0 1px 6px rgba(15,23,42,0.35);
        }
        .login-bottom-line {
          width: 3px;
          height: 48px;
          background: #38BDF8;
          border-radius: 2px;
          flex-shrink: 0;
          margin-top: 2px;
        }
        /* RIGHT */
        .login-form-panel {
          width: 480px;
          flex-shrink: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 24px;
          background: linear-gradient(180deg, #F0F9FF 0%, #E0F2FE 100%);
          border-left: 1px solid #E2E8F0;
        }
        .login-form-card {
          width: 100%;
          max-width: 380px;
          background: #FFFFFF;
          border: 1px solid #E2E8F0;
          border-radius: 20px;
          padding: 28px;
          box-shadow: 0 10px 30px rgba(15,23,42,0.08), 0 1px 3px rgba(15,23,42,0.06);
        }
        .login-input-wrap {
          position: relative;
          display: flex;
          align-items: center;
        }
        .login-field-icon { position: absolute; left: 12px; pointer-events: none; }
        .login-input-wrap input {
          width: 100%;
          padding: 12px 40px 12px 40px;
          border: 1px solid #CBD5E1;
          border-radius: 10px;
          font-size: 14px;
          background: #FFFFFF;
          color: #0F172A;
          outline: none;
          transition: border-color 150ms ease, box-shadow 150ms ease;
        }
        .login-input-wrap input:focus { border-color: #0284C7; box-shadow: 0 0 0 3px rgba(2,132,199,0.12); }
        .login-input-wrap input::placeholder { color: #94A3B8; }
        .login-eye {
          position: absolute;
          right: 10px;
          background: none;
          border: none;
          cursor: pointer;
          padding: 6px;
          display: grid;
          place-items: center;
          border-radius: 6px;
        }
        .login-eye:hover { background: #F1F5F9; }
        .login-forgot { text-align: right; margin: 8px 0 18px; }
        .login-forgot a { font-size: 12px; color: #0284C7; font-weight: 600; text-decoration: none; }
        .login-forgot a:hover { text-decoration: underline; }
        .login-submit {
          width: 100%;
          background: #0284C7;
          border-radius: 10px;
          padding: 13px;
          font-size: 14px;
          font-weight: 700;
          box-shadow: 0 4px 12px rgba(2,132,199,0.22);
        }
        .login-submit:hover { background: #0369A1; }
        .login-spinner {
          width: 16px;
          height: 16px;
          border: 2px solid rgba(255,255,255,0.4);
          border-top-color: white;
          border-radius: 50%;
          animation: spin 0.7s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .login-or {
          display: flex;
          align-items: center;
          gap: 12px;
          margin: 20px 0;
          color: #94A3B8;
          font-size: 12px;
        }
        .login-or::before, .login-or::after { content: ""; flex: 1; height: 1px; background: #E2E8F0; }
        .login-create-wrap { text-align: center; }
        .login-create-label { font-size: 13px; color: #334155; margin-bottom: 10px; font-weight: 500; }
        .login-create-btn {
          display: block;
          width: 100%;
          padding: 12px;
          border-radius: 10px;
          border: 1.5px solid #0284C7;
          color: #0284C7;
          background: #FFFFFF;
          font-weight: 700;
          font-size: 13px;
          text-align: center;
          text-decoration: none;
        }
        .login-create-btn:hover { background: #F0F9FF; text-decoration: none; }
        .login-card-footer {
          margin-top: 22px;
          text-align: center;
          padding-top: 14px;
          border-top: 1px solid #F1F5F9;
        }
        .login-footer-nav {
          display: flex;
          justify-content: center;
          gap: 10px;
          font-size: 10px;
          letter-spacing: 1.2px;
          color: #64748B;
          font-weight: 700;
        }
        .login-footer-nav .dot { color: #CBD5E1; }
        .login-footer-underline { width: 32px; height: 2px; background: #0284C7; border-radius: 2px; margin: 8px auto; }
        .login-powered { font-size: 10px; color: #94A3B8; }
        /* Responsive */
        @media (max-width: 1024px) {
          .login-visual { display: none; }
          .login-form-panel { width: 100%; border-left: none; padding: 16px; }
        }
      `}</style>
    </div>
  );
}
