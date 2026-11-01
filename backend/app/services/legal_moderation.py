"""Moderación legal: motivos de reporte, prioridades, medidas con declaración de motivos, cuarentena, derechos de
autor (aviso, contra-aviso, staydown y reincidentes) y apelaciones.

Lo que prometen las páginas y dónde se cumple:
- moderacion.html §1 y proteccion-nna.html §7: catálogo REASONS (las siete categorías del Decreto NNA art. 3,
  «Involucra a una niña, niño o adolescente», maltrato, venta o cobro, estafa, contenido íntimo, mi imagen o mis
  datos, difamación, suplantación, reseña falsa, cédula falsa, condiciones sanitarias y publicidad engañosa).
- moderacion.html §2 y §4: orden de revisión (priority_for) y plazos objetivo (due_for); lo que involucra a menores
  se oculta al recibir el reporte (intake) y se avisa a los administradores.
- moderacion.html §6: cada medida se registra en ModerationAction y la persona recibe el aviso con el contenido, la
  regla, el origen de la detección, la duración y cómo apelar (record_action).
- moderacion.html §7: apelación con folio y correo aunque la cuenta esté suspendida; la resuelve una persona distinta.
- proteccion-nna.html §11 y autoridades.html §7: material de abuso sexual infantil en cuarentena (quarantine): se
  saca de /uploads, se cifra en la bóveda con retención legal, se bloquea por hash, nunca va a la IA ni se muestra en
  el panel, y queda registrada la denuncia pendiente ante el Ministerio Público (AuthorityRequest saliente).
  Si lo señala un reporte (de cualquier persona, con o sin cuenta), primero es una cuarentena PREVENTIVA
  (preventive_quarantine): se oculta y los archivos pasan a la bóveda, restaurables, sin bloqueo por hash, sin
  denuncia y sin alertas de reintento. Un superadmin la confirma (confirm_quarantine) o la descarta
  (release_pending_quarantine) con la vista protegida (quarantine_signals), que nunca muestra el material.
- derechos-de-autor.html §6 a §8: retiro, aviso a quien subió, contra-aviso, restauración del día hábil 10 al 15,
  staydown y política de reincidentes.
"""
import datetime
import hashlib
import logging
import re
import secrets
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from sqlalchemy import Text, cast, func, or_
from sqlalchemy.orm import Session

from app import cache
from app.config import settings
from app.models import (
    AuthorityRequest, ContentReport, CopyrightNotice, Dog, LostReport, ModerationAction, ModerationAppeal, Product,
    User, Veterinary,
)
from app.services import evidence, moderation, ratelimit, staydown
from app.utils.notifications import create_notification

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- catálogo de motivos
# Orden = orden en el formulario público. Las claves caben en content_reports.reason (40).
DECREE_REASONS = (
    "acoso", "abuso_sexual", "odio_violencia_masiva", "incitacion_odio_violencia", "conductas_ilicitas",
    "pornografia", "suicidio_autolesiones",
)
MINOR_REASONS = ("involucra_menor", "abuso_sexual_infantil")
CSAM_REASONS = ("abuso_sexual_infantil",)
REASONS = {
    "involucra_menor": "Involucra a una niña, niño o adolescente",
    "abuso_sexual_infantil": "Material de abuso sexual infantil",
    # Decreto de entornos digitales seguros, art. 3 fr. I a VII
    "acoso": "Acoso",
    "abuso_sexual": "Abuso, explotación o violencia sexual",
    "odio_violencia_masiva": "Discurso de odio o violencia masiva",
    "incitacion_odio_violencia": "Incitación al odio o a la violencia",
    "conductas_ilicitas": "Conductas ilícitas o apología del delito",
    "pornografia": "Pornografía",
    "suicidio_autolesiones": "Suicidio, autolesiones o trastornos alimenticios",
    "contenido_intimo": "Contenido íntimo sin consentimiento",
    "maltrato": "Maltrato animal",
    "venta_animal": "Venta o cobro por un animal",
    "fraude": "Estafa o solicitud de dinero",
    "mi_imagen": "Mi imagen o mis datos",
    "difamacion": "Difamación o acusación contra una persona",
    "suplantacion": "Suplantación",
    "resena_falsa": "Reseña falsa o pagada",
    "honor_reputacion": "Afecta mi honor o reputación",
    "datos_personales": "Datos personales",
    "cedula_falsa": "Cédula o veterinario falso",
    "condiciones_sanitarias": "Condiciones sanitarias",
    "publicidad_enganosa": "Publicidad engañosa",
    "spam": "Spam",
    "contenido_inapropiado": "Contenido inapropiado",
    "datos_falsos": "Datos falsos",
    "otro": "Otro",
}
INTERNAL_REASONS = {"retiro_autor": "Retiro solicitado por la persona autora (publicación importada)"}
# Lo que ofrece el formulario público (los mismos que el botón «Reportar»)
PUBLIC_REASONS = tuple(REASONS)
URGENT_REASONS = DECREE_REASONS + ("contenido_intimo", "venta_animal", "maltrato")
PRIORITY_2_REASONS = ("fraude", "suplantacion")
PRIORITY_LABELS = {0: "Menores", 1: "Urgente", 2: "Estafas y venta", 3: "General"}
DETECTION_LABELS = {
    "reporte": "un reporte de otra persona",
    "equipo": "una revisión de nuestro equipo",
    "filtro": "un filtro automático revisado por una persona",
    "autoridad": "una orden de autoridad",
    "aviso_derechos": "un aviso de derechos de autor",
}
ACTION_LABELS = {
    "hide_content": "Ocultamos el contenido",
    "suspend_user": "Suspendimos la cuenta",
    "cancel_account": "Cancelamos la cuenta",
    "copyright_removal": "Retiramos el contenido por un aviso de derechos de autor",
    "quarantine": "Contenido en cuarentena",
}
PREVENTIVE_HIDE_TYPES = ("dog", "lost_report", "product", "veterinary", "veterinary_review", "message")
# Un reporte de abuso sexual infantil solo pone en cuarentena contenido concreto (no una cuenta ni un refugio entero)
QUARANTINE_TYPES = PREVENTIVE_HIDE_TYPES
PENDING_QUARANTINE_KIND = "csam_preventivo"  # EvidenceRecord.kind de la cuarentena sin confirmar
APPEALABLE_ACTIONS = ("hide_content", "suspend_user", "cancel_account")
ALERT_EMAIL_DEDUPE_SECONDS = 3600  # un correo por contenido y hora (los avisos en la app sí se crean siempre)
PUBLIC_ALERT_EMAILS_PER_HOUR = 20  # tope de correos al equipo por reportes del formulario público
MODERACION_URL = "/app/legal/moderacion.html"
COPYRIGHT_URL = "/app/legal/derechos-de-autor.html"
CSAM_WITHHELD = "Material de abuso sexual infantil: avisar pondría en riesgo la investigación."
_FOLIO_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EMAIL_RE = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")
COPYRIGHT_STRIKE_WINDOW_DAYS = 365
COPYRIGHT_RESTORE_FROM_DAYS = 10  # Reglamento LFDA art. 37 Nonies: restauración entre el día hábil 10 y el 15
COPYRIGHT_RESTORE_UNTIL_DAYS = 15
COPYRIGHT_COUNTING = ("removed", "counter_notice", "litigation", "final")


