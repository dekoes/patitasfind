"""Reportes de contenido (moderación): los usuarios señalan publicaciones y los admins las revisan."""
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_verified_user, require_admin
from app.models import AdminAuditLog, ContentReport, ModerationAction, User
from app.schemas import (
    ContentReportAdminOut, ContentReportCreate, ContentReportOut, ContentReportResolve, ReportReason, ReportTargetType,
)
from app.services import evidence, legal_moderation, moderation, staydown
from app.services.audit import record_admin_action
from app.services.notify import notify_user
from app.utils.notifications import create_notification

router = APIRouter(tags=["moderation"])

REPORTS_PER_HOUR = 10
ADMIN_ALERT_THRESHOLD = 3  # reportes abiertos sobre el mismo contenido para avisar a los admins
VALID_STATUSES = {"open", "resolved", "dismissed"}


class HiddenUpdate(BaseModel):
    hidden: bool
    # Regla aplicada (va en el aviso a quien publicó); sin ella se cita «Contenido inapropiado»
    rule: ReportReason | None = None
    # Origen: el equipo o una orden de autoridad (con orden se bloquean además sus imágenes: staydown)
    detection: Literal["equipo", "autoridad"] = "equipo"
    notes: str | None = Field(None, max_length=2000)  # p. ej. datos de la orden (LGAMVLV art. 20 Sexies)


def _open_count(db: Session, target_type: str, target_id: int) -> int:
    return db.query(func.count(ContentReport.id)).filter(
        ContentReport.target_type == target_type, ContentReport.target_id == target_id, ContentReport.status == "open",
    ).scalar() or 0


def _alert_admins(db: Session, report: ContentReport, title: str, count: int) -> None:
    admins = db.query(User).filter(User.role.in_(moderation.ADMIN_ROLES), User.is_active == True).all()  # noqa: E712
    label = moderation.TARGET_LABELS.get(report.target_type, report.target_type)
    for admin in admins:
        notify_user(
            db, admin, "moderation_alert",
            title="Contenido con varios reportes 🚩",
            body=f"{label} «{title}» acumula {count} reportes abiertos. Revísalo en el panel de administración.",
            url="/admin/", email=True,
            data={"target_type": report.target_type, "target_id": report.target_id, "content_report_id": report.id},
            commit=False,
        )


@router.post("/reports", response_model=ContentReportOut, status_code=status.HTTP_201_CREATED)
def create_report(
    payload: ContentReportCreate,
    response: Response,
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    target = moderation.load_target(db, payload.target_type, payload.target_id)
    if not moderation.visible_to(db, payload.target_type, target, current_user):
        raise HTTPException(status_code=404, detail="No encontramos ese contenido.")
    if moderation.owner_id(db, payload.target_type, target) == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes reportar tu propio contenido.")

    existing = db.query(ContentReport).filter(
        ContentReport.reporter_id == current_user.id, ContentReport.target_type == payload.target_type,
        ContentReport.target_id == payload.target_id, ContentReport.status == "open",
    ).first()
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    since = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    recent = db.query(func.count(ContentReport.id)).filter(
        ContentReport.reporter_id == current_user.id, ContentReport.created_at >= since,
    ).scalar() or 0
    if recent >= REPORTS_PER_HOUR:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Enviaste muchos reportes en poco tiempo. Intenta de nuevo en una hora.",
        )

    report = ContentReport(
        reporter_id=current_user.id, target_type=payload.target_type, target_id=payload.target_id,
        reason=payload.reason, details=(payload.details or "").strip() or None, status="open",
    )
    db.add(report)
    db.flush()
    # Prioridad, plazo y medidas inmediatas (lo que involucra a menores se oculta al momento)
    legal_moderation.intake(db, report, target)
    count = _open_count(db, payload.target_type, payload.target_id)
    if count == ADMIN_ALERT_THRESHOLD:
        _alert_admins(db, report, moderation.summary(db, payload.target_type, target).get("title") or "", count)
    db.commit()
    db.refresh(report)
    return report


