"""Tienda — correcciones de la revisión: donativos sin RFC, reembolsos parciales y saldo insuficiente, avisos al
comprador y al refugio (enlaces a "Mi tienda"), checkout con aceptación guardada, link de pago pendiente,
facturas (perfil fiscal, UUID único, aviso de cancelación), cancelaciones con motivo, plazo de despacho,
estados de cuenta por mes del reembolso, admin y regresiones (cuenta eliminada, exportación).

Ninguna prueba llama a Mercado Pago ni a un PAC: todo va con monkeypatch (fixtures de test_tienda.py).
"""
import datetime
import random
import uuid
from decimal import Decimal

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import Notification, Order, OrderInvoice, OrderRefund, Refuge, RefugePaymentAccount, User
from app.services import account_deletion, invoicing, mercadopago_oauth, order_flow, payment_flow, payments
from app.services.payments import refund_payment as real_refund_payment  # el fixture mp lo reemplaza
from test_tienda import (  # noqa: F401 - fixtures (admin, emails, mp, _deactivate_products) y utilidades
    _buy, _cfdi_xml, _commission_10, _db, _deactivate_products, _delivered_order, _in_period, _make_seller, _move_refunds, _notifs,
    _order, _order_body, _pay, _period, _product, _stock, _update_order, _user_id, admin, emails, mp,
)


# --------------------------------------------------------------------------- S1c donativos sin RFC
def test_donations_ready_does_not_require_rfc(client, user, mp, monkeypatch):
    seller = _make_seller(client)  # Mercado Pago vinculado, sin perfil fiscal
    refuge = client.get(f"/refuges/{seller['refuge_id']}").json()
    assert refuge["donations_ready"] is True and refuge["seller_payments_ready"] is True
    db = _db()
    try:
        r = db.query(Refuge).filter(Refuge.id == seller["refuge_id"]).first()
        monkeypatch.setattr(settings, "environment", "production")
        # En producción sin RFC no se vende, pero sí se dona (fiscal-tienda-19)
        assert mercadopago_oauth.refuge_payments_ready(r) is False
        assert mercadopago_oauth.refuge_donations_ready(r) is True
        monkeypatch.setattr(settings, "environment", "development")
    finally:
        db.close()
    off = _make_seller(client, connected=False)
    monkeypatch.setattr(settings, "donations_fallback_to_platform_account", False)
    assert client.get(f"/refuges/{off['refuge_id']}").json()["donations_ready"] is False
    monkeypatch.setattr(settings, "donations_fallback_to_platform_account", True)
    assert client.get(f"/refuges/{off['refuge_id']}").json()["donations_ready"] is True


# --------------------------------------------------------------------------- S1d saldo insuficiente
def test_refund_insufficient_balance_is_explained_and_retryable(client, user, mp, monkeypatch):
    class Resp:
        status_code = 400
        text = '{"message":"Insufficient balance to refund","error":"bad_request","status":400}'

    monkeypatch.setattr(payments.requests, "post", lambda *a, **kw: Resp())
    with pytest.raises(payments.PaymentError) as exc:
        real_refund_payment("123456789", access_token="APP_USR-x")
    assert exc.value.code == "insufficient_balance" and "saldo" in str(exc.value)

    seller = _make_seller(client)
    product = _product(client, seller, price=150)
    order = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, order, collector=seller["mp_user_id"])
    oid = order["id"]
    client.patch(f"/refuges/me/orders/{oid}", headers=seller["h"], json={"status": "shipped", "carrier": "DHL",
                                                                         "tracking_number": "DHL9"})
    client.post(f"/orders/{oid}/confirm-delivery", headers=user["h"])
    client.post(f"/orders/{oid}/return", headers=user["h"], json={"reason": "defectuoso", "details": "Llegó roto"})

    def no_balance(*a, **kw):
        raise payments.PaymentError(payments.INSUFFICIENT_BALANCE_DETAIL, code="insufficient_balance")

    monkeypatch.setattr(payments, "refund_payment", no_balance)
    r = client.post(f"/refuges/me/orders/{oid}/return-decision", headers=seller["h"], json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "return_approved"
    assert r.json()["refund_status"] == "insufficient_funds" and r.json()["can_retry_refund"] is True
    warn = _notifs(seller["user_id"], "order_refund_failed", oid)
    assert warn and "saldo" in warn[0].body
    # El refugio ingresa saldo y reintenta
    monkeypatch.setattr(payments, "refund_payment", lambda pid, **kw: {"id": 99, "status": "approved"})
    r = client.post(f"/refuges/me/orders/{oid}/retry-refund", headers=seller["h"])
    assert r.status_code == 200 and r.json()["status"] == "refunded" and r.json()["can_retry_refund"] is False
    assert client.post(f"/refuges/me/orders/{oid}/retry-refund", headers=seller["h"]).status_code == 409


def test_refund_older_than_180_days_is_rejected_locally(client, user, mp, monkeypatch):
    seller = _make_seller(client)
    product = _product(client, seller, price=90)
    order = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, order)
    _update_order(order["id"], paid_at=datetime.datetime.utcnow() - datetime.timedelta(days=181))
    db = _db()
    try:
        with pytest.raises(payment_flow.RefundFailed) as exc:
            payment_flow.refund_at_provider(db, db.query(Order).filter(Order.id == order["id"]).first())
        assert exc.value.code == "too_old" and "180" in exc.value.detail
    finally:
        db.close()


