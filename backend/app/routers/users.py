import datetime
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import hash_otp
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import PhoneVerifyRequest, User as UserSchema, UserUpdate
from app.services import sms

router = APIRouter(tags=["users"])
logger = logging.getLogger(__name__)
OTP_TTL = datetime.timedelta(minutes=10)


@router.get("/users/me", response_model=UserSchema)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/users/me", response_model=UserSchema)
def update_current_user(payload: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    if "full_name" in data and not (data["full_name"] or "").strip():
        raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío.")
    if "phone" in data and (data["phone"] or None) != current_user.phone:
        current_user.phone_verified = False
        current_user.phone_otp_hash = None
    for field, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/users/me/phone/send-code")
def send_phone_code(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user.phone:
        raise HTTPException(status_code=400, detail="Agrega tu número de teléfono en tu perfil primero.")
    if settings.otp_enabled:
        try:
            sms.send_verification(current_user.phone)
        except sms.OTPError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return {"sent": True, "channel": settings.twilio_channel}
    if not settings.is_development:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La verificación por SMS no está disponible en este momento.",
        )
    code = f"{secrets.randbelow(10000):04d}"
    current_user.phone_otp_hash = hash_otp(current_user.id, code)
    current_user.phone_otp_expires_at = datetime.datetime.utcnow() + OTP_TTL
    db.commit()
    logger.info("[otp:dev] Código para %s: %s", current_user.phone, code)
    return {"sent": True, "dev_code": code}


@router.post("/users/me/phone/verify")
def verify_phone_code(payload: PhoneVerifyRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    code = (payload.code or "").strip()
    if not current_user.phone:
        raise HTTPException(status_code=400, detail="Agrega tu número de teléfono en tu perfil primero.")
    if settings.otp_enabled:
        try:
            ok = sms.check_verification(current_user.phone, code)
        except sms.OTPError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    else:
        ok = bool(
            current_user.phone_otp_hash
            and current_user.phone_otp_expires_at
            and current_user.phone_otp_expires_at > datetime.datetime.utcnow()
            and secrets.compare_digest(current_user.phone_otp_hash, hash_otp(current_user.id, code))
        )
    if not ok:
        raise HTTPException(status_code=400, detail="Código incorrecto")
    current_user.phone_verified = True
    current_user.phone_otp_hash = None
    current_user.phone_otp_expires_at = None
    db.commit()
    return {"verified": True}
