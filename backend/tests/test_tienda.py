"""Tienda: Mercado Pago Marketplace (OAuth + split), envíos, estados del pedido, devoluciones, reembolsos,
facturas del refugio, perfil fiscal, CFDI de la plataforma (PAC) y estados de cuenta.

Ninguna prueba llama a Mercado Pago, Facturama ni a ningún servicio externo: todo va con monkeypatch.
"""
import base64
import datetime
import random
import uuid
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AdminAuditLog, Cfdi, Donation, Notification, Order, OrderRefund, Product, Refuge, RefugeFiscalProfile,
    RefugePaymentAccount, User,
)
from app.routers import payments as payments_router
from app.services import invoicing, mercadopago_oauth, notify, order_flow, payment_flow, payments, statements
from conftest import _register

CREATED_PRODUCTS: list[int] = []


# --------------------------------------------------------------------------- utilidades
def _db():
    return SessionLocal()


@pytest.fixture(autouse=True)
def _commission_10(monkeypatch):
    """Estas pruebas verifican la aritmética de comisión y retenciones con 10 % (el valor por defecto ahora es 0 %)."""
    monkeypatch.setattr(settings, "mercadopago_marketplace_fee_percent", 10.0)


@pytest.fixture(scope="module", autouse=True)
def _deactivate_products():
    """Al terminar, los productos de prueba dejan de listarse (otras pruebas compran el más reciente)."""
    yield
    if CREATED_PRODUCTS:
        db = _db()
        try:
            db.query(Product).filter(Product.id.in_(CREATED_PRODUCTS)).update({Product.is_active: False},
                                                                              synchronize_session=False)
            db.commit()
        finally:
            db.close()


def _user_id(email):
    db = _db()
    try:
        return db.query(User.id).filter(User.email == email).scalar()
    finally:
        db.close()


def _set_role(email, role):
    db = _db()
    try:
        db.query(User).filter(User.email == email).update({User.role: role})
        db.commit()
    finally:
        db.close()


def _connect(db, refuge_id, mp_user_id=None, expires_in=15552000):
    return mercadopago_oauth.save_tokens(db, refuge_id, {
        "access_token": f"APP_USR-seller-{refuge_id}", "refresh_token": f"TG-refresh-{refuge_id}",
        "user_id": mp_user_id or random.randint(10 ** 8, 10 ** 9), "public_key": "APP_USR-pk", "expires_in": expires_in})


def _make_seller(client, connected=True, fiscal: dict | None = None, name="Refugio Tienda"):
    u = _register(client, name)
    db = _db()
    try:
        user = db.query(User).filter(User.email == u["email"]).first()
        refuge = Refuge(user_id=user.id, name=f"Refugio {uuid.uuid4().hex[:5]}", status="approved")
        db.add(refuge)
        db.flush()
        if connected:
            account = _connect(db, refuge.id)
            u["mp_user_id"] = account.mp_user_id
        if fiscal:
            db.add(RefugeFiscalProfile(refuge_id=refuge.id, **fiscal))
        db.commit()
        u["refuge_id"] = refuge.id
        u["user_id"] = user.id
        u["seller_token"] = f"APP_USR-seller-{refuge.id}"
        return u
    finally:
        db.close()


def _product(client, seller, price=100, stock=10, **extra):
    # Categoría y garantía obligatorias (reglas de negocio, consumidor-ecommerce-04)
    body = {"name": f"Collar {uuid.uuid4().hex[:4]}", "price": price, "stock": stock, "category": "accesorios_juguetes",
            "warranty_text": "Sin garantía adicional", **extra}
    r = client.post("/products", headers=seller["h"], json=body)
    assert r.status_code == 201, r.text
    CREATED_PRODUCTS.append(r.json()["id"])
    return r.json()


ADDRESS = {"shipping_name": "Ana Pérez", "shipping_phone": "5512345678", "shipping_street": "Av. Insurgentes Sur",
           "shipping_ext_number": "123", "shipping_int_number": "4B", "shipping_neighborhood": "Del Valle",
           "shipping_city": "Benito Juárez", "shipping_state": "CDMX", "shipping_postal_code": "03100",
           "shipping_references": "Portón negro"}


# Las dos casillas no premarcadas del checkout (consumidor-ecommerce-05 y 06)
CONSENT = {"accepted_terms": True, "consent_prepayment": True}


def _order_body(items, **address):
    return {"items": [{"product_id": p["id"], "quantity": q} for p, q in items], **ADDRESS, **CONSENT, **address}


def _buy(client, buyer, items, **address):
    r = client.post("/orders", headers=buyer["h"], json=_order_body(items, **address))
    assert r.status_code == 201, r.text
    return r.json()


def _order(order_id) -> Order:
    db = _db()
    try:
        o = db.query(Order).filter(Order.id == order_id).first()
        db.expunge(o)
        return o
    finally:
        db.close()


def _update_order(order_id, **values):
    db = _db()
    try:
        db.query(Order).filter(Order.id == order_id).update(values)
        db.commit()
    finally:
        db.close()


def _notifs(user_id, type_, order_id=None):
    db = _db()
    try:
        rows = db.query(Notification).filter(Notification.user_id == user_id, Notification.type == type_).all()
        return [n for n in rows if order_id is None or (n.data or {}).get("order_id") == order_id]
    finally:
        db.close()


def _move_refunds(order_id, when):
    """Fecha los reembolsos de un pedido (los periodos de prueba están en el futuro)."""
    db = _db()
    try:
        db.query(OrderRefund).filter(OrderRefund.order_id == order_id).update({OrderRefund.created_at: when})
        db.commit()
    finally:
        db.close()


def _stock(product_id):
    db = _db()
    try:
        return db.query(Product.stock).filter(Product.id == product_id).scalar()
    finally:
        db.close()


def _mp_payment(ref, amount, status="approved", pid=None, collector=None):
    return {"id": int(pid or random.randint(10 ** 11, 10 ** 12 - 1)), "status": status, "external_reference": ref,
            "transaction_amount": float(amount), "currency_id": "MXN", "collector_id": collector}


@pytest.fixture
def emails(monkeypatch):
    """Captura los correos que despacha services/notify.py (sin SMTP real)."""
    sent = []
    monkeypatch.setattr(notify, "can_email", lambda user: True)
    monkeypatch.setattr(notify, "_dispatch", lambda task, *args: sent.append((task, args)))
    return sent


@pytest.fixture
def mp(monkeypatch):
    """Mercado Pago "activo" (plataforma + aplicación Marketplace) con la API simulada."""
    monkeypatch.setattr(settings, "mercadopago_access_token", "APP_USR-platform")
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", None)
    monkeypatch.setattr(settings, "mercadopago_app_id", "1234567890")
    monkeypatch.setattr(settings, "mercadopago_client_secret", "secreto-app")
    calls = {"preferences": [], "refunds": [], "searches": [], "refund_keys": []}

    def fake_preference(items, external_reference, back_query, payer_email=None, **kwargs):
        calls["preferences"].append({"items": items, "external_reference": external_reference, **kwargs})
        return {"id": f"pref-{uuid.uuid4().hex[:8]}", "init_point": "https://www.mercadopago.com.mx/checkout/v1/redirect"}

    def fake_refund(payment_id, **kwargs):
        # Todo reembolso lleva una clave de idempotencia estable (ver test_admin_refund_is_idempotent_...)
        key = kwargs.pop("idempotency_key", None)
        assert key and key.startswith("guauwoow-"), "reembolso sin X-Idempotency-Key estable"
        calls["refund_keys"].append(key)
        calls["refunds"].append({"payment_id": payment_id, **kwargs})
        return {"id": random.randint(10 ** 6, 10 ** 7), "status": "approved", "amount": kwargs.get("amount")}

    monkeypatch.setattr(payments, "create_preference", fake_preference)
    monkeypatch.setattr(payments, "refund_payment", fake_refund)
    monkeypatch.setattr(payments, "search_payments", lambda ref, **kw: calls["searches"].append((ref, kw)) or [])
    return calls


