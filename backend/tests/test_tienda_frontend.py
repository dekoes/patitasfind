"""Frontend de la tienda (S7): contrato entre app/tienda.js + app/admin-tienda.js y el backend.

- Esquemas y rutas: los campos y endpoints que leen las pantallas (Mis pedidos, Mi tienda, panel de admin).
  Si alguno cambia de nombre la UI dejaría de mostrarlo sin ningún error visible; estas pruebas fallan antes.
- API (corre en el contenedor): las peticiones se arman EXACTAMENTE como las manda tienda.js (producto con
  envío y estados, datos fiscales, estado de cuenta, cola de facturas, estado de Mercado Pago).
- Archivos del frontend: dentro del contenedor (/app = backend) no está app/; esas pruebas se omiten salvo que
  PATITASFIND_REPO apunte al repo completo (como en CI).

Ninguna prueba llama a Mercado Pago ni a un PAC: el refugio de prueba no conecta su cuenta.
"""
import datetime
import os
import re
import uuid
from pathlib import Path

import pytest

from app import schemas
from app.data import estados_mx
from app.database import SessionLocal
from app.main import app
from app.models import Product, Refuge, User
from conftest import _register

REPO = Path(os.environ.get("PATITASFIND_REPO") or Path(__file__).resolve().parents[2])
APP_DIR = REPO / "app"
needs_frontend = pytest.mark.skipif(not (APP_DIR / "tienda.js").exists(),
                                    reason="app/ no está disponible (contenedor); usa PATITASFIND_REPO")


# --------------------------------------------------------------------------- esquemas y rutas
def _fields(model) -> set[str]:
    return set(model.model_fields)


def test_order_fields_read_by_buyer_screens():
    """Mis pedidos / detalle con línea de tiempo, acciones, devoluciones, reembolso y factura."""
    used = {
        "id", "status", "refuge_id", "refuge_name", "subtotal", "shipping_total", "total", "items", "created_at",
        "shipping_address", "shipping_name", "shipping_phone", "shipping_street", "shipping_ext_number",
        "shipping_int_number", "shipping_neighborhood", "shipping_city", "shipping_state", "shipping_postal_code",
        "shipping_references", "carrier", "tracking_number", "tracking_url", "paid_at", "preparing_at", "shipped_at",
        "delivered_at", "completed_at", "cancelled_at", "cancel_reason", "return_reason", "return_details",
        "return_decision_note", "refund_amount", "refund_status", "timeline", "can_cancel", "can_confirm_delivery",
        "can_return", "revocation_until", "claim_until", "invoice_status", "checkout_url", "cancel_note",
        "dispatch_due_at", "fee_percent", "fee_amount",
    }
    assert used <= _fields(schemas.OrderOut), used - _fields(schemas.OrderOut)
    assert {"checkout_url", "simulated"} <= _fields(schemas.OrderCheckoutOut)
    assert {"status", "at", "note", "by"} <= _fields(schemas.TimelineEntry)


def test_refuge_order_invoice_and_payment_fields_read_by_seller_panel():
    used_orders = {
        "id", "status", "total", "net_amount", "buyer_name", "items", "shipping_name", "shipping_phone",
        "shipping_street", "shipping_state", "carrier", "tracking_number", "tracking_url", "shipped_at",
        "delivered_at", "return_reason", "return_details", "return_photos", "return_decision_note", "refund_status",
        "invoice", "created_at", "cancel_reason", "cancel_note", "dispatch_due_at", "dispatch_cancel_at", "can_cancel",
        "can_retry_refund",
    }
    assert used_orders <= _fields(schemas.RefugeOrderOut), used_orders - _fields(schemas.RefugeOrderOut)
    used_invoice = {"order_id", "status", "rfc", "legal_name", "regimen_fiscal", "postal_code", "uso_cfdi", "email",
                    "uuid", "note", "requested_at", "xml_url", "pdf_url"}
    assert used_invoice <= _fields(schemas.InvoiceOut)
    used_mp = {"connected", "ready", "simulated", "marketplace_configured", "mp_user_id", "connected_at", "last_error",
               "fee_percent", "donation_fee_percent", "fiscal_profile_complete"}
    assert used_mp <= _fields(schemas.SellerPaymentsStatusOut)
    assert {"person_type", "rfc", "legal_name", "regimen_fiscal", "postal_code", "is_donataria",
            "csf_document_id"} <= _fields(schemas.RefugeFiscalOut)
    assert {"seller_payments_ready", "donations_ready"} <= _fields(schemas.RefugeOut)
    assert {"shipping_cost", "ships_nationwide", "ships_states", "handling_days", "seller_payments_ready",
            "platform_fee_percent"} <= _fields(schemas.ProductOut)


