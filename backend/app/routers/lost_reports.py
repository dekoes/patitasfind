import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import LostReport, User
from app.schemas import (
    ConversationSummary, LostReportAdminOut, LostReportCreate, LostReportOut, LostReportUpdate, MatchCandidate,
)
from app.services import chat, matching
from app.services.background import dispatch
from app.services.geo import apply_distance, distance_to
from app.utils.notifications import create_notification

router = APIRouter(tags=["lost_reports"])
VALID_TYPES = {"lost", "found"}
VALID_STATUSES = {"active", "resolved", "closed"}


def _get_report(db: Session, report_id: int) -> LostReport:
    report = db.query(LostReport).options(joinedload(LostReport.reporter)).filter(LostReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese reporte.")
    return report


@router.post("/lost-reports", response_model=LostReportOut, status_code=status.HTTP_201_CREATED)
def create_lost_report(payload: LostReportCreate, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    query = db.query(LostReport).options(joinedload(LostReport.reporter))
    if status_filter and status_filter != "all":
        query = query.filter(LostReport.status == status_filter)
    if report_type:
        query = query.filter(LostReport.report_type == report_type)
    if city and (lat is None or lon is None):
        query = query.filter(LostReport.city.ilike(f"%{city}%"))
    return apply_distance(query, LostReport, None, lat, lon, radius_km, skip, limit)


@router.get("/lost-reports/me", response_model=list[LostReportOut])
def my_lost_reports(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(LostReport).filter(LostReport.reporter_id == current_user.id)
        .order_by(LostReport.created_at.desc()).all()
    )


@router.get("/lost-reports/{id}", response_model=LostReportOut)
def get_lost_report(id: int, lat: float | None = Query(None), lon: float | None = Query(None), db: Session = Depends(get_db)):
    report = _get_report(db, id)
    report.distance_km = distance_to(report, lat, lon)
    return report


@router.get("/lost-reports/{id}/matches", response_model=list[MatchCandidate])
def get_report_matches(id: int, db: Session = Depends(get_db)):
    report = _get_report(db, id)
    return matching.matches_for_report(db, report, limit=10)


@router.patch("/lost-reports/{id}/resolve", response_model=LostReportOut)
def resolve_lost_report(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = _get_report(db, id)
    if report.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo quien creó el reporte puede marcarlo como resuelto.")
    report.status = "resolved"
    report.resolved_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(report)
    return report


@router.post("/lost-reports/{id}/contact", response_model=ConversationSummary)
def contact_reporter(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = _get_report(db, id)
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
    db.commit()
    db.refresh(report)
    return report