def _pay(monkeypatch, order, collector=None):
    """El webhook confirma el pago aprobado (consulta simulada)."""
    payment = _mp_payment(f"order:{order['id']}", order["total"], collector=collector)
    monkeypatch.setattr(payments, "get_payment", lambda pid, **kw: payment)
    db = _db()
    try:
        assert payment_flow.process_payment(db, str(payment["id"])) == "order:paid"
    finally:
        db.close()
    return payment


@pytest.fixture
def admin(client):
    u = _register(client, "Admin Tienda")
    _set_role(u["email"], "admin")
    u["id"] = _user_id(u["email"])
    yield u
    _set_role(u["email"], "user")


# --------------------------------------------------------------------------- S1 OAuth
def test_oauth_connect_callback_status_and_disconnect(client, monkeypatch, mp):
    seller = _make_seller(client, connected=False)
    r = client.get("/refuges/me/payments/connect", headers=seller["h"])
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["url"])
    q = parse_qs(url.query)
    assert url.netloc == "auth.mercadopago.com" and url.path == "/authorization"
    assert q["client_id"] == ["1234567890"] and q["response_type"] == ["code"] and q["platform_id"] == ["mp"]
    assert q["redirect_uri"][0].endswith("/payments/mercadopago/oauth/callback")
    state = q["state"][0]
    assert mercadopago_oauth.read_state(state)["r"] == seller["refuge_id"]
    assert client.get("/refuges/me/payments/status", headers=seller["h"]).json()["connected"] is False

    sent = []

    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"access_token": "APP_USR-recien-vinculado", "token_type": "bearer", "expires_in": 15552000,
                    "scope": "offline_access read write", "user_id": 777000111, "refresh_token": "TG-nuevo",
                    "public_key": "APP_USR-pk-1", "live_mode": False}

    monkeypatch.setattr(mercadopago_oauth.requests, "post", lambda url, json=None, **kw: sent.append((url, json)) or Resp())
    bad = client.get("/payments/mercadopago/oauth/callback", params={"code": "TG-abc", "state": state + "x"},
                     follow_redirects=False)
    assert bad.status_code == 302 and bad.headers["location"].endswith("/app/#mp=error") and not sent
    ok = client.get("/payments/mercadopago/oauth/callback", params={"code": "TG-abc123", "state": state},
                    follow_redirects=False)
    assert ok.status_code == 302 and ok.headers["location"].endswith("/app/#mp=connected")
    assert sent[0][0] == "https://api.mercadopago.com/oauth/token"
    assert sent[0][1]["grant_type"] == "authorization_code" and sent[0][1]["code"] == "TG-abc123"
    assert sent[0][1]["client_secret"] == "secreto-app"

    db = _db()
    try:
        account = db.query(RefugePaymentAccount).filter(RefugePaymentAccount.refuge_id == seller["refuge_id"]).first()
        assert account.mp_user_id == "777000111" and account.status == "connected"
        assert "APP_USR-recien-vinculado" not in (account.access_token_enc or "")  # cifrado en reposo
        assert mercadopago_oauth.decrypt(account.access_token_enc) == "APP_USR-recien-vinculado"
        assert mercadopago_oauth.decrypt(account.refresh_token_enc) == "TG-nuevo"
    finally:
        db.close()
    st = client.get("/refuges/me/payments/status", headers=seller["h"]).json()
    assert st["connected"] is True and st["mp_user_id"] == "777000111" and st["fee_percent"] == 10.0
    refuge = client.get(f"/refuges/{seller['refuge_id']}").json()
    assert refuge["seller_payments_ready"] is True

    off = client.post("/refuges/me/payments/disconnect", headers=seller["h"])
    assert off.status_code == 200 and off.json()["connected"] is False
    assert client.get(f"/refuges/{seller['refuge_id']}").json()["seller_payments_ready"] is False


def test_seller_token_refresh_before_expiry(client, monkeypatch, mp):
    seller = _make_seller(client)
    db = _db()
    try:
        account = db.query(RefugePaymentAccount).filter(RefugePaymentAccount.refuge_id == seller["refuge_id"]).first()
        account.expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=2)  # vence hoy
        db.commit()
        bodies = []

        class Resp:
            status_code = 200
            text = ""

            def json(self):
                return {"access_token": "APP_USR-renovado", "refresh_token": "TG-renovado", "user_id": account.mp_user_id,
                        "expires_in": 15552000}

        monkeypatch.setattr(mercadopago_oauth.requests, "post", lambda url, json=None, **kw: bodies.append(json) or Resp())
        assert mercadopago_oauth.seller_access_token(db, account) == "APP_USR-renovado"
        assert bodies[0]["grant_type"] == "refresh_token" and bodies[0]["refresh_token"] == f"TG-refresh-{seller['refuge_id']}"
        db.refresh(account)
        assert mercadopago_oauth.decrypt(account.refresh_token_enc) == "TG-renovado"
        assert account.expires_at > datetime.datetime.utcnow() + datetime.timedelta(days=170)
    finally:
        db.close()


# --------------------------------------------------------------------------- S1/S4 checkout con split
def test_checkout_uses_seller_token_and_marketplace_fee(client, user, mp):
    seller = _make_seller(client)
    p1 = _product(client, seller, price="199.90", shipping_cost="89")
    p2 = _product(client, seller, price="50", shipping_cost="40")
    order = _buy(client, user, [(p1, 2), (p2, 1)])
    # subtotal 449.80 + envío (el mayor: 89, una sola vez) = 538.80; comisión 10 % = 53.88
    assert Decimal(order["subtotal"]) == Decimal("449.80") and Decimal(order["shipping_total"]) == Decimal("89.00")
    assert Decimal(order["total"]) == Decimal("538.80") and Decimal(order["fee_amount"]) == Decimal("53.88")
    assert order["status"] == "pending_payment" and order["checkout_url"].startswith("https://")
    assert order["refuge_id"] == seller["refuge_id"] and order["payment_mode"] == "split"
    assert order["shipping_state"] == "Ciudad de México" and "Del Valle" in order["shipping_address"]
    pref = mp["preferences"][-1]
    assert pref["access_token"] == seller["seller_token"]
    assert pref["marketplace_fee"] == Decimal("53.88")
    assert pref["notification_query"] == f"ref=order-{order['id']}"
    assert {"title": "Envío", "quantity": 1, "unit_price": Decimal("89.00")} in pref["items"]
    assert sum(Decimal(str(i["unit_price"])) * i["quantity"] for i in pref["items"]) == Decimal("538.80")
    o = _order(order["id"])
    assert o.net_amount == Decimal("484.92") and o.collector_id == seller["mp_user_id"]
    assert [e["status"] for e in order["timeline"]] == ["pending_payment"]


def test_retentions_for_persona_fisica_go_in_marketplace_fee(client, user, mp, monkeypatch):
    fiscal = {"person_type": "fisica", "rfc": "GODE561231GR8", "legal_name": "ELENA GOMEZ DIAZ", "regimen_fiscal": "626",
              "postal_code": "06700"}
    seller = _make_seller(client, fiscal=fiscal)
    product = _product(client, seller, price="488.80")
    order = _buy(client, user, [(product, 1)])
    # base sin IVA 421.38; ISR 2.5 % = 10.53; IVA cobrado 67.42 -> 50 % = 33.71; comisión 48.88
    o = _order(order["id"])
    assert (o.fee_amount, o.isr_retenido, o.iva_retenido) == (Decimal("48.88"), Decimal("10.53"), Decimal("33.71"))
    assert o.net_amount == Decimal("395.68")
    assert mp["preferences"][-1]["marketplace_fee"] == Decimal("93.12")
    # Persona moral: LIF 2026 art. 25 fr. VI y IX también la incluye (RETENCION_PERSONAS_MORALES=true por defecto)
    assert settings.retencion_personas_morales is True
    db = _db()
    try:
        refuge = db.query(Refuge).filter(Refuge.id == seller["refuge_id"]).first()
        refuge.fiscal_profile.person_type = "moral"
        assert payment_flow.compute_split(Decimal("488.80"), refuge)["marketplace_fee"] == Decimal("93.12")
        monkeypatch.setattr(settings, "retencion_personas_morales", False)  # si el contador decide que no aplica
        assert payment_flow.compute_split(Decimal("488.80"), refuge)["marketplace_fee"] == Decimal("48.88")
    finally:
        db.rollback()
        db.close()