def test_admin_fields_read_by_admin_panel():
    assert {"user", "refuge_name", "fee_amount", "net_amount", "provider_payment_id", "review_note", "refund_id",
            "refund_amount", "refund_status", "timeline", "return_decision_note", "paid_amount", "cancel_reason",
            "cancel_note", "terms_version", "terms_accepted_at", "terms_hash", "terms_ip"} <= _fields(schemas.AdminOrderOut)
    assert {"id", "kind", "period", "refuge_id", "refuge_name", "uuid", "status", "subtotal", "iva", "isr_retenido",
            "iva_retenido", "total", "error", "attempts", "created_at", "has_xml", "has_pdf"} <= _fields(schemas.CfdiOut)


ROUTES_USED = [
    # app/tienda.js
    ("GET", "/products"), ("POST", "/products"), ("PATCH", "/products/{id}"), ("DELETE", "/products/{id}"),
    ("POST", "/orders"), ("GET", "/orders"), ("GET", "/orders/{id}"), ("POST", "/orders/{id}/cancel"),
    ("POST", "/orders/{id}/confirm-delivery"), ("POST", "/orders/{id}/return"),
    ("POST", "/orders/{id}/invoice-request"), ("GET", "/orders/{id}/invoice"), ("GET", "/orders/{id}/invoice/{fmt}"),
    ("POST", "/upload/cfdi-xml"), ("POST", "/upload/document"),
    ("GET", "/refuges/me"), ("GET", "/refuges/me/products"), ("GET", "/refuges/me/orders"),
    ("PATCH", "/refuges/me/orders/{id}"), ("POST", "/refuges/me/orders/{id}/return-decision"),
    ("POST", "/refuges/me/orders/{id}/cancel"), ("POST", "/refuges/me/orders/{id}/retry-refund"),
    ("GET", "/refuges/me/invoice-requests"), ("POST", "/refuges/me/orders/{id}/invoice"),
    ("GET", "/refuges/me/fiscal"), ("PATCH", "/refuges/me/fiscal"),
    ("GET", "/refuges/me/payments/connect"), ("GET", "/refuges/me/payments/status"),
    ("POST", "/refuges/me/payments/disconnect"),
    ("GET", "/refuges/me/statements"), ("GET", "/refuges/me/statements/export"),
    ("GET", "/payments/status"), ("GET", "/payments/mercadopago/oauth/callback"),
    # app/admin-tienda.js
    ("GET", "/admin/orders"), ("POST", "/admin/orders/{id}/refund"), ("POST", "/admin/orders/{id}/resolve"),
    ("POST", "/admin/orders/{id}/cancel"),
    ("GET", "/admin/cfdi"), ("POST", "/admin/cfdi/generate"), ("POST", "/admin/cfdi/{id}/retry"),
    ("GET", "/admin/cfdi/{id}/{fmt}"), ("GET", "/admin/statements"),
]


def test_every_endpoint_used_by_the_frontend_exists():
    # Se usa el esquema OpenAPI: app.routes puede traer routers incluidos de forma perezosa (sin .path)
    paths = app.openapi()["paths"]
    missing = [f"{m} {p}" for m, p in ROUTES_USED if m.lower() not in paths.get(p, {})]
    assert not missing, missing


