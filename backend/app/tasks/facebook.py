import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=300)
def scrape_facebook_groups(self):
    """Ingresa publicaciones nuevas de todas las Páginas de Facebook activas."""
    from app.config import settings
    from app.database import SessionLocal
    from app.models import FacebookGroup
    from app.services.facebook_monitor import ingest_page
    from app.services.matching import run_report_matching

    if not settings.facebook_enabled:
        return {"skipped": "FACEBOOK_PAGE_ACCESS_TOKEN no configurado"}
    db = SessionLocal()
    try:
        sources = db.query(FacebookGroup).filter(FacebookGroup.is_active == True, FacebookGroup.kind == "page").all()  # noqa: E712
        created = []
        for source in sources:
            try:
                created += ingest_page(db, source)
            except Exception:  # noqa: BLE001
                logger.exception("Falló la ingesta de la página %s", source.page_id)
        for report_id in created:
            run_report_matching(db, report_id)
        return {"sources_processed": len(sources), "reports_created": len(created)}
    finally:
        db.close()