def test_unconnected_refuge_not_purchasable(client, user, monkeypatch, mp):
    seller = _make_seller(client, connected=False)
    product = _product(client, seller)
    assert client.get(f"/products/{product['id']}").json()["seller_payments_ready"] is False
    r = client.post("/orders", headers=user["h"], json=_order_body([(product, 1)]))
    assert r.status_code == 409 and r.json()["detail"] == "Este refugio aún no activa cobros."
    assert _stock(product["id"]) == 10
    monkeypatch.setattr(settings, "donations_fallback_to_platform_account", False)
    d = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 100})
    assert d.status_code == 409 and d.json()["detail"] == "Este refugio aún no activa cobros."
    # Con el respaldo activo se cobra con la cuenta de la plataforma (flujo anterior, sin token del refugio)
    monkeypatch.setattr(settings, "donations_fallback_to_platform_account", True)
    d = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 100})
    assert d.status_code == 201 and "access_token" not in mp["preferences"][-1]
    # No se puede donar al refugio propio (donativos-16)
    own = client.post("/payments/donations", headers=seller["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 50})
    assert own.status_code == 400


def test_donation_split_fee(client, user, monkeypatch, mp):
    seller = _make_seller(client)
    monkeypatch.setattr(settings, "mercadopago_donation_fee_percent", 5.0)
    r = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 250})
    assert r.status_code == 201, r.text
    pref = mp["preferences"][-1]
    assert pref["access_token"] == seller["seller_token"] and pref["marketplace_fee"] == Decimal("12.50")
    db = _db()
    try:
        d = db.query(Donation).filter(Donation.id == r.json()["donation_id"]).first()
        assert d.payment_mode == "split" and d.fee_amount == Decimal("12.50") and d.net_amount == Decimal("237.50")
        assert d.collector_id == seller["mp_user_id"]
    finally:
        db.close()


def test_webhook_falls_back_to_seller_token(client, user, monkeypatch, mp):
    seller = _make_seller(client)
    product = _product(client, seller, price=120)
    order = _buy(client, user, [(product, 1)])
    payment = _mp_payment(f"order:{order['id']}", 120, collector=seller["mp_user_id"])
    seen = []

    def get_payment(pid, access_token=None):
        seen.append(access_token)
        return payment if access_token == seller["seller_token"] else None  # la plataforma no lo ve (split)

    monkeypatch.setattr(payments, "get_payment", get_payment)
    db = _db()
    try:
        assert payment_flow.process_payment(db, str(payment["id"]), ref_hint=f"order-{order['id']}") == "order:paid"
        # Pista por user_id del vendedor (cuerpo del aviso) también sirve
        assert payment_flow.process_payment(db, str(payment["id"]), mp_user_id=seller["mp_user_id"]) == "order:paid"
    finally:
        db.close()
    assert seen[:2] == [None, seller["seller_token"]]
    # Un pago con nuestra referencia pero cobrado por otra cuenta no se aplica
    other = _buy(client, user, [(product, 1)])
    forged = _mp_payment(f"order:{other['id']}", 120, collector=999)
    monkeypatch.setattr(payments, "get_payment", lambda pid, **kw: forged)
    db = _db()
    try:
        assert payment_flow.process_payment(db, str(forged["id"])) == "order_collector_mismatch"
    finally:
        db.close()
    # El webhook pasa las pistas a la tarea
    calls = []
    monkeypatch.setattr(payments_router, "dispatch", lambda *a, **kw: calls.append(a) or "inline")
    pid = str(payment["id"])
    client.post(f"/payments/mercadopago/webhook?ref=order-{order['id']}&data.id={pid}&type=payment",
                json={"type": "payment", "user_id": int(seller["mp_user_id"]), "data": {"id": pid}})
    assert calls[-1] == ("app.tasks.payments.process_mercadopago_payment", pid, f"order-{order['id']}",
                         seller["mp_user_id"])


# --------------------------------------------------------------------------- S2/S4 un refugio y envíos
def test_single_seller_shipping_rules_and_address(client, user):
    seller = _make_seller(client)
    other = _make_seller(client, name="Otro Refugio")
    jalisco = _product(client, seller, shipping_cost="120", ships_nationwide=False, ships_states=["Jal.", "Colima"])
    assert jalisco["ships_states"] == ["Jalisco", "Colima"]
    cheap = _product(client, seller, shipping_cost="50")
    foreign = _product(client, other)
    r = client.post("/orders", headers=user["h"], json=_order_body([(cheap, 1), (foreign, 1)]))
    assert r.status_code == 400 and "varios refugios" in r.json()["detail"]
    r = client.post("/orders", headers=user["h"], json=_order_body([(jalisco, 1)]))
    assert r.status_code == 400 and "no se envía a Ciudad de México" in r.json()["detail"]
    r = client.post("/orders", headers=user["h"], json={"items": [{"product_id": jalisco["id"], "quantity": 1}],
                                                        "shipping_address": "Calle 1, Guadalajara", **CONSENT})
    assert r.status_code == 400 and "estado de entrega" in r.json()["detail"]
    missing = client.post("/orders", headers=user["h"], json=_order_body([(cheap, 1)], shipping_postal_code=None,
                                                                         shipping_ext_number=None))
    assert missing.status_code == 400 and "número exterior" in missing.json()["detail"]
    assert client.post("/orders", headers=user["h"], json=_order_body([(cheap, 1)], shipping_postal_code="123")).status_code == 400
    assert client.post("/orders", headers=user["h"], json=_order_body([(cheap, 1)], shipping_state="Narnia")).status_code == 400
    # Dirección anidada ("shipping": {...}) también se acepta
    nested = {"items": [{"product_id": jalisco["id"], "quantity": 1}, {"product_id": cheap["id"], "quantity": 2}],
              "shipping": {k.replace("shipping_", ""): v for k, v in ADDRESS.items()} | {"state": "Jalisco"}, **CONSENT}
    r = client.post("/orders", headers=user["h"], json=nested)
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["shipping_total"]) == Decimal("120.00")  # el mayor, una sola vez
    assert Decimal(r.json()["total"]) == Decimal("420.00")  # 100 + 2 x 100 + 120
    assert client.post("/products", headers=seller["h"], json={"name": "x", "price": 10, "ships_nationwide": False}).status_code == 422
    r = client.patch(f"/products/{cheap['id']}", headers=seller["h"], json={"ships_nationwide": False})
    assert r.status_code == 400
    r = client.patch(f"/products/{cheap['id']}", headers=seller["h"], json={"ships_nationwide": False,
                                                                           "ships_states": ["nl"], "handling_days": 5})
    assert r.status_code == 200 and r.json()["ships_states"] == ["Nuevo León"] and r.json()["handling_days"] == 5


