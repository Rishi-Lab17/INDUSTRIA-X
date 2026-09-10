"""Password hashing (bcrypt), JWT session tokens."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
from jose import JWTError, jwt

from .config import get_settings

ROLES = ("COMPANY_ADMIN", "ENGINEER", "TECHNICIAN")

# bcrypt truncates inputs at 72 bytes; reject longer passwords loudly
# instead of silently weakening them.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    if len(pw) > MAX_PASSWORD_BYTES:
        raise ValueError("Password must not exceed 72 bytes")
    salt = _bcrypt.gensalt(rounds=get_settings().BCRYPT_ROUNDS)
    return _bcrypt.hashpw(pw, salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def create_access_token(user_id: int, company_id: int, role: str) -> tuple[str, str]:
    """Returns (token, jti). Session row must be persisted by the caller."""
    s = get_settings()
    jti = uuid.uuid4().hex
    exp = utcnow() + timedelta(minutes=s.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "company_id": company_id, "role": role,
               "jti": jti, "exp": exp}
    token = jwt.encode(payload, s.JWT_SECRET, algorithm=s.JWT_ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict | None:
    s = get_settings()
    try:
        return jwt.decode(token, s.JWT_SECRET, algorithms=[s.JWT_ALGORITHM])
    except JWTError:
        return None
