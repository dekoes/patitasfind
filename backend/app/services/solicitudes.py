"""Centro de solicitudes (contrato K-SOLIC): derechos ARCO, revocación y limitación del consentimiento, dudas y
quejas, y retiro de publicaciones importadas, con o sin cuenta.

Páginas que lo prometen (app/legal/plantillas): derechos-arco.html, eliminacion-datos.html, atencion-y-quejas.html y
contenido-importado.html. Cada solicitud recibe un folio PF-AAAA-NNNNN y un acuse con la fecha límite.

Estados: recibida -> en_revision -> respondida -> efectiva | cerrada.
Plazos (días hábiles de services/order_flow.add_business_days: sin sábados, domingos ni días de descanso
obligatorio; cada plazo vence al final del día en la Ciudad de México):
- ARCO, revocación y limitación: respuesta en 20 días hábiles desde que se recibe y, si procede, se hace efectiva
  en los 15 siguientes (LFPDPPP art. 31). Cada plazo se puede ampliar una sola vez por un periodo igual.
  Acceso a la información usada para publicidad: el menor entre 20 días hábiles y 30 naturales (LFPC art. 16).
  Si falta información se pide una sola vez dentro de los 5 días hábiles siguientes; la persona tiene 10 días
  hábiles para contestar y el plazo de respuesta vuelve a contar desde que la recibimos.
- Dudas, aclaraciones y quejas: primera respuesta y respuesta final según COMPLAINT_FIRST_RESPONSE_BUSINESS_DAYS y
  COMPLAINT_RESPONSE_BUSINESS_DAYS; un producto defectuoso se resuelve en 15 días naturales como máximo (LFPC art. 93).
- Retiro de una publicación importada: se oculta al recibir la solicitud y su texto y fotos se borran antes de
  72 h (IMPORTED_REMOVAL_PURGE_HOURS) si el equipo no lo descarta. Si quien escribe solo aparece en ella, la
  respuesta formal sigue el plazo ARCO.

Identidad: con la sesión iniciada y el correo verificado basta la cuenta; sin cuenta se confirma con un enlace al
correo (o desde el mismo número de WhatsApp, si llega por el bot). Solo si hace falta se pide una identificación,
que se guarda como documento privado y se borra al comprobar la identidad, al resolver la solicitud o a los 30
días, lo que pase primero; queda solo la constancia (fecha, método y huella SHA-256).

Efectos al hacerla efectiva: acceso -> enlace de descarga del mismo archivo de «Descargar mis datos»;
cancelación de la cuenta -> la misma anonimización de «Eliminar mi cuenta» (routers/users.anonymize_account);
revocación / limitación -> apaga los permisos elegidos y, con «publicidad», entra al listado de exclusión;
retiro_importado -> borra el texto y las fotos (services/facebook_groups.purge_report_content).

create_solicitud(db, ...) es la entrada para otros módulos (p. ej. el bot de WhatsApp con canal "whatsapp").
"""
import datetime
import hashlib
import logging
import re
import secrets
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import BotInteraction, ComplianceRequest, ComplianceRequestEvent, ContentReport, LostReport, Order, User
from app.services.order_flow import add_business_days, is_business_day

logger = logging.getLogger(__name__)

MX_TZ = ZoneInfo("America/Mexico_City")
FOLIO_SCOPE = "PF"
FOLIO_RE = re.compile(r"^PF-\d{4}-\d{5,}$")
EMAIL_RE = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']{2,}$")
REPORT_URL_RE = re.compile(r"[?&#]report=(\d{1,10})\b")

KINDS = ("acceso", "rectificacion", "cancelacion", "oposicion", "revocacion", "limitacion", "queja", "aclaracion",
         "retiro_importado")
ARCO_KINDS = ("acceso", "rectificacion", "cancelacion", "oposicion", "revocacion", "limitacion")
ATTENTION_KINDS = ("queja", "aclaracion")
KIND_LABELS = {
    "acceso": "Acceso", "rectificacion": "Rectificación", "cancelacion": "Cancelación", "oposicion": "Oposición",
    "revocacion": "Revocación del consentimiento", "limitacion": "Limitación del uso o divulgación",
    "queja": "Queja", "aclaracion": "Duda o aclaración", "retiro_importado": "Retiro de una publicación importada",
}
STATUS_LABELS = {"recibida": "Recibida", "en_revision": "En revisión", "respondida": "Respondida",
                 "efectiva": "Hecha efectiva", "cerrada": "Cerrada"}
OPEN_STATUSES = ("recibida", "en_revision")
FINAL_STATUSES = ("efectiva", "cerrada")
OUTCOMES = {"procede": "Procede", "procede_parcial": "Procede en parte", "no_procede": "No procede",
            "sin_datos": "No encontramos datos tuyos"}
POSITIVE_OUTCOMES = ("procede", "procede_parcial")
DENIAL_REASONS = {  # LFPDPPP arts. 25 y 33
    "identidad_no_acreditada": "No se acreditó la identidad o la representación",
    "sin_datos": "No tenemos los datos que pides",
    "derechos_de_terceros": "Se afectarían derechos de otra persona",
    "impedimento_legal": "Una ley o una autoridad competente lo impide",
    "ya_realizada": "La corrección, la cancelación o la oposición ya se había hecho",
    "obligacion_legal": "Debemos conservar esos datos por ley, por un contrato vigente o por un procedimiento",
    "informacion_incompleta": "No recibimos la información que te pedimos",
    "otro": "Otro motivo",
}
PERMISSIONS = {
    "alertas": "Alertas de perritos perdidos cerca", "correos": "Correos promocionales y de novedades",
    "whatsapp": "Avisos por WhatsApp", "analitica": "Analítica (cookies)", "publicidad": "Publicidad por cualquier medio",
    "otro": "Otro permiso",
}
CANCEL_SCOPES = {"cuenta": "Toda mi cuenta", "datos": "Datos específicos", "whatsapp": "Mis datos del bot de WhatsApp",
                 "importado": "Una publicación importada"}
COMPLAINT_TOPICS = {"servicio": "El servicio de GuauWoow", "compra": "Una compra en la tienda",
                    "producto_defectuoso": "Un producto que llegó con defecto o no corresponde",
                    "donativo": "Un donativo", "refugio": "Un Refugio o una Casa de paso", "otro": "Otro tema"}
REMOVAL_RELATIONS = {"autor": "Soy la persona autora", "aparezco": "Aparezco en la publicación", "otro": "Otro"}
# contenido-importado.html §8: se oculta al recibirla si la pide la persona autora o quien aparece; «otro» solo entra a
# la cola. El borrado automático (menos de 72 h) es solo para la persona autora que confirmó su correo (o si el
# equipo ya lo aprobó): sin eso, cualquiera podría borrar una alerta ajena
IMPORTED_HIDE_RELATIONS = ("autor", "aparezco")
WHATSAPP_UNPROVEN = (
    "No está comprobado que el número de WhatsApp sea de la persona titular (confirmar el correo no lo prueba). "
    "Pídele que escriba ELIMINAR (o BAJA) al bot desde ese número, o que lo pida con una cuenta que tenga ese "
    "teléfono verificado. Lo demás de la solicitud sí se puede hacer efectivo.")
EVENT_LABELS = {
    "creada": "Recibimos tu solicitud", "confirmada": "Confirmaste tu correo",
    "identidad_verificada": "Comprobamos tu identidad", "en_revision": "La estamos revisando",
    "primera_respuesta": "Te dimos una primera respuesta", "requerimiento": "Te pedimos más información",
    "info_recibida": "Recibimos la información que te pedimos", "identificacion_recibida": "Recibimos tu identificación",
    "ampliacion": "Ampliamos el plazo una sola vez", "respondida": "Te respondimos", "efectiva": "La hicimos efectiva",
    "cerrada": "La cerramos", "respuesta_titular": "Nos escribiste", "oculta": "Ocultamos la publicación",
    "retirada": "Borramos el texto y las fotos de la publicación", "restaurada": "La publicación volvió a mostrarse",
    "descarga": "Descargaste tus datos", "nota": "Nota interna",
}
INTERNAL_EVENTS = ("nota",)

ARCO_RESPONSE_DAYS = 20  # LFPDPPP art. 31
ARCO_EFFECTIVE_DAYS = 15  # LFPDPPP art. 31
INFO_REQUEST_WINDOW_DAYS = 5  # Reglamento de la LFPDPPP art. 96: se pide una sola vez en 5 días hábiles
INFO_REPLY_DAYS = 10  # la persona tiene 10 días hábiles para contestar
CONFIRM_DAYS = 10  # días hábiles para confirmar el correo antes de cerrar la solicitud
ADVERTISING_ACCESS_DAYS = 30  # LFPC art. 16: 30 días naturales
DEFECT_CLAIM_DAYS = 15  # LFPC art. 93: 15 días naturales
IMPORTED_AUTHOR_HOURS = 72  # contenido-importado.html: «la retiramos en menos de 72 horas»
DOWNLOAD_LINK_DAYS = 15
SECOND_REVIEW_DAYS = 30  # vigencia del enlace para pedir la segunda revisión de una queja  # vigencia del enlace de descarga de «Mis datos»
ID_DOCUMENT_MAX_DAYS = 30  # una identificación nunca se guarda más de 30 días
IP_TRIM_DAYS = 30  # IP y navegador de quien presenta la solicitud (conservacion.html, R37)
RECORD_RETENTION_YEARS = 5  # eliminacion-datos.html: el expediente (folio, fechas y respuesta) se conserva 5 años
DUE_SOON_BUSINESS_DAYS = 2  # semáforo amarillo
ADMIN_ROLES = ("admin", "superadmin")