# --------------------------------------------------------------------------- S3 estados, permisos y avisos
def test_status_machine_permissions_timeline_and_notifications(client, user, make_user, emails):
    seller = _make_seller(client)
    product = _product(client, seller, price=80)
    order = _buy(client, user, [(product, 1)])  # desarrollo sin Mercado Pago: pago simulado
    assert order["status"] == "paid" and order["simulated"] is True and order["can_cancel"] is True
    oid = order["id"]
    stranger = _make_seller(client, name="Refugio Ajeno")
    assert client.patch(f"/refuges/me/orders/{oid}", headers=stranger["h"], json={"status": "preparing"}).status_code == 404
    assert client.patch(f"/refuges/me/orders/{oid}", headers=user["h"], json={"status": "preparing"}).status_code == 404
    assert client.post(f"/orders/{oid}/confirm-delivery", headers=user["h"]).status_code == 409
    assert client.patch(f"/refuges/me/orders/{oid}", headers=seller["h"], json={"status": "delivered"}).status_code == 409

    r = client.patch(f"/refuges/me/orders/{oid}", headers=seller["h"], json={"status": "preparing"})
    assert r.status_code == 200 and r.json()["status"] == "preparing"
    r = client.patch(f"/refuges/me/orders/{oid}", headers=seller["h"], json={"status": "shipped"})
    assert r.status_code == 409 and "guía" in r.json()["detail"]  # guía obligatoria
    r = client.patch(f"/refuges/me/orders/{oid}", headers=seller["h"], json={
        "status": "shipped", "carrier": "Estafeta", "tracking_number": "EST987", "tracking_url": "https://rastreo.mx/EST987"})
    assert r.status_code == 200 and r.json()["tracking_url"] == "https://rastreo.mx/EST987"
    other = make_user("Curioso")
    assert client.post(f"/orders/{oid}/cancel", headers=other["h"]).status_code == 404
    assert client.post(f"/orders/{oid}/cancel", headers=user["h"]).status_code == 409  # ya salió
    r = client.post(f"/orders/{oid}/confirm-delivery", headers=user["h"])
    assert r.status_code == 200 and r.json()["status"] == "delivered" and r.json()["can_return"] is True
    assert r.json()["revocation_until"] and r.json()["claim_until"]

    detail = client.get(f"/orders/{oid}", headers=user["h"]).json()
    assert [e["status"] for e in detail["timeline"]] == ["pending_payment", "paid", "preparing", "shipped", "delivered"]
    assert all(e["at"] for e in detail["timeline"]) and detail["status_label"] == "Entregado"
    assert client.get(f"/orders/{oid}", headers=other["h"]).status_code == 403
    buyer_id = _user_id(user["email"])
    for kind in ("order_paid", "order_preparing", "order_shipped", "order_delivered"):
        assert len(_notifs(buyer_id, kind, oid)) == 1, kind
    buyer_mails = [a for t, a in emails if t == "app.tasks.notifications.send_notification_email" and a[0] == user["email"]]
    assert len(buyer_mails) >= 4  # un correo por cada cambio de estado
    listing = client.get("/refuges/me/orders", headers=seller["h"], params={"status": "delivered"}).json()
    assert [o["id"] for o in listing] == [oid] and listing[0]["shipping_phone"] == "5512345678"


