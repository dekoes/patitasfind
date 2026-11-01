import datetime
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import client_ip, get_current_user, get_verified_user, require_admin
from app.models import Order, OrderInvoice, OrderItem, Product, Refuge, User
from app.schemas import (
    AdminOrderOut, AdminRefundRequest, InvoiceIssueIn, InvoiceOut, InvoiceRequestIn, OrderCancelRequest,
    OrderCheckoutOut, OrderCreate, OrderOut, OrderReturnRequest, PaymentResolveRequest, RefugeOrderOut,
    RefugeOrderUpdate, ReturnDecisionRequest,
)
from app.services import invoicing, legal_acceptance, order_flow, ratelimit
from app.services.payment_flow import (
    ADMIN_ROLES, PAID_ORDER, checkout_terms_hash, create_order_checkout, notify_order_user, resolve_order, shop_guard,
)

router = APIRouter(tags=["orders"])
logger = logging.getLogger(__name__)

# Estados que ve el refugio: nunca pedidos sin pagar (no se deben enviar)
REFUGE_ORDER_STATUSES = ("paid", "preparing", "shipped", "delivered", "completed", "return_requested",
                         "return_approved", "return_rejected", "refunded", "cancelled")
REFUGE_STATUS_PATTERN = "^(" + "|".join(REFUGE_ORDER_STATUSES) + ")$"
# Datos de entrega visibles para el refugio hasta 2 meses después de cerrar el pedido (consumidor-ecommerce-20)
SHIPPING_PRIVACY_DAYS = 60
CLOSED_STATUSES = ("completed", "refunded", "cancelled", "return_rejected")
MAX_XML_UPLOADS_PER_HOUR = 30
INVOICE_ALLOWED = PAID_ORDER  # solo pedidos pagados (o más avanzados) se facturan


def _now():
    return datetime.datetime.utcnow()


def _order_query(db: Session):
    return db.query(Order).options(
        selectinload(Order.items).selectinload(OrderItem.product).joinedload(Product.refuge),
        joinedload(Order.refuge), selectinload(Order.invoice),
    )


def order_out(order: Order, schema=OrderOut, **extra) -> dict:
    """Pedido para el comprador con los datos calculados (acciones disponibles y plazos)."""
    data = schema.model_validate(order).model_dump()
    deadlines = order_flow.return_deadlines(order)
    now = _now()
    last = max((d for d in deadlines.values() if d), default=None)
    # El link de pago de Mercado Pago solo sirve mientras el pedido espera el pago y no ha vencido
    pay_until = order.created_at + datetime.timedelta(minutes=settings.checkout_expiration_minutes)
    data.update({
        "checkout_url": order.checkout_url if order.status == "pending_payment" and now < pay_until else None,
        "dispatch_due_at": order_flow.dispatch_deadline(order) if order.status in order_flow.PAID_CANCELLABLE else None,
        "refuge_name": order.refuge.name if order.refuge else None,
        "status_label": order_flow.STATUS_LABELS.get(order.status, order.status),
        "can_cancel": order.status in order_flow.BUYER_CANCELLABLE,
        "can_confirm_delivery": order.status == "shipped",
        "can_return": order.status in order_flow.RETURNABLE and last is not None and now <= last,
        "revocation_until": deadlines.get("revocation_until"),
        "claim_until": deadlines.get("claim_until"),
        "invoice_status": order.invoice.status if order.invoice else None,
        **extra,
    })
    return data


def _get_buyer_order(db: Session, order_id: int, user: User) -> Order:
    order = _order_query(db).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    if order.user_id != user.id and user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="No tienes acceso a este pedido.")
    return order


