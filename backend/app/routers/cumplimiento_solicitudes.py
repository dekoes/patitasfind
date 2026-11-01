"""Centro de solicitudes (contrato K-SOLIC): formulario con o sin cuenta, confirmación por correo, seguimiento por
folio y cola del equipo con semáforo de plazos. La lógica vive en services/solicitudes.py.

Público (sin cuenta; con sesión se liga a la cuenta):
- GET  /cumplimiento/solicitudes/opciones            tipos, permisos, motivos y plazos para el formulario
- POST /cumplimiento/solicitudes                     -> {folio, responde_antes_de, ...}
- POST /cumplimiento/solicitudes/confirmar {token}   enlace del correo (comprueba que controla ese correo)
- GET  /cumplimiento/solicitudes/mias                «Mis solicitudes» (con sesión)
- GET  /cumplimiento/solicitudes/{folio}?email=      historial de estados (sin datos personales)
- GET  /cumplimiento/solicitudes/{folio}/acceso?clave=      qué falta (información, identificación, descarga)
- POST /cumplimiento/solicitudes/{folio}/respuesta   (multipart: clave, mensaje, archivo) contestar o adjuntar
- GET  /cumplimiento/solicitudes/{folio}/descarga?clave=    archivo de «Mis datos» (acceso que procede)
Equipo (/admin/cumplimiento/solicitudes...): cola, detalle con plantillas, acciones, alta manual e identificación.
"""
import datetime
import hashlib
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import client_ip, get_current_user, get_optional_user, require_admin
from app.models import ComplianceRequest, LostReport, User
from app.schemas import SolicitudAcuse, SolicitudAdminAccion, SolicitudAdminCreate, SolicitudConfirmar, SolicitudCreate
from app.services import ratelimit
from app.services import solicitudes as sol
from app.services.audit import record_admin_action

router = APIRouter(tags=["cumplimiento"])
logger = logging.getLogger(__name__)

CREATE_PER_HOUR_IP = 5
CREATE_PER_DAY_IP = 20
CREATE_PER_DAY_USER = 10
CREATE_PER_DAY_EMAIL = 5  # sin cuenta: acuses a una misma dirección (que nadie llene el buzón de un tercero)
LOOKUPS_PER_HOUR_IP = 30
MAX_ATTACHMENT_MB = 10
NOT_FOUND = "No encontramos una solicitud con ese folio y ese correo."


def _raise(err: sol.SolicitudError):
    raise HTTPException(status_code=err.status_code, detail=err.detail)


def _details(p: SolicitudCreate) -> dict:
    """Campos propios de cada tipo (lo demás se ignora)."""
    if p.tipo == "retiro_importado":
        return {"relacion": p.relacion}
    if p.tipo in ("revocacion", "limitacion"):
        return {"permisos": sorted(set(p.permisos))}
    if p.tipo == "cancelacion":
        return {"alcance": p.alcance or "datos"}
    if p.tipo == "acceso":
        return {"publicidad": p.publicidad}
    if p.tipo in ("queja", "aclaracion"):
        return {"motivo": p.motivo or "otro"}
    return {}


def _check_kind_fields(p: SolicitudCreate) -> None:
    if p.tipo in ("revocacion", "limitacion") and not p.permisos:
        raise HTTPException(status_code=400, detail="Elige qué permiso retiras o qué uso quieres limitar.")
    if p.tipo == "queja" and not p.motivo:
        raise HTTPException(status_code=400, detail="Elige el tema de tu queja.")
    if p.tipo == "retiro_importado" and not p.relacion:
        raise HTTPException(status_code=400, detail="Dinos tu relación con la publicación.")


