import { useState } from "react";
import { Link } from "react-router-dom";
import type { ConfirmationResult } from "firebase/auth";
import { api } from "../api";
import { isFirebaseConfigured, sendPhoneCode } from "../firebase";

/** Link a Firebase-verified phone number to the logged-in INDUSTRIA-X user.
    Firebase proves number ownership; company/RBAC/sessions stay server-side. */
export default function PhoneVerify() {
  const configured = isFirebaseConfigured();
  const [phone, setPhone] = useState("");
  const [smsCode, setSmsCode] = useState("");
  const [confirm, setConfirm] = useState<ConfirmationResult | null>(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setOk("");
    setBusy(true);
    try {
      const c = await sendPhoneCode(phone.trim(), "ix-recaptcha");
      setConfirm(c);
      setOk("SMS code sent to your phone.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not send SMS code");
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setOk("");
    setBusy(true);
    try {
      if (!confirm) throw new Error("Request an SMS code first");
      const cred = await confirm.confirm(smsCode.trim());
      const idToken = await cred.user.getIdToken();
      const r = await api.linkPhone({ id_token: idToken });
      setOk(`${r.message} (${r.phone_masked})`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Phone verification failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Mobile Verification</h1>
          <p className="page-sub">Firebase proves number ownership; INDUSTRIA-X keeps all authorization.</p>
        </div>
      </div>
      <div className="panel" style={{ maxWidth: 480 }}>
        {!configured && (
          <div className="alert alert-warn">
            Mobile verification is not configured on this deployment (missing
            VITE_FIREBASE_* settings). Email verification above remains the
            active method — nothing here is mocked.
          </div>
        )}
        {err && <div className="alert alert-error">{err}</div>}
        {ok && <div className="alert alert-ok">{ok}</div>}
        <div id="ix-recaptcha" />
        <form onSubmit={send}>
          <div className="field">
            <label>PHONE (E.164, E.G. +919876543210)</label>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} disabled={!configured} />
          </div>
          <button className="btn" disabled={busy || !configured}>
            {busy ? "Sending…" : "Send SMS Code"}
          </button>
        </form>
        {confirm && (
          <form onSubmit={verify} style={{ marginTop: 14 }}>
            <div className="field">
              <label>SMS CODE</label>
              <input
                value={smsCode}
                onChange={(e) => setSmsCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                inputMode="numeric"
                maxLength={6}
              />
            </div>
            <button className="btn" disabled={busy}>Verify &amp; Link Phone</button>
          </form>
        )}
        <div className="auth-switch">
          <Link to="/">Back to dashboard</Link>
        </div>
      </div>
    </div>
  );
}
