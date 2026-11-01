"""Código de verificación de teléfono (OTP) propio de GuauWoow.

- 6 dígitos con `secrets`, guardado como HMAC-SHA256 (SECRET_KEY + usuario + teléfono).
- Vence en OTP_TTL_MINUTES (10), máximo OTP_MAX_ATTEMPTS (5) intentos por código.
- Reenvío con espera de OTP_RESEND_COOLDOWN_SECONDS (60).
- Límite de envíos: OTP_MAX_SENDS_PER_PHONE_HOUR (5) por teléfono y OTP_MAX_SENDS_PER_IP_HOUR (10)
  por IP. Usa Redis si está disponible; si no, cuenta en la tabla phone_verification_logs.
"""
import datetime
import logging
import secrets
import time

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import cache
from app.auth import hash_otp
from app.config import settings
from app.models import PhoneVerificationLog, User
from app.services import sms

logger = logging.getLogger(__name__)
TOO_MANY = "Demasiados intentos, espera unos minutos"
PHONE_TAKEN = "Este teléfono ya está verificado en otra cuenta"


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def phone_taken(db: Session, phone: str, exclude_user_id: int | None) -> bool:
    q = db.query(User.id).filter(User.phone == phone, User.phone_verified.is_(True), User.is_active.is_(True))
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    return db.query(q.exists()).scalar()


def _too_many(retry_after: int = 600) -> HTTPException:
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=TOO_MANY,
                         headers={"Retry-After": str(retry_after)})


def _hit_limit(db: Session, kind: str, value: str, limit: int) -> bool:
    """Registra un intento y devuelve True si se superó el límite por hora."""
    r = cache._get_redis()
    if r is not None:
        try:
            key = f"otp:{kind}:{value}:{int(time.time() // 3600)}"
            count = r.incr(key)
            if count == 1:
                r.expire(key, 3600)
            return count > limit
        except Exception:  # noqa: BLE001 - Redis caído: se usa la base de datos
            pass
    since = _now() - datetime.timedelta(hours=1)
    column = PhoneVerificationLog.phone if kind == "phone" else PhoneVerificationLog.ip
    count = db.query(PhoneVerificationLog).filter(column == value, PhoneVerificationLog.created_at >= since).count()
    return count >= limit


def send_code(db: Session, user: User, ip: str) -> dict:
    phone = user.phone
    if not phone:
        raise HTTPException(status_code=400, detail="Agrega tu número de celular primero.")
    if user.phone_verified:
        return {"sent": False, "phone": phone, "already_verified": True, "cooldown": 0}
    provider = sms.provider()
    if provider is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="La verificación por SMS no está disponible en este momento.")

    cooldown = settings.otp_resend_cooldown_seconds
    if user.phone_otp_sent_at:
        elapsed = (_now() - user.phone_otp_sent_at).total_seconds()
        if elapsed < cooldown:
            wait = int(cooldown - elapsed) + 1
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail=f"Espera {wait} segundos para pedir otro código.",
                                headers={"Retry-After": str(wait)})
    if phone_taken(db, phone, user.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PHONE_TAKEN)
    over_phone = _hit_limit(db, "phone", phone, settings.otp_max_sends_per_phone_hour)
    over_ip = _hit_limit(db, "ip", ip, settings.otp_max_sends_per_ip_hour)
    if over_phone or over_ip:
        logger.warning("Límite de SMS alcanzado (phone=%s ip=%s)", over_phone, over_ip)
        raise _too_many()

    code = generate_code()
    log = PhoneVerificationLog(user_id=user.id, phone=phone, ip=ip[:64], provider=provider, success=False)
    db.add(log)
    try:
        sms.send_otp(phone, code)
    except sms.SMSError as exc:
        db.commit()  # el intento fallido también cuenta para los límites
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    log.success = True
    user.phone_otp_hash = hash_otp(user.id, phone, code)
    user.phone_otp_expires_at = _now() + datetime.timedelta(minutes=settings.otp_ttl_minutes)
    user.phone_otp_attempts = 0
    user.phone_otp_sent_at = _now()
    db.commit()
    response = {"sent": True, "phone": phone, "cooldown": cooldown}
    if provider == "dev" and settings.is_development:
        response["dev_code"] = code
    return response


def verify_code(db: Session, user: User, code: str) -> dict:
    code = (code or "").strip()
    if not user.phone:
        raise HTTPException(status_code=400, detail="Agrega tu número de celular primero.")
    if user.phone_verified:
        return {"verified": True}
    if not user.phone_otp_hash or not user.phone_otp_expires_at or user.phone_otp_expires_at <= _now():
        raise HTTPException(status_code=400, detail="El código venció o no existe. Pide uno nuevo.")
    if (user.phone_otp_attempts or 0) >= settings.otp_max_attempts:
        raise _too_many()
    if not secrets.compare_digest(user.phone_otp_hash, hash_otp(user.id, user.phone, code)):
        user.phone_otp_attempts = (user.phone_otp_attempts or 0) + 1
        db.commit()
        remaining = settings.otp_max_attempts - user.phone_otp_attempts
        if remaining <= 0:
            raise _too_many()
        plural = "Te queda 1 intento" if remaining == 1 else f"Te quedan {remaining} intentos"
        raise HTTPException(status_code=400, detail=f"Código incorrecto. {plural}.")
    if phone_taken(db, user.phone, user.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PHONE_TAKEN)
    user.phone_verified = True
    user.phone_verified_at = _now()
    user.phone_otp_hash = None
    user.phone_otp_expires_at = None
    user.phone_otp_attempts = 0
    try:
        db.commit()
    except IntegrityError:  # carrera con otra cuenta (índice único uq_users_verified_phone)
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PHONE_TAKEN)
    return {"verified": True}
