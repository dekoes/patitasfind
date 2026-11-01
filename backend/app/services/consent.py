"""Centro de preferencias (K-PREF): permisos que se dan o se retiran, cada cambio en consent_records.

Propósitos (todos apagados al inicio; comunicaciones.html §2-§4):
  notify_nearby      alertas de perritos perdidos cerca (User.notify_nearby)
  whatsapp_alerts    avisos por WhatsApp: plantillas de utilidad (User.whatsapp_alerts)
  email_marketing    correos promocionales (User.marketing_opt_in)
  analytics_cookies  analítica de PostHog (la elección vive en el navegador; aquí queda la constancia)

text_version identifica el texto exacto que se mostró: "<versión>#<12 primeros del sha256 del texto>".
"""
import datetime
import hashlib
import logging
import re

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import BotInteraction, ConsentRecord, User

logger = logging.getLogger(__name__)

CONSENT_VERSION = "2026-10-17"
PURPOSES = ("notify_nearby", "whatsapp_alerts", "email_marketing", "analytics_cookies")
USER_FIELDS = {"notify_nearby": "notify_nearby", "whatsapp_alerts": "whatsapp_alerts",
               "email_marketing": "marketing_opt_in"}
CHANNELS = ("app", "registro", "whatsapp", "web", "solicitud", "sistema")


def consent_text(purpose: str) -> str:
    """Texto que se muestra junto a cada interruptor (y que se registra por versión)."""
    if purpose == "notify_nearby":
        return (f"Avisarme de perritos perdidos cerca de mí: te avisamos de perros reportados a menos de "
                f"{settings.nearby_alert_radius_km:g} km de tu ubicación guardada ({settings.nearby_alert_partner_radius_km:g} km "
                f"para Refugios y Casas de paso aprobados), máximo {settings.nearby_alert_daily_cap} al día, en la app y "
                "por los canales que tengas activos. Puedes apagarlas cuando quieras.")
    if purpose == "whatsapp_alerts":
        return ("Avisos por WhatsApp: posibles coincidencias con tus reportes y, si activaste las alertas cercanas, "
                "perritos perdidos cerca. Solo mensajes de utilidad, nunca publicidad. Responde BAJA para dejar de "
                "recibirlos.")
    if purpose == "email_marketing":
        return ("Correos promocionales: novedades, campañas de adopción, promociones de la Tienda Solidaria, "
                "solicitudes de donativo y encuestas. Puedes apagarlos cuando quieras.")
    if purpose == "analytics_cookies":
        return ("Analítica (PostHog): medir qué pantallas y funciones se usan para mejorar la app, sin el texto que "
                "escribes ni grabaciones de sesión. Si la rechazas, todo funciona igual.")
    raise ValueError(f"propósito desconocido: {purpose}")


def text_version(purpose: str) -> str:
    digest = hashlib.sha256(consent_text(purpose).encode("utf-8")).hexdigest()[:12]
    return f"{CONSENT_VERSION}#{digest}"


def texts() -> dict:
    return {p: {"text": consent_text(p), "version": text_version(p)} for p in PURPOSES}