PAGE_FOR_KIND = {k: "/app/legal/derechos-arco.html" for k in ARCO_KINDS}
PAGE_FOR_KIND.update({"queja": "/app/legal/atencion-y-quejas.html", "aclaracion": "/app/legal/atencion-y-quejas.html",
                      "retiro_importado": "/app/legal/contenido-importado.html"})
_MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre")


class SolicitudError(Exception):
    """Error con mensaje en español para la persona (el router lo convierte en HTTPException)."""

    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


# --------------------------------------------------------------------------- utilidades de fechas
def utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _local_date(utc_naive: datetime.datetime) -> datetime.date:
    return utc_naive.replace(tzinfo=datetime.timezone.utc).astimezone(MX_TZ).date()


def _end_of_day_utc(day: datetime.date) -> datetime.datetime:
    end = datetime.datetime.combine(day, datetime.time(23, 59, 59), tzinfo=MX_TZ)
    return end.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def business_deadline(start: datetime.datetime, days: int) -> datetime.datetime:
    """Fin del día (Ciudad de México) del día hábil número `days` después de `start` (UTC sin zona)."""
    return _end_of_day_utc(add_business_days(_local_date(start), days))


def calendar_deadline(start: datetime.datetime, days: int) -> datetime.datetime:
    return _end_of_day_utc(_local_date(start) + datetime.timedelta(days=days))


def business_days_left(now: datetime.datetime, deadline: datetime.datetime) -> int:
    """Días hábiles que quedan entre hoy y la fecha límite (0 = vence hoy; negativo = vencida)."""
    today, last = _local_date(now), _local_date(deadline)
    if last < today:
        return -sum(1 for i in range(1, (today - last).days + 1) if is_business_day(last + datetime.timedelta(days=i)))
    return sum(1 for i in range(1, (last - today).days + 1) if is_business_day(today + datetime.timedelta(days=i)))


def fecha_es(value: datetime.datetime | None) -> str:
    if value is None:
        return ""
    local = value.replace(tzinfo=datetime.timezone.utc).astimezone(MX_TZ)
    return f"{local.day} de {_MONTHS[local.month - 1]} de {local.year}"


def fecha_hora_es(value: datetime.datetime | None) -> str:
    if value is None:
        return ""
    local = value.replace(tzinfo=datetime.timezone.utc).astimezone(MX_TZ)
    return f"{fecha_es(value)}, {local:%H:%M} h (hora del centro de México)"


# --------------------------------------------------------------------------- folios y enlaces
def next_folio(db: Session, scope: str = FOLIO_SCOPE, now: datetime.datetime | None = None) -> str:
    """Siguiente folio del año (hora del centro). Un solo INSERT ... ON CONFLICT ... RETURNING: atómico."""
    year = _local_date(now or utcnow()).year
    value = db.execute(sql_text(
        "INSERT INTO folio_counters (scope, year, last_value) VALUES (:scope, :year, 1) "
        "ON CONFLICT (scope, year) DO UPDATE SET last_value = folio_counters.last_value + 1 RETURNING last_value"
    ), {"scope": scope, "year": year}).scalar()
    return f"{scope}-{year}-{int(value):05d}"


def normalize_folio(value: str | None) -> str | None:
    folio = (value or "").strip().upper().replace(" ", "")
    return folio if FOLIO_RE.match(folio) else None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _hash(token)


def page_url(req: ComplianceRequest, **params) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items() if v)
    anchor = "#seguimiento" if req.kind in ATTENTION_KINDS else ("#retiro" if req.kind == "retiro_importado" else "#solicitud")
    return f"{PAGE_FOR_KIND[req.kind]}?{query}{anchor}" if query else f"{PAGE_FOR_KIND[req.kind]}{anchor}"


def normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def valid_email(value: str | None) -> bool:
    email = normalize_email(value)
    return bool(EMAIL_RE.match(email)) and not email.endswith(".invalid")


def phone_variants(phone: str | None) -> list[str]:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 10:
        return []
    last10 = digits[-10:]
    return sorted({last10, f"52{last10}", f"521{last10}", f"+52{last10}", phone or ""} - {""})


# --------------------------------------------------------------------------- plazos y semáforo
def initial_deadlines(kind: str, details: dict | None, received_at: datetime.datetime):
    """(primera respuesta, respuesta, efectiva) para una solicitud recién recibida."""
    details = details or {}
    first = effective = None
    if kind in ATTENTION_KINDS:
        first = business_deadline(received_at, settings.complaint_first_response_business_days)
        respond_by = business_deadline(received_at, settings.complaint_response_business_days)
        if details.get("motivo") == "producto_defectuoso":
            respond_by = min(respond_by, calendar_deadline(received_at, DEFECT_CLAIM_DAYS))
    elif kind == "retiro_importado" and details.get("relacion") == "autor":
        respond_by = effective = received_at + datetime.timedelta(hours=IMPORTED_AUTHOR_HOURS)
    else:
        respond_by = business_deadline(received_at, ARCO_RESPONSE_DAYS)
        if kind == "acceso" and details.get("publicidad"):
            respond_by = min(respond_by, calendar_deadline(received_at, ADVERTISING_ACCESS_DAYS))
    return first, respond_by, effective


def response_days(req: ComplianceRequest) -> int:
    return settings.complaint_response_business_days if req.kind in ATTENTION_KINDS else ARCO_RESPONSE_DAYS


def waiting_on_requester(req: ComplianceRequest) -> bool:
    return bool(req.info_requested_at and not req.info_received_at and req.status not in FINAL_STATUSES)


def active_deadline(req: ComplianceRequest) -> tuple[datetime.datetime | None, str | None]:
    """Plazo que corre ahora y qué hay que hacer antes de que venza."""
    if req.status in FINAL_STATUSES:
        return None, None
    if waiting_on_requester(req):
        return req.info_due_at, "Esperando la información que pedimos"
    if req.status in OPEN_STATUSES:
        if req.kind in ATTENTION_KINDS and req.first_response_due_at and not req.first_response_at:
            return req.first_response_due_at, "Primera respuesta"
        return req.respond_by, "Respuesta"
    if req.status == "respondida" and req.outcome in POSITIVE_OUTCOMES and req.effective_by:
        return req.effective_by, "Hacerla efectiva"
    return None, None


def sla(req: ComplianceRequest, now: datetime.datetime | None = None) -> dict:
    """Semáforo de la cola: rojo (vencida), amarillo (vence en 2 días hábiles o en 24 h), verde, azul (esperando a
    la persona) o gris (sin plazo corriendo)."""
    now = now or utcnow()
    deadline, label = active_deadline(req)
    if deadline is None:
        return {"color": "gris", "vence": None, "etapa": None, "dias_habiles_restantes": None, "vencida": False}
    left = business_days_left(now, deadline)
    if waiting_on_requester(req):
        color = "azul"
    elif now > deadline:
        color = "rojo"
    elif (req.kind == "retiro_importado" and deadline - now <= datetime.timedelta(hours=24)) or left <= DUE_SOON_BUSINESS_DAYS:
        color = "amarillo"
    else:
        color = "verde"
    return {"color": color, "vence": deadline, "etapa": label, "dias_habiles_restantes": left,
            "vencida": now > deadline and not waiting_on_requester(req)}


# --------------------------------------------------------------------------- avisos
def _send_email(to: str | None, title: str, body: str, url: str | None = None) -> None:
    """Correo a quien presentó la solicitud (siempre al correo de la solicitud, tenga o no cuenta)."""
    if not valid_email(to):
        return
    from app.services.background import dispatch

    try:
        dispatch("app.tasks.notifications.send_notification_email", normalize_email(to), title, body, url)
    except Exception:  # noqa: BLE001 - un correo caído no debe tumbar la solicitud
        logger.exception("No se pudo despachar el correo de la solicitud")


def _send_whatsapp(phone: str | None, text: str) -> None:
    if not phone or not settings.whatsapp_enabled:
        return
    from app.services.background import dispatch

    try:
        dispatch("app.tasks.notifications.send_whatsapp_notification", phone, text, None, [])
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo despachar el WhatsApp de la solicitud")


def notify_requester(db: Session, req: ComplianceRequest, title: str, body: str, url: str | None = None,
                     in_app: bool = True) -> None:
    """Correo a la persona; además aviso en la app si la solicitud está ligada a una cuenta activa, y WhatsApp si
    llegó por el bot y no dejó correo."""
    full_title = f"{title} (folio {req.folio})"
    _send_email(req.email, full_title, body, url or page_url(req, folio=req.folio))
    if not req.email and req.channel == "whatsapp":
        _send_whatsapp(req.phone, f"{full_title}\n{body}")
    if req.user_id and in_app:
        user = db.get(User, req.user_id)
        if user and user.is_active and not user.deleted_at:
            from app.utils.notifications import create_notification

            create_notification(db, user_id=user.id, type="compliance_request", title=full_title, body=body[:1000],
                                data={"folio": req.folio, "url": page_url(req)}, commit=False)


def notify_admins(db: Session, req: ComplianceRequest, title: str, body: str, email: bool = False) -> None:
    from app.services.notify import notify_user

    admins = db.query(User).filter(User.role.in_(ADMIN_ROLES), User.is_active == True).all()  # noqa: E712
    for admin in admins:
        notify_user(db, admin, "compliance_request", title=title, body=body, url="/admin/#solicitudes", email=email,
                    data={"folio": req.folio, "compliance_request_id": req.id}, commit=False)


