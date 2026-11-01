import datetime
import hashlib
import logging
import threading
import time
from datetime import timedelta
from html import escape
from urllib.parse import quote

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import cache
from app.auth import (
    PASSWORD_TOO_LONG, create_access_token, create_email_verification_token, create_password_reset_token,
    decode_email_verification_token, decode_password_reset_token, email_fingerprint_matches, get_password_hash,
    password_fingerprint_matches, password_too_long, verify_password,
)
from app.config import DEMO_EMAIL, settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import MfaRecoveryCode, User
from app import oauth
from app.schemas import ForgotPasswordRequest, ResetPasswordRequest, Token, UserCreate, VerifyEmailRequest
from app.schemas import LoginResponse, MfaCodeRequest, MfaEnableRequest, MfaSetupRequest, MfaVerifyRequest
from app.services import otp, ratelimit, sms, totp
from app.services.email import send_email
from app.utils.notifications import create_notification

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)
MIN_PASSWORD = 8
ADMIN_ROLES = ("admin", "superadmin")
# Dominios reservados (RFC 2606): en producción no se puede registrar ni iniciar sesión con ellos
RESERVED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
RESERVED_EMAIL = "Usa un correo real: ese dominio está reservado y no puede recibir mensajes."

# Bloqueo por cuenta tras varios intentos fallidos (aplica igual exista o no el correo)
LOGIN_MAX_FAILURES = 10
LOGIN_LOCK_SECONDS = 15 * 60
LOGIN_LOCKED = "Demasiados intentos, intenta de nuevo en 15 minutos"
_fail_lock = threading.Lock()
_fail_local: dict[str, list[float]] = {}


def create_session_token(user: User, mfa: bool = False) -> dict:
    """JWT de sesión. Lleva "tv" (token_version) para poder revocarlo; admins duran 8 horas.

    mfa=True agrega el claim "mfa": 1 (pasó la verificación en dos pasos); require_admin lo exige a los admins
    cuando la MFA es obligatoria o la tienen activa (services/totp.session_mfa_ok).
    """
    minutes = settings.access_token_expire_minutes
    if user.role in ADMIN_ROLES:
        minutes = min(minutes, settings.admin_token_expire_minutes)
    data = {"sub": str(user.id), "tv": user.token_version or 0}
    if mfa:
        data["mfa"] = 1
    token = create_access_token(data=data, expires_delta=timedelta(minutes=minutes))
    return {"access_token": token, "token_type": "bearer"}


def login_or_mfa_step(user: User) -> dict:
    """Sesión directa, o el segundo paso si es admin y le toca la verificación en dos pasos."""
    if not totp.login_needs_mfa(user):
        return create_session_token(user)
    enroll = not totp.user_has_mfa(user)
    return {"mfa_required": True, "mfa_token": totp.create_mfa_token(user, enroll=enroll), "token_type": "mfa",
            "mfa_enrollment_required": enroll}


def revoke_sessions(user: User) -> None:
    """Invalida todos los tokens emitidos hasta ahora (quien llama hace el commit)."""
    user.token_version = (user.token_version or 0) + 1


def _normalize_email(email: str) -> str:
    try:
        return validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise HTTPException(status_code=400, detail="El correo electrónico no es válido.")


def check_new_password(password: str | None, label: str = "La contraseña") -> None:
    if not password or len(password) < MIN_PASSWORD:
        raise HTTPException(status_code=400, detail=f"{label} debe tener al menos {MIN_PASSWORD} caracteres.")
    if password_too_long(password):
        raise HTTPException(status_code=422, detail=PASSWORD_TOO_LONG)


def is_reserved_email(email: str | None) -> bool:
    email = (email or "").strip().lower()
    if email == DEMO_EMAIL:
        return True
    domain = email.rpartition("@")[2]
    return any(domain == d or domain.endswith("." + d) for d in RESERVED_EMAIL_DOMAINS)


def _blocked_email(email: str | None) -> bool:
    """La cuenta demo y los dominios de ejemplo solo existen fuera de producción."""
    return settings.is_production and is_reserved_email(email)


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


ADULT_REQUIRED = "Marca la casilla en la que declaras tener 18 años o más."


def check_age_declaration(is_adult: bool | None, birth_date) -> datetime.date:
    """Casilla separada de 18+ y fecha de nacimiento (L-edad). Devuelve la fecha validada."""
    from app.services.age_check import check_birth_date

    if is_adult is not True:
        raise HTTPException(status_code=400, detail=ADULT_REQUIRED)
    return check_birth_date(birth_date)


