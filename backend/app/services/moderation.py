"""Moderación de contenido: a qué apunta un reporte, ocultar publicaciones y suspender cuentas."""
import datetime

from sqlalchemy.orm import Session, joinedload

from app.models import (
    ContentReport, Conversation, Dog, LostReport, Message, Product, Refuge, User, Veterinary, VeterinaryReview,
)

ADMIN_ROLES = ("admin", "superadmin")
HIDDEN_MESSAGE = "Mensaje ocultado por moderación."
TARGET_LABELS = {
    "dog": "Perro en adopción", "lost_report": "Reporte de perdido/encontrado", "user": "Usuario",
    "refuge": "Refugio", "product": "Producto", "message": "Mensaje",
    "veterinary": "Veterinaria", "veterinary_review": "Reseña de veterinaria",
    # Formulario público sin enlace reconocible (POST /cumplimiento/reportes-publicos): target_id = 0
    "sin_identificar": "Contenido sin identificar",
}
_MODELS = {"dog": Dog, "lost_report": LostReport, "user": User, "refuge": Refuge, "product": Product, "message": Message,
           "veterinary": Veterinary, "veterinary_review": VeterinaryReview}
_EAGER = {
    "dog": [joinedload(Dog.owner)],
    "lost_report": [joinedload(LostReport.reporter)],
    "product": [joinedload(Product.refuge)],
    "refuge": [joinedload(Refuge.user)],
    "message": [joinedload(Message.sender)],
    "veterinary": [joinedload(Veterinary.owner)],
    "veterinary_review": [joinedload(VeterinaryReview.user), joinedload(VeterinaryReview.veterinary)],
}


def is_staff(user: User | None) -> bool:
    return bool(user and user.role in ADMIN_ROLES)


def can_see_hidden(user: User | None, owner_id: int | None) -> bool:
    """El contenido oculto solo lo ven su dueño y los administradores."""
    return bool(user and ((owner_id is not None and user.id == owner_id) or is_staff(user)))


def load_targets(db: Session, target_type: str, ids) -> dict:
    model = _MODELS.get(target_type)
    ids = {i for i in ids if i is not None}
    if model is None or not ids:
        return {}
    rows = db.query(model).options(*_EAGER.get(target_type, [])).filter(model.id.in_(ids)).all()
    return {row.id: row for row in rows}


def load_target(db: Session, target_type: str, target_id: int):
    return load_targets(db, target_type, [target_id]).get(target_id)


def owner_id(db: Session, target_type: str, obj) -> int | None:
    """Cuenta responsable del contenido (la que se suspende con suspend_user)."""
    if obj is None:
        return None
    if target_type == "dog":
        return obj.owner_id
    if target_type == "lost_report":
        return obj.reporter_id
    if target_type == "user":
        return obj.id
    if target_type == "refuge":
        return obj.user_id
    if target_type == "product":
        return obj.refuge.user_id if obj.refuge else None
    if target_type == "message":
        return obj.sender_id
    if target_type == "veterinary":
        return obj.owner_user_id
    if target_type == "veterinary_review":
        return obj.user_id
    return None


def visible_to(db: Session, target_type: str, obj, user: User) -> bool:
    """Solo se puede reportar lo que uno puede ver."""
    if obj is None:
        return False
    if target_type in ("dog", "lost_report", "product") and obj.is_hidden:
        return can_see_hidden(user, owner_id(db, target_type, obj))
    if target_type == "veterinary" and (obj.is_hidden or obj.status != "verified"):
        return can_see_hidden(user, obj.owner_user_id)
    if target_type == "veterinary_review" and (obj.is_hidden or not obj.veterinary or obj.veterinary.is_hidden):
        return can_see_hidden(user, obj.user_id)
    if target_type == "user":
        return bool(obj.is_active)
    if target_type == "message":
        conv = db.query(Conversation).filter(Conversation.id == obj.conversation_id).first()
        return bool(conv and conv.has_participant(user.id))
    return True


def summary(db: Session, target_type: str, obj) -> dict:
    """Resumen corto para el panel de administración."""
    base = {"type": target_type, "label": TARGET_LABELS.get(target_type, target_type), "exists": obj is not None}
    if target_type == "sin_identificar":
        return base | {"title": "Sin enlace reconocible (ver el enlace y los detalles del reporte)"}
    if obj is None:
        return base | {"title": "Contenido eliminado"}
    if target_type == "dog":
        return base | {
            "title": obj.name, "status": obj.status, "is_hidden": obj.is_hidden, "photo": (obj.photos or [None])[0],
            "owner_id": obj.owner_id, "owner_name": obj.owner.full_name if obj.owner else None,
            "url": f"/app/?dog={obj.id}",
        }
    if target_type == "lost_report":
        return base | {
            "title": obj.dog_name, "status": obj.status, "is_hidden": obj.is_hidden, "report_type": obj.report_type,
            "source": obj.source, "photo": (obj.photos or [None])[0], "owner_id": obj.reporter_id,
            "owner_name": obj.reporter.full_name if obj.reporter else None, "url": f"/app/?report={obj.id}",
        }
    if target_type == "user":
        return base | {
            "title": obj.full_name, "email": obj.email, "role": obj.role, "is_active": obj.is_active,
            "suspended_at": obj.suspended_at.isoformat() if obj.suspended_at else None, "owner_id": obj.id,
            "owner_name": obj.full_name,
        }
    if target_type == "refuge":
        return base | {
            "title": obj.name, "status": obj.status, "city": obj.city, "owner_id": obj.user_id,
            "owner_name": obj.user.full_name if obj.user else None,
        }
    if target_type == "product":
        return base | {
            "title": obj.name, "is_active": obj.is_active, "is_hidden": obj.is_hidden, "photo": (obj.photos or [None])[0],
            "refuge_id": obj.refuge_id, "refuge_name": obj.refuge.name if obj.refuge else None,
            "owner_id": obj.refuge.user_id if obj.refuge else None,
        }
    if target_type == "message":
        return base | {
            "title": (obj.content or "")[:300], "conversation_id": obj.conversation_id, "owner_id": obj.sender_id,
            "owner_name": obj.sender.full_name if obj.sender else None,
            "created_at": obj.created_at.isoformat() if obj.created_at else None,
        }
    if target_type == "veterinary":
        return base | {
            "title": obj.name, "status": obj.status, "is_hidden": obj.is_hidden, "city": obj.city,
            "photo": (obj.photos or [None])[0], "owner_id": obj.owner_user_id,
            "owner_name": obj.owner.full_name if obj.owner else None, "url": f"/app/?vet={obj.id}",
        }
    if target_type == "veterinary_review":
        return base | {
            "title": (obj.text or f"{obj.rating} de 5 estrellas")[:300], "rating": obj.rating, "is_hidden": obj.is_hidden,
            "veterinary_id": obj.veterinary_id, "veterinary_name": obj.veterinary.name if obj.veterinary else None,
            "owner_id": obj.user_id, "owner_name": obj.user.full_name if obj.user else None,
            "url": f"/app/?vet={obj.veterinary_id}",
        }
    return base


