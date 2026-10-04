from app.celery_app import celery_app


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def match_lost_report(self, report_id: int):
    """Enriquece un reporte (firma + IA) y notifica posibles coincidencias."""
    from app.database import SessionLocal
    from app.services.matching import run_report_matching

    db = SessionLocal()
    try:
        matches = run_report_matching(db, report_id)
        return {"report_id": report_id, "matches": len(matches)}
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()
