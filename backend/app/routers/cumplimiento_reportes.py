"""Cumplimiento: reportes públicos, protección de menores, derechos de autor, apelaciones, autoridades y evidencia.

Públicos (sin cuenta; límite por IP; campo trampa «website»):
- POST /cumplimiento/reportes-publicos y GET /cumplimiento/reportes-publicos/{folio}?email=  (moderacion.html §1,
  proteccion-nna.html §7). Lo que involucra a una niña, niño o adolescente se oculta al recibirlo.
- POST /cumplimiento/derechos-autor/avisos y /contra-avisos  (derechos-de-autor.html §3 a §6; Reglamento LFDA
  arts. 37 Quáter, 37 Quinquies y 37 Septies: sin certificados).
- POST /cumplimiento/apelaciones y GET /cumplimiento/apelaciones/{folio}?email=  (moderacion.html §7; funciona
  con la cuenta suspendida: folio de la medida + correo de la cuenta).
- GET /cumplimiento/autoridades/contacto  (contacto 24/7, autoridades.html §1).

Administración (/admin/cumplimiento/...): cola priorizada con plazos, medidas, apelaciones, avisos de derechos de
autor, requerimientos de autoridades (tres niveles), bóveda de evidencia y cuarentena. Todo queda en la bitácora.
"""
import datetime
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import client_ip, get_optional_user, require_admin, require_superadmin
from app.models import (
    AuthorityRequest, ContentReport, CopyrightCounterNotice, CopyrightNotice, Dog, EvidenceRecord, LostReport,
    Message, ModerationAction, ModerationAppeal, Product, Refuge, User,
)
from app.schemas import ReportReason, ReportTargetType
from app.services import evidence, legal_moderation as lm, moderation, ratelimit, staydown
from app.services.audit import record_admin_action

router = APIRouter(tags=["cumplimiento"])

PUBLIC_TARGET_TYPES = ("dog", "lost_report", "user", "refuge", "product", "veterinary", "veterinary_review")
DAY_SECONDS = 24 * 60 * 60
# Acuses por correo a una misma dirección (los formularios no piden cuenta: que nadie llene el buzón de un tercero)
ACK_EMAILS_PER_ADDRESS_DAY = 3
RATE_DETAIL = "Enviaste varias solicitudes seguidas. Espera una hora o escríbenos al correo de contacto."


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _limit(request: Request, bucket: str) -> str:
    ip = client_ip(request)
    hourly = max(1, settings.public_reports_hourly_limit)
    ratelimit.check(f"cumpl:{bucket}:h:{ip}", hourly, 3600, detail=RATE_DETAIL)
    ratelimit.check(f"cumpl:{bucket}:d:{ip}", hourly * 4, DAY_SECONDS,
                    detail="Llegaste al límite de solicitudes por hoy. Escríbenos al correo de contacto.")
    return ip


def _email(value: str | None, required: bool = False) -> str | None:
    value = (value or "").strip()
    if not value:
        if required:
            raise HTTPException(status_code=400, detail="Escribe un correo para poder responderte.")
        return None
    if len(value) > 255 or not lm.EMAIL_RE.match(value):
        raise HTTPException(status_code=400, detail="Escribe un correo válido.")
    return value


def _ack_allowed(email: str | None) -> bool:
    """Tope de acuses por dirección y día. El formulario se recibe igual; solo se omite el correo."""
    if not email:
        return False
    key = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]
    return ratelimit.hit(f"cumpl:acuse:{key}", ACK_EMAILS_PER_ADDRESS_DAY, DAY_SECONDS)


