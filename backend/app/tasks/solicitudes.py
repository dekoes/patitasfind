"""Tareas del centro de solicitudes (services/solicitudes.py).

- daily_maintenance (diaria): borra identificaciones (al resolver la solicitud y nunca después de 30 días), cierra
  las solicitudes cuyo correo nunca se confirmó o cuyo requerimiento no se contestó en 10 días hábiles, avisa al
  equipo de lo que vence en 2 días hábiles y borra los expedientes cerrados hace más de 5 años.
- enforce_imported_removals (cada hora): borra el texto y las fotos de las publicaciones importadas cuyo retiro se
  pidió hace IMPORTED_REMOVAL_PURGE_HOURS horas, para cumplir «en menos de 72 horas».
"""
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def daily_maintenance():
    from app.database import SessionLocal
    from app.services import solicitudes

    db = SessionLocal()
    try:
        out = solicitudes.daily_maintenance(db)
        logger.info("Mantenimiento del centro de solicitudes: %s", out)
        return out
    finally:
        db.close()


@celery_app.task
def enforce_imported_removals():
    from app.database import SessionLocal
    from app.services import solicitudes

    db = SessionLocal()
    try:
        done = solicitudes.enforce_imported_removals(db)
        if done:
            logger.info("Retiros de publicaciones importadas completados: %s", ", ".join(done))
        return len(done)
    finally:
        db.close()
