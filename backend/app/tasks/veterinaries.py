"""Tareas de la sección de veterinarias.

- refresh_google_places (semanal): revisa el place_id de las clínicas verificadas con ficha de Google cuya última
  revisión tiene más de 7 días. Usa Place Details pidiendo solo "id" (SKU IDs Only, sin costo): "Place IDs may change
  over time" y se refrescan así (https://developers.google.com/maps/documentation/places/web-service/place-id).
  Si Google cambió el id se guarda el nuevo; si responde NOT_FOUND durante más de 30 días se desvincula la ficha y
  se avisa a la clínica.
  No hay caché de contenido de Google que limpiar: las reseñas, la calificación y los autores se piden en tiempo
  real y nunca se guardan ("You must not pre-fetch, cache, or store Places API content beyond the allowed
  exceptions"; el place_id se puede guardar indefinidamente:
  https://developers.google.com/maps/documentation/places/web-service/policies). Por eso la regla de los 30 días
  del contrato se aplica a los place_id que Google ya no reconoce, no a reseñas guardadas.
- expire_verifications (diaria): la verificación de la cédula dura 12 meses (gap-veterinarias-y-resenas, hallazgo
  17); al vencer, la clínica vuelve a "pending" (sale del directorio) y se avisa a su dueño (veterinary_expired) y
  a los admins (veterinary_pending).
- purge_documents (diaria): retención de la evidencia de verificación (gap-veterinarias-y-resenas, retención 0:
  "12 meses después de la baja, el rechazo o la revocación; luego eliminación segura"). Borra la cédula y la
  captura del cotejo de las clínicas que llevan más de 12 meses sin publicarse (unpublished_at), y las solicitudes
  de aclaración o queja resueltas hace más de 2 años (retención 1: referencia de 2 años del daño moral en la CDMX).
  La IMAGEN de la cédula se borra antes: 30 días después de verificar o rechazar (R15/R17, purga diaria de
  services/retention.py, que también publica estos plazos en /cumplimiento/conservacion); aquí solo queda la captura.
"""
import datetime
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

REFRESH_AFTER_DAYS = 7
UNLINK_AFTER_DAYS = 30
DOCUMENT_RETENTION_DAYS = 365  # captura del cotejo (R16): 12 meses después de dejar de publicarse (la cédula, 30 días)
REQUEST_RETENTION_DAYS = 730  # aclaraciones y quejas resueltas: 2 años
BATCH = 200
_warned_not_configured = False


def _unlink(vet) -> None:
    vet.google_place_id = None
    vet.google_maps_url = None
    vet.google_place_checked_at = None
    vet.google_place_error_at = None
    vet.google_fetched_at = None


def refresh_google_places_now(db, now: datetime.datetime | None = None, ids: list[int] | None = None) -> dict:
    """Revisa los place_id vencidos (más de 7 días sin revisar). Devuelve contadores para la bitácora."""
    from sqlalchemy import or_

    from app.models import Veterinary
    from app.services import google_places
    from app.services.notify import notify_user

    global _warned_not_configured
    stats = {"checked": 0, "updated": 0, "not_found": 0, "unlinked": 0, "errors": 0, "skipped": False}
    if not google_places.enabled():
        if not _warned_not_configured:
            _warned_not_configured = True
            logger.info("GOOGLE_MAPS_API_KEY vacía: no se revisan las fichas de Google Maps de las veterinarias.")
        stats["skipped"] = True
        return stats

    now = now or datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=REFRESH_AFTER_DAYS)
    unlink_before = now - datetime.timedelta(days=UNLINK_AFTER_DAYS)
    base = db.query(Veterinary).filter(
        Veterinary.google_place_id.isnot(None), Veterinary.status == "verified",
        or_(Veterinary.google_place_checked_at.is_(None), Veterinary.google_place_checked_at < cutoff),
    )
    if ids is not None:
        base = base.filter(Veterinary.id.in_(ids))
    last_id = 0
    while True:
        rows = base.filter(Veterinary.id > last_id).order_by(Veterinary.id).limit(BATCH).all()
        if not rows:
            break
        for vet in rows:
            last_id = vet.id
            stats["checked"] += 1
            try:
                current = google_places.refresh_place_id(vet.google_place_id)
            except google_places.PlacesError:
                # Error pasajero (red, cuota, llave): se reintenta la próxima semana sin tocar nada
                stats["errors"] += 1
                continue
            vet.google_place_checked_at = now
            if current is None:
                stats["not_found"] += 1
                vet.google_place_error_at = vet.google_place_error_at or now
                if vet.google_place_error_at <= unlink_before:
                    _unlink(vet)
                    stats["unlinked"] += 1
                    if vet.owner and vet.owner.is_active:
                        notify_user(
                            db, vet.owner, "veterinary_google_unlinked", title="Desvinculamos tu ficha de Google Maps",
                            body=(f"Google Maps ya no encuentra la ficha de «{vet.name}» desde hace más de "
                                  f"{UNLINK_AFTER_DAYS} días. Búscala y vincúlala de nuevo desde «Mi veterinaria»."),
                            url="/app/", data={"veterinary_id": vet.id}, commit=False,
                        )
                continue
            if current != vet.google_place_id:
                taken = db.query(Veterinary.id).filter(
                    Veterinary.google_place_id == current, Veterinary.id != vet.id).first()
                if not taken:
                    vet.google_place_id = current
                    vet.google_maps_url = google_places.maps_url(current, vet.name)
                    stats["updated"] += 1
            vet.google_place_error_at = None
            vet.google_fetched_at = now
        db.commit()
        if len(rows) < BATCH:
            break
    if stats["checked"]:
        logger.info("Fichas de Google de veterinarias revisadas: %s", stats)
    return stats


