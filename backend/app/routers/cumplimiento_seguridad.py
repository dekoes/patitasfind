"""Cumplimiento: seguridad (contratos K-CONSERV y K-ESTADO; L-seguridad).

Público:
- GET /cumplimiento/conservacion: la tabla de conservación vigente (services/retention.py), la misma que aplica la
  purga diaria. La pinta app/legal/js/conservacion.js en conservacion.html (#tabla-conservacion).
- GET /cumplimiento/estado: estado de los servicios, incidentes públicos y mantenimientos (app/legal/js/estado.js).

Panel (admins; las acciones delicadas, superadmin):
- /admin/cumplimiento/incidentes: registro de incidentes (runbook-incidentes.md §10), avisos a personas afectadas con
  las plantillas del §7 y registro de cada envío (usuario, canal, fecha, versión del aviso).
- /admin/cumplimiento/conservacion: tabla completa, últimas corridas y ejecución manual (también en simulación).
- /admin/cumplimiento/mfa: quién tiene la verificación en dos pasos y restablecimiento por un superadmin.
- /admin/cumplimiento/cifrado: estado de la llave y archivos privados aún sin cifrar.
"""
import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import cache
from app.config import settings
from app.database import get_db
from app.dependencies import require_admin, require_superadmin
from app.models import MfaRecoveryCode, PhoneVerificationLog, SecurityIncident, SecurityIncidentNotice, User
from app.services import retention, totp
from app.services.audit import record_admin_action

router = APIRouter(tags=["cumplimiento"])
logger = logging.getLogger(__name__)

ESTADO_CACHE_KEY = "cumplimiento:estado:v1"
ESTADO_TTL = 60
CONSERVACION_CACHE_KEY = "cumplimiento:conservacion:v1"
CONSERVACION_TTL = 600
PUBLIC_INCIDENT_DAYS = 90
MAX_NOTICE_RECIPIENTS = 5000

COMPONENTS = {
    "web": "Sitio y app web",
    "api": "Servidor (API)",
    "base_de_datos": "Base de datos",
    "cola": "Tareas en segundo plano",
    "correo": "Correo",
    "pagos": "Pagos (Mercado Pago)",
    "sms": "Código por SMS",
    "whatsapp": "Asistente de WhatsApp",
    "ia": "Inteligencia artificial",
}
CATEGORIES = ("vulneracion", "disponibilidad", "mantenimiento")
INCIDENT_TYPES = ("perdida", "robo_copia", "uso_no_autorizado", "dano_alteracion", "caida", "credenciales",
                  "aviso_proveedor", "otro")
SEVERITIES = ("S1", "S2", "S3")
STATUSES = ("abierto", "contenido", "cerrado")


def _utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _iso(value: datetime.datetime | None) -> str | None:
    return value.replace(microsecond=0).isoformat() + "Z" if value else None


# =========================================================================== conservación (K-CONSERV)
@router.get("/cumplimiento/conservacion")
def conservacion(db: Session = Depends(get_db)):
    """Tabla de conservación vigente: categoría, plazo, desde cuándo, qué pasa al vencer, fundamento y cómo se aplica."""
    cached = cache.get(CONSERVACION_CACHE_KEY)
    if isinstance(cached, dict):
        return cached
    body = retention.public_table(db)
    cache.set(CONSERVACION_CACHE_KEY, body, ttl=CONSERVACION_TTL)
    return body


