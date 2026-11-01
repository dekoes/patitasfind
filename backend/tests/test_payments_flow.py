"""Pagos: firma del webhook, idempotencia, montos, pagos tardíos, expiración, tienda apagada y envíos del refugio.

Desde Mercado Pago Marketplace (split) la tienda solo vende si el refugio vinculó su cuenta: el refugio de estas
pruebas se crea ya vinculado (tokens falsos) y los dobles de la API aceptan access_token/marketplace_fee.
Un pago vencido ahora deja el pedido "cancelled" (antes "expired"), como pide el contrato S3.
"""
import datetime
import hashlib
import hmac
import random
import threading
import uuid

import pytest
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal
from app.models import AdminAuditLog, Donation, Notification, Order, PaymentEvent, Product, Refuge, User
from app.routers import payments as payments_router
from app.services import mercadopago_oauth, payment_flow, payments
from conftest import _register

SECRET = "secreto-de-pruebas"


# --------------------------------------------------------------------------- utilidades
def _db():
    return SessionLocal()


def _user_id(email: str) -> int:
    db = _db()
    try:
        return db.query(User.id).filter(User.email == email).scalar()
    finally:
        db.close()


def _make_refuge(email: str, connected: bool = True) -> int:
    db = _db()
    try:
        u = db.query(User).filter(User.email == email).first()
        refuge = Refuge(user_id=u.id, name=f"Refugio {uuid.uuid4().hex[:5]}", status="approved")
        db.add(refuge)
        db.flush()
        if connected:  # cuenta de Mercado Pago vinculada por OAuth (tokens de prueba, cifrados)
            mercadopago_oauth.save_tokens(db, refuge.id, {
                "access_token": f"APP_USR-seller-{refuge.id}", "refresh_token": f"TG-{refuge.id}",
                "user_id": random.randint(10 ** 8, 10 ** 9), "public_key": "APP_USR-pk", "expires_in": 15552000})
        db.commit()
        return refuge.id
    finally:
        db.close()


def _product(client, seller, price=100, stock=5) -> dict:
    r = client.post("/products", headers=seller["h"], json={"name": f"Taza {uuid.uuid4().hex[:4]}", "price": price, "stock": stock,
                                                           "category": "promocionales", "warranty_text": "Sin garantía adicional"})
    assert r.status_code == 201, r.text
    return r.json()


def _stock(product_id: int) -> int:
    db = _db()
    try:
        return db.query(Product.stock).filter(Product.id == product_id).scalar()
    finally:
        db.close()


def _order(order_id: int) -> Order:
    db = _db()
    try:
        o = db.query(Order).filter(Order.id == order_id).first()
        db.expunge(o)
        return o
    finally:
        db.close()


def _notifications(user_id: int, type: str) -> list[Notification]:
    db = _db()
    try:
        return db.query(Notification).filter(Notification.user_id == user_id, Notification.type == type).all()
    finally:
        db.close()


def _payment_id() -> str:
    return str(random.randint(10 ** 11, 10 ** 12 - 1))


def _mp_payment(ref: str, amount, status="approved", currency="MXN", pid=None) -> dict:
    return {"id": int(pid or _payment_id()), "status": status, "external_reference": ref,
            "transaction_amount": float(amount), "currency_id": currency}


def _process(payment: dict, monkeypatch) -> str:
    monkeypatch.setattr(payments, "get_payment", lambda pid, **kw: payment)
    db = _db()
    try:
        return payment_flow.process_payment(db, str(payment["id"]))
    finally:
        db.close()


def _age(model, obj_id: int, minutes: int = 120):
    db = _db()
    try:
        db.query(model).filter(model.id == obj_id).update(
            {model.created_at: datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)})
        db.commit()
    finally:
        db.close()


def _expire(monkeypatch, found=None):
    monkeypatch.setattr(payments, "search_payments", lambda ref, **kw: (found or {}).get(ref, []))
    db = _db()
    try:
        return payment_flow.expire_pending_payments(db)
    finally:
        db.close()