# --------------------------------------------------------------------------- S3b avisos
def test_expiry_email_payment_review_and_spanish_return_reasons(client, user, mp, monkeypatch, emails):
    seller = _make_seller(client)
    product = _product(client, seller, price=70)
    pending = _buy(client, user, [(product, 1)])
    db = _db()
    try:
        assert payment_flow.expire_order(db, pending["id"]) is True
    finally:
        db.close()
    buyer_id = _user_id(user["email"])
    assert _notifs(buyer_id, "order_expired", pending["id"])
    mails = [a for t, a in emails if t == "app.tasks.notifications.send_notification_email" and a[0] == user["email"]]
    assert any("expiró" in str(a) for a in mails)  # el vencimiento también llega por correo

    other = _buy(client, user, [(product, 1)])
    pid = random.randint(10 ** 11, 10 ** 12 - 1)
    wrong = {"id": pid, "status": "approved", "external_reference": f"order:{other['id']}",
             "transaction_amount": 1.0, "currency_id": "MXN"}
    monkeypatch.setattr(payments, "get_payment", lambda pid, **kw: wrong)
    db = _db()
    try:
        assert payment_flow.process_payment(db, str(pid)) == "order:amount_mismatch"
    finally:
        db.close()
    review = _notifs(buyer_id, "order_payment_review", other["id"])
    assert review and review[0].title == "Estamos revisando tu pago"

    monkeypatch.setattr(settings, "mercadopago_access_token", None)  # pagos simulados para entregarlo rápido
    oid = _delivered_order(client, user, seller, _product(client, seller))
    r = client.post(f"/orders/{oid}/return", headers=user["h"], json={"reason": "no_corresponde", "details": "Es otro"})
    assert r.json()["timeline"][-1]["note"] == "Motivo: no corresponde a lo que se pidió."
    body = _notifs(seller["user_id"], "order_return_requested", oid)[0].body
    assert "no_corresponde" not in body and "no corresponde a lo que se pidió" in body


def test_refuge_notifications_open_my_shop(client, user, mp, monkeypatch):
    seller = _make_seller(client)
    product = _product(client, seller, price=60)
    order = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, order)
    seller_note = _notifs(seller["user_id"], "new_order", order["id"])[0]
    assert seller_note.data["url"] == "/app/?shop=pedidos" and seller_note.data["seller_view"] is True
    buyer_note = _notifs(_user_id(user["email"]), "order_paid", order["id"])[0]
    assert buyer_note.data["url"] == f"/app/?order={order['id']}" and "seller_view" not in buyer_note.data
    req = {"rfc": "MOPA800101AB3", "legal_name": "Ana Morales", "regimen_fiscal": "605", "postal_code": "03100",
           "uso_cfdi": "G03", "email": "ana@ejemplo.mx"}
    client.post(f"/orders/{order['id']}/invoice-request", headers=user["h"], json=req)
    inv_note = _notifs(seller["user_id"], "invoice_requested", order["id"])[0]
    assert inv_note.data["url"] == "/app/?shop=facturas" and inv_note.data["tab"] == "facturas"