def test_buyer_cancel_paid_order_refunds_with_seller_token(client, user, monkeypatch, mp):
    seller = _make_seller(client)
    product = _product(client, seller, price=150, stock=3)
    pending = _buy(client, user, [(product, 1)])
    r = client.post(f"/orders/{pending['id']}/cancel", headers=user["h"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and not mp["refunds"]
    assert _stock(product["id"]) == 3

    order = _buy(client, user, [(product, 2)])
    payment = _pay(monkeypatch, order, collector=seller["mp_user_id"])
    assert _stock(product["id"]) == 1
    r = client.post(f"/orders/{order['id']}/cancel", headers=user["h"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["refund_status"] == "approved"
    assert mp["refunds"][-1] == {"payment_id": str(payment["id"]), "access_token": seller["seller_token"]}
    assert _stock(product["id"]) == 3
    o = _order(order["id"])
    assert o.cancel_reason == "buyer" and o.refunded_at and o.refund_amount == Decimal("300.00")
    assert _notifs(seller["user_id"], "order_cancelled", order["id"])
    # El aviso "refunded" de Mercado Pago por ese mismo reembolso no cambia nada
    refunded = dict(payment, status="refunded")
    monkeypatch.setattr(payments, "get_payment", lambda pid, **kw: refunded)
    db = _db()
    try:
        assert payment_flow.process_payment(db, str(payment["id"])) == "order:cancelled"
    finally:
        db.close()


def test_cancel_refund_racing_with_webhook_is_recorded_once(client, user, monkeypatch, mp):
    """El aviso «refunded» de Mercado Pago llega MIENTRAS la cancelación espera la respuesta del reembolso.

    Antes: el webhook registraba el reembolso y la cancelación lo registraba otra vez (refund_amount al doble,
    dos filas en order_refunds y estados de cuenta / CFDI con el doble descontado).
    """
    seller = _make_seller(client)
    product = _product(client, seller, price=150, stock=3)
    order = _buy(client, user, [(product, 2)])
    payment = _pay(monkeypatch, order, collector=seller["mp_user_id"])
    refunded = dict(payment, status="refunded")

    def refund_and_webhook_arrives(payment_id, **kwargs):
        kwargs.pop("idempotency_key", None)
        mp["refunds"].append({"payment_id": payment_id, **kwargs})
        monkeypatch.setattr(payments, "get_payment", lambda pid, **kw: refunded)
        other = _db()  # el webhook corre en otra conexión mientras esperamos a Mercado Pago
        try:
            payment_flow.process_payment(other, str(payment["id"]))
        finally:
            other.close()
        return {"id": 8_123_456, "status": "approved"}

    monkeypatch.setattr(payments, "refund_payment", refund_and_webhook_arrives)
    r = client.post(f"/orders/{order['id']}/cancel", headers=user["h"])
    assert r.status_code == 200, r.text
    o = _order(order["id"])
    assert o.refund_amount == Decimal("300.00") and o.refunded_at
    db = _db()
    try:
        rows = db.query(OrderRefund).filter(OrderRefund.order_id == order["id"]).all()
        assert len(rows) == 1 and rows[0].amount == Decimal("300.00")
    finally:
        db.close()
    assert _stock(product["id"]) == 3  # el inventario vuelve una sola vez


# --------------------------------------------------------------------------- S3 devoluciones
def test_return_window_uses_business_days():
    # Entregado el viernes 16-10-2026 (CDMX): 5 días hábiles -> viernes 23
    delivered = datetime.datetime(2026, 10, 16, 20, 0)  # 14:00 en la Ciudad de México
    assert order_flow.return_deadline(delivered, "arrepentimiento") == datetime.datetime(2026, 10, 24, 5, 59, 59)
    # Jueves 12-11-2026: el lunes 16 es día de descanso (tercer lunes de noviembre) -> viernes 20
    deadline = order_flow.return_deadline(datetime.datetime(2026, 11, 12, 18, 0), "otro")
    assert deadline.date() == datetime.date(2026, 11, 21)
    assert datetime.date(2026, 11, 16) in order_flow.mx_holidays(2026)
    assert datetime.date(2030, 10, 1) in order_flow.mx_holidays(2030)
    # Defectuoso / no corresponde / no llegó: 60 días naturales (LFPC art. 93)
    assert order_flow.return_deadline(delivered, "defectuoso") == delivered + datetime.timedelta(days=60)


def _delivered_order(client, user, seller, product, quantity=1, days_ago=1):
    order = _buy(client, user, [(product, quantity)])
    oid = order["id"]
    client.patch(f"/refuges/me/orders/{oid}", headers=seller["h"],
                 json={"status": "shipped", "carrier": "DHL", "tracking_number": f"DHL{oid}"})
    r = client.patch(f"/refuges/me/orders/{oid}", headers=seller["h"], json={"status": "delivered"})
    assert r.status_code == 200, r.text
    _update_order(oid, delivered_at=datetime.datetime.utcnow() - datetime.timedelta(days=days_ago))
    return oid


def test_return_window_enforced(client, user):
    seller = _make_seller(client)
    product = _product(client, seller)
    oid = _delivered_order(client, user, seller, product, days_ago=10)
    r = client.post(f"/orders/{oid}/return", headers=user["h"], json={"reason": "arrepentimiento"})
    assert r.status_code == 409 and "días hábiles" in r.json()["detail"]
    r = client.post(f"/orders/{oid}/return", headers=user["h"], json={"reason": "defectuoso", "details": "Llegó roto"})
    assert r.status_code == 200 and r.json()["status"] == "return_requested"
    assert _notifs(seller["user_id"], "order_return_requested", oid)
    old = _delivered_order(client, user, seller, product, days_ago=61)
    assert client.post(f"/orders/{old}/return", headers=user["h"], json={"reason": "no_corresponde"}).status_code == 409
    assert client.post(f"/orders/{old}/return", headers=user["h"], json={"reason": "capricho"}).status_code == 422


def test_return_approval_triggers_refund_and_rejection_needs_note(client, user, monkeypatch, mp):
    seller = _make_seller(client)
    product = _product(client, seller, price=200, stock=5)
    order = _buy(client, user, [(product, 1)])
    payment = _pay(monkeypatch, order, collector=seller["mp_user_id"])
    oid = order["id"]
    client.patch(f"/refuges/me/orders/{oid}", headers=seller["h"], json={"status": "shipped", "carrier": "DHL",
                                                                         "tracking_number": "DHL1"})
    client.post(f"/orders/{oid}/confirm-delivery", headers=user["h"])
    r = client.post(f"/orders/{oid}/return", headers=user["h"], json={"reason": "arrepentimiento", "details": "No le quedó"})
    assert r.status_code == 200
    assert client.post(f"/refuges/me/orders/{oid}/return-decision", headers=seller["h"],
                       json={"approve": False, "note": "no"}).status_code == 409  # negativa sin motivo
    assert client.post(f"/refuges/me/orders/{oid}/return-decision", headers=user["h"],
                       json={"approve": True}).status_code == 404
    r = client.post(f"/refuges/me/orders/{oid}/return-decision", headers=seller["h"], json={"approve": True, "note": "Ok"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "refunded" and r.json()["refund_status"] == "approved"
    assert mp["refunds"][-1] == {"payment_id": str(payment["id"]), "access_token": seller["seller_token"]}
    timeline = [e["status"] for e in client.get(f"/orders/{oid}", headers=user["h"]).json()["timeline"]]
    assert timeline[-3:] == ["return_requested", "return_approved", "refunded"]
    buyer_id = _user_id(user["email"])
    assert _notifs(buyer_id, "order_return_approved", oid) and _notifs(buyer_id, "order_refunded", oid)

    # Rechazo con motivo
    second = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, second)
    client.patch(f"/refuges/me/orders/{second['id']}", headers=seller["h"],
                 json={"status": "shipped", "carrier": "DHL", "tracking_number": "DHL2"})
    client.post(f"/orders/{second['id']}/confirm-delivery", headers=user["h"])
    client.post(f"/orders/{second['id']}/return", headers=user["h"], json={"reason": "otro"})
    r = client.post(f"/refuges/me/orders/{second['id']}/return-decision", headers=seller["h"],
                    json={"approve": False, "note": "El producto se usó y tiene mordidas."})
    assert r.status_code == 200 and r.json()["status"] == "return_rejected"
    assert _notifs(buyer_id, "order_return_rejected", second["id"])

    # Si Mercado Pago falla al aprobar, queda aprobada con el reembolso pendiente para admins
    third = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, third)
    client.patch(f"/refuges/me/orders/{third['id']}", headers=seller["h"],
                 json={"status": "shipped", "carrier": "DHL", "tracking_number": "DHL3"})
    client.post(f"/orders/{third['id']}/confirm-delivery", headers=user["h"])
    client.post(f"/orders/{third['id']}/return", headers=user["h"], json={"reason": "defectuoso"})

    def failing(*a, **kw):
        raise payments.PaymentError("Mercado Pago no pudo reembolsar el pago.")

    monkeypatch.setattr(payments, "refund_payment", failing)
    r = client.post(f"/refuges/me/orders/{third['id']}/return-decision", headers=seller["h"], json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "return_approved" and r.json()["refund_status"] == "error"


def test_admin_partial_refund(client, user, admin, monkeypatch, mp):
    seller = _make_seller(client)
    product = _product(client, seller, price=300)
    order = _buy(client, user, [(product, 1)])
    payment = _pay(monkeypatch, order)
    oid = order["id"]
    assert client.post(f"/admin/orders/{oid}/refund", headers=user["h"], json={"amount": 50}).status_code == 403
    assert client.post(f"/admin/orders/{oid}/refund", headers=admin["h"], json={"amount": 301}).status_code == 400
    stock = _stock(product["id"])
    r = client.post(f"/admin/orders/{oid}/refund", headers=admin["h"], json={"amount": 50})
    assert r.status_code == 200, r.text
    # Parcial: el pedido sigue su curso (mismo estado e inventario) y se registra el reembolso
    assert r.json()["status"] == "paid" and Decimal(r.json()["refund_amount"]) == Decimal("50.00")
    assert _stock(product["id"]) == stock and not r.json()["refunded_at"]
    assert mp["refunds"][-1] == {"payment_id": str(payment["id"]), "access_token": seller["seller_token"],
                                 "amount": Decimal("50.00")}
    assert mp["refund_keys"][-1] == f"guauwoow-orders-{oid}-refund-0-5000"
    assert r.json()["refund_id"]
    assert r.json()["timeline"][-1]["status"] == "partial_refund"
    assert _notifs(_user_id(user["email"]), "order_partial_refund", oid)
    refuge_note = _notifs(seller["user_id"], "order_partial_refund", oid)
    assert refuge_note and "No lo envíes" not in refuge_note[0].body
    db = _db()
    try:
        log = db.query(AdminAuditLog).filter(AdminAuditLog.target_type == "order", AdminAuditLog.target_id == oid,
                                             AdminAuditLog.action == "order_refund").first()
        assert log and log.details["amount"] == "50.00"
    finally:
        db.close()
    # Más parciales hasta el total (quedan 250); el que completa el total cierra el pedido
    over = client.post(f"/admin/orders/{oid}/refund", headers=admin["h"], json={"amount": 251})
    assert over.status_code == 400 and "$250.00" in over.json()["detail"]
    assert client.post(f"/admin/orders/{oid}/refund", headers=admin["h"], json={"amount": 100}).json()["status"] == "paid"
    r = client.post(f"/admin/orders/{oid}/refund", headers=admin["h"])
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    assert Decimal(r.json()["refund_amount"]) == Decimal("300.00") and _stock(product["id"]) == stock + 1
    assert mp["refunds"][-1]["amount"] == Decimal("150.00")  # lo que faltaba, no "total" (ya hubo parciales)
    db = _db()
    try:
        rows = db.query(OrderRefund).filter(OrderRefund.order_id == oid).order_by(OrderRefund.id).all()
        assert [r.amount for r in rows] == [Decimal("50.00"), Decimal("100.00"), Decimal("150.00")]
        assert sum(r.fee_reversed for r in rows) == Decimal("30.00") and [r.is_full for r in rows] == [False, False, True]
    finally:
        db.close()
    assert client.post(f"/admin/orders/{oid}/refund", headers=admin["h"]).status_code == 409


def test_admin_refund_is_idempotent_after_timeout_and_double_click(client, user, admin, monkeypatch, mp):
    """Mercado Pago aplica el reembolso pero la respuesta no llega (timeout) y luego el admin pulsa dos veces.

    Mercado Pago (como el real) responde el MISMO reembolso para la misma X-Idempotency-Key. Antes cada intento
    mandaba una clave aleatoria y el comprador recibía su dinero dos o tres veces.
    """
    seller = _make_seller(client)
    product = _product(client, seller, price=300)
    order = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, order)
    oid = order["id"]
    at_mp = {}          # clave de idempotencia -> reembolso hecho en Mercado Pago
    lose_response = {"left": 1}

    def mp_refund(payment_id, **kwargs):
        key = kwargs["idempotency_key"]
        if key not in at_mp:
            at_mp[key] = {"id": 7_000_000 + len(at_mp), "status": "approved", "amount": kwargs.get("amount")}
        if lose_response["left"]:
            lose_response["left"] -= 1
            raise payments.PaymentError("No pudimos conectar con Mercado Pago. Inténtalo de nuevo.")
        return at_mp[key]

    monkeypatch.setattr(payments, "refund_payment", mp_refund)
    first = client.post(f"/admin/orders/{oid}/refund", headers=admin["h"], json={"amount": 100})
    assert first.status_code == 502  # el admin ve el error y reintenta
    retry = client.post(f"/admin/orders/{oid}/refund", headers=admin["h"], json={"amount": 100})
    assert retry.status_code == 200, retry.text
    assert Decimal(retry.json()["refund_amount"]) == Decimal("100.00")
    assert sum(Decimal(str(r["amount"])) for r in at_mp.values()) == Decimal("100.00")  # se devolvió UNA vez
    # Doble clic: el segundo clic llega con lo ya reembolsado actualizado => es OTRO reembolso legítimo de 100.
    # Lo que no debe pasar es que el mismo reembolso de Mercado Pago se registre dos veces en la base.
    db = _db()
    try:
        order_row = db.query(Order).filter(Order.id == oid).first()
        rows = db.query(OrderRefund).filter(OrderRefund.order_id == oid).all()
        assert len(rows) == 1 and rows[0].provider_refund_id == str(at_mp[next(iter(at_mp))]["id"])
        same = {"id": rows[0].provider_refund_id, "status": "approved"}
        from app.services import payment_flow as pf

        assert pf.record_refund(db, order_row, Decimal("100.00"), same, by="admin").id == rows[0].id
        assert order_row.refund_amount == Decimal("100.00")
    finally:
        db.rollback()
        db.close()


def test_auto_complete_after_delivery(client, user):
    seller = _make_seller(client)
    product = _product(client, seller)
    old = _delivered_order(client, user, seller, product, days_ago=11)
    recent = _delivered_order(client, user, seller, product, days_ago=2)
    db = _db()
    try:
        assert order_flow.auto_complete_orders(db) >= 1
    finally:
        db.close()
    assert _order(old).status == "completed" and _order(old).completed_at
    assert _order(recent).status == "delivered"
    assert _notifs(_user_id(user["email"]), "order_completed", old)
    # Completado todavía admite reclamación por defecto (60 días)
    r = client.post(f"/orders/{old}/return", headers=user["h"], json={"reason": "defectuoso"})
    assert r.status_code == 200


# --------------------------------------------------------------------------- S5 perfil fiscal y facturas
def test_fiscal_profile_validation(client):
    seller = _make_seller(client)
    h = seller["h"]
    assert client.get("/refuges/me/fiscal", headers=h).json() is None
    assert client.patch("/refuges/me/fiscal", headers=h, json={"rfc": "GODE561231GR8"}).status_code == 400
    base = {"person_type": "fisica", "rfc": "GODE561231GR8", "legal_name": "Elena Gómez Díaz",
            "regimen_fiscal": "626", "postal_code": "06700"}
    assert client.patch("/refuges/me/fiscal", headers=h, json={**base, "rfc": "GOD561231GR8"}).status_code == 400
    assert client.patch("/refuges/me/fiscal", headers=h, json={**base, "regimen_fiscal": "601"}).status_code == 400
    assert client.patch("/refuges/me/fiscal", headers=h, json={**base, "is_donataria": True}).status_code == 400
    assert client.patch("/refuges/me/fiscal", headers=h, json={**base, "csf_document_id": "nope.pdf"}).status_code == 400
    assert client.patch("/refuges/me/fiscal", headers=h, json={**base, "postal_code": "6700"}).status_code == 422
    doc = client.post("/upload/document", headers=h, files={"file": ("csf.pdf", b"%PDF-1.4\n%prueba\n", "application/pdf")})
    assert doc.status_code == 200, doc.text
    r = client.patch("/refuges/me/fiscal", headers=h, json={**base, "csf_document_id": doc.json()["id"]})
    assert r.status_code == 200 and r.json()["legal_name"] == "ELENA GÓMEZ DÍAZ" and r.json()["csf_document_id"]
    moral = {"person_type": "moral", "rfc": "pfi010101ab2", "regimen_fiscal": "603", "is_donataria": True}
    r = client.patch("/refuges/me/fiscal", headers=h, json=moral)
    assert r.status_code == 200 and r.json()["rfc"] == "PFI010101AB2" and r.json()["is_donataria"] is True
    assert client.get("/refuges/me/fiscal", headers=h).json()["person_type"] == "moral"


def _cfdi_xml(uuid_, emisor, receptor, total, doctype=False):
    head = '<?xml version="1.0" encoding="UTF-8"?>' + ('<!DOCTYPE x [<!ENTITY a "b">]>' if doctype else "")
    return (head + f'<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" '
            f'xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" Version="4.0" Total="{total}">'
            f'<cfdi:Emisor Rfc="{emisor}" Nombre="REFUGIO" RegimenFiscal="603"/>'
            f'<cfdi:Receptor Rfc="{receptor}" Nombre="COMPRADOR" UsoCFDI="G03"/>'
            f'<cfdi:Complemento><tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid_}"/></cfdi:Complemento>'
            '</cfdi:Comprobante>').encode()


def test_invoice_request_issue_and_private_download(client, user, make_user):
    fiscal = {"person_type": "moral", "rfc": "PFI010101AB2", "legal_name": "PATITAS AC", "regimen_fiscal": "603",
              "postal_code": "06700"}
    seller = _make_seller(client, fiscal=fiscal)
    product = _product(client, seller, price="116")
    order = _buy(client, user, [(product, 1)])
    oid = order["id"]
    req = {"rfc": "MOPA800101AB3", "legal_name": "Ana Morales Pérez", "regimen_fiscal": "605", "postal_code": "03100",
           "uso_cfdi": "G03", "email": "ana@ejemplo.mx"}
    assert client.post(f"/orders/{oid}/invoice-request", headers=user["h"], json={**req, "regimen_fiscal": "601"}).status_code == 422
    assert client.post(f"/orders/{oid}/invoice-request", headers=user["h"], json={**req, "uso_cfdi": "Z99"}).status_code == 422
    r = client.post(f"/orders/{oid}/invoice-request", headers=user["h"], json=req)
    assert r.status_code == 201 and r.json()["status"] == "requested" and r.json()["legal_name"] == "ANA MORALES PÉREZ"
    assert client.post(f"/orders/{oid}/invoice-request", headers=user["h"], json=req).status_code == 409
    assert _notifs(seller["user_id"], "invoice_requested", oid)
    queue = client.get("/refuges/me/invoice-requests", headers=seller["h"]).json()
    assert [i["order_id"] for i in queue] == [oid]
    assert client.get(f"/orders/{oid}", headers=user["h"]).json()["invoice_status"] == "requested"

    good_uuid = str(uuid.uuid4()).upper()
    bad = client.post("/upload/cfdi-xml", headers=seller["h"],
                      files={"file": ("f.xml", _cfdi_xml(good_uuid, "PFI010101AB2", "MOPA800101AB3", "116.00", doctype=True),
                                      "application/xml")})
    assert bad.status_code == 400
    assert client.post("/upload/cfdi-xml", headers=user["h"],
                       files={"file": ("f.xml", b"<a/>", "application/xml")}).status_code == 403
    xml = client.post("/upload/cfdi-xml", headers=seller["h"],
                      files={"file": ("f.xml", _cfdi_xml(good_uuid, "PFI010101AB2", "MOPA800101AB3", "116.00"),
                                      "application/xml")})
    assert xml.status_code == 200 and xml.json()["uuid"] == good_uuid
    wrong_rfc = client.post("/upload/cfdi-xml", headers=seller["h"],
                            files={"file": ("f.xml", _cfdi_xml(good_uuid, "AAA010101AAA", "MOPA800101AB3", "116.00"),
                                            "application/xml")}).json()["id"]
    pdf = client.post("/upload/document", headers=seller["h"], files={"file": ("f.pdf", b"%PDF-1.4\n%f\n", "application/pdf")})
    issue = {"status": "issued", "xml_document_id": xml.json()["id"], "pdf_document_id": pdf.json()["id"]}
    assert client.post(f"/refuges/me/orders/{oid}/invoice", headers=seller["h"],
                       json={**issue, "uuid": str(uuid.uuid4())}).status_code == 400  # UUID distinto al del XML
    assert client.post(f"/refuges/me/orders/{oid}/invoice", headers=seller["h"],
                       json={**issue, "xml_document_id": wrong_rfc}).status_code == 400  # RFC emisor ajeno
    assert client.post(f"/refuges/me/orders/{oid}/invoice", headers=user["h"], json=issue).status_code == 404
    r = client.post(f"/refuges/me/orders/{oid}/invoice", headers=seller["h"], json=issue)
    assert r.status_code == 200 and r.json()["status"] == "issued" and r.json()["uuid"] == good_uuid
    assert _notifs(_user_id(user["email"]), "invoice_issued", oid)

    inv = client.get(f"/orders/{oid}/invoice", headers=user["h"]).json()
    assert inv["xml_url"] == f"/orders/{oid}/invoice/xml" and inv["pdf_url"] == f"/orders/{oid}/invoice/pdf"
    dl = client.get(inv["xml_url"], headers=user["h"])
    assert dl.status_code == 200 and good_uuid.encode() in dl.content and "attachment" in dl.headers["content-disposition"]
    assert client.get(inv["pdf_url"], headers=seller["h"]).status_code == 200
    assert client.get(inv["xml_url"], headers=make_user("Mirón")["h"]).status_code == 404
    assert client.get(inv["xml_url"]).status_code == 401

    # Rechazo con motivo y nueva solicitud
    second = _buy(client, user, [(product, 1)])
    client.post(f"/orders/{second['id']}/invoice-request", headers=user["h"], json=req)
    assert client.post(f"/refuges/me/orders/{second['id']}/invoice", headers=seller["h"],
                       json={"status": "rejected"}).status_code == 400
    r = client.post(f"/refuges/me/orders/{second['id']}/invoice", headers=seller["h"],
                    json={"status": "rejected", "note": "El RFC no está en la lista del SAT."})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.post(f"/orders/{second['id']}/invoice-request", headers=user["h"], json=req).status_code == 201
    # Pedidos sin pagar no se facturan
    db = _db()
    try:
        pending = db.query(Order).filter(Order.id == second["id"]).first()
        pending.status = "pending_payment"
        db.commit()
    finally:
        db.close()
    third = _buy(client, user, [(product, 1)])
    _update_order(third["id"], status="pending_payment")
    assert client.post(f"/orders/{third['id']}/invoice-request", headers=user["h"], json=req).status_code == 409


# --------------------------------------------------------------------------- S5 CFDI de la plataforma
def _period():
    return f"{random.randint(2060, 2099)}-{random.randint(1, 12):02d}"


def _in_period(period):
    start, _ = statements.period_bounds(period)
    return start + datetime.timedelta(days=10, hours=6)


def test_cfdi_pending_without_pac_and_facturama_payload(client, user, admin, monkeypatch):
    fiscal = {"person_type": "fisica", "rfc": "GODE561231GR8", "legal_name": "ELENA GOMEZ DIAZ", "regimen_fiscal": "626",
              "postal_code": "06700"}
    seller = _make_seller(client, fiscal=fiscal)
    product = _product(client, seller, price="1160")
    order = _buy(client, user, [(product, 1)])
    period = _period()
    _update_order(order["id"], paid_at=_in_period(period))
    monkeypatch.setattr(settings, "pac_provider", "")
    db = _db()
    try:
        result = invoicing.generate_period_cfdis(db, period)
        rows = {r.kind: r for r in db.query(Cfdi).filter(Cfdi.period == period, Cfdi.refuge_id == seller["refuge_id"])}
        assert result["pending_pac"] >= 2 and set(rows) == {"comision", "retencion"}
        com, ret = rows["comision"], rows["retencion"]
        # Comisión 10 % de 1160 = 116.00 con IVA incluido -> 100.00 + 16.00
        assert (com.status, com.subtotal, com.iva, com.total) == ("pending_pac", Decimal("100.00"), Decimal("16.00"),
                                                                Decimal("116.00"))
        # Retenciones: base 1000.00 -> ISR 25.00; IVA cobrado 160.00 -> 80.00
        assert (ret.isr_retenido, ret.iva_retenido, ret.status) == (Decimal("25.00"), Decimal("80.00"), "pending_pac")
        com_id, ret_id = com.id, ret.id
    finally:
        db.close()
    r = client.post(f"/admin/cfdi/{com_id}/retry", headers=admin["h"])
    assert r.status_code == 200 and r.json()["status"] == "pending_pac" and "PAC" in r.json()["error"]
    listing = client.get("/admin/cfdi", headers=admin["h"], params={"period": period, "status": "pending_pac"}).json()
    assert {c["kind"] for c in listing if c["refuge_id"] == seller["refuge_id"]} == {"comision", "retencion"}
    assert client.get("/admin/cfdi", headers=user["h"]).status_code == 403
    assert client.get(f"/admin/cfdi/{com_id}/xml", headers=admin["h"]).status_code == 404

    # Con Facturama (HTTP simulado): forma del JSON y archivos guardados
    calls = []

    class Resp:
        def __init__(self, data, status=200):
            self._data, self.status_code, self.content, self.text = data, status, b"x", ""

        def json(self):
            return self._data

    def fake_request(method, url, auth=None, timeout=None, json=None):
        calls.append({"method": method, "url": url, "auth": auth, "json": json, "timeout": timeout})
        if method == "POST":
            return Resp({"Id": "fact-1", "Complement": {"TaxStamp": {"Uuid": "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"}}})
        content = b"<cfdi/>" if "/xml/" in url else b"%PDF-1.4"
        return Resp({"Content": base64.b64encode(content).decode(), "ContentEncoding": "base64"})

    monkeypatch.setattr(invoicing.requests, "request", fake_request)
    monkeypatch.setattr(settings, "emisor_cp", "06600")
    adapter = invoicing.FacturamaAdapter("usuario", "clave", sandbox=True)
    db = _db()
    try:
        row = db.query(Cfdi).filter(Cfdi.id == com_id).first()
        invoicing.issue_cfdi_row(db, row, adapter=adapter)
        assert row.status == "issued" and row.uuid == "AAAAAAAA-1111-2222-3333-BBBBBBBBBBBB"
    finally:
        db.close()
    post = calls[0]
    assert post["url"] == "https://apisandbox.facturama.mx/3/cfdis" and post["auth"] == ("usuario", "clave")
    body = post["json"]
    assert body["CfdiType"] == "I" and body["PaymentMethod"] == "PUE" and body["ExpeditionPlace"] == "06600"
    assert body["Receiver"] == {"Rfc": "GODE561231GR8", "Name": "ELENA GOMEZ DIAZ", "CfdiUse": "G03",
                                "FiscalRegime": "626", "TaxZipCode": "06700"}
    item = body["Items"][0]
    assert item["Subtotal"] == 100.0 and item["Total"] == 116.0 and item["TaxObject"] == "02"
    assert item["Taxes"] == [{"Name": "IVA", "Rate": 0.16, "Base": 100.0, "Total": 16.0, "IsRetention": False}]
    assert "_kind" not in body and post["timeout"]
    assert [c["url"] for c in calls[1:]] == ["https://apisandbox.facturama.mx/cfdi/xml/issued/fact-1",
                                             "https://apisandbox.facturama.mx/cfdi/pdf/issued/fact-1"]
    dl = client.get(f"/admin/cfdi/{com_id}/xml", headers=admin["h"])
    assert dl.status_code == 200 and dl.content == b"<cfdi/>"
    assert client.post(f"/admin/cfdi/{com_id}/retry", headers=admin["h"]).status_code == 409

    # Facturama timbra el CFDI de retenciones pero la descarga del XML falla (timeout / 5xx). Antes el registro quedaba
    # "error" SIN el UUID y el reintento timbraba un segundo CFDI ante el SAT por el mismo concepto.
    posts = []

    def stamp_then_download_fails(method, url, auth=None, timeout=None, json=None):
        if method == "POST":
            posts.append(url)
            return Resp({"Id": "ret-1", "Complement": {"TaxStamp": {"Uuid": "cccccccc-1111-2222-3333-dddddddddddd"}}})
        return Resp({"Message": "Servicio no disponible"}, status=503)

    monkeypatch.setattr(invoicing.requests, "request", stamp_then_download_fails)
    db = _db()
    try:
        row = db.query(Cfdi).filter(Cfdi.id == ret_id).first()
        invoicing.issue_cfdi_row(db, row, adapter=adapter)
        assert row.status == "issued" and row.uuid == "CCCCCCCC-1111-2222-3333-DDDDDDDDDDDD"
        assert row.provider_ref == "ret-1" and "NO lo vuelvas a timbrar" in row.error
        invoicing.issue_cfdi_row(db, row, adapter=adapter)  # la tarea programada lo vuelve a intentar
    finally:
        db.close()
    assert len(posts) == 1  # un solo timbrado
    assert client.post(f"/admin/cfdi/{ret_id}/retry", headers=admin["h"]).status_code == 409
    # Un registro que se quedó a mitad del timbrado (el proceso murió) no se reintenta solo ni desde el panel
    db = _db()
    try:
        row = db.query(Cfdi).filter(Cfdi.id == ret_id).first()
        row.status, row.uuid = "stamping", None
        db.commit()
        invoicing.issue_cfdi_row(db, row, adapter=adapter)
        assert row.status == "stamping"
    finally:
        db.close()
    assert len(posts) == 1
    stuck = client.post(f"/admin/cfdi/{ret_id}/retry", headers=admin["h"])
    assert stuck.status_code == 409 and "Facturama" in stuck.json()["detail"]


# --------------------------------------------------------------------------- S6 estados de cuenta
def test_statements_math_and_csv(client, user, make_user, admin):
    seller = _make_seller(client)
    product = _product(client, seller, price="200", shipping_cost="50")
    period = _period()
    a = _buy(client, user, [(product, 1)])  # 250.00, comisión 25.00
    b = _buy(client, user, [(product, 2)])  # 450.00, comisión 45.00
    c = _buy(client, user, [(product, 1)])  # venta del mes que se reembolsa en el mismo mes
    for o in (a, b, c):
        _update_order(o["id"], paid_at=_in_period(period))
    client.post(f"/orders/{c['id']}/cancel", headers=user["h"])
    _move_refunds(c["id"], _in_period(period) + datetime.timedelta(days=1))
    donor = make_user("Donante")
    d = client.post("/payments/donations", headers=donor["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 300})
    assert d.status_code == 201
    db = _db()
    try:
        db.query(Donation).filter(Donation.id == d.json()["donation_id"]).update(
            {Donation.approved_at: _in_period(period), Donation.fee_amount: Decimal("15.00")})
        db.commit()
    finally:
        db.close()
    st = client.get("/refuges/me/statements", headers=seller["h"], params={"period": period})
    assert st.status_code == 200, st.text
    s = st.json()
    # Ventas: las 3 cobradas en el mes (950, envío incluido); el reembolso de c resta en el mismo mes
    assert s["period"] == period and s["orders_count"] == 3
    assert Decimal(str(s["gross"])) == Decimal("950") and Decimal(str(s["shipping"])) == Decimal("150")
    assert Decimal(str(s["refunds_total"])) == Decimal("250") and s["refunds_count"] == 1
    assert Decimal(str(s["platform_fee"])) == Decimal("70") and Decimal(str(s["fee_iva"])) == Decimal("9.66")
    assert Decimal(str(s["net_received"])) == Decimal("630") and Decimal(str(s["net_sales"])) == Decimal("700")
    assert Decimal(str(s["donations_gross"])) == Decimal("300") and Decimal(str(s["donations_fee"])) == Decimal("15")
    assert {o["id"] for o in s["orders"]} == {a["id"], b["id"], c["id"]}
    csv = client.get("/refuges/me/statements/export", headers=seller["h"], params={"period": period})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert f"estado-de-cuenta-{period}.csv" in csv.headers["content-disposition"]
    assert "tipo,pedido,fecha,estado" in csv.text and str(a["id"]) in csv.text and "reembolso total" in csv.text
    assert "Ventas (incluye envío)" in csv.text
    assert client.get("/refuges/me/statements", headers=seller["h"], params={"period": "2026-13"}).status_code == 400
    assert client.get("/refuges/me/statements", headers=user["h"]).status_code == 404
    adm = client.get("/admin/statements", headers=admin["h"], params={"period": period}).json()
    row = next(r for r in adm["refuges"] if r["refuge_id"] == seller["refuge_id"])
    assert row["orders_count"] == 3 and "orders" not in row and Decimal(str(row["refunds_total"])) == Decimal("250")
    assert Decimal(str(adm["totals"]["platform_income"])) >= Decimal("85")
    assert adm["fee_percent"] == settings.mercadopago_marketplace_fee_percent and "donation_fee_percent" in adm
    assert client.get("/admin/statements", headers=user["h"]).status_code == 403


# --------------------------------------------------------------------------- tareas programadas
def test_beat_schedule_has_shop_tasks():
    from app.celery_app import celery_app
    from app.tasks import invoicing as invoicing_tasks
    from app.tasks import payments as payment_tasks

    beat = celery_app.conf.beat_schedule
    assert beat["orders-auto-complete-daily"]["task"] == payment_tasks.auto_complete_orders.name
    assert beat["mercadopago-seller-tokens-weekly"]["task"] == payment_tasks.refresh_seller_tokens.name
    assert beat["cfdi-monthly"]["task"] == invoicing_tasks.issue_monthly_cfdi.name
    assert beat["cfdi-monthly"]["schedule"].day_of_month == {3}


def test_mp_connect_deauthorization_and_weekly_refresh(client, monkeypatch, mp):
    import hashlib
    import hmac

    seller = _make_seller(client)
    body = {"type": "mp-connect", "action": "application.deauthorized", "user_id": int(seller["mp_user_id"])}
    # Sin secreto de firma configurado no se confía en el aviso
    r = client.post("/payments/mercadopago/webhook", json=body)
    assert r.json()["reason"] == "invalid_signature"
    assert client.get(f"/refuges/{seller['refuge_id']}").json()["seller_payments_ready"] is True
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", "firma-pruebas")
    ts, req = "1742505638", str(uuid.uuid4())
    v1 = hmac.new(b"firma-pruebas", f"request-id:{req};ts:{ts};".encode(), hashlib.sha256).hexdigest()
    r = client.post("/payments/mercadopago/webhook", json=body, headers={"x-signature": f"ts={ts},v1={v1}",
                                                                         "x-request-id": req})
    assert r.json() == {"received": True}
    st = client.get("/refuges/me/payments/status", headers=seller["h"]).json()
    assert st["connected"] is False and st["status"] == "disconnected"

    # Tarea semanal: renueva lo que vence en menos de 30 días
    other = _make_seller(client, name="Refugio Por Vencer")
    db = _db()
    try:
        account = db.query(RefugePaymentAccount).filter(RefugePaymentAccount.refuge_id == other["refuge_id"]).first()
        account.expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=10)
        db.commit()

        class Resp:
            status_code = 200
            text = ""

            def json(self):
                return {"access_token": "APP_USR-semanal", "refresh_token": "TG-semanal", "user_id": account.mp_user_id,
                        "expires_in": 15552000}

        monkeypatch.setattr(mercadopago_oauth.requests, "post", lambda *a, **kw: Resp())
        result = mercadopago_oauth.refresh_expiring_accounts(db)
        assert result["refreshed"] >= 1
        db.refresh(account)
        assert mercadopago_oauth.decrypt(account.access_token_enc) == "APP_USR-semanal"
    finally:
        db.close()


def test_return_photos_must_be_uploads(client, user):
    seller = _make_seller(client)
    product = _product(client, seller)
    oid = _delivered_order(client, user, seller, product)
    r = client.post(f"/orders/{oid}/return", headers=user["h"],
                    json={"reason": "defectuoso", "photos": ["https://evil.example.com/x.jpg"]})
    assert r.status_code == 422
