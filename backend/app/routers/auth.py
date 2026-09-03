"""Authentication: company registration, email-OTP verification, login/logout,
sessions (persisted + revocable), RBAC user management, phone linking, audit read.

OTP rule: the code is emailed to the user and NEVER returned by any API,
NEVER logged, NEVER rendered by the frontend.
"""
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.config import get_settings
from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import (ROLES, create_access_token, hash_otp, hash_password,
                             new_otp_code, utcnow, utcnow_iso, verify_password)
from ..db import connect
from ..services import email_service
from ..services import firebase_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


def mask_email(email: str) -> str:
    """rishi@example.com -> r****@example.com (safe for UI display)."""
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return "****"
    if len(local) <= 1:
        masked = "*"
    else:
        masked = local[0] + "****"
    return f"{masked}@{domain}"


class RegisterIn(BaseModel):
    company_name: str
    name: str
    email: str
    password: str
    mobile_number: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email")
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("company_name", "name")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Must not be empty")
        return v.strip()

    @field_validator("mobile_number")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip().replace(" ", "").replace("-", "")
        if not _PHONE_RE.match(v):
            raise ValueError("Invalid mobile number (use 7-15 digits, optional leading +)")
        return v


class VerifyOtpIn(BaseModel):
    email: str
    code: str


class ResendOtpIn(BaseModel):
    email: str


class PhoneLinkIn(BaseModel):
    id_token: str


class LoginIn(BaseModel):
    email: str
    password: str


class CreateUserIn(BaseModel):
    name: str
    email: str
    password: str
    role: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email")
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError(f"Role must be one of {ROLES}")
        return v


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request):
    s = get_settings()
    con = connect()
    try:
        if con.execute("SELECT 1 FROM users WHERE email = ?", (body.email,)).fetchone():
            raise HTTPException(status_code=409, detail="Email already registered")
        if con.execute("SELECT 1 FROM companies WHERE name = ?",
                       (body.company_name,)).fetchone():
            raise HTTPException(status_code=409, detail="Company already exists")
        cur = con.execute("INSERT INTO companies (name, created_at) VALUES (?, ?)",
                          (body.company_name, utcnow_iso()))
        company_id = cur.lastrowid
        cur = con.execute(
            "INSERT INTO users (company_id, name, email, password_hash, role, is_active,"
            " phone, phone_verified, created_at)"
            " VALUES (?, ?, ?, ?, 'COMPANY_ADMIN', 0, ?, 0, ?)",
            (company_id, body.name, body.email, hash_password(body.password),
             body.mobile_number, utcnow_iso()),
        )
        user_id = cur.lastrowid
        code = new_otp_code()
        exp = (utcnow() + timedelta(minutes=s.OTP_EXPIRE_MINUTES)).isoformat()
        con.execute(
            "INSERT INTO otp_codes (user_id, code_hash, expires_at, created_at)"
            " VALUES (?, ?, ?, ?)", (user_id, hash_otp(code), exp, utcnow_iso()))
        con.commit()
    finally:
        con.close()
    # Deliver OUT-OF-BAND only. The code never appears in any API response,
    # log line, or frontend view.
    try:
        email_service.send_verification_code(body.email, body.name, code)
    except email_service.EmailNotConfigured as e:
        log_event("register_email_failed", {"email": body.email, "reason": "not_configured"},
                  company_id=company_id, user_id=user_id, ip=_client_ip(request))
        raise HTTPException(status_code=502, detail=str(e))
    except email_service.EmailError:
        log_event("register_email_failed", {"email": body.email, "reason": "delivery_failed"},
                  company_id=company_id, user_id=user_id, ip=_client_ip(request))
        raise HTTPException(
            status_code=502,
            detail="Could not send verification email. Please use Resend Code to retry.")
    finally:
        code = "******"  # drop the plaintext code from this scope immediately
    log_event("register", {"email": body.email}, company_id=company_id,
              user_id=user_id, ip=_client_ip(request))
    return {"message": "Verification code sent to your email address.",
            "email_masked": mask_email(body.email)}


