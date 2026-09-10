"""Auth dependencies. Tenant (company_id) always comes from the verified
session — never from client-supplied fields."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..core.security import decode_token
from ..db import connect

_bearer = HTTPBearer(auto_error=False)


def get_current_session(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated")
    claims = decode_token(creds.credentials)
    if not claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token")
    con = connect()
    try:
        row = con.execute(
            "SELECT s.*, u.role AS user_role FROM sessions s"
            " JOIN users u ON u.id = s.user_id"
            " WHERE s.jti = ? AND s.revoked = 0",
            (claims.get("jti"),),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session revoked or user deactivated")
    return {"user_id": int(claims["sub"]),
            "company_id": int(claims["company_id"]),
            "role": str(claims["role"]), "jti": str(claims["jti"])}


def require_roles(*roles: str):
    def _check(sess: dict = Depends(get_current_session)) -> dict:
        if sess["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Insufficient role")
        return sess
    return _check