@pytest.fixture
def mp(monkeypatch):
    """Mercado Pago "activo" con la API simulada (sin llamadas reales)."""
    monkeypatch.setattr(settings, "mercadopago_access_token", "TEST-token-pruebas")
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", SECRET)
    prefs = []

    def fake_preference(items, external_reference, back_query, payer_email=None, **kwargs):
        prefs.append({"items": items, "external_reference": external_reference, **kwargs})
        return {"id": f"pref-{uuid.uuid4().hex[:8]}", "init_point": "https://www.mercadopago.com.mx/checkout/v1/redirect?x=1"}

    monkeypatch.setattr(payments, "create_preference", fake_preference)
    monkeypatch.setattr(payments, "search_payments", lambda ref, **kw: [])
    return prefs


@pytest.fixture
def seller(client):
    u = _register(client, "Refugio Vendedor")
    u["refuge_id"] = _make_refuge(u["email"])
    return u


def _set_role(email: str, role: str):
    db = _db()
    try:
        db.query(User).filter(User.email == email).update({User.role: role})
        db.commit()
    finally:
        db.close()


@pytest.fixture
def admin(client):
    u = _register(client, "Admin Pagos")
    _set_role(u["email"], "admin")
    u["id"] = _user_id(u["email"])
    yield u
    _set_role(u["email"], "user")  # que la base de desarrollo no acumule admins de prueba


def _checkout(client, buyer, product, quantity=1):
    r = client.post("/orders", headers=buyer["h"], json={
        "items": [{"product_id": product["id"], "quantity": quantity}], "shipping_address": "Av. Siempre Viva 742, CDMX",
        "accepted_terms": True, "consent_prepayment": True})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- M1 firma
def _mp_signature(secret, data_id, request_id, ts):
    """Firma tal como la arma Mercado Pago (documentación de Webhooks)."""
    manifest = f"id:{data_id.lower() if data_id.isalnum() else data_id};request-id:{request_id};ts:{ts};"
    return f"ts={ts},v1={hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()}"


def test_signature_follows_mp_docs(monkeypatch):
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", SECRET)
    ts, req = "1742505638683", "bb56a2f1-6aae-46ac-982e-9dcd3581d08e"
    sig = _mp_signature(SECRET, "ABC123def", req, ts)
    assert payments.verify_signature(sig, req, "ABC123def") is True  # alfanumérico: en minúsculas
    assert payments.verify_signature(sig.replace("v1=", "v1= ").replace(",", " , "), req, "ABC123def") is True
    assert payments.verify_signature(sig, req, "ABC123deg") is False
    assert payments.verify_signature(sig, "otro-request-id", "ABC123def") is False
    assert payments.verify_signature(sig.replace(f"ts={ts}", "ts=1"), req, "ABC123def") is False
    assert payments.verify_signature(None, req, "ABC123def") is False
    assert payments.verify_signature("v1=abc", req, "ABC123def") is False
    # Sin x-request-id el fragmento se omite del manifiesto
    no_req = f"id:999;ts:{ts};"
    v1 = hmac.new(SECRET.encode(), no_req.encode(), hashlib.sha256).hexdigest()
    assert payments.verify_signature(f"ts={ts},v1={v1}", None, "999") is True


def test_webhook_accepts_valid_signature_and_rejects_tampered(client, mp, monkeypatch):
    calls = []
    monkeypatch.setattr(payments_router, "dispatch", lambda *a, **kw: calls.append(a) or "inline")
    pid, ts, req = _payment_id(), "1742505638", str(uuid.uuid4())
    url = f"/payments/mercadopago/webhook?data.id={pid}&type=payment"
    body = {"type": "payment", "action": "payment.updated", "data": {"id": pid}}
    ok = client.post(url, json=body, headers={"x-signature": _mp_signature(SECRET, pid, req, ts), "x-request-id": req})
    assert ok.json() == {"received": True}
    assert calls == [("app.tasks.payments.process_mercadopago_payment", pid)]

    # Firma alterada, otro data.id en el query o request-id distinto: se ignora sin procesar
    bad_sig = _mp_signature(SECRET, pid, req, ts)[:-2] + "00"
    for q_id, sig, rid in ((pid, bad_sig, req), (_payment_id(), _mp_signature(SECRET, pid, req, ts), req),
                           (pid, _mp_signature(SECRET, pid, req, ts), "otro")):
        r = client.post(f"/payments/mercadopago/webhook?data.id={q_id}&type=payment", json=body,
                        headers={"x-signature": sig, "x-request-id": rid})
        assert r.status_code == 200 and r.json()["reason"] == "invalid_signature"
    # data.id solo en el cuerpo: el manifiesto no lleva id y la firma con id no coincide
    r = client.post("/payments/mercadopago/webhook?type=payment", json=body,
                    headers={"x-signature": _mp_signature(SECRET, pid, req, ts), "x-request-id": req})
    assert r.json()["reason"] == "invalid_signature"
    assert len(calls) == 1


