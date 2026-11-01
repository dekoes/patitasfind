from app.celery_app import celery_app

MAX_ENRICH_BATCH = 100


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


@celery_app.task
def enrich_signatures(kind: str, ids: list[int]):
    """Calcula las firmas visuales (sin IA) que pidió el matching de una petición pública."""
    from app.database import SessionLocal
    from app.models import Dog, LostReport
    from app.services.matching import ensure_enrichment, invalidate_report_matches

    model = Dog if kind == "dog" else LostReport
    db = SessionLocal()
    done = []
    try:
        for obj in db.query(model).filter(model.id.in_(list(ids)[:MAX_ENRICH_BATCH])).all():
            if not obj.photo_signature and obj.photos and ensure_enrichment(db, obj, with_ai=False, commit=False):
                done.append(obj.id)
        db.commit()
        if model is LostReport and done:
            invalidate_report_matches(*done)  # su lista de coincidencias ya puede usar la firma
        return {"kind": kind, "enriched": len(done)}
    finally:
        db.close()