def _event(db: Session, req: ComplianceRequest, kind: str, actor: User | None = None, public_note: str | None = None,
           internal_note: str | None = None, now: datetime.datetime | None = None) -> ComplianceRequestEvent:
    ev = ComplianceRequestEvent(request_id=req.id, kind=kind, status=req.status, actor_id=actor.id if actor else None,
                                public_note=(public_note or None), internal_note=(internal_note or None),
                                created_at=now or utcnow())
    db.add(ev)
    return ev


def _deadline_sentence(req: ComplianceRequest) -> str:
    if req.kind == "retiro_importado" and (req.details or {}).get("relacion") == "autor":
        return f"Borraremos su texto y sus fotos antes del {fecha_hora_es(req.respond_by)}."
    text = f"Te responderemos a más tardar el {fecha_es(req.respond_by)}"
    if req.kind in ATTENTION_KINDS and req.first_response_due_at:
        text += f"; la primera respuesta llegará a más tardar el {fecha_es(req.first_response_due_at)}"
    if req.kind in ARCO_KINDS:
        text += f" ({ARCO_RESPONSE_DAYS} días hábiles) y, si procede, la haremos efectiva en los {ARCO_EFFECTIVE_DAYS} días hábiles siguientes"
    return text + "."


# --------------------------------------------------------------------------- creación
def _find_imported_report(db: Session, report_id: int | None, url: str | None) -> LostReport | None:
    from app.services import facebook_groups as fbg

    if not report_id and url:
        m = REPORT_URL_RE.search(url)
        if m:
            report_id = int(m.group(1))
    if report_id:
        return db.query(LostReport).filter(LostReport.id == report_id).first()
    if url:
        return fbg.find_imported_report(db, None, url)
    return None


def imported_removal_ready(req: ComplianceRequest) -> bool:
    """El retiro se puede borrar sin esperar al equipo: lo pidió la persona autora y confirmó su correo (o llegó
    desde su cuenta), o el equipo ya respondió que procede."""
    if req.kind != "retiro_importado":
        return False
    if req.outcome in POSITIVE_OUTCOMES:
        return True
    return (req.details or {}).get("relacion") == "autor" and req.identity_verified_at is not None


def ready_removal_report_ids():
    """Subconsulta de los ContentReport de retiro cuyo borrado automático ya procede (para la purga horaria de
    facebook_groups, que también cubre «Soy el autor» desde la app)."""
    from sqlalchemy import and_, select

    return select(ComplianceRequest.content_report_id).where(
        ComplianceRequest.kind == "retiro_importado", ComplianceRequest.content_report_id.isnot(None),
        or_(ComplianceRequest.outcome.in_(POSITIVE_OUTCOMES),
            and_(ComplianceRequest.identity_verified_at.isnot(None),
                 ComplianceRequest.details["relacion"].as_string() == "autor")),
    )


def _hide_imported_report(db: Session, req: ComplianceRequest, report: LostReport, user: User | None,
                          now: datetime.datetime, hide: bool = True) -> None:
    """Deja la solicitud de retiro en la cola de moderación (ContentReport con el mismo motivo que «Soy el autor»)
    y, si la pide la persona autora o quien aparece (hide=True), oculta la publicación de inmediato."""
    from app.services import facebook_groups as fbg

    removal = db.query(ContentReport).filter(
        ContentReport.target_type == "lost_report", ContentReport.target_id == report.id,
        ContentReport.reason == fbg.AUTHOR_REMOVAL_REASON, ContentReport.status == "open",
    ).first()
    if removal is None:
        relation = REMOVAL_RELATIONS.get((req.details or {}).get("relacion"), "Otro")
        removal = ContentReport(
            reporter_id=user.id if user else None, target_type="lost_report", target_id=report.id,
            reason=fbg.AUTHOR_REMOVAL_REASON, status="open",
            details=f"Solicitud {req.folio}. {relation}. Contacto: {req.email or req.phone or '-'}."[:1000],
        )
        db.add(removal)
        db.flush()
    req.content_report_id = removal.id
    if not hide:
        return
    if not report.is_hidden:
        report.is_hidden = True
        report.updated_at = now
    _event(db, req, "oculta", public_note="Ocultamos la publicación mientras atendemos tu solicitud.", now=now)


def create_solicitud(
    db: Session,
    *,
    kind: str,
    name: str,
    description: str,
    email: str | None = None,
    phone: str | None = None,
    user: User | None = None,
    channel: str = "web",
    details: dict | None = None,
    report_id: int | None = None,
    report_url: str | None = None,
    order_id: int | None = None,
    document_id: str | None = None,
    acting_as: str = "titular",
    holder_name: str | None = None,
    identity_method: str | None = None,
    actor: User | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    now: datetime.datetime | None = None,
    commit: bool = True,
) -> ComplianceRequest:
    """Registra una solicitud, manda el acuse con el folio y avisa al equipo.

    - user: cuenta con la sesión iniciada (se liga la solicitud; con correo verificado la identidad queda comprobada).
    - channel="whatsapp" con identity_method="whatsapp": llegó del bot desde el número de la persona titular.
    - actor: admin que la registra a nombre de alguien (canal correo, escrito o teléfono).
    Lanza SolicitudError con un mensaje en español si algo no cuadra.
    """
    now = now or utcnow()
    if kind not in KINDS:
        raise SolicitudError("Elige el tipo de solicitud.")
    details = {k: v for k, v in (details or {}).items() if v is not None and v is not False and v != "" and v != []}
    name = " ".join((name or "").split())[:255]
    description = (description or "").strip()
    email = normalize_email(email) or (normalize_email(user.email) if user else "")
    if len(name) < 3:
        raise SolicitudError("Escribe tu nombre completo.")
    if len(description) < 10:
        raise SolicitudError("Cuéntanos qué necesitas con un poco más de detalle (mínimo 10 caracteres).")
    if email and not valid_email(email):
        raise SolicitudError("Escribe un correo válido para enviarte el acuse y la respuesta.")
    if not email and channel != "whatsapp":
        raise SolicitudError("Escribe un correo para enviarte el acuse y la respuesta.")
    if acting_as == "representante" and len((holder_name or "").strip()) < 3:
        raise SolicitudError("Escribe el nombre de la persona titular a la que representas.")

    report = None
    if kind == "retiro_importado":
        from app.services import facebook_groups as fbg

        if details.get("relacion") not in REMOVAL_RELATIONS:
            raise SolicitudError("Dinos tu relación con la publicación.")
        if not report_id and not (report_url or "").strip():
            raise SolicitudError("Pega el enlace a la publicación o al reporte en GuauWoow.")
        report = _find_imported_report(db, report_id, report_url)
        if report is not None and not fbg.is_imported(report):
            raise SolicitudError("Este formulario es solo para publicaciones importadas de Facebook o enviadas por "
                                 "voluntarios. Para otros reportes usa «Reportar».")
        if report is not None:
            dup = db.query(ComplianceRequest).filter(
                ComplianceRequest.kind == "retiro_importado", ComplianceRequest.lost_report_id == report.id,
                ComplianceRequest.status.notin_(FINAL_STATUSES),
            ).first()
            if dup is not None:
                dup._duplicate = True  # el router responde 200 con el mismo folio
                return dup
        if report_url:
            details["enlace"] = report_url.strip()[:1000]
    elif report_id:
        report = db.query(LostReport).filter(LostReport.id == report_id).first()

    linked_order = None
    if order_id and user:
        linked_order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if order_id and not linked_order:
        details["pedido"] = str(order_id)[:20]

    first, respond_by, effective_by = initial_deadlines(kind, details, now)
    req = ComplianceRequest(
        folio=next_folio(db, now=now), kind=kind, status="recibida", user_id=user.id if user else None,
        name=name, email=email or None, phone=(phone or "").strip()[:30] or None, channel=channel,
        acting_as=acting_as if acting_as in ("titular", "representante") else "titular",
        holder_name=(holder_name or "").strip()[:255] or None, description=description[:4000],
        details=details or None, lost_report_id=report.id if report else None,
        order_id=linked_order.id if linked_order else None, received_at=now, first_response_due_at=first,
        respond_by=respond_by, effective_by=effective_by, ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:255] or None, created_at=now, updated_at=now,
    )
    # Identidad: cuenta con correo verificado (y el mismo correo), WhatsApp desde el número titular o admin
    if user and user.email_verified and normalize_email(user.email) == email and acting_as == "titular":
        req.identity_verified_at, req.identity_method = now, "cuenta"
    elif identity_method in ("whatsapp", "identificacion", "otro") and (channel == "whatsapp" or actor is not None):
        req.identity_verified_at, req.identity_method = now, identity_method
    confirm_token = None
    if req.identity_verified_at is None and email:
        confirm_token, req.confirm_token_hash = _new_token()
        req.confirm_expires_at = business_deadline(now, CONFIRM_DAYS)
    db.add(req)
    db.flush()

    if document_id and user:
        _attach_own_document(req, document_id, user, now)

    _event(db, req, "creada", actor=actor, now=now,
           public_note=f"Folio {req.folio}. Recibida el {fecha_hora_es(now)}.",
           internal_note=f"Registrada por el equipo (canal {channel})." if actor else None)
    if req.identity_verified_at is not None:
        _event(db, req, "identidad_verificada", actor=actor, now=now,
               public_note={"cuenta": "Con tu cuenta y tu correo verificado.", "whatsapp": "Desde tu número de WhatsApp."}
               .get(req.identity_method, "Comprobada por el equipo."))
    hidden_now = False
    if kind == "retiro_importado" and report is not None:
        hidden_now = details.get("relacion") in IMPORTED_HIDE_RELATIONS
        _hide_imported_report(db, req, report, user, now, hide=hidden_now)

    # Acuse con folio y fecha límite
    lines = [f"Hola, {name.split()[0]}.",
             f"Recibimos tu solicitud de {KIND_LABELS[kind].lower()} el {fecha_hora_es(now)}. Tu folio es {req.folio}.",
             _deadline_sentence(req)]
    if kind == "retiro_importado":
        lines.append("Ya ocultamos la publicación en GuauWoow." if hidden_now else
                     "La revisaremos y te escribiremos." if report is not None else
                     "Todavía no encontramos esa publicación en GuauWoow; la buscaremos y te escribiremos.")
        if details.get("relacion") == "autor" and req.identity_verified_at is None and confirm_token:
            lines.append("Para borrar su texto y sus fotos en menos de 72 horas necesitamos que confirmes tu correo "
                         "con el enlace de este mensaje.")
    confirm_url = None
    if confirm_token:
        confirm_url = page_url(req, folio=req.folio, confirmar=confirm_token)
        lines.append(f"Para confirmar que eres tú, abre el enlace de este correo antes del {fecha_es(req.confirm_expires_at)}. "
                     "Si no la confirmas, tendremos que cerrarla sin atenderla. Si tú no enviaste esta solicitud, "
                     "ignora este correo.")
    lines.append(f"Puedes seguirla con tu folio y tu correo en {settings.public_url(PAGE_FOR_KIND[kind])}.")
    if email or channel != "whatsapp":  # por WhatsApp el bot ya contesta con el folio en la conversación
        notify_requester(db, req, "Recibimos tu solicitud", "\n\n".join(lines), url=confirm_url)
    urgent = kind == "retiro_importado"
    notify_admins(db, req, f"Nueva solicitud {req.folio}: {KIND_LABELS[kind]}",
                  f"{name} · plazo {fecha_hora_es(req.respond_by) if urgent else fecha_es(req.respond_by)}."
                  + (" La publicación ya está oculta." if hidden_now else ""), email=urgent)
    if commit:
        db.commit()
        db.refresh(req)
    return req


