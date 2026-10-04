import datetime
import logging
from datetime import timedelta
from urllib.parse import quote

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
from app.config import DEMO_EMAIL, settings
from app.database import get_db
from app.models import User
from app import oauth
from app.schemas import ForgotPasswordRequest, ResetPasswordRequest, Token, UserCreate
from app.services import otp, sms
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


def record_terms(user: User, marketing_opt_in: bool | None = None) -> None:
    user.terms_accepted_at = datetime.datetime.utcnow()
    user.terms_version = settings.legal_terms_version
    user.privacy_version = settings.legal_privacy_version
    if marketing_opt_in is not None:
        user.marketing_opt_in = bool(marketing_opt_in)


@router.get("/auth/config")
def auth_config():
    return {
        "google_enabled": settings.google_enabled,
        "demo_enabled": settings.demo_enabled,
        "otp_enabled": settings.otp_enabled,
        "require_phone_verification": settings.require_phone_verification,
        "sms_provider": settings.sms_effective_provider or "none",
        "otp_cooldown": settings.otp_resend_cooldown_seconds,
        "payments_enabled": settings.payments_enabled,
        "ai_enabled": settings.ai_enabled,
        "whatsapp_enabled": settings.whatsapp_enabled,
        "environment": settings.environment,
        "sentry_dsn_frontend": settings.sentry_dsn_frontend,
        "posthog_key": settings.posthog_key,
        "posthog_host": settings.posthog_host,
        "legal_versions": {"terms": settings.legal_terms_version, "privacy": settings.legal_privacy_version},
    }


@router.post("/auth/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    email = _normalize_email(payload.email)
    _check_password(payload.password)
    if not payload.full_name or not payload.full_name.strip():
        raise HTTPException(status_code=400, detail="Escribe tu nombre.")
    phone = None
    if payload.phone and payload.phone.strip():
        phone = sms.normalize_mx_phone(payload.phone)
        if not phone:
            raise HTTPException(status_code=400, detail="El número de celular no es válido. Usa 10 dígitos, p. ej. 55 1234 5678.")
    elif settings.require_phone_verification:
        raise HTTPException(status_code=400, detail="Escribe tu número de celular (10 dígitos).")
    if payload.accepted_terms is not True:
        raise HTTPException(status_code=400, detail="Debes aceptar los Términos y Condiciones y el Aviso de Privacidad para crear tu cuenta.")
    if _find_user_by_email(db, email):
        raise HTTPException(status_code=400, detail="Este correo ya está registrado")
    if phone and otp.phone_taken(db, phone, None):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=otp.PHONE_TAKEN)

    user = User(
        email=email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name.strip(),
        phone=phone,
        city=payload.city,
        country=payload.country,
    )
    record_terms(user, payload.marketing_opt_in)
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tu cuenta está desactivada.")
    return _create_token(user)


@router.post("/auth/demo-login", response_model=Token)
def demo_login(db: Session = Depends(get_db)):
    if not settings.demo_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El acceso de demostración está desactivado.")
    user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if not user:
        user = User(
            email=DEMO_EMAIL, hashed_password=None, full_name="Usuario Demo", phone="+525512345678",
            city="Ciudad de México", country="México", latitude=19.4326, longitude=-99.1332,
        )
        record_terms(user)
        db.add(user)
        db.commit()
        db.refresh(user)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tu cuenta está desactivada.")
    if not user.terms_accepted_at:
        # El usuario demo pudo crearse antes de existir el registro de términos
        record_terms(user)
        db.commit()
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
    if settings.google_redirect_uri:
        return settings.google_redirect_uri
    return f"{_frontend_base(request)}/auth/google/callback"


def _auth_error_redirect(request: Request, message: str) -> RedirectResponse:
    resp = RedirectResponse(f"{_frontend_base(request)}/app/?auth_error={quote(message)}", status_code=302)
    resp.delete_cookie(oauth.STATE_COOKIE, path="/auth/google")
    return resp


def _cookie_secure(request: Request) -> bool:
    base = settings.public_base_url or ""
    return base.startswith("https://") or request.headers.get("x-forwarded-proto") == "https"


@router.get("/auth/google/login")
def google_login(request: Request, accepted_terms: bool = False, marketing_opt_in: bool = False):
    """Inicia el flujo. El frontend puede pasar ?accepted_terms=1&marketing_opt_in=0 para registrar el
    consentimiento de cuentas nuevas (se transporta dentro del `state` firmado)."""
    if not oauth.is_google_configured():
        return _auth_error_redirect(request, "El inicio de sesión con Google no está disponible por ahora.")
    state, nonce = oauth.create_state({"t": 1 if accepted_terms else 0, "m": 1 if marketing_opt_in else 0})
    resp = RedirectResponse(oauth.get_google_authorize_url(_get_google_redirect_uri(request), state), status_code=302)
    resp.set_cookie(oauth.STATE_COOKIE, nonce, max_age=oauth.STATE_MAX_AGE, httponly=True, samesite="lax",
                    secure=_cookie_secure(request), path="/auth/google")
    return resp


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                    db: Session = Depends(get_db)):
    if error:
        msg = "Cancelaste el inicio de sesión con Google." if error == "access_denied" else "Google no pudo iniciar tu sesión."
        return _auth_error_redirect(request, msg)
    try:
        flags = oauth.verify_state(state, request.cookies.get(oauth.STATE_COOKIE))
    except oauth.OAuthError as exc:
        logger.warning("state de Google inválido: %s", exc)
        return _auth_error_redirect(request, str(exc))
    if not code:
        return _auth_error_redirect(request, "Falta el código de autorización de Google.")
    try:
        userinfo = oauth.get_google_userinfo(code, _get_google_redirect_uri(request))
    except oauth.OAuthError as exc:
        logger.warning("Error validando con Google: %s", exc)
        return _auth_error_redirect(request, "No pudimos validar tu cuenta de Google. Inténtalo de nuevo.")

    email = (userinfo.get("email") or "").strip().lower()
    sub = str(userinfo.get("sub") or "") or None
    verified = userinfo.get("email_verified") in (True, "true", "True")
    if not email:
        return _auth_error_redirect(request, "Google no compartió tu correo.")
    if not verified:
        return _auth_error_redirect(request, "Tu correo de Google no está verificado.")

    user = db.query(User).filter(User.google_sub == sub).first() if sub else None
    if user is None:
        user = _find_user_by_email(db, email)  # vincula con la cuenta existente del mismo correo verificado
    if user is None:
        user = User(
            email=email, hashed_password=None, full_name=(userinfo.get("name") or email.split("@")[0])[:255],
            avatar_url=userinfo.get("picture"), google_sub=sub,
        )
        if flags.get("t"):
            record_terms(user, bool(flags.get("m")))
        db.add(user)
    else:
        if not user.is_active:
            return _auth_error_redirect(request, "Tu cuenta está desactivada.")
        if sub and not user.google_sub:
            user.google_sub = sub
        if not user.avatar_url and userinfo.get("picture"):
            user.avatar_url = userinfo["picture"]
    db.commit()
    db.refresh(user)

    token = _create_token(user)
    resp = RedirectResponse(f"{_frontend_base(request)}/app/?token={token['access_token']}", status_code=302)
    resp.delete_cookie(oauth.STATE_COOKIE, path="/auth/google")
    return resp