def reason_label(reason: str | None) -> str:
    return REASONS.get(reason or "") or INTERNAL_REASONS.get(reason or "") or (reason or "")


def new_folio(prefix: str) -> str:
    return f"{prefix}-" + "".join(secrets.choice(_FOLIO_ALPHABET) for _ in range(8))


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _fmt(dt: datetime.datetime | None) -> str:
    from app.services import order_flow

    return order_flow._fmt_day(dt) if dt else ""


def add_business_days(start: datetime.datetime, days: int) -> datetime.datetime:
    """Fin del día hábil `days` (calendario de order_flow: lunes a viernes sin días de descanso obligatorio)."""
    from app.services import order_flow

    return order_flow._end_of_local_day_utc(order_flow.add_business_days(order_flow._local_date(start), days))


def same_day_deadline(now: datetime.datetime | None = None) -> datetime.datetime:
    """Fin del día (hora del centro), con al menos 2 horas de margen: «alerta el mismo día»."""
    from app.services import order_flow

    now = now or _now()
    return max(order_flow._end_of_local_day_utc(order_flow._local_date(now)), now + datetime.timedelta(hours=2))


def priority_for(reason: str) -> int:
    """moderacion.html §2: primero menores y violencia sexual; luego riesgo para personas y animales; luego estafas
    y venta; al final, lo demás."""
    if reason in MINOR_REASONS:
        return 0
    if reason in URGENT_REASONS:
        return 1
    if reason in PRIORITY_2_REASONS:
        return 2
    return 3


def due_for(reason: str, now: datetime.datetime | None = None) -> datetime.datetime:
    now = now or _now()
    priority = priority_for(reason)
    if priority == 0:
        return now + datetime.timedelta(hours=min(settings.moderation_urgent_hours, settings.moderation_minor_response_hours))
    if priority == 1:
        return now + datetime.timedelta(hours=settings.moderation_urgent_hours)
    return add_business_days(now, settings.moderation_review_business_days)


# --------------------------------------------------------------------------- avisos
def send_email(to: str | None, title: str, body: str, url: str | None = None) -> None:
    """Correo directo (personas sin cuenta o con la cuenta suspendida). Nunca rompe el flujo."""
    if not to or not settings.smtp_enabled or to.lower().endswith(".invalid"):
        return
    try:
        from app.services.background import dispatch

        dispatch("app.tasks.notifications.send_notification_email", to, title, body, url)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo despachar un correo de moderación")


def notify_person(db: Session, user: User | None, kind: str, title: str, body: str, url: str | None = None,
                  data: dict | None = None) -> None:
    """Aviso en la app y por correo; si la cuenta está suspendida el correo sale directo (notify_user no lo manda)."""
    from app.services.notify import notify_user

    if user is None or user.deleted_at is not None:
        return
    if user.is_active:
        notify_user(db, user, kind, title=title, body=body, url=url, email=True, data=data, commit=False)
        return
    create_notification(db, user_id=user.id, type=kind, title=title, body=body, data=data, commit=False)
    send_email(user.email, title, body, url)


def _alert_email_allowed(dedupe_key: str | None, public: bool) -> bool:
    """Correo a los admins: uno por clave (contenido) y hora; los que llegan del formulario público comparten además
    un tope por hora, para que nadie sin cuenta pueda llenar de correos al equipo."""
    if dedupe_key and not cache.add(f"lm:alerta:{dedupe_key}", ALERT_EMAIL_DEDUPE_SECONDS):
        return False
    if public and not ratelimit.hit("lm:alertas-publico:correo", PUBLIC_ALERT_EMAILS_PER_HOUR, 3600):
        return False
    return True


def alert_admins(db: Session, title: str, body: str, data: dict | None = None, kind: str = "moderation_alert",
                 dedupe_key: str | None = None, public: bool = False) -> int:
    """Aviso a los administradores (siempre en la app; por correo según _alert_email_allowed)."""
    from app.services.notify import notify_user

    with_email = _alert_email_allowed(dedupe_key, public)
    admins = db.query(User).filter(User.role.in_(moderation.ADMIN_ROLES), User.is_active == True).all()  # noqa: E712
    for admin in admins:
        notify_user(db, admin, kind, title=title, body=body, url="/admin/", email=with_email, data=data, commit=False)
    return len(admins)


def _is_public(report: ContentReport | None) -> bool:
    return report is not None and (report.source == "publico" or report.reporter_id is None)


# --------------------------------------------------------------------------- objetivo de un reporte público
_QUERY_TYPES = {"dog": "dog", "report": "lost_report", "vet": "veterinary", "product": "product", "refuge": "refuge",
                "user": "user"}
FACEBOOK_HOSTS = ("facebook.com", "fb.com", "fb.watch")


def upload_stem(url: str | None) -> str | None:
    """Los 32 caracteres hexadecimales del nombre que generamos al subir una foto (images.GENERATED_NAME), sin
    «_thumb». None si el enlace no es una foto nuestra con nombre generado (no se adivina por fragmentos)."""
    from app.services import images

    path = (url or "").strip().split("?", 1)[0].split("#", 1)[0]
    if "/uploads/" not in path:
        return None
    match = images.GENERATED_NAME.fullmatch(path.rsplit("/", 1)[-1].lower())
    return match.group(1) if match else None


def photo_matches(photo: str | None, stem: str | None) -> bool:
    """True si la foto guardada es exactamente la del nombre generado `stem` (original o miniatura)."""
    return bool(stem) and isinstance(photo, str) and upload_stem(photo) == stem


def resolve_url(db: Session, url: str | None) -> tuple[str, int] | None:
    """(target_type, target_id) de un enlace de GuauWoow (/app/?dog=1, una foto /uploads/...) o de una
    publicación importada de Facebook. None si no lo reconocemos."""
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw if "://" in raw or raw.startswith("/") else f"https://{raw}")
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in FACEBOOK_HOSTS):
        from app.services import facebook_monitor

        report = facebook_monitor.find_by_post_url(db, raw)
        return ("lost_report", report.id) if report else None
    query = parse_qs(parsed.query)
    for key, target_type in _QUERY_TYPES.items():
        values = query.get(key) or []
        if values and values[0].isdigit():
            target_id = int(values[0])
            return (target_type, target_id) if moderation.load_target(db, target_type, target_id) else None
    stem = upload_stem(parsed.path or "")
    if stem:
        # Nombre generado completo (32 hex) y coincidencia exacta con un elemento de las fotos: un fragmento como
        # «/uploads/a.jpg» ya no apunta a cualquier publicación
        like = f"%/uploads/{stem}.%"
        for target_type, model in (("dog", Dog), ("lost_report", LostReport), ("product", Product),
                                   ("veterinary", Veterinary)):
            for row_id, photos in (db.query(model.id, model.photos).filter(cast(model.photos, Text).like(like))
                                   .order_by(model.id).limit(20).all()):
                if any(photo_matches(p, stem) for p in (photos or [])):
                    return target_type, row_id
        for row_id, avatar in db.query(User.id, User.avatar_url).filter(User.avatar_url.like(like)).limit(20).all():
            if photo_matches(avatar, stem):
                return "user", row_id
    return None