@router.get("/admin/cumplimiento/conservacion")
def admin_conservacion(admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import RetentionRun

    runs = db.query(RetentionRun).order_by(RetentionRun.id.desc()).limit(10).all()
    freeze = retention.freeze_status(db)
    return {
        "categorias": retention.categories(),
        "pausada": not settings.retention_purge_enabled or freeze["congelada"],
        "purga_activada": settings.retention_purge_enabled,
        "congelada_por_incidente": freeze["congelada"],
        # Hasta cuándo (tope de 30 días por vez), qué incidentes y qué purgas siguen corriendo durante la pausa
        "congelamiento": {**freeze, "hasta": _iso(freeze["hasta"])},
        "corridas": [{"id": r.id, "inicio": _iso(r.started_at), "fin": _iso(r.finished_at), "estado": r.status,
                      "simulacion": r.dry_run, "resultados": r.results, "error": r.error} for r in runs],
    }


class PurgeRunIn(BaseModel):
    dry_run: bool = True


@router.post("/admin/cumplimiento/conservacion/ejecutar")
def admin_run_purge(payload: PurgeRunIn, request: Request, admin_user: User = Depends(require_superadmin),
                    db: Session = Depends(get_db)):
    """Corre la purga ahora (por defecto en simulación: cuenta lo que borraría sin borrar nada)."""
    record_admin_action(db, admin_user, "retention.run", "retention", None, {"dry_run": payload.dry_run}, request)
    db.commit()
    result = retention.run_purge(db, dry_run=payload.dry_run)
    cache.delete(CONSERVACION_CACHE_KEY)
    return result


# =========================================================================== estado del servicio (K-ESTADO)
def _check_database() -> tuple[str, str | None]:
    from sqlalchemy import text

    from app.database import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "operativo", None
    except Exception:  # noqa: BLE001
        return "interrumpido", "No responde"


def _check_queue() -> tuple[str, str | None]:
    """Redis (cola) y, si hay Celery, que algún worker responda (1 s como máximo; el resultado se guarda 60 s)."""
    if not settings.celery_enabled:
        return "operativo", None
    try:
        r = cache._get_redis()
        if r is None or not r.ping():
            return "interrumpido", "La cola no responde"
    except Exception:  # noqa: BLE001
        return "interrumpido", "La cola no responde"
    try:
        from app.celery_app import celery_app

        replies = celery_app.control.ping(timeout=1.0)
    except Exception:  # noqa: BLE001
        replies = []
    if not replies:
        return "degradado", "Los avisos y las tareas en segundo plano pueden tardar"
    return "operativo", None


def _check_sms(db: Session) -> tuple[str, str | None]:
    if not settings.otp_enabled:
        return "no_configurado", None
    since = _utcnow() - datetime.timedelta(hours=1)
    total, ok = db.query(func.count(PhoneVerificationLog.id),
                         func.count(PhoneVerificationLog.id).filter(PhoneVerificationLog.success.is_(True))).filter(
        PhoneVerificationLog.created_at >= since).one()
    if total >= 5 and ok == 0:
        return "degradado", "Los códigos pueden tardar en llegar"
    return "operativo", None


def _configured(flag: bool, detail_off: str | None = None) -> tuple[str, str | None]:
    return ("operativo", None) if flag else ("no_configurado", detail_off)


def _public_incident(inc: SecurityIncident) -> dict:
    return {
        "folio": inc.folio, "titulo": inc.title, "categoria": inc.category,
        "estado": "resuelto" if inc.status == "cerrado" or (inc.ended_at and inc.ended_at <= _utcnow()) else "en_curso",
        "inicio": _iso(inc.started_at or inc.detected_at), "fin": _iso(inc.ended_at or inc.closed_at),
        "componentes": [c for c in (inc.components or []) if c in COMPONENTS],
        "resumen": inc.public_summary,
    }


def build_status(db: Session) -> dict:
    now = _utcnow()
    checks = {
        "web": ("operativo", None),
        "api": ("operativo", None),
        "base_de_datos": _check_database(),
        "cola": _check_queue(),
        "correo": _configured(settings.smtp_enabled),
        "pagos": _configured(settings.payments_enabled, "Pagos simulados (desarrollo)" if settings.payments_simulated
                             else None),
        "sms": _check_sms(db),
        "whatsapp": _configured(settings.whatsapp_enabled),
        "ia": _configured(settings.ai_enabled),
    }
    componentes = {key: {"nombre": COMPONENTS[key], "estado": state, "detalle": detail}
                   for key, (state, detail) in checks.items()}
    public = db.query(SecurityIncident).filter(SecurityIncident.public.is_(True)).filter(
        func.coalesce(SecurityIncident.started_at, SecurityIncident.detected_at)
        >= now - datetime.timedelta(days=PUBLIC_INCIDENT_DAYS)).order_by(
        func.coalesce(SecurityIncident.started_at, SecurityIncident.detected_at).desc()).limit(50).all()
    incidentes, mantenimientos = [], []
    for inc in public:
        if inc.category == "mantenimiento":
            if inc.started_at and inc.started_at > now:
                mantenimientos.append(_public_incident(inc))
                continue
            active = inc.started_at and inc.started_at <= now and (inc.ended_at is None or inc.ended_at > now)
            if active and inc.status != "cerrado":
                for c in inc.components or []:
                    if c in componentes and componentes[c]["estado"] == "operativo":
                        componentes[c]["estado"], componentes[c]["detalle"] = "mantenimiento", inc.public_summary
        elif inc.status != "cerrado" and (inc.ended_at is None or inc.ended_at > now):
            # Incidente en curso: el componente baja a «degradado» (o «interrumpido» si es S1 o una caída)
            impact = "interrumpido" if inc.severity == "S1" or inc.category == "disponibilidad" else "degradado"
            for c in inc.components or []:
                current = componentes.get(c, {}).get("estado")
                if current == "operativo" or (current == "degradado" and impact == "interrumpido"):
                    componentes[c]["estado"], componentes[c]["detalle"] = impact, inc.public_summary
        incidentes.append(_public_incident(inc))
    states = {c["estado"] for c in componentes.values()}
    if "interrumpido" in {componentes["api"]["estado"], componentes["base_de_datos"]["estado"]}:
        estado = "interrupcion"
    elif "interrumpido" in states or "degradado" in states:
        estado = "degradado"
    elif "mantenimiento" in states:
        estado = "mantenimiento"
    else:
        estado = "operativo"
    return {"estado": estado, "actualizado": _iso(now), "componentes": componentes,
            "incidentes": incidentes[:20], "mantenimientos": sorted(mantenimientos, key=lambda m: m["inicio"] or "")}


@router.get("/cumplimiento/estado")
def estado(db: Session = Depends(get_db)):
    """Tablero de estado: {estado, componentes{web, api, base_de_datos, cola, correo, pagos, sms, whatsapp, ia},
    incidentes[], mantenimientos[]}. Solo resúmenes públicos; se calcula como máximo cada 60 s."""
    cached = cache.get(ESTADO_CACHE_KEY)
    if isinstance(cached, dict):
        return cached
    body = build_status(db)
    cache.set(ESTADO_CACHE_KEY, body, ttl=ESTADO_TTL)
    return body


# =========================================================================== registro de incidentes
class IncidentIn(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    category: str | None = None
    incident_type: str | None = None
    severity: str | None = None
    status: str | None = None
    detection_source: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=10000)
    systems_affected: list[str] | None = Field(None, max_length=30)
    data_categories: list[str] | None = Field(None, max_length=30)
    components: list[str] | None = Field(None, max_length=len(COMPONENTS))
    affected_count: int | None = Field(None, ge=0)
    significant_impact: bool | None = None
    significant_impact_reason: str | None = Field(None, max_length=5000)
    contractual_notices: list[dict] | None = Field(None, max_length=20)
    authority_report: dict | None = None
    sabg_notified: bool | None = None
    root_cause: str | None = Field(None, max_length=10000)
    immediate_actions: str | None = Field(None, max_length=10000)
    definitive_actions: str | None = Field(None, max_length=10000)
    evidence_ref: str | None = Field(None, max_length=500)
    freeze_purges: bool | None = None
    renew_freeze: bool | None = None  # solo superadmin: otros 30 días de congelamiento de purgas
    detected_at: datetime.datetime | None = None
    confirmed_at: datetime.datetime | None = None
    contained_at: datetime.datetime | None = None
    closed_at: datetime.datetime | None = None
    started_at: datetime.datetime | None = None
    ended_at: datetime.datetime | None = None
    public: bool | None = None
    public_summary: str | None = Field(None, max_length=1000)
    lead_id: int | None = None
    note: str | None = Field(None, max_length=2000)  # entrada de la línea de tiempo


def _naive(value):
    if isinstance(value, datetime.datetime) and value.tzinfo is not None:
        return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return value


def _validate_incident(data: dict) -> None:
    if data.get("category") is not None and data["category"] not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Categoría no válida: vulneracion, disponibilidad o mantenimiento.")
    if data.get("incident_type") is not None and data["incident_type"] not in INCIDENT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de incidente no válido.")
    if data.get("severity") is not None and data["severity"] not in SEVERITIES:
        raise HTTPException(status_code=400, detail="Severidad no válida: S1, S2 o S3.")
    if data.get("status") is not None and data["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail="Estado no válido: abierto, contenido o cerrado.")
    bad = [c for c in (data.get("components") or []) if c not in COMPONENTS]
    if bad:
        raise HTTPException(status_code=400, detail=f"Componente no válido: {bad[0]}.")


def _incident_out(inc: SecurityIncident, db: Session | None = None) -> dict:
    out = {c.name: getattr(inc, c.name) for c in SecurityIncident.__table__.columns}
    for key, value in list(out.items()):
        if isinstance(value, datetime.datetime):
            out[key] = _iso(value)
    until = retention.freeze_until(inc)
    out["purges_frozen"] = bool(until and until > _utcnow())
    out["freeze_expired"] = bool(until and until <= _utcnow())
    out["freeze_until"] = _iso(until)
    if db is not None:
        rows = db.query(SecurityIncidentNotice.channel, SecurityIncidentNotice.status,
                        func.count(SecurityIncidentNotice.id)).filter(
            SecurityIncidentNotice.incident_id == inc.id).group_by(
            SecurityIncidentNotice.channel, SecurityIncidentNotice.status).all()
        out["notices_sent"] = [{"channel": ch, "status": st, "count": n} for ch, st, n in rows]
    return out


def _bust_status_cache() -> None:
    cache.delete(ESTADO_CACHE_KEY, CONSERVACION_CACHE_KEY)


@router.get("/admin/cumplimiento/incidentes")
def list_incidents(status: str | None = Query(None), skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                   admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = db.query(SecurityIncident)
    if status in STATUSES:
        query = query.filter(SecurityIncident.status == status)
    elif status == "activos":
        query = query.filter(SecurityIncident.status != "cerrado")
    rows = query.order_by(SecurityIncident.detected_at.desc(), SecurityIncident.id.desc()).offset(skip).limit(limit).all()
    return [_incident_out(r) for r in rows]


@router.post("/admin/cumplimiento/incidentes", status_code=201)
def create_incident(payload: IncidentIn, request: Request, admin_user: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    """Abre un incidente (hora 0 del runbook). Por defecto congela las purgas automáticas hasta cerrarlo."""
    data = {k: _naive(v) for k, v in payload.model_dump(exclude_unset=True).items()}
    note = data.pop("note", None)
    if not data.get("title"):
        raise HTTPException(status_code=400, detail="Escribe un título para el incidente.")
    _validate_incident(data)
    data.setdefault("status", "abierto")
    data.setdefault("category", "vulneracion")
    if data.get("public") and not (data.get("public_summary") or "").strip():
        raise HTTPException(status_code=400, detail="Para publicarlo en el tablero escribe el resumen público.")
    now = _utcnow()
    inc = SecurityIncident(**data, created_by_id=admin_user.id)
    if inc.detected_at is None:
        inc.detected_at = now
    data.pop("renew_freeze", None)
    if inc.category == "mantenimiento" and "freeze_purges" not in data:
        inc.freeze_purges = False  # un mantenimiento programado no es una investigación
    if inc.freeze_purges:
        inc.freeze_purges_until = now + datetime.timedelta(days=retention.FREEZE_MAX_DIAS)
    inc.timeline = [{"at": _iso(now), "by": admin_user.id, "text": note or "Incidente registrado"}]
    db.add(inc)
    db.flush()
    inc.folio = f"INC-{inc.detected_at.year}-{inc.id:04d}"
    record_admin_action(db, admin_user, "incident.create", "security_incident", inc.id,
                        {"folio": inc.folio, "severity": inc.severity, "category": inc.category}, request)
    db.commit()
    db.refresh(inc)
    _bust_status_cache()
    return _incident_out(inc, db)


FREEZE_RENEW_SUPERADMIN = ("Solo un superadmin puede renovar el congelamiento de las purgas (dura "
                           f"{retention.FREEZE_MAX_DIAS} días por vez).")


def _freeze_change(inc: SecurityIncident, data: dict, renew: bool, admin_user: User,
                   now: datetime.datetime) -> str | None:
    """Tope del congelamiento de purgas: 30 días desde que se activa; otros 30 solo con un superadmin (renovar o
    volver a activarlo ya vencido). Devuelve la nota para la línea de tiempo o None."""
    wants = data.get("freeze_purges", inc.freeze_purges)
    if not wants:
        return None
    until = inc.freeze_purges_until or (retention.freeze_until(inc) if inc.freeze_purges else None)
    turning_on = "freeze_purges" in data and data["freeze_purges"] and not inc.freeze_purges
    expired = until is not None and until <= now
    if renew or (turning_on and expired):
        if admin_user.role != "superadmin":
            raise HTTPException(status_code=403, detail=FREEZE_RENEW_SUPERADMIN)
    elif turning_on and until is None:
        pass  # primera vez: cualquier admin
    else:
        return None
    inc.freeze_purges_until = now + datetime.timedelta(days=retention.FREEZE_MAX_DIAS)
    return f"Purgas congeladas hasta el {inc.freeze_purges_until.date().isoformat()} (tope de {retention.FREEZE_MAX_DIAS} días)"


def _get_incident(db: Session, id: int) -> SecurityIncident:
    inc = db.query(SecurityIncident).filter(SecurityIncident.id == id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="No encontramos ese incidente.")
    return inc


@router.get("/admin/cumplimiento/incidentes/{id}")
def get_incident(id: int, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _incident_out(_get_incident(db, id), db)


@router.patch("/admin/cumplimiento/incidentes/{id}")
def update_incident(id: int, payload: IncidentIn, request: Request, admin_user: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    inc = _get_incident(db, id)
    data = {k: _naive(v) for k, v in payload.model_dump(exclude_unset=True).items()}
    note = data.pop("note", None)
    renew = bool(data.pop("renew_freeze", None))
    _validate_incident(data)
    if "title" in data and not data["title"]:
        raise HTTPException(status_code=400, detail="El incidente necesita un título.")
    now = _utcnow()
    freeze_note = _freeze_change(inc, data, renew, admin_user, now)
    new_status = data.get("status", inc.status)
    if new_status == "cerrado" and inc.status != "cerrado" and (data.get("category") or inc.category) == "vulneracion":
        # Runbook §9 y §6: no se cierra sin causa raíz ni sin decidir (y razonar) si hubo afectación significativa
        root = data.get("root_cause", inc.root_cause)
        impact = data.get("significant_impact", inc.significant_impact)
        reason = data.get("significant_impact_reason", inc.significant_impact_reason)
        if not (root or "").strip() or impact is None or not (reason or "").strip():
            raise HTTPException(status_code=400, detail="Para cerrar una vulneración registra la causa raíz y la "
                                                        "decisión sobre la afectación significativa con su razón.")
    public = data.get("public", inc.public)
    summary = data.get("public_summary", inc.public_summary)
    if public and not (summary or "").strip():
        raise HTTPException(status_code=400, detail="Para publicarlo en el tablero escribe el resumen público.")
    changed = {}
    for key, value in data.items():
        if getattr(inc, key) != value:
            changed[key] = value if not isinstance(value, datetime.datetime) else _iso(value)
            setattr(inc, key, value)
    if new_status == "contenido" and inc.contained_at is None:
        inc.contained_at = now
    if new_status == "cerrado" and inc.closed_at is None:
        inc.closed_at = now
    if new_status != "cerrado" and "status" in changed:
        inc.closed_at = None
    if freeze_note:
        changed["freeze_purges_until"] = _iso(inc.freeze_purges_until)
        inc.timeline = [*(inc.timeline or []), {"at": _iso(now), "by": admin_user.id, "text": freeze_note}]
    if changed or note:
        text = note or ("Cambio de estado a «" + new_status + "»" if "status" in changed else "Registro actualizado")
        inc.timeline = [*(inc.timeline or []), {"at": _iso(now), "by": admin_user.id, "text": text}]
        record_admin_action(db, admin_user, "incident.update", "security_incident", inc.id,
                            {"folio": inc.folio, "changed": sorted(changed)}, request)
    db.commit()
    db.refresh(inc)
    _bust_status_cache()
    return _incident_out(inc, db)


# --------------------------------------------------------------------------- avisos a personas afectadas (§7)
class NoticeIn(BaseModel):
    resumen: str = Field(..., min_length=3, max_length=200)  # va en el asunto: «Aviso de seguridad: ...»
    fecha: str = Field(..., min_length=3, max_length=60)  # «17 de octubre de 2026»
    que_paso: str = Field(..., min_length=3, max_length=2000)
    datos: str = Field(..., min_length=3, max_length=1000)  # datos afectados, lista exacta
    no_afectados: str | None = Field(None, max_length=1000)
    acciones: str = Field(..., min_length=3, max_length=2000)
    recomendaciones: str = Field(..., min_length=3, max_length=2000)
    mas_info: str | None = Field(None, max_length=500)  # enlace al aviso completo


class NoticeSendIn(BaseModel):
    notice: NoticeIn
    user_ids: list[int] | None = Field(None, max_length=MAX_NOTICE_RECIPIENTS)
    emails: list[str] | None = Field(None, max_length=MAX_NOTICE_RECIPIENTS)
    all_users: bool = False  # toda la base de cuentas activas (solo superadmin)


def render_notice(notice: dict, name: str | None = None) -> dict:
    """Plantillas del runbook §7.1 (correo) y §7.2 (app). Cinco elementos: qué pasó, qué datos, qué hicimos, qué
    recomendamos y dónde informarse."""
    more = notice.get("mas_info") or settings.public_url("/app/legal/seguridad.html")
    contact = settings.support_email or "el correo de privacidad del Aviso de Privacidad"
    not_affected = (notice.get("no_afectados") or "").strip()
    email_body = (
        f"Hola, {name or ''}:\n\n"
        "Te escribimos porque detectamos un incidente de seguridad que puede afectarte y queremos que lo sepas de "
        "inmediato.\n\n"
        f"1. Qué pasó. El {notice['fecha']} {notice['que_paso']}\n\n"
        f"2. Qué datos se vieron afectados. {notice['datos']}"
        + (f" No se vieron afectados: {not_affected}" if not_affected else "") + "\n\n"
        f"3. Qué hicimos. {notice['acciones']}\n\n"
        f"4. Qué te recomendamos. {notice['recomendaciones']} GuauWoow nunca te pedirá tu código de verificación "
        "ni tu contraseña.\n\n"
        f"5. Dónde obtener más información. Escríbenos a {contact} o consulta {more}. Puedes ejercer tus derechos de "
        "acceso, rectificación, cancelación y oposición conforme a nuestro Aviso de Privacidad.\n\n"
        "Lamentamos lo ocurrido.\nEquipo de GuauWoow"
    )
    app_body = (f"El {notice['fecha']} detectamos {notice['resumen']}. Pudo afectar {notice['datos']}. "
                f"Ya {notice['acciones']} Te recomendamos {notice['recomendaciones']} Más información: {more}")
    return {"email_subject": f"Aviso de seguridad: {notice['resumen']}", "email_body": email_body,
            "app_title": "Aviso de seguridad", "app_body": " ".join(app_body.split()), "url": more}


@router.post("/admin/cumplimiento/incidentes/{id}/avisos/vista-previa")
def preview_notice(id: int, payload: NoticeIn, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    _get_incident(db, id)
    return render_notice(payload.model_dump(), "Nombre de la persona")


@router.post("/admin/cumplimiento/incidentes/{id}/avisos")
def send_notice(id: int, payload: NoticeSendIn, request: Request, admin_user: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    """Avisa a las personas afectadas por correo y en la app (LFPDPPP art. 19) y registra cada envío.

    Reenviar el mismo aviso no duplica: a quien ya recibió esta versión no se le vuelve a mandar. Con all_users se
    envía a lo más MAX_NOTICE_RECIPIENTS cuentas por llamada, en orden, saltando en SQL a quien ya lo recibió;
    "pendientes" dice cuántas faltan (se vuelve a llamar con el mismo aviso hasta que sea 0).
    """
    from app.services import notify

    from sqlalchemy import exists, or_

    inc = _get_incident(db, id)
    if payload.all_users and admin_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Solo un superadmin puede avisar a todas las cuentas.")
    notice = payload.notice.model_dump()
    if inc.notice != notice:
        inc.notice = notice
        inc.notice_version = (inc.notice_version or 0) + 1
    version = inc.notice_version or 1
    inc.notice_version = version
    # Quien ya recibió esta versión se descarta en SQL ANTES del tope: cada envío avanza con las siguientes cuentas
    notified = exists().where(SecurityIncidentNotice.incident_id == inc.id,
                              SecurityIncidentNotice.notice_version == version,
                              SecurityIncidentNotice.user_id == User.id)
    query = db.query(User).filter(User.is_active.is_(True), User.deleted_at.is_(None))
    if payload.all_users:
        pending_query = query.filter(~notified)
        total_pending = pending_query.count()
        recipients = pending_query.order_by(User.id).limit(MAX_NOTICE_RECIPIENTS).all()
        skipped = query.count() - total_pending
    else:
        ids = set(payload.user_ids or [])
        emails = {e.strip().lower() for e in (payload.emails or []) if e and e.strip()}
        if not ids and not emails:
            raise HTTPException(status_code=400, detail="Indica a quién avisar (cuentas o correos afectados).")
        conds = []
        if ids:
            conds.append(User.id.in_(ids))
        if emails:
            conds.append(func.lower(User.email).in_(emails))
        targeted = query.filter(or_(*conds))
        recipients = targeted.filter(~notified).order_by(User.id).all()
        total_pending = len(recipients)
        skipped = targeted.count() - total_pending
    sent = {"app": 0, "email": 0, "sin_correo": 0, "omitidos": skipped,
            "pendientes": max(0, total_pending - len(recipients))}
    now = _utcnow()
    for user in recipients:
        texts = render_notice(notice, user.full_name)
        notify.notify_user(db, user, "security_incident", title=texts["app_title"], body=texts["app_body"],
                           url="/app/legal/seguridad.html", data={"incident": inc.folio, "version": version},
                           commit=False)
        db.add(SecurityIncidentNotice(incident_id=inc.id, user_id=user.id, channel="app", notice_version=version,
                                      sent_at=now, sent_by_id=admin_user.id))
        sent["app"] += 1
        if notify.can_email(user):
            notify._dispatch("app.tasks.notifications.send_notification_email", user.email,
                             texts["email_subject"], texts["email_body"], None)
            status = "enviado"
            sent["email"] += 1
        else:
            status = "sin_correo"
            sent["sin_correo"] += 1
        db.add(SecurityIncidentNotice(incident_id=inc.id, user_id=user.id, channel="email", notice_version=version,
                                      status=status, sent_at=now, sent_by_id=admin_user.id))
    left = f"; faltan {sent['pendientes']}" if sent["pendientes"] else ""
    inc.timeline = [*(inc.timeline or []), {"at": _iso(now), "by": admin_user.id,
                                            "text": f"Aviso v{version} enviado a {sent['app']} persona(s){left}"}]
    record_admin_action(db, admin_user, "incident.notify", "security_incident", inc.id,
                        {"folio": inc.folio, "version": version, **sent}, request)
    db.commit()
    return {"ok": True, "version": version, **sent}


# =========================================================================== MFA y cifrado (panel)
@router.get("/admin/cumplimiento/mfa")
def admin_mfa_list(admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Personal administrador y su verificación en dos pasos (sin secretos)."""
    admins = db.query(User).filter(User.role.in_(totp.ADMIN_ROLES), User.deleted_at.is_(None)).order_by(User.id).all()
    left = dict(db.query(MfaRecoveryCode.user_id, func.count(MfaRecoveryCode.id)).filter(
        MfaRecoveryCode.used_at.is_(None)).group_by(MfaRecoveryCode.user_id).all())
    return {"required": totp.mfa_required(), "admins": [
        {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
         "mfa_enabled": totp.user_has_mfa(u), "mfa_enabled_at": _iso(u.mfa_enabled_at),
         "recovery_codes_left": int(left.get(u.id, 0))} for u in admins]}


@router.post("/admin/cumplimiento/mfa/{user_id}/reset")
def admin_mfa_reset(user_id: int, request: Request, admin_user: User = Depends(require_superadmin),
                    db: Session = Depends(get_db)):
    """Restablece la MFA de otro admin (teléfono perdido): la tendrá que configurar al volver a entrar."""
    from app.routers.auth import revoke_sessions
    from app.utils.notifications import create_notification

    if user_id == admin_user.id:
        raise HTTPException(status_code=400, detail="No puedes restablecer tu propia verificación en dos pasos: "
                                                    "pídeselo a otro superadmin o usa el comando reset-mfa.")
    target = db.query(User).filter(User.id == user_id, User.role.in_(totp.ADMIN_ROLES)).first()
    if not target:
        raise HTTPException(status_code=404, detail="No encontramos esa cuenta de administración.")
    target.mfa_secret_enc = None
    target.mfa_pending_secret_enc = None
    target.mfa_enabled_at = None
    target.mfa_last_step = None
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == target.id).delete(synchronize_session=False)
    revoke_sessions(target)
    record_admin_action(db, admin_user, "auth.mfa_reset", "user", target.id, {"email": target.email}, request)
    create_notification(db, user_id=target.id, type="security", title="Restablecimos tu verificación en dos pasos",
                        body="Un superadmin restableció tu verificación en dos pasos y cerró tus sesiones. Al volver a "
                             "entrar al panel tendrás que configurarla de nuevo.", commit=False)
    db.commit()
    return {"ok": True}


@router.get("/admin/cumplimiento/cifrado")
def admin_encryption_status(admin_user: User = Depends(require_admin)):
    """Llave de cifrado (solo su id) y cuántos archivos privados siguen en claro."""
    from app.routers.documents import private_dir
    from app.services import crypto_storage

    status = crypto_storage.encryption_status()
    plain = total = 0
    for path in private_dir().rglob("*"):
        if not path.is_file() or path.name.startswith(".tmp-"):
            continue
        total += 1
        try:
            with path.open("rb") as fh:
                plain += int(not crypto_storage.is_encrypted(fh.read(len(crypto_storage.MAGIC))))
        except OSError:
            continue
        if total >= 20000:
            break
    return {**status, "private_files": total, "plaintext_files": plain,
            "command": "python -m app.cli encrypt-private-files" if plain else None}
