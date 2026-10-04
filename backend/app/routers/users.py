import datetime
import logging
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_password_hash, verify_password
from app.config import settings
from app.database import get_db
from app.dependencies import client_ip, get_current_user
from app.models import (
    AdoptionApplication, BotInteraction, Conversation, Dog, Donation, FosterHome, LostReport, Match, Message,
    Notification, Order, Refuge, Reminder, User,
)
from app.routers.auth import record_terms
from app.schemas import (
    AccountDeleteRequest, PasswordChangeRequest, PhoneSendRequest, PhoneVerifyRequest, TermsAcceptRequest,
    User as UserSchema, UserUpdate,
)
from app.services import otp, sms

router = APIRouter(tags=["users"])
logger = logging.getLogger(__name__)
MIN_PASSWORD = 8
INVALID_PHONE = "El número de celular no es válido. Usa 10 dígitos, p. ej. 55 1234 5678."


def _set_phone(user: User, raw: str | None) -> None:
    """Normaliza y asigna el teléfono. Si cambia, se pierde la verificación y el código pendiente."""
    phone = None
    if raw is not None and str(raw).strip():
        phone = sms.normalize_mx_phone(raw)
        if not phone:
            raise HTTPException(status_code=400, detail=INVALID_PHONE)
    if phone != user.phone:
        user.phone = phone
        user.phone_verified = False
        user.phone_verified_at = None
        user.phone_otp_hash = None
        user.phone_otp_expires_at = None
        user.phone_otp_attempts = 0


