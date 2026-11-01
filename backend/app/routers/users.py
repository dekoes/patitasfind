import datetime
import logging

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
    AdoptionApplication, BotInteraction, ComplianceRequest, Conversation, Dog, Donation, FosterHome, LostReport, Match,
    Message, Notification, Order, OrderInvoice, Refuge, Reminder, User, Veterinary, VeterinaryRequest, VeterinaryReview,
)
from app.routers.auth import (
    check_age_declaration, check_new_password, create_session_token, record_signup_acceptances, record_terms,
    revoke_sessions,
)
from app.schemas import (
    AccountDeleteRequest, PasswordChangeRequest, PhoneSendRequest, PhoneVerifyRequest, TermsAcceptRequest,
    User as UserSchema, UserUpdate,
)
from app.services import account_deletion, consent, legal_acceptance, otp, sms

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
def update_current_user(payload: UserUpdate, request: Request, current_user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    if "full_name" in data and not (data["full_name"] or "").strip():
        raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío.")
    if "phone" in data:
        _set_phone(current_user, data.pop("phone"))
    # Permisos: cada cambio deja su constancia en consent_records (K-PREF; también por /cumplimiento/preferencias)
    for field, purpose in (("marketing_opt_in", "email_marketing"), ("notify_nearby", "notify_nearby")):
        if field in data:
            value = data.pop(field)
            if value is not None:
                consent.set_preference(db, current_user, purpose, bool(value), channel="app", request=request)
    if not current_user.notify_nearby and ("latitude" in data or "longitude" in data):
        # Solo con las alertas cercanas encendidas guardamos tu ubicación en la cuenta (privacidad.html §8);
        # con ellas apagadas queda solo la ciudad
        data.pop("latitude", None)
        data.pop("longitude", None)
        current_user.latitude = current_user.longitude = None
    for field, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


UNDERAGE_CLOSED = "underage_account_closed"


def _declares_minor(birth: datetime.date | None) -> bool:
    """La fecha indicada es real (no futura ni anterior a 1900) y de una persona menor de 18 años."""
    from app.services.age_check import MIN_AGE, _today_mx, age_on

    if birth is None:
        return False
    today = _today_mx()
    return 1900 <= birth.year and birth <= today and age_on(birth, today) < MIN_AGE


def _close_minor_account(db: Session, user: User) -> None:
    """Completar una cuenta creada con Google con una fecha de menos de 18 años (terminos.html 5.3).

    - Cuenta recién creada (nunca aceptó Términos): solo tiene nombre, correo y foto de Google -> se anonimiza y se
      desactiva al momento (si fue un error al escribir el año, puede volver a entrar con Google y empezar de cero).
    - Cuenta con historial (anterior a la fecha de nacimiento): se desactiva y se cierran sus sesiones; el equipo
      revisa compras o donativos en curso (reembolsos) y borra sus datos.
    En ambos casos se avisa a los administradores. Siempre lanza 403 code=underage_account_closed."""
    from app.services.age_check import UNDERAGE
    from app.services.legal_acceptance import ComplianceError

    uid, had_history = user.id, user.terms_accepted_at is not None
    revoke_sessions(user)
    if had_history:
        user.is_active = False
        db.commit()
        detail = (UNDERAGE + " Cerramos esta cuenta. Nuestro equipo revisará si hay compras o donativos en curso para "
                  "reembolsarlos y borrará sus datos.")
    else:
        anonymize_account(db, user)
        detail = UNDERAGE + " Cerramos esta cuenta y borramos sus datos."
    logger.info("Cuenta %s cerrada: al completar el registro indicó una fecha de menos de 18 años.", uid)
    try:
        consent.notify_admins(
            db, "age_minor_closed", "Cuenta de una persona menor de edad cerrada",
            (f"La cuenta {uid} (creada con Google) indicó una fecha de nacimiento de menos de 18 años al completar el "
             "registro. " + ("Tenía historial: revisa pedidos y donativos en curso (reembolsos) y elimina sus datos "
                             "(terminos.html 5.3)." if had_history else "Se anonimizó y desactivó al momento.")),
            url="/admin/#cumplimiento-edad", data={"user_id": uid})
    except Exception:  # noqa: BLE001 - el aviso al equipo no impide cerrar la cuenta
        logger.exception("No se pudo avisar al equipo del cierre de la cuenta %s", uid)
    raise ComplianceError(403, detail, UNDERAGE_CLOSED)


@router.post("/users/me/terms", response_model=UserSchema)
def accept_terms(payload: TermsAcceptRequest, request: Request, current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Completa la cuenta (p. ej. creada con Google): Términos y Aviso de Privacidad y, si faltan, la casilla
    separada de 18+ y la fecha de nacimiento. Todo queda en la bitácora de aceptaciones."""
    if payload.accepted_terms is not True:
        raise HTTPException(status_code=400, detail="Debes aceptar los Términos y Condiciones y el Aviso de Privacidad.")
    exempt = current_user.is_phone_exempt  # admins y demo
    declared_now = False
    if not current_user.age_declared and not exempt:
        if _declares_minor(payload.birth_date):
            # Cuenta de Google de una persona menor de 18 (terminos.html 5.3): se cierra y se borran sus datos
            _close_minor_account(db, current_user)
        current_user.birth_date = check_age_declaration(payload.is_adult, payload.birth_date)
        current_user.adult_declared_at = datetime.datetime.utcnow()
        declared_now = True
    first_time = current_user.terms_accepted_at is None
    record_terms(current_user)
    record_signup_acceptances(db, current_user, request, payload.marketing_opt_in,
                              method="registro" if first_time else "reaceptacion", channel="app",
                              record_age=declared_now)
    if payload.marketing_opt_in is False:
        consent.set_preference(db, current_user, "email_marketing", False, channel="app", request=request)
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
    from app.services.legal_moderation import check_not_banned_phone  # teléfonos de cuentas canceladas

    check_not_banned_phone(db, current_user)
    return otp.send_code(db, current_user, client_ip(request))


@router.post("/users/me/phone/verify")
def verify_phone_code(payload: PhoneVerifyRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.legal_moderation import check_not_banned_phone  # bloqueo de nuevos registros (moderacion.html §5)

    check_not_banned_phone(db, current_user)
    return otp.verify_code(db, current_user, payload.code)


# --------------------------------------------------------------------------- contraseña
@router.post("/users/me/password")
def change_password(payload: PasswordChangeRequest, request: Request, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    from app.auth import decode_access_token

    # Un admin que entró con verificación en dos pasos conserva esa marca en la sesión nueva
    auth = request.headers.get("authorization") or ""
    session = decode_access_token(auth[7:].strip()) if auth.lower().startswith("bearer ") else None
    had_mfa = bool(session and session.get("mfa") == 1)
    check_new_password(payload.new_password, "La nueva contraseña")
    if current_user.hashed_password:
        if not payload.current_password or not verify_password(payload.current_password, current_user.hashed_password):
            raise HTTPException(status_code=400, detail="Tu contraseña actual no es correcta.")
    # Las cuentas creadas con Google (sin contraseña) pueden definir una sin la actual
    current_user.hashed_password = get_password_hash(payload.new_password)
    # Cierra las demás sesiones; este dispositivo sigue con el token nuevo de la respuesta
    revoke_sessions(current_user)
    db.commit()
    return {"ok": True, **create_session_token(current_user, mfa=had_mfa)}


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
    invoices = db.query(OrderInvoice).filter(OrderInvoice.user_id == u.id).all()
    veterinaries = db.query(Veterinary).filter(Veterinary.owner_user_id == u.id).all()
    vet_reviews = db.query(VeterinaryReview).filter(VeterinaryReview.user_id == u.id).all()
    vet_requests = db.query(VeterinaryRequest).filter(VeterinaryRequest.user_id == u.id).all()

    data = {
        "exported_at": datetime.datetime.utcnow(),
        "service": "GuauWoow",
        "profile": _rows([u], [
            "id", "email", "full_name", "phone", "phone_verified", "phone_verified_at", "avatar_url", "role", "city",
            "country", "latitude", "longitude", "is_active", "terms_accepted_at", "terms_version", "privacy_version",
            "marketing_opt_in", "notify_nearby", "whatsapp_alerts", "birth_date", "adult_declared_at",
            "age_check_status", "created_at",
        ])[0] | {"has_password": u.has_password, "google_linked": bool(u.google_sub)},
        # Bitácora de aceptaciones y de permisos (historial.html §5; comunicaciones.html §11)
        "legal_acceptances": legal_acceptance.acceptances_for_export(db, u.id),
        "consent_records": consent.consents_for_export(db, u.id),
        # Centro de solicitudes (derechos ARCO, quejas): folio, fechas y respuesta
        "compliance_requests": _rows(db.query(ComplianceRequest).filter(ComplianceRequest.user_id == u.id).all(), [
            "folio", "kind", "status", "outcome", "description", "details", "received_at", "respond_by", "responded_at",
            "response_text", "effective_at", "closed_at"]),
        "dogs": _rows(dogs, ["id", "name", "breed", "age_years", "age_months", "size", "color", "description", "status",
                             "photos", "city", "country", "latitude", "longitude", "ai_analysis", "created_at"]),
        "lost_reports": _rows(reports, ["id", "dog_name", "report_type", "description", "photos", "city", "country",
                                        "state", "latitude", "longitude", "status", "source", "contact_phone",
                                        "external_url", "resolved_at", "ai_analysis", "created_at"]),
        "matches": _rows(matches, ["id", "dog_id", "status", "created_at"]),
        "adoption_applications": _rows(apps, ["id", "match_id", "answers", "status", "created_at"]),
        "conversations": _rows(conversations, ["id", "match_id", "lost_report_id", "created_at", "last_message_at"]),
        "messages_sent": _rows(messages, ["id", "conversation_id", "content", "created_at"]),
        "orders": [
            {**_rows([o], ["id", "refuge_id", "subtotal", "shipping_total", "total", "shipping_address",
                           "shipping_name", "shipping_phone", "shipping_street", "shipping_ext_number",
                           "shipping_int_number", "shipping_neighborhood", "shipping_city", "shipping_state",
                           "shipping_postal_code", "shipping_references", "status", "provider", "carrier",
                           "tracking_number", "return_reason", "return_details", "return_photos", "paid_at",
                           "delivered_at", "created_at"])[0],
             "items": _rows(o.items, ["product_id", "quantity", "unit_price"])}
            for o in orders
        ],
        "invoice_requests": _rows(invoices, ["order_id", "status", "rfc", "legal_name", "regimen_fiscal", "postal_code",
                                             "uso_cfdi", "email", "uuid", "requested_at", "issued_at"]),
        "donations": _rows(donations, ["id", "refuge_id", "amount", "status", "provider", "created_at"]),
        "notifications": _rows(notifications, ["id", "type", "title", "body", "is_read", "created_at"]),
        "refuges": _rows(refuges, ["id", "name", "description", "city", "country", "status", "documents", "created_at"]),
        # Tienda: datos fiscales del refugio y estado de la cuenta de Mercado Pago vinculada (nunca los tokens)
        "refuge_fiscal_profiles": _rows([r.fiscal_profile for r in refuges if r.fiscal_profile], [
            "refuge_id", "person_type", "rfc", "legal_name", "regimen_fiscal", "postal_code", "is_donataria",
            "csf_document_id", "created_at", "updated_at"]),
        "refuge_payment_accounts": _rows([r.payment_account for r in refuges if r.payment_account], [
            "refuge_id", "provider", "status", "mp_user_id", "live_mode", "connected_at", "expires_at",
            "disconnected_at"]),
        "foster_homes": _rows(fosters, ["id", "description", "city", "country", "capacity", "status", "created_at"]),
        "reminders": _rows(reminders, ["id", "match_id", "title", "due_date", "type", "is_completed", "created_at"]),
        "veterinaries": _rows(veterinaries, [
            "id", "name", "description", "address", "city", "state", "postal_code", "latitude", "longitude", "phone",
            "whatsapp", "email", "website", "hours", "services", "emergency_24h", "photos", "responsible_vet_name",
            "cedula_profesional", "cedula_institution", "status", "consent_at", "consent_terms_version", "created_at"]),
        "veterinary_reviews": _rows(vet_reviews, ["id", "veterinary_id", "rating", "text", "visited_month",
                                                  "incentivized", "created_at", "updated_at"]),
        "veterinary_requests": _rows(vet_requests, ["id", "kind", "veterinary_id", "review_id", "relation", "reason",
                                                    "text", "status", "due_at", "resolution_note", "created_at"]),
    }
    filename = f"guauwoow-mis-datos-{datetime.date.today().isoformat()}.json"
    return JSONResponse(
        content=jsonable_encoder(data),
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.delete("/users/me")
def delete_my_account(payload: AccountDeleteRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Cancelación de cuenta (derecho de cancelación, LFPDPPP).

    - Anonimiza el perfil (correo, nombre, teléfono, foto, ubicación, contraseña) y desactiva la cuenta.
    - Oculta sus perros y reportes (404 en las vistas públicas) y borra del disco sus fotos y miniaturas;
      quita descripción, ubicación y teléfono de contacto. Cierra su refugio (fuera de listados, ranking
      y donaciones), desactiva sus productos y borra sus documentos privados.
    - Vacía las respuestas de sus cuestionarios de adopción y anonimiza su bitácora de SMS (teléfono e IP).
    - Borra sus notificaciones, recordatorios y conversaciones del bot de WhatsApp ligadas a su número.
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
    anonymize_account(db, user)
    return {"ok": True}


def anonymize_account(db: Session, user: User, now: datetime.datetime | None = None) -> None:
    """Hace la cancelación descrita en delete_my_account y confirma la transacción. También la usa el centro de
    solicitudes al hacer efectiva una solicitud de cancelación de cuenta (services/solicitudes.py)."""
    now = now or datetime.datetime.utcnow()
    # Refugio, perros, reportes, fotos, cuestionarios, documentos, bitácora de SMS y menciones de su nombre
    account_deletion.purge_user_content(db, user, now)
    # Pedidos: se conservan (obligación fiscal) sin datos de entrega; solo quedan ciudad y estado
    db.query(Order).filter(Order.user_id == user.id).update(
        {Order.shipping_address: "[eliminada a solicitud del titular]", Order.shipping_name: None,
         Order.shipping_phone: None, Order.shipping_street: None, Order.shipping_ext_number: None,
         Order.shipping_int_number: None, Order.shipping_neighborhood: None, Order.shipping_postal_code: None,
         Order.shipping_references: None}, synchronize_session=False)
    if user.phone:
        digits = user.phone.lstrip("+")
        db.query(BotInteraction).filter(BotInteraction.phone.in_([digits, digits.replace("52", "521", 1), user.phone])).delete(
            synchronize_session=False)

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
    user.notify_nearby = False
    user.whatsapp_alerts = False
    user.birth_date = None
    user.is_active = False
    user.deleted_at = now
    db.commit()
    logger.info("Cuenta %s eliminada (anonimizada) a solicitud del titular.", user.id)