def record_signup_acceptances(db: Session, user: User, request: Request | None, marketing_opt_in: bool | None,
                              method: str = "registro", channel: str = "registro", record_age: bool = True) -> None:
    """Bitácora del registro: Términos, Aviso de Privacidad y declaración de 18+ (cada una con versión y SHA-256),
    más la constancia del permiso de correos promocionales si lo dio. Requiere user.id (sin commit)."""
    from app.services import consent
    from app.services.legal_acceptance import AGE_SLUG, PRIVACY_SLUG, TERMS_SLUG, record_acceptance

    for slug in (TERMS_SLUG, PRIVACY_SLUG):
        record_acceptance(db, user, slug, method, request)
    # La fecha de nacimiento va con la declaración (conservacion.html: bitácora de 18+ y fecha de nacimiento)
    if record_age and user.adult_declared_at is not None:
        record_acceptance(db, user, AGE_SLUG, "registro", request,
                          context={"birth_date": user.birth_date.isoformat()} if user.birth_date else None)
    if marketing_opt_in:
        consent.set_preference(db, user, "email_marketing", True, channel=channel, request=request)


# --------------------------------------------------------------------------- bloqueo de inicio de sesión
def _login_key(email: str) -> str:
    return "login-fail:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


def _login_locked(key: str) -> bool:
    r = cache._get_redis()
    if r is not None:
        try:
            return int(r.get(key) or 0) >= LOGIN_MAX_FAILURES
        except Exception:  # noqa: BLE001
            pass
    now = time.time()
    with _fail_lock:
        hits = [t for t in _fail_local.get(key, []) if now - t < LOGIN_LOCK_SECONDS]
        if hits:
            _fail_local[key] = hits
        else:
            _fail_local.pop(key, None)
        return len(hits) >= LOGIN_MAX_FAILURES


def _register_login_failure(key: str) -> None:
    r = cache._get_redis()
    if r is not None:
        try:
            count = r.incr(key)
            # La ventana de 15 min empieza con el primer fallo; al llegar al límite se reinicia para
            # que el bloqueo dure 15 min completos
            if count == 1 or count >= LOGIN_MAX_FAILURES:
                r.expire(key, LOGIN_LOCK_SECONDS)
            return
        except Exception:  # noqa: BLE001
            pass
    now = time.time()
    with _fail_lock:
        hits = [t for t in _fail_local.get(key, []) if now - t < LOGIN_LOCK_SECONDS] + [now]
        _fail_local[key] = [now] * len(hits) if len(hits) >= LOGIN_MAX_FAILURES else hits


def _clear_login_failures(key: str) -> None:
    r = cache._get_redis()
    if r is not None:
        try:
            r.delete(key)
        except Exception:  # noqa: BLE001
            pass
    with _fail_lock:
        _fail_local.pop(key, None)


# --------------------------------------------------------------------------- verificación de correo
def send_verification_email(user_id: int, email: str, full_name: str | None) -> tuple[bool, str]:
    """Envía el enlace /app/#verify_email=<token>. Devuelve (enviado, enlace)."""
    token = create_email_verification_token(user_id, email)
    link = settings.public_url(f"/app/#verify_email={token}")
    text = (
        f"Hola {full_name or ''}:\n\n"
        "Confirma tu correo para terminar de configurar tu cuenta de GuauWoow.\n"
        f"Abre este enlace (vence en 48 horas):\n{link}\n\n"
        "Si no creaste una cuenta, puedes ignorar este correo. 🐾"
    )
    html_body = (
        f"<p>Hola {escape(full_name or '')}:</p><p>Confirma tu correo para terminar de configurar tu cuenta de "
        f'GuauWoow.</p><p><a href="{escape(link, quote=True)}" style="background:#f97316;color:#fff;'
        'padding:10px 18px;border-radius:8px;text-decoration:none">Confirmar mi correo</a></p>'
        "<p>El enlace vence en 48 horas. Si no creaste una cuenta, ignora este correo. 🐾</p>"
    )
    text, html_body = _with_footer(text, html_body)
    return send_email(email, "Confirma tu correo de GuauWoow", text, html_body), link


def _with_footer(text: str, html_body: str) -> tuple[str, str]:
    """Pie con quién envía el correo, por qué lo recibes y el centro legal (comunicaciones.html §6)."""
    from app.services.notify import ACCOUNT_EMAIL_REASON, email_footer, footer_html

    footer = email_footer(ACCOUNT_EMAIL_REASON)
    return (f"{text}\n\n--\n{footer}\n",
            f'{html_body}<p style="font-size:12px;line-height:1.4;color:#8a7a6a">{footer_html(footer)}</p>')


def _send_verification_safely(user_id: int, email: str, full_name: str | None) -> None:
    try:
        send_verification_email(user_id, email, full_name)
    except Exception:  # noqa: BLE001 - nunca debe romper el registro
        logger.exception("No se pudo enviar el correo de verificación al usuario %s", user_id)


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
        "email_enabled": settings.smtp_enabled,
        "shop_enabled": settings.effective_shop_enabled,
        # Donativos a refugios sin Mercado Pago vinculado: true = los cobra la cuenta de la plataforma
        "donations_fallback": settings.effective_donations_fallback,
        "support_email": settings.support_email,
        "support_whatsapp": settings.support_whatsapp,
        "environment": settings.environment,
        "sentry_dsn_frontend": settings.sentry_dsn_frontend,
        "posthog_key": settings.posthog_key,
        "posthog_host": settings.posthog_host,
        "legal_versions": {"terms": settings.legal_terms_version, "privacy": settings.legal_privacy_version},
    }