def _latest_pending_otp(con, user_id: int):
    return con.execute(
        "SELECT * FROM otp_codes WHERE user_id = ? AND consumed = 0"
        " ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()


@router.post("/verify-otp")
def verify_otp(body: VerifyOtpIn, request: Request):
    s = get_settings()
    email = body.email.strip().lower()
    ok, retry_after = allow(f"otp-verify:{email}",
                            s.OTP_VERIFY_MAX_PER_WINDOW, s.OTP_VERIFY_WINDOW_S)
    if not ok:
        raise HTTPException(status_code=429,
                            detail="Too many attempts. Please try again later.")
    con = connect()
    try:
        user = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None:
            # Generic message: do not reveal whether the email is registered.
            raise HTTPException(status_code=400,
                                detail="Invalid verification code. Please try again.")
        otp = _latest_pending_otp(con, user["id"])
        if otp is None:
            if user["is_active"]:
                raise HTTPException(status_code=400,
                                    detail="Email is already verified. Please log in.")
            raise HTTPException(status_code=400,
                                detail="Verification code expired. Please request a new code.")
        if otp["attempts"] >= s.OTP_MAX_ATTEMPTS:
            con.execute("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (otp["id"],))
            con.commit()
            raise HTTPException(status_code=400,
                                detail="Too many attempts. Please request a new code.")
        if otp["expires_at"] < utcnow_iso():
            con.execute("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (otp["id"],))
            con.commit()
            raise HTTPException(status_code=400,
                                detail="Verification code expired. Please request a new code.")
        if hash_otp(body.code.strip()) != otp["code_hash"]:
            con.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?",
                        (otp["id"],))
            con.commit()
            raise HTTPException(status_code=400,
                                detail="Invalid verification code. Please try again.")
        # Single use: consume immediately, then activate (replay is impossible).
        con.execute("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (otp["id"],))
        con.execute("UPDATE users SET is_active = 1 WHERE id = ?", (user["id"],))
        con.commit()
        company_id, user_id = user["company_id"], user["id"]
    finally:
        con.close()
    log_event("otp_verified", {"email": email}, company_id=company_id,
              user_id=user_id, ip=_client_ip(request))
    return {"message": "Email verified successfully. You can now log in."}


@router.post("/resend-otp")
def resend_otp(body: ResendOtpIn, request: Request):
    s = get_settings()
    email = body.email.strip().lower()
    generic_ok = {"message": "If this email is registered and unverified, "
                            "a new verification code has been sent.",
                  "email_masked": mask_email(email)}
    # Cooldown: max 1 resend per OTP_RESEND_COOLDOWN_S per email.
    ok, retry_after = allow(f"otp-resend-cool:{email}", 1, s.OTP_RESEND_COOLDOWN_S)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {retry_after} seconds before requesting a new code.",
            headers={"Retry-After": str(retry_after)})
    # Hourly cap against OTP bombing.
    ok, _ = allow(f"otp-resend-hour:{email}", s.OTP_RESEND_MAX_PER_HOUR, 3600)
    if not ok:
        raise HTTPException(status_code=429,
                            detail="Too many code requests. Please try again later.")
    con = connect()
    try:
        user = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or user["is_active"]:
            # Generic response: never reveal registration state.
            return generic_ok
        # Invalidate ALL previous pending codes, then issue a fresh one.
        con.execute("UPDATE otp_codes SET consumed = 1 WHERE user_id = ? AND consumed = 0",
                    (user["id"],))
        code = new_otp_code()
        exp = (utcnow() + timedelta(minutes=s.OTP_EXPIRE_MINUTES)).isoformat()
        con.execute(
            "INSERT INTO otp_codes (user_id, code_hash, expires_at, created_at)"
            " VALUES (?, ?, ?, ?)", (user["id"], hash_otp(code), exp, utcnow_iso()))
        con.commit()
        name, user_id, company_id = user["name"], user["id"], user["company_id"]
    finally:
        con.close()
    try:
        email_service.send_verification_code(email, name, code)
    except email_service.EmailError:
        log_event("resend_email_failed", {"email": email},
                  company_id=company_id, user_id=user_id, ip=_client_ip(request))
        raise HTTPException(
            status_code=502,
            detail="Could not send verification email. Please try again.")
    finally:
        code = "******"
    log_event("otp_resent", {"email": email}, company_id=company_id,
              user_id=user_id, ip=_client_ip(request))
    return {"message": "Verification code sent to your email address.",
            "email_masked": mask_email(email)}


@router.post("/phone/link")
def link_phone(body: PhoneLinkIn, request: Request,
               sess: dict = Depends(get_current_session)):
    """Link a Firebase-verified phone number to the current INDUSTRIA-X user.

    Firebase only proves number ownership. Company, role, sessions and audit
    remain 100% INDUSTRIA-X.
    """
    try:
        result = firebase_service.verify_id_token(body.id_token)
    except firebase_service.FirebaseNotConfigured as e:
        raise HTTPException(status_code=501, detail=str(e))
    except firebase_service.FirebaseTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid phone credential")
    con = connect()
    try:
        con.execute("UPDATE users SET phone = ?, phone_verified = 1 WHERE id = ?",
                    (result["phone_number"], sess["user_id"]))
        con.commit()
    finally:
        con.close()
    log_event("phone_linked", {"phone_masked": result["phone_number"][-4:].rjust(
        len(result["phone_number"]), "*")}, company_id=sess["company_id"],
        user_id=sess["user_id"], ip=_client_ip(request))
    return {"message": "Phone number verified and linked.",
            "phone_masked": result["phone_number"][-4:].rjust(
                len(result["phone_number"]), "*")}


@router.post("/login")
def login(body: LoginIn, request: Request):
    s = get_settings()
    email = body.email.strip().lower()
    con = connect()
    try:
        user = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or not verify_password(body.password, user["password_hash"]):
            log_event("login_failed", {"email": email}, ip=_client_ip(request))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid email or password")
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Account not verified. Please verify your email first.")
        token, jti = create_access_token(int(user["id"]), int(user["company_id"]), user["role"])
        exp = (utcnow() + timedelta(minutes=s.ACCESS_TOKEN_EXPIRE_MINUTES)).isoformat()
        con.execute(
            "INSERT INTO sessions (jti, user_id, company_id, expires_at, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (jti, user["id"], user["company_id"], exp, utcnow_iso()))
        con.commit()
        payload = {"access_token": token, "token_type": "bearer",
                   "user": {"id": user["id"], "name": user["name"], "email": user["email"],
                            "role": user["role"], "company_id": user["company_id"]}}
        company_id, user_id = user["company_id"], user["id"]
    finally:
        con.close()
    log_event("login", {"email": email}, company_id=company_id,
              user_id=user_id, ip=_client_ip(request))
    return payload


@router.post("/logout")
def logout(request: Request, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        con.execute("UPDATE sessions SET revoked = 1 WHERE jti = ?", (sess["jti"],))
        con.commit()
    finally:
        con.close()
    log_event("logout", {}, company_id=sess["company_id"],
              user_id=sess["user_id"], ip=_client_ip(request))
    return {"message": "Logged out"}


@router.get("/me")
def me(sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        user = con.execute("SELECT id, name, email, role, company_id FROM users WHERE id = ?",
                           (sess["user_id"],)).fetchone()
        company = con.execute("SELECT id, name FROM companies WHERE id = ?",
                              (sess["company_id"],)).fetchone()
    finally:
        con.close()
    return {"user": dict(user), "company": dict(company)}


@router.post("/users", status_code=201, dependencies=[Depends(require_roles("COMPANY_ADMIN"))])
def create_user(body: CreateUserIn, request: Request,
                sess: dict = Depends(get_current_session)):
    email = body.email
    con = connect()
    try:
        if con.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="Email already registered")
        # Tenant comes from the session, never from the request body.
        cur = con.execute(
            "INSERT INTO users (company_id, name, email, password_hash, role, is_active, created_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?)",
            (sess["company_id"], body.name.strip(), email,
             hash_password(body.password), body.role, utcnow_iso()))
        user_id = cur.lastrowid
        con.commit()
    finally:
        con.close()
    log_event("user_created", {"email": email, "role": body.role},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request))
    return {"user_id": user_id, "message": f"{body.role} account created."}


@router.get("/users", dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def list_users(sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        rows = con.execute(
            "SELECT id, name, email, role, is_active, created_at FROM users"
            " WHERE company_id = ? ORDER BY id", (sess["company_id"],)).fetchall()
    finally:
        con.close()
    return {"users": [dict(r) for r in rows]}


@router.get("/audit", dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def read_audit(sess: dict = Depends(get_current_session), limit: int = 50):
    limit = max(1, min(limit, 200))
    con = connect()
    try:
        # Strictly company-scoped: a tenant sees only its own events.
        rows = con.execute(
            "SELECT id, user_id, action, detail, ip, created_at FROM audit_events"
            " WHERE company_id = ? ORDER BY id DESC LIMIT ?",
            (sess["company_id"], limit)).fetchall()
    finally:
        con.close()
    return {"events": [dict(r) for r in rows]}