# --------------------------------------------------------------------------- llegada de un reporte
def _preventive_hide(db: Session, report: ContentReport, target) -> dict | None:
    if report.target_type not in PREVENTIVE_HIDE_TYPES or target is None:
        return None
    if report.target_type == "message":
        if target.content == moderation.HIDDEN_MESSAGE:
            return None
    elif target.is_hidden:
        return None
    return moderation.hide(db, report.target_type, target)


def intake(db: Session, report: ContentReport, target, now: datetime.datetime | None = None) -> dict:
    """Prioridad, plazo y medidas inmediatas de un reporte recién creado (in-app o público). Sin commit.

    - Material de abuso sexual infantil sobre un contenido concreto: cuarentena PREVENTIVA (preventive_quarantine);
      la confirma o la descarta un superadmin. Sobre una cuenta o un refugio entero se trata como «involucra a un
      menor» (prioridad 0 y alerta), sin cuarentena.
    - Involucra a una niña, niño o adolescente: se oculta al momento, se guarda la evidencia y se avisa a los
      administradores; quien publicó recibe un aviso de que está en revisión.
    - Urgentes (siete categorías del Decreto, contenido íntimo, venta, maltrato): aviso inmediato a los admins.
    Los correos al equipo se agrupan por contenido y los del formulario público tienen un tope por hora.
    """
    now = now or _now()
    report.priority = priority_for(report.reason)
    report.due_at = due_for(report.reason, now)
    out = {"priority": report.priority, "auto_hidden": False, "quarantined": False}
    label = moderation.TARGET_LABELS.get(report.target_type, report.target_type)
    public = _is_public(report)
    dedupe = f"{report.target_type}:{report.target_id}" if report.target_type != "sin_identificar" else None
    if report.reason in CSAM_REASONS and target is not None and report.target_type in QUARANTINE_TYPES:
        report.due_at = min(report.due_at, same_day_deadline(now))  # se confirma o se descarta el mismo día
        if _pending_report(db, report.target_type, report.target_id, exclude_id=report.id) is not None:
            out["quarantine_pending"] = True  # ya está en cuarentena preventiva por otro reporte
            return out
        out |= preventive_quarantine(db, report, target, now=now)
        report.auto_hidden = True
        out["auto_hidden"] = True
        return out
    if report.reason in MINOR_REASONS and target is not None:
        details = _preventive_hide(db, report, target)
        owner_id = moderation.owner_id(db, report.target_type, target)
        if details is not None:
            report.auto_hidden = True
            out["auto_hidden"] = True
            record = evidence.capture(
                db, kind="ocultamiento_preventivo", target_type=report.target_type, target_id=report.target_id,
                obj=target, owner_user_id=owner_id, reason=report.reason, report=report,
                decision={"action": "preventive_hide", "details": details, "at": now.isoformat()},
            )
            out["evidence_id"] = record.id
            owner = db.query(User).filter(User.id == owner_id).first() if owner_id else None
            if owner and report.target_type != "message":
                title = moderation.summary(db, report.target_type, target).get("title") or ""
                notify_person(
                    db, owner, "content_hidden", "Ocultamos una publicación mientras la revisamos",
                    (f"«{title}» ({label}) dejó de mostrarse mientras la revisamos, porque recibimos un reporte "
                     "relacionado con la protección de niñas, niños y adolescentes. Te avisaremos el resultado."),
                    data={"target_type": report.target_type, "target_id": report.target_id},
                )
        if out["auto_hidden"] or not _other_open(db, report, max_priority=0):  # una alerta por contenido
            alert_admins(
                db, "Reporte sobre una persona menor de edad",
                (f"{label} #{report.target_id}: {reason_label(report.reason)}. "
                 + ("Ya está oculto. " if out["auto_hidden"] else "Revisa la cuenta con prioridad. ")
                 + f"Revísalo antes del {_fmt(report.due_at)} en Moderación legal."),
                data={"content_report_id": report.id, "target_type": report.target_type, "target_id": report.target_id},
                dedupe_key=f"menor:{dedupe}", public=public,
            )
        return out
    if report.reason in MINOR_REASONS:
        # Sin objetivo identificado: igual va primero en la cola (un correo por hora para todos los de este tipo)
        alert_admins(db, "Reporte sobre una persona menor de edad",
                     "Llegó un reporte sin enlace reconocible que involucra a una persona menor. Revísalo con prioridad.",
                     data={"content_report_id": report.id}, dedupe_key="menor:sin_identificar", public=public)
    elif report.priority == 1 and not _other_open(db, report, max_priority=1):
        # Uno por contenido (los siguientes reportes del mismo contenido ya están en la cola)
        alert_admins(db, "Reporte urgente",
                     f"{label} #{report.target_id}: {reason_label(report.reason)}. Plazo objetivo: {_fmt(report.due_at)}.",
                     data={"content_report_id": report.id, "target_type": report.target_type,
                           "target_id": report.target_id}, kind="moderation_urgent",
                     dedupe_key=f"urgente:{dedupe}" if dedupe else "urgente:sin_identificar", public=public)
    return out


def _pending_report(db: Session, target_type: str, target_id: int, exclude_id: int | None = None):
    """Reporte abierto que dejó el contenido en cuarentena preventiva (sin confirmar), o None."""
    query = db.query(ContentReport).filter(
        ContentReport.target_type == target_type, ContentReport.target_id == target_id,
        ContentReport.status == "open", ContentReport.reason.in_(CSAM_REASONS),
        ContentReport.auto_hidden == True,  # noqa: E712
    )
    if exclude_id is not None:
        query = query.filter(ContentReport.id != exclude_id)
    return query.order_by(ContentReport.id).first()


def is_pending_quarantine(db: Session, report: ContentReport) -> bool:
    """El reporte (o uno anterior sobre el mismo contenido) tiene el contenido en cuarentena preventiva."""
    if report.status != "open" or report.reason not in CSAM_REASONS or report.target_type not in QUARANTINE_TYPES:
        return False
    return _pending_report(db, report.target_type, report.target_id) is not None


def _other_open(db: Session, report: ContentReport, max_priority: int = 3) -> bool:
    if report.target_type == "sin_identificar":
        return False
    return db.query(ContentReport.id).filter(
        ContentReport.target_type == report.target_type, ContentReport.target_id == report.target_id,
        ContentReport.status == "open", ContentReport.id != report.id, ContentReport.priority <= max_priority,
    ).first() is not None


