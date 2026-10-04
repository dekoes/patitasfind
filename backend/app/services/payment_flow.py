"""Flujo de pagos compartido por endpoints, webhook y tareas (idempotente)."""
import datetime
import logging
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Donation, Order, OrderItem, PointLog, Product, Refuge, User
from app.services import payments
from app.utils.notifications import create_notification

logger = logging.getLogger(__name__)

PENDING_ORDER = ("pending_payment", "created")
FAILED_STATUSES = ("rejected", "cancelled", "refunded", "charged_back")


def _require_payments_or_dev():
    if not settings.payments_enabled and not settings.is_development:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Los pagos no están disponibles en este momento. Inténtalo más tarde.",
        )


# --------------------------------------------------------------------------- órdenes
def create_order_checkout(db: Session, user: User, items_payload, shipping_address: str):
    _require_payments_or_dev()
    if not items_payload:
        raise HTTPException(status_code=400, detail="Tu pedido debe tener al menos un producto.")

    product_ids = [i.product_id for i in items_payload]
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).with_for_update().all()}
    total = Decimal("0")
    lines = []
    for item in items_payload:
        product = products.get(item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"El producto {item.product_id} no existe.")
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0.")
        if not product.is_active:
            raise HTTPException(status_code=400, detail=f"{product.name} ya no está disponible.")
        if product.stock < item.quantity:
            raise HTTPException(status_code=400, detail=f"No hay suficiente inventario de {product.name}.")
        product.stock -= item.quantity
        total += Decimal(product.price) * item.quantity
        lines.append((product, item.quantity))

    order = Order(user_id=user.id, total=total, shipping_address=shipping_address, status="pending_payment")
    db.add(order)
    db.flush()
    for product, qty in lines:
        db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=qty, unit_price=product.price))

    checkout_url, simulated = None, False
    if settings.payments_enabled:
        try:
            pref = payments.create_preference(
                [{"title": p.name, "quantity": q, "unit_price": p.price} for p, q in lines],
                external_reference=f"order:{order.id}",
                back_query=f"order={order.id}",
                payer_email=user.email,
            )
        except payments.PaymentError as exc:
            db.rollback()
            raise HTTPException(status_code=502, detail=str(exc))
        order.provider = "mercadopago"
        order.provider_preference_id = pref["id"]
        checkout_url = pref["init_point"]
        db.commit()
    else:
        # Desarrollo sin Mercado Pago: el pago se simula como aprobado
        db.commit()
        mark_order_paid(db, order, payment_id=None, provider="simulated")
        simulated = True
    db.refresh(order)
    return order, checkout_url, simulated


def mark_order_paid(db: Session, order: Order, payment_id: str | None, provider: str = "mercadopago"):
    if order.status not in PENDING_ORDER:
        return False
    order.status = "paid"
    order.paid_at = datetime.datetime.utcnow()
    order.provider = order.provider or provider
    if payment_id:
        order.provider_payment_id = str(payment_id)
    db.commit()
    notified = set()
    for item in order.items:
        refuge_id = item.product.refuge_id
        if refuge_id in notified:
            continue
        refuge = db.query(Refuge).filter(Refuge.id == refuge_id).first()
        if refuge:
            create_notification(
                db, user_id=refuge.user_id, type="new_order", title="Nueva venta en la tienda",
                body=f"Recibiste un pedido pagado por ${order.total:.2f} MXN. Revisa la orden #{order.id}.",
                data={"order_id": order.id},
            )
        notified.add(refuge_id)
    create_notification(
        db, user_id=order.user_id, type="order_paid", title="¡Pago confirmado!",
        body=f"Tu pedido #{order.id} fue pagado. Gracias por apoyar a los refugios 🐾",
        data={"order_id": order.id},
    )
    return True


def cancel_order(db: Session, order: Order, payment_id: str | None = None):
    if order.status not in PENDING_ORDER:
        return False
    for item in order.items:
        item.product.stock += item.quantity
    order.status = "cancelled"
    if payment_id:
        order.provider_payment_id = str(payment_id)
    db.commit()
    return True


