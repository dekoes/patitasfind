import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError

from app.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
    # Los tokens con "purpose" (p. ej. reset de contraseña) no sirven como sesión
    if payload.get("purpose"):
        return None
    return payload


def _password_fingerprint(hashed_password: str | None) -> str:
    """Huella del hash actual: invalida el token de reset una vez que se cambia la contraseña."""
    return hashlib.sha256((hashed_password or "sin-password").encode()).hexdigest()[:16]


def create_password_reset_token(user_id: int, hashed_password: str | None) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "purpose": "password_reset",
            "fp": _password_fingerprint(hashed_password),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def decode_password_reset_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
    if payload.get("purpose") != "password_reset":
        return None
    return payload


def password_fingerprint_matches(payload: dict, hashed_password: str | None) -> bool:
    return hmac.compare_digest(payload.get("fp", ""), _password_fingerprint(hashed_password))


def hash_otp(user_id: int, code: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"{user_id}:{code}".encode(), hashlib.sha256).hexdigest()
