import datetime
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

EXPIRE_BATCH = 500


def expire_stale_reports_now(db, days: int | None = None, now: datetime.datetime | None = None,
                             report_ids: list[int] | None = None) -> list[int]:
    """Pasa a "expired" los reportes activos sin actividad de quien reporta en `days` días y le avisa en la app.

    El reloj es last_activity_at (crear, renovar, resolver), no updated_at: las firmas de fotos y el
    análisis IA en segundo plano o un cambio de moderación no extienden la vigencia de un reporte.
    Devuelve los IDs expirados (`report_ids` limita la revisión a esos reportes, p. ej. en pruebas).
    Quien reportó lo puede reactivar con POST /lost-reports/{id}/renew.
    """
    from sqlalchemy import func

    from app.config import settings
    from app.models import LostReport
    from app.utils.notifications import create_notification

    days = days or settings.report_expiry_days
    now = now or datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=days)
    expired: list[int] = []
    base = db.query(LostReport).filter(
        LostReport.status == "active", func.coalesce(LostReport.last_activity_at, LostReport.created_at) < cutoff
    )
    if report_ids is not None:
        base = base.filter(LostReport.id.in_(report_ids))
    while True:
        rows = base.order_by(LostReport.id).limit(EXPIRE_BATCH).all()
        if not rows:
            break
        for report in rows:
            report.status = "expired"
            report.updated_at = now
            if report.reporter_id:
                kind = "perdido" if report.report_type == "lost" else "encontrado"
                create_notification(
                    db, user_id=report.reporter_id, type="report_expired", title="Tu reporte expiró",
                    body=(f"Tu reporte de perro {kind} \"{report.dog_name}\" lleva {days} días sin cambios y ya no "
                          "aparece en las búsquedas. Si sigue vigente, renuévalo desde tu perfil."),
                    data={"report_id": report.id}, commit=False,
                )
            expired.append(report.id)
        db.commit()
        if len(rows) < EXPIRE_BATCH:
            break
    if expired:  # los listados en caché y sus coincidencias se invalidan solos al hacer commit
        logger.info("Reportes expirados por inactividad: %s", len(expired))
    return expired


@celery_app.task
def expire_stale_reports():
    """Tarea diaria (beat): expira reportes activos sin cambios en REPORT_EXPIRY_DAYS días."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return {"expired": len(expire_stale_reports_now(db))}
    finally:
        db.close()
