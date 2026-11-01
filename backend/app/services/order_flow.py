"""Máquina de estados de los pedidos de la tienda (después del pago).

pending_payment -> paid -> preparing -> shipped -> delivered -> completed
                 \\-> cancelled (el comprador antes del envío, el pago no llegó a tiempo, el refugio no lo envió a
                     tiempo, o el refugio / el equipo con una causa objetiva registrada)
delivered/completed -> return_requested -> return_approved -> refunded | return_rejected

Quién puede hacer qué:
- Comprador: cancelar (antes del envío; si ya pagó se le reembolsa), confirmar la entrega, pedir devolución.
- Refugio vendedor: preparing, shipped (con paquetería y guía), delivered; aprobar o rechazar devoluciones;
  cancelar un pedido que no puede surtir con un motivo (consumidor-ecommerce-14: reembolso total inmediato).
- Admin: reembolsar (total o parcial) cualquier pedido pagado y cancelar con un motivo.
Un reembolso PARCIAL no cierra el pedido: conserva su estado y su inventario, y se pueden hacer más reembolsos
hasta completar el total; cada uno queda en order_refunds (estados de cuenta del mes en que ocurre).
Cada cambio queda en Order.timeline y avisa al comprador en la app y por correo (services/notify.py).

Plazos de devolución (docs/legal/secciones/consumidor-ecommerce.json):
- Revocación ("arrepentimiento", "otro"): RETURN_WINDOW_DAYS = 5 días HÁBILES desde la entrega
  (LFPC art. 56; hallazgo consumidor-ecommerce-09), sin contar sábados, domingos ni días de descanso
  obligatorio (LFT art. 74).
- Producto defectuoso, que no corresponde o que no llegó: RETURN_CLAIM_WINDOW_DAYS = 60 días naturales
  (LFPC art. 93: dos meses; hallazgos consumidor-ecommerce-10 y 11).
Plazo de despacho (consumidor-ecommerce-13): handling_days hábiles desde el pago (el mayor de los productos);
al vencer se avisa al refugio y al comprador; ORDER_DISPATCH_GRACE_DAYS hábiles después se cancela y se
reembolsa solo (tarea diaria enforce_dispatch_deadlines).
"""
import datetime
import logging
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, Refuge, User
from app.services import payment_flow as pf
from app.services.audit import record_admin_action

logger = logging.getLogger(__name__)

MX_TZ = ZoneInfo("America/Mexico_City")
RETURN_REASONS = ("defectuoso", "no_corresponde", "no_llego", "arrepentimiento", "otro")
# Etiquetas en español para avisos, historial y correos (la app usa las mismas en tienda.js)
RETURN_REASON_LABELS = {
    "defectuoso": "llegó dañado o defectuoso", "no_corresponde": "no corresponde a lo que se pidió",
    "no_llego": "no llegó", "arrepentimiento": "cambio de opinión (revocación)", "otro": "otro motivo",
}
CLAIM_REASONS = ("defectuoso", "no_corresponde", "no_llego")  # plazo largo (LFPC art. 93)
BUYER_CANCELLABLE = ("pending_payment", "created", "paid", "preparing")
PAID_CANCELLABLE = ("paid", "preparing")  # cobrados y todavía sin enviar: se cancelan con reembolso total
SELLER_CANCELLABLE = PAID_CANCELLABLE
ADMIN_CANCELLABLE = ("pending_payment", "created", "paid", "preparing")
# Causas objetivas para que el refugio o el equipo cancelen (consumidor-ecommerce-14)
CANCEL_REASONS = {
    "sin_inventario": "Se agotó el producto", "no_puedo_enviar": "No es posible enviarlo",
    "direccion_invalida": "La dirección de entrega no es válida o no tiene cobertura",
    "sospecha_fraude": "Posible fraude en el pago", "otro": "Otro motivo",
}
RETURNABLE = ("delivered", "completed")
ADMIN_REFUNDABLE = ("paid", "preparing", "shipped", "delivered", "completed", "return_requested", "return_approved",
                    "return_rejected", "refund_pending", "amount_mismatch")
REFUND_RETRYABLE = ("error", "insufficient_funds")  # el reembolso automático de una devolución falló
# Estado al que puede pasar el refugio -> estados de origen permitidos
REFUGE_TRANSITIONS = {
    "preparing": ("paid",),
    "shipped": ("paid", "preparing", "shipped"),  # "shipped" otra vez = corregir la guía
    "delivered": ("shipped",),
}
STATUS_LABELS = {
    "pending_payment": "Esperando pago", "paid": "Pagado", "preparing": "En preparación", "shipped": "Enviado",
    "delivered": "Entregado", "completed": "Completado", "cancelled": "Cancelado", "expired": "Expirado",
    "return_requested": "Devolución solicitada", "return_approved": "Devolución aprobada",
    "return_rejected": "Devolución rechazada", "refunded": "Reembolsado", "refund_pending": "Reembolso pendiente",
    "amount_mismatch": "En revisión",
}