def _attach_own_document(req: ComplianceRequest, document_id: str, user: User, now: datetime.datetime) -> None:
    from app.routers.documents import own_private_document, private_document_path

    if not own_private_document(document_id, user.id):
        raise SolicitudError("No encontramos el documento que subiste. Vuelve a subirlo.")
    path = private_document_path(document_id)
    req.id_document_id = document_id
    from app.services import crypto_storage

    # Huella del documento en claro (en disco está cifrado: crypto_storage), igual que al subirlo por correo
    req.id_document_sha256 = hashlib.sha256(crypto_storage.read_private(path)).hexdigest() if path else None
    req.id_document_uploaded_at = now


# --------------------------------------------------------------------------- lado de la persona
def get_by_folio(db: Session, folio: str | None, lock: bool = False) -> ComplianceRequest | None:
    folio = normalize_folio(folio)
    if not folio:
        return None
    q = db.query(ComplianceRequest).filter(ComplianceRequest.folio == folio)
    if lock:
        q = q.with_for_update()
    return q.first()


def find_for_tracking(db: Session, folio: str | None, email: str | None) -> ComplianceRequest | None:
    req = get_by_folio(db, folio)
    if req is None or not req.email or normalize_email(email) != req.email:
        return None
    return req


def confirm(db: Session, token: str | None, now: datetime.datetime | None = None) -> ComplianceRequest:
    """Confirma la solicitud desde el enlace del correo (comprueba que la persona controla ese correo)."""
    now = now or utcnow()
    if not token or len(token) > 200:
        raise SolicitudError("El enlace no es válido.", 404)
    req = db.query(ComplianceRequest).filter(ComplianceRequest.confirm_token_hash == _hash(token)).with_for_update().first()
    if req is None:
        raise SolicitudError("El enlace no es válido o ya se usó.", 404)
    if req.status in FINAL_STATUSES:
        raise SolicitudError("Esta solicitud ya está cerrada.", 409)
    if req.confirm_expires_at and req.confirm_expires_at < now:
        raise SolicitudError("El enlace venció. Envía una solicitud nueva.", 410)
    req.confirm_token_hash = None
    req.confirm_expires_at = None
    if req.identity_verified_at is None:
        req.identity_verified_at, req.identity_method = now, "correo"
    if req.user_id is None and req.acting_as == "titular":
        account = db.query(User).filter(func.lower(User.email) == req.email, User.is_active == True).first()  # noqa: E712
        if account is not None:
            req.user_id = account.id  # controla el correo de esa cuenta: la solicitud aparece en «Mis solicitudes»
    req.updated_at = now
    _event(db, req, "confirmada", public_note="Confirmaste tu solicitud desde tu correo.", now=now)
    db.commit()
    db.refresh(req)
    return req


def access_by_token(db: Session, folio: str | None, token: str | None, lock: bool = False) -> ComplianceRequest:
    req = get_by_folio(db, folio, lock=lock)
    if req is None or not token or not req.access_token_hash or not secrets.compare_digest(req.access_token_hash, _hash(token)):
        raise SolicitudError("El enlace no es válido.", 404)
    if req.access_expires_at and req.access_expires_at < utcnow():
        raise SolicitudError("El enlace venció. Escríbenos con tu folio para enviarte uno nuevo.", 410)
    return req


def pending_actions(req: ComplianceRequest) -> dict:
    return {
        "informacion": waiting_on_requester(req),
        "identificacion": bool(req.id_document_requested_at and not req.id_document_uploaded_at
                               and req.identity_verified_at is None and req.status not in FINAL_STATUSES),
        "descarga": bool(req.kind == "acceso" and req.status == "efectiva" and req.user_id
                         and (req.access_expires_at is None or req.access_expires_at > utcnow())),
        "responder": req.status not in FINAL_STATUSES,
    }


def requester_reply(db: Session, req: ComplianceRequest, message: str | None, file_bytes: bytes | None = None,
                    now: datetime.datetime | None = None) -> ComplianceRequest:
    """La persona contesta un requerimiento, sube la identificación que le pedimos o nos escribe de nuevo
    (p. ej. para pedir una segunda revisión de una queja)."""
    now = now or utcnow()
    message = (message or "").strip()[:4000]
    if req.status == "cerrada" and req.closed_at and req.closed_at < now - datetime.timedelta(days=30):
        raise SolicitudError("Esta solicitud se cerró hace más de 30 días. Envía una solicitud nueva.", 409)
    if not message and not file_bytes:
        raise SolicitudError("Escribe tu respuesta o adjunta el documento.")
    if file_bytes:
        if not req.id_document_requested_at:
            raise SolicitudError("No te pedimos ningún documento para esta solicitud.")
        from app.routers.documents import _write_document, delete_private_document

        doc_id = _write_document(file_bytes)  # valida el contenido (PDF o imagen) y lo guarda en /uploads/private
        if req.id_document_id:
            delete_private_document(req.id_document_id)
        req.id_document_id = doc_id
        req.id_document_sha256 = hashlib.sha256(file_bytes).hexdigest()
        req.id_document_uploaded_at = now
        _event(db, req, "identificacion_recibida", now=now,
               public_note="Recibimos tu documento. Lo borraremos en cuanto terminemos la verificación.")
    if waiting_on_requester(req):
        req.info_received_at = now
        # El plazo de respuesta vuelve a contar desde que recibimos la información (Reglamento LFPDPPP art. 96)
        req.respond_by = business_deadline(now, response_days(req))
        req.status = "en_revision"
        _event(db, req, "info_recibida", internal_note=message or None, now=now,
               public_note=f"Te responderemos a más tardar el {fecha_es(req.respond_by)}.")
    elif message:
        if req.status == "respondida" and req.kind in ATTENTION_KINDS:
            req.status = "en_revision"  # segunda revisión de una queja (atencion-y-quejas.html §5)
            req.respond_by = business_deadline(now, settings.complaint_response_business_days)
        _event(db, req, "respuesta_titular", internal_note=message, now=now)
    req.updated_at = now
    notify_admins(db, req, f"Respuesta en la solicitud {req.folio}",
                  "La persona contestó o adjuntó un documento. Revísalo en la cola de solicitudes.")
    db.commit()
    db.refresh(req)
    return req


def public_view(req: ComplianceRequest, owner: bool = False) -> dict:
    """Lo que ve quien consulta su folio. Sin datos personales ni el texto de la respuesta (llega al correo);
    con owner=True (la cuenta ligada, en «Mis solicitudes») se agregan la descripción y la respuesta."""
    events = [e for e in req.events if e.kind not in INTERNAL_EVENTS]
    view = {
        "folio": req.folio, "tipo": req.kind, "tipo_texto": KIND_LABELS.get(req.kind, req.kind),
        "estado": req.status, "estado_texto": STATUS_LABELS.get(req.status, req.status),
        "resultado": req.outcome, "resultado_texto": OUTCOMES.get(req.outcome) if req.outcome else None,
        "recibida_en": req.received_at, "responde_antes_de": req.respond_by,
        "primera_respuesta_antes_de": req.first_response_due_at if req.kind in ATTENTION_KINDS else None,
        "efectiva_antes_de": req.effective_by if req.outcome in POSITIVE_OUTCOMES or req.kind == "retiro_importado" else None,
        "plazo_ampliado": bool(req.respond_extended_at or req.effective_extended_at),
        "identidad_confirmada": req.identity_verified_at is not None,
        "esperando_tu_respuesta": waiting_on_requester(req),
        "informacion_antes_de": req.info_due_at if waiting_on_requester(req) else None,
        "respondida_en": req.responded_at, "efectiva_en": req.effective_at, "cerrada_en": req.closed_at,
        "historial": [{"tipo": e.kind, "texto": EVENT_LABELS.get(e.kind, e.kind), "fecha": e.created_at,
                       "estado": e.status, **({"nota": e.public_note} if owner and e.public_note else {})}
                      for e in events],
    }
    if owner:
        view.update({"descripcion": req.description, "respuesta": req.response_text,
                     "pendiente": pending_actions(req)})
    return view