# --------------------------------------------------------------------------- checkout: aceptación y link de pago
def test_checkout_requires_and_stores_consent(client, user, mp, admin):
    seller = _make_seller(client)
    product = _product(client, seller, price=80)
    body = _order_body([(product, 1)])
    for missing in ({"accepted_terms": False}, {"consent_prepayment": False}):
        r = client.post("/orders", headers=user["h"], json={**body, **missing})
        assert r.status_code == 400 and "condiciones" in r.json()["detail"]
    old = client.post("/orders", headers=user["h"], json={**body, "terms_version": "2020-01-01"})
    assert old.status_code == 409 and "Recarga" in old.json()["detail"]
    r = client.post("/orders", headers={**user["h"], "User-Agent": "Pruebas/1.0", "X-Real-IP": "10.9.8.7"},
                    json={**body, "terms_version": settings.legal_terms_version})
    assert r.status_code == 201, r.text
    o = _order(r.json()["id"])
    assert o.terms_version == settings.legal_terms_version and o.terms_hash == payment_flow.checkout_terms_hash()
    assert o.terms_accepted_at and o.consent_prepayment_at and o.terms_user_agent == "Pruebas/1.0" and o.terms_ip
    assert len(o.terms_hash) == 64
    detail = client.get("/admin/orders", headers=admin["h"], params={"refuge_id": seller["refuge_id"]}).json()[0]
    assert detail["terms_hash"] == o.terms_hash and detail["consent_prepayment_at"]
    assert _stock(product["id"]) == 9  # los intentos rechazados no apartaron inventario


def test_pending_order_exposes_checkout_url_until_it_expires(client, user, mp):
    seller = _make_seller(client)
    product = _product(client, seller, price=55)
    order = _buy(client, user, [(product, 1)])
    detail = client.get(f"/orders/{order['id']}", headers=user["h"]).json()
    assert detail["status"] == "pending_payment" and detail["checkout_url"].startswith("https://")
    _update_order(order["id"], created_at=datetime.datetime.utcnow() - datetime.timedelta(
        minutes=settings.checkout_expiration_minutes + 1))
    assert client.get(f"/orders/{order['id']}", headers=user["h"]).json()["checkout_url"] is None