@router.post("/auth/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    email = _normalize_email(payload.email)
    if _blocked_email(email):
        raise HTTPException(status_code=400, detail=RESERVED_EMAIL)
    check_new_password(payload.password)
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
    birth_date = check_age_declaration(payload.is_adult, payload.birth_date)
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
        birth_date=birth_date,
        adult_declared_at=datetime.datetime.utcnow(),
    )
    record_terms(user)
    db.add(user)
    db.flush()
    record_signup_acceptances(db, user, request, payload.marketing_opt_in)
    db.commit()
    db.refresh(user)
    if settings.smtp_enabled or settings.is_development:
        # Se envía después de responder: el SMTP puede tardar varios segundos
        background_tasks.add_task(_send_verification_safely, user.id, user.email, user.full_name)
    return create_session_token(user)


@router.post("/auth/login", response_model=LoginResponse, response_model_exclude_none=True)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = (form_data.username or "").strip().lower()
    key = _login_key(email)
    if _login_locked(key):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=LOGIN_LOCKED)
    user = None if _blocked_email(email) else _find_user_by_email(db, email)
    if not user or not user.hashed_password or not verify_password(form_data.password, user.hashed_password):
        _register_login_failure(key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Correo o contraseña incorrectos")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tu cuenta está desactivada.")
    _clear_login_failures(key)
    # Admin con verificación en dos pasos: todavía no hay sesión, solo el comprobante para el segundo paso
    return login_or_mfa_step(user)