def test_bodies_built_like_the_frontend_validate():
    """submitCheckout, readInvoiceRequest, submitFiscal y readProduct (tienda.js) contra los esquemas de entrada."""
    checkout = {
        "items": [{"product_id": 1, "quantity": 2}],
        "shipping_name": "Ana Pérez", "shipping_phone": "33 1234 5678", "shipping_street": "Av. Juárez",
        "shipping_ext_number": "100", "shipping_int_number": None, "shipping_neighborhood": "Centro",
        "shipping_city": "Guadalajara", "shipping_state": "Jalisco", "shipping_postal_code": "44100",
        "shipping_references": None, "shipping_address": "Av. Juárez 100, Centro, 44100 Guadalajara, Jalisco",
        "accepted_terms": True, "consent_prepayment": True, "terms_version": "2026-10-16",
    }
    order = schemas.OrderCreate.model_validate(checkout)
    assert order.structured_shipping()["shipping_state"] == "Jalisco"

    inv = schemas.InvoiceRequestIn.model_validate({"rfc": "PEPA800101AB1", "legal_name": "ANA PEREZ PEREZ",
                                                   "regimen_fiscal": "612", "postal_code": "44100", "uso_cfdi": "G03",
                                                   "email": "ana@example.com"})
    assert inv.regimen_fiscal == "612"
    with pytest.raises(ValueError):  # la UI filtra los regímenes por tipo de RFC; el backend lo exige
        schemas.InvoiceRequestIn.model_validate({"rfc": "PEPA800101AB1", "legal_name": "ANA PEREZ",
                                                 "regimen_fiscal": "601", "postal_code": "44100",
                                                 "uso_cfdi": "G03", "email": "ana@example.com"})

    schemas.RefugeFiscalUpdate.model_validate({"person_type": "moral", "rfc": "ABC010101AB1", "legal_name": "HUELLITAS AC",
                                               "regimen_fiscal": "603", "postal_code": "06700", "is_donataria": True})
    product = schemas.ProductCreate.model_validate({
        "name": "Placa QR", "description": None, "price": 149.0, "stock": 3, "shipping_cost": 60.0, "handling_days": 2,
        "ships_nationwide": False, "ships_states": ["Jalisco", "México"], "photos": ["/uploads/x.jpg"],
    })
    assert product.ships_states == ["Jalisco", "México"]


# --------------------------------------------------------------------------- API como la usa "Mi tienda"
def _approved_refuge(client):
    """Refugio aprobado SIN Mercado Pago conectado (no se llama a ningún servicio externo)."""
    u = _register(client, "Refugio Panel Tienda")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == u["email"]).first()
        user.role = "refuge"
        refuge = Refuge(user_id=user.id, name=f"Refugio Front {uuid.uuid4().hex[:5]}", status="approved")
        db.add(refuge)
        db.commit()
        u["refuge_id"] = refuge.id
    finally:
        db.close()
    return u


def test_seller_panel_requests_as_tienda_js_sends_them(client):
    seller = _approved_refuge(client)
    h = seller["h"]

    # Pestaña Productos: alta con envío y estados atendidos (readProduct)
    r = client.post("/products", headers=h, json={
        "name": "Placa QR E2E", "description": None, "price": 149, "stock": 3, "shipping_cost": 60, "handling_days": 2,
        "ships_nationwide": False, "ships_states": ["Jalisco", "México"], "photos": [],
        "category": "accesorios_juguetes", "warranty_text": "Sin garantía adicional",
    })
    assert r.status_code == 201, r.text
    p = r.json()
    try:
        assert set(p["ships_states"]) == {"Jalisco", "México"}
        assert float(p["shipping_cost"]) == 60 and p["handling_days"] == 2 and p["ships_nationwide"] is False
        # La tarjeta de producto y la pestaña Cobros deben coincidir: sin cuenta conectada el producto solo se
        # puede comprar si hay pagos simulados (desarrollo); si no, la UI muestra "Este refugio aún no activa cobros"
        ready = client.get("/refuges/me/payments/status", headers=h).json()["ready"]
        assert p["seller_payments_ready"] is ready
        listed = client.get("/refuges/me/products", headers=h).json()
        assert any(x["id"] == p["id"] for x in listed)

        # Pestaña Pedidos y Facturas
        assert client.get("/refuges/me/orders?limit=100", headers=h).status_code == 200
        r = client.get("/refuges/me/invoice-requests?status=all", headers=h)
        assert r.status_code == 200 and r.json() == []

        # Pestaña Datos fiscales: sin perfil responde null (la UI muestra el formulario vacío)
        r = client.get("/refuges/me/fiscal", headers=h)
        assert r.status_code == 200 and r.json() is None
        r = client.patch("/refuges/me/fiscal", headers=h, json={
            "person_type": "fisica", "rfc": "PEPA800101AB1", "legal_name": "ANA PEREZ PEREZ", "regimen_fiscal": "612",
            "postal_code": "44100", "is_donataria": False,
        })
        assert r.status_code == 200, r.text
        assert r.json()["rfc"] == "PEPA800101AB1"

        # Pestaña Cobros
        r = client.get("/refuges/me/payments/status", headers=h)
        assert r.status_code == 200, r.text
        st = r.json()
        assert st["connected"] is False and "fee_percent" in st and st["fiscal_profile_complete"] is True

        # Pestaña Estado de cuenta (periodo AAAA-MM como lo arma lastPeriods())
        period = datetime.date.today().strftime("%Y-%m")
        r = client.get(f"/refuges/me/statements?period={period}", headers=h)
        assert r.status_code == 200, r.text
        s = r.json()
        for key in ("orders_count", "gross", "shipping", "platform_fee", "fee_iva", "isr_retenido", "iva_retenido",
                    "net_received", "donations_gross", "donations_fee", "orders"):
            assert key in s, key
        r = client.get(f"/refuges/me/statements/export?period={period}", headers=h)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    finally:
        db = SessionLocal()
        try:
            db.query(Product).filter(Product.id == p["id"]).update({Product.is_active: False})
            db.commit()
        finally:
            db.close()


