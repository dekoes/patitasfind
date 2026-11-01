"""Purga diaria de conservación de datos (beat "retention-purge-daily").

Aplica la tabla de services/retention.py: la misma que publica GET /cumplimiento/conservacion. No hace nada
mientras RETENTION_PURGE_ENABLED=false o haya un incidente abierto con «congelar purgas» (queda registrado en
retention_runs con estado disabled o frozen).
"""
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(soft_time_limit=540, time_limit=600)
def run_retention(dry_run: bool = False):
    from app.database import SessionLocal
    from app.services import retention

    db = SessionLocal()
    try:
        result = retention.run_purge(db, dry_run=dry_run)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {"status": result["status"], "run_id": result.get("run_id")}