def _now():
    return datetime.datetime.utcnow()


def return_reason_label(reason: str | None) -> str:
    return RETURN_REASON_LABELS.get(reason or "", reason or "")


# --------------------------------------------------------------------------- días hábiles
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime.date:
    first = datetime.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + datetime.timedelta(days=offset + 7 * (n - 1))


def mx_holidays(year: int) -> set[datetime.date]:
    """Días de descanso obligatorio (LFT art. 74). El 1 de octubre solo cada seis años (cambio de Ejecutivo)."""
    days = {
        datetime.date(year, 1, 1),
        _nth_weekday(year, 2, 0, 1),  # primer lunes de febrero
        _nth_weekday(year, 3, 0, 3),  # tercer lunes de marzo
        datetime.date(year, 5, 1),
        datetime.date(year, 9, 16),
        _nth_weekday(year, 11, 0, 3),  # tercer lunes de noviembre
        datetime.date(year, 12, 25),
    }
    if year >= 2024 and (year - 2024) % 6 == 0:
        days.add(datetime.date(year, 10, 1))
    return days


def is_business_day(day: datetime.date) -> bool:
    return day.weekday() < 5 and day not in mx_holidays(day.year)


def add_business_days(day: datetime.date, n: int) -> datetime.date:
    current, left = day, n
    while left > 0:
        current += datetime.timedelta(days=1)
        if is_business_day(current):
            left -= 1
    return current


def _local_date(utc_naive: datetime.datetime) -> datetime.date:
    return utc_naive.replace(tzinfo=datetime.timezone.utc).astimezone(MX_TZ).date()


def _end_of_local_day_utc(day: datetime.date) -> datetime.datetime:
    end = datetime.datetime.combine(day, datetime.time(23, 59, 59), tzinfo=MX_TZ)
    return end.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _fmt_day(utc_naive: datetime.datetime) -> str:
    return _local_date(utc_naive).strftime("%d/%m/%Y")


def return_deadline(delivered_at: datetime.datetime | None, reason: str) -> datetime.datetime | None:
    """Fecha límite (UTC, sin zona) para pedir una devolución por ese motivo."""
    if not delivered_at:
        return None
    if reason in CLAIM_REASONS:
        return delivered_at + datetime.timedelta(days=settings.return_claim_window_days)
    last_day = add_business_days(_local_date(delivered_at), settings.return_window_days)
    return _end_of_local_day_utc(last_day)


def return_deadlines(order: Order) -> dict:
    """Plazos que la app muestra en "Mis pedidos"."""
    if not order.delivered_at:
        return {}
    return {"revocation_until": return_deadline(order.delivered_at, "arrepentimiento"),
            "claim_until": return_deadline(order.delivered_at, "defectuoso")}


def order_handling_days(order: Order) -> int:
    days = [i.product.handling_days for i in order.items if i.product is not None and i.product.handling_days is not None]
    return max(days) if days else 3


def dispatch_deadline(order: Order) -> datetime.datetime | None:
    """Último momento (UTC, sin zona) para que el refugio envíe: handling_days hábiles después del pago."""
    if not order.paid_at:
        return None
    return _end_of_local_day_utc(add_business_days(_local_date(order.paid_at), order_handling_days(order)))


def dispatch_cancel_at(order: Order) -> datetime.datetime | None:
    """Si no se envía antes de esta fecha, el pedido se cancela y se reembolsa solo."""
    due = dispatch_deadline(order)
    if not due:
        return None
    return _end_of_local_day_utc(add_business_days(_local_date(due), settings.order_dispatch_grace_days))


# --------------------------------------------------------------------------- utilidades
def _locked_order(db: Session, order_id: int) -> Order:
    order = pf._locked(db, Order, order_id)
    if not order:
        db.rollback()
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    return order


def _conflict(db: Session, detail: str):
    db.rollback()
    raise HTTPException(status_code=409, detail=detail)


def _buyer_order(db: Session, order_id: int, user: User) -> Order:
    order = _locked_order(db, order_id)
    if order.user_id != user.id:
        db.rollback()
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    return order