def list_for_user(db: Session, user: User) -> list[ComplianceRequest]:
    return (db.query(ComplianceRequest).filter(ComplianceRequest.user_id == user.id)
            .order_by(ComplianceRequest.received_at.desc()).limit(100).all())


# --------------------------------------------------------------------------- lado del equipo
def _require_open(req: ComplianceRequest) -> None:
    if req.status in FINAL_STATUSES:
        raise SolicitudError("La solicitud ya está cerrada.", 409)


def take(db: Session, req: ComplianceRequest, admin: User, message: str | None = None, now=None) -> None:
    now = now or utcnow()
    _require_open(req)
    if req.status != "recibida":
        raise SolicitudError("La solicitud ya está en revisión o respondida.", 409)
    req.status = "en_revision"
    req.assigned_to_id = admin.id
    _event(db, req, "en_revision", actor=admin, public_note=message, now=now)
    notify_requester(db, req, "Estamos revisando tu solicitud",
                     (message + "\n\n" if message else "") + _deadline_sentence(req))


def first_response(db: Session, req: ComplianceRequest, admin: User, message: str, now=None) -> None:
    now = now or utcnow()
    _require_open(req)
    if req.kind not in ATTENTION_KINDS:
        raise SolicitudError("La primera respuesta es solo para dudas, aclaraciones y quejas.")
    if not message:
        raise SolicitudError("Escribe la primera respuesta.")
    req.first_response_at = req.first_response_at or now
    if req.status == "recibida":
        req.status = "en_revision"
        req.assigned_to_id = req.assigned_to_id or admin.id
    _event(db, req, "primera_respuesta", actor=admin, public_note=message, now=now)
    notify_requester(db, req, "Primera respuesta a tu solicitud",
                     f"{message}\n\nTe daremos la respuesta final a más tardar el {fecha_es(req.respond_by)}.")


def request_info(db: Session, req: ComplianceRequest, admin: User, message: str, ask_document: bool = False,
                 now=None) -> str:
    """Requerimiento de información (una sola vez, dentro de los 5 días hábiles siguientes a la recepción).
    Devuelve el enlace para contestar (también va en el correo)."""
    now = now or utcnow()
    _require_open(req)
    if req.status == "respondida":
        raise SolicitudError("La solicitud ya se respondió.", 409)
    if req.info_requested_at:
        raise SolicitudError("Ya pediste información una vez; la ley solo permite pedirla una sola vez.", 409)
    if req.kind not in ATTENTION_KINDS and now > business_deadline(req.received_at, INFO_REQUEST_WINDOW_DAYS):
        raise SolicitudError("Ya pasaron los 5 días hábiles para pedir información. Responde con lo que tienes.", 409)
    if not message or len(message) < 10:
        raise SolicitudError("Explica qué información necesitas (mínimo 10 caracteres).")
    token, req.access_token_hash = _new_token()
    req.info_requested_at = now
    req.info_due_at = business_deadline(now, INFO_REPLY_DAYS)
    req.access_expires_at = req.info_due_at
    if ask_document:
        req.id_document_requested_at = now
    if req.status == "recibida":
        req.status = "en_revision"
        req.assigned_to_id = req.assigned_to_id or admin.id
    _event(db, req, "requerimiento", actor=admin, public_note=message, now=now)
    link = page_url(req, folio=req.folio, clave=token)
    extra = ("\n\nPuedes subir una identificación oficial en la que tapes los datos que no hacen falta (como la "
             "CURP o la clave de elector). La usaremos solo para comprobar quién eres y la borraremos al terminar."
             if ask_document else "")
    notify_requester(db, req, "Necesitamos más información",
                     f"{message}{extra}\n\nContesta desde el enlace de este correo antes del {fecha_es(req.info_due_at)} "
                     f"({INFO_REPLY_DAYS} días hábiles). El plazo para responderte vuelve a contar desde que recibamos "
                     "tu información. Si no la recibimos, tendremos que cerrar la solicitud.", url=link)
    return link


def verify_identity(db: Session, req: ComplianceRequest, admin: User, method: str = "identificacion",
                    note: str | None = None, now=None) -> None:
    now = now or utcnow()
    _require_open(req)
    req.identity_verified_at = now
    req.identity_method = method if method in ("identificacion", "correo", "whatsapp", "cuenta", "otro") else "otro"
    _event(db, req, "identidad_verificada", actor=admin, internal_note=note, now=now,
           public_note="Comprobamos tu identidad." + (" Ya borramos la copia de tu identificación." if req.id_document_id else ""))
    purge_id_document(req, now)  # derechos-arco §5: al terminar la verificación la borramos


def extend(db: Session, req: ComplianceRequest, admin: User, reason: str, now=None) -> None:
    """Ampliación del plazo que corre (una sola vez por plazo, por un periodo igual, avisando antes de que venza)."""
    now = now or utcnow()
    _require_open(req)
    if not reason or len(reason) < 10:
        raise SolicitudError("Explica el motivo de la ampliación (se le comunica a la persona).")
    if req.kind not in ARCO_KINDS:
        raise SolicitudError("La ampliación de plazo aplica solo a solicitudes de datos personales.")
    if req.status in OPEN_STATUSES:
        if req.respond_extended_at:
            raise SolicitudError("El plazo de respuesta ya se amplió una vez.", 409)
        if now > req.respond_by:
            raise SolicitudError("El plazo de respuesta ya venció; no se puede ampliar.", 409)
        req.respond_by = _end_of_day_utc(add_business_days(_local_date(req.respond_by), ARCO_RESPONSE_DAYS))
        req.respond_extended_at = now
        new_deadline, what = req.respond_by, "para responderte"
    elif req.status == "respondida" and req.outcome in POSITIVE_OUTCOMES and req.effective_by:
        if req.effective_extended_at:
            raise SolicitudError("El plazo para hacerla efectiva ya se amplió una vez.", 409)
        if now > req.effective_by:
            raise SolicitudError("El plazo para hacerla efectiva ya venció; no se puede ampliar.", 409)
        req.effective_by = _end_of_day_utc(add_business_days(_local_date(req.effective_by), ARCO_EFFECTIVE_DAYS))
        req.effective_extended_at = now
        new_deadline, what = req.effective_by, "para hacerla efectiva"
    else:
        raise SolicitudError("No hay un plazo que ampliar.", 409)
    req.extension_reason = reason
    _event(db, req, "ampliacion", actor=admin, public_note=f"Nuevo plazo {what}: {fecha_es(new_deadline)}. Motivo: {reason}",
           now=now)
    notify_requester(db, req, "Ampliamos el plazo de tu solicitud",
                     f"Necesitamos más tiempo {what}. Ampliamos el plazo una sola vez, hasta el {fecha_es(new_deadline)}, "
                     f"por este motivo: {reason}")


def respond(db: Session, req: ComplianceRequest, admin: User, outcome: str, message: str,
            denial_reason: str | None = None, now=None) -> None:
    now = now or utcnow()
    _require_open(req)
    if req.status == "respondida" and req.kind not in ATTENTION_KINDS:
        raise SolicitudError("La solicitud ya se respondió. Hazla efectiva o ciérrala.", 409)
    if outcome not in OUTCOMES:
        raise SolicitudError("Elige el resultado de la solicitud.")
    if not message or len(message) < 10:
        raise SolicitudError("Escribe la respuesta para la persona (mínimo 10 caracteres).")
    if req.kind in ARCO_KINDS and outcome in POSITIVE_OUTCOMES and req.identity_verified_at is None:
        raise SolicitudError("Comprueba primero la identidad de la persona (correo confirmado o identificación).", 409)
    if outcome == "no_procede" and denial_reason not in DENIAL_REASONS:
        raise SolicitudError("Elige la causa de la negativa (LFPDPPP art. 33).")
    req.outcome = outcome
    req.denial_reason = denial_reason if outcome in ("no_procede", "sin_datos") else None
    if outcome == "sin_datos":
        req.denial_reason = "sin_datos"
    req.response_text = message[:8000]
    req.responded_at = now
    req.first_response_at = req.first_response_at or now
    req.assigned_to_id = req.assigned_to_id or admin.id
    final = outcome not in POSITIVE_OUTCOMES and req.kind not in ATTENTION_KINDS
    if req.kind in ARCO_KINDS and outcome in POSITIVE_OUTCOMES:
        req.effective_by = business_deadline(now, ARCO_EFFECTIVE_DAYS)
    req.status = "cerrada" if final else "respondida"
    if final:
        req.closed_at = now
    _event(db, req, "respondida", actor=admin, public_note=message, now=now)
    body = message
    if req.kind in ARCO_KINDS and outcome in POSITIVE_OUTCOMES:
        body += f"\n\nLa haremos efectiva a más tardar el {fecha_es(req.effective_by)} ({ARCO_EFFECTIVE_DAYS} días hábiles)."
    if req.kind in ARCO_KINDS and outcome not in POSITIVE_OUTCOMES:
        body += ("\n\nSi no estás de acuerdo, puedes presentar una solicitud de protección de datos ante la Secretaría "
                 "Anticorrupción y Buen Gobierno dentro de los 15 días hábiles siguientes a esta respuesta "
                 f"(cómo hacerlo: {settings.public_url('/app/legal/derechos-arco.html#autoridad')}).")
    link = None
    if req.kind in ATTENTION_KINDS:
        # Enlace para pedir una segunda revisión sin cuenta (atencion-y-quejas.html §5)
        token, req.access_token_hash = _new_token()
        req.access_expires_at = now + datetime.timedelta(days=SECOND_REVIEW_DAYS)
        link = page_url(req, folio=req.folio, clave=token)
        body += ("\n\nSi no estás conforme, pide una segunda revisión desde el enlace de este correo (vale "
                 f"{SECOND_REVIEW_DAYS} días). También puedes acudir a PROFECO en cualquier momento.")
    if req.kind == "retiro_importado" and outcome not in POSITIVE_OUTCOMES:
        _restore_imported(db, req, admin, now)
    if final:
        purge_id_document(req, now)
    notify_requester(db, req, "Respondimos tu solicitud", body, url=link)


