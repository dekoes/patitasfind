"""Consentimiento: registro de versiones, aceptaciones, preferencias y verificación de edad.

Públicos:   GET  /cumplimiento/documentos                     registro de versiones (historial.js)
Con sesión: GET  /cumplimiento/pendientes                     documentos por aceptar, avisos de 30 días, edad
            POST /cumplimiento/aceptaciones                   {slug, version, sha256}: aceptación expresa
            GET  /cumplimiento/aceptaciones/mias              mi bitácora
            GET|PATCH /cumplimiento/preferencias              {notify_nearby, whatsapp_alerts, email_marketing}
            POST /cumplimiento/preferencias/cookies           {analytics}: constancia de la elección del banner
            GET  /cumplimiento/edad · POST /cumplimiento/edad/codigo · POST /cumplimiento/edad/verificar
Admin:      /admin/cumplimiento/aceptaciones[/verificar], /admin/cumplimiento/consentimientos,
            /admin/cumplimiento/edad[/{user_id}/solicitar|liberar], /admin/cumplimiento/documentos[/sincronizar]
"""
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import client_ip, get_current_user, require_admin
from app.models import AgeCheck, ConsentRecord, LegalAcceptance, LegalDocument, User
from app.services import age_check, consent, legal_acceptance as la, ratelimit

router = APIRouter(tags=["cumplimiento"])


class AcceptancePayload(BaseModel):
    slug: str = Field(max_length=80)
    version: str = Field(max_length=20)
    sha256: str = Field(min_length=64, max_length=64)


class PreferencesPatch(BaseModel):
    notify_nearby: bool | None = None
    whatsapp_alerts: bool | None = None
    email_marketing: bool | None = None


class CookieChoice(BaseModel):
    analytics: bool


class AgeVerifyPayload(BaseModel):
    birth_date: datetime.date
    code: str = Field(max_length=10)
    declaration: bool = False


class AdminNote(BaseModel):
    note: str | None = Field(None, max_length=1000)


# --------------------------------------------------------------------------- registro de versiones
@router.get("/cumplimiento/documentos")
def list_documents(db: Session = Depends(get_db)):
    """Cada documento con su versión vigente, la próxima (si hay aviso previo) y el historial con SHA-256."""
    docs = la.registry(db)
    source = "registro"
    if not docs:
        # Antes del primer sync se muestra lo que trae versiones.json (sin historial)
        source = "archivo"
        for e in la.load_entries():
            item = {**{k: e[k] for k in ("slug", "title", "version", "sha256", "effective_at", "requires_reacceptance",
                                         "summary", "url")}, "id": None, "published_at": None, "status": "vigente"}
            docs.append({"slug": e["slug"], "title": e["title"], "url": e["url"],
                         "requires_reacceptance": e["requires_reacceptance"], "vigente": item, "proxima": None,
                         "versiones": [item]})
    body = {"generated_at": datetime.datetime.utcnow(), "source": source, "documentos": docs}
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(content=jsonable_encoder(body), headers={"Cache-Control": "public, max-age=300"})


# --------------------------------------------------------------------------- aceptaciones
def _signup_incomplete(user: User) -> bool:
    if user.role in la.ADMIN_ROLES or user.is_phone_exempt:
        return False
    return user.terms_accepted_at is None or not user.age_declared