def _refund_now(db: Session, order_id: int, amount=None) -> dict:
    """Reembolsa en Mercado Pago sin bloqueos abiertos (lee el pedido de nuevo)."""
    db.rollback()
    order = db.query(Order).filter(Order.id == order_id).first()
    return pf.refund_at_provider(db, order, amount)


def _notify_buyer(db: Session, order: Order, kind: str, title: str, body: str, **extra) -> None:
    pf.notify_order_user(db, order.user_id, kind, title, body, order, extra=extra or None)


def _cancel_order(db: Session, order_id: int, *, by: str, reason: str, note: str | None, allowed: tuple,
                  conflict_detail: str, buyer: User | None = None) -> tuple[Order, Decimal | None]:
    """Cancela antes del envío. Si ya se cobró, reembolsa TODO lo que falte en Mercado Pago (fuera del bloqueo)
    y devuelve el inventario. Sin commit. Devuelve (pedido, monto reembolsado o None).

    Lanza pf.RefundFailed si Mercado Pago no reembolsa: en ese caso el pedido no cambia.
    """
    lock = (lambda: _buyer_order(db, order_id, buyer)) if buyer else (lambda: _locked_order(db, order_id))
    order = lock()
    if order.status not in allowed:
        _conflict(db, conflict_detail)
    refunded = None
    if order.status in PAID_CANCELLABLE:
        remaining = pf.refundable_remaining(order)
        whole = remaining >= pf.money2(order.paid_amount or order.total)
        refund = _refund_now(db, order_id, None if whole else remaining) if remaining > 0 else None
        order = lock()
        if order.status not in PAID_CANCELLABLE:  # cambió mientras se reembolsaba
            logger.warning("El pedido %s cambió a %s durante la cancelación con reembolso", order.id, order.status)
            pf._notify_admins(db, "order_cancel_race", "Revisa un pedido cancelado",
                              f"El pedido #{order.id} se reembolsó por cancelación pero ya estaba {order.status}.",
                              {"order_id": order.id})
        if remaining > 0:
            pf.record_refund(db, order, remaining, refund, by=by, note="Reembolso por cancelación.", final=True)
            refunded = remaining
        order.refunded_at = _now()
    if order.status in pf.STOCK_HELD_ORDER:
        pf.release_stock(db, order)
    timeline = {"buyer": "Cancelado por el comprador.", "refuge": "Cancelado por el refugio.",
                "admin": "Cancelado por el equipo de GuauWoow.",
                "system": "Cancelado automáticamente: el refugio no lo envió a tiempo."}.get(by, "Cancelado.")
    if note:
        timeline += f" {note}"
    if refunded is not None:
        timeline += " Se reembolsó el pago."
    pf.set_order_status(order, "cancelled", timeline, by=by)
    order.cancelled_at = _now()
    order.cancel_reason = reason
    order.cancel_note = note
    return order, refunded


def _refund_text(refunded) -> str:
    if refunded is None:
        return ""
    return (f" Te devolvimos {pf._money(refunded)} MXN a tu medio de pago original; puede tardar unos días en "
            "reflejarse.")


# --------------------------------------------------------------------------- comprador
def buyer_cancel(db: Session, order_id: int, user: User) -> Order:
    """Cancela antes del envío. Si ya estaba pagado, se reembolsa completo y se devuelve el inventario."""
    try:
        order, refunded = _cancel_order(
            db, order_id, by="buyer", reason="buyer", note=None, allowed=BUYER_CANCELLABLE, buyer=user,
            conflict_detail="Este pedido ya no se puede cancelar: ya salió o ya está cerrado. Si tienes un problema, "
                            "solicita una devolución cuando lo recibas.")
    except pf.RefundFailed as exc:
        db.rollback()
        order = db.query(Order).filter(Order.id == order_id).first()
        pf._notify_admins(db, "order_refund_failed", "Reembolso pendiente",
                          f"El comprador quiso cancelar el pedido #{order_id} y falló el reembolso: {exc.detail}",
                          {"order_id": order_id})
        if order is not None and exc.code == "insufficient_funds":
            pf._notify_refuges_of_order(db, order, "order_refund_failed", "No se pudo reembolsar una cancelación",
                                        f"El comprador quiso cancelar el pedido #{order_id}, pero tu cuenta de Mercado "
                                        "Pago no tiene saldo suficiente para reembolsarlo. Ingresa saldo y no lo envíes "
                                        "todavía: te escribiremos para resolverlo.")
        db.commit()
        raise HTTPException(status_code=409 if exc.status_code < 500 else exc.status_code,
                            detail="No pudimos procesar el reembolso de tu cancelación en este momento. Ya avisamos al "
                                   "refugio y a nuestro equipo; inténtalo más tarde o escríbenos desde Ayuda.")
    _notify_buyer(db, order, "order_cancelled", "Pedido cancelado",
                  f"Cancelaste tu pedido #{order.id}." + _refund_text(refunded))
    if refunded is not None:
        pf._notify_refuges_of_order(db, order, "order_cancelled", "Pedido cancelado",
                                    f"El comprador canceló el pedido #{order.id} y se le reembolsó. No lo envíes.")
        pf.notify_invoice_cancellation(db, order)
    db.commit()
    db.refresh(order)
    return order


