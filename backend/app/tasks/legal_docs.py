"""Aviso previo de cambios a los documentos legales (historial.html §2: 30 días antes, por correo y en la app).

send_change_notices(doc_id): avisa a las cuentas a las que aplica una versión nueva que pide aceptación. Avanza por
lotes con un cursor (LegalDocument.notice_cursor = último user_id avisado), así un reintento no repite correos.
send_pending_notices(): tarea diaria que retoma los avisos que no se mandaron (p. ej. el sync corrió sin Celery).
"""
import datetime
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

BATCH = 200


def _fecha(value: datetime.datetime | None) -> str:
    if value is None:
        return "hoy"
    local = value - datetime.timedelta(hours=6)  # Ciudad de México
    months = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
              "noviembre", "diciembre")
    return f"{local.day} de {months[local.month - 1]} de {local.year}"


def notice_texts(doc) -> tuple[str, str]:
    title = f"Actualizamos: {doc.title}"
    when = _fecha(doc.effective_at)
    future = doc.effective_at is not None and doc.effective_at > datetime.datetime.utcnow()
    body = (f"La versión {doc.version} de «{doc.title}» entra en vigor el {when}." if future
            else f"La versión {doc.version} de «{doc.title}» ya está vigente.")
    if doc.summary:
        body += f"\n\nQué cambia: {doc.summary.strip()[:600]}"
    body += ("\n\nTe pediremos aceptarla de forma expresa dentro de la app; seguir usando GuauWoow no cuenta como "
             "aceptación. Si no estás de acuerdo, puedes pedir una copia de tus datos y cerrar tu cuenta sin costo.")
    return title, body


def run_notices(db, doc_id: int) -> int:
    """Avisa a las cuentas pendientes de este documento. Devuelve cuántos avisos creó (hace commit por lote)."""
    from app.models import LegalDocument, User
    from app.services.legal_acceptance import audience_query
    from app.services.notify import notify_user

    doc = db.get(LegalDocument, doc_id)
    if doc is None or doc.notice_sent_at is not None or not doc.requires_reacceptance:
        return 0
    title, body = notice_texts(doc)
    sent = 0
    while True:
        users = (audience_query(db, doc.slug).filter(User.id > (doc.notice_cursor or 0))
                 .order_by(User.id).limit(BATCH).all())
        if not users:
            break
        for user in users:
            notify_user(db, user, "legal_change", title, body, url=doc.url, email=True,
                        data={"slug": doc.slug, "version": doc.version, "doc_id": doc.id}, commit=False)
            sent += 1
        doc.notice_cursor = users[-1].id
        db.commit()
    doc.notice_sent_at = datetime.datetime.utcnow()
    db.commit()
    logger.info("Aviso de cambio de %s %s enviado a %s cuentas.", doc.slug, doc.version, sent)
    return sent


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def send_change_notices(self, doc_id: int) -> int:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return run_notices(db, doc_id)
    except Exception as exc:
        db.rollback()
        logger.warning("Falló el aviso del documento legal %s: %s", doc_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task
def send_pending_notices() -> int:
    """Diaria: versiones nuevas que reemplazan a otra, piden aceptación y aún no se avisaron."""
    from app.database import SessionLocal
    from app.models import LegalDocument

    db = SessionLocal()
    total = 0
    try:
        rows = db.query(LegalDocument).filter(LegalDocument.notice_sent_at.is_(None),
                                              LegalDocument.requires_reacceptance.is_(True)).all()
        for row in rows:
            earlier = db.query(LegalDocument.id).filter(
                LegalDocument.slug == row.slug, LegalDocument.version != row.version,
                LegalDocument.published_at < row.published_at).first()
            if earlier is None:
                # Primera versión del documento: no hay cambio que avisar
                row.notice_sent_at = row.published_at
                db.commit()
                continue
            total += run_notices(db, row.id)
        return total
    finally:
        db.close()