@router.get("/cumplimiento/pendientes")
def pending(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = la.pending_for(db, current_user)
    prefs = consent.preferences_out(db, current_user)
    return {
        **data,
        "completar_registro": _signup_incomplete(current_user),
        "verificacion_edad": age_check.status_for(db, current_user) if current_user.age_check_required else None,
        "invitar_alertas": prefs["invite_nearby"] and current_user.role not in la.ADMIN_ROLES,
    }


@router.post("/cumplimiento/aceptaciones")
def accept_document(payload: AcceptancePayload, request: Request, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Aceptación expresa de una versión publicada (vigente o próxima) de un documento del registro."""
    ratelimit.check(f"legal-accept:{current_user.id}", 60, 3600)
    slug = payload.slug.strip().lower()
    if not la.SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Documento no válido.")
    if slug == la.AGE_SLUG:
        raise HTTPException(status_code=400, detail="La declaración de edad se hace al registrarte o al confirmar tu edad.")
    if db.query(LegalDocument.id).filter(LegalDocument.slug == slug).first() is None:
        raise HTTPException(status_code=404, detail="No encontramos ese documento en el registro de versiones.")
    previous = la.accepted_versions(db, current_user.id, [slug]).get(slug)
    method = "anexo" if (slug in la.ALL_ANNEX_SLUGS and not previous) else "reaceptacion"
    entry = la.record_acceptance(db, current_user, slug, method, request, version=payload.version,
                                 sha256=payload.sha256.lower(), context={"origen": "app"})
    db.commit()
    return {
        "ok": True,
        "aceptacion": {"slug": entry.slug, "version": entry.version, "sha256": entry.sha256,
                       "accepted_at": entry.accepted_at, "method": entry.method, "row_hash": entry.row_hash},
        **la.pending_for(db, current_user),
    }


@router.get("/cumplimiento/aceptaciones/mias")
def my_acceptances(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"aceptaciones": la.acceptances_for_export(db, current_user.id)}


# --------------------------------------------------------------------------- preferencias
@router.get("/cumplimiento/preferencias")
def get_preferences(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return consent.preferences_out(db, current_user)


@router.patch("/cumplimiento/preferencias")
def update_preferences(payload: PreferencesPatch, request: Request, current_user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Los cambios son inmediatos; cada uno agrega una constancia (propósito, sí/no, versión del texto, canal, IP)."""
    ratelimit.check(f"prefs:{current_user.id}", 60, 3600)
    changes = payload.model_dump(exclude_unset=True)
    for purpose in ("notify_nearby", "whatsapp_alerts", "email_marketing"):
        if changes.get(purpose) is not None:
            consent.set_preference(db, current_user, purpose, changes[purpose], channel="app", request=request)
    db.commit()
    db.refresh(current_user)
    return consent.preferences_out(db, current_user)


@router.post("/cumplimiento/preferencias/cookies")
def record_cookie_choice(payload: CookieChoice, request: Request, current_user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Constancia de la elección del banner de cookies (la elección en sí vive en el navegador: patitas_consent)."""
    ratelimit.check(f"cookies:{current_user.id}", 30, 3600)
    last = consent.latest_records(db, current_user.id).get("analytics_cookies")
    if last is None or last.granted != payload.analytics or last.text_version != consent.text_version("analytics_cookies"):
        consent.record_consent(db, current_user, "analytics_cookies", payload.analytics, "web", request)
        db.commit()
    return {"ok": True, "analytics": payload.analytics}


# --------------------------------------------------------------------------- verificación reforzada de edad
@router.get("/cumplimiento/edad")
def age_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return age_check.status_for(db, current_user)


@router.post("/cumplimiento/edad/codigo")
def age_send_code(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return age_check.send_code(db, current_user, client_ip(request))


@router.post("/cumplimiento/edad/verificar")
def age_verify(payload: AgeVerifyPayload, request: Request, current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    ratelimit.check(f"age-verify:{current_user.id}", 10, 3600)
    return age_check.complete(db, current_user, payload.birth_date, payload.code, payload.declaration, request)


# --------------------------------------------------------------------------- administración
def _user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No encontramos esa cuenta.")
    return user


@router.get("/admin/cumplimiento/aceptaciones/verificar")
def admin_verify_chain(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Recalcula la cadena de huellas de toda la bitácora y dice si el trigger de solo inserción está activo."""
    return {**la.verify_chain(db), "append_only_trigger": la.append_only_active(db)}


@router.get("/admin/cumplimiento/aceptaciones")
def admin_acceptances(user_id: int | None = Query(None), slug: str | None = Query(None, max_length=80),
                      limit: int = Query(100, ge=1, le=500), admin: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    q = db.query(LegalAcceptance)
    if user_id is not None:
        q = q.filter(LegalAcceptance.user_id == user_id)
    if slug:
        q = q.filter(LegalAcceptance.slug == slug)
    rows = q.order_by(LegalAcceptance.id.desc()).limit(limit).all()
    return [{"id": r.id, "user_id": r.user_id, "slug": r.slug, "version": r.version, "sha256": r.sha256,
             "accepted_at": r.accepted_at, "ip": r.ip, "user_agent": r.user_agent, "method": r.method,
             "context": r.context, "row_hash": r.row_hash} for r in rows]


@router.get("/admin/cumplimiento/consentimientos")
def admin_consents(user_id: int | None = Query(None), purpose: str | None = Query(None, max_length=40),
                   limit: int = Query(100, ge=1, le=500), admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    q = db.query(ConsentRecord)
    if user_id is not None:
        q = q.filter(ConsentRecord.user_id == user_id)
    if purpose:
        q = q.filter(ConsentRecord.purpose == purpose)
    rows = q.order_by(ConsentRecord.id.desc()).limit(limit).all()
    return [{"id": r.id, "user_id": r.user_id, "phone": r.phone, "purpose": r.purpose, "granted": r.granted,
             "text_version": r.text_version, "channel": r.channel, "ip": r.ip, "created_at": r.created_at}
            for r in rows]


@router.get("/admin/cumplimiento/edad")
def admin_age_checks(status_filter: str = Query("required", alias="status", pattern="^(required|review|passed|cleared|failed|all)$"),
                     limit: int = Query(100, ge=1, le=500), admin: User = Depends(require_admin),
                     db: Session = Depends(get_db)):
    q = db.query(AgeCheck, User).join(User, User.id == AgeCheck.user_id)
    if status_filter != "all":
        q = q.filter(AgeCheck.status == status_filter)
    rows = q.order_by(AgeCheck.created_at.desc()).limit(limit).all()
    return [{"id": c.id, "user_id": u.id, "full_name": u.full_name, "email": u.email, "status": c.status,
             "reason": c.reason, "reason_label": age_check.REASON_LABELS.get(c.reason), "note": c.note,
             "content_report_id": c.content_report_id, "attempts": c.attempts, "method": c.method,
             "created_at": c.created_at, "resolved_at": c.resolved_at} for c, u in rows]


@router.post("/admin/cumplimiento/edad/{user_id}/solicitar")
def admin_require_age_check(user_id: int, payload: AdminNote, request: Request, admin: User = Depends(require_admin),
                            db: Session = Depends(get_db)):
    """Pide la verificación reforzada (la cuenta queda limitada hasta completarla)."""
    check = age_check.admin_require(db, _user_or_404(db, user_id), admin, payload.note, request)
    return {"ok": True, "age_check_id": check.id, "status": check.status}


@router.post("/admin/cumplimiento/edad/{user_id}/liberar")
def admin_clear_age_check(user_id: int, payload: AdminNote, request: Request, admin: User = Depends(require_admin),
                          db: Session = Depends(get_db)):
    closed = age_check.admin_clear(db, _user_or_404(db, user_id), admin, payload.note, request)
    return {"ok": True, "closed": closed}


@router.get("/admin/cumplimiento/documentos")
def admin_documents(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(LegalDocument).order_by(LegalDocument.slug, LegalDocument.published_at.desc()).all()
    return [{**la.doc_out(r), "notice_sent_at": r.notice_sent_at} for r in rows]


@router.post("/admin/cumplimiento/documentos/sincronizar")
def admin_sync_documents(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.audit import record_admin_action

    result = la.sync_from_file(db)
    record_admin_action(db, admin, "legal_documents.sync", "legal_document", None,
                        {"created": result["created"], "updated": result["updated"]}, request)
    db.commit()
    return result