def confirm_delivery(db: Session, order_id: int, user: User) -> Order:
    order = _buyer_order(db, order_id, user)
    if order.status != "shipped":
        _conflict(db, "Solo puedes confirmar la entrega de un pedido enviado.")
    order.delivered_at = _now()
    pf.set_order_status(order, "delivered", "El comprador confirmó que lo recibió.", by="buyer")
    _notify_buyer(db, order, "order_delivered", "Pedido entregado",
                  f"Confirmaste la entrega del pedido #{order.id}. ¡Gracias por apoyar! 🐾")
    pf._notify_refuges_of_order(db, order, "order_delivered", "Pedido entregado",
                                f"El comprador confirmó que recibió el pedido #{order.id}.")
    db.commit()
    db.refresh(order)
    return order


def request_return(db: Session, order_id: int, user: User, reason: str, details: str | None, photos: list) -> Order:
    order = _buyer_order(db, order_id, user)
    if order.status not in RETURNABLE:
        _conflict(db, "Solo puedes pedir una devolución de un pedido entregado.")
    if reason not in RETURN_REASONS:
        _conflict(db, "Elige un motivo de devolución válido.")
    deadline = return_deadline(order.delivered_at, reason)
    if deadline is None or _now() > deadline:
        if reason in CLAIM_REASONS:
            msg = f"El plazo para reclamar ({settings.return_claim_window_days} días desde la entrega) ya venció."
        else:
            msg = (f"El plazo para devolver por arrepentimiento ({settings.return_window_days} días hábiles desde la "
                   "entrega) ya venció. Si el producto llegó dañado o no corresponde, elige ese motivo.")
        _conflict(db, msg)
    label = return_reason_label(reason)
    order.return_reason = reason
    order.return_details = (details or "").strip() or None
    order.return_photos = list(photos or [])
    order.return_requested_at = _now()
    order.return_decided_at = None
    order.return_decision_note = None
    pf.set_order_status(order, "return_requested", f"Motivo: {label}.", by="buyer")
    _notify_buyer(db, order, "order_return_requested", "Recibimos tu solicitud de devolución",
                  f"El refugio revisará tu solicitud del pedido #{order.id} y te avisaremos su respuesta.")
    pf._notify_refuges_of_order(db, order, "order_return_requested", "Solicitud de devolución",
                                f"El comprador pidió devolver el pedido #{order.id} (motivo: {label}). "
                                "Revísala en Mi tienda > Pedidos.")
    db.commit()
    db.refresh(order)
    return order


# --------------------------------------------------------------------------- refugio
def refuge_update(db: Session, order_id: int, refuge: Refuge, new_status: str, fields: dict) -> Order:
    """preparing | shipped (paquetería y guía obligatorias) | delivered. fields: carrier, tracking_number, tracking_url."""
    order = _locked_order(db, order_id)
    allowed = REFUGE_TRANSITIONS.get(new_status, ())
    if order.status not in allowed:
        if order.status in ("delivered", "completed"):
            _conflict(db, "Este pedido ya fue entregado.")
        if order.status in pf.PENDING_ORDER or order.status in pf.CLOSED_ORDER:
            _conflict(db, "Solo puedes preparar o enviar pedidos pagados.")
        _conflict(db, f"No puedes pasar este pedido de «{STATUS_LABELS.get(order.status, order.status)}» a "
                      f"«{STATUS_LABELS.get(new_status, new_status)}».")
    for key in ("carrier", "tracking_number", "tracking_url"):
        if key in fields:
            setattr(order, key, (fields[key] or "").strip() or None)
    now = _now()
    if new_status == "preparing":
        order.preparing_at = now
        pf.set_order_status(order, "preparing", None, by="refuge")
        _notify_buyer(db, order, "order_preparing", "Tu pedido se está preparando",
                      f"{refuge.name} está preparando tu pedido #{order.id}.")
    elif new_status == "shipped":
        # Guía con rastreo obligatoria: evidencia para contracargos (gap-custodia-...-08; consumidor-ecommerce-13)
        if not order.carrier or not order.tracking_number:
            _conflict(db, "Para marcarlo como enviado escribe la paquetería y el número de guía.")
        correction = order.status == "shipped"
        order.shipped_at = order.shipped_at or now
        guide = ", ".join(p for p in (order.carrier, f"guía {order.tracking_number}") if p)
        pf.set_order_status(order, "shipped", ("Guía corregida: " if correction else "") + guide, by="refuge")
        _notify_buyer(db, order, "order_shipped", "¡Tu pedido va en camino!" if not correction else "Guía actualizada",
                      f"{refuge.name} envió tu pedido #{order.id}. {guide}.",
                      carrier=order.carrier, tracking_number=order.tracking_number, tracking_url=order.tracking_url)
    else:
        order.delivered_at = now
        pf.set_order_status(order, "delivered", "El refugio marcó el pedido como entregado.", by="refuge")
        _notify_buyer(db, order, "order_delivered", "Pedido entregado",
                      f"{refuge.name} marcó tu pedido #{order.id} como entregado. Si algo no está bien, puedes pedir "
                      "una devolución desde Mis pedidos. ¡Gracias por apoyar! 🐾")
    db.commit()
    db.refresh(order)
    return order