# --------------------------------------------------------------------------- S5b facturas
def test_invoice_needs_fiscal_profile_unique_uuid_and_cancel_notice(client, user, mp, monkeypatch, admin):
    req = {"rfc": "MOPA800101AB3", "legal_name": "Ana Morales Pérez", "regimen_fiscal": "605", "postal_code": "03100",
           "uso_cfdi": "G03", "email": "ana@ejemplo.mx"}
    bare = _make_seller(client)  # sin perfil fiscal
    product = _product(client, bare, price="116")
    order = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, order, collector=bare["mp_user_id"])
    assert client.post(f"/orders/{order['id']}/invoice-request", headers=user["h"], json=req).status_code == 201
    good = str(uuid.uuid4()).upper()
    xml = client.post("/upload/cfdi-xml", headers=bare["h"], files={
        "file": ("f.xml", _cfdi_xml(good, "ZZZZ991231ZZ9", "MOPA800101AB3", "116.00"), "application/xml")}).json()["id"]
    r = client.post(f"/refuges/me/orders/{order['id']}/invoice", headers=bare["h"],
                    json={"status": "issued", "xml_document_id": xml})
    assert r.status_code == 400 and "datos fiscales" in r.json()["detail"]

    fiscal = {"person_type": "moral", "rfc": "PFI010101AB2", "legal_name": "PATITAS AC", "regimen_fiscal": "603",
              "postal_code": "06700"}
    seller = _make_seller(client, fiscal=fiscal)
    product = _product(client, seller, price="116")
    first, second = _buy(client, user, [(product, 1)]), _buy(client, user, [(product, 1)])
    _pay(monkeypatch, first, collector=seller["mp_user_id"])
    _pay(monkeypatch, second, collector=seller["mp_user_id"])
    for o in (first, second):
        assert client.post(f"/orders/{o['id']}/invoice-request", headers=user["h"], json=req).status_code == 201
    no_emisor = client.post("/upload/cfdi-xml", headers=seller["h"], files={
        "file": ("f.xml", _cfdi_xml(good, "", "MOPA800101AB3", "116.00"), "application/xml")}).json()["id"]
    assert client.post(f"/refuges/me/orders/{first['id']}/invoice", headers=seller["h"],
                       json={"status": "issued", "xml_document_id": no_emisor}).status_code == 400
    xml = client.post("/upload/cfdi-xml", headers=seller["h"], files={
        "file": ("f.xml", _cfdi_xml(good, "PFI010101AB2", "MOPA800101AB3", "116.00"), "application/xml")}).json()["id"]
    ok = client.post(f"/refuges/me/orders/{first['id']}/invoice", headers=seller["h"],
                     json={"status": "issued", "xml_document_id": xml})
    assert ok.status_code == 200, ok.text
    dup = client.post(f"/refuges/me/orders/{second['id']}/invoice", headers=seller["h"],
                      json={"status": "issued", "xml_document_id": xml})
    assert dup.status_code == 409 and "otro pedido" in dup.json()["detail"]

    # Se cancela un pedido ya facturado: el refugio debe cancelar el CFDI
    r = client.post(f"/orders/{first['id']}/cancel", headers=user["h"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    notice = _notifs(seller["user_id"], "invoice_cancel_needed", first["id"])
    assert notice and good in notice[0].body and notice[0].data["tab"] == "facturas"
    db = _db()
    try:
        assert "cancelar este CFDI" in db.query(OrderInvoice).filter(OrderInvoice.order_id == first["id"]).first().note
    finally:
        db.close()


# --------------------------------------------------------------------------- consumidor-ecommerce-13 / 14
def test_refuge_and_admin_cancel_with_recorded_reason(client, user, mp, monkeypatch, admin):
    seller = _make_seller(client)
    product = _product(client, seller, price=120, stock=4)
    order = _buy(client, user, [(product, 1)])
    payment = _pay(monkeypatch, order, collector=seller["mp_user_id"])
    oid = order["id"]
    assert client.get("/refuges/me/orders", headers=seller["h"]).json()[0]["can_cancel"] is True
    short = client.post(f"/refuges/me/orders/{oid}/cancel", headers=seller["h"], json={"reason": "sin_inventario",
                                                                                      "note": "no"})
    assert short.status_code == 422
    assert client.post(f"/refuges/me/orders/{oid}/cancel", headers=user["h"],
                       json={"reason": "sin_inventario", "note": "Se nos acabó la talla M."}).status_code == 404
    r = client.post(f"/refuges/me/orders/{oid}/cancel", headers=seller["h"],
                    json={"reason": "sin_inventario", "note": "Se nos acabó la talla M."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "refuge"
    assert r.json()["cancel_note"] == "Se agotó el producto: Se nos acabó la talla M."
    assert mp["refunds"][-1] == {"payment_id": str(payment["id"]), "access_token": seller["seller_token"]}
    assert _stock(product["id"]) == 4 and Decimal(r.json()["refund_amount"]) == Decimal("120.00")
    buyer_note = _notifs(_user_id(user["email"]), "order_cancelled", oid)[0]
    assert "Se nos acabó la talla M." in buyer_note.body and "equivalente" in buyer_note.body
    assert client.get(f"/orders/{oid}", headers=user["h"]).json()["cancel_note"].startswith("Se agotó")
    # Ya enviado: el refugio no puede cancelarlo
    sent = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, sent)
    client.patch(f"/refuges/me/orders/{sent['id']}", headers=seller["h"],
                 json={"status": "shipped", "carrier": "DHL", "tracking_number": "X1"})
    assert client.post(f"/refuges/me/orders/{sent['id']}/cancel", headers=seller["h"],
                       json={"reason": "otro", "note": "Cambiamos de opinión"}).status_code == 409

    third = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, third)
    assert client.post(f"/admin/orders/{third['id']}/cancel", headers=user["h"],
                       json={"reason": "sospecha_fraude", "note": "Tarjeta reportada"}).status_code == 403
    r = client.post(f"/admin/orders/{third['id']}/cancel", headers=admin["h"],
                    json={"reason": "sospecha_fraude", "note": "Mercado Pago marcó el pago como riesgoso."})
    assert r.status_code == 200 and r.json()["cancel_reason"] == "admin" and r.json()["status"] == "cancelled"


def test_dispatch_deadline_warns_then_auto_cancels(client, user, mp, monkeypatch):
    seller = _make_seller(client)
    product = _product(client, seller, price=99, handling_days=2)
    order = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, order, collector=seller["mp_user_id"])
    oid = order["id"]
    paid = datetime.datetime(2026, 10, 5, 17, 0)  # lunes 5-oct (11:00 CDMX): despacho hasta el miércoles 7
    _update_order(oid, paid_at=paid)
    o = _order(oid)
    db = _db()
    try:
        fresh = db.query(Order).filter(Order.id == oid).first()
        due, cancel_at = order_flow.dispatch_deadline(fresh), order_flow.dispatch_cancel_at(fresh)
    finally:
        db.close()
    assert order_flow._local_date(due) == datetime.date(2026, 10, 7)
    assert order_flow._local_date(cancel_at) == datetime.date(2026, 10, 9)  # + 2 días hábiles de gracia
    assert o.status == "paid"
    run = lambda db, now: order_flow.enforce_dispatch_deadlines(db, now=now, order_ids=[oid])  # noqa: E731
    db = _db()
    try:
        assert run(db, due - datetime.timedelta(hours=1)) == {"warned": 0, "cancelled": 0, "failed": 0}
        assert run(db, due + datetime.timedelta(hours=1))["warned"] == 1
        assert run(db, due + datetime.timedelta(hours=2))["warned"] == 0  # se avisa una sola vez
    finally:
        db.close()
    assert _notifs(seller["user_id"], "order_dispatch_overdue", oid)
    assert _notifs(_user_id(user["email"]), "order_dispatch_overdue", oid)
    db = _db()
    try:
        assert run(db, cancel_at + datetime.timedelta(hours=1))["cancelled"] == 1
    finally:
        db.close()
    o = _order(oid)
    assert o.status == "cancelled" and o.cancel_reason == "dispatch_timeout" and o.refunded_at
    assert _stock(product["id"]) == 10
    assert any("no lo envió a tiempo" in n.body for n in _notifs(_user_id(user["email"]), "order_cancelled", oid))


def test_beat_has_dispatch_task():
    from app.celery_app import celery_app
    from app.tasks import payments as payment_tasks

    beat = celery_app.conf.beat_schedule
    assert beat["orders-dispatch-deadline-daily"]["task"] == payment_tasks.enforce_dispatch_deadlines.name


# --------------------------------------------------------------------------- S6 reembolso en otro mes
def test_refund_in_next_month_does_not_change_closed_month(client, user, mp, monkeypatch):
    seller = _make_seller(client)
    product = _product(client, seller, price="1000")
    order = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, order)
    p1 = _period()
    year, month = map(int, p1.split("-"))
    p2 = f"{year + (month == 12):04d}-{1 if month == 12 else month + 1:02d}"
    _update_order(order["id"], paid_at=_in_period(p1))
    before = client.get("/refuges/me/statements", headers=seller["h"], params={"period": p1}).json()
    db = _db()
    try:
        order_flow.execute_refund(db, order["id"], Decimal("400"), by="admin")
    finally:
        db.close()
    _move_refunds(order["id"], _in_period(p2))
    after = client.get("/refuges/me/statements", headers=seller["h"], params={"period": p1}).json()
    totals = lambda st: {k: v for k, v in st.items() if k not in ("orders", "refunds")}  # noqa: E731
    assert totals(after) == totals(before) and not after["refunds"]  # el mes cerrado (y facturado) no cambia
    assert Decimal(str(before["gross"])) == Decimal("1000") and Decimal(str(before["platform_fee"])) == Decimal("100")
    nxt = client.get("/refuges/me/statements", headers=seller["h"], params={"period": p2}).json()
    assert nxt["orders_count"] == 0 and Decimal(str(nxt["refunds_total"])) == Decimal("400")
    assert Decimal(str(nxt["platform_fee"])) == Decimal("-40")  # MP regresa la parte proporcional de la comisión
    assert Decimal(str(nxt["net_received"])) == Decimal("-360")
    assert nxt["refunds"][0]["is_full"] is False and Decimal(str(nxt["refunds"][0]["fee_reversed"])) == Decimal("40")
    monkeypatch.setattr(settings, "pac_provider", "")
    db = _db()
    try:
        assert invoicing.generate_period_cfdis(db, p2)["credit_notes_needed"] >= 1
    finally:
        db.close()