# --------------------------------------------------------------------------- comprador
@router.post("/orders", response_model=OrderCheckoutOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(shop_guard)])
def create_order(payload: OrderCreate, request: Request, current_user: User = Depends(get_verified_user),
                 db: Session = Depends(get_db)):
    # Casillas no premarcadas: condiciones de compra y cobro antes de la entrega (consumidor-ecommerce-05 y 06)
    if not (payload.accepted_terms and payload.consent_prepayment):
        raise HTTPException(status_code=400, detail="Para pagar acepta las condiciones de compra y autoriza el cobro "
                                                    "antes de la entrega.")
    if payload.terms_version and payload.terms_version != settings.legal_terms_version:
        raise HTTPException(status_code=409, detail="Actualizamos las condiciones de compra. Recarga la página para "
                                                    "revisarlas y aceptarlas de nuevo.")
    accepted_at = _now()
    consent = {
        "terms_version": settings.legal_terms_version, "terms_hash": checkout_terms_hash(),
        "terms_accepted_at": accepted_at, "consent_prepayment_at": accepted_at,
        "terms_ip": client_ip(request)[:45] or None,
        "terms_user_agent": (request.headers.get("user-agent") or "")[:255] or None,
    }
    structured = payload.structured_shipping()
    if structured:
        required = {"shipping_name": "nombre de quien recibe", "shipping_phone": "teléfono",
                    "shipping_street": "calle", "shipping_ext_number": "número exterior",
                    "shipping_neighborhood": "colonia", "shipping_city": "ciudad o municipio",
                    "shipping_state": "estado", "shipping_postal_code": "código postal"}
        missing = [label for key, label in required.items() if not structured.get(key)]
        if missing:
            raise HTTPException(status_code=400, detail="Completa la dirección de envío: " + ", ".join(missing) + ".")
        digits = "".join(c for c in structured["shipping_phone"] if c.isdigit())
        if len(digits) < 10:
            raise HTTPException(status_code=400, detail="Escribe un teléfono de 10 dígitos para la entrega.")
        if not (structured["shipping_postal_code"].isdigit() and len(structured["shipping_postal_code"]) == 5):
            raise HTTPException(status_code=400, detail="El código postal debe tener 5 dígitos.")
        from app.data.estados_mx import normalize_state

        if not normalize_state(structured["shipping_state"]):
            raise HTTPException(status_code=400, detail="Elige un estado de la República válido.")
        shipping = structured
    else:
        if not payload.shipping_address or not payload.shipping_address.strip():
            raise HTTPException(status_code=400, detail="Escribe la dirección de envío.")
        shipping = payload.shipping_address.strip()
    order, checkout_url, simulated = create_order_checkout(db, current_user, payload.items, shipping, consent=consent)
    # Bitácora de aceptaciones (K-ACEPT): versión y SHA-256 de los Términos de la tienda ligados al pedido. Va en su
    # propia transacción corta, después de crear el pedido (no se retiene el candado de la cadena mientras se paga)
    try:
        legal_acceptance.record_acceptance(db, current_user, legal_acceptance.SHOP_SLUG, "checkout", request,
                                           context={"order_id": order.id}, commit=True)
    except Exception:  # noqa: BLE001 - el pedido ya existe; la constancia de la casilla también queda en el pedido
        db.rollback()
        logger.exception("No se pudo registrar la aceptación de los Términos de la tienda del pedido %s", order.id)
    order = _order_query(db).filter(Order.id == order.id).first()
    return order_out(order, OrderCheckoutOut, checkout_url=checkout_url, simulated=simulated)


# El historial y el seguimiento siguen disponibles aunque la tienda se apague (pedidos ya pagados)
@router.get("/orders", response_model=list[OrderOut])
def list_my_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    orders = (_order_query(db).filter(Order.user_id == current_user.id)
              .order_by(Order.created_at.desc(), Order.id.desc()).offset(skip).limit(limit).all())
    return [order_out(o) for o in orders]


