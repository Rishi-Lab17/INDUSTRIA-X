"""Password hashing (bcrypt), OTP hashing (sha256), JWT session tokens."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import get_settings

ROLES = ("COMPANY_ADMIN", "ENGINEER", "TECHNICIAN")

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd.verify(password, password_hash)
    except Exception:
        return False


def new_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


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