def test_preference_has_expiration(monkeypatch):
    sent = {}

    class Resp:
        status_code = 201

        def json(self):
            return {"id": "pref-1", "init_point": "https://mp/init"}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(json)
        return Resp()

    monkeypatch.setattr(settings, "mercadopago_access_token", "TEST-token")
    monkeypatch.setattr(payments.requests, "post", fake_post)
    before = datetime.datetime.now(datetime.timezone.utc)
    payments.create_preference([{"title": "Taza", "quantity": 1, "unit_price": 100}], "order:1", "order=1")
    assert sent["expires"] is True
    to = datetime.datetime.fromisoformat(sent["expiration_date_to"])
    delta = (to - before).total_seconds() / 60
    assert settings.checkout_expiration_minutes - 1 <= delta <= settings.checkout_expiration_minutes + 1


# --------------------------------------------------------------------------- M4 checkout
def test_checkout_reserves_stock_without_holding_lock(client, mp, seller, user, monkeypatch):
    product = _product(client, seller, price=150, stock=3)
    seen = []
    original = payments.create_preference

    def checking_preference(*args, **kwargs):
        # Mientras se llama a Mercado Pago, otra conexión puede bloquear el producto (no hay FOR UPDATE abierto)
        db = _db()
        try:
            db.execute(text("SET LOCAL lock_timeout = '1s'"))
            db.execute(text("SELECT id FROM products WHERE id = :id FOR UPDATE NOWAIT"), {"id": product["id"]})
            seen.append(db.execute(text("SELECT stock FROM products WHERE id = :id"), {"id": product["id"]}).scalar())
        finally:
            db.rollback()
            db.close()
        return original(*args, **kwargs)

    monkeypatch.setattr(payments, "create_preference", checking_preference)
    order = _checkout(client, user, product, quantity=2)
    assert order["status"] == "pending_payment" and order["checkout_url"].startswith("https://")
    assert order["simulated"] is False and order["total"] in ("300.00", "300")
    assert seen == [1] and _stock(product["id"]) == 1
    assert mp[-1]["external_reference"] == f"order:{order['id']}"

    # Si Mercado Pago falla, se devuelve el inventario y el pedido queda cancelado
    def failing(*a, **kw):
        raise payments.PaymentError("Mercado Pago rechazó la solicitud de pago.")

    monkeypatch.setattr(payments, "create_preference", failing)
    r = client.post("/orders", headers=user["h"], json={"items": [{"product_id": product["id"], "quantity": 1}],
                                                        "shipping_address": "Calle 2", "accepted_terms": True,
                                                        "consent_prepayment": True})
    assert r.status_code == 502 and "Mercado Pago" in r.json()["detail"]
    assert _stock(product["id"]) == 1
    db = _db()
    try:
        last = db.query(Order).filter(Order.user_id == _user_id(user["email"])).order_by(Order.id.desc()).first()
        assert last.status == "cancelled"
    finally:
        db.close()


def test_mixed_refuges_and_limits(client, seller, user, make_user):
    other = make_user("Otro Refugio")
    _make_refuge(other["email"])
    p1, p2 = _product(client, seller), _product(client, other)
    r = client.post("/orders", headers=user["h"], json={
        "items": [{"product_id": p1["id"], "quantity": 1}, {"product_id": p2["id"], "quantity": 1}],
        "shipping_address": "Calle 3", "accepted_terms": True, "consent_prepayment": True})
    assert r.status_code == 400 and "varios refugios" in r.json()["detail"]
    r = client.post("/orders", headers=user["h"], json={"items": [{"product_id": p1["id"], "quantity": 101}],
                                                        "shipping_address": "Calle 3", "accepted_terms": True, "consent_prepayment": True})
    assert r.status_code == 400
    assert _stock(p1["id"]) == 5 and _stock(p2["id"]) == 5