def _check_cancel_reason(reason: str, note: str | None) -> tuple[str, str]:
    if reason not in CANCEL_REASONS:
        raise HTTPException(status_code=400, detail="Elige el motivo de la cancelación.")
    note = " ".join((note or "").split())
    if len(note) < 10:
        raise HTTPException(status_code=400, detail="Explica el motivo de la cancelación (mínimo 10 caracteres): queda "
                                                    "registrado y se le muestra al comprador.")
    return CANCEL_REASONS[reason], note[:1000]


def seller_cancel(db: Session, order_id: int, refuge: Refuge, reason: str, note: str | None) -> Order:
    """El refugio no puede surtir el pedido: se cancela con una causa objetiva y reembolso total inmediato
    (consumidor-ecommerce-14). El equipo recibe aviso para vigilar cancelaciones frecuentes."""
    label, note = _check_cancel_reason(reason, note)
    detail = f"{label}: {note}"
    order, refunded = _cancel_order(db, order_id, by="refuge", reason="refuge", note=detail, allowed=SELLER_CANCELLABLE,
                                    conflict_detail="Solo puedes cancelar pedidos pagados que todavía no envías.")
    _notify_buyer(db, order, "order_cancelled", "Tu pedido se canceló",
                  f"{refuge.name} canceló tu pedido #{order.id}. Motivo: {detail}." + _refund_text(refunded) +
                  " Si quieres, busca un producto equivalente en la tienda.")
    pf._notify_admins(db, "order_cancelled_by_refuge", "Un refugio canceló un pedido",
                      f"{refuge.name} canceló el pedido #{order.id}. Motivo: {detail}", {"order_id": order.id})
    pf.notify_invoice_cancellation(db, order)
    db.commit()
    db.refresh(order)
    return order


def admin_cancel(db: Session, order_id: int, admin: User, reason: str, note: str | None,
                 request: Request | None = None) -> Order:
    label, note = _check_cancel_reason(reason, note)
    detail = f"{label}: {note}"
    before = db.query(Order.status).filter(Order.id == order_id).scalar()
    order, refunded = _cancel_order(db, order_id, by="admin", reason="admin", note=detail, allowed=ADMIN_CANCELLABLE,
                                    conflict_detail="Solo se pueden cancelar pedidos que todavía no se envían.")
    _notify_buyer(db, order, "order_cancelled", "Tu pedido se canceló",
                  f"El equipo de GuauWoow canceló tu pedido #{order.id}. Motivo: {detail}." + _refund_text(refunded))
    if before in PAID_CANCELLABLE:
        pf._notify_refuges_of_order(db, order, "order_cancelled", "Pedido cancelado",
                                    f"El equipo de GuauWoow canceló el pedido #{order.id} ({detail}) y se le "
                                    "reembolsó al comprador. No lo envíes.")
    pf.notify_invoice_cancellation(db, order)
    record_admin_action(db, admin, "order_cancel", "order", order.id, request=request,
                        details={"from": before, "to": order.status, "reason": reason, "note": note,
                                 "refunded": str(refunded) if refunded is not None else None})
    db.commit()
    db.refresh(order)
    return order


