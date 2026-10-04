from app.celery_app import celery_app


@celery_app.task
def enrich_dog(dog_id: int):
    """Calcula firma visual y análisis IA de un perro recién publicado."""
    from app.database import SessionLocal
    from app.models import Dog
    from app.services.matching import ensure_enrichment

    db = SessionLocal()
    try:
        dog = db.query(Dog).filter(Dog.id == dog_id).first()
        if dog:
            ensure_enrichment(db, dog, with_ai=True)
    finally:
        db.close()


@celery_app.task
def backfill_photo_signatures(batch: int = 50):
    """Completa firmas visuales (y análisis IA si hay llave) faltantes."""
    from app.database import SessionLocal
    from app.models import Dog, LostReport
    from app.services import vision
    from app.services.matching import ensure_enrichment

    db = SessionLocal()
    done = 0
    try:
        for model in (Dog, LostReport):
            q = db.query(model).filter(model.photo_signature.is_(None))
            if vision.is_configured():
                q = db.query(model).filter((model.photo_signature.is_(None)) | (model.ai_analysis.is_(None)))
            for obj in q.order_by(model.created_at.desc()).limit(batch).all():
                if obj.photos:
                    ensure_enrichment(db, obj, with_ai=True)
                    done += 1
        return {"processed": done}
    finally:
        db.close()


@celery_app.task
def process_uploaded_image(file_path: str, purpose: str = "general"):
    """Compatibilidad: el procesamiento ahora es síncrono en la subida (Pillow)."""
    return {"file_path": file_path, "purpose": purpose, "status": "processed"}