def _acuse(req: ComplianceRequest) -> SolicitudAcuse:
    hidden = None
    if req.kind == "retiro_importado":
        relation = (req.details or {}).get("relacion")
        found = req.lost_report_id is not None
        # Se oculta al momento si la pide la persona autora o quien aparece; «otro» solo entra a la cola
        hidden = found and relation in sol.IMPORTED_HIDE_RELATIONS
        if hidden and relation == "autor":
            text = ("Ya ocultamos la publicación y borraremos su texto y sus fotos en menos de 72 horas."
                    if req.identity_verified_at is not None else
                    "Ya ocultamos la publicación. En cuanto confirmes tu correo, borraremos su texto y sus fotos en "
                    "menos de 72 horas.")
        elif hidden:
            text = "Ya ocultamos la publicación mientras atendemos tu solicitud."
        elif found:
            text = "La revisaremos y te responderemos."
        else:
            text = "Todavía no encontramos esa publicación en GuauWoow; la buscaremos y te escribiremos."
        msg = f"Recibimos tu solicitud. Tu folio es {req.folio}. " + text
    else:
        msg = (f"Recibimos tu solicitud. Tu folio es {req.folio} y te enviamos el acuse por correo. "
               f"Te responderemos a más tardar el {sol.fecha_es(req.respond_by)}.")
    needs_confirm = req.identity_verified_at is None and bool(req.confirm_token_hash)
    if needs_confirm:
        msg += " Abre el enlace que te enviamos por correo para confirmar que eres tú."
    return SolicitudAcuse(
        folio=req.folio, tipo=req.kind, estado=req.status, recibida_en=req.received_at,
        responde_antes_de=req.respond_by,
        primera_respuesta_antes_de=req.first_response_due_at if req.kind in sol.ATTENTION_KINDS else None,
        requiere_confirmacion=needs_confirm, publicacion_oculta=hidden, mensaje=msg,
    )


# --------------------------------------------------------------------------- público
@router.get("/cumplimiento/solicitudes/opciones")
def solicitud_options():
    """Etiquetas y plazos vigentes para que el formulario diga lo mismo que el servidor."""
    return {
        "tipos": sol.KIND_LABELS, "permisos": sol.PERMISSIONS, "alcances": sol.CANCEL_SCOPES,
        "motivos": sol.COMPLAINT_TOPICS, "relaciones": sol.REMOVAL_RELATIONS, "estados": sol.STATUS_LABELS,
        "plazos": {
            "arco_respuesta_dias_habiles": sol.ARCO_RESPONSE_DAYS, "arco_efectiva_dias_habiles": sol.ARCO_EFFECTIVE_DAYS,
            "queja_primera_respuesta_dias_habiles": settings.complaint_first_response_business_days,
            "queja_respuesta_dias_habiles": settings.complaint_response_business_days,
            "retiro_importado_horas": sol.IMPORTED_AUTHOR_HOURS,
            "confirmacion_dias_habiles": sol.CONFIRM_DAYS,
        },
    }


