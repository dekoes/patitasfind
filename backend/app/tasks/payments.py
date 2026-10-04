from app.celery_app import celery_app


@celery_app.task(bind=True, max_retries=5, default_retry_delay=30)
def process_mercadopago_payment(self, payment_id: str):
    from app.database import SessionLocal
    from app.services.payment_flow import process_payment

    db = SessionLocal()
    try:
        return process_payment(db, payment_id)
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()
