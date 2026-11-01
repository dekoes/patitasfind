"""Flujo de pagos compartido por endpoints, webhook y tareas (idempotente).

Reglas:
- El inventario se aparta en una transacción corta y se libera si falla Mercado Pago o si el pedido expira.
- Un pago rechazado NO cancela el pedido: en Checkout Pro el comprador puede reintentar con el mismo link.
- Cada pago aprobado se aplica una sola vez (fila bloqueada con FOR UPDATE + tabla payment_events única).
- Si el monto o la moneda no coinciden, no se marca pagado: queda "amount_mismatch" para revisión.
- Un pago aprobado que llega tarde (pedido cancelado por vencimiento) vuelve a apartar el inventario o queda
  "refund_pending" para que un admin lo reembolse.

Mercado Pago Marketplace (split 1:1, fiscal-tienda-22 y gap-custodia-...-01/09/13):
- La tienda cobra SIEMPRE con la cuenta del refugio vendedor (token OAuth) y `marketplace_fee`; si el refugio no
  ha vinculado su cuenta, sus productos se ven pero no se pueden comprar.
- Los donativos usan el mismo split; sin cuenta vinculada solo se aceptan con la cuenta de la plataforma si
  DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT lo permite (por defecto solo en development).
- Sin MERCADOPAGO_ACCESS_TOKEN y en development todo se simula como aprobado (como antes).
Donativos (contrato L-donativos, services/reglas.py): no suman puntos de ranking, nadie se dona a sí mismo, hay
tope por donativo y tope diario por cuenta, y al aprobarse se revisa el acumulado de 6 meses (ley antilavado).
"""
import datetime
import hashlib
import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.data.estados_mx import normalize_state
from app.dependencies import get_optional_user
from app.models import Donation, Order, OrderInvoice, OrderItem, OrderRefund, PaymentEvent, Product, Refuge, User
from app.services import legal_acceptance, mercadopago_oauth, payments, ratelimit, reglas
from app.services.audit import record_admin_action
from app.utils.notifications import create_notification

logger = logging.getLogger(__name__)

ADMIN_ROLES = ("admin", "superadmin")
PENDING_ORDER = ("pending_payment", "created")
CLOSED_ORDER = ("cancelled", "expired")  # sin inventario apartado
# Inventario apartado y todavía sin enviar
STOCK_HELD_ORDER = ("pending_payment", "created", "paid", "preparing", "amount_mismatch")
# Pagados y todavía en manos del refugio o del comprador (se avisa al refugio si se reembolsan)
PAID_ORDER = ("paid", "preparing", "shipped", "delivered", "completed", "return_requested", "return_approved",
              "return_rejected")
REOPENABLE_DONATION = ("pending", "rejected", "cancelled", "expired")
REVERSED_STATUSES = ("refunded", "charged_back")
MAX_QUANTITY_PER_PRODUCT = 100
SHOP_DISABLED_DETAIL = "La tienda no está disponible por ahora."
NOT_READY_DETAIL = mercadopago_oauth.NOT_READY_DETAIL
ANNEX_NOT_READY_DONATIONS = ("Este refugio todavía no puede recibir donativos: le falta aceptar la versión vigente de "
                             "sus condiciones de aliado. Inténtalo más tarde.")
ANNEX_NOT_READY_SALES = ("Este refugio todavía no puede vender: le falta aceptar la versión vigente de sus condiciones "
                         "de aliado. Inténtalo más tarde.")
CENT = Decimal("0.01")
IVA_RATE = Decimal("0.16")
REF_HINT_RE = re.compile(r"^(order|donation)-(\d{1,12})$")
REFUND_MAX_DAYS = 180  # Mercado Pago solo reembolsa pagos aprobados hace menos de 180 días
# Textos exactos de las casillas del checkout (app/index.html, #co-terms y #co-prepay). Su hash junto con
# LEGAL_TERMS_VERSION queda en el pedido como evidencia de lo que se aceptó (consumidor-ecommerce-05, 06 y 08).
# Si cambias el texto en index.html cámbialo aquí también.
CHECKOUT_CONSENT_TEXTS = (
    "Revisé mi pedido y acepto las condiciones de compra de la tienda solidaria.",
    "Autorizo el cobro antes de la entrega; el refugio despacha en el plazo indicado arriba.",
)


class RefundFailed(HTTPException):
    """No se pudo reembolsar en Mercado Pago. code: insufficient_funds | too_old | not_configured | no_token | error."""

    def __init__(self, status_code: int, detail: str, code: str = "error"):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def _now():
    return datetime.datetime.utcnow()


def checkout_terms_hash(version: str | None = None) -> str:
    """sha256 de la versión de las condiciones + los textos de las casillas que aceptó el comprador."""
    raw = "\n".join((version or settings.legal_terms_version, *CHECKOUT_CONSENT_TEXTS))
    return hashlib.sha256(raw.encode()).hexdigest()


