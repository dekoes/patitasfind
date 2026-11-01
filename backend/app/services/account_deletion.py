"""Cancelación de cuenta (LFPDPPP): borra o anonimiza el contenido que publicó la persona.

Lo usa DELETE /users/me antes de anonimizar el perfil. Nada de aquí hace commit.
"""
import logging
import re
from pathlib import Path

from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AdoptionApplication, Conversation, Dog, DogPass, Donation, FosterHome, LostReport, Match, Notification,
    PhoneVerificationLog, PointLog, Product, Refuge, Reminder, User, Veterinary, VeterinaryRequest, VeterinaryReview,
)
from app.routers.documents import delete_private_document, is_document_id
from app.services import mercadopago_oauth

logger = logging.getLogger(__name__)

DELETED_NAME = "Usuario eliminado"
# Solo archivos sueltos de /uploads/ (nunca subcarpetas como private/)
UPLOAD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.[A-Za-z0-9]{2,5}$")
LIKE_BATCH = 50


def upload_name(url) -> str | None:
    """'/uploads/abc.jpg' (o con el dominio propio) -> 'abc.jpg'. Las URLs externas no son nuestras."""
    if not isinstance(url, str):
        return None
    path = url
    base = settings.public_base_url
    if base and path.startswith(base + "/uploads/"):
        path = path[len(base):]
    if not path.startswith("/uploads/"):
        return None
    name = path[len("/uploads/"):]
    return name if UPLOAD_NAME_RE.match(name) else None


def referenced_uploads(db: Session, names: set[str], exclude_user_id: int | None = None,
                       include_documents: bool = True) -> set[str]:
    """Archivos de `names` que usa contenido de otras personas (perros, reportes, productos, fotos de perfil
    y, si include_documents, documentos de refugios). Sin exclude_user_id cuenta el de cualquier persona."""
    user_id = exclude_user_id if exclude_user_id is not None else 0  # ningún usuario tiene id 0
    found: set[str] = set()
    names_list = sorted(names)
    for i in range(0, len(names_list), LIKE_BATCH):
        batch = names_list[i:i + LIKE_BATCH]

        def like_any(col):
            return or_(*[cast(col, String).like(f"%{n}%") for n in batch])

        queries = [
            db.query(cast(Dog.photos, String)).filter(Dog.owner_id != user_id, like_any(Dog.photos)),
            db.query(cast(LostReport.photos, String)).filter(
                or_(LostReport.reporter_id.is_(None), LostReport.reporter_id != user_id), like_any(LostReport.photos)),
            db.query(cast(Product.photos, String)).join(Refuge, Refuge.id == Product.refuge_id)
            .filter(Refuge.user_id != user_id, like_any(Product.photos)),
            db.query(User.avatar_url).filter(User.id != user_id, like_any(User.avatar_url)),
            db.query(cast(Veterinary.photos, String)).filter(
                Veterinary.owner_user_id != user_id, like_any(Veterinary.photos)),
        ]
        if include_documents:
            queries.append(
                db.query(cast(Refuge.documents, String)).filter(Refuge.user_id != user_id, like_any(Refuge.documents)))
        for query in queries:
            for (text_value,) in query.all():
                found.update(n for n in batch if text_value and n in text_value)
    return found


def delete_upload_files(db: Session, user_id: int, urls) -> int:
    """Borra del disco las fotos (y sus miniaturas _thumb.jpg) que solo usaba esta persona."""
    names = {n for n in (upload_name(u) for u in urls) if n}
    if not names:
        return 0
    names -= referenced_uploads(db, names, exclude_user_id=user_id)
    base = Path(settings.upload_dir).resolve()
    deleted = 0
    for name in names:
        stem = name.rsplit(".", 1)[0]
        for candidate in {name, f"{stem}_thumb.jpg"}:
            path = (base / candidate).resolve()
            try:
                if path.parent == base and path.is_file():
                    path.unlink()
                    deleted += 1
            except OSError as exc:
                logger.warning("No se pudo borrar %s: %s", path, exc)
    return deleted


def _scrub_name(text: str | None, old_name: str) -> str | None:
    if not text or not old_name or old_name == DELETED_NAME:
        return text
    return text.replace(old_name, DELETED_NAME)