def make_effective(db: Session, req: ComplianceRequest, admin: User | None, message: str | None = None,
                   delete_account: bool = False, delete_whatsapp: bool = False, now=None) -> dict:
    """Ejecuta lo que procede y cierra la solicitud como «efectiva». Devuelve un resumen de lo hecho."""
    now = now or utcnow()
    _require_open(req)
    if req.kind in ARCO_KINDS:
        if req.status != "respondida" or req.outcome not in POSITIVE_OUTCOMES:
            raise SolicitudError("Primero responde la solicitud con un resultado que proceda.", 409)
    elif req.kind in ATTENTION_KINDS:
        raise SolicitudError("Las dudas y quejas se responden y se cierran; no hay nada que hacer efectivo.", 409)
    if req.identity_verified_at is None and req.kind in ARCO_KINDS:
        raise SolicitudError("Comprueba primero la identidad de la persona.", 409)
    done: dict = {}
    body = (message or "").strip()
    link = None
    user = db.get(User, req.user_id) if req.user_id else None
    if req.kind == "acceso":
        if user is not None and user.is_active:
            token, req.access_token_hash = _new_token()
            req.access_expires_at = now + datetime.timedelta(days=DOWNLOAD_LINK_DAYS)
            link = page_url(req, folio=req.folio, clave=token)
            done["descarga"] = link
            body = (body + "\n\n" if body else "") + (
                f"Descarga tus datos en formato JSON desde el enlace de este correo antes del "
                f"{fecha_es(req.access_expires_at)}. Es el mismo archivo de «Perfil → Descargar mis datos».")
        elif not body:
            raise SolicitudError("Esta solicitud no está ligada a una cuenta: escribe en el mensaje los datos que "
                                 "encontraste (o adjúntalos por correo).")
    if req.kind in ("revocacion", "limitacion"):
        done["permisos"] = apply_permission_changes(db, req, user, now)
    if req.kind == "cancelacion":
        if delete_whatsapp:
            phone = proven_whatsapp_phone(req, user)
            if phone is None:
                raise SolicitudError(WHATSAPP_UNPROVEN, 409)
            done["whatsapp"] = delete_whatsapp_data(db, phone, now)
        if delete_account:
            if user is None or not user.is_active:
                raise SolicitudError("La solicitud no está ligada a una cuenta activa.", 409)
            if user.role == "superadmin":
                raise SolicitudError("No se puede eliminar una cuenta de superadmin desde aquí.", 409)
            done["cuenta"] = True
    if req.kind == "retiro_importado":
        done["retiro"] = purge_imported(db, req, admin, now)
    req.status = "efectiva"
    req.effective_at = now
    req.closed_at = now
    req.updated_at = now
    purge_id_document(req, now)
    summary = body or {"revocacion": "Ya retiramos los permisos que pediste.",
                       "limitacion": "Ya limitamos el uso de tus datos como pediste.",
                       "cancelacion": "Ya cancelamos los datos que pediste.",
                       "retiro_importado": "Ya borramos el texto y las fotos de la publicación en GuauWoow."}.get(req.kind, "Listo.")
    _event(db, req, "efectiva", actor=admin, public_note=summary, now=now)
    notify_requester(db, req, "Hicimos efectiva tu solicitud", summary, url=link, in_app=not delete_account)
    if delete_account and user is not None:
        from app.routers.users import anonymize_account

        db.flush()
        anonymize_account(db, user, now)  # hace commit (misma anonimización que «Eliminar mi cuenta»)
    return done


def close(db: Session, req: ComplianceRequest, admin: User | None, message: str | None = None,
          outcome: str | None = None, denial_reason: str | None = None, now=None, notify: bool = True) -> None:
    now = now or utcnow()
    _require_open(req)
    if outcome and outcome not in OUTCOMES:
        raise SolicitudError("Resultado no válido.")
    if outcome == "no_procede" and denial_reason not in DENIAL_REASONS:
        raise SolicitudError("Elige la causa de la negativa.")
    req.outcome = outcome or req.outcome
    if denial_reason:
        req.denial_reason = denial_reason
    req.status = "cerrada"
    req.closed_at = now
    req.updated_at = now
    if message and not req.response_text:
        req.response_text = message[:8000]
        req.responded_at = req.responded_at or now
    if req.kind == "retiro_importado" and req.outcome not in POSITIVE_OUTCOMES:
        _restore_imported(db, req, admin, now)
    purge_id_document(req, now)
    _event(db, req, "cerrada", actor=admin, public_note=message, now=now)
    if notify:
        notify_requester(db, req, "Cerramos tu solicitud", message or "Cerramos tu solicitud.")


def add_note(db: Session, req: ComplianceRequest, admin: User, note: str, now=None) -> None:
    if not note:
        raise SolicitudError("Escribe la nota.")
    _event(db, req, "nota", actor=admin, internal_note=note[:4000], now=now)


# --------------------------------------------------------------------------- efectos
def apply_permission_changes(db: Session, req: ComplianceRequest, user: User | None, now: datetime.datetime) -> list[str]:
    """Apaga los permisos de una revocación o limitación. Lo que no depende de la cuenta (analítica en el
    navegador) se le explica en la respuesta."""
    permisos = list((req.details or {}).get("permisos") or [])
    if req.kind == "limitacion" and "publicidad" in permisos:
        permisos = sorted(set(permisos) | {"correos", "whatsapp"})  # listado de exclusión: todos los canales
    wa_phone = proven_whatsapp_phone(req, user) if "whatsapp" in permisos else None
    if "whatsapp" in permisos and wa_phone is None and (req.phone or user is None):
        # Un número escrito en el formulario no prueba nada: no se apagan avisos de un número ajeno
        raise SolicitudError(WHATSAPP_UNPROVEN, 409)
    applied: list[str] = []
    if user is not None:
        # Mismo camino que Perfil -> Preferencias (K-PREF): cambia el permiso, deja la constancia con el propósito
        # estándar (canal «solicitud») y, para WhatsApp, marca la baja en el bot
        from app.services import consent

        targets = []
        if {"correos", "publicidad"} & set(permisos):
            targets.append(("email_marketing", "marketing_opt_in"))
        if "alertas" in permisos:
            targets.append(("notify_nearby", "notify_nearby"))
        if "whatsapp" in permisos:
            targets.append(("whatsapp_alerts", "whatsapp_alerts"))
        for purpose, field in targets:
            if consent.set_preference(db, user, purpose, False, channel="solicitud"):
                applied.append(field)
    if "whatsapp" in permisos:
        variants = phone_variants(wa_phone)
        if variants:
            n = db.query(BotInteraction).filter(BotInteraction.phone.in_(variants), BotInteraction.opted_out_at.is_(None)) \
                .update({BotInteraction.opted_out_at: now}, synchronize_session=False)
            if n:
                applied.append("whatsapp_bot")
    return applied


def is_marketing_excluded(db: Session, email: str | None = None, phone: str | None = None) -> bool:
    """Listado de exclusión de GuauWoow (derechos-arco §10): solicitudes de limitación por publicidad hechas
    efectivas. Cualquier envío promocional debe consultarlo antes de mandar."""
    filters = []
    if email:
        filters.append(ComplianceRequest.email == normalize_email(email))
    variants = phone_variants(phone)
    if variants:
        filters.append(ComplianceRequest.phone.in_(variants))
    if not filters:
        return False
    rows = db.query(ComplianceRequest.details).filter(
        ComplianceRequest.kind == "limitacion", ComplianceRequest.status == "efectiva", or_(*filters)).all()
    return any("publicidad" in ((d or {}).get("permisos") or []) for (d,) in rows)


def proven_whatsapp_phone(req: ComplianceRequest, user: User | None) -> str | None:
    """Número de WhatsApp cuya titularidad está comprobada, o None. Vale si la solicitud llegó del bot desde ese
    número, o si es el teléfono verificado de la cuenta ligada (y coincide con el que se escribió, si se escribió).
    Confirmar el correo de la solicitud no prueba que el número escrito sea de quien la envió."""
    if req.channel == "whatsapp" and req.identity_method == "whatsapp" and req.phone:
        return req.phone
    if user is not None and user.phone and user.phone_verified:
        if not req.phone or set(phone_variants(req.phone)) & set(phone_variants(user.phone)):
            return user.phone
    return None


