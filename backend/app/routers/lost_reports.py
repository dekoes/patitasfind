import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app import cache
from app.config import settings
from app.database import get_db
from app.dependencies import client_ip, get_current_user, get_optional_user, require_admin, get_verified_user
from app.models import LostReport, User
from app.schemas import (
    ConversationSummary, LostReportAdminOut, LostReportCreate, LostReportOut, LostReportPrivateOut, LostReportUpdate,
    MatchCandidate,
)
from app.data import estados_mx
from app.services import chat, facebook_groups, matching, moderation, privacy, ratelimit
from app.services.background import dispatch
from app.services.geo import apply_distance, distance_to
from app.utils.notifications import create_notification

router = APIRouter(tags=["lost_reports"])
VALID_TYPES = {"lost", "found"}
VALID_STATUSES = {"active", "resolved", "closed", "expired"}
RENEWABLE_STATUSES = {"active", "expired"}
# Listados públicos en caché; al cambiar un reporte se invalidan solos, junto con sus coincidencias
# (ver watch_sessions en app/cache.py)
CACHE_NS = "lost_reports"


def _get_report(db: Session, report_id: int) -> LostReport:
    report = db.query(LostReport).options(joinedload(LostReport.reporter)).filter(LostReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese reporte.")
    return report


def _public_report(db: Session, report_id: int, viewer: User | None = None) -> LostReport:
    """Reporte visible para el público: los de cuentas eliminadas solo los ven los admins."""
    report = _get_report(db, report_id)
    if report.reporter and report.reporter.deleted_at and not privacy.is_owner_or_admin(viewer, None):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese reporte.")
    # Oculto por moderación: solo lo ven quien lo creó y los admins
    if report.is_hidden and not moderation.can_see_hidden(viewer, report.reporter_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese reporte.")
    # Contenido importado de Facebook caducado o purgado: deja de ser público (aviso de contenido importado)
    if facebook_groups.is_withdrawn(report) and not moderation.can_see_hidden(viewer, report.reporter_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese reporte.")
    return report


@router.post("/lost-reports", response_model=LostReportPrivateOut, status_code=status.HTTP_201_CREATED)
def create_lost_report(payload: LostReportCreate, background_tasks: BackgroundTasks, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    if payload.report_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="El tipo de reporte debe ser 'lost' (perdido) o 'found' (encontrado).")
    if not payload.dog_name.strip():
        raise HTTPException(status_code=400, detail="Escribe el nombre del perrito (o 'Sin nombre').")
    report = LostReport(
        reporter_id=current_user.id,
        dog_name=payload.dog_name.strip(),
        report_type=payload.report_type,
        description=payload.description,
        city=payload.city,
        # Estado: el que manda la app (geocodificador) o se deduce de la ciudad / coordenadas
        state=estados_mx.derive_state(payload.state, payload.city, payload.latitude, payload.longitude),
        country=payload.country,
        latitude=payload.latitude,
        longitude=payload.longitude,
        photos=payload.photos or [],
        status="active",
        source="app",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    dispatch("app.tasks.matching.match_lost_report", report.id, background_tasks=background_tasks)
    # Alerta a quienes viven cerca y a refugios/casas de paso de la zona
    dispatch("app.tasks.notifications.notify_nearby_report", report.id, background_tasks=background_tasks)
    # Busca publicaciones recientes en los grupos públicos de Facebook del estado (si hay proveedor)
    facebook_groups.trigger_zone_fetch(report.state, background_tasks=background_tasks)
    return report


@router.get("/lost-reports", response_model=list[LostReportOut])
def list_lost_reports(
    city: str | None = Query(None),
    report_type: str | None = Query(None),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    radius_km: float = Query(50, gt=0, le=2000),
    status_filter: str = Query("active", alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    # La respuesta no depende de quién pregunta: se calcula desde el punto aproximado (~1 km) y se
    # guarda 60 s en Redis por combinación de filtros
    lat, lon = privacy.coarse(lat), privacy.coarse(lon)
    key = cache.make_key(
        CACHE_NS, view="list", lat=lat, lon=lon, radius_km=radius_km, status=status_filter, report_type=report_type,
        skip=skip, limit=limit, city=(city or "").strip().lower() if lat is None or lon is None else None,
    )
    hit = cache.get(key)
    if isinstance(hit, list):
        return JSONResponse(hit)
    query = db.query(LostReport).options(joinedload(LostReport.reporter)).filter(
        ~LostReport.reporter.has(User.deleted_at.isnot(None)),  # sin reportes de cuentas eliminadas
        LostReport.is_hidden == False,  # noqa: E712 - ni ocultos por moderación
        # ni contenido importado de Facebook caducado o purgado (la lista es pública y no depende de quién pregunta)
        ~and_(LostReport.source.in_(facebook_groups.IMPORTED_SOURCES),
              or_(LostReport.status == "expired", LostReport.purged_at.isnot(None))),
    )
    if status_filter and status_filter != "all":
        query = query.filter(LostReport.status == status_filter)
    if report_type:
        query = query.filter(LostReport.report_type == report_type)
    if city and (lat is None or lon is None):
        query = query.filter(LostReport.city.ilike(f"%{city}%"))
    items = privacy.coarsen_distances(apply_distance(query, LostReport, None, lat, lon, radius_km, skip, limit), lat, lon)
    cache.set(key, [LostReportOut.model_validate(r).model_dump(mode="json") for r in items],
              ttl=settings.list_cache_ttl_seconds)
    return items


@router.get("/lost-reports/me", response_model=list[LostReportPrivateOut])
def my_lost_reports(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(LostReport).filter(LostReport.reporter_id == current_user.id)
        .order_by(LostReport.created_at.desc()).all()
    )


@router.get("/lost-reports/{id}", response_model=LostReportOut)
def get_lost_report(
    id: int,
    lat: float | None = Query(None),
    lon: float | None = Query(None),
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    report = _public_report(db, id, viewer)
    if privacy.is_owner_or_admin(viewer, report.reporter_id):
        # Quien reporta y los admins ven las coordenadas exactas
        report.distance_km = distance_to(report, lat, lon)
        return JSONResponse(jsonable_encoder(LostReportPrivateOut.model_validate(report)))
    report.distance_km = privacy.public_distance(report, lat, lon)
    return report


@router.get("/lost-reports/{id}/matches", response_model=list[MatchCandidate])
def get_report_matches(
    id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    # Público: límite por IP. Solo usa firmas ya calculadas (las faltantes se encargan en segundo plano)
    ratelimit.check(
        f"report-matches:{client_ip(request)}", settings.report_matches_ip_minute_limit, 60,
        detail="Consultaste demasiadas coincidencias seguidas. Espera un minuto e inténtalo de nuevo.",
    )
    report = _public_report(db, id, viewer)
    candidates = matching.cached_matches_for_report(db, report, limit=10, background_tasks=background_tasks)
    return moderation.drop_hidden_candidates(db, candidates)


@router.patch("/lost-reports/{id}/resolve", response_model=LostReportPrivateOut)
def resolve_lost_report(id: int, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    report = _get_report(db, id)
    if report.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo quien creó el reporte puede marcarlo como resuelto.")
    report.status = "resolved"
    report.resolved_at = report.last_activity_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(report)
    return report


@router.post("/lost-reports/{id}/renew", response_model=LostReportPrivateOut)
def renew_lost_report(id: int, background_tasks: BackgroundTasks, current_user: User = Depends(get_verified_user),
                      db: Session = Depends(get_db)):
    """Quien reportó lo vuelve a activar (o extiende su vigencia otros 90 días)."""
    report = _get_report(db, id)
    if report.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo quien creó el reporte puede renovarlo.")
    if report.status not in RENEWABLE_STATUSES:
        raise HTTPException(status_code=400, detail="Este reporte ya se cerró; si tu perrito sigue perdido, crea uno nuevo.")
    if facebook_groups.is_withdrawn(report):
        # Las publicaciones importadas caducan a los 30 días de publicadas y luego se borran: no se renuevan
        raise HTTPException(status_code=400, detail=(
            "Las publicaciones importadas de Facebook caducan a los 30 días y no se pueden renovar. Si el perrito "
            "sigue perdido, crea un reporte nuevo con tus propias fotos."))
    was_expired = report.status == "expired"
    report.status = "active"
    report.updated_at = report.last_activity_at = datetime.datetime.utcnow()  # reinicia el plazo de expiración
    db.commit()
    db.refresh(report)
    if was_expired:  # pudo haber reportes nuevos parecidos mientras estuvo expirado
        dispatch("app.tasks.matching.match_lost_report", report.id, background_tasks=background_tasks)
    return report


@router.post("/lost-reports/{id}/contact", response_model=ConversationSummary)
def contact_reporter(id: int, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    report = _public_report(db, id)
    if not report.reporter_id:
        raise HTTPException(
            status_code=400,
            detail="Este reporte llegó por WhatsApp o Facebook y no tiene una cuenta para chatear. Revisa la descripción para contactar.",
        )
    if report.reporter_id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes contactarte a ti mismo.")
    conv, created = chat.get_or_create_report_conversation(db, report, current_user)
    db.commit()
    db.refresh(conv)
    if created:
        create_notification(
            db, user_id=report.reporter_id, type="report_contact", title="Alguien quiere ayudarte 🐾",
            body=f"{current_user.full_name} te escribió sobre tu reporte de {report.dog_name}.",
            data={"conversation_id": conv.id, "report_id": report.id},
        )
    return chat.summarize(db, conv, current_user)


@router.patch("/admin/lost-reports/{id}/status", response_model=LostReportAdminOut)
def update_lost_report_status(id: int, payload: LostReportUpdate, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Usa: {', '.join(sorted(VALID_STATUSES))}.")
    report = _get_report(db, id)
    report.status = payload.status
    if payload.status == "resolved" and not report.resolved_at:
        report.resolved_at = datetime.datetime.utcnow()
    if payload.status == "active":  # reactivado por un admin: cuenta como actividad (si no, expiraría al día siguiente)
        report.last_activity_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(report)
    return report
