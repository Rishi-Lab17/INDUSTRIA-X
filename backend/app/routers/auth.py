"""Authentication: company registration, OTP verification, login/logout,
sessions (persisted + revocable), RBAC user management, basic audit read."""
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.config import get_settings
from ..core.deps import get_current_session, require_roles
from ..core.security import (ROLES, create_access_token, hash_otp, hash_password,
                             new_otp_code, utcnow, utcnow_iso, verify_password)
from ..db import connect

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_ATTEMPTS = 5


class RegisterIn(BaseModel):
    company_name: str
    name: str
    email: str
    password: str

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


class VerifyOtpIn(BaseModel):
    email: str
    code: str


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
            "INSERT INTO users (company_id, name, email, password_hash, role, is_active, created_at)"
            " VALUES (?, ?, ?, ?, 'COMPANY_ADMIN', 0, ?)",
            (company_id, body.name, body.email, hash_password(body.password), utcnow_iso()),
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
    log_event("register", {"email": body.email}, company_id=company_id,
              user_id=user_id, ip=_client_ip(request))
    # Local-dev only: return the OTP so the hackathon demo can proceed without
    # an email server. Production MUST deliver it out-of-band instead.
    out = {"company_id": company_id, "user_id": user_id,
           "message": "Company registered. Verify the OTP to activate the admin account."}
    if s.APP_ENV == "local":
        out["dev_otp"] = code
    return out


@router.post("/verify-otp")
def verify_otp(body: VerifyOtpIn, request: Request):
    email = body.email.strip().lower()
    con = connect()
    try:
        user = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="Account not found")
        otp = con.execute(
            "SELECT * FROM otp_codes WHERE user_id = ? AND consumed = 0"
            " ORDER BY id DESC LIMIT 1", (user["id"],)).fetchone()
        if otp is None:
            raise HTTPException(status_code=400, detail="No pending OTP for this account")
        if otp["attempts"] >= _MAX_ATTEMPTS:
            con.execute("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (otp["id"],))
            con.commit()
            raise HTTPException(status_code=400, detail="Too many attempts. Register again.")
        if otp["expires_at"] < utcnow_iso():
            raise HTTPException(status_code=400, detail="OTP expired. Register again.")
        if hash_otp(body.code.strip()) != otp["code_hash"]:
            con.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?",
                        (otp["id"],))
            con.commit()
            raise HTTPException(status_code=400, detail="Invalid OTP")
        con.execute("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (otp["id"],))
        con.execute("UPDATE users SET is_active = 1 WHERE id = ?", (user["id"],))
        con.commit()
        company_id, user_id = user["company_id"], user["id"]
    finally:
        con.close()
    log_event("otp_verified", {"email": email}, company_id=company_id,
              user_id=user_id, ip=_client_ip(request))
    return {"message": "Account verified. You can now log in."}


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
            raise HTTPException(status_code=403, detail="Account not verified. Complete OTP verification.")
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