def purge_user_content(db: Session, user: User, now) -> None:
    """Retira y anonimiza todo lo que publicó la persona. El perfil lo anonimiza quien llama."""
    uid = user.id
    old_name = user.full_name or ""
    files = [user.avatar_url]

    # Verificación en dos pasos (admins): secreto cifrado y códigos de recuperación se borran (tabla de conservación)
    from app.models import MfaRecoveryCode

    user.mfa_secret_enc = None
    user.mfa_pending_secret_enc = None
    user.mfa_enabled_at = None
    user.mfa_last_step = None
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == uid).delete(synchronize_session=False)

    # Refugio: cerrado (fuera de listados, ranking y donaciones), productos desactivados, documentos borrados
    refuge_ids = []
    for refuge in db.query(Refuge).filter(Refuge.user_id == uid).all():
        refuge_ids.append(refuge.id)
        for doc in refuge.documents or []:
            # Ids nuevos: solo se borran de la carpeta privada. Rutas antiguas (/uploads/...): con las fotos, que
            # revisan antes si otra persona usa el archivo (nunca se borra la foto pública de alguien más).
            if isinstance(doc, str) and is_document_id(doc):
                delete_private_document(doc)
            elif isinstance(doc, str):
                files.append(doc)
        refuge.documents = []
        refuge.status = "closed"
        # Mercado Pago: se borran los tokens OAuth (la tarea semanal no debe seguir renovando credenciales de una
        # cuenta eliminada). El perfil fiscal se conserva por las obligaciones fiscales de los CFDI ya emitidos.
        if refuge.payment_account is not None:
            mercadopago_oauth.disconnect(refuge.payment_account, "Cuenta eliminada")
    if refuge_ids:
        db.query(Product).filter(Product.refuge_id.in_(refuge_ids)).update(
            {Product.is_active: False}, synchronize_session=False)

    # Veterinaria: oculta y sin fotos, contacto ni cédula (el documento privado se borra). Sus reseñas en otras
    # clínicas se borran (también dejan de contar en los promedios).
    for vet in db.query(Veterinary).filter(Veterinary.owner_user_id == uid).all():
        if vet.cedula_document_id:
            delete_private_document(vet.cedula_document_id)  # nunca un archivo fuera de la carpeta privada
        # La captura fechada del cotejo en el RNP (evidencia del equipo) se conserva 12 meses tras la baja y la
        # borra la tarea purge_documents (retención de gap-veterinarias-y-resenas)
        vet.unpublished_at = now
        files.extend(vet.photos or [])
        vet.photos = []
        vet.cedula_document_id = None
        vet.description = None
        vet.phone = None
        vet.whatsapp = None
        vet.email = None
        vet.website = None
        vet.google_place_id = None
        vet.google_maps_url = None
        vet.is_hidden = True
    db.query(VeterinaryReview).filter(VeterinaryReview.user_id == uid).delete(synchronize_session=False)
    # Aclaraciones y quejas: se conservan como evidencia de moderación, sin nombre ni correo de contacto
    db.query(VeterinaryRequest).filter(VeterinaryRequest.user_id == uid).update(
        {VeterinaryRequest.name: None, VeterinaryRequest.email: None}, synchronize_session=False)

    # Perros: se ocultan, sin fotos, descripción ni ubicación (el adoptante conserva su historial)
    for dog in db.query(Dog).filter(Dog.owner_id == uid).all():
        files.extend(dog.photos or [])
        dog.photos = []
        dog.photo_signature = None
        dog.ai_analysis = None
        dog.description = None
        dog.latitude = None
        dog.longitude = None
        dog.is_hidden = True
        if dog.status != "adopted":
            dog.status = "unavailable"
    owned_dogs = select(Dog.id).where(Dog.owner_id == uid)
    db.query(Match).filter(Match.dog_id.in_(owned_dogs), Match.status == "pending_application").update(
        {Match.status: "rejected"}, synchronize_session=False)

    # Reportes de perdidos / encontrados: cerrados, ocultos y sin datos de contacto, fotos ni ubicación
    for report in db.query(LostReport).filter(LostReport.reporter_id == uid).all():
        files.extend(report.photos or [])
        report.photos = []
        report.photo_signature = None
        report.ai_analysis = None
        report.description = None
        report.contact_phone = None
        report.latitude = None
        report.longitude = None
        report.is_hidden = True
        if report.status == "active":
            report.status = "closed"

    # Solicitudes de adopción: sin respuestas del cuestionario; las pendientes se cierran
    my_matches = select(Match.id).where(Match.user_id == uid)
    db.query(AdoptionApplication).filter(AdoptionApplication.match_id.in_(my_matches)).update(
        {AdoptionApplication.answers: {}}, synchronize_session=False)
    db.query(AdoptionApplication).filter(
        AdoptionApplication.match_id.in_(my_matches), AdoptionApplication.status == "pending"
    ).update({AdoptionApplication.status: "rejected"}, synchronize_session=False)
    db.query(Match).filter(Match.user_id == uid, Match.status == "pending_application").update(
        {Match.status: "rejected"}, synchronize_session=False)

    db.query(Reminder).filter(Reminder.user_id == uid).delete(synchronize_session=False)
    db.query(DogPass).filter(DogPass.user_id == uid).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == uid).delete(synchronize_session=False)
    db.query(FosterHome).filter(FosterHome.user_id == uid).update(
        {FosterHome.status: "inactive", FosterHome.description: None}, synchronize_session=False)

    # Bitácora de SMS: se conserva para costos y límites, sin teléfono ni IP
    log_filter = PhoneVerificationLog.user_id == uid
    if user.phone:
        log_filter = or_(log_filter, PhoneVerificationLog.phone == user.phone)
    db.query(PhoneVerificationLog).filter(log_filter).update(
        {PhoneVerificationLog.phone: "eliminado", PhoneVerificationLog.ip: None}, synchronize_session=False)

    # Donaciones y pedidos se conservan (obligación fiscal) sin datos de la persona
    donation_ids = {d for (d,) in db.query(Donation.id).filter(Donation.user_id == uid).all()}
    db.query(Donation).filter(Donation.user_id == uid).update({Donation.share_name: False}, synchronize_session=False)

    _scrub_mentions(db, uid, old_name, donation_ids)
    delete_upload_files(db, uid, files)