@router.get("/orders/{id}", response_model=OrderOut)
def get_order(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Detalle con historial (timeline [{status, at, note, by}]) y acciones disponibles."""
    return order_out(_get_buyer_order(db, id, current_user))


@router.post("/orders/{id}/cancel", response_model=OrderOut)
def cancel_order(id: int, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    """Antes del envío. Si ya se pagó, se reembolsa completo al medio de pago original."""
    order_flow.buyer_cancel(db, id, current_user)
    return order_out(_get_buyer_order(db, id, current_user))


@router.post("/orders/{id}/confirm-delivery", response_model=OrderOut)
def confirm_delivery(id: int, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    order_flow.confirm_delivery(db, id, current_user)
    return order_out(_get_buyer_order(db, id, current_user))


@router.post("/orders/{id}/return", response_model=OrderOut)
def request_return(id: int, payload: OrderReturnRequest, current_user: User = Depends(get_verified_user),
                   db: Session = Depends(get_db)):
    """Devolución: arrepentimiento u otro motivo en 5 días hábiles; defecto, no corresponde o no llegó en 60 días."""
    order_flow.request_return(db, id, current_user, payload.reason, payload.details, payload.photos)
    return order_out(_get_buyer_order(db, id, current_user))


# --------------------------------------------------------------------------- factura del comprador
def _invoice_out(invoice: OrderInvoice) -> dict:
    base = f"/orders/{invoice.order_id}/invoice"
    return {
        "order_id": invoice.order_id, "status": invoice.status, "rfc": invoice.rfc, "legal_name": invoice.legal_name,
        "regimen_fiscal": invoice.regimen_fiscal, "postal_code": invoice.postal_code, "uso_cfdi": invoice.uso_cfdi,
        "email": invoice.email, "uuid": invoice.uuid, "note": invoice.note, "requested_at": invoice.requested_at,
        "issued_at": invoice.issued_at,
        "xml_url": f"{base}/xml" if invoice.status == "issued" and invoice.xml_document_id else None,
        "pdf_url": f"{base}/pdf" if invoice.status == "issued" and invoice.pdf_document_id else None,
    }


@router.post("/orders/{id}/invoice-request", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def request_invoice(id: int, payload: InvoiceRequestIn, current_user: User = Depends(get_verified_user),
                    db: Session = Depends(get_db)):
    """Pide factura del pedido. Modelo B: la emite el refugio vendedor y la sube (XML y PDF)."""
    order = db.query(Order).filter(Order.id == id).populate_existing().with_for_update().first()
    if not order or order.user_id != current_user.id:
        db.rollback()
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    if order.status not in INVOICE_ALLOWED:
        db.rollback()
        raise HTTPException(status_code=409, detail="Solo puedes pedir factura de un pedido pagado.")
    invoice = db.query(OrderInvoice).filter(OrderInvoice.order_id == id).first()
    if invoice and invoice.status in ("requested", "issued"):
        db.rollback()
        detail = "Ya se emitió la factura de este pedido." if invoice.status == "issued" else "Ya pediste factura de este pedido."
        raise HTTPException(status_code=409, detail=detail)
    if not invoice:
        invoice = OrderInvoice(order_id=order.id, user_id=current_user.id)
        db.add(invoice)
    data = payload.model_dump()
    for key in ("rfc", "legal_name", "regimen_fiscal", "postal_code", "uso_cfdi", "email"):
        setattr(invoice, key, data[key])
    invoice.refuge_id = order.refuge_id
    invoice.status = "requested"
    invoice.note = None
    invoice.requested_at = _now()
    refuge = db.query(Refuge).filter(Refuge.id == order.refuge_id).first() if order.refuge_id else None
    if refuge:
        notify_order_user(db, refuge.user_id, "invoice_requested", "Te pidieron factura",
                          f"El comprador del pedido #{order.id} pidió factura (RFC {invoice.rfc}). Emítela y súbela en "
                          "Mi tienda > Facturas.", order, seller_tab="facturas")
    db.commit()
    db.refresh(invoice)
    return _invoice_out(invoice)


@router.get("/orders/{id}/invoice", response_model=InvoiceOut)
def get_invoice(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_buyer_order(db, id, current_user)
    if not order.invoice:
        raise HTTPException(status_code=404, detail="Todavía no pides factura de este pedido.")
    return _invoice_out(order.invoice)


def _file_response(doc_id: str | None, filename: str):
    from app.services import crypto_storage

    path = invoicing.fiscal_file_path(doc_id)
    if not path:
        raise HTTPException(status_code=404, detail="No encontramos ese archivo.")
    ext = path.suffix.lstrip(".").lower()
    # El XML y el PDF están cifrados en disco: se descifran en memoria para quien tiene permiso
    return crypto_storage.private_file_response(
        path, media_type="application/xml" if ext == "xml" else "application/pdf",
        filename=f"{filename}.{ext}", content_disposition_type="attachment",
    )


@router.get("/orders/{id}/invoice/{fmt}")
def download_invoice(id: int, fmt: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """XML o PDF de la factura (privados): comprador, refugio vendedor o admins."""
    if fmt not in ("xml", "pdf"):
        raise HTTPException(status_code=404, detail="Formato no disponible.")
    order = db.query(Order).filter(Order.id == id).first()
    invoice = order.invoice if order else None
    seller = (order is not None and order.refuge_id is not None and db.query(Refuge.id).filter(
        Refuge.id == order.refuge_id, Refuge.user_id == current_user.id).first() is not None)
    if not order or not (order.user_id == current_user.id or seller or current_user.role in ADMIN_ROLES):
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    if not invoice or invoice.status != "issued":
        raise HTTPException(status_code=404, detail="La factura todavía no está lista.")
    return _file_response(invoice.xml_document_id if fmt == "xml" else invoice.pdf_document_id,
                          f"factura-pedido-{order.id}")


@router.post("/upload/cfdi-xml")
def upload_cfdi_xml(file: UploadFile = File(...), current_user: User = Depends(get_verified_user),
                    db: Session = Depends(get_db)):
    """El refugio sube el XML timbrado de una factura. Devuelve {id, uuid, emisor_rfc, receptor_rfc, total}."""
    if not db.query(Refuge.id).filter(Refuge.user_id == current_user.id).first():
        raise HTTPException(status_code=403, detail="Solo los refugios vendedores suben facturas.")
    ratelimit.check(f"cfdi-xml:{current_user.id}", limit=MAX_XML_UPLOADS_PER_HOUR, window_seconds=3600,
                    detail="Subiste demasiados archivos. Espera un rato e inténtalo de nuevo.")
    try:
        data = file.file.read(invoicing.MAX_XML_BYTES + 1)
    finally:
        file.file.close()
    try:
        info = invoicing.parse_cfdi_xml(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    doc_id = invoicing.store_fiscal_file(data, "xml")
    return {"id": doc_id, "uuid": info["uuid"], "emisor_rfc": info["emisor_rfc"], "receptor_rfc": info["receptor_rfc"],
            "total": str(info["total"]) if info["total"] is not None else None}


# --------------------------------------------------------------------------- pedidos del refugio
def _my_refuge(db: Session, user: User) -> Refuge:
    refuge = db.query(Refuge).filter(Refuge.user_id == user.id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="Todavía no tienes un refugio registrado.")
    return refuge


def _refuge_order_ids(db: Session, refuge_id: int):
    return db.query(OrderItem.order_id).join(Product, Product.id == OrderItem.product_id).filter(
        Product.refuge_id == refuge_id)


def _shipping_hidden(order: Order) -> bool:
    if order.status not in CLOSED_STATUSES:
        return False
    closed_at = order.completed_at or order.refunded_at or order.cancelled_at or order.return_decided_at
    return bool(closed_at and closed_at < _now() - datetime.timedelta(days=SHIPPING_PRIVACY_DAYS))


def _refuge_order_out(order: Order, refuge_id: int) -> dict:
    items = [i for i in order.items if i.product and i.product.refuge_id == refuge_id]
    hidden = _shipping_hidden(order)
    pending_dispatch = order.status in order_flow.SELLER_CANCELLABLE
    shipping = {f: (None if hidden else getattr(order, f)) for f in (
        "shipping_name", "shipping_phone", "shipping_street", "shipping_ext_number", "shipping_int_number",
        "shipping_neighborhood", "shipping_city", "shipping_state", "shipping_postal_code", "shipping_references")}
    invoice = order.invoice
    return {
        "id": order.id, "status": order.status,
        "status_label": order_flow.STATUS_LABELS.get(order.status, order.status),
        "total": order.total if order.refuge_id == refuge_id else
        sum((Decimal(i.unit_price) * i.quantity for i in items), Decimal("0")),
        "subtotal": order.subtotal, "shipping_total": order.shipping_total or 0, "fee_amount": order.fee_amount or 0,
        "isr_retenido": order.isr_retenido or 0, "iva_retenido": order.iva_retenido or 0, "net_amount": order.net_amount,
        "buyer_name": order.user.full_name if order.user and not hidden else None,
        "shipping_address": "Datos de entrega ocultos (pedido cerrado)" if hidden else order.shipping_address,
        **shipping, "items": items,
        "carrier": order.carrier, "tracking_number": order.tracking_number, "tracking_url": order.tracking_url,
        "paid_at": order.paid_at, "preparing_at": order.preparing_at, "shipped_at": order.shipped_at,
        "delivered_at": order.delivered_at, "completed_at": order.completed_at, "cancelled_at": order.cancelled_at,
        "return_reason": order.return_reason, "return_details": order.return_details,
        "return_photos": order.return_photos, "return_requested_at": order.return_requested_at,
        "return_decided_at": order.return_decided_at,
        "return_decision_note": order.return_decision_note, "refund_amount": order.refund_amount,
        "refund_status": order.refund_status, "timeline": order.timeline or [],
        "cancel_reason": order.cancel_reason, "cancel_note": order.cancel_note,
        "dispatch_due_at": order_flow.dispatch_deadline(order) if pending_dispatch else None,
        "dispatch_cancel_at": order_flow.dispatch_cancel_at(order) if pending_dispatch else None,
        "can_cancel": pending_dispatch,
        "can_retry_refund": order.status == "return_approved" and order.refund_status in order_flow.REFUND_RETRYABLE,
        "invoice": _invoice_out(invoice) if invoice else None,
        "created_at": order.created_at,
    }


def _refuge_order(db: Session, refuge: Refuge, order_id: int) -> Order:
    order = (db.query(Order).options(selectinload(Order.items).selectinload(OrderItem.product), joinedload(Order.user),
                                     selectinload(Order.invoice))
             .filter(Order.id == order_id).first())
    if not order or not (order.refuge_id == refuge.id or db.query(
            _refuge_order_ids(db, refuge.id).filter(OrderItem.order_id == order_id).exists()).scalar()):
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    return order


@router.get("/refuges/me/orders", response_model=list[RefugeOrderOut])
def my_refuge_orders(
    status: str | None = Query(None, pattern=REFUGE_STATUS_PATTERN),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pedidos pagados (o que se pagaron) con productos de mi refugio: para prepararlos, enviarlos y atenderlos."""
    refuge = _my_refuge(db, current_user)
    statuses = [status] if status else list(REFUGE_ORDER_STATUSES)
    orders = (
        db.query(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product), joinedload(Order.user),
                 selectinload(Order.invoice))
        .filter(Order.id.in_(_refuge_order_ids(db, refuge.id)), Order.status.in_(statuses), Order.paid_at.isnot(None))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset(skip).limit(limit).all()
    )
    return [_refuge_order_out(o, refuge.id) for o in orders]


