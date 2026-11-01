import csv
import datetime
import hashlib
import io
import json
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.data import estados_mx
from app.database import get_db
from app.dependencies import client_ip, get_optional_user, get_verified_user, require_admin
from app.models import FacebookGroup, LostReport, User
from app.schemas import (
    AuthorRemovalRequest, FacebookGroupCreate, FacebookGroupOut, FacebookGroupUpdate, FacebookImportRequest,
    FacebookPublicGroupCreate, LostReportAdminOut, LostReportPrivateOut, VolunteerImportRequest,
)
from app.services import facebook_groups as fbg
from app.services import ratelimit
from app.services.audit import record_admin_action
from app.services.background import dispatch
from app.services.facebook_monitor import (
    FacebookImportDisabled, FacebookNotConfigured, create_report_from_post, find_by_post_url, ingest_page,
)

router = APIRouter(tags=["facebook"])

NOT_CONFIGURED = "La lectura de Páginas de Facebook no está configurada (falta FACEBOOK_PAGE_ACCESS_TOKEN)."
GROUPS_NOT_CONFIGURED = "Proveedor no configurado (APIFY_TOKEN)"
# Interruptor legal (config.py): sin FB_GROUPS_ENABLED=true no se importa nada aunque haya APIFY_TOKEN
GROUPS_DISABLED = "Importación de grupos apagada (FB_GROUPS_ENABLED=false)"
VOLUNTEER_DAILY_LIMIT = 10
DUPLICATE_POST = "Esa publicación ya está en GuauWoow. ¡Gracias por ayudar!"
CONSENT_REQUIRED = ("Confirma que la publicación es pública, que no incluyes datos de contacto de otras personas y "
                    "que GuauWoow puede retirarla a petición de su autor.")
# Retiro sin cuenta: por IP, para que no se use para ocultar reportes en masa
AUTHOR_REMOVAL_HOURLY_LIMIT = 5
AUTHOR_REMOVAL_DAILY_LIMIT = 20
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
CSV_MAX_BYTES = 1024 * 1024
CSV_MAX_ROWS = 2000
# "active" es opcional: los grupos nuevos se crean PAUSADOS salvo que la fila diga sí/1/true
CSV_COLUMNS = ("name", "state", "city", "group_url", "active")
# Encabezados aceptados en español (se traducen a los de arriba)
CSV_ALIASES = {"nombre": "name", "estado": "state", "ciudad": "city", "url": "group_url", "url_grupo": "group_url",
               "enlace": "group_url", "municipio": "city", "activo": "active", "is_active": "active"}
CSV_TRUE = {"1", "si", "sí", "true", "verdadero", "x", "yes", "activo"}
CSV_FALSE = {"0", "no", "false", "falso", "pausado", ""}



def _groups_message() -> str | None:
    """Motivo por el que no se leen grupos (None = importación activa)."""
    if not settings.fb_groups_provider_configured:
        return GROUPS_NOT_CONFIGURED
    if not settings.fb_groups_enabled:
        return GROUPS_DISABLED
    return None