def hide(db: Session, target_type: str, obj) -> dict:
    """Oculta el contenido. Devuelve detalles para la bitácora. ValueError si no aplica."""
    if target_type in ("dog", "lost_report", "product", "veterinary", "veterinary_review"):
        obj.is_hidden = True
        return {"hidden": True}
    if target_type == "refuge":
        previous = obj.status
        obj.status = "suspended"  # deja de aparecer en listados y ranking, y no recibe donativos
        products = db.query(Product).filter(Product.refuge_id == obj.id, Product.is_hidden == False).all()  # noqa: E712
        for p in products:
            p.is_hidden = True  # sus productos tampoco se pueden comprar
        return {"refuge_status_from": previous, "refuge_status_to": "suspended", "hidden_products": [p.id for p in products]}
    if target_type == "message":
        original = obj.content
        obj.content = HIDDEN_MESSAGE
        return {"original_content": original}  # el texto original queda solo en la bitácora
    raise ValueError("Para un usuario usa la acción suspend_user.")


def suspend(db: Session, user: User) -> dict:
    """Desactiva la cuenta, cierra sus sesiones y oculta sus publicaciones visibles."""
    now = datetime.datetime.utcnow()
    user.is_active = False
    user.suspended_at = now
    if hasattr(user, "token_version"):
        user.token_version = (user.token_version or 0) + 1
    dogs = db.query(Dog).filter(Dog.owner_id == user.id, Dog.is_hidden == False).all()  # noqa: E712
    reports = db.query(LostReport).filter(LostReport.reporter_id == user.id, LostReport.is_hidden == False).all()  # noqa: E712
    refuge_ids = [r.id for r in db.query(Refuge.id).filter(Refuge.user_id == user.id)]
    products = (
        db.query(Product).filter(Product.refuge_id.in_(refuge_ids), Product.is_hidden == False).all()  # noqa: E712
        if refuge_ids else []
    )
    for item in (*dogs, *reports, *products):
        item.is_hidden = True
    return {
        "suspended_user_id": user.id,
        "hidden_dogs": [d.id for d in dogs],
        "hidden_lost_reports": [r.id for r in reports],
        "hidden_products": [p.id for p in products],
    }


def restore_hidden(db: Session, details: dict | None) -> dict:
    """Vuelve a mostrar lo que se ocultó en bloque (suspensión de cuenta o de refugio), según la bitácora.

    No se muestra lo que un admin ocultó por un reporte (acción hide_content).
    """
    details = details or {}
    restored = {}
    for key, target_type in (("hidden_dogs", "dog"), ("hidden_lost_reports", "lost_report"), ("hidden_products", "product")):
        ids = [i for i in details.get(key) or [] if isinstance(i, int)]
        if ids:
            by_report = {i for (i,) in db.query(ContentReport.target_id).filter(
                ContentReport.target_type == target_type, ContentReport.target_id.in_(ids),
                ContentReport.status == "resolved", ContentReport.action == "hide_content")}
            ids = [i for i in ids if i not in by_report]
        for obj in load_targets(db, target_type, ids).values():
            obj.is_hidden = False
        restored[key] = ids
    return restored


def drop_hidden_candidates(db: Session, items: list[dict]) -> list[dict]:
    """Quita de una lista de coincidencias ({type, id}) los perros y reportes ocultos."""
    dog_ids = [m["id"] for m in items if m.get("type") == "adoption"]
    report_ids = [m["id"] for m in items if m.get("type") != "adoption"]
    hidden_dogs = {i for (i,) in db.query(Dog.id).filter(Dog.id.in_(dog_ids), Dog.is_hidden == True)} if dog_ids else set()  # noqa: E712
    hidden_reports = (
        {i for (i,) in db.query(LostReport.id).filter(LostReport.id.in_(report_ids), LostReport.is_hidden == True)}  # noqa: E712
        if report_ids else set()
    )
    return [
        m for m in items
        if m["id"] not in (hidden_dogs if m.get("type") == "adoption" else hidden_reports)
    ]
