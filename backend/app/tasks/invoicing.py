from app.celery_app import celery_app


@celery_app.task
def issue_monthly_cfdi(period: str | None = None):
    """Día 3 de cada mes (beat): CFDI de comisión y de retenciones del mes anterior por refugio con ventas.

    Sin PAC configurado los registros quedan "pending_pac" y no se envía nada (fiscal-tienda-10: el CFDI de
    retenciones se emite dentro de los 5 días siguientes al mes).
    """
    from app.database import SessionLocal
    from app.services.invoicing import generate_period_cfdis

    db = SessionLocal()
    try:
        return generate_period_cfdis(db, period)
    finally:
        db.close()


@celery_app.task
def retry_cfdi(cfdi_id: int):
    from app.database import SessionLocal
    from app.models import Cfdi
    from app.services.invoicing import issue_cfdi_row

    db = SessionLocal()
    try:
        row = db.query(Cfdi).filter(Cfdi.id == cfdi_id).first()
        return issue_cfdi_row(db, row).status if row else "not_found"
    finally:
        db.close()