def _meta(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    from app.dependencies import client_ip

    return (client_ip(request) or "")[:64] or None, (request.headers.get("user-agent") or "")[:255] or None


def record_consent(db: Session, user: User | None, purpose: str, granted: bool, channel: str,
                   request: Request | None = None, phone: str | None = None) -> ConsentRecord:
    """Agrega la constancia (no hace commit)."""
    if purpose not in PURPOSES:
        raise ValueError(f"propósito desconocido: {purpose}")
    if channel not in CHANNELS:
        raise ValueError(f"canal desconocido: {channel}")
    ip, ua = _meta(request)
    record = ConsentRecord(user_id=user.id if user is not None else None, phone=(phone or None),
                           purpose=purpose, granted=bool(granted), text_version=text_version(purpose),
                           channel=channel, ip=ip, user_agent=ua)
    db.add(record)
    return record


def _digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def bot_interactions_for(db: Session, phone: str | None) -> list[BotInteraction]:
    digits = _digits(phone)
    if len(digits) < 10:
        return []
    return db.query(BotInteraction).filter(BotInteraction.phone.like(f"%{digits[-10:]}")).all()


def sync_bot_opt_out(db: Session, phone: str | None, granted: bool) -> None:
    """Apagar los avisos de WhatsApp en la app equivale a escribir BAJA (y encenderlos, a ALTA)."""
    digits = _digits(phone)
    if len(digits) < 10:
        return
    rows = bot_interactions_for(db, phone)
    now = datetime.datetime.utcnow()
    if not rows and not granted:
        db.add(BotInteraction(phone=digits, stage="welcome", data={}, opted_out_at=now))
        return
    for row in rows:
        row.opted_out_at = None if granted else (row.opted_out_at or now)


def set_preference(db: Session, user: User, purpose: str, granted: bool, channel: str = "app",
                   request: Request | None = None, sync_bot: bool = True) -> bool:
    """Cambia un permiso de la cuenta y agrega su constancia si cambió. Devuelve True si cambió (sin commit)."""
    field = USER_FIELDS[purpose]
    granted = bool(granted)
    if bool(getattr(user, field)) == granted:
        return False
    setattr(user, field, granted)
    record_consent(db, user, purpose, granted, channel, request, phone=user.phone if purpose == "whatsapp_alerts" else None)
    if purpose == "whatsapp_alerts" and sync_bot:
        sync_bot_opt_out(db, user.phone, granted)
    if purpose == "notify_nearby" and not granted:
        # La ubicación de la cuenta solo existe para las alertas (privacidad.html §8): apagarlas la borra
        user.latitude = user.longitude = None
    return True


def preferences_out(db: Session, user: User) -> dict:
    last = latest_records(db, user.id)
    return {
        "notify_nearby": bool(user.notify_nearby),
        "whatsapp_alerts": bool(user.whatsapp_alerts),
        "email_marketing": bool(user.marketing_opt_in),
        "analytics": last["analytics_cookies"].granted if last.get("analytics_cookies") else None,
        "updated_at": {p: (r.created_at if r else None) for p, r in last.items()},
        "has_location": user.latitude is not None and user.longitude is not None,
        "phone_verified": bool(user.phone_verified),
        "whatsapp_enabled": settings.whatsapp_enabled,
        "texts": texts(),
        # Invitación a activar las alertas cercanas: cuentas que nunca han decidido (p. ej. las anteriores al
        # cambio, cuando la migración apagó notify_nearby)
        "invite_nearby": not user.notify_nearby and last.get("notify_nearby") is None,
    }


def latest_records(db: Session, user_id: int) -> dict:
    out = {p: None for p in PURPOSES}
    rows = (db.query(ConsentRecord).filter(ConsentRecord.user_id == user_id)
            .order_by(ConsentRecord.id.desc()).limit(200).all())
    for row in rows:
        if row.purpose in out and out[row.purpose] is None:
            out[row.purpose] = row
    return out


def nearby_consent_clause(user_model=User):
    """Condición SQL: la constancia más reciente de notify_nearby de la cuenta es un «sí» (además del interruptor)."""
    latest = (select(ConsentRecord.granted)
              .where(ConsentRecord.user_id == user_model.id, ConsentRecord.purpose == "notify_nearby")
              .order_by(ConsentRecord.id.desc()).limit(1).correlate(user_model).scalar_subquery())
    return latest.is_(True)


def latest_phone_consent(db: Session, phone: str | None, purpose: str = "whatsapp_alerts") -> bool | None:
    """Última constancia de ese número (por los últimos 10 dígitos): True/False, o None si nunca decidió.

    Sirve para los números del bot sin cuenta: solo se les escribe por iniciativa propia si respondieron que sí
    a la pregunta del bot o escribieron ALTA (privacidad-whatsapp.html §5)."""
    digits = _digits(phone)
    if len(digits) < 10:
        return None
    row = (db.query(ConsentRecord.granted)
           .filter(ConsentRecord.purpose == purpose, ConsentRecord.phone.like(f"%{digits[-10:]}"))
           .order_by(ConsentRecord.id.desc()).first())
    return None if row is None else bool(row[0])


def has_consent(db: Session, user_id: int, purpose: str) -> bool:
    row = (db.query(ConsentRecord.granted).filter(ConsentRecord.user_id == user_id, ConsentRecord.purpose == purpose)
           .order_by(ConsentRecord.id.desc()).first())
    return bool(row and row[0])


def consents_for_export(db: Session, user_id: int) -> list[dict]:
    rows = db.query(ConsentRecord).filter(ConsentRecord.user_id == user_id).order_by(ConsentRecord.id).all()
    return [{"purpose": r.purpose, "granted": r.granted, "text_version": r.text_version, "channel": r.channel,
             "ip": r.ip, "created_at": r.created_at} for r in rows]


# --------------------------------------------------------------------------- avisos al equipo
def notify_admins(db: Session, kind: str, title: str, body: str, url: str | None = None, data: dict | None = None,
                  email: bool = True) -> int:
    """Aviso en la app a cada admin activo y, si hay SMTP y SUPPORT_EMAIL, un correo al buzón de soporte."""
    from app.models import Notification

    admins = db.query(User).filter(User.role.in_(("admin", "superadmin")), User.is_active.is_(True)).all()
    payload = dict(data or {})
    if url:
        payload.setdefault("url", url)
    for admin in admins:
        db.add(Notification(user_id=admin.id, type=kind, title=title[:255], body=body, data=payload or None))
    db.commit()
    if email and settings.smtp_enabled and settings.support_email:
        from app.services.background import dispatch

        try:
            dispatch("app.tasks.notifications.send_notification_email", settings.support_email, title, body, url)
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo enviar al buzón de soporte el aviso %s", kind)
    return len(admins)