def undo_preventive_hide(db: Session, report: ContentReport, exclude_ids: tuple = ()) -> bool:
    """Al descartar un reporte que ocultó el contenido al llegar: lo vuelve a mostrar si nada más lo mantiene oculto.
    La cuarentena preventiva se descarta con release_pending_quarantine (que llama aquí al final)."""
    if not report.auto_hidden or (report.reason in CSAM_REASONS and not exclude_ids):
        return False
    target = moderation.load_target(db, report.target_type, report.target_id)
    if target is None:
        return False
    others = db.query(ContentReport.id).filter(
        ContentReport.target_type == report.target_type, ContentReport.target_id == report.target_id,
        ContentReport.status == "open", ContentReport.auto_hidden == True, ContentReport.id != report.id,  # noqa: E712
        ContentReport.id.notin_(exclude_ids or (0,)),
    ).first()
    active = db.query(ModerationAction.id).filter(
        ModerationAction.target_type == report.target_type, ModerationAction.target_id == report.target_id,
        ModerationAction.status == "active", ModerationAction.action.in_(("hide_content", "copyright_removal", "quarantine")),
    ).first()
    if others or active:
        return False
    if report.target_type == "message":
        original = _original_message(db, report)
        if original is None:
            return False
        target.content = original
    else:
        target.is_hidden = False
    return True


def _original_message(db: Session, report: ContentReport, record=None) -> str | None:
    from app.models import EvidenceRecord

    record = record or (db.query(EvidenceRecord).filter(EvidenceRecord.content_report_id == report.id,
                                                        EvidenceRecord.target_type == "message")
                        .order_by(EvidenceRecord.id).first())
    if record is None:
        return None
    try:
        data = evidence.read_bundle(record)
    except evidence.EvidenceError:
        return None
    decision = (data.get("decision") or {}).get("details") or {}
    return decision.get("original_content") or ((data.get("target") or {}).get("data") or {}).get("content")


# --------------------------------------------------------------------------- medidas con declaración de motivos
def _notice_body(action: ModerationAction, title: str, label: str, strikes: int | None = None, repeat: int = 0) -> str:
    what = {
        "hide_content": f"«{title}» ({label}) dejó de mostrarse.",
        "copyright_removal": f"«{title}» ({label}) se retiró por un aviso de derechos de autor.",
        "suspend_user": "Tu cuenta quedó suspendida" + (
            f" por {action.duration_days} días, hasta el {_fmt(action.ends_at)}." if action.duration_days else
            " mientras dure la medida."),
        # Bloqueo real: el correo, el teléfono y la cuenta de Google se quedan en el perfil cancelado hasta 24 meses
        # (retention.expire_sanction_fingerprints; privacidad.html §21 «Cuentas sancionadas»)
        "cancel_account": ("Tu cuenta quedó cancelada de forma definitiva y no podrás volver a registrarte con el mismo "
                           "correo, teléfono o cuenta de Google."),
    }.get(action.action, "Aplicamos una medida a tu contenido.")
    lines = [
        what,
        f"Regla aplicada: {action.rule_text}.",
        f"Cómo lo detectamos: {DETECTION_LABELS.get(action.detection, action.detection)}.",
    ]
    if action.detection == "autoridad" and action.notes:
        lines.append(f"Datos de la orden: {action.notes}")  # LGAMVLV art. 20 Sexies
    elif action.detection == "filtro" and action.notes:
        lines.append(f"Motivo: {action.notes}")  # lo que explicó quien revisó la retención automática
        lines.append("Si la corriges, vuelve a revisión.")
    if strikes is not None:
        lines.append(f"Avisos de derechos de autor procedentes en los últimos 12 meses: {strikes}.")
    elif repeat:
        lines.append(f"Es la medida número {repeat + 1} por esta regla: si se repite, la siguiente será más fuerte.")
    if action.action == "copyright_removal":
        lines.append(
            f"Si tenías derecho a publicarlo, presenta un contra-aviso con el folio {action.folio} en "
            f"{COPYRIGHT_URL}#formularios. Somos neutrales: si quien avisó no acredita haber iniciado un procedimiento, "
            "restauramos el contenido entre 10 y 15 días hábiles después de tu contra-aviso.")
    elif action.appeal_until:
        lines.append(
            f"Puedes apelar hasta el {_fmt(action.appeal_until)} con el folio {action.folio} y el correo de tu cuenta "
            f"en {MODERACION_URL}?apelacion={action.folio}#apelacion, aunque tu cuenta esté suspendida. La revisa una "
            "persona distinta de quien decidió. Esto no sustituye tu derecho de acudir a la PROFECO o a los tribunales.")
    return "\n".join(lines)


def record_action(
    db: Session,
    *,
    user: User | None,
    target_type: str,
    target_id: int | None,
    action: str,
    rule: str,
    detection: str,
    actor: User | None,
    title: str = "",
    report: ContentReport | None = None,
    notice: CopyrightNotice | None = None,
    evidence_record=None,
    duration_days: int | None = None,
    notes: str | None = None,
    details: dict | None = None,
    withhold_reason: str | None = None,
    strikes: int | None = None,
) -> ModerationAction:
    """Registra la medida y manda la declaración de motivos (salvo que avisar ponga en riesgo una investigación)."""
    now = _now()
    rule_text = (f"Lineamientos de la comunidad: {reason_label(rule)}" if rule in REASONS or rule in INTERNAL_REASONS
                 else rule)
    repeat = db.query(func.count(ModerationAction.id)).filter(
        ModerationAction.user_id == user.id, ModerationAction.rule == rule[:60], ModerationAction.status != "revoked",
    ).scalar() if user is not None else 0
    item = ModerationAction(
        folio=new_folio("MOD"), user_id=user.id if user else None, target_type=target_type, target_id=target_id,
        action=action, rule=rule[:60], rule_text=rule_text[:300], detection=detection, duration_days=duration_days,
        ends_at=now + datetime.timedelta(days=duration_days) if duration_days else None,
        content_report_id=report.id if report else None, copyright_notice_id=notice.id if notice else None,
        evidence_id=evidence_record.id if evidence_record is not None else None,
        decided_by_id=actor.id if actor else None, notes=notes, details=details,
        appeal_until=now + datetime.timedelta(days=settings.appeal_window_days) if action in APPEALABLE_ACTIONS else None,
        notice_withheld_reason=withhold_reason, created_at=now,
    )
    db.add(item)
    db.flush()
    if user is not None and not withhold_reason:
        label = moderation.TARGET_LABELS.get(target_type, target_type)
        kind = "content_hidden" if action in ("hide_content", "copyright_removal") else "moderation_notice"
        notify_person(
            db, user, kind, ACTION_LABELS.get(action, "Medida de moderación"),
            _notice_body(item, title, label, strikes, repeat or 0),
            url=(f"{COPYRIGHT_URL}#formularios" if action == "copyright_removal"
                 else f"{MODERACION_URL}?apelacion={item.folio}#apelacion"),
            data={"moderation_action": item.folio, "target_type": target_type, "target_id": target_id,
                  **({"copyright_notice": notice.folio} if notice and action == "copyright_removal" else {})},
        )
        item.notice_sent_at = now
    return item


