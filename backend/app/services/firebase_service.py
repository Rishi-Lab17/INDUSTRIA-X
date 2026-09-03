"""Firebase phone authentication — verification ONLY.

Firebase proves ownership of a phone number. Everything else (company
membership, RBAC, sessions, audit, isolation) stays in INDUSTRIA-X.
Requires firebase-admin + service-account credentials; otherwise every call
fails loudly with FirebaseNotConfigured (HTTP 501), never a fake success.
"""
from ..core.config import get_settings


class FirebaseNotConfigured(Exception):
    pass


class FirebaseTokenInvalid(Exception):
    pass


_app_initialized = False


def _ensure_app():
    global _app_initialized
    if _app_initialized:
        return
    s = get_settings()
    if not s.FIREBASE_PROJECT_ID or not s.FIREBASE_CREDENTIALS_FILE:
        raise FirebaseNotConfigured(
            "Firebase phone auth is not configured. Set FIREBASE_PROJECT_ID and "
            "FIREBASE_CREDENTIALS_FILE in .env (see .env.example)."
        )
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError as e:
        raise FirebaseNotConfigured(
            "firebase-admin package is not installed.") from e
    try:
        cred = credentials.Certificate(s.FIREBASE_CREDENTIALS_FILE)
        firebase_admin.initialize_app(cred, {"projectId": s.FIREBASE_PROJECT_ID})
    except Exception as e:
        raise FirebaseNotConfigured(f"Could not initialize Firebase: {type(e).__name__}") from e
    _app_initialized = True


def verify_id_token(id_token: str) -> dict:
    """Verify a Firebase ID token. Returns {'phone_number': ...} on success."""
    _ensure_app()
    try:
        from firebase_admin import auth as fb_auth
    except ImportError as e:
        raise FirebaseNotConfigured("firebase-admin package is not installed.") from e
    if not id_token or len(id_token) > 8192:
        raise FirebaseTokenInvalid("Invalid token")
    try:
        claims = fb_auth.verify_id_token(id_token, clock_skew_seconds=30)
    except Exception as e:
        raise FirebaseTokenInvalid("Token verification failed") from e
    phone = claims.get("phone_number")
    if not phone:
        raise FirebaseTokenInvalid("Token has no verified phone number")
    return {"phone_number": str(phone), "uid": str(claims.get("uid", ""))}