# --------------------------------------------------------------------------- M2/M3 webhook
def test_webhook_idempotent_and_rejection_keeps_order(client, mp, seller, user, monkeypatch):
    product = _product(client, seller, price=120, stock=2)
    order = _checkout(client, user, product)
    ref = f"order:{order['id']}"
    # Un pago rechazado no cancela: el comprador puede reintentar
    assert _process(_mp_payment(ref, 120, status="rejected"), monkeypatch) == "order:pending_payment"
    assert _stock(product["id"]) == 1

    approved = _mp_payment(ref, 120)
    assert _process(approved, monkeypatch) == "order:paid"
    assert _process(approved, monkeypatch) == "order:paid"  # webhook + IPN: sin efecto la segunda vez
    o = _order(order["id"])
    assert o.status == "paid" and o.provider_payment_id == str(approved["id"]) and str(o.paid_amount) == "120.00"
    buyer_id = _user_id(user["email"])
    assert len([n for n in _notifications(buyer_id, "order_paid") if n.data["order_id"] == order["id"]]) == 1
    db = _db()
    try:
        assert db.query(PaymentEvent).filter(PaymentEvent.payment_id == str(approved["id"])).count() == 1
    finally:
        db.close()
    assert _stock(product["id"]) == 1
    status = client.get("/payments/status", headers=user["h"], params={"order": order["id"]}).json()
    assert status["status"] == "paid"


def test_parallel_notifications_credit_donation_once(client, mp, seller, user, monkeypatch):
    r = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 250})
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["checkout_url"]
    donation_id = r.json()["donation_id"]
    payment = _mp_payment(f"donation:{donation_id}", 250)
    monkeypatch.setattr(payments, "get_payment", lambda pid, **kw: payment)
    db = _db()
    before = db.query(Refuge.points).filter(Refuge.id == seller["refuge_id"]).scalar()
    db.close()

    barrier, results = threading.Barrier(4), []

    def worker():
        s = _db()
        try:
            barrier.wait()
            results.append(payment_flow.process_payment(s, str(payment["id"])))
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(results) == 4 and all(r.startswith("donation:") for r in results)
    db = _db()
    try:
        # Se acredita una sola vez y no suma puntos de ranking (donativos.html §12)
        assert db.query(Refuge.points).filter(Refuge.id == seller["refuge_id"]).scalar() == before
        assert db.query(Donation.status).filter(Donation.id == donation_id).scalar() == "approved"
        assert db.query(PaymentEvent).filter(PaymentEvent.payment_id == str(payment["id"])).count() == 1
    finally:
        db.close()
    owner_id = _user_id(seller["email"])
    received = [n for n in _notifications(owner_id, "donation_received") if n.data["donation_id"] == donation_id]
    assert len(received) == 1