# --------------------------------------------------------------------------- administración
def _admin_rows(db: Session, reports: list[ContentReport]) -> list[dict]:
    """Agrega reportante, quien resolvió, resumen del contenido y reportes abiertos por contenido."""
    by_type: dict[str, set] = {}
    for r in reports:
        by_type.setdefault(r.target_type, set()).add(r.target_id)
    targets = {t: moderation.load_targets(db, t, ids) for t, ids in by_type.items()}
    user_ids = {r.reporter_id for r in reports} | {r.resolved_by for r in reports if r.resolved_by}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    counts = {}
    for t, ids in by_type.items():
        rows = (
            db.query(ContentReport.target_id, func.count(ContentReport.id))
            .filter(ContentReport.target_type == t, ContentReport.target_id.in_(ids), ContentReport.status == "open")
            .group_by(ContentReport.target_id).all()
        )
        counts.update({(t, tid): n for tid, n in rows})

    out = []
    for r in reports:
        item = {f: getattr(r, f) for f in (
            "id", "status", "target_type", "target_id", "reason", "details", "action", "admin_notes", "created_at",
            "resolved_at", "source", "priority", "due_at", "auto_hidden", "folio", "contact_email", "target_url",
        )}
        reporter, resolver = users.get(r.reporter_id), users.get(r.resolved_by)
        item["reporter"] = {"id": reporter.id, "full_name": reporter.full_name, "email": reporter.email} if reporter else None
        item["resolved_by"] = {"id": resolver.id, "full_name": resolver.full_name} if resolver else None
        item["target"] = moderation.summary(db, r.target_type, targets.get(r.target_type, {}).get(r.target_id))
        if r.reason in legal_moderation.CSAM_REASONS or r.action == "quarantine":
            # Material en cuarentena: el panel solo muestra metadatos, nunca el contenido
            item["target"] = {k: v for k, v in item["target"].items() if k not in ("photo", "title", "url")}
            item["target"]["title"] = "Contenido en cuarentena (solo metadatos)"
        item["open_reports_for_target"] = counts.get((r.target_type, r.target_id), 0)
        out.append(item)
    return out