@router.get("/facebook/groups", response_model=list[FacebookGroupOut])
def list_facebook_sources(admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(FacebookGroup).order_by(FacebookGroup.created_at.desc()).all()


@router.get("/facebook/status")
def facebook_status(admin_user: User = Depends(require_admin)):
    return {
        "pages_enabled": settings.facebook_enabled, "graph_api_version": settings.graph_api_version,
        "groups_enabled": settings.fb_groups_active,
        "groups_message": _groups_message(),
    }


@router.post("/facebook/groups", response_model=FacebookGroupOut, status_code=status.HTTP_201_CREATED)
def create_facebook_source(payload: FacebookGroupCreate, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    kind = payload.kind or ("page" if payload.page_id else "manual")
    if kind not in ("page", "manual"):
        raise HTTPException(status_code=400, detail="kind debe ser 'page' o 'manual'. Los grupos públicos se dan de alta en /admin/facebook/groups.")
    if kind == "page" and not payload.page_id:
        raise HTTPException(status_code=400, detail="Para una Página indica su page_id (ID numérico o alias).")
    source = FacebookGroup(name=payload.name, url=payload.url, page_id=payload.page_id, kind=kind, city=payload.city)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/facebook/groups/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_facebook_source(id: int, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    source = db.query(FacebookGroup).filter(FacebookGroup.id == id).first()
    if not source:
        raise HTTPException(status_code=404, detail="No encontramos esa fuente.")
    db.delete(source)
    db.commit()
    return None


def _match_new(report_ids, background_tasks):
    for rid in report_ids:
        dispatch("app.tasks.matching.match_lost_report", rid, background_tasks=background_tasks)


@router.post("/facebook/scrape")
def scrape_facebook_source(group_id: int, background_tasks: BackgroundTasks, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not settings.fb_groups_enabled:
        raise HTTPException(status_code=409, detail=GROUPS_DISABLED)
    source = db.query(FacebookGroup).filter(FacebookGroup.id == group_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="No encontramos esa fuente.")
    try:
        created = ingest_page(db, source)
    except FacebookImportDisabled:
        raise HTTPException(status_code=409, detail=GROUPS_DISABLED)
    except FacebookNotConfigured:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    _match_new(created, background_tasks)
    return {
        "group_id": group_id,
        "images_found": len(created),
        "reports_created": len(created),
        "report_ids": created,
        "message": f"Listo. {len(created)} reportes nuevos creados desde {source.name}.",
    }


@router.post("/facebook/scrape-all")
def scrape_all_facebook_sources(background_tasks: BackgroundTasks, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not settings.fb_groups_enabled:
        raise HTTPException(status_code=409, detail=GROUPS_DISABLED)
    if not settings.facebook_enabled:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    sources = db.query(FacebookGroup).filter(FacebookGroup.is_active == True, FacebookGroup.kind == "page").all()  # noqa: E712
    created, errors = [], []
    for source in sources:
        try:
            created += ingest_page(db, source)
        except FacebookImportDisabled:
            raise HTTPException(status_code=409, detail=GROUPS_DISABLED)
        except (ValueError, RuntimeError) as exc:
            errors.append({"source_id": source.id, "error": str(exc)})
    _match_new(created, background_tasks)
    return {
        "groups_processed": len(sources),
        "total_reports_created": len(created),
        "errors": errors,
        "message": f"Procesadas {len(sources)} páginas. {len(created)} reportes creados.",
    }


@router.post("/facebook/import", response_model=LostReportAdminOut, status_code=status.HTTP_201_CREATED)
def manual_import(payload: FacebookImportRequest, background_tasks: BackgroundTasks, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if payload.report_type not in ("lost", "found"):
        raise HTTPException(status_code=400, detail="report_type debe ser 'lost' o 'found'.")
    if not payload.text.strip() and not payload.image_urls:
        raise HTTPException(status_code=400, detail="Pega al menos el texto o una foto de la publicación.")
    report = create_report_from_post(
        db, text=payload.text, image_urls=payload.image_urls, report_type=payload.report_type,
        city=payload.city, state=payload.state, post_url=payload.post_url, require_dog=False,
    )
    if report is None:
        raise HTTPException(status_code=409, detail="Esa publicación ya fue importada.")
    _match_new([report.id], background_tasks)
    return report


# --------------------------------------------------------------------------- voluntarios
@router.post("/facebook/volunteer-import", response_model=LostReportPrivateOut, status_code=status.HTTP_201_CREATED)
def volunteer_import(payload: VolunteerImportRequest, background_tasks: BackgroundTasks,
                     current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    """Un voluntario comparte una publicación de Facebook: se vuelve un reporte (fuente "volunteer") a su nombre."""
    # La raíz de un grupo, un perfil o el inicio no son una publicación (y bloquearían ese enlace para siempre)
    problem = fbg.post_url_problem(payload.url)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    post_url = fbg.normalize_post_url(payload.url)
    existing = find_by_post_url(db, post_url)
    if existing:
        return _duplicate(existing)
    if not payload.consent:
        raise HTTPException(status_code=400, detail=CONSENT_REQUIRED)
    if not fbg.strip_pii(payload.text) and not payload.photos:
        raise HTTPException(status_code=400, detail="Pega el texto de la publicación o agrega al menos una foto.")
    ratelimit.check(f"fb-volunteer:{current_user.id}", VOLUNTEER_DAILY_LIMIT, 86400,
                    detail=f"Llegaste al límite de {VOLUNTEER_DAILY_LIMIT} publicaciones por día. Gracias por ayudar; vuelve mañana.")
    try:
        report = fbg.create_volunteer_report(
            db, current_user, url=post_url, text=payload.text, city=payload.city, state=payload.state,
            report_type=payload.report_type, photos=payload.photos, consent_version=settings.legal_terms_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if report is None:  # otra persona la mandó al mismo tiempo (índice único): se muestra la que ganó
        existing = find_by_post_url(db, post_url)
        if existing:
            return _duplicate(existing)
        raise HTTPException(status_code=409, detail=DUPLICATE_POST)
    _match_new([report.id], background_tasks)
    # Hay una persona responsable: se avisa como a un reporte de la app. Sin coordenadas, la alerta llega a
    # refugios y casas de paso de la ciudad (no a vecinos por distancia). No dispara la lectura de grupos.
    dispatch("app.tasks.notifications.notify_nearby_report", report.id, background_tasks=background_tasks)
    return report


def _duplicate(existing: LostReport) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": DUPLICATE_POST, "report_id": existing.id})


# --------------------------------------------------------------------------- retiro sin cuenta (autor)
@router.post("/facebook/author-removal", status_code=status.HTTP_201_CREATED)
def author_removal(payload: AuthorRemovalRequest, request: Request, response: Response,
                   viewer: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """«Soy el autor: retirar o reclamar» para una publicación importada de Facebook, sin cuenta.

    Entra al centro de solicitudes (retiro_importado, services/solicitudes.py) con las mismas reglas que el
    formulario de contenido-importado.html §8: se oculta al momento si la pide la persona autora o quien aparece;
    el borrado de su texto y fotos en menos de 72 h es para la persona autora que confirma su correo (o llega con su
    cuenta). «Otro» solo entra a la cola de moderación.
    """
    from app.services import solicitudes as sol

    ip = client_ip(request)
    ratelimit.check(f"fb-author-removal:h:{ip}", AUTHOR_REMOVAL_HOURLY_LIMIT, 3600,
                    detail="Enviaste varias solicitudes seguidas. Espera una hora o escríbenos al correo de privacidad.")
    ratelimit.check(f"fb-author-removal:d:{ip}", AUTHOR_REMOVAL_DAILY_LIMIT, 86400,
                    detail="Llegaste al límite de solicitudes por hoy. Escríbenos al correo de privacidad.")
    email = payload.email.strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Escribe un correo válido para poder responderte.")
    if not payload.report_id and not (payload.url or "").strip():
        raise HTTPException(status_code=400, detail="Indica el reporte o pega el enlace de tu publicación.")
    report = fbg.find_imported_report(db, payload.report_id, payload.url)
    if report is None:
        raise HTTPException(status_code=404, detail="No encontramos esa publicación en GuauWoow.")
    if not fbg.is_imported(report):
        raise HTTPException(status_code=400, detail=(
            "Este formulario es solo para publicaciones importadas de Facebook. Para otros reportes usa «Reportar»."))
    if viewer is None:
        # Acuse y enlace de confirmación a una misma dirección: tope diario (el mismo del centro de solicitudes)
        from app.routers.cumplimiento_solicitudes import CREATE_PER_DAY_EMAIL

        key = hashlib.sha256(sol.normalize_email(email).encode()).hexdigest()[:32]
        ratelimit.check(f"solicitud:email:d:{key}", CREATE_PER_DAY_EMAIL, 86400,
                        detail="Ya recibimos varias solicitudes con ese correo hoy. Revisa tu bandeja.")
    comment = (payload.details or "").strip()
    name = (viewer.full_name or "").strip() if viewer else ""
    try:
        req = sol.create_solicitud(
            db, kind="retiro_importado", name=name if len(name) >= 3 else "Persona sin cuenta",
            description=("Retiro pedido con «Soy el autor: retirar o reclamar» en la app."
                         + (f" Comentario: {comment}" if comment else "")),
            email=email, user=viewer, channel="app" if viewer else "web", details={"relacion": payload.relation},
            report_id=report.id, ip=ip, user_agent=request.headers.get("user-agent"),
        )
    except sol.SolicitudError as err:
        db.rollback()
        raise HTTPException(status_code=err.status_code, detail=err.detail)
    if getattr(req, "_duplicate", False):
        response.status_code = status.HTTP_200_OK
    return _removal_ack(req, report)


def _removal_ack(req, report: LostReport) -> dict:
    relation = (req.details or {}).get("relacion")
    confirmed = req.identity_verified_at is not None
    if relation == "autor":
        message = (f"Recibimos tu solicitud (folio {req.folio}). Ya ocultamos la publicación"
                   + (f" y borramos su texto y fotos en menos de {fbg.AUTHOR_REMOVAL_PURGE_HOURS} horas." if confirmed else
                      f". Abre el enlace que te enviamos por correo para confirmar que eres tú y borraremos su texto y "
                      f"fotos en menos de {fbg.AUTHOR_REMOVAL_PURGE_HOURS} horas."))
    elif relation == "aparezco":
        message = (f"Recibimos tu solicitud (folio {req.folio}). Ya ocultamos la publicación mientras la revisamos y te "
                   "respondemos en un máximo de 20 días hábiles.")
    else:
        message = f"Recibimos tu solicitud (folio {req.folio}). La revisaremos y te escribiremos."
    return {"folio": req.folio, "content_report_id": req.content_report_id, "report_id": report.id,
            "status": req.status, "requiere_confirmacion": not confirmed, "message": message}


# --------------------------------------------------------------------------- admin: grupos públicos
def _get_group(db: Session, group_id: int) -> FacebookGroup:
    group = db.query(FacebookGroup).filter(FacebookGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="No encontramos ese grupo.")
    return group


def _clean_state(value: str | None) -> str:
    state = estados_mx.normalize_state(value)
    if not state:
        raise ValueError(f"Estado no reconocido: «{(value or '').strip()[:60]}». Usa el nombre del estado (p. ej. Jalisco, Ciudad de México).")
    return state


def _clean_group_url(value: str | None) -> str:
    url = fbg.normalize_group_url(value)
    if not url:
        raise ValueError("La URL debe ser de un grupo de Facebook (https://www.facebook.com/groups/...).")
    return url


def _find_by_group_url(db: Session, group_url: str, exclude_id: int | None = None) -> FacebookGroup | None:
    q = db.query(FacebookGroup).filter(FacebookGroup.group_url == group_url)
    if exclude_id is not None:
        q = q.filter(FacebookGroup.id != exclude_id)
    return q.first()


@router.get("/admin/facebook/groups", response_model=list[FacebookGroupOut])
def admin_list_groups(
    kind: str = Query("group", description="group | page | manual | all"),
    state: str | None = Query(None),
    active: bool | None = Query(None),
    admin_user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    q = db.query(FacebookGroup)
    if kind != "all":
        q = q.filter(FacebookGroup.kind == kind)
    if state:
        q = q.filter(FacebookGroup.state == (estados_mx.normalize_state(state) or state))
    if active is not None:
        q = q.filter(FacebookGroup.is_active == active)
    return q.order_by(FacebookGroup.state.asc().nullsfirst(), FacebookGroup.name, FacebookGroup.id).all()


@router.post("/admin/facebook/groups", response_model=FacebookGroupOut, status_code=status.HTTP_201_CREATED)
def admin_create_group(payload: FacebookPublicGroupCreate, request: Request, admin_user: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    try:
        state = _clean_state(payload.state)
        group_url = _clean_group_url(payload.group_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if _find_by_group_url(db, group_url):
        raise HTTPException(status_code=409, detail="Ese grupo ya está dado de alta.")
    group = FacebookGroup(name=payload.name.strip(), url=group_url, group_url=group_url, kind="group", state=state,
                          city=(payload.city or "").strip() or None, is_active=payload.is_active, provider="apify")
    db.add(group)
    db.flush()
    record_admin_action(db, admin_user, "facebook_group.create", "facebook_group", group.id,
                        {"name": group.name, "state": state, "group_url": group_url}, request)
    db.commit()
    db.refresh(group)
    return group


@router.patch("/admin/facebook/groups/{id}", response_model=FacebookGroupOut)
def admin_update_group(id: int, payload: FacebookGroupUpdate, request: Request, admin_user: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    group = _get_group(db, id)
    changes = payload.model_dump(exclude_unset=True)
    try:
        if "state" in changes:
            changes["state"] = _clean_state(changes["state"]) if changes["state"] else None
        if "group_url" in changes:
            if group.kind != "group":
                raise ValueError("Solo los grupos públicos tienen group_url.")
            changes["group_url"] = _clean_group_url(changes["group_url"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if changes.get("group_url") and _find_by_group_url(db, changes["group_url"], exclude_id=group.id):
        raise HTTPException(status_code=409, detail="Ese grupo ya está dado de alta.")
    if "name" in changes and changes["name"] is not None:
        changes["name"] = changes["name"].strip()
    if "city" in changes:
        changes["city"] = (changes["city"] or "").strip() or None
    if changes.get("is_active") is None:
        changes.pop("is_active", None)
    if changes.get("name") is None:
        changes.pop("name", None)
    for field, value in changes.items():
        setattr(group, field, value)
    if "group_url" in changes:
        group.url = changes["group_url"]
    record_admin_action(db, admin_user, "facebook_group.update", "facebook_group", group.id,
                        {k: v for k, v in changes.items()}, request)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/admin/facebook/groups/{id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_group(id: int, request: Request, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    group = _get_group(db, id)
    record_admin_action(db, admin_user, "facebook_group.delete", "facebook_group", group.id,
                        {"name": group.name, "kind": group.kind, "group_url": group.group_url}, request)
    db.delete(group)
    db.commit()
    return None


async def _read_csv_payload(request: Request) -> str:
    """CSV desde multipart (campo "file" o "csv"), JSON {"csv": "..."} o el cuerpo en texto (text/csv)."""
    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        item = form.get("file") or form.get("csv")
        raw = await item.read() if hasattr(item, "read") else (item or "").encode()
    elif content_type.startswith("application/json"):
        try:
            data = json.loads(await request.body() or b"{}")
        except ValueError:
            raise HTTPException(status_code=400, detail="El cuerpo no es JSON válido.")
        raw = str((data or {}).get("csv") or "").encode() if isinstance(data, dict) else b""
    else:
        raw = await request.body()
    if len(raw) > CSV_MAX_BYTES:
        raise HTTPException(status_code=413, detail="El archivo es demasiado grande (máximo 1 MB). Divídelo en varios.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")  # Excel en Windows guarda CSV en Latin-1
    if not text.strip():
        raise HTTPException(status_code=400, detail="El CSV está vacío. Columnas: name,state,city,group_url[,active].")
    return text


def _import_csv_rows(db: Session, admin_user: User, text: str, request: Request) -> dict:
    first_line = text.lstrip().splitlines()[0] if text.strip() else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = {h: CSV_ALIASES.get((h or "").strip().lower(), (h or "").strip().lower()) for h in (reader.fieldnames or [])}
    missing = [c for c in ("name", "state", "group_url") if c not in headers.values()]
    if missing:
        raise HTTPException(status_code=400,
                            detail=f"Faltan columnas: {', '.join(missing)}. Encabezado esperado: name,state,city,group_url.")
    created, updated, skipped, errors, total = [], [], 0, [], 0
    seen: set[str] = set()
    for line_no, row in enumerate(reader, start=2):
        total += 1
        if total > CSV_MAX_ROWS:
            errors.append({"line": line_no, "error": f"Máximo {CSV_MAX_ROWS} filas por archivo; el resto se ignoró."})
            break
        values = {headers.get(k, k): (v or "").strip() for k, v in row.items() if k is not None}
        if not any(values.values()):
            continue
        try:
            name = values.get("name") or ""
            if len(name) < 2:
                raise ValueError("Falta el nombre del grupo.")
            state = _clean_state(values.get("state"))
            group_url = _clean_group_url(values.get("group_url"))
            active = _csv_bool(values.get("active")) if "active" in values else None
        except ValueError as exc:
            errors.append({"line": line_no, "error": str(exc)})
            continue
        if group_url in seen:
            skipped += 1
            continue
        seen.add(group_url)
        city = (values.get("city") or "")[:100] or None
        group = _find_by_group_url(db, group_url)
        if group:
            # Un grupo que ya existe solo cambia de situación si la fila trae la columna "active"
            new_active = group.is_active if active is None else active
            if (group.name, group.state, group.city, group.is_active) == (name[:255], state, city, new_active):
                skipped += 1
                continue
            group.name, group.state, group.city, group.is_active = name[:255], state, city, new_active
            updated.append(group)
        else:
            # Nuevos: pausados salvo "active" = sí (docs/facebook-grupos.md §3: se prueban antes de activarlos)
            group = FacebookGroup(name=name[:255], url=group_url, group_url=group_url, kind="group", state=state,
                                  city=city, is_active=bool(active), provider="apify")
            db.add(group)
            created.append(group)
    db.flush()
    record_admin_action(db, admin_user, "facebook_group.import_csv", "facebook_group", None,
                        {"created": len(created), "updated": len(updated), "skipped": skipped, "errors": len(errors)},
                        request)
    db.commit()
    paused = sum(1 for g in created if not g.is_active)
    return {
        "total_rows": total, "created": len(created), "updated": len(updated), "skipped": skipped, "errors": errors,
        "created_paused": paused,
        "group_ids": [g.id for g in created + updated],
        "message": f"Listo: {len(created)} grupos nuevos, {len(updated)} actualizados, {skipped} sin cambios"
                   + (f" y {len(errors)} filas con error." if errors else ".")
                   + (f" {paused} grupo(s) nuevo(s) quedaron pausados: pruébalos con «Leer ahora» y actívalos."
                      if paused else ""),
    }


def _csv_bool(value: str | None) -> bool:
    raw = (value or "").strip().lower()
    if raw in CSV_TRUE:
        return True
    if raw in CSV_FALSE:
        return False
    raise ValueError(f"Valor de «active» no reconocido: «{raw[:20]}». Usa sí o no (vacío = pausado).")


@router.post("/admin/facebook/groups/import-csv")
async def admin_import_groups_csv(request: Request, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Alta masiva de grupos: CSV con columnas name,state,city,group_url y, opcional, active (sí/no).

    Los grupos nuevos quedan pausados salvo active = sí; los que ya existen se actualizan.
    """
    text = await _read_csv_payload(request)
    return await run_in_threadpool(_import_csv_rows, db, admin_user, text, request)


@router.post("/admin/facebook/groups/{id}/fetch", status_code=status.HTTP_202_ACCEPTED)
def admin_fetch_group(id: int, request: Request, background_tasks: BackgroundTasks,
                      admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Lectura manual de un grupo (ignora el intervalo; sí cuenta para el presupuesto diario)."""
    group = _get_group(db, id)
    if group.kind != "group" or not group.group_url:
        raise HTTPException(status_code=400, detail="Solo se pueden leer grupos públicos con URL.")
    if not settings.fb_groups_active:
        raise HTTPException(status_code=503, detail=_groups_message())
    if fbg.affordable_posts() <= 0:
        raise HTTPException(status_code=429, detail=(
            f"Presupuesto diario agotado ({fbg.spent_today():.2f} de {settings.fb_groups_daily_budget_usd:.2f} USD). "
            "Inténtalo mañana o sube FB_GROUPS_DAILY_BUDGET_USD."))
    record_admin_action(db, admin_user, "facebook_group.fetch", "facebook_group", group.id, None, request)
    db.commit()
    mechanism = dispatch("app.tasks.facebook_groups.fetch_group", group.id, True, background_tasks=background_tasks)
    return {"group_id": group.id, "queued": True, "mechanism": mechanism,
            "message": f"Lectura de «{group.name}» encargada. Los reportes nuevos aparecerán en unos minutos."}


@router.get("/admin/facebook/stats")
def admin_facebook_stats(days: int = Query(7, ge=1, le=30), admin_user: User = Depends(require_admin),
                         db: Session = Depends(get_db)):
    """Estadísticas por grupo, gasto diario estimado y presupuesto."""
    now = datetime.datetime.utcnow()
    groups = db.query(FacebookGroup).filter(FacebookGroup.kind == "group").order_by(
        FacebookGroup.state.asc().nullsfirst(), FacebookGroup.name).all()
    rows, by_state = [], {}
    for g in groups:
        cost = float(g.cost_estimate_total or 0)
        rows.append({
            "id": g.id, "name": g.name, "state": g.state, "city": g.city, "group_url": g.group_url,
            "is_active": g.is_active, "last_fetched_at": g.last_fetched_at, "last_post_at": g.last_post_at,
            "posts_fetched_total": g.posts_fetched_total or 0, "reports_created_total": g.reports_created_total or 0,
            "cost_estimate_total": round(cost, 4), "last_error": g.last_error, "due": fbg.is_due(g, now),
            "last_attempt_at": g.last_attempt_at,
        })
        s = by_state.setdefault(g.state or "Sin estado", {"state": g.state, "groups": 0, "active": 0, "posts": 0,
                                                         "reports": 0, "cost": 0.0})
        s["groups"] += 1
        s["active"] += 1 if g.is_active else 0
        s["posts"] += g.posts_fetched_total or 0
        s["reports"] += g.reports_created_total or 0
        s["cost"] = round(s["cost"] + cost, 4)
    today = now.date()
    history = []
    for i in range(days):
        day = today - datetime.timedelta(days=i)
        history.append({"date": day.isoformat(), "spent_usd": fbg.spent_on(day),
                        "posts": fbg.daily_count("posts", day), "reports": fbg.daily_count("reports", day)})
    imported = dict(
        db.query(LostReport.status, func.count(LostReport.id))
        .filter(LostReport.source == "facebook").group_by(LostReport.status).all()
    )
    volunteer = db.query(func.count(LostReport.id)).filter(LostReport.source == "volunteer").scalar() or 0
    spent = fbg.spent_today()
    return {
        "provider_configured": settings.fb_groups_provider_configured,
        "import_enabled": settings.fb_groups_enabled,
        "provider": "apify",
        "actor": settings.apify_fb_groups_actor,
        "message": _groups_message(),
        "budget": {
            "daily_budget_usd": settings.fb_groups_daily_budget_usd,
            "spent_today_usd": spent,
            "remaining_usd": round(max(0.0, settings.fb_groups_daily_budget_usd - spent), 4),
            "exhausted": fbg.affordable_posts() <= 0,
            "cost_per_1000_posts_usd": settings.fb_groups_cost_per_1000_posts_usd,
            "cost_per_run_usd": settings.fb_groups_cost_per_run_usd,
            "max_run_cost_usd": fbg.cost_for(settings.fb_groups_max_posts_per_run),
        },
        "settings": {
            "fetch_interval_hours": settings.fb_groups_fetch_interval_hours,
            "lookback_days": settings.fb_groups_lookback_days,
            "max_posts_per_run": settings.fb_groups_max_posts_per_run,
            "post_ttl_days": settings.fb_groups_post_ttl_days,
            "volunteer_post_ttl_days": settings.fb_volunteer_post_ttl_days,
            "purge_after_days": settings.fb_imported_purge_after_days,
            "daily_budget_usd": settings.fb_groups_daily_budget_usd,
            "cost_per_1000_posts_usd": settings.fb_groups_cost_per_1000_posts_usd,
            "cost_per_run_usd": settings.fb_groups_cost_per_run_usd,
        },
        # Día UTC más reciente primero: gasto estimado, publicaciones leídas y reportes creados
        "history": history,
        "posts_today": history[0]["posts"],
        "reports_today": history[0]["reports"],
        "totals": {
            "groups": len(rows), "active_groups": sum(1 for r in rows if r["is_active"]),
            "posts_fetched": sum(r["posts_fetched_total"] for r in rows),
            "reports_created": sum(r["reports_created_total"] for r in rows),
            "cost_estimate_usd": round(sum(r["cost_estimate_total"] for r in rows), 4),
            "imported_reports_by_status": imported,
            "volunteer_reports": volunteer,
        },
        "by_state": sorted(by_state.values(), key=lambda s: (s["state"] is None, s["state"] or "")),
        "groups": rows,
    }
