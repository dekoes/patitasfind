from app.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_whatsapp_event(self, event: dict):
    """Procesa un evento de WhatsApp (ya normalizado) y responde por la Cloud API."""
    from app import cache
    from app.database import SessionLocal
    from app.services.whatsapp_bot import process_event

    # Meta reintenta el webhook si tardamos en responder: cada mensaje se procesa una sola vez
    r = cache._get_redis()
    if event.get("message_id") and r is not None and self.request.retries == 0:
        try:
            if not r.set(f"wa:msg:{event['message_id']}", 1, nx=True, ex=24 * 60 * 60):
                return {"duplicate": True}
        except Exception:  # noqa: BLE001
            pass

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
