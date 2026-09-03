"""INDUSTRIA-X email service — provider abstraction, credentials from env only.

    EmailProvider
    ├── ResendEmailProvider        (production; official Resend HTTP API)
    └── DevelopmentEmailProvider   (local dev; server-side outbox file)

Selection: RESEND_ENABLED=true AND a non-empty RESEND_API_KEY → Resend.
Otherwise: development outbox when APP_ENV=local, loud EmailNotConfigured
refusal in any other env. A missing key NEVER crashes registration with a
500/502 in local dev and NEVER fakes delivery.

Security rules enforced here:
- Provider calls happen ONLY here (FastAPI backend). The key never reaches
  the frontend, URLs, logs, or API responses.
- The OTP/code is NEVER logged, NEVER returned, NEVER printed.
- Only safe structured log lines are emitted (no keys, codes, headers,
  passwords, JWTs, or full payloads).
- If Resend rejects/fails, EmailError is raised: the account stays
  unverified and the API returns a safe generic message.
"""
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..core.config import ROOT, get_settings

logger = logging.getLogger("industria-x.email")

DEV_MODE = "dev-outbox"
RESEND_MODE = "resend"


class EmailError(Exception):
    pass


class EmailNotConfigured(EmailError):
    pass


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


def outbox_dir() -> Path:
    s = get_settings()
    p = Path(s.DEV_OUTBOX_DIR)
    return p if p.is_absolute() else ROOT / p


class EmailProvider(ABC):
    name = "base"

    @abstractmethod
    def send(self, *, recipient: str, name: str, code: str, expires_at: str) -> str:
        """Deliver the OTP. Returns a message id (Resend) or file path (dev).
        `code` must never be logged, returned, or printed by implementations."""


class ResendEmailProvider(EmailProvider):
    name = RESEND_MODE

    def send(self, *, recipient: str, name: str, code: str, expires_at: str) -> str:
        s = get_settings()
        if not s.RESEND_FROM_EMAIL:
            raise EmailNotConfigured(
                "Resend is enabled but RESEND_FROM_EMAIL is not set. "
                "Add it to .env (see .env.example).")
        subject, text, html = render_verification_email(
            name, code, s.OTP_EXPIRE_MINUTES)
        sender = (f"{s.RESEND_FROM_NAME} <{s.RESEND_FROM_EMAIL}>"
                  if s.RESEND_FROM_NAME else s.RESEND_FROM_EMAIL)
        try:
            resp = httpx.post(
                s.RESEND_BASE_URL.rstrip("/") + "/emails",
                headers={"Authorization": "Bearer " + s.RESEND_API_KEY,
                         "Content-Type": "application/json"},
                json={"from": sender, "to": [recipient],
                      "subject": subject, "text": text, "html": html},
                timeout=s.RESEND_TIMEOUT_S,
            )
        except Exception as e:
            # Network/timeout failure: type name only, never content or key.
            logger.warning("Verification email not accepted by Resend: provider unreachable")
            raise EmailError(
                f"Email provider unreachable ({type(e).__name__})") from e
        finally:
            del subject, text, html
        if resp.status_code not in (200, 201):
            # Status only: Resend's body is never echoed (defense in depth).
            logger.warning("Verification email not accepted by Resend: HTTP %d",
                           resp.status_code)
            raise EmailError("Email provider rejected the request "
                             f"(HTTP {resp.status_code})")
        try:
            message_id = str(resp.json().get("id", ""))
        except Exception:
            message_id = ""
        logger.info("Verification email accepted by Resend for %s", recipient)
        return message_id


class DevelopmentEmailProvider(EmailProvider):
    name = DEV_MODE

    def send(self, *, recipient: str, name: str, code: str, expires_at: str) -> str:
        s = get_settings()
        subject, text, _html = render_verification_email(
            name, code, s.OTP_EXPIRE_MINUTES)
        try:
            outbox_dir().mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^a-z0-9]", "_", recipient.lower())[:64] or "unknown"
            path = outbox_dir() / f"{safe}.eml"
            created = datetime.now(timezone.utc).isoformat()
            path.write_text(
                f"To: {recipient}\n"
                f"Subject: {subject}\n"
                f"Purpose: email-verification\n"
                f"Provider: development-outbox\n"
                f"Created-At: {created}\n"
                f"Expires-At: {expires_at}\n"
                f"\n{text}", encoding="utf-8")
        finally:
            del subject, text, _html
        logger.info("Verification email queued through development outbox for %s",
                    recipient)
        return str(path)


def resend_wanted() -> bool:
    s = get_settings()
    return bool(s.RESEND_ENABLED and s.RESEND_API_KEY)


def get_provider() -> EmailProvider:
    """Select the active provider without ever crashing on a missing key."""
    if resend_wanted():
        return ResendEmailProvider()
    return DevelopmentEmailProvider()


def is_configured() -> bool:
    return isinstance(get_provider(), ResendEmailProvider)


def send_verification_email(*, recipient: str, name: str, code: str,
                            expires_at: str) -> str:
    """Internal entry point used by authentication. Returns 'resend' or
    'dev-outbox'. `code` is used once and never logged.

    Dev-outbox files live under DEV_OUTBOX_DIR (gitignored) and are the
    documented local-dev mechanism — the code still never touches any API
    response, log, or UI. Outside APP_ENV=local with no Resend key, raises
    EmailNotConfigured instead of faking delivery.
    """
    s = get_settings()
    provider = get_provider()
    if isinstance(provider, DevelopmentEmailProvider) and s.APP_ENV != "local":
        logger.warning("Email provider unavailable; refusing (non-local env)")
        raise EmailNotConfigured(
            "Email delivery is not configured. Set RESEND_ENABLED=true with "
            "RESEND_API_KEY/RESEND_FROM_EMAIL in .env (see .env.example).")
    if isinstance(provider, DevelopmentEmailProvider):
        logger.info("Email provider unavailable; development mode active")
    provider.send(recipient=recipient, name=name, code=code, expires_at=expires_at)
    return provider.name