def decide_return(db: Session, order_id: int, refuge: Refuge, approve: bool, note: str | None) -> Order:
    order = _locked_order(db, order_id)
    if order.status != "return_requested":
        _conflict(db, "Este pedido no tiene una solicitud de devolución pendiente.")
    note = (note or "").strip() or None
    if not approve and (not note or len(note) < 10):
        # La negativa debe explicarse con evidencia (consumidor-ecommerce-11)
        _conflict(db, "Explica por qué rechazas la devolución (mínimo 10 caracteres).")
    order.return_decided_at = _now()
    order.return_decision_note = note
    if not approve:
        pf.set_order_status(order, "return_rejected", note, by="refuge")
        _notify_buyer(db, order, "order_return_rejected", "Devolución rechazada",
                      f"{refuge.name} rechazó la devolución del pedido #{order.id}: {note} Si no estás de acuerdo, "
                      "escríbenos desde Ayuda.")
        db.commit()
        db.refresh(order)
        return order
    pf.set_order_status(order, "return_approved", note, by="refuge")
    _notify_buyer(db, order, "order_return_approved", "Devolución aprobada",
                  f"{refuge.name} aprobó la devolución del pedido #{order.id}. Estamos procesando tu reembolso.")
    # Defecto o no corresponde: además, bonificación de al menos 20 % a cargo del refugio (LFPC 92 Ter; reglas.py)
    from app.services import reglas

    reglas.register_bonus(db, order, by="refuge")
    db.commit()
    return _refund_approved_return(db, order_id)


def _refund_approved_return(db: Session, order_id: int) -> Order:
    """Aprobar una devolución dispara el reembolso. Si Mercado Pago falla, queda "return_approved" con
    refund_status=error (o insufficient_funds si la cuenta del refugio no tiene saldo) para reintentarlo."""
    try:
        return execute_refund(db, order_id, None, by="refuge", note="Reembolso por devolución aprobada.")
    except HTTPException as exc:
        code = getattr(exc, "code", None)
        order = _locked_order(db, order_id)
        order.refund_status = "insufficient_funds" if code == "insufficient_funds" else "error"
        order.review_note = pf._append_note(order.review_note, f"Falló el reembolso automático: {exc.detail}")
        pf._notify_admins(db, "order_refund_failed", "Reembolso pendiente",
                          f"No se pudo reembolsar el pedido #{order.id} tras aprobar su devolución: {exc.detail}",
                          {"order_id": order.id})
        if code == "insufficient_funds":
            pf._notify_refuges_of_order(db, order, "order_refund_failed", "Reembolso pendiente: falta saldo",
                                        f"No pudimos reembolsar el pedido #{order.id} porque tu cuenta de Mercado Pago "
                                        "no tiene saldo disponible suficiente. Ingresa saldo y vuelve a intentarlo desde "
                                        "Mi tienda > Pedidos.")
        db.commit()
        db.refresh(order)
        return order


