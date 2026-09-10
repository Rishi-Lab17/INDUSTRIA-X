"""Authentication: company registration, login/logout, sessions (persisted +
revocable), RBAC user management, phone linking, audit read.

Login uses email (as username/employee ID) + password. No email verification
required — accounts are immediately active after registration.
"""
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.config import get_settings
from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import (ROLES, create_access_token, hash_password,
                             utcnow, utcnow_iso, verify_password)
from ..db import connect
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
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 bytes")
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
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 bytes")
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
            " email_verified, phone, phone_verified, created_at)"
            " VALUES (?, ?, ?, ?, 'COMPANY_ADMIN', 1, 1, ?, 0, ?)",
            (company_id, body.name, body.email, hash_password(body.password),
             body.mobile_number, utcnow_iso()),
        )
        user_id = cur.lastrowid
        con.commit()
    finally:
        con.close()
    log_event("register", {"email": body.email}, company_id=company_id,
              user_id=user_id, ip=_client_ip(request))
    return {"message": "Registration successful. You can now log in.",
            "email_masked": mask_email(body.email)}


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
    email = body.email.strip().lower()
    con = connect()
    try:
        user = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or not verify_password(body.password, user["password_hash"]):
            log_event("login_failed", {"email": email}, ip=_client_ip(request))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid email or password")
        if not user["is_active"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Account is deactivated. Please contact your administrator.")
        token, jti = create_access_token(int(user["id"]), int(user["company_id"]), user["role"])
        exp = (utcnow() + timedelta(minutes=get_settings().ACCESS_TOKEN_EXPIRE_MINUTES)).isoformat()
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
        cur = con.execute(
            "INSERT INTO users (company_id, name, email, password_hash, role, is_active, email_verified, created_at)"
            " VALUES (?, ?, ?, ?, ?, 1, 1, ?)",
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
        rows = con.execute(
            "SELECT id, user_id, action, detail, ip, created_at FROM audit_events"
            " WHERE company_id = ? ORDER BY id DESC LIMIT ?",
            (sess["company_id"], limit)).fetchall()
    finally:
        con.close()
    return {"events": [dict(r) for r in rows]}