# --------------------------------------------------------------------------- archivos del frontend
def _read(name: str) -> str:
    return (APP_DIR / name).read_text(encoding="utf-8")


def _js_list(src: str, name: str) -> list[str]:
    m = re.search(rf"const {name} = \[(.*?)\];", src, re.S)
    assert m, name
    return re.findall(r"'([^']+)'", m.group(1))


@needs_frontend
def test_states_and_regimes_match_backend_catalogs():
    src = _read("tienda.js")
    assert _js_list(src, "MX_STATES") == list(estados_mx.STATE_NAMES)
    assert _js_list(src, "REGIMENES_FISICA") == list(schemas.REGIMENES_FISICA)
    # 609 (Consolidación) ya no se ofrece en la UI; el resto es igual al backend
    assert set(_js_list(src, "REGIMENES_MORAL")) == set(schemas.REGIMENES_MORAL) - {"609"}
    labels = re.search(r"const ORDER_STATUS = \{(.*?)\};", src, re.S).group(1)
    for status in schemas.ORDER_STATUSES:
        assert re.search(rf"\b{status}: '", labels), f"falta la etiqueta en español de {status}"


@needs_frontend
def test_scripts_are_loaded_and_ids_exist():
    index, admin = _read("index.html"), _read("admin.html")
    assert index.index('src="/app/app.js') < index.index('src="/app/tienda.js')
    assert admin.index('src="/admin/admin.js') < admin.index('src="/app/admin-tienda.js')
    ids = set(re.findall(r'id="([^"]+)"', index))
    src = _read("tienda.js")
    dynamic = {"ms-add-product", "ms-orders", "ms-order-filters", "ms-period", "ms-csv", "ms-stmt", "fiscal-form",
               "fp-type", "fp-rfc", "fp-name", "fp-regimen", "fp-cp", "fp-donataria", "fp-csf", "fp-csf-btn",
               "fp-csf-text", "fp-save", "mp-connect", "mp-disconnect", "mp-status", "od-cancel", "od-confirm",
               "od-return", "od-invoice", "od-hint", "od-invoice-card", "pd-add", "pd-name", "dc-reason-wrap",
               "dc-reason",
               "co-seller", "co-iva"}  # identidad del vendedor e IVA: se dibujan dentro de #co-summary
    used = set(re.findall(r"\$\('#([A-Za-z0-9_-]+)", src)) - dynamic
    assert not used - ids, sorted(used - ids)
    admin_ids = set(re.findall(r'id="([^"]+)"', admin))
    used_admin = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)', _read("admin-tienda.js")))
    assert not used_admin - admin_ids, sorted(used_admin - admin_ids)


@needs_frontend
def test_checkout_texts_match_backend_and_legal_notices():
    """Los textos de las casillas son los que se guardan con hash (consumidor-ecommerce-05/06/08); aviso de 18+,
    dirección guardada solo con casilla no premarcada (-20) y sin "Pago 100% seguro" (-17)."""
    from app.services.payment_flow import CHECKOUT_CONSENT_TEXTS

    index = _read("index.html")
    labels = [re.sub(r"<[^>]+>", "", m) for m in re.findall(
        r'id="co-(?:terms|prepay)"[^>]*> <span>(.*?)</span></label>', index)]
    assert labels == list(CHECKOUT_CONSENT_TEXTS)
    assert "mayores de 18 años" in index
    save = re.search(r'<input type="checkbox" id="co-save-address"[^>]*>', index).group(0)
    assert "checked" not in save
    for name in ("index.html", "app.js", "tienda.js"):
        assert "Pago 100% seguro" not in _read(name), name
    src = _read("tienda.js")
    assert "if ($('#co-save-address').checked) rememberAddress(a);" in src
    assert "e.status === 403 || e.status === 404" in src  # avisos viejos /app/?order=N al refugio
    assert "donations_ready" in _read("app.js") and "?shop=" in src + _read("app.js")