@router.get("/admin/reports", response_model=list[ContentReportAdminOut])
def list_reports(
    status_filter: str | None = Query(None, alias="status"),
    target_type: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(ContentReport)
    if status_filter and status_filter != "all":
        if status_filter not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Estado inválido. Usa: open, resolved o dismissed.")
        query = query.filter(ContentReport.status == status_filter)
    if target_type:
        query = query.filter(ContentReport.target_type == target_type)
    reports = query.order_by(ContentReport.created_at.desc(), ContentReport.id.desc()).offset(skip).limit(limit).all()
    return _admin_rows(db, reports)


PENDING_QUARANTINE_ONLY = ("Este contenido está en cuarentena preventiva: un superadmin la confirma (acción "
                           "«Cuarentena») o la descarta (reporte falso, con el motivo en las notas).")


def _decide_pending_quarantine(db: Session, report: ContentReport, payload: ContentReportResolve, admin_user: User,
                               request: Request) -> dict:
    """Cuarentena preventiva (legal_moderation.preventive_quarantine): solo se confirma o se descarta, y solo lo hace
    un superadmin con la vista protegida (nunca se muestra el material)."""
    if payload.status == "resolved" and payload.action == "quarantine":
        out = legal_moderation.confirm_quarantine(db, report, admin_user)
        record_admin_action(db, admin_user, "content.quarantine_confirm", report.target_type, report.target_id,
                            {"content_report_id": report.id, **out}, request)
    elif payload.status == "dismissed" and not payload.action:
        reason = (payload.notes or "").strip()
        if len(reason) < 10:
            raise HTTPException(status_code=400, detail="Escribe en las notas por qué descartas la cuarentena preventiva.")
        out = legal_moderation.release_pending_quarantine(db, report, admin_user, reason)
        record_admin_action(db, admin_user, "content.quarantine_dismiss", report.target_type, report.target_id,
                            {"content_report_id": report.id, "motivo": reason, **out}, request)
    else:
        raise HTTPException(status_code=400, detail=PENDING_QUARANTINE_ONLY)
    # Formulario público: aviso del resultado sin detalles de la medida
    ids = out.get("resolved_reports") or out.get("dismissed") or []
    for r in db.query(ContentReport).filter(ContentReport.id.in_(ids or [0])).all():
        if r.contact_email and not r.reporter_id:
            legal_moderation.send_email(r.contact_email, f"Revisamos tu reporte {r.folio or ''}".strip(),
                                        "Revisamos el contenido que nos reportaste. Gracias por cuidar a la comunidad.")
    db.commit()
    db.refresh(report)
    return _admin_rows(db, [report])[0]


@router.patch("/admin/reports/{id}", response_model=ContentReportAdminOut)
def resolve_report(
    id: int,
    payload: ContentReportResolve,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    report = db.query(ContentReport).filter(ContentReport.id == id).first()
    if not report:
        raise HTTPException(status_code=404, detail="No encontramos ese reporte.")
    if report.status != "open":
        raise HTTPException(status_code=400, detail="Este reporte ya fue revisado.")
    if payload.status == "dismissed" and payload.action:
        raise HTTPException(status_code=400, detail="Para aplicar una acción marca el reporte como resuelto.")

    if legal_moderation.is_pending_quarantine(db, report):
        return _decide_pending_quarantine(db, report, payload, admin_user, request)
    target = moderation.load_target(db, report.target_type, report.target_id)
    # Retención automática de reglas de negocio (services/reglas.py): descartar el reporte desde la cola general
    # libera la publicación, igual que «Liberar» en Admin > Reglas de negocio (si no, se quedaría oculta)
    from app.services import reglas

    if (payload.status == "dismissed" and report.reason == reglas.HOLD_REPORT_REASON and target is not None
            and getattr(target, "review_hold", None) not in (None, reglas.HOLD_RELEASED, reglas.HOLD_REJECTED)):
        reglas.decide_hold(db, report.target_type, report.target_id, admin_user, "liberar", payload.notes, request)
        db.refresh(report)
        return _admin_rows(db, [report])[0]
    details = {"content_report_id": report.id, "reason": report.reason}
    rule = payload.rule or report.reason
    detection = "equipo" if report.source == "equipo" else "reporte"
    if payload.action == "hide_content":
        if target is None:
            raise HTTPException(status_code=400, detail="El contenido ya no existe.")
        already_hidden = report.auto_hidden and (
            target.content == moderation.HIDDEN_MESSAGE if report.target_type == "message"
            else bool(getattr(target, "is_hidden", False)))
        snapshot = evidence.row_data(target)
        try:
            details |= ({"hidden": True, "preventive": True} if already_hidden
                        else moderation.hide(db, report.target_type, target))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        owner_id = moderation.owner_id(db, report.target_type, target)
        owner = db.query(User).filter(User.id == owner_id).first() if owner_id else None
        # Copia cifrada de lo retirado (Decreto NNA art. 5 fr. II) y aviso con la regla, el origen y cómo apelar
        record = evidence.capture(
            db, kind="contenido_retirado", target_type=report.target_type, target_id=report.target_id, obj=target,
            owner_user_id=owner_id, reason=rule, report=report,
            decision={"action": "hide_content", "details": details, "before": snapshot, "actor_id": admin_user.id,
                      "notes": payload.notes},
            actor_id=admin_user.id,
        )
        title = moderation.summary(db, report.target_type, target).get("title") or ""
        action = legal_moderation.record_action(
            db, user=owner if report.target_type not in ("user",) else None, target_type=report.target_type,
            target_id=report.target_id, action="hide_content", rule=rule, detection=detection, actor=admin_user,
            title=title if report.target_type != "message" else "Mensaje del chat", report=report,
            evidence_record=record, notes=payload.notes, details=details,
        )
        details["moderation_action"] = action.folio
        record_admin_action(db, admin_user, "content.hide", report.target_type, report.target_id, details, request)
    elif payload.action == "suspend_user":
        owner_id = moderation.owner_id(db, report.target_type, target)
        target_user = db.query(User).filter(User.id == owner_id).first() if owner_id else None
        if not target_user:
            raise HTTPException(status_code=400, detail="Este contenido no tiene una cuenta asociada para suspender.")
        if not target_user.is_active:
            raise HTTPException(status_code=400, detail="Esa cuenta ya está desactivada.")
        from app.routers.admin import check_user_management  # mismas reglas que el panel de usuarios

        check_user_management(db, admin_user, target_user, deactivate=True)
        action = legal_moderation.suspend_account(db, target_user, rule=rule, detection=detection, actor=admin_user,
                                                  report=report, notes=payload.notes)
        details |= action.details or {}
        details["moderation_action"] = action.folio
        record_admin_action(db, admin_user, "user.suspend", "user", target_user.id, details, request)
    elif payload.action == "quarantine":
        if target is None:
            raise HTTPException(status_code=400, detail="El contenido ya no existe.")
        if report.target_type in ("refuge",):
            raise HTTPException(status_code=400, detail="Para un refugio suspende la cuenta y pon en cuarentena cada contenido.")
        details |= legal_moderation.quarantine(db, report, target, actor=admin_user)
        record_admin_action(db, admin_user, "content.quarantine", report.target_type, report.target_id, details, request)
    elif payload.status == "dismissed" and legal_moderation.undo_preventive_hide(db, report):
        record_admin_action(db, admin_user, "content.unhide", report.target_type, report.target_id,
                            {"content_report_id": report.id, "reason": "Reporte descartado: se revierte el ocultamiento preventivo"},
                            request)
        owner_id = moderation.owner_id(db, report.target_type, target)
        owner = db.query(User).filter(User.id == owner_id).first() if owner_id else None
        if owner and report.target_type != "message":
            legal_moderation.notify_person(
                db, owner, "content_restored", "Tu publicación volvió a mostrarse",
                "Revisamos el reporte y no encontramos un incumplimiento. Ya se muestra de nuevo.",
                data={"target_type": report.target_type, "target_id": report.target_id},
            )

    now = datetime.datetime.utcnow()
    notes = (payload.notes or "").strip() or None
    resolved = [report]
    if payload.action:
        # Los demás reportes abiertos sobre el mismo contenido quedan atendidos con la misma acción
        resolved += db.query(ContentReport).filter(
            ContentReport.target_type == report.target_type, ContentReport.target_id == report.target_id,
            ContentReport.status == "open", ContentReport.id != report.id,
        ).all()
    for r in resolved:
        r.status = payload.status
        r.action = payload.action
        r.admin_notes = notes if r.id == report.id else f"Resuelto junto con el reporte #{report.id}."
        r.resolved_by = admin_user.id
        r.resolved_at = now
    record_admin_action(
        db, admin_user, "report.resolve" if payload.status == "resolved" else "report.dismiss", "content_report",
        report.id, {"action": payload.action, "also_resolved": [r.id for r in resolved[1:]]}, request,
    )
    # Formulario público: si dejaron correo, se les avisa el resultado (sin detalles de la medida)
    for r in resolved:
        if r.contact_email and not r.reporter_id:
            legal_moderation.send_email(
                r.contact_email, f"Revisamos tu reporte {r.folio or ''}".strip(),
                ("Revisamos el contenido que nos reportaste y tomamos medidas. Gracias por cuidar a la comunidad."
                 if payload.action else
                 "Revisamos el contenido que nos reportaste y no encontramos un incumplimiento de nuestras reglas."),
            )
    if payload.action:
        # reporter_id NULL = solicitud sin cuenta (retiro de una publicación importada): no hay a quién avisar
        for reporter_id in {r.reporter_id for r in resolved if r.reporter_id}:
            create_notification(
                db, user_id=reporter_id, type="report_resolved", title="Gracias por tu reporte 💛",
                body="Revisamos el contenido que nos señalaste y tomamos medidas. Gracias por cuidar a la comunidad.",
                data={"content_report_id": report.id}, commit=False,
            )
    db.commit()
    db.refresh(report)
    return _admin_rows(db, [report])[0]


@router.patch("/admin/content/{target_type}/{target_id}", response_model=dict)
def set_content_hidden(
    target_type: ReportTargetType,
    target_id: int,
    payload: HiddenUpdate,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Oculta o vuelve a mostrar un perro, reporte o producto (también un refugio suspendido)."""
    target = moderation.load_target(db, target_type, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No encontramos ese contenido.")
    details = None
    was_hidden = target.status == "suspended" if target_type == "refuge" else bool(getattr(target, "is_hidden", False))
    if target_type in ("dog", "lost_report", "product", "veterinary", "veterinary_review"):
        target.is_hidden = payload.hidden
    elif target_type == "refuge":
        if payload.hidden and target.status != "suspended":
            details = moderation.hide(db, target_type, target)
        elif not payload.hidden and target.status == "suspended":
            last = (
                db.query(AdminAuditLog)
                .filter(AdminAuditLog.action == "content.hide", AdminAuditLog.target_type == "refuge",
                        AdminAuditLog.target_id == target_id)
                .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc()).first()
            )
            previous = ((last.details or {}).get("refuge_status_from") if last else None) or "approved"
            target.status = "approved" if previous == "suspended" else previous
            details = moderation.restore_hidden(db, last.details if last else None)
    else:
        raise HTTPException(status_code=400, detail="Este tipo de contenido no se puede ocultar ni mostrar desde aquí.")
    if payload.hidden and not was_hidden:
        # Medida del equipo: copia cifrada y aviso con la regla, el origen y cómo apelar (moderacion.html §6 y §9)
        owner_id = moderation.owner_id(db, target_type, target)
        owner = db.query(User).filter(User.id == owner_id).first() if owner_id else None
        rule = payload.rule or "contenido_inapropiado"
        record = evidence.capture(db, kind="contenido_retirado", target_type=target_type, target_id=target_id, obj=target,
                                  owner_user_id=owner_id, reason=rule,
                                  decision={"action": "hide_content", "details": details, "actor_id": admin_user.id},
                                  actor_id=admin_user.id)
        blocked = []
        if payload.detection == "autoridad":
            blocked = staydown.block_urls(db, evidence.target_photo_urls(target_type, target), "autoridad",
                                          evidence_id=record.id, actor_id=admin_user.id)
        action = legal_moderation.record_action(
            db, user=owner, target_type=target_type, target_id=target_id, action="hide_content", rule=rule,
            detection=payload.detection, actor=admin_user,
            title=moderation.summary(db, target_type, target).get("title") or "", evidence_record=record,
            details=details, notes=payload.notes,
        )
        details = (details or {}) | {"moderation_action": action.folio, "blocked_hashes": len(blocked)}
    elif not payload.hidden and was_hidden:
        # Volver a mostrar levanta las medidas de ocultamiento vigentes sobre ese contenido
        db.query(ModerationAction).filter(
            ModerationAction.target_type == target_type, ModerationAction.target_id == target_id,
            ModerationAction.status == "active", ModerationAction.action == "hide_content",
        ).update({"status": "lifted", "revoked_at": datetime.datetime.utcnow()}, synchronize_session=False)
    record_admin_action(db, admin_user, "content.hide" if payload.hidden else "content.unhide", target_type, target_id,
                        details, request)
    db.commit()
    return {"target": moderation.summary(db, target_type, target)}


@router.post("/admin/users/{id}/unsuspend", response_model=dict)
def unsuspend_user(id: int, request: Request, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Reactiva una cuenta suspendida y vuelve a mostrar lo que se ocultó al suspenderla.

    No se muestra lo que un admin ocultó por un reporte (acción hide_content).
    """
    user = db.query(User).filter(User.id == id).first()
    if not user:
        raise HTTPException(status_code=404, detail="No encontramos ese usuario.")
    if user.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Esa cuenta fue eliminada por su titular y no se puede reactivar.")
    last = (
        db.query(AdminAuditLog)
        .filter(AdminAuditLog.action == "user.suspend", AdminAuditLog.target_type == "user", AdminAuditLog.target_id == id)
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc()).first()
    )
    restored = moderation.restore_hidden(db, last.details if last else None)
    user.is_active = True
    user.suspended_at = None
    # Las medidas de suspensión vigentes quedan levantadas (el registro de la medida se conserva)
    db.query(ModerationAction).filter(
        ModerationAction.user_id == user.id, ModerationAction.status == "active",
        ModerationAction.action.in_(("suspend_user", "cancel_account")),
    ).update({"status": "lifted", "revoked_at": datetime.datetime.utcnow()}, synchronize_session=False)
    record_admin_action(db, admin_user, "user.unsuspend", "user", user.id, restored, request)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Otra cuenta activa ya verificó el teléfono de este usuario.")
    return {"ok": True, "restored": restored}
