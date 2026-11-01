import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=300)
def scrape_facebook_groups(self):
    """Encarga una tarea por cada Página de Facebook activa (en paralelo y con su propio límite de tiempo)."""
    from app.config import settings
    from app.database import SessionLocal
    from app.models import FacebookGroup
    from app.services.background import dispatch

    if not settings.facebook_enabled:
        return {"skipped": "FACEBOOK_PAGE_ACCESS_TOKEN no configurado"}
    if not settings.fb_groups_enabled:  # interruptor legal de la importación automática (contrato L-fb)
        return {"skipped": "Importación de Facebook apagada (FB_GROUPS_ENABLED=false)"}
    db = SessionLocal()
    try:
        source_ids = [s.id for s in db.query(FacebookGroup.id).filter(
            FacebookGroup.is_active == True, FacebookGroup.kind == "page"  # noqa: E712
        ).all()]
    finally:
        db.close()
    for source_id in source_ids:
        dispatch("app.tasks.facebook.scrape_facebook_source", source_id)
    return {"sources_queued": len(source_ids)}


@celery_app.task
def scrape_facebook_source(source_id: int):
    """Ingresa las publicaciones nuevas de una Página y encarga el matching de cada reporte por separado."""
    from app.database import SessionLocal
    from app.models import FacebookGroup
    from app.services.background import dispatch
    from app.services.facebook_monitor import ingest_page

    db = SessionLocal()
    created: list[int] = []
    try:
        source = db.query(FacebookGroup).filter(FacebookGroup.id == source_id).first()
        if source is None or not source.is_active:
            return {"source_id": source_id, "skipped": True}
        try:
            created = ingest_page(db, source)
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Falló la ingesta de la página %s", source.page_id)
    finally:
        db.close()
    # Una tarea de matching por reporte: si una falla o tarda, no detiene a las demás
    for report_id in created:
        dispatch("app.tasks.matching.match_lost_report", report_id)
    return {"source_id": source_id, "reports_created": len(created)}
