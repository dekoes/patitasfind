from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.auth import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def _user_from_token(token: str | None, db: Session) -> User | None:
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None or payload.get("sub") is None:
        return None
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    user = _user_from_token(token, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tu sesión no es válida o expiró. Inicia sesión de nuevo.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


PHONE_VERIFICATION_CODE = "phone_verification_required"
PHONE_VERIFICATION_MESSAGE = "Verifica tu teléfono para continuar"


class PhoneVerificationRequired(Exception):
    """Se convierte en 403 {"detail": "...", "code": "phone_verification_required"} (ver main.py)."""


def get_verified_user(current_user: User = Depends(get_current_user)) -> User:
    """Usuario con teléfono verificado (o exento: admins y demo). Para acciones de escritura."""
    if current_user.phone_verification_required:
        raise PhoneVerificationRequired()
    return current_user


def get_optional_user(
    token: str | None = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> User | None:
    return _user_from_token(token, db)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Necesitas permisos de administrador.",
        )
    return current_user


def client_ip(request: Request) -> str:
    # Nginx sobrescribe X-Real-IP con $remote_addr (no lo puede falsificar el cliente);
    # app/server.py (desarrollo) sobrescribe X-Forwarded-For.
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