@router.patch("/refuges/me/orders/{id}", response_model=RefugeOrderOut)
def update_my_refuge_order(id: int, payload: RefugeOrderUpdate, current_user: User = Depends(get_verified_user),
                           db: Session = Depends(get_db)):
    """preparing | shipped (paquetería y guía obligatorias) | delivered. El comprador recibe un aviso."""
    refuge = _my_refuge(db, current_user)
    _refuge_order(db, refuge, id)
    fields = {k: getattr(payload, k) for k in ("carrier", "tracking_number", "tracking_url") if k in payload.model_fields_set}
    order_flow.refuge_update(db, id, refuge, payload.status, fields)
    return _refuge_order_out(_refuge_order(db, refuge, id), refuge.id)


@router.post("/refuges/me/orders/{id}/return-decision", response_model=RefugeOrderOut)
def decide_return(id: int, payload: ReturnDecisionRequest, current_user: User = Depends(get_verified_user),
                  db: Session = Depends(get_db)):
    """Aprobar dispara el reembolso en Mercado Pago; rechazar exige explicar el motivo."""
    refuge = _my_refuge(db, current_user)
    _refuge_order(db, refuge, id)
    order_flow.decide_return(db, id, refuge, payload.approve, payload.note)
    return _refuge_order_out(_refuge_order(db, refuge, id), refuge.id)