def suspend_account(db: Session, user: User, *, rule: str, detection: str, actor: User | None,
                    report: ContentReport | None = None, notice: CopyrightNotice | None = None,
                    duration_days: int | None = None, cancel: bool = False, notes: str | None = None,
                    strikes: int | None = None) -> ModerationAction:
    """Suspende (o cancela) la cuenta, guarda la evidencia de la cuenta y manda el aviso por correo."""
    details = moderation.suspend(db, user)
    if cancel:
        # La cancelación reemplaza a las suspensiones vigentes: hereda lo que ocultaron (para revertir si se apela)
        for prev in db.query(ModerationAction).filter(
                ModerationAction.user_id == user.id, ModerationAction.action == "suspend_user",
                ModerationAction.status == "active").all():
            for key, ids in (prev.details or {}).items():
                if isinstance(ids, list):
                    details[key] = sorted(set(details.get(key) or []) | set(ids))
            prev.status = "lifted"
            prev.revoked_at = _now()
    record = evidence.capture(
        db, kind="cuenta_suspendida", target_type="user", target_id=user.id, obj=user, owner_user_id=user.id,
        reason=rule, report=report, copyright_notice_id=notice.id if notice else None,
        decision={"action": "cancel_account" if cancel else "suspend_user", "details": details,
                  "duration_days": duration_days, "actor_id": actor.id if actor else None},
        include_photos=False, actor_id=actor.id if actor else None,
    )
    return record_action(
        db, user=user, target_type="user", target_id=user.id, action="cancel_account" if cancel else "suspend_user",
        rule=rule, detection=detection, actor=actor, title=user.full_name, report=report, notice=notice,
        evidence_record=record, duration_days=None if cancel else duration_days, notes=notes, details=details,
        strikes=strikes,
    )


def reactivate_account(db: Session, user: User, details: dict | None) -> dict:
    """Revierte una suspensión (apelación procedente o fin del plazo). Lanza HTTPException 409 si el teléfono ya
    lo verificó otra cuenta activa."""
    if user.phone and user.phone_verified:
        taken = db.query(User.id).filter(User.phone == user.phone, User.phone_verified == True,  # noqa: E712
                                         User.is_active == True, User.id != user.id).first()  # noqa: E712
        if taken:
            raise HTTPException(status_code=409, detail="Otra cuenta activa ya verificó el teléfono de este usuario.")
    restored = moderation.restore_hidden(db, details)
    user.is_active = True
    user.suspended_at = None
    return restored


def check_not_banned_phone(db: Session, user: User) -> None:
    """Bloqueo de nuevos registros (moderacion.html §5): un teléfono de una cuenta cancelada no se puede volver a
    verificar en otra cuenta."""
    if not user.phone:
        return
    banned = (
        db.query(ModerationAction.id).join(User, User.id == ModerationAction.user_id)
        .filter(ModerationAction.action == "cancel_account", ModerationAction.status == "active",
                User.phone == user.phone, User.id != user.id).first()
    )
    if banned:
        raise HTTPException(status_code=403, detail=(
            "Este teléfono pertenece a una cuenta cancelada por incumplir las reglas de la comunidad. "
            "Si crees que es un error, escríbenos."))


# --------------------------------------------------------------------------- cuarentena (abuso sexual infantil)
def quarantine(db: Session, report: ContentReport | None, target, actor: User | None, target_type: str | None = None,
               target_id: int | None = None) -> dict:
    """Aísla el contenido: fotos fuera de /uploads (cifradas en la bóveda con retención legal), bloqueo por hash,
    contenido oculto, denuncia pendiente ante el Ministerio Público y alerta a los administradores. Sin commit.

    Nunca se manda a la IA (staydown + vision) y el panel solo muestra metadatos.
    """
    target_type = target_type or report.target_type
    target_id = target_id if target_id is not None else report.target_id
    now = _now()
    urls = evidence.target_photo_urls(target_type, target)
    files = evidence.local_files(urls)
    owner_id = moderation.owner_id(db, target_type, target)
    hidden = None
    if target_type in PREVENTIVE_HIDE_TYPES:
        if target_type == "message" or not target.is_hidden:
            hidden = moderation.hide(db, target_type, target)
    record = evidence.capture(
        db, kind="csam", target_type=target_type, target_id=target_id, obj=target, owner_user_id=owner_id,
        reason="abuso_sexual_infantil", report=report, files=files, is_csam=True,
        decision={"action": "quarantine", "photo_urls": urls, "hidden": hidden, "at": now.isoformat(),
                  "actor_id": actor.id if actor else None},
        actor_id=actor.id if actor else None,
    )
    _remove_upload_files(urls)
    return _finalize_quarantine(db, report, target, target_type, target_id, record, files, urls, owner_id, actor, now)


def _remove_upload_files(urls: list[str]) -> None:
    """Fuera de /uploads: ni Nginx ni el backend lo pueden servir (también la miniatura). La copia queda cifrada en la
    bóveda (evidence.capture), de donde se restaura si la cuarentena se descarta."""
    from app.services import images

    for url in urls:
        path = images.local_path_for(url)
        for candidate in ([path, path.with_name(f"{path.stem}_thumb.jpg")] if path else []):
            try:
                candidate.unlink(missing_ok=True)
            except OSError as exc:
                logger.error("No se pudo retirar un archivo en cuarentena (%s): %s", candidate.name, exc)


def _restore_upload_files(bundle: dict) -> list[str]:
    """Vuelve a escribir en /uploads las fotos de un paquete de la bóveda (solo nombres de archivo seguros) y
    regenera sus miniaturas."""
    from app.services import images

    restored = []
    folder = images.upload_dir()
    for name, data in evidence.bundle_files(bundle):
        filename = name.split("?", 1)[0].rsplit("/", 1)[-1]
        if not images.GENERATED_NAME.fullmatch(filename) and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}\.(jpg|jpeg|png|webp)", filename):
            continue
        path = folder / filename
        path.write_bytes(data)
        try:
            images.ensure_thumbnail(path)
        except Exception as exc:  # noqa: BLE001 - sin miniatura se sirve la foto original
            logger.warning("No se pudo regenerar la miniatura de %s: %s", filename, exc)
        restored.append(name)
    return restored


# --------------------------------------------------------------------------- cuarentena preventiva (sin confirmar)
PENDING_HOLD_REASON = ("Cuarentena preventiva: un reporte señaló posible material de abuso sexual infantil; "
                       "pendiente de que un superadmin la confirme o la descarte.")