# --------------------------------------------------------------------------- S5d retenciones
def test_retention_defaults_follow_lif_2026():
    assert settings.retencion_isr_percent == 2.5 and settings.retencion_iva_percent == 50.0
    assert settings.retencion_personas_morales is True


# --------------------------------------------------------------------------- regresiones
def test_account_deletion_disconnects_mercadopago_and_export_has_fiscal(client, monkeypatch, mp):
    fiscal = {"person_type": "moral", "rfc": "PFI010101AB2", "legal_name": "PATITAS AC", "regimen_fiscal": "603",
              "postal_code": "06700"}
    seller = _make_seller(client, fiscal=fiscal)
    data = client.get("/users/me/export", headers=seller["h"]).json()
    assert data["refuge_fiscal_profiles"][0]["rfc"] == "PFI010101AB2"
    account = data["refuge_payment_accounts"][0]
    assert account["status"] == "connected" and "access_token_enc" not in account and "refresh_token_enc" not in account
    assert "APP_USR" not in str(data["refuge_payment_accounts"])
    db = _db()
    try:
        user = db.query(User).filter(User.email == seller["email"]).first()
        account_deletion.purge_user_content(db, user, datetime.datetime.utcnow())
        db.commit()
        acc = db.query(RefugePaymentAccount).filter(RefugePaymentAccount.refuge_id == seller["refuge_id"]).first()
        assert acc.status == "disconnected" and acc.access_token_enc is None and acc.refresh_token_enc is None
        assert db.query(Refuge.status).filter(Refuge.id == seller["refuge_id"]).scalar() == "closed"
    finally:
        db.close()

    # La tarea semanal no renueva tokens de refugios que no están aprobados
    other = _make_seller(client, name="Refugio Suspendido")
    db = _db()
    try:
        acc = db.query(RefugePaymentAccount).filter(RefugePaymentAccount.refuge_id == other["refuge_id"]).first()
        acc.expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=5)
        db.query(Refuge).filter(Refuge.id == other["refuge_id"]).update({Refuge.status: "closed"})
        db.commit()
        calls = []
        monkeypatch.setattr(mercadopago_oauth, "refresh_account", lambda db_, a: calls.append(a.refuge_id))
        mercadopago_oauth.refresh_expiring_accounts(db)
        assert other["refuge_id"] not in calls
    finally:
        db.close()


def test_admin_orders_list_is_eager_loaded(client, user, admin):
    from sqlalchemy import event

    from app.database import engine

    seller = _make_seller(client)
    product = _product(client, seller, price=30)
    for _ in range(3):
        _buy(client, user, [(product, 1)])
    statements_run = []
    listener = lambda *a, **kw: statements_run.append(1)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        r = client.get("/admin/orders", headers=admin["h"], params={"limit": 50})
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert r.status_code == 200 and len(r.json()) >= 3
    assert len(statements_run) < 20, len(statements_run)  # sin N+1 (antes: varias consultas por pedido)