def _sha256(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _honeypot(website: str | None, prefix: str) -> dict | None:
    """Campo oculto que solo llenan los robots: se responde como si se hubiera recibido, sin guardar nada."""
    if (website or "").strip():
        return {"folio": lm.new_folio(prefix), "estado": "recibido",
                "mensaje": "Recibimos tu solicitud. Te escribiremos si necesitamos algo más."}
    return None


def _ua(request: Request) -> str | None:
    return (request.headers.get("user-agent") or "")[:300] or None


def _fmt(dt: datetime.datetime | None) -> str:
    return lm._fmt(dt)


# =========================================================================== reportes públicos
class PublicReportIn(BaseModel):
    target_url: str | None = Field(None, max_length=1000)
    target_type: ReportTargetType | None = None
    target_id: int | None = Field(None, ge=1)
    reason: ReportReason
    details: str = Field(..., min_length=5, max_length=2000)
    email: str | None = Field(None, max_length=255)
    website: str | None = Field(None, max_length=200)  # campo trampa


@router.get("/cumplimiento/reportes-publicos/motivos")
def public_report_reasons():
    """Motivos del formulario público (los mismos del botón «Reportar»), en el orden en que se muestran."""
    def group(reason):
        if reason in lm.MINOR_REASONS:
            return "menores"
        if reason in lm.DECREE_REASONS:
            return "decreto"
        return "otros"

    return [{"value": r, "label": lm.REASONS[r], "grupo": group(r), "oculta_al_reportar": r in lm.MINOR_REASONS}
            for r in lm.PUBLIC_REASONS]


@router.post("/cumplimiento/reportes-publicos", status_code=status.HTTP_201_CREATED)
def create_public_report(payload: PublicReportIn, request: Request, response: Response,
                         viewer: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """Formulario público de reportes, sin cuenta (moderacion.html §1; proteccion-nna.html §7 y §8)."""
    fake = _honeypot(payload.website, "REP")
    if fake:
        return fake
    ip = _limit(request, "reportes")
    email = _email(payload.email)
    url = (payload.target_url or "").strip() or None
    target = None
    if payload.target_type and payload.target_id:
        if payload.target_type not in PUBLIC_TARGET_TYPES:
            raise HTTPException(status_code=400, detail="Los mensajes del chat solo se reportan desde la conversación.")
        target_type, target_id = payload.target_type, payload.target_id
        target = moderation.load_target(db, target_type, target_id)
        if target is None:
            raise HTTPException(status_code=404, detail="No encontramos ese contenido.")
    else:
        found = lm.resolve_url(db, url)
        if found:
            target_type, target_id = found
            target = moderation.load_target(db, target_type, target_id)
        else:
            target_type, target_id = "sin_identificar", 0

    if target_type != "sin_identificar":
        same_sender = [ContentReport.reporter_ip == ip[:64]] + ([ContentReport.contact_email == email] if email else [])
        existing = db.query(ContentReport).filter(
            ContentReport.target_type == target_type, ContentReport.target_id == target_id,
            ContentReport.status == "open", ContentReport.reason == payload.reason, ContentReport.source == "publico",
            or_(*same_sender),
        ).first()
        if existing:
            response.status_code = status.HTTP_200_OK
            return _public_ack(existing)

    report = ContentReport(
        reporter_id=viewer.id if viewer else None, target_type=target_type, target_id=target_id,
        reason=payload.reason, details=payload.details.strip()[:2000], status="open", source="publico",
        folio=lm.new_folio("REP"), contact_email=email, reporter_ip=ip[:64], target_url=url,
    )
    db.add(report)
    db.flush()
    lm.intake(db, report, target)
    if _ack_allowed(email):
        lm.send_email(email, f"Recibimos tu reporte {report.folio}",
                      (f"Tu folio es {report.folio}. "
                       + ("Ocultamos el contenido mientras lo revisamos con prioridad. " if report.auto_hidden else "")
                       + f"Plazo objetivo de revisión: {_fmt(report.due_at)}. Puedes consultar el estado con tu folio "
                         "y este correo en la página de Moderación."),
                      "/app/legal/moderacion.html#formulario-reporte")
    db.commit()
    db.refresh(report)
    return _public_ack(report)


def _public_ack(report: ContentReport) -> dict:
    if report.reason in lm.MINOR_REASONS:
        message = ("Recibimos tu reporte. "
                   + ("Ya ocultamos el contenido y lo revisamos con prioridad." if report.auto_hidden
                      else "Lo revisamos con prioridad.")
                   + " Si alguien está en riesgo inmediato, llama al 911.")
    else:
        message = f"Recibimos tu reporte. Lo revisaremos a más tardar el {_fmt(report.due_at)}."
    return {"folio": report.folio, "estado": "recibido", "prioridad": lm.PRIORITY_LABELS.get(report.priority),
            "oculto": bool(report.auto_hidden), "revision_antes_de": report.due_at, "mensaje": message}


PUBLIC_STATUS = {"open": "En revisión", "resolved": "Revisado: tomamos medidas",
                 "dismissed": "Revisado: no encontramos un incumplimiento"}


@router.get("/cumplimiento/reportes-publicos/{folio}")
def public_report_status(folio: str, request: Request, email: str = Query(..., max_length=255),
                         db: Session = Depends(get_db)):
    """Estado de un reporte público con su folio y el correo que se dejó (sin detalles de la medida)."""
    _limit(request, "consultas")
    report = db.query(ContentReport).filter(ContentReport.folio == folio.strip().upper()).first()
    if not report or not report.contact_email or report.contact_email.lower() != email.strip().lower():
        raise HTTPException(status_code=404, detail="No encontramos un reporte con ese folio y correo.")
    return {"folio": report.folio, "estado": PUBLIC_STATUS.get(report.status, report.status),
            "recibido_en": report.created_at, "revision_antes_de": report.due_at, "revisado_en": report.resolved_at}


# =========================================================================== derechos de autor
class CopyrightNoticeIn(BaseModel):
    tipo: Literal["derechos_autor", "marca"] = "derechos_autor"
    ubicacion: str = Field(..., min_length=3, max_length=1000)  # art. 37 Quáter fr. I
    obra: str = Field(..., min_length=3, max_length=2000)  # obra o derecho infringido
    hechos: str = Field(..., min_length=10, max_length=4000)  # breve descripción de los hechos
    nombre: str = Field(..., min_length=3, max_length=255)
    caracter: Literal["titular", "representante"]
    representado: str | None = Field(None, max_length=255)
    documento_representacion: str | None = Field(None, max_length=2000)
    email: str = Field(..., max_length=255)
    email_alterno: str | None = Field(None, max_length=255)
    telefono: str = Field(..., min_length=8, max_length=30)
    domicilio: str = Field(..., min_length=10, max_length=1000)
    bajo_protesta: bool
    conoce_sancion: bool
    website: str | None = Field(None, max_length=200)


class CounterNoticeIn(BaseModel):
    folio: str = Field(..., min_length=4, max_length=24)  # folio del aviso (DA-…) o de la medida (MOD-…)
    email_cuenta: str = Field(..., max_length=255)  # correo de la cuenta que publicó el contenido
    nombre: str = Field(..., min_length=3, max_length=255)
    caracter: Literal["propio", "representante"]
    representado: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)  # contacto (si es otro)
    telefono: str | None = Field(None, max_length=30)
    domicilio: str = Field(..., min_length=10, max_length=1000)
    fundamento: Literal["licencia", "excepcion", "dominio_publico"]
    detalle: str = Field(..., min_length=10, max_length=4000)
    bajo_protesta: bool
    conoce_sancion: bool
    website: str | None = Field(None, max_length=200)


DECLARATION_MISSING = ("Para presentar el aviso debes declarar bajo protesta de decir verdad y manifestar que conoces "
                       "la sanción por declarar en falso (Ley Federal del Derecho de Autor, art. 232 Quinquies).")


@router.post("/cumplimiento/derechos-autor/avisos", status_code=status.HTTP_201_CREATED)
def create_copyright_notice(payload: CopyrightNoticeIn, request: Request,
                            db: Session = Depends(get_db)):
    """Aviso de derechos de autor o marca, sin cuenta ni certificados (Reglamento LFDA arts. 37 Quáter y 37 Quinquies)."""
    fake = _honeypot(payload.website, "DA")
    if fake:
        return fake
    ip = _limit(request, "avisos")
    if not (payload.bajo_protesta and payload.conoce_sancion):
        raise HTTPException(status_code=400, detail=DECLARATION_MISSING)
    email = _email(payload.email, required=True)
    alt = _email(payload.email_alterno)
    if payload.caracter == "representante" and not (payload.representado or "").strip():
        raise HTTPException(status_code=400, detail="Indica a quién representas.")
    now = _now()
    found = lm.resolve_url(db, payload.ubicacion)
    target = moderation.load_target(db, *found) if found else None
    photo_urls = None
    stem = lm.upload_stem(payload.ubicacion)
    if stem and target is not None:
        photo_urls = [u for u in evidence.target_photo_urls(found[0], target) if lm.photo_matches(u, stem)] or None
    incomplete = payload.caracter == "representante" and not (payload.documento_representacion or "").strip()
    fields = payload.model_dump(exclude={"website"})
    notice = CopyrightNotice(
        folio=lm.new_folio("DA"), kind=payload.tipo, status="incomplete" if incomplete else "received",
        content_url=payload.ubicacion.strip(), target_type=found[0] if found else None,
        target_id=found[1] if found else None, photo_urls=photo_urls, work=payload.obra.strip(),
        facts=payload.hechos.strip(), claimant_name=payload.nombre.strip(), claimant_capacity=payload.caracter,
        represented_name=(payload.representado or "").strip() or None,
        representation_document=(payload.documento_representacion or "").strip() or None, email=email, alt_email=alt,
        phone=payload.telefono.strip(), address=payload.domicilio.strip(), good_faith=True, knows_penalty=True,
        sha256=_sha256({**fields, "recibido_en": now.isoformat()}), ip=ip[:64], user_agent=_ua(request),
        uploader_user_id=moderation.owner_id(db, found[0], target) if target is not None else None,
        due_at=lm.add_business_days(now, settings.copyright_removal_business_days), created_at=now, updated_at=now,
    )
    db.add(notice)
    db.flush()
    pending = ("Falta el documento que acredita tu representación: envíalo al correo legal citando tu folio. "
               "Mientras tanto no retiramos el contenido.") if incomplete else (
        f"Lo revisamos y, si procede, retiramos el contenido a más tardar el {_fmt(notice.due_at)}.")
    if _ack_allowed(email):
        lm.send_email(email, f"Acuse de tu aviso {notice.folio}",
                      (f"Recibimos tu aviso el {now.strftime('%d/%m/%Y %H:%M')} (UTC). Folio: {notice.folio}. "
                       f"Huella SHA-256 del aviso: {notice.sha256}. {pending} GuauWoow es neutral: si hay disputa "
                       "sobre quién tiene los derechos, decide la autoridad."))
    lm.alert_admins(db, "Nuevo aviso de derechos de autor",
                    f"Aviso {notice.folio} sobre {notice.content_url[:200]}. Plazo objetivo de retiro: {_fmt(notice.due_at)}.",
                    data={"copyright_notice": notice.folio}, public=True,
                    dedupe_key=f"da:{notice.target_type}:{notice.target_id}" if notice.target_id else None)
    db.commit()
    return {"folio": notice.folio, "estado": notice.status, "recibido_en": notice.created_at, "sha256": notice.sha256,
            "retiro_antes_de": None if incomplete else notice.due_at,
            "mensaje": f"Recibimos tu aviso (folio {notice.folio}). {pending}"}


def _notice_by_folio(db: Session, folio: str) -> CopyrightNotice | None:
    folio = folio.strip().upper()
    if folio.startswith("MOD-"):
        action = db.query(ModerationAction).filter(ModerationAction.folio == folio).first()
        if not action or not action.copyright_notice_id:
            return None
        return db.query(CopyrightNotice).filter(CopyrightNotice.id == action.copyright_notice_id).first()
    return db.query(CopyrightNotice).filter(CopyrightNotice.folio == folio).first()


@router.post("/cumplimiento/derechos-autor/contra-avisos", status_code=status.HTTP_201_CREATED)
def create_counter_notice(payload: CounterNoticeIn, request: Request, db: Session = Depends(get_db)):
    """Contra-aviso de quien subió el contenido retirado (Reglamento LFDA art. 37 Septies). Se envía copia de inmediato
    a quien avisó y se restaura entre el día hábil 10 y el 15 salvo que acredite un procedimiento."""
    fake = _honeypot(payload.website, "CA")
    if fake:
        return fake
    ip = _limit(request, "avisos")
    if not (payload.bajo_protesta and payload.conoce_sancion):
        raise HTTPException(status_code=400, detail=DECLARATION_MISSING.replace("el aviso", "el contra-aviso"))
    account_email = _email(payload.email_cuenta, required=True)
    contact = _email(payload.email) or account_email
    notice = _notice_by_folio(db, payload.folio)
    uploader = db.query(User).filter(User.id == notice.uploader_user_id).first() if notice and notice.uploader_user_id else None
    if not notice or not uploader or (uploader.email or "").lower() != account_email.lower():
        raise HTTPException(status_code=404, detail="No encontramos un retiro con ese folio para el correo de esa cuenta.")
    if notice.status != "removed":
        raise HTTPException(status_code=409, detail="Ese aviso no está en un estado que admita contra-aviso.")
    if payload.caracter == "representante" and not (payload.representado or "").strip():
        raise HTTPException(status_code=400, detail="Indica a quién representas.")
    now = _now()
    fields = payload.model_dump(exclude={"website"})
    counter = CopyrightCounterNotice(
        folio=lm.new_folio("CA"), notice_id=notice.id, name=payload.nombre.strip(), capacity=payload.caracter,
        represented_name=(payload.representado or "").strip() or None, email=contact,
        phone=(payload.telefono or "").strip() or None, address=payload.domicilio.strip(), basis=payload.fundamento,
        basis_details=payload.detalle.strip(), good_faith=True, knows_penalty=True,
        sha256=_sha256({**fields, "recibido_en": now.isoformat()}), ip=ip[:64], created_at=now,
    )
    db.add(counter)
    notice.status = "counter_notice"
    notice.restore_from = lm.add_business_days(now, lm.COPYRIGHT_RESTORE_FROM_DAYS)
    notice.restore_until = lm.add_business_days(now, lm.COPYRIGHT_RESTORE_UNTIL_DAYS)
    notice.updated_at = now
    db.flush()
    basis = {"licencia": "Contrato o licencia", "excepcion": "Uso permitido por una excepción de la ley",
             "dominio_publico": "Obra de dominio público"}[payload.fundamento]
    # Copia inmediata a quien avisó (Reglamento LFDA art. 37 Octies)
    lm.send_email(notice.email, f"Contra-aviso sobre tu aviso {notice.folio}", (
        f"Quien subió el contenido presentó un contra-aviso (folio {counter.folio}).\n"
        f"Nombre: {counter.name} ({'por su cuenta' if counter.capacity == 'propio' else 'como representante de ' + (counter.represented_name or '')})\n"
        f"Domicilio: {counter.address}\nContacto: {counter.email}\nFundamento: {basis}\nDetalle: {counter.basis_details}\n\n"
        f"Restauraremos el contenido entre el {_fmt(notice.restore_from)} y el {_fmt(notice.restore_until)}, salvo que "
        "antes nos acredites que iniciaste un procedimiento judicial, administrativo, penal o alterno (escribe al correo "
        "legal citando tu folio). GuauWoow es neutral: la disputa la decide la autoridad."))
    if contact.lower() == account_email.lower() or _ack_allowed(contact):
        lm.send_email(contact, f"Recibimos tu contra-aviso {counter.folio}", (
            f"Enviamos copia a quien presentó el aviso. Si no acredita un procedimiento, restauraremos el contenido "
            f"entre el {_fmt(notice.restore_from)} y el {_fmt(notice.restore_until)}."))
    lm.alert_admins(db, "Contra-aviso de derechos de autor",
                    f"Contra-aviso {counter.folio} al aviso {notice.folio}. Restauración: {_fmt(notice.restore_from)}.",
                    data={"copyright_notice": notice.folio})
    db.commit()
    return {"folio": counter.folio, "aviso": notice.folio, "restauracion_desde": notice.restore_from,
            "restauracion_hasta": notice.restore_until,
            "mensaje": (f"Recibimos tu contra-aviso (folio {counter.folio}) y enviamos copia a quien avisó. Si no acredita "
                        f"un procedimiento, restauraremos el contenido entre el {_fmt(notice.restore_from)} y el "
                        f"{_fmt(notice.restore_until)}.")}


# =========================================================================== apelaciones
class AppealIn(BaseModel):
    folio: str = Field(..., min_length=4, max_length=24)  # folio de la medida (MOD-…)
    email: str | None = Field(None, max_length=255)  # correo de la cuenta (obligatorio sin sesión)
    argumentos: str = Field(..., min_length=20, max_length=4000)
    pruebas: str | None = Field(None, max_length=2000)
    website: str | None = Field(None, max_length=200)


APPEAL_STATUS = {"pending": "En revisión", "upheld": "Resuelta: se confirma la medida",
                 "reversed": "Resuelta: revocamos la medida"}


@router.post("/cumplimiento/apelaciones", status_code=status.HTTP_201_CREATED)
def create_appeal(payload: AppealIn, request: Request, response: Response,
                  viewer: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """Apelación de una medida de moderación. Sirve aunque la cuenta esté suspendida (folio + correo de la cuenta)."""
    fake = _honeypot(payload.website, "APE")
    if fake:
        return fake
    ip = _limit(request, "apelaciones")
    not_found = HTTPException(status_code=404, detail="No encontramos una medida con ese folio para esa cuenta.")
    action = db.query(ModerationAction).filter(ModerationAction.folio == payload.folio.strip().upper()).first()
    if not action or action.action == "quarantine" or not action.user_id:
        raise not_found
    owner = db.query(User).filter(User.id == action.user_id).first()
    email = _email(payload.email)
    if not owner or not ((viewer and viewer.id == owner.id) or (email and (owner.email or "").lower() == email.lower())):
        raise not_found
    if action.action == "copyright_removal":
        raise HTTPException(status_code=400, detail=(
            "Los retiros por derechos de autor se responden con un contra-aviso en la página de Propiedad intelectual."))
    if action.status != "active":
        raise HTTPException(status_code=409, detail="Esa medida ya no está vigente.")
    now = _now()
    if action.appeal_until and now > action.appeal_until:
        raise HTTPException(status_code=400, detail=(
            f"El plazo para apelar terminó el {_fmt(action.appeal_until)}. Aún puedes ejercer tus derechos ARCO o acudir "
            "a la PROFECO."))
    existing = lm.pending_appeal(db, action.id)
    if existing:
        response.status_code = status.HTTP_200_OK
        return _appeal_ack(existing)
    appeal = ModerationAppeal(
        folio=lm.new_folio("APE"), action_id=action.id, user_id=owner.id, email=email or owner.email,
        arguments=payload.argumentos.strip(), evidence_text=(payload.pruebas or "").strip() or None,
        due_at=lm.appeal_due(now), ip=ip[:64], created_at=now,
    )
    db.add(appeal)
    db.flush()
    lm.alert_admins(db, "Nueva apelación de moderación",
                    (f"Apelación {appeal.folio} contra la medida {action.folio} ({lm.ACTION_LABELS.get(action.action)}). "
                     f"Debe resolverla una persona distinta de quien decidió, antes del {_fmt(appeal.due_at)}."),
                    data={"appeal": appeal.folio, "moderation_action": action.folio})
    lm.send_email(appeal.email, f"Recibimos tu apelación {appeal.folio}",
                  f"Una persona distinta de quien decidió la revisará y te responderá a más tardar el {_fmt(appeal.due_at)}.")
    db.commit()
    return _appeal_ack(appeal)


def _appeal_ack(appeal: ModerationAppeal) -> dict:
    return {"folio": appeal.folio, "estado": APPEAL_STATUS.get(appeal.status, appeal.status),
            "responde_antes_de": appeal.due_at,
            "mensaje": (f"Recibimos tu apelación (folio {appeal.folio}). Una persona distinta de quien decidió la "
                        f"revisará y te responderá a más tardar el {_fmt(appeal.due_at)}.")}


@router.get("/cumplimiento/apelaciones/{folio}")
def appeal_status(folio: str, request: Request, email: str = Query(..., max_length=255), db: Session = Depends(get_db)):
    _limit(request, "consultas")
    appeal = db.query(ModerationAppeal).filter(ModerationAppeal.folio == folio.strip().upper()).first()
    if not appeal or (appeal.email or "").lower() != email.strip().lower():
        raise HTTPException(status_code=404, detail="No encontramos una apelación con ese folio y correo.")
    return {"folio": appeal.folio, "estado": APPEAL_STATUS.get(appeal.status, appeal.status),
            "responde_antes_de": appeal.due_at, "resuelta_en": appeal.decided_at, "respuesta": appeal.decision_note}


# =========================================================================== autoridades (público)
@router.get("/cumplimiento/autoridades/contacto")
def authority_contact():
    """Punto de contacto 24/7 para autoridades de procuración e impartición de justicia (Decreto NNA art. 5 fr. I)."""
    return {
        "configurado": bool(settings.authority_contact_email or settings.authority_contact_phone),
        "correo": settings.authority_contact_email, "telefono": settings.authority_contact_phone,
        "disponibilidad": "24 horas, los 365 días",
        "primera_respuesta": {"menores_o_riesgo_minutos": settings.authority_first_response_urgent_minutes,
                              "otros_horas": settings.authority_first_response_hours},
        "solo_autoridades": True,
    }


# =========================================================================== administración: cola
@router.get("/admin/cumplimiento/resumen")
def admin_summary(admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    now = _now()
    open_q = db.query(ContentReport).filter(ContentReport.status == "open")
    by_priority = dict(db.query(ContentReport.priority, func.count(ContentReport.id))
                       .filter(ContentReport.status == "open").group_by(ContentReport.priority).all())
    return {
        "reportes_abiertos": {lm.PRIORITY_LABELS[p]: by_priority.get(p, 0) for p in lm.PRIORITY_LABELS},
        "reportes_vencidos": open_q.filter(ContentReport.due_at < now).count(),
        "apelaciones_pendientes": db.query(ModerationAppeal).filter(ModerationAppeal.status == "pending").count(),
        "avisos_derechos_pendientes": db.query(CopyrightNotice).filter(
            CopyrightNotice.status.in_(("received", "incomplete", "counter_notice"))).count(),
        "autoridades_abiertas": db.query(AuthorityRequest).filter(
            AuthorityRequest.status.notin_(("cerrado", "rechazado", "entregado", "denunciado"))).count(),
        "cuarentenas": db.query(EvidenceRecord).filter(EvidenceRecord.is_csam == True,  # noqa: E712
                                                        EvidenceRecord.legal_hold == True,  # noqa: E712
                                                        EvidenceRecord.kind != lm.PENDING_QUARANTINE_KIND).count(),
        "cuarentenas_preventivas": open_q.filter(ContentReport.reason.in_(lm.CSAM_REASONS),
                                                 ContentReport.auto_hidden == True).count(),  # noqa: E712
        "contacto_24_7_configurado": bool(settings.authority_contact_email or settings.authority_contact_phone),
    }


@router.get("/admin/cumplimiento/cola")
def admin_queue(
    prioridad: int | None = Query(None, ge=0, le=3),
    vencidos: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Reportes abiertos por prioridad (0 = menores) y plazo; los de abuso sexual infantil solo con metadatos."""
    from app.routers.reports import _admin_rows

    query = db.query(ContentReport).filter(ContentReport.status == "open")
    if prioridad is not None:
        query = query.filter(ContentReport.priority == prioridad)
    if vencidos:
        query = query.filter(ContentReport.due_at < _now())
    rows = (query.order_by(ContentReport.priority, ContentReport.due_at.asc().nullslast(), ContentReport.id)
            .offset(skip).limit(limit).all())
    now = _now()
    out = _admin_rows(db, rows)
    pending = {(r.target_type, r.target_id) for r in rows if lm.is_pending_quarantine(db, r)}
    for item in out:
        item["quarantine_pending"] = (item["target_type"], item["target_id"]) in pending
    # Reincidencia (moderacion.html §5): medidas firmes previas de la cuenta responsable, en total y por motivo
    owners = {(item.get("target") or {}).get("owner_id") for item in out} - {None}
    history: dict[int, dict[str, int]] = {}
    if owners:
        for user_id, rule, count in (
            db.query(ModerationAction.user_id, ModerationAction.rule, func.count(ModerationAction.id))
            .filter(ModerationAction.user_id.in_(owners), ModerationAction.status != "revoked")
            .group_by(ModerationAction.user_id, ModerationAction.rule).all()
        ):
            history.setdefault(user_id, {})[rule] = count
    for item in out:
        item["reason_label"] = lm.reason_label(item["reason"])
        item["priority_label"] = lm.PRIORITY_LABELS.get(item["priority"], "")
        item["overdue"] = bool(item["due_at"] and item["due_at"] < now)
        owner_history = history.get((item.get("target") or {}).get("owner_id"), {})
        item["owner_prior_actions"] = sum(owner_history.values())
        item["owner_prior_same_rule"] = owner_history.get(item["reason"], 0)
    return out


class TargetLink(BaseModel):
    target_type: ReportTargetType
    target_id: int = Field(..., ge=1)


@router.patch("/admin/cumplimiento/reportes/{id}/objetivo")
def link_report_target(id: int, payload: TargetLink, request: Request, admin_user: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    """Asigna el contenido a un reporte público sin enlace reconocible (y aplica las medidas inmediatas)."""
    report = db.query(ContentReport).filter(ContentReport.id == id).first()
    if not report or report.status != "open":
        raise HTTPException(status_code=404, detail="No encontramos ese reporte abierto.")
    if report.target_type != "sin_identificar":
        raise HTTPException(status_code=400, detail="Este reporte ya tiene un contenido asignado.")
    target = moderation.load_target(db, payload.target_type, payload.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No encontramos ese contenido.")
    report.target_type, report.target_id = payload.target_type, payload.target_id
    out = lm.intake(db, report, target)
    record_admin_action(db, admin_user, "report.link_target", "content_report", report.id,
                        {"target_type": payload.target_type, "target_id": payload.target_id, **out}, request)
    db.commit()
    return {"ok": True, **out}


@router.post("/admin/cumplimiento/contenido/{target_type}/{target_id}/cuarentena")
def quarantine_content(target_type: ReportTargetType, target_id: int, request: Request,
                       admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Pone en cuarentena contenido que el equipo identificó como material de abuso sexual infantil."""
    if target_type == "refuge":
        raise HTTPException(status_code=400, detail="Para un refugio suspende la cuenta y pon en cuarentena cada contenido.")
    target = moderation.load_target(db, target_type, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No encontramos ese contenido.")
    pending, _record = lm.pending_quarantine_record(db, target_type, target_id)
    if pending is not None:
        # Ya está en cuarentena preventiva por un reporte: se confirma esa (los archivos ya están en la bóveda)
        out = lm.confirm_quarantine(db, pending, admin_user)
        record_admin_action(db, admin_user, "content.quarantine_confirm", target_type, target_id, out, request)
        db.commit()
        return out
    report = ContentReport(reporter_id=admin_user.id, target_type=target_type, target_id=target_id,
                           reason="abuso_sexual_infantil", details="Detectado por el equipo.", status="resolved",
                           action="quarantine", source="equipo", priority=0, resolved_by=admin_user.id,
                           resolved_at=_now())
    db.add(report)
    db.flush()
    out = lm.quarantine(db, report, target, actor=admin_user)
    record_admin_action(db, admin_user, "content.quarantine", target_type, target_id, out, request)
    db.commit()
    return out


class PendingDecisionIn(BaseModel):
    motivo: str = Field(..., min_length=10, max_length=2000)


def _pending_report_or_404(db: Session, id: int) -> ContentReport:
    report = db.query(ContentReport).filter(ContentReport.id == id).first()
    if not report or not lm.is_pending_quarantine(db, report):
        raise HTTPException(status_code=404, detail="No encontramos una cuarentena preventiva para ese reporte.")
    return report


@router.get("/admin/cumplimiento/reportes/{id}/senales")
def pending_quarantine_signals(id: int, request: Request, admin_user: User = Depends(require_admin),
                               db: Session = Depends(get_db)):
    """Vista protegida de una cuarentena preventiva: solo metadatos y señales (nunca el material)."""
    report = _pending_report_or_404(db, id)
    out = lm.quarantine_signals(db, report)
    record_admin_action(db, admin_user, "content.quarantine_signals", report.target_type, report.target_id,
                        {"content_report_id": report.id}, request)
    db.commit()
    return out


@router.post("/admin/cumplimiento/reportes/{id}/confirmar-cuarentena")
def confirm_pending_quarantine(id: int, payload: PendingDecisionIn, request: Request,
                               admin_user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    """Un superadmin confirma la cuarentena preventiva: bloqueo por hash, denuncia pendiente y alerta de reintentos."""
    report = _pending_report_or_404(db, id)
    out = lm.confirm_quarantine(db, report, admin_user)
    record_admin_action(db, admin_user, "content.quarantine_confirm", report.target_type, report.target_id,
                        {"content_report_id": report.id, "motivo": payload.motivo, **out}, request)
    db.commit()
    return out


@router.post("/admin/cumplimiento/reportes/{id}/descartar-cuarentena")
def dismiss_pending_quarantine(id: int, payload: PendingDecisionIn, request: Request,
                               admin_user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    """Un superadmin descarta la cuarentena preventiva (reporte falso): restaura los archivos y el contenido."""
    report = _pending_report_or_404(db, id)
    out = lm.release_pending_quarantine(db, report, admin_user, payload.motivo.strip())
    record_admin_action(db, admin_user, "content.quarantine_dismiss", report.target_type, report.target_id,
                        {"content_report_id": report.id, "motivo": payload.motivo, **out}, request)
    for r in db.query(ContentReport).filter(ContentReport.id.in_(out["dismissed"] or [0])).all():
        if r.contact_email and not r.reporter_id:
            lm.send_email(r.contact_email, f"Revisamos tu reporte {r.folio or ''}".strip(),
                          "Revisamos el contenido que nos reportaste y no encontramos un incumplimiento de nuestras reglas.")
    db.commit()
    return out


@router.get("/admin/cumplimiento/medidas")
def list_actions(user_id: int | None = None, estado: str | None = None, skip: int = Query(0, ge=0),
                 limit: int = Query(50, ge=1, le=200), admin_user: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    query = db.query(ModerationAction)
    if user_id:
        query = query.filter(ModerationAction.user_id == user_id)
    if estado:
        query = query.filter(ModerationAction.status == estado)
    rows = query.order_by(ModerationAction.id.desc()).offset(skip).limit(limit).all()
    return [{f: getattr(a, f) for f in (
        "id", "folio", "user_id", "target_type", "target_id", "action", "rule", "rule_text", "detection",
        "duration_days", "ends_at", "content_report_id", "copyright_notice_id", "evidence_id", "decided_by_id",
        "notice_sent_at", "notice_withheld_reason", "appeal_until", "status", "revoked_at", "created_at",
    )} | {"action_label": lm.ACTION_LABELS.get(a.action, a.action)} for a in rows]


# =========================================================================== administración: apelaciones
class AppealDecisionIn(BaseModel):
    decision: Literal["confirmar", "revocar"]
    nota: str = Field(..., min_length=10, max_length=4000)  # respuesta razonada para la persona


def _appeal_row(db: Session, appeal: ModerationAppeal) -> dict:
    action = appeal.action_ref
    return {f: getattr(appeal, f) for f in (
        "id", "folio", "action_id", "user_id", "email", "arguments", "evidence_text", "status", "due_at",
        "decided_by_id", "decision_note", "decided_at", "created_at",
    )} | {
        "overdue": appeal.status == "pending" and appeal.due_at < _now(),
        "action": {"folio": action.folio, "action": action.action, "label": lm.ACTION_LABELS.get(action.action),
                   "rule_text": action.rule_text, "decided_by_id": action.decided_by_id, "target_type": action.target_type,
                   "target_id": action.target_id, "created_at": action.created_at} if action else None,
    }


@router.get("/admin/cumplimiento/apelaciones")
def list_appeals(estado: str = Query("pending"), admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = db.query(ModerationAppeal)
    if estado != "all":
        query = query.filter(ModerationAppeal.status == estado)
    return [_appeal_row(db, a) for a in query.order_by(ModerationAppeal.due_at, ModerationAppeal.id).limit(200).all()]


@router.post("/admin/cumplimiento/apelaciones/{id}/resolver")
def resolve_appeal(id: int, payload: AppealDecisionIn, request: Request, admin_user: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    """La resuelve una persona distinta de quien decidió la medida; si prospera se restaura el contenido o la cuenta."""
    appeal = db.query(ModerationAppeal).filter(ModerationAppeal.id == id).first()
    if not appeal:
        raise HTTPException(status_code=404, detail="No encontramos esa apelación.")
    if appeal.status != "pending":
        raise HTTPException(status_code=400, detail="Esta apelación ya fue resuelta.")
    action = appeal.action_ref
    if action.decided_by_id and action.decided_by_id == admin_user.id:
        raise HTTPException(status_code=409, detail=(
            "La apelación debe resolverla una persona distinta de quien decidió la medida."))
    restored = {}
    if payload.decision == "revocar" and action.status == "active":
        restored = lm.undo_action(db, action)
    appeal.status = "reversed" if payload.decision == "revocar" else "upheld"
    appeal.decided_by_id = admin_user.id
    appeal.decision_note = payload.nota.strip()
    appeal.decided_at = _now()
    user = db.query(User).filter(User.id == appeal.user_id).first() if appeal.user_id else None
    title = "Revocamos la medida que apelaste" if payload.decision == "revocar" else "Resolvimos tu apelación"
    body = (f"Apelación {appeal.folio} sobre la medida {action.folio}: "
            + ("revocamos la medida y restauramos tu contenido o tu cuenta. " if payload.decision == "revocar"
               else "confirmamos la medida. ")
            + f"Motivos: {appeal.decision_note}")
    if user is not None:
        lm.notify_person(db, user, "moderation_notice", title, body, data={"appeal": appeal.folio})
        if appeal.email and appeal.email.lower() != (user.email or "").lower():
            lm.send_email(appeal.email, title, body)
    else:
        lm.send_email(appeal.email, title, body)
    record_admin_action(db, admin_user, f"appeal.{appeal.status}", "moderation_appeal", appeal.id,
                        {"folio": appeal.folio, "moderation_action": action.folio, "restored": restored}, request)
    db.commit()
    return _appeal_row(db, appeal)


# =========================================================================== administración: derechos de autor
class NoteIn(BaseModel):
    nota: str | None = Field(None, max_length=4000)


class RemovalIn(BaseModel):
    target_type: ReportTargetType | None = None
    target_id: int | None = Field(None, ge=1)
    photo_urls: list[str] | None = None  # imágenes a bloquear; vacío = las del aviso o todas las del contenido
    nota: str | None = Field(None, max_length=4000)


def _notice_row(db: Session, n: CopyrightNotice) -> dict:
    counter = db.query(CopyrightCounterNotice).filter(CopyrightCounterNotice.notice_id == n.id).first()
    target = moderation.load_target(db, n.target_type, n.target_id) if n.target_type and n.target_id else None
    row = {c: getattr(n, c) for c in (
        "id", "folio", "kind", "status", "content_url", "target_type", "target_id", "photo_urls", "work", "facts",
        "claimant_name", "claimant_capacity", "represented_name", "representation_document", "email", "alt_email",
        "phone", "address", "sha256", "uploader_user_id", "due_at", "removed_at", "uploader_notified_at",
        "restore_from", "restore_until", "proceeding_at", "proceeding_note", "restored_at", "admin_notes", "created_at",
    )}
    row["target"] = moderation.summary(db, n.target_type, target) if n.target_type else None
    row["overdue"] = n.status == "received" and bool(n.due_at and n.due_at < _now())
    row["strikes"] = lm.copyright_strikes(db, n.uploader_user_id) if n.uploader_user_id else None
    row["counter_notice"] = {c: getattr(counter, c) for c in (
        "folio", "name", "capacity", "represented_name", "email", "phone", "address", "basis", "basis_details", "sha256",
        "created_at")} if counter else None
    return row


def _get_notice(db: Session, id: int) -> CopyrightNotice:
    notice = db.query(CopyrightNotice).filter(CopyrightNotice.id == id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="No encontramos ese aviso.")
    return notice


@router.get("/admin/cumplimiento/derechos-autor")
def list_copyright_notices(estado: str = Query("open"), admin_user: User = Depends(require_admin),
                           db: Session = Depends(get_db)):
    query = db.query(CopyrightNotice)
    if estado == "open":
        query = query.filter(CopyrightNotice.status.in_(("received", "incomplete", "counter_notice", "litigation")))
    elif estado != "all":
        query = query.filter(CopyrightNotice.status == estado)
    return [_notice_row(db, n) for n in query.order_by(CopyrightNotice.id.desc()).limit(200).all()]


@router.post("/admin/cumplimiento/derechos-autor/{id}/retirar")
def remove_for_copyright(id: int, payload: RemovalIn, request: Request, admin_user: User = Depends(require_admin),
                         db: Session = Depends(get_db)):
    """Retiro expedito: oculta el contenido, bloquea sus imágenes (staydown), guarda la evidencia, avisa a quien lo
    subió (con copia del aviso y el enlace al contra-aviso) y aplica la política de reincidentes."""
    notice = _get_notice(db, id)
    if notice.status not in ("received", "incomplete"):
        raise HTTPException(status_code=400, detail="Este aviso ya se atendió.")
    if payload.target_type and payload.target_id:
        notice.target_type, notice.target_id = payload.target_type, payload.target_id
    if not notice.target_type or not notice.target_id:
        raise HTTPException(status_code=400, detail="Indica el contenido que se retira (tipo e id).")
    target = moderation.load_target(db, notice.target_type, notice.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="El contenido ya no existe.")
    if notice.target_type in ("user", "refuge", "message"):
        raise HTTPException(status_code=400, detail="Por derechos de autor se retira una publicación, un producto o una reseña.")
    all_photos = evidence.target_photo_urls(notice.target_type, target)
    photos = [u for u in (payload.photo_urls or notice.photo_urls or all_photos) if u in all_photos]
    now = _now()
    uploader_id = moderation.owner_id(db, notice.target_type, target)
    uploader = db.query(User).filter(User.id == uploader_id).first() if uploader_id else None
    record = evidence.capture(
        db, kind="derechos_autor", target_type=notice.target_type, target_id=notice.target_id, obj=target,
        owner_user_id=uploader_id, reason="derechos_autor", copyright_notice_id=notice.id,
        decision={"action": "copyright_removal", "photo_urls": photos, "actor_id": admin_user.id, "notes": payload.nota,
                  "notice_sha256": notice.sha256},
        actor_id=admin_user.id,
    )
    blocked = staydown.block_urls(db, photos, "derechos_autor", notice_id=notice.id, evidence_id=record.id,
                                  actor_id=admin_user.id)
    if hasattr(target, "is_hidden"):
        target.is_hidden = True
    notice.status = "removed"
    notice.removed_at = now
    notice.removed_by_id = admin_user.id
    notice.uploader_user_id = uploader_id
    notice.photo_urls = photos or None
    notice.admin_notes = payload.nota
    notice.updated_at = now
    db.flush()
    strikes = lm.copyright_strikes(db, uploader_id, now) if uploader_id else None
    title = moderation.summary(db, notice.target_type, target).get("title") or ""
    action = lm.record_action(
        db, user=uploader, target_type=notice.target_type, target_id=notice.target_id, action="copyright_removal",
        rule=f"Derechos de autor o marca: aviso {notice.folio}", detection="aviso_derechos", actor=admin_user,
        title=title, notice=notice, evidence_record=record, notes=payload.nota, strikes=strikes,
    )
    if uploader is not None:
        # Copia del aviso (sin los datos de contacto de quien avisó: solo su nombre y carácter)
        lm.notify_person(db, uploader, "copyright_notice_copy", f"Copia del aviso {notice.folio}", (
            f"Quien avisó: {notice.claimant_name} ({notice.claimant_capacity}"
            + (f" de {notice.represented_name}" if notice.represented_name else "") + ").\n"
            f"Obra o derecho: {notice.work}\nHechos: {notice.facts}\nUbicación: {notice.content_url}\n"
            f"Puedes presentar un contra-aviso con el folio {notice.folio} en {lm.COPYRIGHT_URL}#formularios."),
            url=f"{lm.COPYRIGHT_URL}#formularios", data={"copyright_notice": notice.folio})
        notice.uploader_notified_at = now
        sanction = lm.enforce_repeat_infringer(db, uploader, notice, admin_user, strikes or 0)
    else:
        sanction = None
    lm.send_email(notice.email, f"Retiramos el contenido de tu aviso {notice.folio}",
                  "Retiramos o inhabilitamos el contenido y avisamos a quien lo subió. Si presenta un contra-aviso te "
                  "enviaremos una copia de inmediato.")
    record_admin_action(db, admin_user, "copyright.remove", notice.target_type, notice.target_id,
                        {"notice": notice.folio, "blocked_hashes": len(blocked), "evidence_id": record.id,
                         "strikes": strikes, "sanction": sanction, "moderation_action": action.folio}, request)
    db.commit()
    return _notice_row(db, notice)


def _notice_transition(id: int, payload: NoteIn, request: Request, admin_user: User, db: Session, *, allowed: tuple,
                       new_status: str, audit: str, email_title: str, email_body: str) -> dict:
    notice = _get_notice(db, id)
    if notice.status not in allowed:
        raise HTTPException(status_code=400, detail="Este aviso no está en un estado que permita esa acción.")
    now = _now()
    if new_status == "restored":
        lm.restore_copyright(db, notice, (payload.nota or "Restaurado por el equipo.").strip())
    else:
        notice.status = new_status
        notice.admin_notes = ((notice.admin_notes or "") + "\n" + (payload.nota or "")).strip()[:4000] or None
    if new_status == "litigation":
        notice.proceeding_at = now
        notice.proceeding_note = payload.nota
    notice.updated_at = now
    lm.send_email(notice.email, f"{email_title} ({notice.folio})", email_body + (f"\n{payload.nota}" if payload.nota else ""))
    record_admin_action(db, admin_user, audit, "copyright_notice", notice.id, {"folio": notice.folio, "nota": payload.nota},
                        request)
    db.commit()
    return _notice_row(db, notice)


@router.post("/admin/cumplimiento/derechos-autor/{id}/incompleto")
def notice_incomplete(id: int, payload: NoteIn, request: Request, admin_user: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    return _notice_transition(id, payload, request, admin_user, db, allowed=("received",), new_status="incomplete",
                              audit="copyright.incomplete", email_title="Completa tu aviso",
                              email_body="A tu aviso le falta información. Mientras la completas no retiramos el contenido.")


@router.post("/admin/cumplimiento/derechos-autor/{id}/rechazar")
def notice_reject(id: int, payload: NoteIn, request: Request, admin_user: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    return _notice_transition(id, payload, request, admin_user, db, allowed=("received", "incomplete"),
                              new_status="rejected", audit="copyright.reject", email_title="Tu aviso no procede",
                              email_body="Revisamos tu aviso y no procede el retiro.")


@router.post("/admin/cumplimiento/derechos-autor/{id}/procedimiento")
def notice_proceeding(id: int, payload: NoteIn, request: Request, admin_user: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    """Quien avisó acreditó un procedimiento antes de la restauración: el contenido sigue retirado."""
    return _notice_transition(id, payload, request, admin_user, db, allowed=("counter_notice",), new_status="litigation",
                              audit="copyright.proceeding", email_title="Registramos tu procedimiento",
                              email_body="El contenido sigue retirado hasta que resuelva la autoridad.")


@router.post("/admin/cumplimiento/derechos-autor/{id}/restaurar")
def notice_restore(id: int, payload: NoteIn, request: Request, admin_user: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    return _notice_transition(id, payload, request, admin_user, db, allowed=("counter_notice", "litigation", "removed"),
                              new_status="restored", audit="copyright.restore", email_title="Restauramos el contenido",
                              email_body="Restauramos el contenido retirado por tu aviso.")


@router.post("/admin/cumplimiento/derechos-autor/{id}/cerrar")
def notice_close(id: int, payload: NoteIn, request: Request, admin_user: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    return _notice_transition(id, payload, request, admin_user, db, allowed=("removed", "litigation"), new_status="final",
                              audit="copyright.final", email_title="Cerramos tu aviso",
                              email_body="El retiro quedó firme.")


# =========================================================================== administración: autoridades
AuthorityKind = Literal["datos_cuenta", "comunicaciones", "ubicacion", "conservacion", "retiro", "orden_proteccion",
                        "denuncia", "otro"]
AuthorityType = Literal["ministerio_publico", "juez", "paot", "impi", "profeco", "indautor", "policia", "otra"]
AuthorityStatus = Literal["recibido", "en_revision", "incompleto", "preservado", "entregado", "entregado_parcial",
                          "rechazado", "cerrado", "pendiente_denuncia", "denunciado"]
LEVEL_BY_KIND = {"datos_cuenta": 1, "comunicaciones": 2, "ubicacion": 3}
# Tipos que no dicen por sí solos qué se entrega: el nivel se indica siempre (y nunca baja del que exige el tipo)
LEVEL_REQUIRED_KINDS = ("conservacion", "retiro", "orden_proteccion", "otro")


def effective_level(kind: str | None, level: int | None) -> int | None:
    """El nivel nunca es menor que el que exige el tipo de información (autoridades.html §3)."""
    minimum = LEVEL_BY_KIND.get(kind or "")
    if level is None:
        return minimum
    return max(level, minimum or 1)


class TargetRef(BaseModel):
    type: Literal["user", "dog", "lost_report", "product", "refuge", "message", "veterinary", "veterinary_review",
                  "conversation"]
    id: int = Field(..., ge=1)


class AuthorityIn(BaseModel):
    direction: Literal["entrante", "saliente"] = "entrante"
    kind: AuthorityKind
    level: Literal[1, 2, 3] | None = None
    authority_name: str = Field(..., min_length=3, max_length=255)
    authority_type: AuthorityType
    case_number: str | None = Field(None, max_length=120)
    legal_basis: str | None = Field(None, max_length=4000)
    requested_data: str | None = Field(None, max_length=4000)
    targets: list[TargetRef] = []
    involves_minor: bool = False
    life_risk: bool = False
    judicial_order: bool = False
    participant_consent: bool = False
    received_at: datetime.datetime | None = None
    due_at: datetime.datetime | None = None
    authenticity_verified: bool = False
    authenticity_method: str | None = Field(None, max_length=300)
    legal_review: bool = False
    external_folio: str | None = Field(None, max_length=120)


class AuthorityUpdate(BaseModel):
    status: AuthorityStatus | None = None
    level: Literal[1, 2, 3] | None = None  # solo puede subir o fijarse; nunca baja del que exige el tipo
    case_number: str | None = Field(None, max_length=120)
    legal_basis: str | None = Field(None, max_length=4000)
    requested_data: str | None = Field(None, max_length=4000)
    due_at: datetime.datetime | None = None
    judicial_order: bool | None = None
    participant_consent: bool | None = None
    authenticity_verified: bool | None = None
    authenticity_method: str | None = Field(None, max_length=300)
    legal_review: bool | None = None
    decision: str | None = Field(None, max_length=4000)
    response_summary: str | None = Field(None, max_length=4000)
    user_notified: bool | None = None
    notice_withheld_reason: str | None = Field(None, max_length=300)
    external_folio: str | None = Field(None, max_length=120)


AUTHORITY_FIELDS = (
    "id", "folio", "direction", "kind", "level", "authority_name", "authority_type", "case_number", "legal_basis",
    "requested_data", "targets", "involves_minor", "life_risk", "judicial_order", "participant_consent", "received_at",
    "due_at", "first_response_due_at", "authenticity_verified", "authenticity_method", "legal_review", "status",
    "decision", "response_summary", "responded_at", "user_notified", "notice_withheld_reason", "external_folio",
    "evidence_ids", "content_report_id", "handled_by_id", "created_by_id", "created_at", "updated_at",
)
LEVEL_RULES = {
    1: "Oficio fundado y motivado de autoridad competente (LFPDPPP arts. 9 fr. VII y 36 fr. V).",
    2: "Autorización judicial (Constitución art. 16; CNPP art. 291) o que una persona participante la aporte.",
    3: "Orden del Juez de control o, en los casos del CNPP art. 303, requerimiento del Ministerio Público con ratificación judicial.",
}


def _authority_row(item: AuthorityRequest) -> dict:
    row = {f: getattr(item, f) for f in AUTHORITY_FIELDS}
    row["level_rule"] = LEVEL_RULES.get(item.level)
    row["overdue"] = (item.status in ("recibido", "en_revision", "pendiente_denuncia")
                      and bool(item.first_response_due_at and item.first_response_due_at < _now()))
    return row


def _check_delivery(item: AuthorityRequest) -> None:
    """Tres niveles de entrega (autoridades.html §3): sin el requisito del nivel no se entrega. El nivel sale también
    del tipo de información, para que un nivel guardado más bajo no lo rebaje."""
    level = effective_level(item.kind, item.level)
    if item.direction == "entrante" and level is None:
        raise HTTPException(status_code=400, detail=(
            "Antes de entregar, indica el nivel de la información (1 datos de la cuenta, 2 comunicaciones, 3 ubicación)."))
    if level == 2 and not (item.judicial_order or item.participant_consent):
        raise HTTPException(status_code=400, detail=(
            "El contenido de comunicaciones solo se entrega con autorización judicial o si una persona participante "
            "lo aporta. Preserva la evidencia y responde por escrito."))
    if level == 3 and not (item.judicial_order or "303" in (item.legal_basis or "")):
        raise HTTPException(status_code=400, detail=(
            "La ubicación solo se entrega con orden del Juez de control o con el requerimiento del CNPP art. 303 "
            "(anótalo en el fundamento y da seguimiento a la ratificación judicial)."))
    if item.direction == "entrante" and not item.authenticity_verified:
        raise HTTPException(status_code=400, detail="Antes de entregar, verifica que el requerimiento sea auténtico.")


@router.get("/admin/cumplimiento/autoridades")
def list_authority_requests(estado: str = Query("open"), admin_user: User = Depends(require_admin),
                            db: Session = Depends(get_db)):
    query = db.query(AuthorityRequest)
    if estado == "open":
        query = query.filter(AuthorityRequest.status.notin_(("cerrado", "rechazado", "entregado", "denunciado")))
    elif estado != "all":
        query = query.filter(AuthorityRequest.status == estado)
    rows = query.order_by(AuthorityRequest.first_response_due_at.asc().nullslast(), AuthorityRequest.id.desc()).limit(200).all()
    return [_authority_row(r) for r in rows]


@router.post("/admin/cumplimiento/autoridades", status_code=status.HTTP_201_CREATED)
def create_authority_request(payload: AuthorityIn, request: Request, admin_user: User = Depends(require_admin),
                             db: Session = Depends(get_db)):
    now = _now()
    received = payload.received_at or now
    if received.tzinfo is not None:
        received = received.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    due = payload.due_at.astimezone(datetime.timezone.utc).replace(tzinfo=None) if payload.due_at and payload.due_at.tzinfo else payload.due_at
    if (payload.direction == "entrante" and payload.kind in LEVEL_REQUIRED_KINDS and payload.level is None):
        raise HTTPException(status_code=400, detail=(
            "Indica el nivel de la información que se pide: 1 datos de la cuenta, 2 contenido de comunicaciones, "
            "3 ubicación."))
    urgent = payload.involves_minor or payload.life_risk
    first = received + (datetime.timedelta(minutes=settings.authority_first_response_urgent_minutes) if urgent
                        else datetime.timedelta(hours=settings.authority_first_response_hours))
    item = AuthorityRequest(
        folio=lm.new_folio("AUT"), direction=payload.direction, kind=payload.kind,
        level=effective_level(payload.kind, payload.level), authority_name=payload.authority_name.strip(),
        authority_type=payload.authority_type, case_number=payload.case_number, legal_basis=payload.legal_basis,
        requested_data=payload.requested_data, targets=[t.model_dump() for t in payload.targets] or None,
        involves_minor=payload.involves_minor, life_risk=payload.life_risk, judicial_order=payload.judicial_order,
        participant_consent=payload.participant_consent, received_at=received, due_at=due, first_response_due_at=first,
        authenticity_verified=payload.authenticity_verified, authenticity_method=payload.authenticity_method,
        legal_review=payload.legal_review, external_folio=payload.external_folio,
        status="pendiente_denuncia" if payload.direction == "saliente" else "recibido",
        handled_by_id=admin_user.id, created_by_id=admin_user.id, created_at=now, updated_at=now,
    )
    db.add(item)
    db.flush()
    record_admin_action(db, admin_user, "authority.create", "authority_request", item.id,
                        {"folio": item.folio, "kind": item.kind, "level": item.level, "authority": item.authority_name,
                         "case_number": item.case_number, "targets": item.targets}, request)
    db.commit()
    return _authority_row(item)


@router.patch("/admin/cumplimiento/autoridades/{id}")
def update_authority_request(id: int, payload: AuthorityUpdate, request: Request,
                             admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.query(AuthorityRequest).filter(AuthorityRequest.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="No encontramos ese requerimiento.")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key == "due_at" and value is not None and value.tzinfo is not None:
            value = value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        if key == "level":
            if value is None:
                continue
            value = max(value, item.level or 1)  # un nivel ya fijado no se rebaja
            value = effective_level(item.kind, value)
        setattr(item, key, value)
    if changes.get("status") in ("entregado", "entregado_parcial"):
        _check_delivery(item)
        item.responded_at = item.responded_at or _now()
    if changes.get("status") in ("rechazado", "denunciado", "incompleto") and not item.responded_at:
        item.responded_at = _now()
    item.handled_by_id = admin_user.id
    item.updated_at = _now()
    record_admin_action(db, admin_user, "authority.update", "authority_request", item.id,
                        {"folio": item.folio, **{k: (str(v) if isinstance(v, datetime.datetime) else v)
                                                for k, v in changes.items()}}, request)
    db.commit()
    return _authority_row(item)


def _preservation_snapshot(db: Session, ref: dict):
    """(objeto, archivos, extra) de una cuenta o contenido para una orden de conservación."""
    ttype, tid = ref["type"], ref["id"]
    if ttype == "user":
        user = db.query(User).filter(User.id == tid).first()
        if user is None:
            return None, None
        extra = {
            "dogs": [evidence.row_data(d) for d in db.query(Dog).filter(Dog.owner_id == tid).all()],
            "lost_reports": [evidence.row_data(r) for r in db.query(LostReport).filter(LostReport.reporter_id == tid).all()],
            "products": [evidence.row_data(p) for p in db.query(Product).join(Refuge, Refuge.id == Product.refuge_id)
                         .filter(Refuge.user_id == tid).all()],
            # Contenido de comunicaciones: se preserva aquí y solo se entrega con autorización judicial (nivel 2)
            "messages": [evidence.row_data(m) for m in db.query(Message).filter(Message.sender_id == tid)
                         .order_by(Message.id.desc()).limit(5000).all()],
        }
        return user, extra
    if ttype == "conversation":
        from app.models import Conversation

        conv = db.query(Conversation).filter(Conversation.id == tid).first()
        if conv is None:
            return None, None
        msgs = db.query(Message).filter(Message.conversation_id == tid).order_by(Message.id).limit(5000).all()
        return conv, {"messages": [evidence.row_data(m) for m in msgs]}
    return moderation.load_target(db, ttype, tid), None


@router.post("/admin/cumplimiento/autoridades/{id}/preservar")
def preserve_for_authority(id: int, request: Request, admin_user: User = Depends(require_admin),
                           db: Session = Depends(get_db)):
    """Orden de conservación (CNPP art. 303, último párrafo): retención legal inmediata de la evidencia existente y
    copia cifrada de las cuentas o contenidos señalados. No borra nada aunque la persona elimine su cuenta."""
    item = db.query(AuthorityRequest).filter(AuthorityRequest.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="No encontramos ese requerimiento.")
    if not item.targets:
        raise HTTPException(status_code=400, detail="Agrega las cuentas o contenidos que la autoridad pidió conservar.")
    reason = f"Orden de conservación {item.folio} ({item.authority_name}, expediente {item.case_number or 's/n'})"
    held = evidence.hold_for_targets(db, item.targets, reason, admin_user.id, authority_request_id=item.id)
    created = []
    for ref in item.targets:
        obj, extra = _preservation_snapshot(db, ref)
        if obj is None:
            continue
        owner_id = ref["id"] if ref["type"] == "user" else moderation.owner_id(db, ref["type"], obj)
        record = evidence.capture(
            db, kind="preservacion", target_type=ref["type"], target_id=ref["id"], obj=obj, owner_user_id=owner_id,
            reason="orden_conservacion", extra=extra, legal_hold_reason=reason, authority_request_id=item.id,
            decision={"authority_request": item.folio, "actor_id": admin_user.id}, actor_id=admin_user.id,
        )
        created.append(record.id)
    item.evidence_ids = sorted(set((item.evidence_ids or []) + held + created))
    if item.status in ("recibido", "en_revision"):
        item.status = "preservado"
    item.updated_at = _now()
    record_admin_action(db, admin_user, "authority.preserve", "authority_request", item.id,
                        {"folio": item.folio, "held": held, "created": created}, request)
    db.commit()
    return {"ok": True, "retenidas": held, "copias_nuevas": created, "requerimiento": _authority_row(item)}


# =========================================================================== administración: evidencia
CSAM_EXPORT_NOTE = ("No se exporta: el material de abuso sexual infantil nunca se descarga. Se entrega al Ministerio "
                    "Público conforme a sus instrucciones, directamente desde la bóveda cifrada; aquí van sus huellas "
                    "SHA-256 para cotejarlo.")


class HoldIn(BaseModel):
    legal_hold: bool
    motivo: str | None = Field(None, max_length=300)


class ReleaseIn(BaseModel):
    motivo: str = Field(..., min_length=10, max_length=2000)


@router.get("/admin/cumplimiento/evidencia")
def list_evidence(target_type: str | None = None, target_id: int | None = None, csam: bool | None = None,
                  skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                  admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Solo metadatos (nunca el contenido)."""
    query = db.query(EvidenceRecord)
    if target_type:
        query = query.filter(EvidenceRecord.target_type == target_type)
    if target_id is not None:
        query = query.filter(EvidenceRecord.target_id == target_id)
    if csam is not None:
        query = query.filter(EvidenceRecord.is_csam == csam)
    return [evidence.metadata(r) for r in query.order_by(EvidenceRecord.id.desc()).offset(skip).limit(limit).all()]


@router.get("/admin/cumplimiento/evidencia/verificar")
def verify_evidence_chain(request: Request, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    out = evidence.verify_chain(db)
    record_admin_action(db, admin_user, "evidence.verify", "evidence_record", None, out, request)
    db.commit()
    return out


@router.post("/admin/cumplimiento/evidencia/{id}/retencion")
def set_evidence_hold(id: int, payload: HoldIn, request: Request, admin_user: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    record = db.query(EvidenceRecord).filter(EvidenceRecord.id == id).first()
    if not record:
        raise HTTPException(status_code=404, detail="No encontramos esa evidencia.")
    if record.is_csam and not payload.legal_hold and admin_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Solo un superadmin libera la retención de material en cuarentena.")
    try:
        evidence.set_legal_hold(db, record, payload.legal_hold, payload.motivo, admin_user.id)
    except evidence.EvidenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_admin_action(db, admin_user, "evidence.hold" if payload.legal_hold else "evidence.release", "evidence_record",
                        record.id, {"motivo": payload.motivo}, request)
    db.commit()
    return evidence.metadata(record)


@router.get("/admin/cumplimiento/evidencia/{id}/exportar")
def export_evidence(id: int, request: Request, requerimiento: str | None = Query(None, max_length=24),
                    admin_user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    """Exportación para entregar a una autoridad (superadmin): paquete con hashes y cadena de custodia. Se descarga como
    archivo; el material en cuarentena solo se exporta ligado a su requerimiento o denuncia."""
    record = db.query(EvidenceRecord).filter(EvidenceRecord.id == id).first()
    if not record:
        raise HTTPException(status_code=404, detail="No encontramos esa evidencia.")
    authority = (db.query(AuthorityRequest).filter(AuthorityRequest.folio == requerimiento.strip().upper()).first()
                 if requerimiento else None)
    if record.is_csam and (authority is None or record.id not in (authority.evidence_ids or [])):
        raise HTTPException(status_code=403, detail=(
            "El material en cuarentena solo se exporta para la denuncia o el requerimiento al que está ligado."))
    if record.is_csam:
        # Nunca se descarga el material (gap-nna §3.6): solo metadatos, huellas y cadena de custodia. El original se
        # entrega al Ministerio Público según sus instrucciones, directo desde la bóveda.
        bundle = {"material": CSAM_EXPORT_NOTE, "target": {"type": record.target_type, "id": record.target_id},
                  "archivos": [{k: f.get(k) for k in ("name", "sha256", "bytes")} for f in (record.files or [])],
                  "content_sha256": record.content_sha256, "row_hash": record.row_hash, "prev_hash": record.prev_hash}
    else:
        try:
            bundle = evidence.read_bundle(record)
        except evidence.EvidenceError as exc:
            raise HTTPException(status_code=410, detail=str(exc))
    custody = {"exported_at": _now().isoformat(), "exported_by": admin_user.id, "authority_request": requerimiento,
               "record": {k: (v.isoformat() if isinstance(v, datetime.datetime) else v)
                          for k, v in evidence.metadata(record).items()}}
    record_admin_action(db, admin_user, "evidence.export", "evidence_record", record.id,
                        {"authority_request": requerimiento, "content_sha256": record.content_sha256}, request)
    db.commit()
    body = json.dumps({"cadena_de_custodia": custody, "paquete": bundle}, ensure_ascii=False, default=str)
    return Response(content=body, media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="evidencia-{record.id}.json"',
        "Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"})


@router.post("/admin/cumplimiento/evidencia/{id}/liberar-cuarentena")
def release_quarantine(id: int, payload: ReleaseIn, request: Request, admin_user: User = Depends(require_superadmin),
                       db: Session = Depends(get_db)):
    """Cuarentena equivocada (reporte falso): restaura los archivos y deja el contenido oculto para revisión normal."""
    record = db.query(EvidenceRecord).filter(EvidenceRecord.id == id).first()
    if not record or not record.is_csam:
        raise HTTPException(status_code=404, detail="No encontramos esa cuarentena.")
    try:
        out = lm.release_quarantine(db, record, admin_user, payload.motivo)
    except evidence.EvidenceError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    record_admin_action(db, admin_user, "content.quarantine_release", record.target_type, record.target_id,
                        {"evidence_id": record.id, "motivo": payload.motivo, **out}, request)
    db.commit()
    return out
