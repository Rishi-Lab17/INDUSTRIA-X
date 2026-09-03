import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";

const RESEND_COOLDOWN_S = 60;

function maskEmail(email: string): string {
  const at = email.indexOf("@");
  if (at <= 0) return "****";
  const local = email.slice(0, at);
  const domain = email.slice(at + 1);
  return `${local.length > 1 ? local[0] : "*"}****@${domain}`;
}

export default function Verify() {
  const loc = useLocation() as { state?: { email?: string; devMode?: boolean } };
  const [email, setEmail] = useState(loc.state?.email ?? "");
  const [devMode, setDevMode] = useState(loc.state?.devMode ?? false);
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState(loc.state?.email ? "Verification code sent to your email address." : "");
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const nav = useNavigate();

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setOk("");
    setBusy(true);
    try {
      const r = await api.verifyOtp({ email: email.trim(), code: code.trim() });
      setOk(r.message + " Redirecting to login…");
      setTimeout(() => nav("/login"), 1500);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setErr("");
    setOk("");
    try {
      const r = await api.resendOtp({ email: email.trim() });
      setOk(r.message);
      if (r.dev_mode) setDevMode(true);
      setCooldown(RESEND_COOLDOWN_S);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Resend failed";
      setErr(msg);
      const m = msg.match(/wait (\d+) seconds/);
      if (m) setCooldown(parseInt(m[1], 10));
    }
  }

  return (
    <div className="auth-wrap">
      <div className="panel auth-card">
        <h1>Verify Your Email</h1>
        <p>
          We&apos;ve sent a 6-digit verification code to:
          <br />
          <b>{email ? maskEmail(email.trim()) : "your email address"}</b>
        </p>
        {devMode && (
          <div className="alert alert-warn">
            Development mode — no email was sent. Read the code from the
            server&apos;s local outbox: <b>storage/temporary/dev-outbox</b>.
          </div>
        )}
        {err && <div className="alert alert-error">{err}</div>}
        {ok && <div className="alert alert-ok">{ok}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <label>EMAIL</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
          </div>
          <div className="field">
            <label>6-DIGIT CODE</label>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              inputMode="numeric"
              maxLength={6}
              autoComplete="one-time-code"
              placeholder="······"
            />
          </div>
          <button className="btn" disabled={busy}>{busy ? "Verifying…" : "Verify Email"}</button>
        </form>
        <div className="auth-switch">
          Didn&apos;t receive the code?{" "}
          <button
            className="btn btn-ghost"
            onClick={resend}
            disabled={cooldown > 0 || !email.trim()}
            style={{ padding: "6px 12px", fontSize: 13 }}
          >
            {cooldown > 0 ? `Resend Code (${cooldown}s)` : "Resend Code"}
          </button>
        </div>
        <div className="auth-switch">
          <Link to="/login">Back to login</Link>
        </div>
      </div>
    </div>
  );
}