def preventive_quarantine(db: Session, report: ContentReport, target, now: datetime.datetime | None = None) -> dict:
    """Lo que un REPORTE señala como material de abuso sexual infantil (de cualquier persona, con o sin cuenta). Sin
    commit.

    Se oculta el contenido y sus archivos salen de /uploads hacia la bóveda (cifrados, con retención legal y
    restaurables): nadie los puede ver ni se mandan a la IA. Pero un reporte no basta para tratar una imagen como
    material de abuso: NO se bloquea por hash, no se quita la foto de la ficha, no se registra denuncia ni se avisa de
    reintentos. Un superadmin la confirma (confirm_quarantine) o la descarta (release_pending_quarantine) con la vista
    protegida (quarantine_signals), que nunca muestra el material.
    """
    now = now or _now()
    target_type, target_id = report.target_type, report.target_id
    urls = evidence.target_photo_urls(target_type, target)
    files = evidence.local_files(urls)
    owner_id = moderation.owner_id(db, target_type, target)
    hidden = _preventive_hide(db, report, target)
    record = evidence.capture(
        db, kind=PENDING_QUARANTINE_KIND, target_type=target_type, target_id=target_id, obj=target,
        owner_user_id=owner_id, reason="abuso_sexual_infantil", report=report, files=files, is_csam=True,
        legal_hold_reason=PENDING_HOLD_REASON,
        decision={"action": "preventive_quarantine", "details": hidden, "photo_urls": urls, "at": now.isoformat(),
                  "reporter": "cuenta" if report.reporter_id else "sin_cuenta", "source": report.source},
    )
    _remove_upload_files(urls)
    label = moderation.TARGET_LABELS.get(target_type, target_type)
    alert_admins(
        db, "Posible material de abuso sexual infantil: cuarentena preventiva",
        (f"{label} #{target_id}: un reporte lo señaló como material de abuso sexual infantil. Lo ocultamos y sus "
         f"{len(files)} archivo(s) pasaron a la bóveda, sin bloqueo por hash ni denuncia. Un superadmin debe "
         f"confirmarla o descartarla antes del {_fmt(report.due_at)} con la vista protegida de Moderación legal "
         "(nunca muestra el material). No descargues ni reproduzcas los archivos."),
        data={"content_report_id": report.id, "evidence_id": record.id, "target_type": target_type,
              "target_id": target_id},
        dedupe_key=f"csam:{target_type}:{target_id}", public=_is_public(report),
    )
    return {"quarantine_pending": True, "evidence_id": record.id, "files": len(files)}


def pending_quarantine_record(db: Session, target_type: str, target_id: int):
    """Evidencia de la cuarentena preventiva vigente de ese contenido (o None)."""
    from app.models import EvidenceRecord

    report = _pending_report(db, target_type, target_id)
    if report is None:
        return None, None
    record = (db.query(EvidenceRecord).filter(
        EvidenceRecord.kind == PENDING_QUARANTINE_KIND, EvidenceRecord.target_type == target_type,
        EvidenceRecord.target_id == target_id, EvidenceRecord.purged_at.is_(None))
        .order_by(EvidenceRecord.id.desc()).first())
    return report, record


def _open_csam_reports(db: Session, target_type: str, target_id: int) -> list[ContentReport]:
    return db.query(ContentReport).filter(
        ContentReport.target_type == target_type, ContentReport.target_id == target_id,
        ContentReport.status == "open", ContentReport.reason.in_(CSAM_REASONS),
    ).order_by(ContentReport.id).all()


def _require_superadmin(actor: User | None) -> None:
    if actor is None or actor.role != "superadmin":
        raise HTTPException(status_code=403, detail=(
            "Solo un superadmin confirma o descarta una cuarentena preventiva, con la vista protegida."))