def test_amount_mismatch_flags_for_review(client, mp, seller, user, admin, monkeypatch):
    product = _product(client, seller, price=200, stock=3)
    order = _checkout(client, user, product)
    result = _process(_mp_payment(f"order:{order['id']}", 1), monkeypatch)
    assert result == "order:amount_mismatch"
    o = _order(order["id"])
    assert o.status == "amount_mismatch" and o.paid_at is None and "$1.00" in o.review_note
    assert any(n.data.get("order_id") == order["id"] for n in _notifications(admin["id"], "payment_amount_mismatch"))
    assert _stock(product["id"]) == 2  # sigue apartado hasta que un admin decida

    # Moneda distinta con el mismo número también es sospechoso
    order2 = _checkout(client, user, product)
    assert _process(_mp_payment(f"order:{order2['id']}", 200, currency="USD"), monkeypatch) == "order:amount_mismatch"

    # El admin reembolsa: se llama a Mercado Pago, se libera el inventario y queda en la bitácora
    refunded = []
    monkeypatch.setattr(payments, "refund_payment", lambda pid, **kw: refunded.append(pid) or {"id": 1})
    r = client.post(f"/admin/orders/{order['id']}/resolve", headers=admin["h"], json={"action": "refund", "notes": "monto raro"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "refunded" and refunded == [o.provider_payment_id]
    assert _stock(product["id"]) == 2
    assert client.post(f"/admin/orders/{order['id']}/resolve", headers=admin["h"],
                       json={"action": "refund"}).status_code == 409
    # El otro lo acepta como pagado
    r = client.post(f"/admin/orders/{order2['id']}/resolve", headers=admin["h"], json={"action": "mark_paid"})
    assert r.status_code == 200 and r.json()["status"] == "paid"
    db = _db()
    try:
        actions = {a.action for a in db.query(AdminAuditLog).filter(AdminAuditLog.target_type == "order",
                                                                    AdminAuditLog.target_id.in_([order["id"], order2["id"]]))}
        assert actions == {"order_refund", "order_mark_paid"}
    finally:
        db.close()
    assert client.post(f"/admin/orders/{order['id']}/resolve", headers=user["h"], json={"action": "refund"}).status_code == 403


def test_donation_amount_mismatch_and_refund(client, mp, seller, user, admin, monkeypatch):
    d = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 100}).json()
    assert _process(_mp_payment(f"donation:{d['donation_id']}", 10), monkeypatch) == "donation:amount_mismatch"
    db = _db()
    before = db.query(Refuge.points).filter(Refuge.id == seller["refuge_id"]).scalar()
    db.close()
    r = client.post(f"/admin/donations/{d['donation_id']}/resolve", headers=admin["h"], json={"action": "mark_paid"})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["amount"] in ("10.00", "10")
    db = _db()
    try:
        assert db.query(Refuge.points).filter(Refuge.id == seller["refuge_id"]).scalar() == before  # sin puntos
    finally:
        db.close()
    # Mercado Pago avisa que el pago se reembolsó: no hay puntos que descontar
    db = _db()
    try:
        payment_id = db.query(Donation.provider_payment_id).filter(Donation.id == d["donation_id"]).scalar()
    finally:
        db.close()
    refund = _mp_payment(f"donation:{d['donation_id']}", 10, status="refunded", pid=payment_id)
    assert _process(refund, monkeypatch) == "donation:refunded"
    db = _db()
    try:
        assert db.query(Refuge.points).filter(Refuge.id == seller["refuge_id"]).scalar() == before
    finally:
        db.close()


# --------------------------------------------------------------------------- M2/M5 expiración y pagos tardíos
def test_expiry_releases_stock_and_late_payment_rereserves(client, mp, seller, user, monkeypatch):
    product = _product(client, seller, price=80, stock=2)
    order = _checkout(client, user, product)
    fresh = _checkout(client, user, product)
    assert _stock(product["id"]) == 0
    _age(Order, order["id"])
    result = _expire(monkeypatch)
    assert result["orders_expired"] >= 1
    assert _order(order["id"]).status == "cancelled" and _order(fresh["id"]).status == "pending_payment"
    assert _order(order["id"]).cancel_reason == "payment_expired"
    assert _stock(product["id"]) == 1
    buyer_id = _user_id(user["email"])
    assert any(n.data["order_id"] == order["id"] for n in _notifications(buyer_id, "order_expired"))

    # El pago aprobado llega tarde: hay inventario, se vuelve a apartar y queda pagado
    assert _process(_mp_payment(f"order:{order['id']}", 80), monkeypatch) == "order:paid"
    assert _stock(product["id"]) == 0


