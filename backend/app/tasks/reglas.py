"""Tareas de las reglas de negocio (services/reglas.py)."""
from app.celery_app import celery_app


@celery_app.task
def remind_invoice_requests():
    """Cada hora: facturas pedidas hace más de 24 h => recordatorio al refugio; más de 72 h => aviso al equipo."""
    from app.database import SessionLocal
    from app.services import reglas

    db = SessionLocal()
    try:
        return reglas.remind_invoice_requests(db)
    finally:
        db.close()


@celery_app.task
def run_daily_rules():
    """Diaria: bonificaciones vencidas (recordatorio) y fin del resguardo de perros encontrados (aviso)."""
    from app.database import SessionLocal
    from app.services import reglas

    db = SessionLocal()
    try:
        return reglas.run_daily(db)
    finally:
        db.close()