@router.post("/auth/logout-all")
def logout_all(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Cierra la sesión en todos los dispositivos (incluido este)."""
    revoke_sessions(current_user)
    db.commit()
    return {"ok": True}


@router.post("/auth/demo-login", response_model=Token)
def demo_login(db: Session = Depends(get_db)):
    if not settings.demo_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El acceso de demostración está desactivado.")
    user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if not user:
        user = User(
            email=DEMO_EMAIL, hashed_password=None, full_name="Usuario Demo", phone="+525512345678",
            city="Ciudad de México", country="México", latitude=19.4326, longitude=-99.1332,
            birth_date=datetime.date(1990, 1, 1), adult_declared_at=datetime.datetime.utcnow(),
        )
        record_terms(user)
        db.add(user)
        db.commit()
        db.refresh(user)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tu cuenta está desactivada.")
    if not user.terms_accepted_at or not user.age_declared:
        # El usuario demo pudo crearse antes de existir el registro de términos y de la fecha de nacimiento
        record_terms(user)
        user.birth_date = user.birth_date or datetime.date(1990, 1, 1)
        user.adult_declared_at = user.adult_declared_at or datetime.datetime.utcnow()
        db.commit()
    return create_session_token(user)


@router.post("/auth/verify-email")
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    data = decode_email_verification_token(payload.token or "")
    invalid = "El enlace de verificación no es válido o ya expiró. Pide uno nuevo desde tu perfil."
    if not data:
        raise HTTPException(status_code=400, detail=invalid)
    try:
        user = db.query(User).filter(User.id == int(data["sub"])).first()
    except (KeyError, TypeError, ValueError):
        user = None
    if not user or not user.is_active or not email_fingerprint_matches(data, user.email):
        raise HTTPException(status_code=400, detail=invalid)
    if user.email_verified:
        raise HTTPException(status_code=400, detail="Este enlace ya se usó: tu correo ya está verificado.")
    user.email_verified = True
    user.email_verified_at = datetime.datetime.utcnow()
    db.commit()
    return {"ok": True, "email_verified": True}


@router.post("/auth/resend-verification")
def resend_verification(current_user: User = Depends(get_current_user)):
    if current_user.email_verified:
        return {"ok": True, "email_verified": True}
    if not settings.smtp_enabled and not settings.is_development:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Por ahora no podemos enviar correos. Inténtalo más tarde.")
    try:
        ratelimit.check(f"verify-mail:{current_user.id}", 3, 3600)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise HTTPException(status_code=exc.status_code,
                                detail="Ya te enviamos varios correos de verificación. Espera una hora e inténtalo de nuevo.")
        raise
    sent, link = send_verification_email(current_user.id, current_user.email, current_user.full_name)
    response = {"ok": True, "email_verified": False}
    if not sent and settings.is_development:
        response["dev_link"] = link
    elif not sent:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="No pudimos enviar el correo. Inténtalo más tarde.")
    return response


@router.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    response = {"ok": True}
    email = (payload.email or "").strip().lower()
    if _blocked_email(email):
        return response
    user = _find_user_by_email(db, email)
    if not user or not user.is_active:
        return response
    try:
        # Máximo 5 correos por cuenta y hora (evita usar el formulario para llenar un buzón)
        ratelimit.check(f"forgot:{user.id}", 5, 3600)
    except HTTPException:
        return response
    token = create_password_reset_token(user.id, user.hashed_password)
    link = settings.public_url(f"/app/?reset={token}")
    text = (
        f"Hola {user.full_name}:\n\n"
        "Recibimos una solicitud para restablecer tu contraseña de GuauWoow.\n"
        f"Abre este enlace (vence en 1 hora):\n{link}\n\n"
        "Si no fuiste tú, puedes ignorar este correo. 🐾"
    )
    html_body = (
        f"<p>Hola {escape(user.full_name or '')}:</p><p>Recibimos una solicitud para restablecer tu contraseña de "
        f'GuauWoow.</p><p><a href="{escape(link, quote=True)}" style="background:#f97316;color:#fff;'
        'padding:10px 18px;border-radius:8px;text-decoration:none">Restablecer contraseña</a></p>'
        "<p>El enlace vence en 1 hora. Si no fuiste tú, ignora este correo. 🐾</p>"
    )
    text, html_body = _with_footer(text, html_body)
    sent = send_email(user.email, "Restablece tu contraseña de GuauWoow", text, html_body)
    if not sent:
        if settings.is_development:
            print(f"[forgot-password] Enlace de restablecimiento para {user.email}: {link}", flush=True)
            response["dev_link"] = link
        else:
            # Nunca se registra el enlace fuera de desarrollo: es una credencial de un solo uso
            logger.warning("No se pudo enviar el correo de restablecimiento al usuario %s; revisa la configuración SMTP.",
                           user.id)
    return response


@router.post("/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    data = decode_password_reset_token(payload.token or "")
    if not data:
        raise HTTPException(status_code=400, detail="El enlace no es válido o ya expiró. Solicita uno nuevo.")
    check_new_password(payload.password)
    user = db.query(User).filter(User.id == int(data["sub"])).first()
    if not user or not password_fingerprint_matches(data, user.hashed_password):
        raise HTTPException(status_code=400, detail="El enlace no es válido o ya se usó. Solicita uno nuevo.")
    user.hashed_password = get_password_hash(payload.password)
    revoke_sessions(user)
    if not user.email_verified:
        # Abrir el enlace que llegó al buzón demuestra que el correo es suyo
        user.email_verified = True
        user.email_verified_at = datetime.datetime.utcnow()
    db.commit()
    _clear_login_failures(_login_key(user.email))
    return {"ok": True}


# --------------------------------------------------------------------------- Google
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


def link_google_account(db: Session, userinfo: dict, flags: dict | None = None) -> User:
    """Busca, vincula o crea la cuenta del perfil de Google y hace commit.

    Si se vincula con una cuenta cuyo correo nadie había verificado, alguien pudo registrarla antes
    con el correo de la víctima (pre-account takeover): se borra esa contraseña y se cierran todas sus
    sesiones, y el correo queda verificado. Lanza oauth.OAuthError con un mensaje para el usuario.
    """
    flags = flags or {}
    email = (userinfo.get("email") or "").strip().lower()
    sub = str(userinfo.get("sub") or "") or None
    verified = userinfo.get("email_verified") in (True, "true", "True")
    if not email:
        raise oauth.OAuthError("Google no compartió tu correo.")
    if not verified:
        raise oauth.OAuthError("Tu correo de Google no está verificado.")
    if _blocked_email(email):
        raise oauth.OAuthError("Esta cuenta no está disponible.")

    now = datetime.datetime.utcnow()
    password_cleared = False
    user = db.query(User).filter(User.google_sub == sub).first() if sub else None
    if user is None:
        user = _find_user_by_email(db, email)  # vincula con la cuenta existente del mismo correo verificado
    if user is None:
        # Cuenta nueva: sin Términos, sin permisos y sin edad hasta completar POST /users/me/terms (casilla de
        # Términos y Aviso, casilla separada de 18+, fecha de nacimiento y, si quiere, correos promocionales).
        # Ahí queda la bitácora con method="registro" y la constancia del permiso (K-ACEPT, K-PREF). Las banderas
        # del `state` (accepted_terms/marketing_opt_in) ya no cuentan como aceptación.
        user = User(
            email=email, hashed_password=None, full_name=(userinfo.get("name") or email.split("@")[0])[:255],
            avatar_url=userinfo.get("picture"), google_sub=sub, email_verified=True, email_verified_at=now,
            marketing_opt_in=False,
        )
        db.add(user)
    else:
        if not user.is_active:
            raise oauth.OAuthError("Tu cuenta está desactivada.")
        if not user.email_verified and (user.email or "").lower() == email:
            if user.hashed_password:
                user.hashed_password = None
                password_cleared = True
            revoke_sessions(user)
            user.email_verified = True
            user.email_verified_at = now
        if sub and not user.google_sub:
            user.google_sub = sub
        if not user.avatar_url and userinfo.get("picture"):
            user.avatar_url = userinfo["picture"]
    db.commit()
    db.refresh(user)
    if password_cleared:
        create_notification(
            db, user_id=user.id, type="security",
            title="Vinculamos tu cuenta con Google",
            body="Por seguridad quitamos la contraseña anterior y cerramos las demás sesiones. "
                 "Si quieres entrar también con contraseña, crea una nueva en tu perfil.",
        )
        logger.info("Cuenta %s vinculada con Google: se borró una contraseña sin correo verificado.", user.id)
    return user


@router.get("/auth/google/login")
def google_login(request: Request):
    """Inicia el flujo. Las cuentas nuevas aceptan Términos, declaran su edad y dan permisos después, en la app
    (POST /users/me/terms): un parámetro en la URL no es una aceptación expresa."""
    if not oauth.is_google_configured():
        return _auth_error_redirect(request, "El inicio de sesión con Google no está disponible por ahora.")
    state, nonce = oauth.create_state({})
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

    try:
        user = link_google_account(db, userinfo, flags)
    except oauth.OAuthError as exc:
        return _auth_error_redirect(request, str(exc))

    if totp.login_needs_mfa(user):
        # Admin: el segundo paso (o el alta de la verificación en dos pasos) se hace en el panel
        step = login_or_mfa_step(user)
        enroll = "1" if step["mfa_enrollment_required"] else "0"
        resp = RedirectResponse(f"{_frontend_base(request)}/admin/#mfa={step['mfa_token']}&enroll={enroll}",
                                status_code=302)
        resp.delete_cookie(oauth.STATE_COOKIE, path="/auth/google")
        return resp
    token = create_session_token(user)
    # En el fragmento (#): no llega a los logs del servidor ni viaja en el encabezado Referer
    resp = RedirectResponse(f"{_frontend_base(request)}/app/#token={token['access_token']}", status_code=302)
    resp.delete_cookie(oauth.STATE_COOKIE, path="/auth/google")
    return resp


# --------------------------------------------------------------------------- verificación en dos pasos (admins)
# TOTP (RFC 6238) con services/totp.py. Flujo: POST /auth/login -> {mfa_required, mfa_token} -> POST /auth/mfa/verify.
# Alta: POST /auth/mfa/setup (secreto + otpauth://) -> POST /auth/mfa/enable (primer código) -> 10 códigos de
# recuperación. Todo queda en la bitácora de administración.
MFA_ATTEMPTS = 10  # intentos de código por cuenta cada 15 minutos (6 dígitos: imposible adivinarlo así)
MFA_ATTEMPTS_WINDOW = 15 * 60
MFA_INVALID = "El código no es válido o ya se usó. Revisa que la hora de tu teléfono sea correcta e inténtalo de nuevo."
MFA_EXPIRED = "El inicio de sesión venció. Vuelve a escribir tu correo y tu contraseña."
MFA_TOO_MANY = "Demasiados intentos con códigos. Espera 15 minutos e inténtalo de nuevo."
# Fallos acumulados en 24 h (bitácora de administración, sobrevive a reinicios y a varios procesos): desde el 5.º
# cada fallo duplica la espera (1 min, 2, 4... hasta 6 h) y con 30 la cuenta no acepta códigos hasta que pasen 24 h.
# Con la contraseña robada quedan menos de ~20 intentos al día (antes ~960). Al 5.º, 15.º y 30.º fallo se avisa a la
# persona y a los superadmins.
MFA_FAILED_ACTIONS = ("auth.mfa_failed", "auth.mfa_enable_failed", "auth.mfa_code_failed", "auth.mfa_rotate_failed")
MFA_BACKOFF_AFTER = 5
MFA_BACKOFF_MAX_SECONDS = 6 * 3600
MFA_DAILY_FAILURES = 30
MFA_ALERT_AT = (5, 15, 30)
MFA_LOCKED_DAY = ("Demasiados códigos incorrectos en 24 horas. Por seguridad esta cuenta no acepta códigos por ahora; "
                  "si no fuiste tú, avisa a un superadmin.")
MFA_ROTATE_REQUIRED = ("Para cambiar tu app de autenticación escribe tu contraseña y un código actual de tu app "
                       "(o uno de recuperación).")


def _mfa_audit(db: Session, user: User, action: str, request: Request | None, details: dict | None = None) -> None:
    from app.services.audit import record_admin_action

    record_admin_action(db, user, action, "user", user.id, details=details, request=request)


def _mfa_recent_failures(db: Session, user: User) -> list[datetime.datetime]:
    """Fechas de los códigos fallidos de la cuenta en las últimas 24 h (más reciente primero)."""
    from app.models import AdminAuditLog

    since = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    rows = (db.query(AdminAuditLog.created_at)
            .filter(AdminAuditLog.actor_id == user.id, AdminAuditLog.action.in_(MFA_FAILED_ACTIONS),
                    AdminAuditLog.created_at >= since)
            .order_by(AdminAuditLog.created_at.desc()).limit(MFA_DAILY_FAILURES).all())
    return [r for (r,) in rows]


def _mfa_throttle(db: Session, user: User) -> None:
    """Límite por ventana (10 cada 15 min), espera creciente desde el 5.º fallo y tope diario de 30 fallos."""
    ratelimit.check(f"mfa-try:{user.id}", MFA_ATTEMPTS, MFA_ATTEMPTS_WINDOW, detail=MFA_TOO_MANY)
    fails = _mfa_recent_failures(db, user)
    now = datetime.datetime.utcnow()
    if len(fails) >= MFA_DAILY_FAILURES:
        wait = int((fails[-1] + datetime.timedelta(hours=24) - now).total_seconds()) + 1
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=MFA_LOCKED_DAY,
                            headers={"Retry-After": str(max(wait, 1))})
    if len(fails) >= MFA_BACKOFF_AFTER:
        wait = min(60 * 2 ** (len(fails) - MFA_BACKOFF_AFTER), MFA_BACKOFF_MAX_SECONDS)
        left = wait - int((now - fails[0]).total_seconds())
        if left > 0:
            minutes = max(1, -(-left // 60))
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail=f"Demasiados códigos incorrectos. Espera {minutes} min e inténtalo de nuevo.",
                                headers={"Retry-After": str(left)})


def _mfa_alert(db: Session, user: User, failures: int) -> None:
    """Aviso (app + correo) a la persona y a los superadmins de los códigos fallidos acumulados."""
    from app.services.notify import notify_user

    title = "Códigos incorrectos de verificación en dos pasos"
    notify_user(db, user, "security", title,
                f"Hubo {failures} códigos incorrectos para entrar a tu cuenta del panel en las últimas 24 horas. Si no "
                "fuiste tú, alguien tiene tu contraseña: cámbiala y avisa a un superadmin.",
                url="/admin/", email=True, commit=False)
    bosses = db.query(User).filter(User.role == "superadmin", User.is_active.is_(True), User.id != user.id).all()
    for boss in bosses:
        notify_user(db, boss, "security", title,
                    f"La cuenta de administración {user.email} acumuló {failures} códigos incorrectos de verificación "
                    "en dos pasos en 24 horas. Revisa la bitácora y, si no fue la persona, restablece su verificación "
                    "en dos pasos y su contraseña.",
                    url="/admin/#seguridad", email=True, commit=False, data={"user_id": user.id})


def _mfa_failed(db: Session, user: User, action: str, request: Request | None, details: dict | None = None) -> None:
    """Registra el fallo (cuenta para la espera creciente) y avisa al llegar a 5, 15 y 30 en 24 h. Hace commit."""
    _mfa_audit(db, user, action, request, details)
    db.flush()
    failures = len(_mfa_recent_failures(db, user))
    if failures in MFA_ALERT_AT:
        try:
            _mfa_alert(db, user, failures)
        except Exception:  # noqa: BLE001 - el aviso nunca impide registrar el fallo
            logger.exception("No se pudo avisar de los códigos fallidos de la cuenta %s", user.id)
    db.commit()


def _mfa_user_from_token(db: Session, mfa_token: str | None, lock: bool = False) -> User:
    payload = totp.decode_mfa_token(mfa_token)
    user = None
    if payload:
        try:
            query = db.query(User).filter(User.id == int(payload["sub"]))
            user = (query.with_for_update() if lock else query).first()
        except (KeyError, TypeError, ValueError):
            user = None
    if (not user or not user.is_active or user.role not in ADMIN_ROLES
            or not totp.mfa_token_matches(payload, user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=MFA_EXPIRED)
    return user


def _mfa_session_user(db: Session, request: Request) -> User | None:
    """Admin con sesión. Si ya tiene MFA, la sesión debe venir de la verificación en dos pasos."""
    from app.auth import decode_access_token
    from app.dependencies import _user_from_token

    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    user = _user_from_token(token, db) if token else None
    if user is None:
        return None
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Necesitas permisos de administrador.")
    if not totp.session_mfa_ok(user, decode_access_token(token)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=MFA_EXPIRED)
    return user


def _mfa_actor(db: Session, request: Request, mfa_token: str | None) -> tuple[User, bool]:
    """(admin, viene_del_primer_paso). Sin sesión, el comprobante solo sirve para dar de alta la MFA."""
    if mfa_token:
        user = _mfa_user_from_token(db, mfa_token, lock=True)
        if totp.user_has_mfa(user):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Ya tienes la verificación en dos pasos. Entra con tu código para cambiarla.")
        return user, True
    user = _mfa_session_user(db, request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inicia sesión de nuevo.")
    return user, False


def _check_second_factor(db: Session, user: User, code: str) -> str | None:
    """"totp" o "recovery" si el código vale (y lo consume), None si no."""
    step = totp.matching_step(user.mfa_secret_enc, code, last_step=user.mfa_last_step)
    if step is not None:
        user.mfa_last_step = step
        return "totp"
    if totp.looks_like_recovery_code(code):
        rows = db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id,
                                                MfaRecoveryCode.used_at.is_(None)).with_for_update().all()
        for row in rows:
            if totp.recovery_code_matches(code, row.code_hash):
                row.used_at = datetime.datetime.utcnow()
                return "recovery"
    return None


def _new_recovery_codes(db: Session, user: User) -> list[str]:
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id).delete(synchronize_session=False)
    codes = totp.new_recovery_codes()
    for code in codes:
        db.add(MfaRecoveryCode(user_id=user.id, code_hash=totp.hash_recovery_code(code)))
    return codes


def _recovery_left(db: Session, user: User) -> int:
    return db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id,
                                            MfaRecoveryCode.used_at.is_(None)).count()


@router.post("/auth/mfa/verify", response_model=Token)
def mfa_verify(payload: MfaVerifyRequest, request: Request, db: Session = Depends(get_db)):
    """Segundo paso del inicio de sesión de un admin: código de la app (o de recuperación) -> sesión con "mfa"."""
    user = _mfa_user_from_token(db, payload.mfa_token, lock=True)
    _mfa_throttle(db, user)
    if not totp.user_has_mfa(user):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Primero configura la verificación en dos pasos.")
    method = _check_second_factor(db, user, payload.code)
    if not method:
        _mfa_failed(db, user, "auth.mfa_failed", request)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=MFA_INVALID)
    _mfa_audit(db, user, "auth.mfa_login", request, {"method": method})
    if method == "recovery":
        left = _recovery_left(db, user)
        create_notification(
            db, user_id=user.id, type="security", title="Usaste un código de recuperación",
            body=f"Entraste al panel con un código de recuperación. Te quedan {left}. Si no fuiste tú, cambia tu "
                 "contraseña y avisa al equipo de seguridad.", commit=False)
    db.commit()
    return create_session_token(user, mfa=True)


@router.post("/auth/mfa/setup")
def mfa_setup(payload: MfaSetupRequest, request: Request, db: Session = Depends(get_db)):
    """Genera el secreto TOTP (pendiente hasta confirmar el primer código). Devuelve {secret, otpauth_uri}.

    Si la cuenta ya tiene la verificación en dos pasos (cambio de teléfono o de app), pide la contraseña y un código
    vigente de la app o de recuperación: una sesión robada no basta para reemplazar el segundo factor."""
    user, _ = _mfa_actor(db, request, payload.mfa_token)
    rotating = totp.user_has_mfa(user)
    method = None
    if rotating:
        _mfa_throttle(db, user)
        if not payload.code:
            raise HTTPException(status_code=400, detail=MFA_ROTATE_REQUIRED)
        if user.hashed_password and not verify_password(payload.password or "", user.hashed_password):
            _mfa_failed(db, user, "auth.mfa_rotate_failed", request, {"motivo": "contraseña"})
            raise HTTPException(status_code=400, detail="Tu contraseña no es correcta.")
        method = _check_second_factor(db, user, payload.code)
        if not method:
            _mfa_failed(db, user, "auth.mfa_rotate_failed", request, {"motivo": "codigo"})
            raise HTTPException(status_code=400, detail=MFA_INVALID)
    secret = totp.b32_secret()
    user.mfa_pending_secret_enc = secret
    _mfa_audit(db, user, "auth.mfa_setup", request, {"rotation": True, "method": method} if rotating else None)
    if rotating:
        create_notification(db, user_id=user.id, type="security", title="Pediste cambiar tu app de autenticación",
                            body="Se generó un código QR nuevo para tu verificación en dos pasos. La app anterior sigue "
                                 "sirviendo hasta que confirmes la nueva. Si no fuiste tú, cambia tu contraseña y "
                                 "avisa a un superadmin.", commit=False)
    db.commit()
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, user.email),
            "issuer": settings.mfa_issuer, "account": user.email, "digits": totp.DIGITS, "period": totp.PERIOD}


@router.post("/auth/mfa/enable")
def mfa_enable(payload: MfaEnableRequest, request: Request, db: Session = Depends(get_db)):
    """Confirma el alta con el primer código. Cierra las demás sesiones y devuelve los 10 códigos de recuperación
    (solo se muestran esta vez) y una sesión nueva que ya pasó la verificación en dos pasos."""
    user, _ = _mfa_actor(db, request, payload.mfa_token)
    _mfa_throttle(db, user)
    pending = user.mfa_pending_secret_enc
    step = totp.matching_step(pending, payload.code) if pending else None
    if step is None:
        _mfa_failed(db, user, "auth.mfa_enable_failed", request)
        raise HTTPException(status_code=400, detail=MFA_INVALID if pending else "Primero genera tu código QR.")
    # Reemplazo de un segundo factor que ya existía: el secreto pendiente solo pudo generarse en /auth/mfa/setup
    # con contraseña + código vigente (ver mfa_setup)
    replacing = totp.user_has_mfa(user)
    user.mfa_secret_enc = pending
    user.mfa_pending_secret_enc = None
    user.mfa_enabled_at = datetime.datetime.utcnow()
    user.mfa_last_step = step
    codes = _new_recovery_codes(db, user)
    revoke_sessions(user)
    _mfa_audit(db, user, "auth.mfa_replaced" if replacing else "auth.mfa_enabled", request)
    if replacing:
        from app.services.notify import notify_user

        notify_user(db, user, "security", "Cambiaste tu app de autenticación",
                    "Tu verificación en dos pasos ahora usa una app nueva y tus códigos de recuperación anteriores ya no "
                    "sirven. Cerramos tus demás sesiones. Si no fuiste tú, avisa de inmediato a un superadmin.",
                    url="/admin/", email=True, commit=False)
        for boss in db.query(User).filter(User.role == "superadmin", User.is_active.is_(True),
                                          User.id != user.id).all():
            notify_user(db, boss, "security", "Cambio de verificación en dos pasos",
                        f"La cuenta de administración {user.email} reemplazó su app de autenticación y sus códigos "
                        "de recuperación.", url="/admin/#seguridad", commit=False, data={"user_id": user.id})
    else:
        create_notification(db, user_id=user.id, type="security", title="Activaste la verificación en dos pasos",
                            body="Desde ahora el panel te pedirá un código de tu app de autenticación. Guarda tus "
                                 "códigos de recuperación en un lugar seguro.", commit=False)
    db.commit()
    return {"ok": True, "recovery_codes": codes, **create_session_token(user, mfa=True)}


@router.get("/auth/mfa/status")
def mfa_status(request: Request, db: Session = Depends(get_db)):
    user = _mfa_session_user(db, request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inicia sesión de nuevo.")
    return {"enabled": totp.user_has_mfa(user), "enabled_at": user.mfa_enabled_at, "required": totp.mfa_required(),
            "recovery_codes_left": _recovery_left(db, user) if totp.user_has_mfa(user) else 0}


@router.post("/auth/mfa/recovery-codes")
def mfa_regenerate_codes(payload: MfaCodeRequest, request: Request, db: Session = Depends(get_db)):
    """Nuevos 10 códigos de recuperación (los anteriores dejan de servir). Pide un código de la app."""
    user = _mfa_session_user(db, request)
    if user is None or not totp.user_has_mfa(user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inicia sesión de nuevo.")
    _mfa_throttle(db, user)
    step = totp.matching_step(user.mfa_secret_enc, payload.code, last_step=user.mfa_last_step)
    if step is None:
        _mfa_failed(db, user, "auth.mfa_code_failed", request, {"para": "codigos_de_recuperacion"})
        raise HTTPException(status_code=400, detail=MFA_INVALID)
    user.mfa_last_step = step
    codes = _new_recovery_codes(db, user)
    _mfa_audit(db, user, "auth.mfa_recovery_regenerated", request)
    db.commit()
    return {"ok": True, "recovery_codes": codes}


@router.post("/auth/mfa/disable")
def mfa_disable(payload: MfaCodeRequest, request: Request, db: Session = Depends(get_db)):
    """Solo donde no es obligatoria (development). Pide contraseña y un código de la app."""
    user = _mfa_session_user(db, request)
    if user is None or not totp.user_has_mfa(user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inicia sesión de nuevo.")
    if totp.mfa_required():
        raise HTTPException(status_code=403, detail="La verificación en dos pasos es obligatoria para el personal "
                                                    "administrador. Para cambiar de teléfono, pide a un superadmin "
                                                    "que la restablezca.")
    _mfa_throttle(db, user)
    if user.hashed_password and not verify_password(payload.password or "", user.hashed_password):
        _mfa_failed(db, user, "auth.mfa_code_failed", request, {"para": "desactivar", "motivo": "contraseña"})
        raise HTTPException(status_code=400, detail="Tu contraseña no es correcta.")
    if totp.matching_step(user.mfa_secret_enc, payload.code, last_step=user.mfa_last_step) is None:
        _mfa_failed(db, user, "auth.mfa_code_failed", request, {"para": "desactivar"})
        raise HTTPException(status_code=400, detail=MFA_INVALID)
    user.mfa_secret_enc = None
    user.mfa_pending_secret_enc = None
    user.mfa_enabled_at = None
    user.mfa_last_step = None
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id).delete(synchronize_session=False)
    revoke_sessions(user)
    _mfa_audit(db, user, "auth.mfa_disabled", request)
    db.commit()
    return {"ok": True, **create_session_token(user)}