def quarantine_signals(db: Session, report: ContentReport) -> dict:
    """Vista protegida para decidir una cuarentena preventiva SIN ver el material: metadatos de los archivos
    (formato, tamaño, dimensiones, SHA-256), si coinciden con material ya confirmado, el análisis de la IA hecho
    ANTES del reporte, los reportes recibidos y el historial de la cuenta. Nunca devuelve bytes ni miniaturas."""
    from app.services import images

    target = moderation.load_target(db, report.target_type, report.target_id)
    pending, record = pending_quarantine_record(db, report.target_type, report.target_id)
    files = []
    if record is not None:
        try:
            bundle = evidence.read_bundle(record)
        except evidence.EvidenceError:
            bundle = {}
        for name, data in evidence.bundle_files(bundle):
            meta = {"nombre": name.rsplit("/", 1)[-1], "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            try:
                with images.open_image(data) as img:
                    meta |= {"formato": img.format, "ancho": img.width, "alto": img.height}
            except Exception:  # noqa: BLE001 - ilegible: solo el tamaño
                meta["formato"] = None
            hashes = staydown.hashes_for_bytes(data)
            hit = staydown.match_hashes(*hashes, kinds=("csam",)) if hashes else None
            meta["coincide_con_material_confirmado"] = bool(hit)
            files.append(meta)
    reports = _open_csam_reports(db, report.target_type, report.target_id)
    reporter_ids = {r.reporter_id for r in reports if r.reporter_id}
    verified = db.query(func.count(User.id)).filter(User.id.in_(reporter_ids or {0}),
                                                   User.phone_verified == True).scalar() or 0  # noqa: E712
    owner_id = moderation.owner_id(db, report.target_type, target) if target is not None else None
    owner = db.query(User).filter(User.id == owner_id).first() if owner_id else None
    ai = getattr(target, "ai_analysis", None) if target is not None else None
    ai_summary = None
    if isinstance(ai, dict):
        ai_summary = {k: ai.get(k) for k in ("is_dog", "breed", "breeds", "color", "colors", "size", "description",
                                             "labels", "confidence") if k in ai}
    return {
        "reporte": {"id": report.id, "folio": report.folio, "recibido_en": report.created_at,
                    "plazo": report.due_at, "detalles": report.details},
        "reportes_abiertos": len(reports),
        "reportantes": {"sin_cuenta": sum(1 for r in reports if not r.reporter_id),
                        "con_cuenta": len(reporter_ids), "con_telefono_verificado": verified,
                        "ips_distintas": len({r.reporter_ip for r in reports if r.reporter_ip})},
        "contenido": {"tipo": report.target_type, "id": report.target_id, "existe": target is not None,
                      "creado_en": getattr(target, "created_at", None) if target is not None else None,
                      "texto": (moderation.summary(db, report.target_type, target).get("title")
                                if target is not None else None),
                      "analisis_ia_previo": ai_summary},
        "archivos": files,
        "cuenta": {"id": owner.id, "creada_en": owner.created_at, "telefono_verificado": bool(owner.phone_verified),
                   "rol": owner.role,
                   "medidas_previas": db.query(func.count(ModerationAction.id)).filter(
                       ModerationAction.user_id == owner.id, ModerationAction.status != "revoked").scalar() or 0,
                   "cuarentenas_confirmadas": db.query(func.count(ModerationAction.id)).filter(
                       ModerationAction.user_id == owner.id, ModerationAction.action == "quarantine",
                       ModerationAction.status == "active").scalar() or 0} if owner else None,
        "cuarentena_preventiva": record is not None and pending is not None,
        "evidencia_id": record.id if record is not None else None,
    }


def confirm_quarantine(db: Session, report: ContentReport, actor: User) -> dict:
    """Un superadmin confirma la cuarentena preventiva: ahora sí bloqueo por hash, foto fuera de la ficha, denuncia
    pendiente ante el Ministerio Público y alerta de reintentos. Resuelve los reportes abiertos de ese contenido.
    Sin commit."""
    _require_superadmin(actor)
    pending, record = pending_quarantine_record(db, report.target_type, report.target_id)
    if pending is None or record is None:
        raise HTTPException(status_code=409, detail="Ese contenido no está en cuarentena preventiva.")
    try:
        bundle = evidence.read_bundle(record)
    except evidence.EvidenceError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    files = evidence.bundle_files(bundle)
    urls = (bundle.get("decision") or {}).get("photo_urls") or [name for name, _ in files]
    target = moderation.load_target(db, report.target_type, report.target_id)
    owner_id = record.owner_user_id
    now = _now()
    evidence.set_legal_hold(db, record, True, evidence.CSAM_HOLD_REASON, actor.id)
    out = _finalize_quarantine(db, pending, target, report.target_type, report.target_id, record, files, urls,
                               owner_id, actor, now)
    resolved = _open_csam_reports(db, report.target_type, report.target_id)
    for r in resolved:
        r.status, r.action, r.resolved_by, r.resolved_at = "resolved", "quarantine", actor.id, now
        r.admin_notes = r.admin_notes or "Cuarentena confirmada por un superadmin."
    return out | {"resolved_reports": [r.id for r in resolved]}


def release_pending_quarantine(db: Session, report: ContentReport, actor: User, reason: str) -> dict:
    """Un superadmin descarta la cuarentena preventiva (reporte falso): vuelve a escribir los archivos, libera la
    retención de la copia (queda el plazo normal de 90 días hábiles), descarta los reportes abiertos de ese contenido y
    vuelve a mostrarlo si nada más lo mantiene oculto. Sin commit."""
    _require_superadmin(actor)
    pending, record = pending_quarantine_record(db, report.target_type, report.target_id)
    if pending is None:
        raise HTTPException(status_code=409, detail="Ese contenido no está en cuarentena preventiva.")
    restored = []
    if record is not None:
        try:
            restored = _restore_upload_files(evidence.read_bundle(record))
        except evidence.EvidenceError as exc:
            raise HTTPException(status_code=410, detail=str(exc))
        evidence.set_legal_hold(db, record, False, f"Cuarentena preventiva descartada: {reason}"[:300], actor.id)
    reports = _open_csam_reports(db, report.target_type, report.target_id)
    ids = tuple(r.id for r in reports)
    unhidden = undo_preventive_hide(db, pending, exclude_ids=ids or (0,))
    now = _now()
    for r in reports:
        r.status, r.action, r.resolved_by, r.resolved_at = "dismissed", None, actor.id, now
        r.admin_notes = f"Cuarentena preventiva descartada: {reason}"[:2000]
    return {"restored_files": len(restored), "unhidden": unhidden, "dismissed": list(ids)}


def _finalize_quarantine(db: Session, report: ContentReport | None, target, target_type: str, target_id: int,
                         record, files: list[tuple[str, bytes]], urls: list[str], owner_id: int | None,
                         actor: User | None, now: datetime.datetime) -> dict:
    """Pasos de la cuarentena confirmada: bloqueo por hash, foto fuera de la ficha, denuncia pendiente ante el
    Ministerio Público, medida sin aviso a quien publicó y alerta a los administradores. Sin commit."""
    blocked = 0
    for url, data in files:
        if staydown.block_bytes(db, data, "csam", source_url=url, evidence_id=record.id,
                                actor_id=actor.id if actor else None) is not None:
            blocked += 1
    if target is None:
        pass  # el contenido ya no existe: quedan el bloqueo, la evidencia y la denuncia
    elif target_type == "user":
        target.avatar_url = None
    elif urls and hasattr(target, "photos"):
        target.photos = []
    if target is not None and target_type in ("dog", "lost_report"):
        target.photo_signature = None  # la firma visual derivaba de las fotos retiradas
        if hasattr(target, "ai_analysis"):
            target.ai_analysis = None
    alert = AuthorityRequest(
        folio=new_folio("AUT"), direction="saliente", kind="denuncia", authority_name="Ministerio Público",
        authority_type="ministerio_publico", legal_basis="Decreto NNA art. 5 fr. III; CNPP art. 222",
        requested_data="Denuncia por material de abuso sexual infantil y entrega de la evidencia según instrucciones.",
        targets=[{"type": target_type, "id": target_id}] + ([{"type": "user", "id": owner_id}] if owner_id else []),
        involves_minor=True, received_at=now, first_response_due_at=same_day_deadline(now),
        status="pendiente_denuncia", evidence_ids=[record.id], content_report_id=report.id if report else None,
        created_by_id=actor.id if actor else None,
    )
    db.add(alert)
    db.flush()
    owner = db.query(User).filter(User.id == owner_id).first() if owner_id else None
    action = record_action(
        db, user=owner, target_type=target_type, target_id=target_id, action="quarantine",
        rule="abuso_sexual_infantil", detection="reporte" if report and report.source != "equipo" else "equipo",
        actor=actor, report=report, evidence_record=record, details={"photo_urls": urls},
        withhold_reason=CSAM_WITHHELD,
    )
    alert_admins(
        db, "Material de abuso sexual infantil en cuarentena",
        (f"{moderation.TARGET_LABELS.get(target_type, target_type)} #{target_id} quedó en cuarentena: se retiraron "
         f"{len(files)} archivo(s), se bloquearon por hash y se registró la denuncia pendiente {alert.folio}. Presenta "
         "la denuncia ante el Ministerio Público hoy y anota su folio. No descargues ni reproduzcas el material."),
        data={"evidence_id": record.id, "authority_request": alert.folio, "content_report_id": getattr(report, "id", None)},
    )
    return {"quarantined": True, "evidence_id": record.id, "blocked_hashes": blocked, "authority_request": alert.folio,
            "moderation_action": action.folio, "files": len(files)}


def release_quarantine(db: Session, record, actor: User, reason: str) -> dict:
    """Libera una cuarentena equivocada (reporte falso): vuelve a escribir las fotos, quita el bloqueo por hash y deja
    el contenido OCULTO para que la moderación normal decida. La evidencia conserva su retención legal hasta que se
    libere aparte. Sin commit."""
    bundle = evidence.read_bundle(record)
    restored = _restore_upload_files(bundle)
    target = moderation.load_target(db, record.target_type, record.target_id)
    if target is not None:
        if record.target_type == "user" and restored:
            target.avatar_url = restored[0]
        elif hasattr(target, "photos") and restored:
            target.photos = restored
        if record.target_type == "message":
            original = ((bundle.get("decision") or {}).get("hidden") or {}).get("original_content")
            if original:
                target.content = original
    staydown.deactivate(db, evidence_id=record.id)
    db.query(ModerationAction).filter(ModerationAction.evidence_id == record.id, ModerationAction.action == "quarantine",
                                      ModerationAction.status == "active").update(
        {"status": "revoked", "revoked_at": _now(), "notes": f"Cuarentena liberada: {reason}"[:2000]},
        synchronize_session=False)
    return {"restored_files": len(restored), "target_hidden": True}


# --------------------------------------------------------------------------- derechos de autor
def copyright_strikes(db: Session, user_id: int, now: datetime.datetime | None = None,
                      window_days: int | None = COPYRIGHT_STRIKE_WINDOW_DAYS) -> int:
    """Avisos procedentes en los últimos 12 meses (window_days=None: desde siempre). Un aviso deja de contar si
    prospera el contra-aviso (queda «restored»)."""
    now = now or _now()
    query = db.query(func.count(CopyrightNotice.id)).filter(
        CopyrightNotice.uploader_user_id == user_id, CopyrightNotice.status.in_(COPYRIGHT_COUNTING),
        CopyrightNotice.removed_at.isnot(None))
    if window_days is not None:
        query = query.filter(CopyrightNotice.removed_at >= now - datetime.timedelta(days=window_days))
    return query.scalar() or 0


def enforce_repeat_infringer(db: Session, user: User, notice: CopyrightNotice, actor: User | None,
                             strikes: int) -> str | None:
    """derechos-de-autor.html §8: dos avisos procedentes en 12 meses suspenden 30 días; tres avisos procedentes
    (sin plazo) cancelan la cuenta y bloquean nuevos registros."""
    if user.role in moderation.ADMIN_ROLES or user.deleted_at is not None:
        return None
    cancelled = db.query(ModerationAction.id).filter(
        ModerationAction.user_id == user.id, ModerationAction.action == "cancel_account",
        ModerationAction.status == "active").first()
    if cancelled:
        return None
    # La cancelación aplica aunque la cuenta ya esté suspendida (la suspensión temporal ya no la reactiva)
    if copyright_strikes(db, user.id, window_days=None) >= settings.copyright_strikes_cancel:
        suspend_account(db, user, rule="Política de reincidentes de derechos de autor (cancelación)",
                        detection="aviso_derechos", actor=actor, notice=notice, cancel=True, strikes=strikes)
        return "cancel_account"
    if strikes >= settings.copyright_strikes_suspend and user.is_active:
        suspend_account(db, user, rule="Política de reincidentes de derechos de autor (suspensión)",
                        detection="aviso_derechos", actor=actor, notice=notice,
                        duration_days=settings.copyright_suspension_days, strikes=strikes)
        return "suspend_user"
    return None


def restore_copyright(db: Session, notice: CopyrightNotice, reason: str) -> bool:
    """Restaura lo retirado por un aviso (contra-aviso sin procedimiento acreditado). Sin commit."""
    target = (moderation.load_target(db, notice.target_type, notice.target_id)
              if notice.target_type and notice.target_id else None)
    others = db.query(ModerationAction.id).filter(
        ModerationAction.target_type == notice.target_type, ModerationAction.target_id == notice.target_id,
        ModerationAction.status == "active",
        or_(ModerationAction.copyright_notice_id.is_(None), ModerationAction.copyright_notice_id != notice.id),
        ModerationAction.action.in_(("hide_content", "copyright_removal", "quarantine")),
    ).first() if target is not None else None
    if target is not None and not others and hasattr(target, "is_hidden"):
        target.is_hidden = False
    staydown.deactivate(db, notice_id=notice.id)
    now = _now()
    db.query(ModerationAction).filter(ModerationAction.copyright_notice_id == notice.id,
                                      ModerationAction.action == "copyright_removal",
                                      ModerationAction.status == "active").update(
        {"status": "revoked", "revoked_at": now}, synchronize_session=False)
    notice.status = "restored"
    notice.restored_at = now
    notice.admin_notes = ((notice.admin_notes or "") + f"\n{reason}").strip()[:4000]
    return target is not None


# --------------------------------------------------------------------------- apelaciones
def undo_action(db: Session, action: ModerationAction) -> dict:
    """Revierte una medida cuando prospera la apelación. Sin commit."""
    out = {}
    if action.action == "hide_content":
        target = moderation.load_target(db, action.target_type, action.target_id) if action.target_id else None
        if target is not None:
            if action.target_type == "message":
                original = (action.details or {}).get("original_content")
                if original:
                    target.content = original
            elif action.target_type == "refuge":
                previous = (action.details or {}).get("refuge_status_from") or "approved"
                target.status = "approved" if previous == "suspended" else previous
                out = moderation.restore_hidden(db, action.details)
            elif hasattr(target, "is_hidden"):
                target.is_hidden = False
                if getattr(target, "review_hold", None) == "rechazado":
                    target.review_hold = "liberado"  # rechazo de una retención automática que se revocó al apelar
    elif action.action in ("suspend_user", "cancel_account"):
        user = db.query(User).filter(User.id == action.user_id).first() if action.user_id else None
        if user is not None and not user.is_active and user.deleted_at is None:
            out = reactivate_account(db, user, action.details)
    action.status = "revoked"
    action.revoked_at = _now()
    return out


def lift_expired_suspensions(db: Session, now: datetime.datetime | None = None) -> int:
    """Reactiva las cuentas cuya suspensión temporal terminó (si no tienen otra medida vigente). Con commit."""
    now = now or _now()
    due = db.query(ModerationAction).filter(
        ModerationAction.action == "suspend_user", ModerationAction.status == "active",
        ModerationAction.ends_at.isnot(None), ModerationAction.ends_at <= now,
    ).all()
    lifted = 0
    for action in due:
        other = db.query(ModerationAction.id).filter(
            ModerationAction.user_id == action.user_id, ModerationAction.status == "active",
            ModerationAction.id != action.id, ModerationAction.action.in_(("suspend_user", "cancel_account")),
            (ModerationAction.ends_at.is_(None)) | (ModerationAction.ends_at > now),
        ).first()
        action.status = "lifted"
        if other:
            continue
        user = db.query(User).filter(User.id == action.user_id).first()
        if user is not None and not user.is_active and user.deleted_at is None:
            try:
                reactivate_account(db, user, action.details)
            except HTTPException:
                logger.warning("No se pudo reactivar la cuenta %s al terminar su suspensión.", user.id)
                continue
            notify_person(db, user, "moderation_notice", "Terminó la suspensión de tu cuenta",
                          "Ya puedes volver a entrar a GuauWoow. Revisa los Lineamientos de la comunidad.",
                          url="/app/")
            lifted += 1
    db.commit()
    return lifted


def appeal_due(now: datetime.datetime | None = None) -> datetime.datetime:
    return add_business_days(now or _now(), settings.appeal_resolution_business_days)


def pending_appeal(db: Session, action_id: int) -> ModerationAppeal | None:
    return db.query(ModerationAppeal).filter(ModerationAppeal.action_id == action_id,
                                             ModerationAppeal.status == "pending").first()
