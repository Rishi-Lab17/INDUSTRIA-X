"""INDUSTRIA-X email service — real SMTP delivery, credentials from env only.

Security rules enforced here:
- The OTP/code is NEVER logged, NEVER returned, NEVER printed.
- If SMTP is not configured, sending FAILS LOUDLY (EmailNotConfigured) so
  the API can return a clear 502 instead of pretending delivery happened.
"""
import smtplib
import ssl
from email.message import EmailMessage

from ..core.config import get_settings


class EmailError(Exception):
    pass


class EmailNotConfigured(EmailError):
    pass


def is_configured() -> bool:
    s = get_settings()
    return bool(s.SMTP_HOST and s.SMTP_FROM_EMAIL)


def render_verification_email(name: str, code: str, expire_minutes: int) -> tuple[str, str]:
    subject = "INDUSTRIA-X Email Verification"
    body = (
        f"Hello {name},\n\n"
        f"Your INDUSTRIA-X verification code is:\n\n"
        f"{code}\n\n"
        f"This code expires in {expire_minutes} minutes.\n\n"
        "If you did not request this verification, you can ignore this email.\n\n"
        "Regards,\n"
        "INDUSTRIA-X Security Team\n"
    )
    return subject, body


def send_email(to_email: str, subject: str, body: str) -> None:
    """Deliver one plaintext email via the configured SMTP relay."""
    s = get_settings()
    if not is_configured():
        raise EmailNotConfigured(
            "Email delivery is not configured. Set SMTP_HOST/SMTP_FROM_EMAIL "
            "in .env (see .env.example)."
        )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{s.SMTP_FROM_NAME} <{s.SMTP_FROM_EMAIL}>" if s.SMTP_FROM_NAME else s.SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(body)
    try:
        if s.SMTP_USE_TLS:
            context = ssl.create_default_context()
            with smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=s.SMTP_TIMEOUT_S) as client:
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
                if s.SMTP_USERNAME:
                    client.login(s.SMTP_USERNAME, s.SMTP_PASSWORD)
                client.send_message(msg)
        else:
            with smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=s.SMTP_TIMEOUT_S) as client:
                client.ehlo()
                if s.SMTP_USERNAME:
                    client.login(s.SMTP_USERNAME, s.SMTP_PASSWORD)
                client.send_message(msg)
    except EmailNotConfigured:
        raise
    except Exception as e:
        # Never include message content in the error (it may contain the code).
        raise EmailError(f"Could not deliver email to {to_email}: {type(e).__name__}") from e


def send_verification_code(to_email: str, name: str, code: str) -> None:
    """Send the verification OTP. `code` is used once and never logged."""
    s = get_settings()
    subject, body = render_verification_email(name, code, s.OTP_EXPIRE_MINUTES)
    send_email(to_email, subject, body)
    del subject, body