# --------------------------------------------------------------------------- donaciones
def donation_points(amount) -> int:
    return max(1, int(Decimal(str(amount)) // 10))


def create_donation_checkout(db: Session, user: User, refuge_id: int, amount) -> dict:
    _require_payments_or_dev()
    amount = Decimal(str(amount))
    if amount < 10:
        raise HTTPException(status_code=400, detail="El monto mínimo de donación es de $10 MXN.")
    refuge = db.query(Refuge).filter(Refuge.id == refuge_id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="No encontramos ese refugio.")
    if refuge.status != "approved":
        raise HTTPException(status_code=400, detail="Este refugio todavía no está verificado.")

    donation = Donation(user_id=user.id, refuge_id=refuge.id, amount=amount, status="pending")
    db.add(donation)
    db.flush()
    checkout_url, simulated = None, False
    if settings.payments_enabled:
        try:
            pref = payments.create_preference(
                [{"title": f"Donación a {refuge.name}", "quantity": 1, "unit_price": amount}],
                external_reference=f"donation:{donation.id}",
                back_query=f"donation={donation.id}",
                payer_email=user.email,
            )
        except payments.PaymentError as exc:
            db.rollback()
            raise HTTPException(status_code=502, detail=str(exc))
        donation.provider = "mercadopago"
        donation.provider_preference_id = pref["id"]
        checkout_url = pref["init_point"]
        db.commit()
    else:
        db.commit()
        approve_donation(db, donation, payment_id=None, provider="simulated")
        simulated = True
    db.refresh(donation)
    return {"donation_id": donation.id, "status": donation.status, "checkout_url": checkout_url, "simulated": simulated}


def approve_donation(db: Session, donation: Donation, payment_id: str | None, provider: str = "mercadopago"):
    if donation.status != "pending":
        return False
    donation.status = "approved"
    donation.provider = donation.provider or provider
    if payment_id:
        donation.provider_payment_id = str(payment_id)
    refuge = donation.refuge
    points = donation_points(donation.amount)
    refuge.points += points
    donor = donation.user
    db.add(PointLog(refuge_id=refuge.id, action="donation", points=points,
                    description=f"Donación de ${donation.amount} MXN de {donor.full_name if donor else 'un donante'}"))
    db.commit()
    create_notification(
        db, user_id=refuge.user_id, type="donation_received", title="¡Recibiste una donación!",
        body=f"{donor.full_name if donor else 'Alguien'} donó ${donation.amount} MXN a {refuge.name}. +{points} puntos.",
        data={"donation_id": donation.id},
    )
    return True


def reject_donation(db: Session, donation: Donation, payment_id: str | None = None):
    if donation.status != "pending":
        return False
    donation.status = "rejected"
    if payment_id:
        donation.provider_payment_id = str(payment_id)
    db.commit()
    return True


# --------------------------------------------------------------------------- webhook
def process_payment(db: Session, payment_id: str) -> str:
    """Consulta el pago en Mercado Pago y actualiza la orden/donación. Devuelve el resultado."""
    if not settings.payments_enabled:
        return "payments_disabled"
    payment = payments.get_payment(payment_id)
    if not payment:
        return "payment_not_found"
    ref = str(payment.get("external_reference") or "")
    mp_status = payment.get("status")
    kind, _, raw_id = ref.partition(":")
    if not raw_id.isdigit():
        return "unknown_reference"
    obj_id = int(raw_id)
    if kind == "order":
        order = db.query(Order).filter(Order.id == obj_id).first()
        if not order:
            return "order_not_found"
        if mp_status == "approved":
            mark_order_paid(db, order, payment_id)
        elif mp_status in FAILED_STATUSES:
            cancel_order(db, order, payment_id)
        return f"order:{order.status}"
    if kind == "donation":
        donation = db.query(Donation).filter(Donation.id == obj_id).first()
        if not donation:
            return "donation_not_found"
        if mp_status == "approved":
            approve_donation(db, donation, payment_id)
        elif mp_status in FAILED_STATUSES:
            reject_donation(db, donation, payment_id)
        return f"donation:{donation.status}"
    return "unknown_reference"