def retry_return_refund(db: Session, order_id: int) -> Order:
    """El refugio reintenta el reembolso de una devolución aprobada (p. ej. después de ingresar saldo)."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.status != "return_approved" or order.refund_status not in REFUND_RETRYABLE:
        raise HTTPException(status_code=409, detail="Este pedido no tiene un reembolso pendiente.")
    return _refund_approved_return(db, order_id)


# --------------------------------------------------------------------------- reembolsos
def execute_refund(db: Session, order_id: int, amount, by: str, note: str | None = None,
                   item_ids: list[int] | None = None) -> Order:
    """Reembolsa en Mercado Pago. amount None = todo lo que falta por reembolsar.

    Un reembolso menor a lo que falta es PARCIAL: el pedido conserva su estado y su inventario (sigue su curso),
    se avisa a las dos partes y se pueden hacer más reembolsos hasta completar el total. El que completa el total
    deja el pedido "refunded" y, si no se había enviado, devuelve el inventario.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    if order.status == "refunded":
        raise HTTPException(status_code=409, detail="Este pedido ya fue reembolsado.")
    if order.status not in ADMIN_REFUNDABLE:
        raise HTTPException(status_code=409, detail="Este pedido no se puede reembolsar.")
    total = pf.money2(order.paid_amount or order.total)
    remaining = pf.refundable_remaining(order)
    if remaining <= 0:
        raise HTTPException(status_code=409, detail="Este pedido ya fue reembolsado.")
    amount = remaining if amount is None else pf.money2(amount)
    if amount <= 0 or amount > remaining:
        already = f" (ya se reembolsaron {pf._money(total - remaining)})" if remaining < total else ""
        raise HTTPException(status_code=400, detail=f"El monto a reembolsar debe estar entre $0.01 y "
                                                    f"{pf._money(remaining)}{already}.")
    final = amount == remaining
    refund = _refund_now(db, order_id, None if (final and remaining == total) else amount)
    order = _locked_order(db, order_id)
    previous = order.status
    if previous == "refunded":  # el aviso de Mercado Pago del reembolso total llegó primero
        order.refund_id = refund.get("id") or order.refund_id
        order.refund_status = refund.get("status") or order.refund_status
        db.commit()
        db.refresh(order)
        return order
    pf.record_refund(db, order, amount, refund, by=by, note=note, final=final)
    if order.return_requested_at and by == "admin":
        # Reembolso del equipo por una reclamación de defecto o no corresponde (p. ej. tras un rechazo del refugio)
        from app.services import reglas

        reglas.register_bonus(db, order, by=by, refunded=order.refund_amount, item_ids=item_ids)
    money = pf._money(amount)
    if not final:
        pf.add_timeline(order, "partial_refund", f"Reembolso parcial de {money} MXN." + (f" {note}" if note else ""),
                        by=by)
        _notify_buyer(db, order, "order_partial_refund", "Reembolso parcial de tu pedido",
                      f"Te reembolsamos {money} MXN del pedido #{order.id} a tu medio de pago original (reembolso "
                      "parcial). Puede tardar unos días en reflejarse.")
        if previous in pf.PAID_ORDER:
            pf._notify_refuges_of_order(
                db, order, "order_partial_refund", "Reembolso parcial",
                f"Se reembolsaron {money} MXN del pedido #{order.id} al comprador. El pedido sigue activo" +
                ("; envíalo como de costumbre." if previous in PAID_CANCELLABLE else "."))
        pf.notify_invoice_cancellation(db, order, partial_amount=amount)
        db.commit()
        db.refresh(order)
        return order
    if previous in pf.STOCK_HELD_ORDER:
        pf.release_stock(db, order)  # no se envió: el inventario vuelve a estar disponible
    order.refunded_at = _now()
    pf.set_order_status(order, "refunded", note or f"Reembolso de {money} MXN.", by=by)
    _notify_buyer(db, order, "order_refunded", "Reembolso de tu pedido",
                  f"Te reembolsamos {money} MXN del pedido #{order.id} a tu medio de pago original. "
                  "Puede tardar unos días en reflejarse.")
    if previous in ("paid", "preparing", "shipped"):
        pf._notify_refuges_of_order(db, order, "order_refunded", "Pedido reembolsado",
                                    f"El pedido #{order.id} fue reembolsado." +
                                    (" No lo envíes." if previous in PAID_CANCELLABLE else ""))
    pf.notify_invoice_cancellation(db, order)
    db.commit()
    db.refresh(order)
    return order


def admin_refund(db: Session, order_id: int, admin: User, amount, request: Request | None = None,
                 item_ids: list[int] | None = None) -> Order:
    before = db.query(Order.status).filter(Order.id == order_id).scalar()
    order = execute_refund(db, order_id, amount, by="admin", note="Reembolso hecho por el equipo de GuauWoow.",
                           item_ids=item_ids)
    record_admin_action(db, admin, "order_refund", "order", order.id, request=request,
                        details={"from": before, "to": order.status,
                                 "amount": str(pf.money2(amount)) if amount is not None else str(order.refund_amount),
                                 "refunded_total": str(order.refund_amount), "refund_id": order.refund_id})
    db.commit()
    db.refresh(order)
    return order


# --------------------------------------------------------------------------- tareas diarias
def auto_complete_orders(db: Session, now: datetime.datetime | None = None, limit: int = 500) -> int:
    """Entregados hace más de ORDER_AUTO_COMPLETE_DAYS sin devolución => "completed"."""
    cutoff = (now or _now()) - datetime.timedelta(days=settings.order_auto_complete_days)
    ids = [oid for (oid,) in db.query(Order.id).filter(Order.status == "delivered", Order.delivered_at < cutoff)
           .order_by(Order.id).limit(limit)]
    db.rollback()
    done = 0
    for order_id in ids:
        try:
            order = pf._locked(db, Order, order_id)
            if not order or order.status != "delivered":
                db.rollback()
                continue
            order.completed_at = _now()
            pf.set_order_status(order, "completed", "Se completó solo: no hubo devolución en el plazo.")
            _notify_buyer(db, order, "order_completed", "Pedido completado",
                          f"Tu pedido #{order.id} quedó completado. ¡Gracias por apoyar a los refugios! 🐾")
            db.commit()
            done += 1
        except Exception:  # noqa: BLE001 - un pedido con problemas no detiene a los demás
            db.rollback()
            logger.exception("No se pudo completar el pedido %s", order_id)
    if done:
        logger.info("Pedidos completados automáticamente: %s", done)
    return done


