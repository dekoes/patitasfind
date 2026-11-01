"""Bitácora de acciones de administración."""
from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AdminAuditLog, User


def record_admin_action(
    db: Session,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: int | None = None,
    details: dict | None = None,
    request: Request | None = None,
) -> AdminAuditLog:
    """Agrega un registro a la bitácora. Quien llama hace el commit (va en la misma transacción)."""
    ip = None
    if request is not None:
        from app.dependencies import client_ip

        ip = client_ip(request)[:64]
    entry = AdminAuditLog(
        actor_id=actor.id if actor is not None else None,
        action=action[:100],
        target_type=target_type[:50],
        target_id=target_id,
        details=details or None,
        ip=ip,
    )
    db.add(entry)
    return entry