def delete_whatsapp_data(db: Session, phone: str | None, now: datetime.datetime) -> dict:
    """Borra la conversación con el bot y el contenido de los reportes creados desde ese número."""
    from app.services.facebook_groups import purge_report_content

    variants = phone_variants(phone)
    if not variants:
        raise SolicitudError("La solicitud no tiene un número de WhatsApp.")
    # Se borra la conversación pero se conserva la marca de baja del número (como ELIMINAR en el bot): sin ella el
    # bot volvería a escribirle avisos
    chats = 0
    for row in db.query(BotInteraction).filter(BotInteraction.phone.in_(variants)).all():
        row.data = {}
        row.last_message = None
        row.stage = "welcome"
        row.opted_out_at = row.opted_out_at or now
        chats += 1
    reports = db.query(LostReport).filter(LostReport.source == "whatsapp", LostReport.contact_phone.in_(variants),
                                          LostReport.purged_at.is_(None)).all()
    for report in reports:
        report.is_hidden = True
        report.contact_phone = None
        purge_report_content(db, report, now)
    return {"conversaciones": chats, "reportes": len(reports)}


def purge_imported(db: Session, req: ComplianceRequest, admin: User | None, now: datetime.datetime) -> bool:
    """Borra el texto y las fotos de la publicación importada (se conserva el registro y el enlace)."""
    from app.services.facebook_groups import purge_report_content

    report = db.get(LostReport, req.lost_report_id) if req.lost_report_id else None
    if report is None:
        return False
    if report.purged_at is None:
        report.is_hidden = True
        purge_report_content(db, report, now)
    removal = db.get(ContentReport, req.content_report_id) if req.content_report_id else None
    if removal is not None and removal.status == "open":
        removal.status, removal.action, removal.resolved_at = "resolved", "hide_content", now
        removal.resolved_by = admin.id if admin else None
        removal.admin_notes = f"Retiro hecho efectivo desde la solicitud {req.folio}."
    _event(db, req, "retirada", actor=admin, now=now)
    return True


def _restore_imported(db: Session, req: ComplianceRequest, admin: User | None, now: datetime.datetime) -> None:
    """La solicitud de retiro no procede: la publicación vuelve a mostrarse (si no se había borrado)."""
    report = db.get(LostReport, req.lost_report_id) if req.lost_report_id else None
    removal = db.get(ContentReport, req.content_report_id) if req.content_report_id else None
    if removal is not None and removal.status == "open":
        removal.status, removal.resolved_at = "dismissed", now
        removal.resolved_by = admin.id if admin else None
        removal.admin_notes = f"Solicitud {req.folio} no procede."
    hid_it = (req.details or {}).get("relacion") in IMPORTED_HIDE_RELATIONS  # «otro» nunca la ocultó
    if report is not None and hid_it and report.is_hidden and report.purged_at is None:
        report.is_hidden = False
        report.updated_at = now
        _event(db, req, "restaurada", actor=admin, now=now)


def purge_id_document(req: ComplianceRequest, now: datetime.datetime | None = None) -> bool:
    """Borra la copia de la identificación; queda la constancia (fecha y huella SHA-256)."""
    if not req.id_document_id:
        return False
    from app.routers.documents import delete_private_document

    delete_private_document(req.id_document_id)
    req.id_document_id = None
    req.id_document_purged_at = now or utcnow()
    return True


def build_export(db: Session, req: ComplianceRequest):
    """Archivo de «Descargar mis datos» de la cuenta ligada (routers/users.export_my_data)."""
    from app.routers.users import export_my_data

    user = db.get(User, req.user_id) if req.user_id else None
    if user is None or not user.is_active:
        raise SolicitudError("La cuenta de esta solicitud ya no existe.", 410)
    response = export_my_data(current_user=user, db=db)
    _event(db, req, "descarga", now=utcnow())
    db.commit()
    return response


# --------------------------------------------------------------------------- tareas programadas
def daily_maintenance(db: Session, now: datetime.datetime | None = None) -> dict:
    """Identificaciones vencidas, solicitudes sin confirmar o sin la información pedida, aviso de plazos y
    borrado de expedientes de más de 5 años."""
    now = now or utcnow()
    out = {"identificaciones": 0, "sin_info": 0, "sin_confirmar": 0, "por_vencer": 0, "expedientes": 0}
    # 1. Identificaciones: se borran al resolver la solicitud y nunca duran más de 30 días
    cutoff = now - datetime.timedelta(days=ID_DOCUMENT_MAX_DAYS)
    for req in db.query(ComplianceRequest).filter(ComplianceRequest.id_document_id.isnot(None), or_(
            ComplianceRequest.status.in_(FINAL_STATUSES), ComplianceRequest.id_document_uploaded_at < cutoff)).limit(500):
        out["identificaciones"] += purge_id_document(req, now)
    # 2. Requerimiento sin contestar en 10 días hábiles
    for req in db.query(ComplianceRequest).filter(
            ComplianceRequest.status.notin_(FINAL_STATUSES), ComplianceRequest.info_requested_at.isnot(None),
            ComplianceRequest.info_received_at.is_(None), ComplianceRequest.info_due_at < now).limit(500):
        close(db, req, None, "No recibimos la información que te pedimos dentro del plazo, así que cerramos la "
              "solicitud. Puedes presentar una nueva cuando quieras.", outcome="no_procede",
              denial_reason="informacion_incompleta", now=now)
        out["sin_info"] += 1
    # 3. Solicitudes de datos personales cuyo correo nunca se confirmó
    for req in db.query(ComplianceRequest).filter(
            ComplianceRequest.status == "recibida", ComplianceRequest.kind.in_(ARCO_KINDS),
            ComplianceRequest.identity_verified_at.is_(None), ComplianceRequest.info_requested_at.is_(None),
            ComplianceRequest.confirm_expires_at < now).limit(500):
        close(db, req, None, "No confirmaste la solicitud desde tu correo, así que no pudimos comprobar que eres la "
              "persona titular. Puedes presentar una nueva cuando quieras.", outcome="no_procede",
              denial_reason="identidad_no_acreditada", now=now)
        out["sin_confirmar"] += 1
    # 4. Aviso diario al equipo de lo que vence en 2 días hábiles o ya venció
    due = [r for r in db.query(ComplianceRequest).filter(ComplianceRequest.status.notin_(FINAL_STATUSES)).limit(2000)
           if sla(r, now)["color"] in ("rojo", "amarillo")]
    out["por_vencer"] = len(due)
    if due:
        from app import cache

        if cache.add(f"solicitudes:aviso:{_local_date(now).isoformat()}", 2 * 86400):
            overdue = sum(1 for r in due if sla(r, now)["vencida"])
            from app.services.notify import notify_user

            for admin in db.query(User).filter(User.role.in_(ADMIN_ROLES), User.is_active == True).all():  # noqa: E712
                notify_user(db, admin, "compliance_request_due", "Solicitudes por vencer",
                            f"{len(due)} solicitudes vencen en {DUE_SOON_BUSINESS_DAYS} días hábiles o menos; "
                            f"{overdue} ya vencieron.", url="/admin/#solicitudes", email=True, commit=False)
    # 5. IP y navegador de quien presentó la solicitud: se acortan a los 30 días (conservacion.html, R37)
    ip_cutoff = now - datetime.timedelta(days=IP_TRIM_DAYS)
    for req in db.query(ComplianceRequest).filter(ComplianceRequest.created_at < ip_cutoff,
                                                   ComplianceRequest.user_agent.isnot(None)).limit(2000):
        req.ip = trim_ip(req.ip)
        req.user_agent = None
        out["ips"] = out.get("ips", 0) + 1
    # 6. Expedientes cerrados hace más de 5 años
    old = now - datetime.timedelta(days=365 * RECORD_RETENTION_YEARS + 2)
    out["expedientes"] = purge_expired_records(db, old)
    db.commit()
    return out


def trim_ip(ip: str | None) -> str | None:
    """IPv4 sin el último octeto (a.b.c.0); IPv6 con solo los primeros 3 grupos."""
    if not ip:
        return None
    if ":" in ip:
        return ":".join(ip.split(":")[:3]) + "::"
    parts = ip.split(".")
    return ".".join(parts[:3] + ["0"]) if len(parts) == 4 else None


def purge_expired_records(db: Session, closed_before: datetime.datetime) -> int:
    """Borra los expedientes cerrados antes de esa fecha (eventos incluidos). Lo puede llamar services/retention."""
    ids = [i for (i,) in db.query(ComplianceRequest.id).filter(
        ComplianceRequest.status.in_(FINAL_STATUSES), ComplianceRequest.closed_at < closed_before).limit(1000)]
    if not ids:
        return 0
    db.query(ComplianceRequestEvent).filter(ComplianceRequestEvent.request_id.in_(ids)).delete(synchronize_session=False)
    return db.query(ComplianceRequest).filter(ComplianceRequest.id.in_(ids)).delete(synchronize_session=False)


def enforce_imported_removals(db: Session, now: datetime.datetime | None = None) -> list[str]:
    """Cada hora: borra el texto y las fotos de las publicaciones importadas cuyo retiro pidió la persona autora
    (con el correo confirmado) hace IMPORTED_REMOVAL_PURGE_HOURS horas y que el equipo no descartó, para cumplir «en
    menos de 72 horas». Lo demás (quien aparece, «otro», sin confirmar) lo decide el equipo."""
    now = now or utcnow()
    cutoff = now - datetime.timedelta(hours=max(0, settings.imported_removal_purge_hours))
    done: list[str] = []
    rows = db.query(ComplianceRequest).filter(
        ComplianceRequest.kind == "retiro_importado", ComplianceRequest.status.in_(OPEN_STATUSES),
        ComplianceRequest.lost_report_id.isnot(None), ComplianceRequest.received_at <= cutoff,
    ).order_by(ComplianceRequest.id).limit(500).all()
    for req in rows:
        if not imported_removal_ready(req):
            continue  # quien aparece, «otro» o la persona autora sin confirmar su correo: lo decide el equipo
        removal = db.get(ContentReport, req.content_report_id) if req.content_report_id else None
        if removal is not None and removal.status == "dismissed":
            continue  # el equipo lo descartó en moderación: queda en la cola para responder
        try:
            with db.begin_nested():
                purge_imported(db, req, None, now)
                req.outcome = req.outcome or "procede"
                req.status = "efectiva"
                req.responded_at = req.responded_at or now
                req.effective_at = req.closed_at = now
                summary = "Ya borramos el texto y las fotos de la publicación en GuauWoow."
                _event(db, req, "efectiva", public_note=summary, now=now)
                notify_requester(db, req, "Retiramos la publicación",
                                 summary + " La publicación original sigue en Facebook hasta que la borres ahí.")
            done.append(req.folio)
        except Exception:  # noqa: BLE001 - una falla no detiene las demás
            logger.exception("No se pudo completar el retiro de la solicitud %s", req.folio)
    if done:
        db.commit()
    return done