@router.get("/users/me", response_model=UserSchema)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/users/me", response_model=UserSchema)
def update_current_user(payload: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    if "full_name" in data and not (data["full_name"] or "").strip():
        raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío.")
    if "phone" in data:
        _set_phone(current_user, data.pop("phone"))
    if "marketing_opt_in" in data:
        value = data.pop("marketing_opt_in")
        if value is not None:
            current_user.marketing_opt_in = bool(value)
    for field, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/users/me/terms", response_model=UserSchema)
def accept_terms(payload: TermsAcceptRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Registra la aceptación de Términos y Aviso de Privacidad (p. ej. cuentas creadas con Google)."""
    if payload.accepted_terms is not True:
        raise HTTPException(status_code=400, detail="Debes aceptar los Términos y Condiciones y el Aviso de Privacidad.")
    record_terms(current_user, payload.marketing_opt_in)
    db.commit()
    db.refresh(current_user)
    return current_user


# --------------------------------------------------------------------------- teléfono
@router.post("/users/me/phone/send-code")
def send_phone_code(
    request: Request,
    payload: PhoneSendRequest | None = Body(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Envía un código de 6 dígitos por SMS. Opcionalmente recibe {"phone"} para cambiar el número antes."""
    if payload is not None and payload.phone is not None:
        _set_phone(current_user, payload.phone)
        db.commit()
    return otp.send_code(db, current_user, client_ip(request))


@router.post("/users/me/phone/verify")
def verify_phone_code(payload: PhoneVerifyRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return otp.verify_code(db, current_user, payload.code)


# --------------------------------------------------------------------------- contraseña
@router.post("/users/me/password")
def change_password(payload: PasswordChangeRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not payload.new_password or len(payload.new_password) < MIN_PASSWORD:
        raise HTTPException(status_code=400, detail=f"La nueva contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
    if current_user.hashed_password:
        if not payload.current_password or not verify_password(payload.current_password, current_user.hashed_password):
            raise HTTPException(status_code=400, detail="Tu contraseña actual no es correcta.")
    # Las cuentas creadas con Google (sin contraseña) pueden definir una sin la actual
    current_user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- derechos ARCO
def _rows(items, fields: list[str]) -> list[dict]:
    return [{f: getattr(i, f, None) for f in fields} for i in items]


@router.get("/users/me/export")
def export_my_data(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Derecho de acceso y portabilidad (LFPDPPP): todos tus datos personales en JSON."""
    u = current_user
    dogs = db.query(Dog).filter(Dog.owner_id == u.id).all()
    reports = db.query(LostReport).filter(LostReport.reporter_id == u.id).all()
    matches = db.query(Match).filter(Match.user_id == u.id).all()
    apps = (db.query(AdoptionApplication).join(Match, Match.id == AdoptionApplication.match_id)
            .filter(Match.user_id == u.id).all())
    messages = db.query(Message).filter(Message.sender_id == u.id).order_by(Message.id).all()
    conversations = db.query(Conversation).filter(or_(Conversation.user_a_id == u.id, Conversation.user_b_id == u.id)).all()
    orders = db.query(Order).filter(Order.user_id == u.id).all()
    donations = db.query(Donation).filter(Donation.user_id == u.id).all()
    notifications = db.query(Notification).filter(Notification.user_id == u.id).order_by(Notification.id).all()
    refuges = db.query(Refuge).filter(Refuge.user_id == u.id).all()
    fosters = db.query(FosterHome).filter(FosterHome.user_id == u.id).all()
    reminders = db.query(Reminder).filter(Reminder.user_id == u.id).all()

    data = {
        "exported_at": datetime.datetime.utcnow(),
        "service": "PatitasFind",
        "profile": _rows([u], [
            "id", "email", "full_name", "phone", "phone_verified", "phone_verified_at", "avatar_url", "role", "city",
            "country", "latitude", "longitude", "is_active", "terms_accepted_at", "terms_version", "privacy_version",
            "marketing_opt_in", "created_at",
        ])[0] | {"has_password": u.has_password, "google_linked": bool(u.google_sub)},
        "dogs": _rows(dogs, ["id", "name", "breed", "age_years", "age_months", "size", "color", "description", "status",
                             "photos", "city", "country", "latitude", "longitude", "ai_analysis", "created_at"]),
        "lost_reports": _rows(reports, ["id", "dog_name", "report_type", "description", "photos", "city", "country",
                                        "latitude", "longitude", "status", "source", "contact_phone", "resolved_at",
                                        "ai_analysis", "created_at"]),
        "matches": _rows(matches, ["id", "dog_id", "status", "created_at"]),
        "adoption_applications": _rows(apps, ["id", "match_id", "answers", "status", "created_at"]),
        "conversations": _rows(conversations, ["id", "match_id", "lost_report_id", "created_at", "last_message_at"]),
        "messages_sent": _rows(messages, ["id", "conversation_id", "content", "created_at"]),
        "orders": [
            {**_rows([o], ["id", "total", "shipping_address", "status", "provider", "paid_at", "created_at"])[0],
             "items": _rows(o.items, ["product_id", "quantity", "unit_price"])}
            for o in orders
        ],
        "donations": _rows(donations, ["id", "refuge_id", "amount", "status", "provider", "created_at"]),
        "notifications": _rows(notifications, ["id", "type", "title", "body", "is_read", "created_at"]),
        "refuges": _rows(refuges, ["id", "name", "description", "city", "country", "status", "documents", "created_at"]),
        "foster_homes": _rows(fosters, ["id", "description", "city", "country", "capacity", "status", "created_at"]),
        "reminders": _rows(reminders, ["id", "match_id", "title", "due_date", "type", "is_completed", "created_at"]),
    }
    filename = f"patitasfind-mis-datos-{datetime.date.today().isoformat()}.json"
    return JSONResponse(
        content=jsonable_encoder(data),
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


def _delete_local_upload(url: str | None) -> None:
    """Borra /uploads/<archivo> y su miniatura. Las URLs externas (p. ej. Google) solo se olvidan."""
    if not url or not url.startswith("/uploads/"):
        return
    name = Path(url).name
    base = Path(settings.upload_dir)
    stem, _, ext = name.rpartition(".")
    for candidate in {name, f"{stem}_thumb.jpg"} if stem else {name}:
        path = (base / candidate).resolve()
        try:
            if path.parent == base.resolve() and path.is_file():
                path.unlink()
        except OSError as exc:
            logger.warning("No se pudo borrar %s: %s", path, exc)


@router.delete("/users/me")
def delete_my_account(payload: AccountDeleteRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Cancelación de cuenta (derecho de cancelación, LFPDPPP).

    - Anonimiza el perfil (correo, nombre, teléfono, foto, ubicación, contraseña) y desactiva la cuenta.
    - Despublica sus perros (status "unavailable") y resuelve sus reportes activos sin teléfono de contacto.
    - Borra sus notificaciones y conversaciones del bot de WhatsApp ligadas a su número.
    - CONSERVA pedidos y donaciones (montos, fechas, referencias de pago) ya sin datos que identifiquen
      a la persona: el Código Fiscal de la Federación (art. 30) obliga a guardar la contabilidad y su
      soporte 5 años, y sirven para aclaraciones/contracargos con Mercado Pago. La dirección de envío
      de los pedidos se elimina.
    - Los mensajes que envió se conservan para la otra persona de la conversación, firmados como
      "Usuario eliminado".
    """
    if (payload.confirm or "").strip().upper() != "ELIMINAR":
        raise HTTPException(status_code=400, detail='Escribe "ELIMINAR" para confirmar.')
    user = current_user
    if user.hashed_password and not (payload.password and verify_password(payload.password, user.hashed_password)):
        raise HTTPException(status_code=400, detail="Tu contraseña no es correcta.")
    if user.role == "superadmin":
        others = db.query(User).filter(User.role == "superadmin", User.is_active.is_(True), User.id != user.id).count()
        if not others:
            raise HTTPException(status_code=400, detail="Eres el único superadmin; asigna otro antes de eliminar tu cuenta.")

    now = datetime.datetime.utcnow()
    db.query(Dog).filter(Dog.owner_id == user.id, Dog.status != "adopted").update(
        {Dog.status: "unavailable"}, synchronize_session=False)
    for report in db.query(LostReport).filter(LostReport.reporter_id == user.id).all():
        report.contact_phone = None
        if report.status == "active":
            report.status = "resolved"
            report.resolved_at = now
    db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
    db.query(Match).filter(Match.user_id == user.id, Match.status == "pending_application").update(
        {Match.status: "rejected"}, synchronize_session=False)
    db.query(FosterHome).filter(FosterHome.user_id == user.id).update({FosterHome.status: "inactive"}, synchronize_session=False)
    db.query(Order).filter(Order.user_id == user.id).update(
        {Order.shipping_address: "[eliminada a solicitud del titular]"}, synchronize_session=False)
    if user.phone:
        digits = user.phone.lstrip("+")
        db.query(BotInteraction).filter(BotInteraction.phone.in_([digits, digits.replace("52", "521", 1), user.phone])).delete(
            synchronize_session=False)

    _delete_local_upload(user.avatar_url)
    user.email = f"eliminado-{user.id}@patitasfind.invalid"
    user.full_name = "Usuario eliminado"
    user.phone = None
    user.phone_verified = False
    user.phone_verified_at = None
    user.phone_otp_hash = None
    user.phone_otp_expires_at = None
    user.avatar_url = None
    user.latitude = None
    user.longitude = None
    user.city = None
    user.hashed_password = None
    user.google_sub = None
    user.marketing_opt_in = False
    user.is_active = False
    user.deleted_at = now
    db.commit()
    logger.info("Cuenta %s eliminada (anonimizada) a solicitud del titular.", user.id)
    return {"ok": True}
