from app.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_whatsapp_event(self, event: dict):
    """Procesa un evento de WhatsApp (ya normalizado) y responde por la Cloud API."""
    from app.database import SessionLocal
    from app.services.whatsapp_bot import process_event

    db = SessionLocal()
    try:
        return process_event(db, event, send=True)
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_whatsapp_message(self, phone: str, message: str | None, media_url: str | None):
    """Compatibilidad con el formato anterior."""
    return process_whatsapp_event({"phone": phone, "text": message, "media_url": media_url})