# --------------------------------------------------------------------------- estadísticas (transparencia)
def arco_stats(db: Session, start: datetime.datetime, end: datetime.datetime) -> dict:
    """Solicitudes de datos personales recibidas en el periodo: por tipo, respondidas a tiempo, ampliaciones,
    negativas por causa y revocaciones. Sin datos personales."""
    rows = db.query(ComplianceRequest.kind, ComplianceRequest.status, ComplianceRequest.outcome,
                    ComplianceRequest.denial_reason, ComplianceRequest.respond_by, ComplianceRequest.responded_at,
                    ComplianceRequest.respond_extended_at).filter(
        ComplianceRequest.kind.in_(ARCO_KINDS), ComplianceRequest.received_at >= start,
        ComplianceRequest.received_at < end).all()
    by_kind: dict[str, int] = {}
    denials: dict[str, int] = {}
    answered = on_time = extended = 0
    for kind, status, outcome, denial, respond_by, responded, extended_at in rows:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if extended_at:
            extended += 1
        if responded:
            answered += 1
            # A tiempo: antes del plazo vigente (respond_by), que ya incluye la ampliación única de la ley
            # (LFPDPPP art. 32) y el reinicio cuando la persona contesta lo que le pedimos
            if respond_by and responded <= respond_by:
                on_time += 1
        if outcome in ("no_procede", "sin_datos"):
            key = denial or "otro"
            denials[key] = denials.get(key, 0) + 1
    return {
        "recibidas": len(rows), "por_tipo": by_kind, "respondidas": answered, "respondidas_a_tiempo": on_time,
        "porcentaje_a_tiempo": round(100 * on_time / answered, 1) if answered else None,
        "ampliaciones": extended, "negativas_por_causa": denials, "revocaciones": by_kind.get("revocacion", 0),
    }


def imported_removal_count(db: Session, start: datetime.datetime, end: datetime.datetime) -> int:
    return db.query(func.count(ComplianceRequest.id)).filter(
        ComplianceRequest.kind == "retiro_importado", ComplianceRequest.received_at >= start,
        ComplianceRequest.received_at < end).scalar() or 0


# --------------------------------------------------------------------------- plantillas de respuesta
TEMPLATES = (
    {"id": "revision", "titulo": "Acuse: la estamos revisando", "accion": "en_revision", "tipos": KINDS,
     "texto": "Hola, {nombre}: ya estamos revisando tu solicitud {folio}. Te responderemos a más tardar el {fecha_respuesta}."},
    {"id": "req_identidad", "titulo": "Pedir identificación", "accion": "requerir_info", "tipos": ARCO_KINDS,
     "identificacion": True,
     "texto": "Para atender tu solicitud {folio} necesitamos comprobar que eres la persona titular de los datos. "
              "Sube una identificación oficial vigente desde el enlace de este correo; puedes tapar la CURP, la clave "
              "de elector y la fotografía si no hacen falta. Si actúas en representación de alguien, sube también su "
              "identificación y el documento que acredita la representación (poder notarial o carta poder firmada "
              "ante dos testigos)."},
    {"id": "req_info", "titulo": "Pedir información que falta", "accion": "requerir_info", "tipos": KINDS,
     "texto": "Para atender tu solicitud {folio} necesitamos que nos indiques: [describe aquí lo que falta, por "
              "ejemplo el correo de tu cuenta, el enlace a la publicación o el número de pedido]."},
    {"id": "ampliacion", "titulo": "Ampliar el plazo (una vez)", "accion": "ampliar", "tipos": ARCO_KINDS,
     "texto": "[Motivo concreto, por ejemplo: la información está en varios sistemas y necesitamos revisarlos todos.]"},
    {"id": "acceso_procede", "titulo": "Acceso: procede", "accion": "responder", "resultado": "procede",
     "tipos": ("acceso",),
     "texto": "Revisamos tu solicitud de acceso {folio}. Procede: te enviaremos un enlace para descargar todos los "
              "datos personales que tenemos de ti, en un archivo que otras aplicaciones pueden leer, junto con para "
              "qué los usamos y con quién los compartimos, como explica el Aviso de Privacidad."},
    {"id": "rectificacion_procede", "titulo": "Rectificación: procede", "accion": "responder", "resultado": "procede",
     "tipos": ("rectificacion",),
     "texto": "Revisamos tu solicitud de rectificación {folio}. Procede: corregiremos [dato] por [dato correcto] y, "
              "si lo compartimos antes con alguien, le avisaremos de la corrección."},
    {"id": "cancelacion_procede", "titulo": "Cancelación: procede", "accion": "responder", "resultado": "procede",
     "tipos": ("cancelacion",),
     "texto": "Revisamos tu solicitud de cancelación {folio}. Procede: dejaremos de usar tus datos y los borraremos o "
              "anonimizaremos. Por obligación legal conservaremos, bloqueados y sin datos que te identifiquen, los "
              "registros de pedidos y donativos (Código Fiscal de la Federación, art. 30) y la evidencia de "
              "moderación que la ley exige guardar; al vencer esos plazos se suprimen."},
    {"id": "oposicion_procede", "titulo": "Oposición: procede", "accion": "responder", "resultado": "procede",
     "tipos": ("oposicion",),
     "texto": "Revisamos tu solicitud de oposición {folio}. Procede: dejaremos de usar tus datos para [finalidad]."},
    {"id": "revocacion_procede", "titulo": "Revocación: procede", "accion": "responder", "resultado": "procede",
     "tipos": ("revocacion",),
     "texto": "Revisamos tu solicitud {folio}. Procede: retiraremos los permisos que pediste ({permisos}). Retirarlos no "
              "afecta lo que hicimos antes con tu permiso. La analítica la apagas tú en «Preferencias de cookies»."},
    {"id": "limitacion_publicidad", "titulo": "Limitación: listado de exclusión", "accion": "responder",
     "resultado": "procede", "tipos": ("limitacion",),
     "texto": "Revisamos tu solicitud {folio}. Procede: te incluimos en el listado de exclusión de GuauWoow y no te "
              "enviaremos publicidad por ningún medio mientras no lo retires. Este folio, con su fecha y hora, es tu "
              "constancia. Seguirás recibiendo mensajes que son parte del servicio, como códigos de verificación o recibos."},
    {"id": "sin_datos", "titulo": "No encontramos datos", "accion": "responder", "resultado": "sin_datos",
     "tipos": ARCO_KINDS,
     "texto": "Revisamos tu solicitud {folio} y no encontramos datos personales tuyos con la información que nos diste."},
    {"id": "negativa", "titulo": "Negativa fundada", "accion": "responder", "resultado": "no_procede",
     "tipos": ARCO_KINDS,
     "texto": "Revisamos tu solicitud {folio}. No procede porque [causa del artículo 33 de la LFPDPPP, explicada en "
              "lenguaje claro]."},
    {"id": "queja_respuesta", "titulo": "Respuesta a una queja", "accion": "responder", "resultado": "procede",
     "tipos": ATTENTION_KINDS,
     "texto": "Hola, {nombre}: revisamos tu {tipo} {folio}. [Qué encontramos y qué haremos.]"},
    {"id": "queja_primera", "titulo": "Primera respuesta a una queja", "accion": "primera_respuesta",
     "tipos": ATTENTION_KINDS,
     "texto": "Hola, {nombre}: recibimos tu {tipo} {folio} y ya la estamos revisando. [Primeros pasos.] Te daremos la "
              "respuesta final a más tardar el {fecha_respuesta}."},
    {"id": "retiro_no_procede", "titulo": "Retiro de importado: no procede", "accion": "responder",
     "resultado": "no_procede", "tipos": ("retiro_importado",),
     "texto": "Revisamos tu solicitud {folio} y no encontramos que seas la persona autora de la publicación ni que "
              "aparezcas en ella. Volvimos a mostrarla. Si se trata de un error, responde a este correo con más datos."},
)


def templates_for(req: ComplianceRequest) -> list[dict]:
    values = {
        "nombre": req.name.split()[0] if req.name else "", "folio": req.folio,
        "tipo": KIND_LABELS.get(req.kind, req.kind).lower(), "fecha_respuesta": fecha_es(req.respond_by),
        "permisos": ", ".join(PERMISSIONS.get(p, p).lower() for p in ((req.details or {}).get("permisos") or [])) or "los permisos indicados",
    }
    out = []
    for t in TEMPLATES:
        if req.kind not in t["tipos"]:
            continue
        text = t["texto"]
        for key, value in values.items():
            text = text.replace("{" + key + "}", value)
        out.append({k: v for k, v in t.items() if k not in ("tipos", "texto")} | {"texto": text})
    return out
