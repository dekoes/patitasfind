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
    # Tokens emitidos antes de cambiar la contraseña o de "cerrar sesión en todos lados" ya no sirven
    # (los tokens anteriores a este cambio no traen "tv" y cuentan como versión 0)
    try:
        token_version = int(payload.get("tv", 0))
    except (TypeError, ValueError):
        return None
    if token_version != (user.token_version or 0):
        return None
    if user.role in ("admin", "superadmin"):
        # Sesión de admin que no cumple la política de verificación en dos pasos (p. ej. emitida antes de activarla):
        # no sirve para nada, tampoco en las comprobaciones de personal fuera de require_admin (moderation.is_staff,
        # privacy, pedidos, productos...)
        from app.services import totp

        if not totp.session_mfa_ok(user, payload):
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


def get_verified_user(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    """Usuario con teléfono verificado (o exento: admins y demo). Para acciones de escritura."""
    if current_user.phone_verification_required:
        raise PhoneVerificationRequired()
    # L-edad: cuenta en verificación reforzada o creada con Google sin fecha de nacimiento -> solo lectura
    if current_user.age_check_required or current_user.age_declaration_required:
        from app.services.age_check import AGE_CHECK_MESSAGE
        from app.services.legal_acceptance import ComplianceError

        if current_user.age_check_required:
            raise ComplianceError(403, AGE_CHECK_MESSAGE, "age_check_required")
        raise ComplianceError(403, "Indica tu fecha de nacimiento y confirma que tienes 18 años o más para continuar",
                              "age_declaration_required")
    # terminos.html 29.2: con una versión vigente de los Términos o del Aviso sin aceptar, la cuenta no puede escribir
    # (la ventana de aceptación de la app es solo la cara visible; aquí se hace cumplir)
    from app.services import legal_acceptance

    if legal_acceptance.blocking_pending(db, current_user):
        raise legal_acceptance.ComplianceError(403, legal_acceptance.LEGAL_ACCEPTANCE_MESSAGE,
                                               legal_acceptance.LEGAL_ACCEPTANCE_REQUIRED)
    return current_user


def get_optional_user(
    token: str | None = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> User | None:
    return _user_from_token(token, db)


MFA_SESSION_REQUIRED = "Vuelve a iniciar sesión con tu verificación en dos pasos."


def _require_admin_mfa(user: User, token: str | None) -> None:
    """Sesiones de admin: si la MFA es obligatoria o la tiene activa, el token debe traer "mfa": 1 (services/totp)."""
    from app.services import totp

    if not totp.session_mfa_ok(user, decode_access_token(token) if token else None):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=MFA_SESSION_REQUIRED,
                            headers={"WWW-Authenticate": "Bearer"})


def require_admin(current_user: User = Depends(get_current_user), token: str = Depends(oauth2_scheme)) -> User:
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Necesitas permisos de administrador.",
        )
    _require_admin_mfa(current_user, token)
    return current_user


def require_superadmin(current_user: User = Depends(get_current_user), token: str = Depends(oauth2_scheme)) -> User:
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Necesitas permisos de superadministrador.",
        )
    _require_admin_mfa(current_user, token)
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