def expire_verifications_now(db, now: datetime.datetime | None = None, ids: list[int] | None = None) -> list[int]:
    """Regresa a "pending" las clínicas cuya verificación anual venció. Devuelve sus IDs."""
    from app.models import User, Veterinary
    from app.services.moderation import ADMIN_ROLES
    from app.services.notify import notify_user

    now = now or datetime.datetime.utcnow()
    query = db.query(Veterinary).filter(
        Veterinary.status == "verified", Veterinary.verification_expires_at.isnot(None),
        Veterinary.verification_expires_at < now,
    )
    if ids is not None:
        query = query.filter(Veterinary.id.in_(ids))
    vets = query.order_by(Veterinary.id).limit(1000).all()
    if not vets:
        return []
    admins = db.query(User).filter(User.role.in_(ADMIN_ROLES), User.is_active == True).all()  # noqa: E712
    for vet in vets:
        vet.status = "pending"
        vet.unpublished_at = now
        if vet.owner and vet.owner.is_active:
            # veterinary_pending es un aviso para el equipo (la app lo abre en el panel): al dueño, veterinary_expired
            notify_user(
                db, vet.owner, "veterinary_expired", title="Renueva la verificación de tu veterinaria",
                body=(f"La verificación anual de la cédula de «{vet.name}» venció y la clínica dejó de mostrarse. "
                      "Revisa que tus datos estén al día: la volveremos a cotejar en el Registro Nacional de "
                      "Profesionistas."),
                url="/app/", email=True, data={"veterinary_id": vet.id}, commit=False,
            )
    for admin in admins:
        notify_user(
            db, admin, "veterinary_pending", title="Veterinarias por reverificar 🩺",
            body=f"{len(vets)} veterinaria(s) cumplieron un año desde su verificación y esperan revisión.",
            url="/admin/", data={"veterinary_ids": [v.id for v in vets]}, commit=False,
        )
    db.commit()
    logger.info("Verificaciones de veterinarias vencidas: %s", len(vets))
    return [v.id for v in vets]


def purge_documents_now(db, now: datetime.datetime | None = None, ids: list[int] | None = None) -> dict:
    """Borra cédulas y capturas de cotejo vencidas (12 meses sin publicarse) y solicitudes resueltas (2 años)."""
    from app.models import Veterinary, VeterinaryRequest
    from app.routers.documents import delete_private_document

    now = now or datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=DOCUMENT_RETENTION_DAYS)
    # unpublished_at solo tiene valor mientras la clínica no está publicada (verificar lo vuelve None); incluye las
    # clínicas de cuentas canceladas, que se quedan "verified" pero ocultas
    query = db.query(Veterinary).filter(
        Veterinary.unpublished_at.isnot(None), Veterinary.unpublished_at < cutoff,
        (Veterinary.cedula_document_id.isnot(None)) | (Veterinary.verification_evidence_document_id.isnot(None)),
    )
    if ids is not None:
        query = query.filter(Veterinary.id.in_(ids))
    stats = {"veterinaries": 0, "files": 0, "requests": 0}
    for vet in query.order_by(Veterinary.id).limit(1000).all():
        for field in ("cedula_document_id", "verification_evidence_document_id"):
            if getattr(vet, field):
                stats["files"] += int(delete_private_document(getattr(vet, field)))
                setattr(vet, field, None)
        stats["veterinaries"] += 1
    old_requests = db.query(VeterinaryRequest).filter(
        VeterinaryRequest.status != "pending", VeterinaryRequest.resolved_at.isnot(None),
        VeterinaryRequest.resolved_at < now - datetime.timedelta(days=REQUEST_RETENTION_DAYS),
    )
    if ids is not None:
        old_requests = old_requests.filter(VeterinaryRequest.veterinary_id.in_(ids))
    stats["requests"] = old_requests.delete(synchronize_session=False)
    db.commit()
    if stats["veterinaries"] or stats["requests"]:
        logger.info("Retención de veterinarias: %s", stats)
    return stats


@celery_app.task
def refresh_google_places():
    """Tarea semanal (beat): revisa los place_id de Google de las clínicas verificadas."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return refresh_google_places_now(db)
    finally:
        db.close()


@celery_app.task
def expire_verifications():
    """Tarea diaria (beat): vence las verificaciones de cédula con más de 12 meses."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return {"expired": len(expire_verifications_now(db))}
    finally:
        db.close()


@celery_app.task
def purge_documents():
    """Tarea diaria (beat): retención de cédulas, capturas del cotejo y solicitudes resueltas."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return purge_documents_now(db)
    finally:
        db.close()
