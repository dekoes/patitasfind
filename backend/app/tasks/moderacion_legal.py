"""Tareas de moderación legal: purga de la bóveda de evidencia, restauración tras contra-aviso, fin de suspensiones
temporales y aviso de plazos vencidos (services/legal_moderation.py y services/evidence.py)."""
import datetime
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def purge_expired_evidence():
    """Borra el archivo cifrado de la evidencia vencida (90 días hábiles) sin retención legal ni caso abierto."""
    from app.database import SessionLocal
    from app.services import evidence

    db = SessionLocal()
    try:
        purged = evidence.purge_expired(db)
        if purged:
            logger.info("Bóveda de evidencia: %s archivo(s) vencido(s) eliminados.", purged)
        return purged
    finally:
        db.close()


def restore_due_copyright(db, now: datetime.datetime | None = None) -> int:
    """Contra-avisos cuyo día hábil 10 ya pasó sin que quien avisó acreditara un procedimiento: se restaura."""
    from app.models import CopyrightNotice
    from app.services import legal_moderation as lm

    now = now or datetime.datetime.utcnow()
    due = db.query(CopyrightNotice).filter(
        CopyrightNotice.status == "counter_notice", CopyrightNotice.restore_from.isnot(None),
        CopyrightNotice.restore_from <= now, CopyrightNotice.proceeding_at.is_(None),
    ).all()
    for notice in due:
        lm.restore_copyright(db, notice, "Restaurado: no se acreditó un procedimiento tras el contra-aviso.")
        lm.send_email(notice.email, f"Restauramos el contenido de tu aviso {notice.folio}",
                      "No recibimos constancia de un procedimiento dentro del plazo, así que restauramos el contenido "
                      "(Reglamento LFDA art. 37 Nonies).")
        if notice.uploader_user_id:
            from app.models import User

            user = db.query(User).filter(User.id == notice.uploader_user_id).first()
            lm.notify_person(db, user, "content_restored", "Restauramos tu publicación",
                             f"Tras tu contra-aviso al aviso {notice.folio}, el contenido vuelve a mostrarse y ese aviso "
                             "ya no cuenta para la política de reincidentes.")
    db.commit()
    return len(due)


@celery_app.task
def restore_counter_noticed_content():
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return restore_due_copyright(db)
    finally:
        db.close()


@celery_app.task
def lift_expired_suspensions():
    from app.database import SessionLocal
    from app.services import legal_moderation as lm

    db = SessionLocal()
    try:
        return lm.lift_expired_suspensions(db)
    finally:
        db.close()


def overdue_summary(db, now: datetime.datetime | None = None) -> dict:
    from app.models import AuthorityRequest, ContentReport, CopyrightNotice, ModerationAppeal

    now = now or datetime.datetime.utcnow()
    return {
        "reportes": db.query(ContentReport).filter(ContentReport.status == "open", ContentReport.due_at < now).count(),
        "apelaciones": db.query(ModerationAppeal).filter(ModerationAppeal.status == "pending",
                                                         ModerationAppeal.due_at < now).count(),
        "derechos_autor": db.query(CopyrightNotice).filter(CopyrightNotice.status == "received",
                                                           CopyrightNotice.due_at < now).count(),
        "autoridades": db.query(AuthorityRequest).filter(
            AuthorityRequest.status.in_(("recibido", "en_revision", "pendiente_denuncia")),
            AuthorityRequest.first_response_due_at < now).count(),
    }


@celery_app.task
def alert_overdue_moderation():
    """Aviso diario a los administradores si hay reportes, apelaciones, avisos o requerimientos fuera de plazo."""
    from app.database import SessionLocal
    from app.services import legal_moderation as lm

    db = SessionLocal()
    try:
        summary = overdue_summary(db)
        if any(summary.values()):
            lm.alert_admins(
                db, "Plazos vencidos en Moderación legal",
                (f"Reportes: {summary['reportes']} · Apelaciones: {summary['apelaciones']} · Avisos de derechos de autor: "
                 f"{summary['derechos_autor']} · Requerimientos de autoridad: {summary['autoridades']}."),
                data={"overdue": summary},
            )
            db.commit()
        return summary
    finally:
        db.close()