def _dispatch_timeout_cancel(db: Session, order_id: int) -> Order:
    order, refunded = _cancel_order(db, order_id, by="system", reason="dispatch_timeout", note=None,
                                    allowed=SELLER_CANCELLABLE, conflict_detail="El pedido ya no está pendiente de envío.")
    _notify_buyer(db, order, "order_cancelled", "Cancelamos tu pedido",
                  f"Cancelamos tu pedido #{order.id} porque el refugio no lo envió a tiempo." + _refund_text(refunded) +
                  " Si quieres, busca un producto equivalente en la tienda.")
    pf._notify_refuges_of_order(db, order, "order_cancelled", "Pedido cancelado por falta de envío",
                                f"El pedido #{order.id} se canceló y se reembolsó automáticamente porque no se envió "
                                "a tiempo. No lo envíes.")
    pf.notify_invoice_cancellation(db, order)
    db.commit()
    return order


def _dispatch_warning(db: Session, order_id: int, due, cancel_at) -> bool:
    order = _locked_order(db, order_id)
    if order.status not in SELLER_CANCELLABLE or order.dispatch_warned_at:
        db.rollback()
        return False
    order.dispatch_warned_at = _now()
    pf._notify_refuges_of_order(
        db, order, "order_dispatch_overdue", "Pedido sin enviar",
        f"El plazo para enviar el pedido #{order.id} venció el {_fmt_day(due)}. Envíalo y registra la guía antes del "
        f"{_fmt_day(cancel_at)} o se cancelará y se le reembolsará al comprador automáticamente. Si no puedes "
        "surtirlo, cancélalo desde Mi tienda > Pedidos.")
    _notify_buyer(db, order, "order_dispatch_overdue", "Tu pedido va retrasado",
                  f"El refugio aún no envía tu pedido #{order.id} (el plazo venció el {_fmt_day(due)}). Si no sale "
                  f"antes del {_fmt_day(cancel_at)}, lo cancelamos y te reembolsamos automáticamente. También puedes "
                  "cancelarlo tú desde Mis pedidos.")
    db.commit()
    return True


def enforce_dispatch_deadlines(db: Session, now: datetime.datetime | None = None, limit: int = 500,
                               order_ids: list[int] | None = None) -> dict:
    """Pedidos pagados sin enviar: aviso al vencer el plazo de despacho y cancelación con reembolso total al
    vencer la gracia (consumidor-ecommerce-13). order_ids limita la revisión a pedidos concretos (soporte, pruebas)."""
    now = now or _now()
    query = db.query(Order.id).filter(Order.status.in_(SELLER_CANCELLABLE), Order.paid_at.isnot(None),
                                      Order.paid_at < now - datetime.timedelta(days=1))
    if order_ids is not None:
        query = query.filter(Order.id.in_(order_ids))
    ids = [oid for (oid,) in query.order_by(Order.id).limit(limit)]
    db.rollback()
    result = {"warned": 0, "cancelled": 0, "failed": 0}
    for order_id in ids:
        try:
            order = db.query(Order).filter(Order.id == order_id).first()
            due, cancel_at = dispatch_deadline(order), dispatch_cancel_at(order)
            db.rollback()
            if not due or now <= due:
                continue
            if now > cancel_at:
                _dispatch_timeout_cancel(db, order_id)
                result["cancelled"] += 1
            elif _dispatch_warning(db, order_id, due, cancel_at):
                result["warned"] += 1
        except HTTPException as exc:  # p. ej. Mercado Pago no pudo reembolsar: lo atiende un admin
            db.rollback()
            result["failed"] += 1
            logger.warning("No se pudo cancelar por falta de envío el pedido %s: %s", order_id, exc.detail)
            pf._notify_admins(db, "order_refund_failed", "Pedido vencido sin cancelar",
                              f"El pedido #{order_id} venció sin envío y no se pudo cancelar/reembolsar solo: "
                              f"{exc.detail}", {"order_id": order_id})
            db.commit()
        except Exception:  # noqa: BLE001 - un pedido con problemas no detiene a los demás
            db.rollback()
            result["failed"] += 1
            logger.exception("No se pudo revisar el plazo de envío del pedido %s", order_id)
    if any(result.values()):
        logger.info("Plazos de despacho: %s", result)
    return result