@router.post("/refuges/me/orders/{id}/retry-refund", response_model=RefugeOrderOut)
def retry_refund(id: int, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    """Reintenta el reembolso de una devolución aprobada que falló (p. ej. faltaba saldo en tu Mercado Pago)."""
    refuge = _my_refuge(db, current_user)
    _refuge_order(db, refuge, id)
    order_flow.retry_return_refund(db, id)
    return _refuge_order_out(_refuge_order(db, refuge, id), refuge.id)


@router.post("/refuges/me/orders/{id}/cancel", response_model=RefugeOrderOut)
def cancel_my_refuge_order(id: int, payload: OrderCancelRequest, current_user: User = Depends(get_verified_user),
                           db: Session = Depends(get_db)):
    """No puedes surtir un pedido pagado: se cancela con el motivo (queda registrado y lo ve el comprador) y se le
    reembolsa el total de inmediato (consumidor-ecommerce-14)."""
    refuge = _my_refuge(db, current_user)
    _refuge_order(db, refuge, id)
    order_flow.seller_cancel(db, id, refuge, payload.reason, payload.note)
    return _refuge_order_out(_refuge_order(db, refuge, id), refuge.id)


@router.get("/refuges/me/invoice-requests", response_model=list[InvoiceOut])
def my_invoice_requests(
    status: str | None = Query("requested", pattern="^(requested|issued|rejected|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cola de solicitudes de factura de mis compradores."""
    refuge = _my_refuge(db, current_user)
    q = db.query(OrderInvoice).filter(OrderInvoice.refuge_id == refuge.id)
    if status and status != "all":
        q = q.filter(OrderInvoice.status == status)
    return [_invoice_out(i) for i in q.order_by(OrderInvoice.requested_at.desc()).limit(200).all()]


@router.post("/refuges/me/orders/{id}/invoice", response_model=InvoiceOut)
def issue_invoice(id: int, payload: InvoiceIssueIn, current_user: User = Depends(get_verified_user),
                  db: Session = Depends(get_db)):
    """El refugio registra la factura emitida (UUID + XML y PDF) o la rechaza con un motivo."""
    refuge = _my_refuge(db, current_user)
    order = _refuge_order(db, refuge, id)
    invoice = order.invoice
    if not invoice or invoice.status != "requested":
        raise HTTPException(status_code=409, detail="Este pedido no tiene una solicitud de factura pendiente.")
    if payload.status == "rejected":
        note = (payload.note or "").strip()
        if len(note) < 5:
            raise HTTPException(status_code=400, detail="Explica al comprador por qué no puedes emitir la factura.")
        invoice.status = "rejected"
        invoice.note = note
        notify_order_user(db, order.user_id, "invoice_rejected", "No se pudo emitir tu factura",
                          f"{refuge.name} no pudo emitir la factura del pedido #{order.id}: {note} Puedes corregir tus "
                          "datos y pedirla de nuevo.", order)
        db.commit()
        db.refresh(invoice)
        return _invoice_out(invoice)

    profile = refuge.fiscal_profile
    if not profile or not profile.rfc:
        # Sin perfil fiscal no se puede comprobar que el CFDI lo emitió este refugio (fiscal-tienda-19)
        raise HTTPException(status_code=400, detail="Registra tus datos fiscales (RFC) en Mi tienda > Datos fiscales "
                                                    "antes de subir facturas.")
    if not invoicing.fiscal_file_path(payload.xml_document_id):
        raise HTTPException(status_code=400, detail="Sube el XML timbrado de la factura.")
    if payload.pdf_document_id and not invoicing.fiscal_file_path(payload.pdf_document_id):
        raise HTTPException(status_code=400, detail="No encontramos el PDF de la factura. Vuelve a subirlo.")
    try:
        info = invoicing.parse_cfdi_xml(invoicing.read_fiscal_file(payload.xml_document_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Validaciones de fiscal-tienda-19: UUID, RFC emisor (el refugio), receptor (el comprador) y total
    if payload.uuid and payload.uuid.upper() != info["uuid"]:
        raise HTTPException(status_code=400, detail="El UUID no coincide con el del XML.")
    if (info["emisor_rfc"] or "") != profile.rfc.upper():
        raise HTTPException(status_code=400, detail="El RFC emisor del XML no es el de tu perfil fiscal.")
    if info["receptor_rfc"] and info["receptor_rfc"] != invoice.rfc:
        raise HTTPException(status_code=400, detail="El RFC del receptor del XML no es el que pidió el comprador.")
    if info["total"] is not None and abs(info["total"] - Decimal(order.total)) > Decimal("1.00"):
        raise HTTPException(status_code=400, detail=f"El total del XML ({info['total']}) no coincide con el del pedido "
                                                    f"({order.total}).")
    if db.query(OrderInvoice.id).filter(OrderInvoice.uuid == info["uuid"], OrderInvoice.id != invoice.id).first():
        raise HTTPException(status_code=409, detail="Ese CFDI (folio fiscal) ya está registrado en otro pedido. Sube el "
                                                    "XML de la factura de este pedido.")
    invoice.status = "issued"
    invoice.uuid = info["uuid"]
    invoice.xml_document_id = payload.xml_document_id
    invoice.pdf_document_id = payload.pdf_document_id
    invoice.note = (payload.note or "").strip() or None
    invoice.issued_at = _now()
    notify_order_user(db, order.user_id, "invoice_issued", "Tu factura está lista",
                      f"{refuge.name} emitió la factura del pedido #{order.id}. Descárgala desde Mis pedidos.", order)
    try:
        db.commit()
    except IntegrityError:  # dos pedidos con el mismo XML al mismo tiempo (índice único uq_order_invoices_uuid)
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese CFDI (folio fiscal) ya está registrado en otro pedido.")
    db.refresh(invoice)
    return _invoice_out(invoice)


# --------------------------------------------------------------------------- admins
@router.post("/admin/orders/{id}/resolve", response_model=AdminOrderOut)
def admin_resolve_order(id: int, payload: PaymentResolveRequest, request: Request,
                        admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Pedidos en revisión: mark_paid acepta el pago; refund lo reembolsa en Mercado Pago y libera el inventario."""
    resolve_order(db, id, admin_user, payload.action, payload.notes, request=request)
    return order_out(_order_query(db).filter(Order.id == id).first(), AdminOrderOut)


@router.post("/admin/orders/{id}/refund", response_model=AdminOrderOut)
def admin_refund_order(id: int, request: Request, payload: AdminRefundRequest | None = None,
                       admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Reembolso de lo que falta (sin amount) o parcial en Mercado Pago, con el token del refugio si se cobró por
    split. Un parcial no cierra el pedido; se pueden hacer varios hasta completar el total."""
    order_flow.admin_refund(db, id, admin_user, payload.amount if payload else None, request=request,
                            item_ids=payload.item_ids if payload else None)
    return order_out(_order_query(db).filter(Order.id == id).first(), AdminOrderOut)


@router.post("/admin/orders/{id}/cancel", response_model=AdminOrderOut)
def admin_cancel_order(id: int, payload: OrderCancelRequest, request: Request,
                       admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Cancelación por el equipo antes del envío, solo con causa objetiva registrada; si ya se cobró, reembolso total."""
    order_flow.admin_cancel(db, id, admin_user, payload.reason, payload.note, request=request)
    return order_out(_order_query(db).filter(Order.id == id).first(), AdminOrderOut)
