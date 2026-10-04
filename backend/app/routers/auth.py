import logging
from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token, create_password_reset_token, decode_password_reset_token, get_password_hash,
    password_fingerprint_matches, verify_password,
)
from app.config import settings
from app.database import get_db
from app.models import User
from app.oauth import get_google_authorize_url, get_google_userinfo, is_google_configured
from app.schemas import ForgotPasswordRequest, ResetPasswordRequest, Token, UserCreate
from app.services.email import send_email

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)
MIN_PASSWORD = 8


def _create_token(user: User) -> dict:
    token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=timedelta(minutes=settings.access_token_expire_minutes)
    )
    return {"access_token": token, "token_type": "bearer"}


def _normalize_email(email: str) -> str:
    try:
        return validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise HTTPException(status_code=400, detail="El correo electrónico no es válido.")


def _check_password(password: str):
    if not password or len(password) < MIN_PASSWORD:
        raise HTTPException(status_code=400, detail=f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")


def _find_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()


def _frontend_base(request: Request) -> str:
    if settings.public_base_url:
        return settings.public_base_url
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.hostname))
    return f"{scheme}://{host}"


@router.get("/auth/config")
def auth_config():
    return {
        "google_enabled": settings.google_enabled,
        "demo_enabled": settings.demo_enabled,
        "otp_enabled": settings.otp_enabled,
        "payments_enabled": settings.payments_enabled,
        "ai_enabled": settings.ai_enabled,
        "whatsapp_enabled": settings.whatsapp_enabled,
        "environment": settings.environment,
    }


@router.post("/auth/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    email = _normalize_email(payload.email)
    _check_password(payload.password)
    if not payload.full_name or not payload.full_name.strip():
        raise HTTPException(status_code=400, detail="Escribe tu nombre.")
    if _find_user_by_email(db, email):
        raise HTTPException(status_code=400, detail="Este correo ya está registrado")

    user = User(
        email=email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name.strip(),
        phone=payload.phone,
        city=payload.city,
        country=payload.country,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _create_token(user)


@router.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = _find_user_by_email(db, form_data.username or "")
    if not user or not user.hashed_password or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Correo o contraseña incorrectos")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tu cuenta está desactivada.")
    return _create_token(user)


@router.post("/auth/demo-login", response_model=Token)
def demo_login(db: Session = Depends(get_db)):
    if not settings.demo_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El acceso de demostración está desactivado.")
    email = "demo@patitasfind.example.com"
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email, hashed_password=None, full_name="Usuario Demo", phone="5512345678",
            city="Ciudad de México", country="México", latitude=19.4326, longitude=-99.1332,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return _create_token(user)


@router.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    response = {"ok": True}
    user = _find_user_by_email(db, payload.email or "")
    if not user or not user.is_active:
        return response
    token = create_password_reset_token(user.id, user.hashed_password)
    link = settings.public_url(f"/app/?reset={token}")
    text = (
        f"Hola {user.full_name}:\n\n"
        "Recibimos una solicitud para restablecer tu contraseña de PatitasFind.\n"
        f"Abre este enlace (vence en 1 hora):\n{link}\n\n"
        "Si no fuiste tú, puedes ignorar este correo. 🐾"
    )
    html = (
        f"<p>Hola {user.full_name}:</p><p>Recibimos una solicitud para restablecer tu contraseña de PatitasFind.</p>"
        f'<p><a href="{link}" style="background:#f97316;color:#fff;padding:10px 18px;border-radius:8px;'
        'text-decoration:none">Restablecer contraseña</a></p><p>El enlace vence en 1 hora. '
        "Si no fuiste tú, ignora este correo. 🐾</p>"
    )
    sent = send_email(user.email, "Restablece tu contraseña de PatitasFind", text, html)
    if not sent:
        print(f"[forgot-password] Enlace de restablecimiento para {user.email}: {link}", flush=True)
        if settings.is_development:
            response["dev_link"] = link
    return response


@router.post("/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    data = decode_password_reset_token(payload.token or "")
    if not data:
        raise HTTPException(status_code=400, detail="El enlace no es válido o ya expiró. Solicita uno nuevo.")
    _check_password(payload.password)
    user = db.query(User).filter(User.id == int(data["sub"])).first()
    if not user or not password_fingerprint_matches(data, user.hashed_password):
        raise HTTPException(status_code=400, detail="El enlace no es válido o ya se usó. Solicita uno nuevo.")
    user.hashed_password = get_password_hash(payload.password)
    db.commit()
    return {"ok": True}


def _get_google_redirect_uri(request: Request) -> str:
    if settings.public_base_url:
        return f"{settings.public_base_url}/auth/google/callback"
    return f"{_frontend_base(request)}/auth/google/callback"


@router.get("/auth/google/login")
def google_login(request: Request):
    if not is_google_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El inicio de sesión con Google no está disponible por ahora.",
        )
    return RedirectResponse(get_google_authorize_url(_get_google_redirect_uri(request)))


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    if error:
        return RedirectResponse(f"{_frontend_base(request)}/app/?auth_error={error}")
    if not code:
        raise HTTPException(status_code=400, detail="Falta el código de autorización de Google.")
    try:
        userinfo = get_google_userinfo(str(request.url), _get_google_redirect_uri(request))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error validando con Google: %s", exc)
        raise HTTPException(status_code=400, detail="No pudimos validar tu cuenta de Google. Inténtalo de nuevo.")

    email = (userinfo.get("email") or "").lower()
    if not email:
        raise HTTPException(status_code=400, detail="Google no compartió tu correo.")
    user = _find_user_by_email(db, email)
    if not user:
        user = User(
            email=email, hashed_password=None, full_name=userinfo.get("name") or email.split("@")[0],
            avatar_url=userinfo.get("picture"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.avatar_url and userinfo.get("picture"):
        user.avatar_url = userinfo["picture"]
        db.commit()

    token = _create_token(user)
    return RedirectResponse(f"{_frontend_base(request)}/app/?token={token['access_token']}")