@router.post("/cumplimiento/solicitudes", response_model=SolicitudAcuse, status_code=status.HTTP_201_CREATED)
def create_request(payload: SolicitudCreate, request: Request, response: Response,
                   current_user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """Presenta una solicitud. Sin cuenta se confirma con el enlace que llega al correo."""
    if (payload.website or "").strip():
        raise HTTPException(status_code=400, detail="No pudimos procesar tu solicitud.")
    ip = client_ip(request)
    if current_user:
        ratelimit.check(f"solicitud:user:{current_user.id}", CREATE_PER_DAY_USER, 86_400,
                        detail="Enviaste muchas solicitudes hoy. Inténtalo mañana o escríbenos al correo de privacidad.")
    else:
        if payload.acepta_privacidad is not True:
            raise HTTPException(status_code=400, detail="Acepta el Aviso de Privacidad para enviar tu solicitud.")
        ratelimit.check(f"solicitud:ip:h:{ip}", CREATE_PER_HOUR_IP, 3600,
                        detail="Enviaste varias solicitudes seguidas. Espera una hora o escríbenos al correo de privacidad.")
        ratelimit.check(f"solicitud:ip:d:{ip}", CREATE_PER_DAY_IP, 86_400,
                        detail="Llegaste al límite de solicitudes por hoy. Escríbenos al correo de privacidad.")
        if payload.email:
            key = hashlib.sha256(sol.normalize_email(payload.email).encode()).hexdigest()[:32]
            ratelimit.check(f"solicitud:email:d:{key}", CREATE_PER_DAY_EMAIL, 86_400,
                            detail="Ya recibimos varias solicitudes con ese correo hoy. Revisa tu bandeja o escríbenos "
                                   "al correo de privacidad.")
    _check_kind_fields(payload)
    try:
        req = sol.create_solicitud(
            db, kind=payload.tipo, name=payload.nombre, email=payload.email, phone=payload.telefono,
            description=payload.descripcion, user=current_user, channel="app" if current_user else "web",
            details=_details(payload), report_id=payload.report_id, report_url=payload.enlace,
            order_id=payload.pedido_id, document_id=payload.documento_id, acting_as=payload.actua_como,
            holder_name=payload.nombre_titular, ip=ip, user_agent=request.headers.get("user-agent"),
        )
    except sol.SolicitudError as err:
        db.rollback()
        _raise(err)
    if getattr(req, "_duplicate", False):
        response.status_code = status.HTTP_200_OK
    return _acuse(req)


@router.post("/cumplimiento/solicitudes/confirmar")
def confirm_request(payload: SolicitudConfirmar, request: Request, db: Session = Depends(get_db)):
    ratelimit.check(f"solicitud:confirm:{client_ip(request)}", LOOKUPS_PER_HOUR_IP, 3600,
                    detail="Demasiados intentos. Espera un rato e inténtalo de nuevo.")
    try:
        req = sol.confirm(db, payload.token)
    except sol.SolicitudError as err:
        db.rollback()
        _raise(err)
    return sol.public_view(req)


@router.get("/cumplimiento/solicitudes/mias")
def my_requests(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """«Mis solicitudes»: las presentadas con la sesión iniciada o confirmadas desde el correo de la cuenta."""
    return [sol.public_view(r, owner=True) for r in sol.list_for_user(db, current_user)]


@router.get("/cumplimiento/solicitudes/{folio}")
def track_request(folio: str, request: Request, email: str | None = Query(None, max_length=255),
                  current_user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """Seguimiento por folio y correo: estados, fechas y plazos (la respuesta completa llega al correo)."""
    ratelimit.check(f"solicitud:track:{client_ip(request)}", LOOKUPS_PER_HOUR_IP, 3600,
                    detail="Hiciste muchas consultas seguidas. Espera un rato e inténtalo de nuevo.")
    req = sol.get_by_folio(db, folio)
    if req is not None and current_user is not None and req.user_id == current_user.id:
        return sol.public_view(req, owner=True)
    req = sol.find_for_tracking(db, folio, email)
    if req is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return sol.public_view(req)


def _requester_access(db: Session, folio: str, clave: str | None, user: User | None, lock: bool = False) -> ComplianceRequest:
    """Quien presentó la solicitud: con el enlace del correo (clave) o con la sesión de la cuenta ligada."""
    if user is not None:
        req = sol.get_by_folio(db, folio, lock=lock)
        if req is not None and req.user_id == user.id:
            return req
    try:
        return sol.access_by_token(db, folio, clave, lock=lock)
    except sol.SolicitudError as err:
        _raise(err)


@router.get("/cumplimiento/solicitudes/{folio}/acceso")
def requester_access(folio: str, request: Request, clave: str | None = Query(None, max_length=200),
                     current_user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    ratelimit.check(f"solicitud:access:{client_ip(request)}", LOOKUPS_PER_HOUR_IP, 3600,
                    detail="Hiciste muchas consultas seguidas. Espera un rato e inténtalo de nuevo.")
    req = _requester_access(db, folio, clave, current_user)
    asked = next((e.public_note for e in reversed(req.events) if e.kind == "requerimiento"), None)
    return {**sol.public_view(req), "pendiente": sol.pending_actions(req), "lo_que_pedimos": asked}


@router.post("/cumplimiento/solicitudes/{folio}/respuesta")
def requester_reply(folio: str, request: Request, clave: str | None = Form(None), mensaje: str = Form(""),
                    archivo: UploadFile | None = File(None), current_user: User | None = Depends(get_optional_user),
                    db: Session = Depends(get_db)):
    """Contestar un requerimiento, subir la identificación que pedimos o escribirnos de nuevo."""
    ratelimit.check(f"solicitud:reply:{client_ip(request)}", 10, 3600,
                    detail="Enviaste varias respuestas seguidas. Espera un rato e inténtalo de nuevo.")
    req = _requester_access(db, folio, clave, current_user, lock=True)
    data = None
    if archivo is not None and archivo.filename:
        data = archivo.file.read(MAX_ATTACHMENT_MB * 1024 * 1024 + 1)
    try:
        req = sol.requester_reply(db, req, mensaje, data)
    except sol.SolicitudError as err:
        db.rollback()
        _raise(err)
    return sol.public_view(req, owner=req.user_id is not None and current_user is not None and req.user_id == current_user.id)


@router.get("/cumplimiento/solicitudes/{folio}/descarga")
def requester_download(folio: str, request: Request, clave: str | None = Query(None, max_length=200),
                       current_user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """Derecho de acceso que procede: el mismo archivo de «Descargar mis datos» de la cuenta ligada."""
    ratelimit.check(f"solicitud:download:{client_ip(request)}", 10, 3600,
                    detail="Descargaste varias veces seguidas. Espera un rato e inténtalo de nuevo.")
    req = _requester_access(db, folio, clave, current_user)
    if not sol.pending_actions(req)["descarga"]:
        raise HTTPException(status_code=409, detail="Esta solicitud no tiene una descarga disponible.")
    try:
        return sol.build_export(db, req)
    except sol.SolicitudError as err:
        _raise(err)


# --------------------------------------------------------------------------- equipo
def _admin_item(req: ComplianceRequest, now: datetime.datetime) -> dict:
    return {
        "folio": req.folio, "tipo": req.kind, "tipo_texto": sol.KIND_LABELS.get(req.kind, req.kind),
        "estado": req.status, "estado_texto": sol.STATUS_LABELS.get(req.status, req.status),
        "resultado": req.outcome, "nombre": req.name, "email": req.email, "telefono": req.phone,
        "canal": req.channel, "recibida_en": req.received_at, "responde_antes_de": req.respond_by,
        "efectiva_antes_de": req.effective_by, "sla": sol.sla(req, now),
        "identidad_confirmada": req.identity_verified_at is not None, "con_cuenta": req.user_id is not None,
        "asignada_a": req.assigned_to.full_name if req.assigned_to else None,
        "esperando_titular": sol.waiting_on_requester(req),
    }


def _admin_detail(db: Session, req: ComplianceRequest) -> dict:
    now = sol.utcnow()
    user = req.user
    report = db.get(LostReport, req.lost_report_id) if req.lost_report_id else None
    return {
        **_admin_item(req, now),
        "descripcion": req.description, "detalles": req.details or {}, "actua_como": req.acting_as,
        "nombre_titular": req.holder_name, "respuesta": req.response_text, "motivo_negativa": req.denial_reason,
        "metodo_identidad": req.identity_method, "identidad_en": req.identity_verified_at,
        # Efectos sobre WhatsApp: solo con el número comprobado (desde el bot o teléfono verificado de la cuenta)
        "telefono_comprobado": sol.proven_whatsapp_phone(req, user) is not None,
        "identificacion": {
            "pedida_en": req.id_document_requested_at, "subida_en": req.id_document_uploaded_at,
            "disponible": bool(req.id_document_id), "borrada_en": req.id_document_purged_at,
            "sha256": req.id_document_sha256,
        },
        "primera_respuesta_antes_de": req.first_response_due_at, "primera_respuesta_en": req.first_response_at,
        "requerimiento": {"pedido_en": req.info_requested_at, "vence": req.info_due_at, "recibido_en": req.info_received_at},
        "ampliacion": {"respuesta": req.respond_extended_at, "efectiva": req.effective_extended_at,
                       "motivo": req.extension_reason},
        "respondida_en": req.responded_at, "efectiva_en": req.effective_at, "cerrada_en": req.closed_at,
        "cuenta": ({"id": user.id, "email": user.email, "nombre": user.full_name, "activa": user.is_active,
                    "correo_verificado": bool(user.email_verified), "rol": user.role} if user else None),
        "reporte": ({"id": report.id, "nombre": report.dog_name, "fuente": report.source, "oculto": report.is_hidden,
                     "borrado_en": report.purged_at, "enlace_original": report.external_url} if report else None),
        "pedido_id": req.order_id, "content_report_id": req.content_report_id,
        "historial": [{"tipo": e.kind, "texto": sol.EVENT_LABELS.get(e.kind, e.kind), "estado": e.status,
                       "fecha": e.created_at, "nota_publica": e.public_note, "nota_interna": e.internal_note,
                       "por": e.actor.full_name if e.actor else None} for e in req.events],
        "plantillas": sol.templates_for(req),
        "acciones": _allowed_actions(req),
    }


def _allowed_actions(req: ComplianceRequest) -> list[str]:
    if req.status in sol.FINAL_STATUSES:
        return ["nota"]
    actions = []
    if req.status == "recibida":
        actions.append("en_revision")
    if req.kind in sol.ATTENTION_KINDS and not req.first_response_at:
        actions.append("primera_respuesta")
    if not req.info_requested_at and req.status in sol.OPEN_STATUSES:
        actions.append("requerir_info")
    if req.identity_verified_at is None:
        actions.append("verificar_identidad")
    if req.kind in sol.ARCO_KINDS and ((req.status in sol.OPEN_STATUSES and not req.respond_extended_at) or (
            req.status == "respondida" and req.outcome in sol.POSITIVE_OUTCOMES and not req.effective_extended_at)):
        actions.append("ampliar")
    if req.status in sol.OPEN_STATUSES or (req.status == "respondida" and req.kind in sol.ATTENTION_KINDS):
        actions.append("responder")
    if req.kind == "retiro_importado" or (req.status == "respondida" and req.outcome in sol.POSITIVE_OUTCOMES
                                         and req.kind in sol.ARCO_KINDS):
        actions.append("hacer_efectiva")
    actions += ["cerrar", "nota"]
    return actions


def _admin_get(db: Session, folio: str, lock: bool = False) -> ComplianceRequest:
    req = sol.get_by_folio(db, folio, lock=lock)
    if req is None:
        raise HTTPException(status_code=404, detail="No encontramos esa solicitud.")
    return req


@router.get("/admin/cumplimiento/solicitudes")
def admin_list(estado: str = Query("abiertas", max_length=20), tipo: str | None = Query(None, max_length=30),
               q: str | None = Query(None, max_length=120), skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
               admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Cola de solicitudes. Abiertas primero las de plazo más próximo (semáforo en `sla`)."""
    query = db.query(ComplianceRequest)
    if estado == "abiertas":
        query = query.filter(ComplianceRequest.status.notin_(sol.FINAL_STATUSES))
    elif estado in sol.STATUS_LABELS:
        query = query.filter(ComplianceRequest.status == estado)
    elif estado != "todas":
        raise HTTPException(status_code=400, detail="Estado no válido.")
    if tipo:
        if tipo == "arco":
            query = query.filter(ComplianceRequest.kind.in_(sol.ARCO_KINDS))
        elif tipo in sol.KINDS:
            query = query.filter(ComplianceRequest.kind == tipo)
        else:
            raise HTTPException(status_code=400, detail="Tipo no válido.")
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        query = query.filter(or_(func.lower(ComplianceRequest.folio).like(term), func.lower(ComplianceRequest.email).like(term),
                                 func.lower(ComplianceRequest.name).like(term)))
    order = ComplianceRequest.respond_by.asc() if estado == "abiertas" else ComplianceRequest.received_at.desc()
    rows = query.order_by(order, ComplianceRequest.id).offset(skip).limit(limit + 1).all()
    now = sol.utcnow()
    items = [_admin_item(r, now) for r in rows[:limit]]
    if estado == "abiertas":
        rank = {"rojo": 0, "amarillo": 1, "verde": 2, "azul": 3, "gris": 4}
        items.sort(key=lambda i: (rank.get(i["sla"]["color"], 5), i["sla"]["vence"] or i["responde_antes_de"]))
    return {"items": items, "has_more": len(rows) > limit}


@router.get("/admin/cumplimiento/solicitudes/resumen")
def admin_summary(admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    now = sol.utcnow()
    rows = db.query(ComplianceRequest).filter(ComplianceRequest.status.notin_(sol.FINAL_STATUSES)).limit(5000).all()
    colors = {"rojo": 0, "amarillo": 0, "verde": 0, "azul": 0, "gris": 0}
    by_kind: dict[str, int] = {}
    for r in rows:
        colors[sol.sla(r, now)["color"]] += 1
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
    return {"abiertas": len(rows), "vencidas": colors["rojo"], "por_vencer": colors["amarillo"], "semaforo": colors,
            "por_tipo": by_kind}


@router.post("/admin/cumplimiento/solicitudes", status_code=status.HTTP_201_CREATED)
def admin_create(payload: SolicitudAdminCreate, request: Request, admin_user: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    """Registra una solicitud que llegó por correo, por escrito, por teléfono o por WhatsApp (le da folio y acuse)."""
    _check_kind_fields(payload)
    try:
        req = sol.create_solicitud(
            db, kind=payload.tipo, name=payload.nombre, email=payload.email, phone=payload.telefono,
            description=payload.descripcion, channel=payload.canal, details=_details(payload),
            report_id=payload.report_id, report_url=payload.enlace, order_id=None, acting_as=payload.actua_como,
            holder_name=payload.nombre_titular, identity_method=payload.identidad, actor=admin_user,
            ip=None, user_agent=None, commit=False,
        )
        record_admin_action(db, admin_user, "solicitud.registrar", "compliance_request", req.id,
                            details={"folio": req.folio, "tipo": req.kind, "canal": payload.canal}, request=request)
        db.commit()
    except sol.SolicitudError as err:
        db.rollback()
        _raise(err)
    db.refresh(req)
    return _admin_detail(db, req)


@router.get("/admin/cumplimiento/solicitudes/{folio}")
def admin_detail(folio: str, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _admin_detail(db, _admin_get(db, folio))


@router.post("/admin/cumplimiento/solicitudes/{folio}/acciones")
def admin_action(folio: str, payload: SolicitudAdminAccion, request: Request,
                 admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    req = _admin_get(db, folio, lock=True)
    msg = (payload.mensaje or "").strip()
    note = (payload.nota_interna or "").strip()
    extra = {}
    record_admin_action(db, admin_user, f"solicitud.{payload.accion}", "compliance_request", req.id,
                        details={"folio": req.folio, "resultado": payload.resultado,
                                 "motivo_negativa": payload.motivo_negativa,
                                 "eliminar_cuenta": payload.eliminar_cuenta or None,
                                 "eliminar_whatsapp": payload.eliminar_whatsapp or None}, request=request)
    try:
        a = payload.accion
        if a == "en_revision":
            sol.take(db, req, admin_user, msg or None)
        elif a == "primera_respuesta":
            sol.first_response(db, req, admin_user, msg)
        elif a == "requerir_info":
            sol.request_info(db, req, admin_user, msg, ask_document=payload.pedir_identificacion)
        elif a == "verificar_identidad":
            sol.verify_identity(db, req, admin_user, payload.metodo or "identificacion", note or None)
        elif a == "ampliar":
            sol.extend(db, req, admin_user, msg)
        elif a == "responder":
            sol.respond(db, req, admin_user, payload.resultado or "", msg, payload.motivo_negativa)
        elif a == "hacer_efectiva":
            extra = sol.make_effective(db, req, admin_user, msg or None, delete_account=payload.eliminar_cuenta,
                                       delete_whatsapp=payload.eliminar_whatsapp)
        elif a == "cerrar":
            sol.close(db, req, admin_user, msg or None, outcome=payload.resultado, denial_reason=payload.motivo_negativa)
        elif a == "nota":
            sol.add_note(db, req, admin_user, note or msg)
        if note and a not in ("nota", "verificar_identidad"):
            sol.add_note(db, req, admin_user, note)
        req.updated_at = sol.utcnow()
        db.commit()
    except sol.SolicitudError as err:
        db.rollback()
        _raise(err)
    db.refresh(req)
    out = _admin_detail(db, req)
    if extra:
        out["hecho"] = {k: v for k, v in extra.items() if k != "descarga"} | ({"descarga": True} if "descarga" in extra else {})
    return out


@router.get("/admin/cumplimiento/solicitudes/{folio}/identificacion")
def admin_identification(folio: str, request: Request, admin_user: User = Depends(require_admin),
                         db: Session = Depends(get_db)):
    """Identificación privada que subió la persona (solo mientras dura la verificación)."""
    from app.routers.documents import download_document

    req = _admin_get(db, folio)
    if not req.id_document_id:
        raise HTTPException(status_code=404, detail="Esta solicitud no tiene una identificación guardada.")
    record_admin_action(db, admin_user, "solicitud.ver_identificacion", "compliance_request", req.id,
                        details={"folio": req.folio}, request=request)
    db.commit()
    return download_document(req.id_document_id, request, admin_user, db)