def _scrub_mentions(db: Session, uid: int, old_name: str, donation_ids: set[int]) -> None:
    """Quita el nombre de la persona de avisos e historiales de puntos de otras cuentas.

    Los mensajes del chat se conservan para la otra persona; quien los envió aparece como "Usuario eliminado".
    """
    if not old_name or old_name == DELETED_NAME:
        return
    match_ids = {m for (m,) in db.query(Match.id).filter(
        or_(Match.user_id == uid, Match.dog_id.in_(select(Dog.id).where(Dog.owner_id == uid)))).all()}
    conv_ids = {c for (c,) in db.query(Conversation.id).filter(
        or_(Conversation.user_a_id == uid, Conversation.user_b_id == uid)).all()}
    linked = {"match_id": match_ids, "conversation_id": conv_ids, "donation_id": donation_ids}
    candidates = db.query(Notification).filter(
        Notification.user_id != uid,
        or_(Notification.title.contains(old_name, autoescape=True), Notification.body.contains(old_name, autoescape=True)),
    ).all()
    for n in candidates:
        data = n.data or {}
        if any(data.get(key) in ids for key, ids in linked.items() if ids):
            n.title = _scrub_name(n.title, old_name)
            n.body = _scrub_name(n.body, old_name)

    # "Firulais fue adoptado por <nombre>" / "Donación de $X MXN de <nombre>" en refugios con los que tuvo relación
    adopted_from = select(Refuge.id).join(Dog, Dog.owner_id == Refuge.user_id).join(Match, Match.dog_id == Dog.id).where(
        Match.user_id == uid)
    donated_to = select(Donation.refuge_id).where(Donation.user_id == uid)
    logs = db.query(PointLog).filter(
        or_(PointLog.refuge_id.in_(adopted_from), PointLog.refuge_id.in_(donated_to)),
        PointLog.description.contains(old_name, autoescape=True),
    ).all()
    for log in logs:
        log.description = _scrub_name(log.description, old_name)