def money2(value) -> Decimal:
    """Redondeo comercial a centavos (0.005 -> 0.01)."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _require_payments_or_dev():
    if not settings.payments_enabled and not settings.is_development:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Los pagos no están disponibles en este momento. Inténtalo más tarde.",
        )


def shop_guard(user: User | None = Depends(get_optional_user)) -> None:
    """Dependencia: con la tienda apagada (SHOP_ENABLED) productos y compras responden 404; los admins sí pasan."""
    if not settings.effective_shop_enabled and not (user and user.role in ADMIN_ROLES):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SHOP_DISABLED_DETAIL)


def _locked(db: Session, model, obj_id: int):
    """Relee la fila con SELECT ... FOR UPDATE: serializa webhook, IPN, tareas y admins en paralelo."""
    return db.query(model).filter(model.id == obj_id).populate_existing().with_for_update().first()


def _append_note(current: str | None, note: str) -> str:
    return f"{current}\n{note}" if current else note


def _money(value) -> str:
    return f"${Decimal(value):.2f}"


def _notify_admins(db: Session, type: str, title: str, body: str, data: dict) -> None:
    admin_ids = [
        uid for (uid,) in db.query(User.id).filter(User.role.in_(ADMIN_ROLES), User.is_active == True)  # noqa: E712
        .order_by(User.id.desc()).limit(100)
    ]
    for uid in admin_ids:
        create_notification(db, user_id=uid, type=type, title=title, body=body, data=data, commit=False)


# --------------------------------------------------------------------------- historial y avisos de pedidos
def add_timeline(order: Order, status_value: str, note: str | None = None, by: str = "system") -> None:
    """Agrega una entrada al historial del pedido (se reasigna la lista para que SQLAlchemy detecte el cambio)."""
    entry = {"status": status_value, "at": _now().replace(microsecond=0).isoformat() + "Z", "note": note, "by": by}
    order.timeline = [*(order.timeline or []), entry]


def set_order_status(order: Order, status_value: str, note: str | None = None, by: str = "system") -> None:
    order.status = status_value
    add_timeline(order, status_value, note, by)


def order_refuge(db: Session, order: Order) -> Refuge | None:
    if order.refuge_id:
        return db.query(Refuge).filter(Refuge.id == order.refuge_id).first()
    item = order.items[0] if order.items else None
    return item.product.refuge if item and item.product else None


SELLER_TABS = ("productos", "pedidos", "facturas", "fiscal", "cobros", "cuenta")


def notify_order_user(db: Session, user_id: int | None, kind: str, title: str, body: str, order: Order,
                      email: bool = True, extra: dict | None = None, seller_tab: str | None = None) -> None:
    """Aviso en la app + correo (services/notify.py). Nunca rompe el flujo que lo llama.

    seller_tab: el aviso es para el refugio que vende; el enlace abre "Mi tienda" en esa pestaña
    (/app/?shop=pedidos) en lugar del pedido como comprador (GET /orders/{id} es solo del comprador).
    """
    from app.services.notify import notify_user

    user = db.query(User).filter(User.id == user_id).first() if user_id else None
    if not user or not user.is_active:
        return
    data = {"order_id": order.id, **(extra or {})}
    url = f"/app/?order={order.id}"
    if seller_tab:
        url = f"/app/?shop={seller_tab}"
        data.update(seller_view=True, tab=seller_tab)
    notify_user(db, user, kind, title, body, url=url, email=email, data=data, commit=False)


def _notify_refuges_of_order(db: Session, order: Order, type: str, title: str, body: str,
                             tab: str = "pedidos") -> None:
    refuge = order_refuge(db, order)
    owner_ids = {refuge.user_id} if refuge else set()
    if not owner_ids:
        owner_ids = {
            uid for (uid,) in db.query(Refuge.user_id).join(Product, Product.refuge_id == Refuge.id)
            .join(OrderItem, OrderItem.product_id == Product.id).filter(OrderItem.order_id == order.id)
        }
    for uid in owner_ids:
        notify_order_user(db, uid, type, title, body, order, seller_tab=tab)


# --------------------------------------------------------------------------- inventario
def _order_quantities(order: Order) -> dict[int, int]:
    qty: dict[int, int] = {}
    for item in order.items:
        qty[item.product_id] = qty.get(item.product_id, 0) + item.quantity
    return qty


def _lock_products(db: Session, product_ids) -> dict[int, Product]:
    # Siempre en orden de id para que dos transacciones no se bloqueen mutuamente
    rows = (db.query(Product).filter(Product.id.in_(list(product_ids))).order_by(Product.id)
            .populate_existing().with_for_update().all())
    return {p.id: p for p in rows}


def _reserve_stock(db: Session, order: Order) -> bool:
    """Vuelve a apartar el inventario de un pedido. False (sin cambios) si ya no alcanza."""
    qty = _order_quantities(order)
    products = _lock_products(db, qty)
    for pid, q in qty.items():
        product = products.get(pid)
        if not product or not product.is_active or product.is_hidden or product.stock < q:
            return False
    for pid, q in qty.items():
        products[pid].stock -= q
    return True


def release_stock(db: Session, order: Order) -> None:
    qty = _order_quantities(order)
    products = _lock_products(db, qty)
    for pid, q in qty.items():
        if pid in products:
            products[pid].stock += q


_release_stock = release_stock  # nombre anterior


# --------------------------------------------------------------------------- comisión, retenciones y envío
def retention_applies(refuge: Refuge | None, fee_percent=None) -> bool:
    """Retenciones de plataformas (fiscal-tienda-09): personas físicas siempre; morales solo si se configura.

    Sin comisión (0 %, fase 1 de fiscal-tienda) no hay retenciones (terminos-vendedores 11.1), y en producción
    solo se retiene con el régimen de plataformas confirmado (PLATFORM_TAX_REGIME_READY).
    """
    pct = settings.mercadopago_marketplace_fee_percent if fee_percent is None else fee_percent
    if Decimal(str(pct or 0)) <= 0 or not settings.fees_allowed:
        return False
    profile = refuge.fiscal_profile if refuge else None
    if not profile:
        return False
    return profile.person_type == "fisica" or (profile.person_type == "moral" and settings.retencion_personas_morales)


def compute_split(total, refuge: Refuge | None, fee_percent=None) -> dict:
    """Comisión y retenciones de una venta. marketplace_fee = comisión + retenciones (lo que MP separa para la
    plataforma); net = lo que llega al refugio antes de la comisión de Mercado Pago."""
    total = money2(total)
    pct = Decimal(str(settings.mercadopago_marketplace_fee_percent if fee_percent is None else fee_percent))
    fee = money2(total * pct / 100)
    isr = iva = Decimal("0.00")
    if retention_applies(refuge, pct):
        donataria = bool(refuge.fiscal_profile.is_donataria)  # ventas de donatarias: exentas de IVA (donativos-08)
        base = total if donataria else money2(total / (1 + IVA_RATE))
        iva_cobrado = Decimal("0.00") if donataria else total - base
        isr = money2(base * Decimal(str(settings.retencion_isr_percent)) / 100)
        iva = money2(iva_cobrado * Decimal(str(settings.retencion_iva_percent)) / 100)
    return {"fee_percent": pct, "fee_amount": fee, "isr_retenido": isr, "iva_retenido": iva,
            "marketplace_fee": fee + isr + iva, "net_amount": total - fee - isr - iva}


def product_ships_to(product: Product, state: str | None) -> bool:
    if product.ships_nationwide:
        return True
    return bool(state) and state in {normalize_state(s) for s in (product.ships_states or [])}


SHIPPING_FIELDS = ("shipping_name", "shipping_phone", "shipping_street", "shipping_ext_number", "shipping_int_number",
                   "shipping_neighborhood", "shipping_city", "shipping_state", "shipping_postal_code",
                   "shipping_references")
CONSENT_FIELDS = ("terms_version", "terms_hash", "terms_accepted_at", "consent_prepayment_at", "terms_ip",
                  "terms_user_agent")


def join_address(data: dict) -> str:
    """Dirección estructurada en una línea (Order.shipping_address, la que ya usaban el refugio y el admin)."""
    street = " ".join(p for p in (data.get("shipping_street"), data.get("shipping_ext_number")) if p)
    if data.get("shipping_int_number"):
        street += f" int. {data['shipping_int_number']}"
    parts = [data.get("shipping_name"), street,
             f"col. {data['shipping_neighborhood']}" if data.get("shipping_neighborhood") else None,
             data.get("shipping_city"), data.get("shipping_state"),
             f"CP {data['shipping_postal_code']}" if data.get("shipping_postal_code") else None]
    text = ", ".join(p for p in parts if p)
    if data.get("shipping_phone"):
        text += f". Tel. {data['shipping_phone']}"
    if data.get("shipping_references"):
        text += f". Referencias: {data['shipping_references']}"
    return text[:1000]


# --------------------------------------------------------------------------- órdenes
def create_order_checkout(db: Session, user: User, items_payload, shipping, consent: dict | None = None):
    """shipping: dict con los campos shipping_* (o el texto anterior, como str). Devuelve (order, url, simulado).

    consent: evidencia de la aceptación (terms_version, terms_hash, terms_accepted_at, consent_prepayment_at,
    terms_ip, terms_user_agent) que se guarda en el pedido.
    """
    _require_payments_or_dev()
    if not items_payload:
        raise HTTPException(status_code=400, detail="Tu pedido debe tener al menos un producto.")
    quantities: dict[int, int] = {}
    for item in items_payload:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0.")
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
    if any(q > MAX_QUANTITY_PER_PRODUCT for q in quantities.values()):
        raise HTTPException(status_code=400, detail=f"Puedes pedir máximo {MAX_QUANTITY_PER_PRODUCT} piezas de cada producto.")
    address = dict(shipping) if isinstance(shipping, dict) else {"shipping_address": str(shipping or "")}
    state = normalize_state(address.get("shipping_state")) if address.get("shipping_state") else None

    # 1) Transacción corta: se bloquean los productos, se aparta el inventario y se crea el pedido
    products = _lock_products(db, quantities)
    try:
        for pid, qty in quantities.items():
            product = products.get(pid)
            if not product or product.is_hidden:
                raise HTTPException(status_code=404, detail=f"El producto {pid} no existe.")
            if not product.is_active:
                raise HTTPException(status_code=400, detail=f"{product.name} ya no está disponible.")
            if product.stock < qty:
                raise HTTPException(status_code=400, detail=f"No hay suficiente inventario de {product.name}.")
        if len({p.refuge_id for p in products.values()}) > 1:
            raise HTTPException(status_code=400, detail="Tu carrito tiene productos de varios refugios. Haz un pedido "
                                                        "por refugio: cada uno envía sus productos por separado.")
        refuge = next(iter(products.values())).refuge
        if not refuge or refuge.status != "approved" or not refuge.seller_payments_ready:
            raise HTTPException(status_code=409, detail=NOT_READY_DETAIL)
        # Para vender, la cuenta del refugio debe tener aceptados sus anexos vigentes (terminos-refugios 1.3)
        if legal_acceptance.missing_annexes(db, refuge.user, ("refugio", "vendedor")):
            raise HTTPException(status_code=409, detail=ANNEX_NOT_READY_SALES)
        for product in products.values():
            if not product_ships_to(product, state):
                if not state:
                    raise HTTPException(status_code=400, detail="Indica el estado de entrega: algunos productos no se "
                                                                "envían a todo el país.")
                raise HTTPException(status_code=400, detail=f"{product.name} no se envía a {state}.")
    except HTTPException:
        db.rollback()
        raise

    simulated = settings.payments_simulated
    account = refuge.payment_account
    subtotal = sum((Decimal(products[pid].price) * qty for pid, qty in quantities.items()), Decimal("0"))
    # El envío se cobra una sola vez por pedido: el mayor costo entre sus productos (0 = gratis)
    shipping_total = max((Decimal(products[pid].shipping_cost or 0) for pid in quantities), default=Decimal("0"))
    total = money2(subtotal + shipping_total)
    split = compute_split(total, refuge)
    if address.get("shipping_street"):
        address["shipping_state"] = state or address.get("shipping_state")
        address["shipping_address"] = join_address(address)
    order = Order(
        user_id=user.id, refuge_id=refuge.id, status="pending_payment",
        subtotal=money2(subtotal), shipping_total=money2(shipping_total), total=total,
        fee_percent=split["fee_percent"], fee_amount=split["fee_amount"], isr_retenido=split["isr_retenido"],
        iva_retenido=split["iva_retenido"], net_amount=split["net_amount"],
        payment_mode="simulated" if simulated else "split",
        collector_id=None if simulated else (account.mp_user_id if account else None),
        shipping_address=address.get("shipping_address") or "",
        **{f: (address.get(f) or None) for f in SHIPPING_FIELDS},
        **{k: v for k, v in (consent or {}).items() if k in CONSENT_FIELDS},
    )
    add_timeline(order, "pending_payment", "Pedido creado; esperando el pago.", by="buyer")
    db.add(order)
    db.flush()
    pref_items = []
    for pid, qty in quantities.items():
        product = products[pid]
        product.stock -= qty
        db.add(OrderItem(order_id=order.id, product_id=pid, quantity=qty, unit_price=product.price))
        pref_items.append({"title": product.name, "quantity": qty, "unit_price": product.price})
    if shipping_total > 0:
        pref_items.append({"title": "Envío", "quantity": 1, "unit_price": shipping_total})
    order_id = order.id
    db.commit()  # libera el bloqueo de los productos ANTES de llamar a Mercado Pago

    if simulated:
        # Desarrollo sin Mercado Pago: el pago se simula como aprobado
        mark_order_paid(db, order, payment_id=None, provider="simulated")
        db.refresh(order)
        return order, None, True

    # 2) Fuera de cualquier bloqueo: token del refugio (se renueva si está por vencer) y preferencia con
    #    marketplace_fee. El link de pago vence en CHECKOUT_EXPIRATION_MINUTES.
    try:
        token = mercadopago_oauth.seller_access_token(db, account)
        pref = payments.create_preference(
            pref_items, external_reference=f"order:{order_id}", back_query=f"order={order_id}", payer_email=user.email,
            access_token=token, marketplace_fee=split["marketplace_fee"], notification_query=f"ref=order-{order_id}",
        )
    except mercadopago_oauth.OAuthError as exc:
        # El token del refugio venció o se revocó: se bloquean sus ventas (gap-custodia-...-09)
        logger.warning("Checkout del pedido %s sin token del refugio %s: %s", order_id, refuge.id, exc)
        _release_failed_checkout(db, order_id)
        raise HTTPException(status_code=409, detail=NOT_READY_DETAIL)
    except payments.PaymentError as exc:
        _release_failed_checkout(db, order_id)
        raise HTTPException(status_code=502, detail=str(exc))
    order = db.query(Order).filter(Order.id == order_id).first()
    order.provider = "mercadopago"
    order.provider_preference_id = pref["id"]
    order.checkout_url = (pref.get("init_point") or "")[:500] or None  # "Terminar el pago" en Mis pedidos
    db.commit()
    db.refresh(order)
    return order, pref["init_point"], False


def _release_failed_checkout(db: Session, order_id: int) -> None:
    """No se pudo crear el link de pago: se cancela el pedido y se devuelve el inventario."""
    db.rollback()
    order = _locked(db, Order, order_id)
    if order and order.status in PENDING_ORDER:
        release_stock(db, order)
        set_order_status(order, "cancelled", "No se pudo crear el pago en Mercado Pago.")
        order.cancelled_at = _now()
        order.cancel_reason = "checkout_failed"
        order.review_note = _append_note(order.review_note, "No se pudo crear el pago en Mercado Pago.")
    db.commit()


def _set_order_paid(db: Session, order: Order, payment_id: str | None, provider: str) -> None:
    """Marca el pedido como pagado y agrega las notificaciones (sin commit)."""
    set_order_status(order, "paid", "Pago aprobado.", by="payment")
    order.paid_at = _now()
    order.provider = order.provider or provider
    if payment_id:
        order.provider_payment_id = str(payment_id)
    refuge = order_refuge(db, order)
    if refuge:
        order.refuge_id = order.refuge_id or refuge.id
        notify_order_user(
            db, refuge.user_id, "new_order", "Nueva venta en la tienda",
            f"Recibiste un pedido pagado por {_money(order.total)} MXN. Revisa la orden #{order.id}, prepárala y "
            "márcala como enviada con su guía de rastreo.", order, seller_tab="pedidos",
        )
    # Aviso corto en la app; el correo lleva el comprobante completo (consumidor-ecommerce-07; terminos-tienda 4 y 8.1)
    notify_order_user(
        db, order.user_id, "order_paid", "¡Pago confirmado!",
        f"Tu pedido #{order.id} fue pagado. Tu comprobante está en Mis pedidos y te lo enviamos por correo. Gracias "
        "por apoyar a los refugios 🐾", order, email=False, extra={"receipt": True},
    )
    reglas.send_receipt_email(db, order)


def mark_order_paid(db: Session, order: Order, payment_id: str | None = None, provider: str = "mercadopago") -> bool:
    """Marca pagado un pedido pendiente (pago simulado en desarrollo). Idempotente."""
    order = _locked(db, Order, order.id)
    if not order or order.status not in PENDING_ORDER:
        db.rollback()
        return False
    _set_order_paid(db, order, payment_id, provider)
    db.commit()
    return True


def expire_order(db: Session, order_id: int) -> bool:
    """Cancela un pedido cuyo pago no llegó a tiempo y devuelve su inventario."""
    order = _locked(db, Order, order_id)
    if not order or order.status not in PENDING_ORDER:
        db.rollback()
        return False
    release_stock(db, order)
    set_order_status(order, "cancelled", "No se completó el pago a tiempo.")
    order.cancelled_at = _now()
    order.cancel_reason = "payment_expired"
    notify_order_user(
        db, order.user_id, "order_expired", "Tu pedido expiró",
        f"El pedido #{order.id} se canceló porque no se completó el pago a tiempo. No se te cobró nada; puedes "
        "volver a pedir desde la tienda.", order,
    )
    db.commit()
    return True


# --------------------------------------------------------------------------- donaciones
# Los donativos NO suman puntos de ranking (donativos.html §12; contrato L-donativos)


def create_donation_checkout(db: Session, user: User, refuge_id: int, amount, share_name: bool = False) -> dict:
    _require_payments_or_dev()
    amount = Decimal(str(amount))
    if amount < 10:
        raise HTTPException(status_code=400, detail="El monto mínimo de donación es de $10 MXN.")
    refuge = db.query(Refuge).filter(Refuge.id == refuge_id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="No encontramos ese refugio.")
    if refuge.status != "approved":
        raise HTTPException(status_code=400, detail="Este refugio todavía no está verificado.")
    # Para recibir donativos, la cuenta del refugio debe tener aceptados sus anexos vigentes (terminos-refugios 1.3)
    if legal_acceptance.missing_annexes(db, refuge.user, ("refugio",)):
        raise HTTPException(status_code=409, detail=ANNEX_NOT_READY_DONATIONS)
    # Sin autodonaciones, tope por donativo y tope diario por cuenta (donativos §8; prevencion-lavado §4)
    reglas.check_donation_limits(db, user, refuge, amount)
    tax = reglas.donation_tax_notice(refuge)

    account = refuge.payment_account
    if settings.payments_simulated:
        mode = "simulated"
    elif mercadopago_oauth.account_usable(account):
        mode = "split"
    elif settings.effective_donations_fallback:
        mode = "platform"  # flujo anterior: cobra la cuenta de GuauWoow
    else:
        raise HTTPException(status_code=409, detail=NOT_READY_DETAIL)
    pct = Decimal(str(settings.mercadopago_donation_fee_percent)) if mode != "platform" else Decimal("0")
    fee = money2(amount * pct / 100)
    donation = Donation(user_id=user.id, refuge_id=refuge.id, amount=amount, status="pending", share_name=bool(share_name),
                        payment_mode=mode, collector_id=account.mp_user_id if mode == "split" else None,
                        fee_percent=pct, fee_amount=fee, net_amount=amount - fee)
    db.add(donation)
    db.commit()  # no se mantiene una transacción abierta mientras se llama a Mercado Pago
    if mode == "simulated":
        approve_donation(db, donation, payment_id=None, provider="simulated")
        db.refresh(donation)
        return {"donation_id": donation.id, "status": donation.status, "checkout_url": None, "simulated": True, **tax}

    try:
        token = mercadopago_oauth.seller_access_token(db, account) if mode == "split" else None
        extra = {"access_token": token, "marketplace_fee": fee if fee > 0 else None,
                 "notification_query": f"ref=donation-{donation.id}"} if mode == "split" else {}
        pref = payments.create_preference(
            [{"title": f"Donación a {refuge.name}", "quantity": 1, "unit_price": amount}],
            external_reference=f"donation:{donation.id}",
            back_query=f"donation={donation.id}",
            payer_email=user.email,
            **extra,
        )
    except (payments.PaymentError, mercadopago_oauth.OAuthError) as exc:
        donation = db.query(Donation).filter(Donation.id == donation.id).first()
        donation.status = "cancelled"
        donation.review_note = "No se pudo crear el pago en Mercado Pago."
        db.commit()
        if isinstance(exc, mercadopago_oauth.OAuthError):
            logger.warning("Donativo %s sin token del refugio %s: %s", donation.id, refuge.id, exc)
            raise HTTPException(status_code=409, detail=NOT_READY_DETAIL)
        raise HTTPException(status_code=502, detail=str(exc))
    donation.provider = "mercadopago"
    donation.provider_preference_id = pref["id"]
    db.commit()
    return {"donation_id": donation.id, "status": donation.status, "checkout_url": pref["init_point"], "simulated": False,
            **tax}


def _set_donation_approved(db: Session, donation: Donation, payment_id: str | None, provider: str) -> None:
    """Aprueba la donación, notifica al refugio y revisa los umbrales de la ley antilavado (sin commit).

    Los donativos no suman puntos de ranking (donativos.html §12).
    """
    donation.status = "approved"
    donation.approved_at = donation.approved_at or _now()
    donation.provider = donation.provider or provider
    if payment_id:
        donation.provider_payment_id = str(payment_id)
    refuge = db.query(Refuge).filter(Refuge.id == donation.refuge_id).first()
    donor_name = donation.donor_display_name  # "Donante anónimo" salvo que la persona aceptara compartirlo
    create_notification(
        db, user_id=refuge.user_id, type="donation_received", title="¡Recibiste una donación!",
        body=f"{donor_name} donó ${donation.amount} MXN a {refuge.name}.",
        data={"donation_id": donation.id}, commit=False,
    )
    db.flush()
    try:
        with db.begin_nested():  # una falla aquí nunca debe impedir acreditar el donativo
            reglas.check_aml_thresholds(db, donation)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo revisar el acumulado antilavado del donativo %s", donation.id)
    try:
        _notify_donor_receipt(db, donation, refuge)
    except Exception:  # noqa: BLE001 - el comprobante nunca debe impedir acreditar el donativo
        logger.exception("No se pudo avisar a la persona donante del donativo %s", donation.id)


def _notify_donor_receipt(db: Session, donation: Donation, refuge: Refuge) -> None:
    """Comprobante de operación para quien dona, en la app y por correo (comunicaciones.html §2: «recibos de pedidos
    y donativos»; terminos.html 11.1). No es un CFDI ni un recibo deducible (sin commit)."""
    from app.services.notify import notify_user

    donor = db.query(User).filter(User.id == donation.user_id).first()
    if donor is None or not donor.is_active:
        return
    when = (donation.approved_at or _now()) - datetime.timedelta(hours=6)  # hora del centro de México (sin horario de verano)
    lines = [f"Folio: D-{donation.id}", f"Refugio: {refuge.name}", f"Monto: {_money(donation.amount)} MXN",
             f"Fecha: {when.strftime('%d/%m/%Y %H:%M')} (hora del centro de México)"]
    if donation.provider_payment_id:
        lines.append(f"Operación de Mercado Pago: {donation.provider_payment_id}")
    if donation.payment_mode == "split":
        lines.append("El dinero llegó directo a la cuenta de Mercado Pago del Refugio; GuauWoow no lo recibe.")
    lines.append("Este es un comprobante de la operación: no es un CFDI ni un recibo deducible de impuestos.")
    notify_user(db, donor, "donation_receipt", "Recibimos tu donativo 💛", "\n".join(lines), email=True,
                data={"donation_id": donation.id, "receipt": True}, commit=False)


def approve_donation(db: Session, donation: Donation, payment_id: str | None = None, provider: str = "mercadopago") -> bool:
    """Aprueba una donación pendiente (pago simulado en desarrollo). Idempotente."""
    donation = _locked(db, Donation, donation.id)
    if not donation or donation.status != "pending":
        db.rollback()
        return False
    _set_donation_approved(db, donation, payment_id, provider)
    db.commit()
    return True


def expire_donation(db: Session, donation_id: int) -> bool:
    donation = _locked(db, Donation, donation_id)
    if not donation or donation.status != "pending":
        db.rollback()
        return False
    donation.status = "expired"  # si después llega un pago aprobado, se acredita igual
    db.commit()
    return True


# --------------------------------------------------------------------------- tokens por pedido/donación
def provider_token_for(db: Session, obj) -> str | None:
    """Token con el que se opera el pago de un pedido o donación: el del refugio en split, None = plataforma.

    Lanza mercadopago_oauth.OAuthError si es split y la cuenta del refugio ya no se puede usar.
    """
    if getattr(obj, "payment_mode", None) != "split":
        return None
    refuge_id = obj.refuge_id
    if refuge_id is None and isinstance(obj, Order):
        refuge = order_refuge(db, obj)
        refuge_id = refuge.id if refuge else None
    refuge = db.query(Refuge).filter(Refuge.id == refuge_id).first() if refuge_id else None
    if not refuge or not refuge.payment_account:
        raise mercadopago_oauth.OAuthError("El refugio ya no tiene su cuenta de Mercado Pago vinculada.")
    return mercadopago_oauth.seller_access_token(db, refuge.payment_account)


def _token_kwargs(token: str | None) -> dict:
    return {"access_token": token} if token else {}


def _seller_token_from_hint(db: Session, ref_hint: str | None, mp_user_id) -> str | None:
    """Token del vendedor para consultar un pago que la plataforma no ve (split). Pistas: ?ref= y user_id."""
    try:
        match = REF_HINT_RE.match(ref_hint or "")
        if match:
            model = Order if match.group(1) == "order" else Donation
            obj = db.query(model).filter(model.id == int(match.group(2))).first()
            token = provider_token_for(db, obj) if obj else None
            if token:
                return token
        account = mercadopago_oauth.account_for_mp_user(db, mp_user_id)
        if account and mercadopago_oauth.account_usable(account):
            return mercadopago_oauth.seller_access_token(db, account)
    except mercadopago_oauth.OAuthError:
        logger.warning("No hay token del vendedor para consultar el pago (pista %s)", (ref_hint or "")[:40])
    return None


# --------------------------------------------------------------------------- webhook
def _payment_amount(payment: dict) -> tuple[Decimal | None, str | None]:
    try:
        amount = Decimal(str(payment.get("transaction_amount"))).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    currency = str(payment.get("currency_id") or "").upper() or None
    return amount, currency


def _amount_ok(amount: Decimal | None, currency: str | None, expected) -> bool:
    return (amount is not None and currency == settings.currency.upper()
            and amount == Decimal(str(expected)).quantize(CENT))


def _mismatch_note(amount, currency, expected) -> str:
    charged = f"{_money(amount)} {currency or '?'}" if amount is not None else f"un monto inválido ({currency or '?'})"
    return f"Mercado Pago cobró {charged}; se esperaban {_money(expected)} {settings.currency}."


def _order_approved(db: Session, order: Order, payment_id: str, amount, currency) -> str:
    if order.status in PENDING_ORDER:
        pass  # el inventario sigue apartado
    elif order.status in CLOSED_ORDER and not order.refunded_at:
        # Pago aprobado después de que el pedido venció o se canceló: no se pierde el dinero
        previous = order.status
        if not _reserve_stock(db, order):
            set_order_status(order, "refund_pending", "El pago llegó tarde y ya no hay inventario.", by="payment")
            order.provider_payment_id = payment_id
            order.paid_amount = amount
            order.review_note = _append_note(
                order.review_note, f"Llegó el pago aprobado {payment_id} cuando el pedido ya estaba {previous} y ya no "
                                   "hay inventario. Hay que reembolsarlo.")
            logger.warning("Pago %s aprobado para el pedido %s ya %s sin inventario: reembolso pendiente",
                           payment_id, order.id, previous)
            _notify_admins(db, "payment_refund_pending", "Reembolso pendiente",
                           f"El pedido #{order.id} recibió el pago {payment_id} después de {previous} y ya no hay "
                           "inventario. Reembólsalo desde el panel.", {"order_id": order.id, "payment_id": payment_id})
            notify_order_user(
                db, order.user_id, "order_refund_pending", "Recibimos tu pago",
                f"Tu pago del pedido #{order.id} llegó cuando el pedido ya había expirado y el producto se agotó. "
                "Te devolveremos tu dinero en los próximos días.", order,
            )
            return "refund_pending"
    else:
        if order.provider_payment_id == payment_id:
            return "already_applied"
        logger.warning("Pago duplicado %s para el pedido %s (%s)", payment_id, order.id, order.status)
        _notify_admins(db, "payment_duplicate", "Pago duplicado",
                       f"El pedido #{order.id} ya estaba {order.status} y llegó otro pago aprobado ({payment_id}). "
                       "Reembolsa ese pago en Mercado Pago.", {"order_id": order.id, "payment_id": payment_id})
        return "duplicate"

    order.paid_amount = amount
    if not _amount_ok(amount, currency, order.total):
        set_order_status(order, "amount_mismatch", "El monto cobrado no coincide; lo revisa el equipo.", by="payment")
        order.provider_payment_id = payment_id  # el inventario queda apartado hasta que un admin decida
        note = _mismatch_note(amount, currency, order.total)
        order.review_note = _append_note(order.review_note, note)
        logger.warning("Monto distinto en el pago %s del pedido %s: %s", payment_id, order.id, note)
        _notify_admins(db, "payment_amount_mismatch", "Pago con monto distinto",
                       f"Pedido #{order.id}: {note} Revísalo en el panel.", {"order_id": order.id, "payment_id": payment_id})
        notify_order_user(
            db, order.user_id, "order_payment_review", "Estamos revisando tu pago",
            f"Recibimos tu pago del pedido #{order.id}, pero el monto no coincide con el del pedido. Nuestro equipo "
            "lo revisa y te avisamos en cuanto lo resolvamos; no tienes que hacer nada más.", order,
        )
        return "amount_mismatch"
    _set_order_paid(db, order, payment_id, "mercadopago")
    return "paid"


def _order_reversed(db: Session, order: Order, payment_id: str, mp_status: str) -> str:
    if order.provider_payment_id != payment_id or order.status == "refunded" or order.refunded_at:
        return "ignored"  # incluye el aviso de un reembolso que hicimos nosotros
    previous = order.status
    if previous in STOCK_HELD_ORDER:
        release_stock(db, order)
    label = "contracargo" if mp_status == "charged_back" else "reembolso"
    set_order_status(order, "refunded", f"Mercado Pago reporta {label} del pago.", by="payment")
    # "refunded"/"charged_back" en Mercado Pago = el pago completo se revirtió: se registra lo que faltaba
    remaining = refundable_remaining(order)
    if remaining > 0:
        record_refund(db, order, remaining, {"status": mp_status}, by="mercadopago",
                      note=f"Mercado Pago reporta {label} del pago.", final=True)
    order.refunded_at = _now()
    order.refund_status = mp_status
    order.refund_amount = money2(order.paid_amount or order.total)
    order.review_note = _append_note(order.review_note, f"Mercado Pago reporta {label} del pago {payment_id}.")
    notify_order_user(db, order.user_id, "order_refunded", "Reembolso de tu pedido",
                      f"El pago de tu pedido #{order.id} fue reembolsado.", order)
    if previous in PAID_ORDER:
        _notify_refuges_of_order(db, order, "order_refunded", "Pedido reembolsado",
                                 f"El pedido #{order.id} fue reembolsado." +
                                 (" No lo envíes." if previous in ("paid", "preparing") else ""))
    notify_invoice_cancellation(db, order)
    if mp_status == "charged_back" or previous in ("shipped", "delivered", "completed"):
        _notify_admins(db, "payment_reversed", f"Pago con {label}",
                       f"El pago {payment_id} del pedido #{order.id} ({previous}) tuvo {label}.",
                       {"order_id": order.id, "payment_id": payment_id})
    return "refunded"


def _donation_approved(db: Session, donation: Donation, payment_id: str, amount, currency) -> str:
    if donation.status not in REOPENABLE_DONATION:
        if donation.provider_payment_id == payment_id:
            return "already_applied"
        logger.warning("Pago duplicado %s para la donación %s (%s)", payment_id, donation.id, donation.status)
        _notify_admins(db, "payment_duplicate", "Pago duplicado",
                       f"La donación #{donation.id} ya estaba {donation.status} y llegó otro pago aprobado "
                       f"({payment_id}). Reembolsa ese pago en Mercado Pago.",
                       {"donation_id": donation.id, "payment_id": payment_id})
        return "duplicate"
    donation.paid_amount = amount
    if not _amount_ok(amount, currency, donation.amount):
        donation.status = "amount_mismatch"
        donation.provider_payment_id = payment_id
        note = _mismatch_note(amount, currency, donation.amount)
        donation.review_note = _append_note(donation.review_note, note)
        logger.warning("Monto distinto en el pago %s de la donación %s: %s", payment_id, donation.id, note)
        _notify_admins(db, "payment_amount_mismatch", "Pago con monto distinto",
                       f"Donación #{donation.id}: {note} Revísala en el panel.",
                       {"donation_id": donation.id, "payment_id": payment_id})
        return "amount_mismatch"
    _set_donation_approved(db, donation, payment_id, "mercadopago")
    return "approved"


def _donation_reversed(db: Session, donation: Donation, payment_id: str, mp_status: str) -> str:
    if donation.provider_payment_id != payment_id or donation.status == "refunded":
        return "ignored"
    label = "contracargo" if mp_status == "charged_back" else "reembolso"
    donation.status = "refunded"
    donation.review_note = _append_note(donation.review_note, f"Mercado Pago reporta {label} del pago {payment_id}.")
    if mp_status == "charged_back":
        _notify_admins(db, "payment_reversed", "Pago con contracargo",
                       f"El pago {payment_id} de la donación #{donation.id} tuvo contracargo.",
                       {"donation_id": donation.id, "payment_id": payment_id})
    return "refunded"


def apply_payment(db: Session, payment: dict, payment_id: str | None = None) -> str:
    """Aplica un pago ya consultado en Mercado Pago a su pedido o donación. Idempotente por id de pago."""
    payment_id = str(payment.get("id") or payment_id or "")
    ref = str(payment.get("external_reference") or "")
    mp_status = str(payment.get("status") or "")
    kind, _, raw_id = ref.partition(":")
    if not payment_id or kind not in ("order", "donation") or not raw_id.isdigit():
        return "unknown_reference"
    model = Order if kind == "order" else Donation
    if mp_status != "approved" and mp_status not in REVERSED_STATUSES:
        # pending, in_process, rejected, cancelled...: el comprador puede reintentar con el mismo link,
        # así que el pedido sigue apartado hasta que expire
        obj = db.query(model).filter(model.id == int(raw_id)).first()
        return f"{kind}:{obj.status}" if obj else f"{kind}_not_found"

    obj = _locked(db, model, int(raw_id))
    if not obj:
        db.rollback()
        return f"{kind}_not_found"
    collector = payment.get("collector_id") or (payment.get("collector") or {}).get("id")
    if obj.collector_id and collector and str(collector) != str(obj.collector_id):
        # Un pago con nuestra referencia pero cobrado por otra cuenta: no se aplica
        logger.warning("Pago %s de %s %s cobrado por otra cuenta (%s)", payment_id, kind, obj.id, collector)
        db.rollback()
        return f"{kind}_collector_mismatch"
    already = db.query(PaymentEvent.id).filter(
        PaymentEvent.provider == "mercadopago", PaymentEvent.payment_id == payment_id, PaymentEvent.status == mp_status,
    ).first()
    if already:
        result = f"{kind}:{obj.status}"
        db.rollback()  # ya aplicado (webhook + IPN o reintento): libera el bloqueo sin cambios
        return result

    amount, currency = _payment_amount(payment)
    if kind == "order":
        if mp_status == "approved":
            outcome = _order_approved(db, obj, payment_id, amount, currency)
        else:
            outcome = _order_reversed(db, obj, payment_id, mp_status)
    elif mp_status == "approved":
        outcome = _donation_approved(db, obj, payment_id, amount, currency)
    else:
        outcome = _donation_reversed(db, obj, payment_id, mp_status)
    db.add(PaymentEvent(provider="mercadopago", payment_id=payment_id, status=mp_status, kind=kind,
                        object_id=obj.id, outcome=outcome, amount=amount, currency=currency))
    result = f"{kind}:{obj.status}"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # otro proceso registró el mismo pago al mismo tiempo; el suyo es el que cuenta
        return f"{kind}:already_applied"
    return result


def process_payment(db: Session, payment_id: str, ref_hint: str | None = None, mp_user_id=None) -> str:
    """Consulta el pago en Mercado Pago y actualiza la orden/donación. Devuelve el resultado.

    Primero con el token de la plataforma; si Mercado Pago no lo deja ver (en split el pago vive en la cuenta
    del refugio), con el token del refugio que indica la pista ?ref=order-12 de notification_url o el
    user_id (vendedor) del cuerpo del aviso. Lanza payments.PaymentError si Mercado Pago no responde
    (la tarea de Celery reintenta).
    """
    if not settings.payments_enabled:
        return "payments_disabled"
    payment = payments.get_payment(payment_id)
    if not payment and (ref_hint or mp_user_id):
        token = _seller_token_from_hint(db, ref_hint, mp_user_id)
        if token:
            payment = payments.get_payment(payment_id, access_token=token)
    if not payment:
        return "payment_not_found"
    return apply_payment(db, payment, payment_id)


# --------------------------------------------------------------------------- expiración (Celery beat)
def _reconcile(db: Session, kind: str, obj_id: int) -> bool:
    """Antes de expirar, busca en Mercado Pago un pago aprobado cuya notificación se haya perdido."""
    model = Order if kind == "order" else Donation
    obj = db.query(model).filter(model.id == obj_id).first()
    try:
        token = provider_token_for(db, obj) if obj else None
    except mercadopago_oauth.OAuthError:
        return False
    found = payments.search_payments(f"{kind}:{obj_id}", **_token_kwargs(token))
    for payment in found or []:
        if payment.get("status") == "approved" and str(payment.get("external_reference")) == f"{kind}:{obj_id}":
            apply_payment(db, payment)
            return True
    return False


def refresh_from_provider(db: Session, kind: str, obj) -> None:
    """Al volver del checkout, consulta Mercado Pago (máx. 1 vez cada 5 s por pago) por si el webhook no ha llegado."""
    pending = obj.status in PENDING_ORDER if kind == "order" else obj.status == "pending"
    if not (pending and settings.payments_enabled and obj.provider == "mercadopago"):
        return
    if not ratelimit.hit(f"mp-status:{kind}:{obj.id}", 1, 5):
        return
    try:
        _reconcile(db, kind, obj.id)
    except Exception:  # noqa: BLE001 - la consulta de estado nunca debe fallar por esto
        db.rollback()
        logger.exception("No se pudo conciliar %s %s con Mercado Pago", kind, obj.id)


def expire_pending_payments(db: Session, now: datetime.datetime | None = None, limit: int = 200) -> dict:
    """Cancela pedidos y expira donaciones pendientes más viejos que CHECKOUT_EXPIRATION_MINUTES."""
    cutoff = (now or _now()) - datetime.timedelta(minutes=settings.checkout_expiration_minutes)
    result = {"orders_expired": 0, "donations_expired": 0, "reconciled": 0}
    orders = (db.query(Order.id, Order.provider).filter(Order.status.in_(PENDING_ORDER), Order.created_at < cutoff)
              .order_by(Order.id).limit(limit).all())
    donations = (db.query(Donation.id, Donation.provider).filter(Donation.status == "pending", Donation.created_at < cutoff)
                 .order_by(Donation.id).limit(limit).all())
    db.rollback()
    for kind, rows, expire in (("order", orders, expire_order), ("donation", donations, expire_donation)):
        for obj_id, provider in rows:
            try:
                if settings.payments_enabled and provider == "mercadopago" and _reconcile(db, kind, obj_id):
                    result["reconciled"] += 1
                elif expire(db, obj_id):
                    result[f"{kind}s_expired"] += 1
            except Exception:  # noqa: BLE001 - un registro con problemas no detiene a los demás
                db.rollback()
                logger.exception("No se pudo expirar %s %s", kind, obj_id)
    if any(result.values()):
        logger.info("Pagos pendientes expirados: %s", result)
    return result


# --------------------------------------------------------------------------- reembolsos
def refund_at_provider(db: Session, obj, amount=None) -> dict:
    """Reembolsa en Mercado Pago (total si amount es None). Sin bloqueos abiertos: se llama a la API.

    Split: con el token del refugio (el pago está en su cuenta); cuenta de plataforma: con el token de la
    plataforma; pagos simulados: no hay nada que devolver. Devuelve {id, status, amount}.
    """
    payment_id = obj.provider_payment_id
    if obj.provider != "mercadopago" or not payment_id:
        return {"id": None, "status": "simulated", "amount": amount}
    if not settings.payments_enabled:
        raise RefundFailed(503, "Mercado Pago no está configurado; no se puede reembolsar.", "not_configured")
    approved_at = getattr(obj, "paid_at", None) or getattr(obj, "approved_at", None)
    if approved_at and approved_at < _now() - datetime.timedelta(days=REFUND_MAX_DAYS):
        raise RefundFailed(409, f"Mercado Pago solo reembolsa pagos de los últimos {REFUND_MAX_DAYS} días. Este "
                                "reembolso debe hacerse por otro medio; escríbenos desde Ayuda.", "too_old")
    try:
        token = provider_token_for(db, obj)
    except mercadopago_oauth.OAuthError as exc:
        raise RefundFailed(409, f"{exc} El reembolso debe hacerse desde la cuenta del refugio.", "no_token")
    kwargs = _token_kwargs(token)
    if amount is not None:
        kwargs["amount"] = amount
    try:
        refund = payments.refund_payment(payment_id, **kwargs) or {}
    except payments.PaymentError as exc:
        if exc.code == "insufficient_balance":
            raise RefundFailed(409, str(exc), "insufficient_funds")
        raise RefundFailed(502, str(exc), "error")
    return {"id": str(refund.get("id")) if refund.get("id") else None, "status": refund.get("status") or "approved",
            "amount": refund.get("amount", amount)}


_refund_at_provider = refund_at_provider  # nombre anterior


def refundable_remaining(order: Order) -> Decimal:
    """Lo que falta por reembolsar de un pedido (cobrado menos reembolsos parciales ya hechos)."""
    total = money2(order.paid_amount or order.total)
    if order.refunded_at and order.status in ("refunded", "cancelled"):
        return Decimal("0.00")
    return max(Decimal("0.00"), total - money2(order.refund_amount or 0))


def record_refund(db: Session, order: Order, amount, refund: dict | None, by: str, note: str | None = None,
                  final: bool = False) -> OrderRefund:
    """Registra un reembolso (total o parcial) en order_refunds y acumula Order.refund_amount (sin commit).

    Mercado Pago lo reparte en proporción entre el refugio y la plataforma (payments.refund_payment), así que
    regresa la misma proporción de la comisión y de las retenciones; el último reembolso absorbe el redondeo.
    """
    amount = money2(amount)
    total = money2(order.total)
    fee, isr, iva = (money2(order.fee_amount or 0), money2(order.isr_retenido or 0), money2(order.iva_retenido or 0))
    if final:
        prev = db.query(func.coalesce(func.sum(OrderRefund.fee_reversed), 0),
                        func.coalesce(func.sum(OrderRefund.isr_reversed), 0),
                        func.coalesce(func.sum(OrderRefund.iva_reversed), 0)).filter(OrderRefund.order_id == order.id).one()
        fee_rev, isr_rev, iva_rev = (max(Decimal("0.00"), v - money2(p)) for v, p in zip((fee, isr, iva), prev))
    else:
        ratio = (amount / total) if total > 0 else Decimal("0")
        fee_rev, isr_rev, iva_rev = (money2(v * ratio) for v in (fee, isr, iva))
    refund = refund or {}
    row = OrderRefund(order_id=order.id, refuge_id=order.refuge_id, amount=amount, fee_reversed=fee_rev,
                      isr_reversed=isr_rev, iva_reversed=iva_rev, is_full=final,
                      provider_refund_id=refund.get("id"), status=refund.get("status") or "approved", by=by, note=note)
    db.add(row)
    order.refund_amount = money2(order.refund_amount or 0) + amount
    order.refund_status = refund.get("status") or "approved"
    order.refund_id = refund.get("id") or order.refund_id
    return row


def notify_invoice_cancellation(db: Session, order: Order, partial_amount=None) -> None:
    """Si el pedido ya tenía factura emitida, el refugio debe cancelarla (o emitir un CFDI de egreso si el
    reembolso fue parcial) — fiscal-tienda-18. Se avisa al refugio y queda la nota en la factura (sin commit)."""
    invoice = db.query(OrderInvoice).filter(OrderInvoice.order_id == order.id).first()
    if not invoice or invoice.status != "issued":
        return
    folio = f" (folio fiscal {invoice.uuid})" if invoice.uuid else ""
    if partial_amount is not None:
        body = (f"Se reembolsaron {_money(partial_amount)} MXN del pedido #{order.id}, que ya tenía factura{folio}. "
                "Emite un CFDI de egreso (nota de crédito) relacionado con esa factura por el monto reembolsado.")
        note = f"Reembolso parcial de {_money(partial_amount)} MXN: el refugio emitirá un CFDI de egreso."
    else:
        body = (f"El pedido #{order.id} se canceló o reembolsó y ya tenía factura{folio}. Cancela ese CFDI en el "
                "portal del SAT o en tu sistema de facturación (o emite el CFDI de egreso que corresponda).")
        note = "Pedido cancelado o reembolsado: el refugio debe cancelar este CFDI."
    invoice.note = _append_note(invoice.note, note)[:2000]
    _notify_refuges_of_order(db, order, "invoice_cancel_needed", "Cancela la factura del pedido", body, tab="facturas")


# --------------------------------------------------------------------------- revisión de admins
def resolve_order(db: Session, order_id: int, admin: User, action: str, notes: str | None,
                  request: Request | None = None) -> Order:
    """mark_paid: acepta el pago (monto distinto o reembolso pendiente con inventario). refund: reembolsa."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    previous = order.status
    refund = None
    remaining = refundable_remaining(order)
    if action == "refund":
        if previous not in ("amount_mismatch", "refund_pending", "paid", "preparing") or remaining <= 0:
            raise HTTPException(status_code=409, detail="Este pedido no se puede reembolsar.")
        # sin bloqueo mientras se llama a Mercado Pago; si ya hubo reembolsos parciales, solo lo que falta
        partial = remaining < money2(order.paid_amount or order.total)
        refund = refund_at_provider(db, order, remaining if partial else None)
        db.rollback()
    order = _locked(db, Order, order_id)
    previous = order.status
    if action == "mark_paid":
        if previous == "refund_pending":
            if not _reserve_stock(db, order):
                db.rollback()
                raise HTTPException(status_code=409, detail="Ya no hay inventario para este pedido; reembólsalo.")
        elif previous != "amount_mismatch":
            db.rollback()
            raise HTTPException(status_code=409, detail="Este pedido no está en revisión.")
        _set_order_paid(db, order, None, "mercadopago")
    elif previous != "refunded":  # el webhook del reembolso pudo llegar antes
        if previous in STOCK_HELD_ORDER:
            release_stock(db, order)
        record_refund(db, order, remaining, refund, by="admin", note="Reembolso hecho por el equipo de GuauWoow.",
                      final=True)
        order.refunded_at = _now()
        set_order_status(order, "refunded", "Reembolso hecho por el equipo de GuauWoow.", by="admin")
        notify_order_user(db, order.user_id, "order_refunded", "Reembolso de tu pedido",
                          f"Te reembolsamos el pago del pedido #{order.id}.", order)
        if previous in ("paid", "preparing"):
            _notify_refuges_of_order(db, order, "order_refunded", "Pedido reembolsado",
                                     f"El pedido #{order.id} fue reembolsado. No lo envíes.")
        notify_invoice_cancellation(db, order)
    order.review_note = _append_note(order.review_note, f"Admin: {action}" + (f" — {notes}" if notes else ""))
    record_admin_action(db, admin, f"order_{action}", "order", order.id,
                        details={"from": previous, "to": order.status, "notes": notes}, request=request)
    db.commit()
    db.refresh(order)
    return order