def test_late_payment_without_stock_goes_to_refund(client, mp, seller, user, admin, monkeypatch):
    product = _product(client, seller, price=90, stock=1)
    order = _checkout(client, user, product)
    _age(Order, order["id"])
    _expire(monkeypatch)
    assert _order(order["id"]).status == "cancelled"
    other = _checkout(client, user, product)  # alguien más compró la última pieza
    assert _stock(product["id"]) == 0

    late = _mp_payment(f"order:{order['id']}", 90)
    assert _process(late, monkeypatch) == "order:refund_pending"
    assert _process(late, monkeypatch) == "order:refund_pending"
    o = _order(order["id"])
    assert o.provider_payment_id == str(late["id"]) and o.paid_at is None
    assert len([n for n in _notifications(admin["id"], "payment_refund_pending") if n.data["order_id"] == order["id"]]) == 1
    assert _stock(product["id"]) == 0

    # Sin inventario no se puede aceptar; el reembolso sí
    assert client.post(f"/admin/orders/{order['id']}/resolve", headers=admin["h"],
                       json={"action": "mark_paid"}).status_code == 409
    monkeypatch.setattr(payments, "refund_payment", lambda pid, **kw: {"id": 1})
    r = client.post(f"/admin/orders/{order['id']}/resolve", headers=admin["h"], json={"action": "refund"})
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    assert _stock(product["id"]) == 0 and _order(other["id"]).status == "pending_payment"


def test_expiry_reconciles_lost_notification(client, mp, seller, user, monkeypatch):
    product = _product(client, seller, price=60, stock=1)
    order = _checkout(client, user, product)
    d = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 30}).json()
    lost_d = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 40}).json()
    _age(Order, order["id"])
    _age(Donation, d["donation_id"])
    _age(Donation, lost_d["donation_id"])
    found = {f"order:{order['id']}": [_mp_payment(f"order:{order['id']}", 60, status="rejected"),
                                       _mp_payment(f"order:{order['id']}", 60)],
             f"donation:{d['donation_id']}": [_mp_payment(f"donation:{d['donation_id']}", 30)]}
    result = _expire(monkeypatch, found)
    assert result["reconciled"] >= 2
    assert _order(order["id"]).status == "paid" and _stock(product["id"]) == 0
    db = _db()
    try:
        assert db.query(Donation.status).filter(Donation.id == d["donation_id"]).scalar() == "approved"
        assert db.query(Donation.status).filter(Donation.id == lost_d["donation_id"]).scalar() == "expired"
    finally:
        db.close()
    # Una donación expirada sí se acredita si el pago llega después (rechazo previo incluido)
    assert _process(_mp_payment(f"donation:{lost_d['donation_id']}", 40, status="rejected"), monkeypatch) == "donation:expired"
    assert _process(_mp_payment(f"donation:{lost_d['donation_id']}", 40), monkeypatch) == "donation:approved"


def test_status_poll_reconciles_with_mercadopago(client, mp, seller, user, monkeypatch):
    product = _product(client, seller, price=55, stock=1)
    order = _checkout(client, user, product)
    approved = _mp_payment(f"order:{order['id']}", 55)
    searched = []
    monkeypatch.setattr(payments, "search_payments", lambda ref, **kw: searched.append(ref) or [approved])
    r = client.get("/payments/status", headers=user["h"], params={"order": order["id"]})
    assert r.status_code == 200 and r.json()["status"] == "paid"
    assert client.get("/payments/status", headers=user["h"], params={"order": order["id"]}).json()["status"] == "paid"
    assert searched == [f"order:{order['id']}"]  # ya pagado: no se vuelve a consultar


def test_expire_task_is_scheduled():
    from app.celery_app import celery_app
    from app.tasks import payments as payment_tasks

    entry = celery_app.conf.beat_schedule["payments-expire-pending"]
    assert entry["task"] == "app.tasks.payments.expire_pending_payments"
    assert payment_tasks.expire_pending_payments.name == entry["task"]


