"""INDUSTRIA-X email service — Resend API delivery, credentials from env only.

Security rules enforced here:
- The Resend call happens ONLY here (FastAPI backend). The key never reaches
  the frontend, URLs, logs, or API responses.
- The OTP/code is NEVER logged, NEVER returned, NEVER printed.
- If Resend is not configured: local dev (APP_ENV=local) writes the message
  to a server-side outbox FILE (documented dev mechanism); any other env
  FAILS LOUDLY (EmailNotConfigured) so the API returns a clear 502 instead
  of pretending delivery happened.
- If Resend rejects/fails, EmailError is raised: the account stays
  unverified and the API returns a safe generic message.
"""
import re

import httpx

from ..core.config import ROOT, get_settings


class EmailError(Exception):
    pass


class EmailNotConfigured(EmailError):
    pass


def is_configured() -> bool:
    s = get_settings()
    return bool(s.RESEND_API_KEY and s.RESEND_FROM_EMAIL)


def outbox_dir():
    from pathlib import Path
    s = get_settings()
    p = Path(s.DEV_OUTBOX_DIR)
    return p if p.is_absolute() else ROOT / p


def render_verification_email(name: str, code: str, expire_minutes: int) -> tuple[str, str, str]:
    subject = "INDUSTRIA-X Email Verification"
    text = (
        f"Hello {name},\n\n"
        f"Your INDUSTRIA-X email verification code is:\n\n"
        f"{code}\n\n"
        f"This code expires in {expire_minutes} minutes.\n\n"
        "If you did not request this verification, please ignore this email.\n\n"
        "Regards,\n"
        "INDUSTRIA-X Security Team\n"
    )
    html = (
        f"<p>Hello {name},</p>"
        f"<p>Your INDUSTRIA-X email verification code is:</p>"
        f"<p style=\"font-size:24px;font-weight:bold;letter-spacing:4px;\">{code}</p>"
        f"<p>This code expires in {expire_minutes} minutes.</p>"
        f"<p>If you did not request this verification, please ignore this email.</p>"
        f"<p>Regards,<br/>INDUSTRIA-X Security Team</p>"
    )
    return subject, text, html


def send_email(to_email: str, subject: str, text: str, html: str) -> str:
    """Send one email via Resend. Returns the Resend message id."""
    s = get_settings()
    if not is_configured():
        raise EmailNotConfigured(
            "Email delivery is not configured. Set RESEND_API_KEY/RESEND_FROM_EMAIL "
            "in .env (see .env.example)."
        )
    sender = (f"{s.RESEND_FROM_NAME} <{s.RESEND_FROM_EMAIL}>"
              if s.RESEND_FROM_NAME else s.RESEND_FROM_EMAIL)
    try:
        resp = httpx.post(
            s.RESEND_BASE_URL.rstrip("/") + "/emails",
            headers={"Authorization": f"Bearer {s.RESEND_API_KEY}",
                     "Content-Type": "application/json"},
            json={"from": sender, "to": [to_email],
                  "subject": subject, "text": text, "html": html},
            timeout=s.RESEND_TIMEOUT_S,
        )
    except Exception as e:
        # Network/timeout failure: never include content (it holds the code).
        raise EmailError(f"Email provider unreachable ({type(e).__name__})") from e
    if resp.status_code not in (200, 201):
        try:
            detail = str(resp.json().get("message", ""))[:120]
        except Exception:
            detail = ""
        # Never include message content (it holds the code).
        raise EmailError(f"Email provider rejected the request (HTTP {resp.status_code})"
                         + (f": {detail}" if detail else ""))
    try:
        return str(resp.json().get("id", ""))
    except Exception:
        return ""


def send_verification_code(to_email: str, name: str, code: str) -> str:
    """Deliver the verification OTP. Returns 'resend' or 'dev-outbox'.

    `code` is used once and never logged. Dev-outbox files live under
    DEV_OUTBOX_DIR (gitignored) and are the documented local-dev mechanism —
    the code still never touches any API response, log, or UI.
    """
    s = get_settings()
    subject, text, html = render_verification_email(name, code, s.OTP_EXPIRE_MINUTES)
    try:
        if not is_configured():
            if s.APP_ENV != "local":
                raise EmailNotConfigured(
                    "Email delivery is not configured. Set RESEND_API_KEY/"
                    "RESEND_FROM_EMAIL in .env (see .env.example).")
            outbox_dir().mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^a-z0-9]", "_", to_email.lower())[:64] or "unknown"
            (outbox_dir() / f"{safe}.eml").write_text(
                f"To: {to_email}\nSubject: {subject}\n\n{text}", encoding="utf-8")
            return "dev-outbox"
        send_email(to_email, subject, text, html)
        return "resend"
    finally:
        del subject, text, html