def resolve_donation(db: Session, donation_id: int, admin: User, action: str, notes: str | None,
                     request: Request | None = None) -> Donation:
    donation = db.query(Donation).filter(Donation.id == donation_id).first()
    if not donation:
        raise HTTPException(status_code=404, detail="No encontramos esa donación.")
    if action == "refund":
        if donation.status not in ("amount_mismatch", "approved"):
            raise HTTPException(status_code=409, detail="Esta donación no se puede reembolsar.")
        refund_at_provider(db, donation)
        db.rollback()
    donation = _locked(db, Donation, donation_id)
    previous = donation.status
    if action == "mark_paid":
        if previous != "amount_mismatch":
            db.rollback()
            raise HTTPException(status_code=409, detail="Esta donación no está en revisión.")
        if donation.paid_amount:
            donation.amount = donation.paid_amount  # se acredita lo que realmente se cobró
            donation.fee_amount = money2(Decimal(donation.amount) * Decimal(donation.fee_percent or 0) / 100)
            donation.net_amount = Decimal(donation.amount) - donation.fee_amount
        _set_donation_approved(db, donation, None, "mercadopago")
    elif previous != "refunded":
        donation.status = "refunded"
    donation.review_note = _append_note(donation.review_note, f"Admin: {action}" + (f" — {notes}" if notes else ""))
    record_admin_action(db, admin, f"donation_{action}", "donation", donation.id,
                        details={"from": previous, "to": donation.status, "notes": notes}, request=request)
    db.commit()
    db.refresh(donation)
    return donation