# --------------------------------------------------------------------------- M6 tienda apagada
def test_shop_disabled_returns_404(client, seller, user, admin, monkeypatch):
    product = _product(client, seller)
    monkeypatch.setattr(settings, "shop_enabled", False)
    for r in (client.get("/products"), client.get(f"/products/{product['id']}"),
              client.post("/orders", headers=user["h"], json={"items": [{"product_id": product["id"], "quantity": 1}],
                                                              "shipping_address": "Calle 4", "accepted_terms": True,
                                                              "consent_prepayment": True}),
              client.post("/products", headers=seller["h"], json={"name": "x", "price": 10})):
        assert r.status_code == 404 and r.json()["detail"] == payment_flow.SHOP_DISABLED_DETAIL
    assert client.get("/products", headers=admin["h"]).status_code == 200
    r = client.patch(f"/products/{product['id']}", headers=admin["h"], json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    if not settings.payments_enabled:  # las donaciones siguen funcionando
        d = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 50})
        assert d.status_code == 201 and d.json()["status"] == "approved"
    assert client.get("/orders", headers=user["h"]).status_code == 200
    monkeypatch.setattr(settings, "shop_enabled", None)
    assert client.get(f"/products/{product['id']}").status_code == 404  # desactivado por el admin
    assert client.get(f"/products/{product['id']}", headers=seller["h"]).status_code == 200


def test_products_pagination(client, seller):
    for _ in range(3):
        _product(client, seller)
    page = client.get("/products", params={"refuge_id": seller["refuge_id"], "limit": 2})
    assert page.status_code == 200 and len(page.json()) == 2
    rest = client.get("/products", params={"refuge_id": seller["refuge_id"], "limit": 2, "skip": 2}).json()
    assert len(rest) == 1 and rest[0]["id"] not in {p["id"] for p in page.json()}
    assert client.get("/products", params={"limit": 101}).status_code == 422


# --------------------------------------------------------------------------- M7 pedidos del refugio
def test_refuge_orders_ship_and_buyer_tracking(client, seller, user, make_user, mp, monkeypatch):
    product = _product(client, seller, price=75, stock=5)
    unpaid = _checkout(client, user, product)
    paid = _checkout(client, user, product, quantity=2)
    assert _process(_mp_payment(f"order:{paid['id']}", 150), monkeypatch) == "order:paid"

    listing = client.get("/refuges/me/orders", headers=seller["h"])
    assert listing.status_code == 200
    ids = [o["id"] for o in listing.json()]
    assert paid["id"] in ids and unpaid["id"] not in ids  # los no pagados no se envían
    row = next(o for o in listing.json() if o["id"] == paid["id"])
    assert row["buyer_name"] == "Adoptante Prueba" and row["shipping_address"].startswith("Av. Siempre Viva")
    assert row["status"] == "paid" and row["items"][0]["quantity"] == 2 and float(row["total"]) == 150

    stranger = make_user("Otro Refugio")
    _make_refuge(stranger["email"])
    assert paid["id"] not in [o["id"] for o in client.get("/refuges/me/orders", headers=stranger["h"]).json()]
    assert client.patch(f"/refuges/me/orders/{paid['id']}", headers=stranger["h"],
                        json={"status": "shipped"}).status_code == 404
    assert client.patch(f"/refuges/me/orders/{unpaid['id']}", headers=seller["h"],
                        json={"status": "shipped"}).status_code == 409

    r = client.patch(f"/refuges/me/orders/{paid['id']}", headers=seller["h"],
                     json={"status": "shipped", "carrier": "Estafeta", "tracking_number": "EST123456"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "shipped" and r.json()["shipped_at"]
    mine = client.get(f"/orders/{paid['id']}", headers=user["h"]).json()
    assert mine["status"] == "shipped" and mine["carrier"] == "Estafeta" and mine["tracking_number"] == "EST123456"
    assert mine["shipped_at"] and mine["delivered_at"] is None
    shipped = [n for n in _notifications(_user_id(user["email"]), "order_shipped") if n.data["order_id"] == paid["id"]]
    assert len(shipped) == 1 and "EST123456" in shipped[0].body
    assert [o["id"] for o in client.get("/refuges/me/orders", headers=seller["h"],
                                        params={"status": "shipped"}).json()] == [paid["id"]]

    r = client.patch(f"/refuges/me/orders/{paid['id']}", headers=seller["h"], json={"status": "delivered"})
    assert r.status_code == 200 and r.json()["status"] == "delivered" and r.json()["tracking_number"] == "EST123456"
    assert client.patch(f"/refuges/me/orders/{paid['id']}", headers=seller["h"],
                        json={"status": "shipped"}).status_code == 409
    assert client.get("/refuges/me/orders", headers=user["h"]).status_code == 404  # no tiene refugio
