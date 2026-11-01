"""Reglas de negocio con efecto legal (services/reglas.py; contratos L-tienda, L-donativos, L-adopcion, L-fb, L-vet).

B1 tienda: comisión 0 % por defecto, régimen de plataformas en producción, campos obligatorios, productos prohibidos
retenidos, identidad del vendedor, comprobante, bonificación de 20 % y recordatorio de facturas a 24 h.
B2 donativos: sin puntos, sin autodonaciones, topes, aviso de deducibilidad, alertas antilavado y constancia.
B3 adopción: cobros y rifas retenidos para revisión; resguardo de perros encontrados.
B4 Facebook: interruptor legal, nombres de personas fuera, borrado real, etiqueta de importado y Apify sin copias.
B5 veterinarias: el bloque de Google nunca junto al mapa y la insignia como dice la página.
"""
import datetime
import os
import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import Settings, settings
from app.database import SessionLocal
from app.models import (
    ContentReport, Dog, Donation, DonationAmlFlag, LostReport, Notification, Order, OrderBonus, OrderInvoice,
    PointLog, Product, Refuge, RefugeFiscalProfile, User,
)
from app.services import facebook_groups as fbg, payment_flow, reglas
from conftest import _register
from test_tienda import (  # noqa: F401 - fixtures (admin, emails, mp, _deactivate_products) y utilidades
    _buy, _db, _deactivate_products, _make_seller, _notifs, _pay, _product, _update_order, _user_id, admin, emails, mp,
)

REPO = Path(os.environ.get("PATITASFIND_REPO") or Path(__file__).resolve().parents[2])
APP_DIR = REPO / "app"
needs_frontend = pytest.mark.skipif(not (APP_DIR / "veterinarias.js").exists(),
                                    reason="los archivos de app/ no están montados en el contenedor")
FISICA = {"person_type": "fisica", "rfc": "MOPA800101AB3", "legal_name": "ANA MORALES PEREZ", "regimen_fiscal": "612",
          "postal_code": "03100"}


def _now():
    return datetime.datetime.utcnow()


def _get(model, obj_id):
    db = _db()
    try:
        row = db.query(model).filter(model.id == obj_id).first()
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


def _set_profile(refuge_id, **fields):
    db = _db()
    try:
        db.add(RefugeFiscalProfile(refuge_id=refuge_id, **{**FISICA, **fields}))
        db.commit()
    finally:
        db.close()


def _prod_settings(**overrides):
    base = dict(environment="production", secret_key="x" * 64, public_base_url="https://guauwoow.com",
                cors_origins="https://guauwoow.com", database_url="postgresql+psycopg2://u:clave-segura@db/p",
                postgres_password="clave-segura", sms_provider="smsmasivos", smsmasivos_api_key="k",
                smtp_host="smtp.mx", smtp_from="a@b.mx", private_files_key="a" * 44, mfa_required_for_admins=False)
    base.update(overrides)
    return Settings.model_construct(**base)


def _problems(**overrides) -> str:
    return "\n".join(_prod_settings(**overrides).production_problems())


# =========================================================================== B1 tienda
def test_commission_defaults_to_zero_and_needs_tax_regime_in_production():
    assert Settings.model_fields["mercadopago_marketplace_fee_percent"].default == 0.0
    assert Settings.model_fields["platform_tax_regime_ready"].default is False
    assert "PLATFORM_TAX_REGIME_READY" in _problems(mercadopago_marketplace_fee_percent=10)
    assert "PLATFORM_TAX_REGIME_READY" in _problems(mercadopago_donation_fee_percent=3)
    assert "PLATFORM_TAX_REGIME_READY" not in _problems(mercadopago_marketplace_fee_percent=10,
                                                        platform_tax_regime_ready=True)
    assert "PLATFORM_TAX_REGIME_READY" not in _problems(mercadopago_marketplace_fee_percent=0)


def test_no_withholding_without_commission(client, monkeypatch):
    seller = _make_seller(client)
    _set_profile(seller["refuge_id"])
    db = _db()
    try:
        refuge = db.query(Refuge).filter(Refuge.id == seller["refuge_id"]).first()
        monkeypatch.setattr(settings, "mercadopago_marketplace_fee_percent", 0.0)
        split = payment_flow.compute_split(Decimal("488.80"), refuge)
        assert split["isr_retenido"] == 0 and split["iva_retenido"] == 0 and split["marketplace_fee"] == 0
        # Con comisión y fuera de producción sí se retiene a la persona física (fiscal-tienda-09)
        monkeypatch.setattr(settings, "mercadopago_marketplace_fee_percent", 10.0)
        assert payment_flow.compute_split(Decimal("488.80"), refuge)["isr_retenido"] > 0
        # En producción sin el régimen confirmado no se retiene nada
        monkeypatch.setattr(settings, "environment", "production")
        assert payment_flow.retention_applies(refuge) is False
    finally:
        monkeypatch.setattr(settings, "environment", "development")
        db.close()


def test_products_require_category_and_warranty(client):
    seller = _make_seller(client)
    base = {"name": f"Playera {uuid.uuid4().hex[:4]}", "price": 250, "stock": 5}
    r = client.post("/products", headers=seller["h"], json=base)
    assert r.status_code == 400 and "categoría" in r.json()["detail"]
    r = client.post("/products", headers=seller["h"], json={**base, "category": "promocionales"})
    assert r.status_code == 400 and "garantía" in r.json()["detail"]
    r = client.post("/products", headers=seller["h"], json={**base, "category": "promocionales", "warranty_days": 30,
                                                             "warranty_text": "Cubre defectos de fabricación"})
    assert r.status_code == 400 and "90 días" in r.json()["detail"]
    r = client.post("/products", headers=seller["h"], json={**base, "category": "nada", "warranty_text": "x"})
    assert r.status_code == 400
    p = _product(client, seller, name=base["name"], category="promocionales", warranty_days=90,
                 warranty_text="Cubre defectos de fabricación en uso normal; se hace válida desde Mis pedidos.")
    assert p["category"] == "promocionales" and p["warranty_days"] == 90 and p["is_hidden"] is False
    assert p["category_label"].startswith("Artículos promocionales") and p["review"] is None
    assert any(x["id"] == p["id"] for x in client.get("/products", params={"refuge_id": seller["refuge_id"]}).json())
    # Al editar el contenido también se exigen (un producto anterior sin categoría la completa aquí)
    r = client.patch(f"/products/{p['id']}", headers=seller["h"], json={"warranty_days": 10})
    assert r.status_code == 400
    assert client.patch(f"/products/{p['id']}", headers=seller["h"], json={"stock": 3}).status_code == 200
    cfg = client.get("/cumplimiento/reglas").json()
    assert {c["key"] for c in cfg["shop"]["categories"]} == set(reglas.PRODUCT_CATEGORIES)


def test_prohibited_products_are_held_for_review(client, admin):
    seller = _make_seller(client)
    p = _product(client, seller, name="Collar de ahorque para adiestramiento", category="accesorios_juguetes")
    assert p["is_hidden"] is True and p["review"]["status"] == "en_revision"
    assert p["review"]["reason"] == "producto_prohibido" and "collares que lastiman" in p["review"]["terms"]
    assert "productos prohibidos" in p["review"]["message"]
    assert client.get(f"/products/{p['id']}").status_code == 404  # oculto para el público
    assert client.get(f"/products/{p['id']}", headers=seller["h"]).json()["review"]["status"] == "en_revision"
    db = _db()
    try:
        auto = db.query(ContentReport).filter(ContentReport.target_type == "product", ContentReport.target_id == p["id"],
                                              ContentReport.reason == reglas.HOLD_REPORT_REASON).one()
        assert auto.status == "open" and auto.reporter_id is None
    finally:
        db.close()
    assert _notifs(seller["user_id"], "content_held")
    held = client.get("/admin/reglas/retenciones", headers=admin["h"]).json()
    assert any(h["target_type"] == "product" and h["target_id"] == p["id"] for h in held)
    assert client.get("/admin/reglas/retenciones", headers=seller["h"]).status_code == 403

    # Reactivarlo no lo saca de revisión
    r = client.patch(f"/products/{p['id']}", headers=seller["h"], json={"is_active": True})
    assert r.json()["is_hidden"] is True
    # Rechazar exige motivo; liberar lo publica tal cual
    r = client.post(f"/admin/reglas/retenciones/product/{p['id']}", headers=admin["h"], json={"decision": "rechazar"})
    assert r.status_code == 400
    r = client.post(f"/admin/reglas/retenciones/product/{p['id']}", headers=admin["h"], json={"decision": "liberar"})
    assert r.status_code == 200 and r.json()["review_hold"] == reglas.HOLD_RELEASED and r.json()["is_hidden"] is False
    assert client.get(f"/products/{p['id']}").status_code == 200
    # Editar con las mismas palabras aprobadas no vuelve a retener; una palabra nueva sí
    r = client.patch(f"/products/{p['id']}", headers=seller["h"], json={"description": "Collar de ahorque, nylon"})
    assert r.json()["is_hidden"] is False
    r = client.patch(f"/products/{p['id']}", headers=seller["h"], json={"description": "Incluye vacuna antirrábica"})
    assert r.json()["is_hidden"] is True and "medicamentos" in r.json()["review"]["terms"]
    r = client.post(f"/admin/reglas/retenciones/product/{p['id']}", headers=admin["h"],
                    json={"decision": "rechazar", "notas": "No se venden vacunas ni medicamentos."})
    assert r.status_code == 200 and r.json()["review_hold"] == reglas.HOLD_REJECTED
    assert client.get(f"/products/{p['id']}", headers=seller["h"]).json()["review"]["status"] == "rechazado"
    # Editar algo rechazado lo regresa a revisión
    r = client.patch(f"/products/{p['id']}", headers=seller["h"], json={"description": "Collar de nylon"})
    assert r.json()["review"]["status"] == "en_revision" and r.json()["is_hidden"] is True


@pytest.mark.parametrize("name,description,category,reason", [
    ("Cachorro en venta", None, "otro", "producto_prohibido"),
    ("Boletos para la rifa del refugio", None, "impresos", "producto_prohibido"),
    ("Playera Disney", "Algodón", "promocionales", "producto_prohibido"),
    ("Galletas caseras", "Premios hechos en casa", "alimento_industrializado", "producto_prohibido"),
    ("Croquetas premium", "Número SENASICA A-1234", "alimento_industrializado", "categoria_con_requisitos"),
    ("Playera del refugio", "Algodón 100 %, diseño propio", "promocionales", None),
])
def test_product_review_rules(name, description, category, reason):
    got, terms = reglas.product_review(category, name, description)
    assert got == reason, terms


def test_seller_identity_before_paying(client, user):
    seller = _make_seller(client)
    _set_profile(seller["refuge_id"])
    assert client.get(f"/products/sellers/{seller['refuge_id']}/identity").status_code == 401
    # Solo de un refugio que hoy vende algo: sin productos no se expone su RFC
    assert client.get(f"/products/sellers/{seller['refuge_id']}/identity", headers=user["h"]).status_code == 404
    _product(client, seller)
    ident = client.get(f"/products/sellers/{seller['refuge_id']}/identity", headers=user["h"]).json()
    assert ident["legal_name"] == FISICA["legal_name"] and ident["rfc"] == FISICA["rfc"] and ident["iva"] == "incluido"
    donataria = _make_seller(client)
    _set_profile(donataria["refuge_id"], person_type="moral", rfc="ABC010101AB1", legal_name="PATITAS AC",
                 regimen_fiscal="603", is_donataria=True)
    _product(client, donataria)
    assert client.get(f"/products/sellers/{donataria['refuge_id']}/identity", headers=user["h"]).json()["iva"] == "exento"
    assert reglas.iva_included(Decimal("116"), "incluido") == Decimal("16.00")


def test_receipt_page_and_email_after_payment(client, user, mp, monkeypatch, emails):
    seller = _make_seller(client)
    _set_profile(seller["refuge_id"])
    monkeypatch.setattr(settings, "emisor_nombre", "PATITASFIND SA DE CV")
    monkeypatch.setattr(settings, "operator_address", "Av. Reforma 1, CDMX")
    product = _product(client, seller, price=232, warranty_days=90,
                       warranty_text="Cubre defectos de fabricación en uso normal; desde Mis pedidos.")
    order = _buy(client, user, [(product, 1)])
    assert client.get(f"/orders/{order['id']}/comprobante", headers=user["h"]).status_code == 409  # sin pago
    payment = _pay(monkeypatch, order, collector=seller["mp_user_id"])
    r = client.get(f"/orders/{order['id']}/comprobante", headers=user["h"])
    assert r.status_code == 200, r.text
    rc = r.json()
    assert rc["folio"] == f"PF-{order['id']:06d}" and rc["seller"]["rfc"] == FISICA["rfc"]
    assert rc["operator"]["legal_name"] == "PATITASFIND SA DE CV" and rc["operator"]["address"] == "Av. Reforma 1, CDMX"
    assert rc["payment"]["payment_id"] == str(payment["id"]) and rc["items"][0]["warranty_days"] == 90
    assert Decimal(rc["iva_amount"]) == Decimal("32.00") and rc["profeco"]["phone"]
    assert "revocar" in rc["rights"]["revocation"] and "20 %" in rc["rights"]["claims"]
    assert rc["terms"]["url"].endswith("/app/legal/terminos-tienda.html") and "no es una factura" in rc["notice"]
    other = _register(client, "Otra persona")
    assert client.get(f"/orders/{order['id']}/comprobante", headers=other["h"]).status_code == 403
    mails = [a for t, a in emails if t == "app.tasks.notifications.send_notification_email" and a[0] == user["email"]]
    receipt_mail = [a for a in mails if a[1].startswith("Comprobante de tu pedido")]
    assert len(receipt_mail) == 1 and rc["folio"] in receipt_mail[0][2] and "PROFECO" in receipt_mail[0][2]
    assert "RFC " + FISICA["rfc"] in receipt_mail[0][2] and receipt_mail[0][3].endswith("receipt=1")


def _paid_delivered(client, user, seller, monkeypatch, price=300):
    product = _product(client, seller, price=price, stock=5)
    order = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, order, collector=seller["mp_user_id"])
    oid = order["id"]
    client.patch(f"/refuges/me/orders/{oid}", headers=seller["h"], json={"status": "shipped", "carrier": "DHL",
                                                                         "tracking_number": f"DHL{oid}"})
    assert client.post(f"/orders/{oid}/confirm-delivery", headers=user["h"]).status_code == 200
    return oid


def test_defect_claim_registers_20_percent_bonus_for_seller(client, user, mp, monkeypatch, admin):
    seller = _make_seller(client)
    oid = _paid_delivered(client, user, seller, monkeypatch, price=300)
    r = client.post(f"/orders/{oid}/return", headers=user["h"], json={"reason": "defectuoso", "details": "Llegó roto el broche"})
    assert r.status_code == 200
    r = client.post(f"/refuges/me/orders/{oid}/return-decision", headers=seller["h"], json={"approve": True, "note": "Procede"})
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    bonus = _get_bonus(oid)
    assert bonus.amount == Decimal("60.00") and bonus.percent == Decimal("20.00") and bonus.status == "pendiente"
    assert bonus.due_at > _now() + datetime.timedelta(days=14)
    buyer_id = _user_id(user["email"])
    assert _notifs(buyer_id, "order_bonus_registered", oid) and _notifs(seller["user_id"], "order_bonus_due", oid)
    assert _notifs(admin["id"], "order_bonus_due", oid)
    detail = client.get(f"/orders/{oid}", headers=user["h"]).json()
    assert Decimal(detail["bonus_info"]["amount"]) == Decimal("60.00")
    assert "bonus_registered" in [e["status"] for e in detail["timeline"]]
    assert any(b["order_id"] == oid for b in client.get("/refuges/me/bonificaciones", headers=seller["h"]).json())
    # El refugio registra el pago con referencia; el comprador recibe aviso
    assert client.post(f"/refuges/me/orders/{oid}/bonificacion", headers=seller["h"], json={"referencia": "x"}).status_code == 422
    r = client.post(f"/refuges/me/orders/{oid}/bonificacion", headers=seller["h"], json={"referencia": "SPEI 123456"})
    assert r.status_code == 200 and r.json()["status"] == "pagada"
    assert _notifs(buyer_id, "order_bonus_paid", oid)
    assert client.post(f"/refuges/me/orders/{oid}/bonificacion", headers=seller["h"],
                       json={"referencia": "SPEI 123456"}).status_code == 409
    # Seguimiento del equipo: reabrir y marcar que no procede (con evidencia)
    bid = bonus.id
    assert client.post(f"/admin/reglas/bonificaciones/{bid}", headers=admin["h"], json={"accion": "reabrir"}).json()["status"] == "pendiente"
    assert client.post(f"/admin/reglas/bonificaciones/{bid}", headers=admin["h"],
                       json={"accion": "improcedente", "nota": "corto"}).status_code == 400
    r = client.post(f"/admin/reglas/bonificaciones/{bid}", headers=admin["h"],
                    json={"accion": "improcedente", "nota": "El daño se debió a mal uso según las fotos del comprador."})
    assert r.status_code == 200 and r.json()["status"] == "improcedente"
    assert any(b["id"] == bid for b in client.get("/admin/reglas/bonificaciones?status=all", headers=admin["h"]).json())
    # Revocación por cambio de opinión: sin bonificación
    other = _paid_delivered(client, user, seller, monkeypatch)
    client.post(f"/orders/{other}/return", headers=user["h"], json={"reason": "arrepentimiento"})
    client.post(f"/refuges/me/orders/{other}/return-decision", headers=seller["h"], json={"approve": True, "note": "Ok"})
    assert _get_bonus(other) is None


def _get_bonus(order_id):
    db = _db()
    try:
        row = db.query(OrderBonus).filter(OrderBonus.order_id == order_id).first()
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


def test_overdue_bonus_reminder(client, user, mp, monkeypatch, admin):
    seller = _make_seller(client)
    oid = _paid_delivered(client, user, seller, monkeypatch)
    client.post(f"/orders/{oid}/return", headers=user["h"], json={"reason": "no_corresponde", "details": "Pedí talla M"})
    client.post(f"/refuges/me/orders/{oid}/return-decision", headers=seller["h"], json={"approve": True, "note": "Procede"})
    db = _db()
    try:
        db.query(OrderBonus).filter(OrderBonus.order_id == oid).update({OrderBonus.due_at: _now() - datetime.timedelta(days=1)})
        db.commit()
        assert reglas.remind_overdue_bonuses(db) >= 1
        assert reglas.remind_overdue_bonuses(db) == 0 or _get_bonus(oid).reminded_at  # una vez por semana
    finally:
        db.close()
    assert _notifs(seller["user_id"], "order_bonus_overdue", oid)


def test_invoice_requests_reminded_after_24h(client, user, mp, monkeypatch, admin):
    seller = _make_seller(client)
    product = _product(client, seller, price=150)
    order = _buy(client, user, [(product, 1)])
    _pay(monkeypatch, order, collector=seller["mp_user_id"])
    db = _db()
    try:
        inv = OrderInvoice(order_id=order["id"], refuge_id=seller["refuge_id"], user_id=_user_id(user["email"]),
                           status="requested", rfc="MOPA800101AB3", legal_name="ANA MORALES", regimen_fiscal="605",
                           postal_code="03100", uso_cfdi="G03", email="ana@ejemplo.mx",
                           requested_at=_now() - datetime.timedelta(hours=25))
        db.add(inv)
        db.commit()
        out = reglas.remind_invoice_requests(db)
        assert out["reminded"] >= 1
        db.refresh(inv)
        assert inv.reminded_at is not None and inv.escalated_at is None
        assert reglas.remind_invoice_requests(db)["reminded"] == 0  # un solo recordatorio
        inv.requested_at = _now() - datetime.timedelta(hours=73)
        db.commit()
        assert reglas.remind_invoice_requests(db)["escalated"] >= 1
        inv_id = inv.id
    finally:
        db.close()
    assert _notifs(seller["user_id"], "invoice_overdue", order["id"])
    late = client.get("/admin/reglas/facturas-atrasadas", headers=admin["h"]).json()
    assert any(i["order_id"] == order["id"] and i["hours"] >= 72 for i in late)
    assert _get(OrderInvoice, inv_id).escalated_at is not None


# =========================================================================== B2 donativos
def test_donations_no_points_caps_self_and_tax_notice(client, user, monkeypatch):
    monkeypatch.setattr(settings, "donation_max_mxn", 1000.0)
    monkeypatch.setattr(settings, "donation_daily_max_mxn", 1500.0)
    seller = _make_seller(client)
    before = _get(Refuge, seller["refuge_id"]).points
    r = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 1001})
    assert r.status_code == 400 and "tope por donativo" in r.json()["detail"]
    r = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 900})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "approved" and d["deducible"] is False and "no es deducible" in d["aviso_fiscal"]
    r = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 700})
    assert r.status_code == 400 and "tope diario" in r.json()["detail"]
    assert client.post("/payments/donations", headers=user["h"],
                       json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 600}).status_code == 201  # 1,500 justos
    # Sin puntos de ranking ni registro de puntos
    assert _get(Refuge, seller["refuge_id"]).points == before
    db = _db()
    try:
        assert db.query(PointLog).filter(PointLog.refuge_id == seller["refuge_id"],
                                         PointLog.action.in_(("donation", "donation_refund"))).count() == 0
        bodies = [n.body for n in db.query(Notification).filter(Notification.user_id == seller["user_id"],
                                                                Notification.type == "donation_received")]
        assert bodies and not any("puntos" in b for b in bodies)
    finally:
        db.close()
    # Nadie se dona a sí mismo
    r = client.post("/payments/donations", headers=seller["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 50})
    assert r.status_code == 400 and "propio refugio" in r.json()["detail"]
    # Donataria: aviso de deducible con CFDI
    don = _make_seller(client)
    _set_profile(don["refuge_id"], person_type="moral", rfc="ABC010101AB1", legal_name="PATITAS AC", regimen_fiscal="603",
                 is_donataria=True)
    assert client.get(f"/refuges/{don['refuge_id']}").json()["is_donataria"] is True
    r = client.post("/payments/donations", headers=_register(client, "Otra donante")["h"],
                    json={"accepted_policy": True, "refuge_id": don["refuge_id"], "amount": 100})
    assert r.json()["deducible"] is True and "CFDI" in r.json()["aviso_fiscal"]
    cfg = client.get("/cumplimiento/reglas").json()["donations"]
    assert cfg["max_mxn"] == 1000.0 and cfg["daily_max_mxn"] == 1500.0 and cfg["points"] is False


def test_donation_aml_thresholds_alert_refuge_and_admins(client, user, monkeypatch, admin):
    # UMA de 1 peso: aproximación 802.50, identificación 1,605 y aviso 3,210
    monkeypatch.setattr(settings, "uma_daily_mxn", 1.0)
    monkeypatch.setattr(settings, "donation_max_mxn", 5000.0)
    monkeypatch.setattr(settings, "donation_daily_max_mxn", 10000.0)
    seller = _make_seller(client)
    uid = _user_id(user["email"])
    client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 500})
    assert _flags(uid, seller["refuge_id"]) == []
    client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 400})
    assert _flags(uid, seller["refuge_id"]) == ["aproximacion"]
    client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 800})
    assert _flags(uid, seller["refuge_id"]) == ["aproximacion", "identificacion"]
    client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": seller["refuge_id"], "amount": 100})
    assert _flags(uid, seller["refuge_id"]) == ["aproximacion", "identificacion"]  # una alerta por nivel y periodo
    notes = _notifs(seller["user_id"], "donation_aml_threshold")
    assert len(notes) == 2 and "LFPIORPI" in notes[-1].body and "Donante anónimo" in notes[-1].body
    assert user["email"] not in notes[-1].body  # el refugio no ve el correo de quien dona
    flags = client.get("/admin/reglas/alertas-donativos", headers=admin["h"]).json()
    mine = [f for f in flags if f["refuge"] and f["refuge"]["id"] == seller["refuge_id"]]
    assert {f["level"] for f in mine} == {"aproximacion", "identificacion"}
    r = client.post(f"/admin/reglas/alertas-donativos/{mine[0]['id']}/revisar", headers=admin["h"], json={"nota": "ok"})
    assert r.status_code == 200 and r.json()["reviewed_at"]


def _flags(user_id, refuge_id):
    db = _db()
    try:
        return [f.level for f in db.query(DonationAmlFlag).filter(DonationAmlFlag.user_id == user_id,
                                                                    DonationAmlFlag.refuge_id == refuge_id)
                .order_by(DonationAmlFlag.id)]
    finally:
        db.close()


def test_donation_policy_checkbox_is_recorded(client, user):
    from app.models import LegalAcceptance

    seller = _make_seller(client)
    r = client.post("/payments/donations", headers=user["h"],
                    json={"refuge_id": seller["refuge_id"], "amount": 50, "accepted_policy": True})
    assert r.status_code == 201, r.text
    db = _db()
    try:
        rows = db.query(LegalAcceptance).filter(LegalAcceptance.user_id == _user_id(user["email"]),
                                                LegalAcceptance.slug == "donativos").all()
        assert rows and rows[-1].method == "donativo"
    finally:
        db.close()


# =========================================================================== B3 adopción
def _dog(client, who, **extra):
    body = {"name": "Canela", "description": "Muy cariñosa, esterilizada y vacunada.", "city": "Puebla", **extra}
    r = client.post("/dogs", headers=who["h"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_adoption_posts_with_fees_or_raffles_are_held(client, user, owner, admin):
    clean = _dog(client, owner)
    assert clean["is_hidden"] is False and clean["review"] is None
    held = _dog(client, owner, description="Se entrega con cuota de recuperación de $500 y se aparta con depósito.")
    assert held["is_hidden"] is True and held["review"]["reason"] == "cobro_adopcion"
    assert {"cuota", "$", "recuperación", "apartado", "depósito"} <= set(held["review"]["terms"])
    assert "adoptar es gratis" in held["review"]["message"]
    assert client.get(f"/dogs/{held['id']}", headers=user["h"]).status_code == 404
    assert client.get(f"/dogs/{held['id']}", headers=owner["h"]).json()["review"]["status"] == "en_revision"
    raffle = _dog(client, owner, description="Gran rifa: el ganador se lleva un perrito de premio")
    assert raffle["review"]["reason"] == "rifa" and "rifa" in raffle["review"]["terms"]
    # Liberar publica tal cual; una edición con una palabra nueva vuelve a retener
    r = client.post(f"/admin/reglas/retenciones/dog/{held['id']}", headers=admin["h"], json={"decision": "liberar"})
    assert r.status_code == 200 and client.get(f"/dogs/{held['id']}", headers=user["h"]).status_code == 200
    r = client.patch(f"/dogs/{held['id']}", headers=owner["h"], json={"description": held["description"] + " Precio especial."})
    assert r.json()["is_hidden"] is True and "precio" in r.json()["review"]["terms"]
    # Editar un texto limpio no retiene
    r = client.patch(f"/dogs/{clean['id']}", headers=owner["h"], json={"description": "Le encanta pasear."})
    assert r.json()["is_hidden"] is False
    assert _notifs(_user_id(owner["email"]), "content_held")


def _found_report(reporter_email, days_ago=0, report_type="found", status="active"):
    db = _db()
    try:
        uid = db.query(User.id).filter(User.email == reporter_email).scalar()
        r = LostReport(reporter_id=uid, dog_name="Encontrado", report_type=report_type, photos=[], status=status,
                       source="app", city="Puebla", created_at=_now() - datetime.timedelta(days=days_ago))
        db.add(r)
        db.commit()
        return r.id
    finally:
        db.close()


def test_found_dogs_wait_hold_period_with_checklist(client, user, owner):
    rid = _found_report(owner["email"])
    dog = _dog(client, owner, found_report_id=rid)
    hold = dog["found_hold"]
    assert dog["status"] == "unavailable" and hold["active"] is True
    assert set(hold["missing"]) == {"plazo", "microchip", "autoridad"} and "30 días" in hold["message"]
    # No se ofrece en adopción: ni en su ficha pública, ni con solicitudes, ni pasándolo a disponible
    assert client.get(f"/dogs/{dog['id']}", headers=user["h"]).status_code == 404
    assert client.post(f"/dogs/{dog['id']}/like", headers=user["h"]).status_code == 404
    r = client.patch(f"/dogs/{dog['id']}/status", headers=owner["h"], json={"status": "available"})
    assert r.status_code == 409 and "microchip" in r.json()["detail"]
    # Lista de revisión: microchip y aviso a la autoridad (con constancia)
    assert client.patch(f"/dogs/{dog['id']}", headers=owner["h"], json={"authority_notified": True}).status_code == 400
    r = client.patch(f"/dogs/{dog['id']}", headers=owner["h"], json={
        "microchip_checked": True, "microchip_result": "sin_chip", "authority_notified": True,
        "authority_notice": "Centro de Atención Canina, folio 77"})
    assert r.status_code == 200 and r.json()["found_hold"]["missing"] == ["plazo"]
    assert client.patch(f"/dogs/{dog['id']}/status", headers=owner["h"], json={"status": "available"}).status_code == 409
    # Cumplido el plazo desde el reporte, ya puede publicarse
    db = _db()
    try:
        db.query(LostReport).filter(LostReport.id == rid).update({LostReport.created_at: _now() - datetime.timedelta(days=31)})
        db.query(Dog).filter(Dog.id == dog["id"]).update({Dog.found_at: _now() - datetime.timedelta(days=31)})
        db.commit()
    finally:
        db.close()
    r = client.patch(f"/dogs/{dog['id']}/status", headers=owner["h"], json={"status": "available"})
    assert r.status_code == 200 and r.json()["status"] == "available" and r.json()["found_hold"]["active"] is False
    assert client.get(f"/dogs/{dog['id']}", headers=user["h"]).status_code == 200


def test_found_dog_report_rules(client, user, owner):
    others = _found_report(user["email"])
    r = client.post("/dogs", headers=owner["h"], json={"name": "Toby", "found_report_id": others})
    assert r.status_code == 403
    lost = _found_report(owner["email"], report_type="lost")
    assert client.post("/dogs", headers=owner["h"], json={"name": "Toby", "found_report_id": lost}).status_code == 400
    # Declarado como encontrado sin reporte: falta publicar el reporte de «encontrado» (y no se acorta el plazo)
    dog = _dog(client, owner, was_found=True, microchip_checked=True, authority_notified=True, authority_notice="Municipio")
    assert dog["status"] == "unavailable" and "reporte" in dog["found_hold"]["missing"]
    # Solo se liga un reporte publicado y activo; uno cerrado como reencuentro no sirve
    resolved = _found_report(owner["email"], days_ago=40, status="resolved")
    r = client.patch(f"/dogs/{dog['id']}", headers=owner["h"], json={"found_report_id": resolved})
    assert r.status_code == 400 and "activo" in r.json()["detail"]
    # Si el reporte ligado se cierra como reencuentro, bloquea la adopción
    active = _found_report(owner["email"], days_ago=40)
    r = client.patch(f"/dogs/{dog['id']}", headers=owner["h"], json={"found_report_id": active})
    assert r.status_code == 200 and "reencuentro" not in r.json()["found_hold"]["missing"]  # sin db en la vista
    db = _db()
    try:
        db.query(LostReport).filter(LostReport.id == active).update({LostReport.status: "resolved"})
        db.commit()
    finally:
        db.close()
    st = client.patch(f"/dogs/{dog['id']}/status", headers=owner["h"], json={"status": "available"})
    assert st.status_code == 409 and "reencuentro" in st.json()["detail"]
    # Quien publica un perro propio (no encontrado) no tiene resguardo
    assert _dog(client, owner)["found_hold"] is None


def test_found_hold_end_notice(client, owner):
    rid = _found_report(owner["email"], days_ago=30)
    dog = _dog(client, owner, found_report_id=rid)
    db = _db()
    try:
        db.query(Dog).filter(Dog.id == dog["id"]).update({Dog.found_at: _now() - datetime.timedelta(days=30, hours=2)})
        db.commit()
        assert reglas.notify_found_holds_ending(db) >= 1
    finally:
        db.close()
    notes = [n for n in _notifs(_user_id(owner["email"]), "found_hold_ended") if n.data.get("dog_id") == dog["id"]]
    assert notes and "microchip" in notes[0].body


# =========================================================================== B4 Facebook
def test_facebook_import_switch_and_legal_opinion(monkeypatch):
    assert Settings.model_fields["fb_groups_enabled"].default is False
    monkeypatch.setattr(settings, "apify_token", "token")
    monkeypatch.setattr(settings, "fb_groups_enabled", False)
    assert settings.fb_groups_provider_configured and not settings.fb_groups_active and fbg.get_provider() is None
    assert fbg.trigger_zone_fetch("Jalisco") is None
    monkeypatch.setattr(settings, "fb_groups_enabled", True)
    assert settings.fb_groups_active and fbg.get_provider() is not None
    assert "FB_GROUPS_LEGAL_OPINION_REF" in _problems(fb_groups_enabled=True)
    assert "FB_GROUPS_LEGAL_OPINION_REF" not in _problems(fb_groups_enabled=True,
                                                          fb_groups_legal_opinion_ref="Opinión escrita 2026-11-02")


@pytest.mark.parametrize("raw,gone,kept", [
    ("Soy Juan Pérez y encontré este perrito", ["Juan", "Pérez"], ["encontré este perrito"]),
    ("Me llamo Ana. Lo vi cerca del mercado", ["Ana"], ["Lo vi cerca del mercado"]),
    ("Estuvo con Rosa Martínez en el parque, con collar rojo", ["Rosa", "Martínez"], ["con collar rojo", "en el parque"]),
    ("Favor de contactar a María de la Luz Gómez", ["María", "Luz", "Gómez"], ["Favor de"]),
    ("Perrito perdido en Coyoacán.\nSaludos, Lupita", ["Lupita"], ["Perrito perdido en Coyoacán"]),
    ("Lo vio José Luis Hernández ayer", ["José", "Luis", "Hernández"], ["Lo vio", "ayer"]),
    ("Perrita encontrada muy asustada\nMaría López", ["María", "López"], ["Perrita encontrada"]),
    ("Se llama Rocky y anda por Roma Norte", [], ["Rocky", "Roma Norte"]),
])
def test_strip_person_names(raw, gone, kept):
    clean = fbg.strip_pii(raw)
    for piece in gone:
        assert piece not in clean, clean
    for piece in kept:
        assert piece in clean, clean


def test_purge_leaves_only_existence_and_takedown_record(client):
    url = f"https://www.facebook.com/groups/prueba/posts/{uuid.uuid4().int % 10 ** 12}"
    db = SessionLocal()
    try:
        r = LostReport(dog_name="Rocky", report_type="lost", description="Texto con datos", photos=[], status="active",
                       source="facebook", city="Roma Norte", state="Ciudad de México", latitude=19.41, longitude=-99.16,
                       contact_phone="5512345678", external_url=url, ai_analysis={"x": 1}, photo_signature={"y": 2})
        db.add(r)
        db.commit()
        fbg.purge_report_content(db, r)
        db.commit()
        db.refresh(r)
        assert r.description == fbg.PURGED_DESCRIPTION and r.dog_name == fbg.PURGED_NAME and r.photos == []
        assert (r.city, r.latitude, r.longitude, r.contact_phone, r.ai_analysis, r.photo_signature) == (None,) * 6
        assert r.external_url == url and r.purged_at and r.status == "expired" and r.state == "Ciudad de México"
    finally:
        db.close()


def test_imported_reports_expose_import_notice(client):
    db = SessionLocal()
    try:
        imported = LostReport(dog_name="Sin nombre", report_type="found", photos=[], status="active", source="facebook",
                              external_url=f"https://www.facebook.com/groups/x/posts/{uuid.uuid4().int % 10 ** 12}")
        own = LostReport(dog_name="Luna", report_type="lost", photos=[], status="active", source="app")
        db.add_all([imported, own])
        db.commit()
        ids = imported.id, own.id
    finally:
        db.close()
    assert client.get(f"/lost-reports/{ids[0]}").json()["import_notice"] == reglas.IMPORT_NOTICE
    assert client.get(f"/lost-reports/{ids[1]}").json()["import_notice"] is None
    assert reglas.IMPORT_NOTICE == "Importado de una publicación pública; su autor no es usuario de GuauWoow"


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._payload, self.text = status, payload, ""

    def json(self):
        return self._payload


def test_apify_run_storages_are_deleted_and_failures_retried(monkeypatch):
    monkeypatch.setattr(fbg, "KEY_PREFIX", f"fbg:test:{uuid.uuid4().hex[:8]}")
    monkeypatch.setattr(fbg, "_mem_pending", set())
    calls, fail = [], {"datasets/ds-9": True}
    run = {"id": "run-9", "status": "SUCCEEDED", "defaultDatasetId": "ds-9", "defaultKeyValueStoreId": "kv-9"}

    def fake_request(method, url, **kw):
        path = url.replace(fbg.APIFY_API + "/", "")
        calls.append((method, path))
        if method == "DELETE" and fail.get(path):
            raise fbg.ProviderError("Apify no respondió")
        if method == "POST":
            return _Resp(201, {"data": run})
        if method == "GET" and path.endswith("/items"):
            return _Resp(200, [])
        return _Resp(204)

    provider = fbg.ApifyProvider("token")
    monkeypatch.setattr(provider, "_request", fake_request)
    monkeypatch.setattr(provider, "_wait", lambda r: r)
    assert provider.fetch_posts("https://www.facebook.com/groups/x", _now(), 10) == []
    assert ("DELETE", "datasets/ds-9") in calls and ("DELETE", "key-value-stores/kv-9") in calls
    assert provider.last_dataset_deleted is False and fbg._pending_deletes() == ["datasets/ds-9"]
    # La siguiente corrida (o la tarea diaria) reintenta el borrado pendiente
    fail.clear()
    assert provider.retry_pending_deletes() == 1 and fbg._pending_deletes() == []


# =========================================================================== B5 veterinarias (estático)
@needs_frontend
def test_google_block_never_next_to_osm_map_and_badge_wording():
    js = (APP_DIR / "veterinarias.js").read_text(encoding="utf-8")
    start = js.index("async function loadMapMarkers")
    markers = js[start:js.index("/* ---------- notificaciones", start)]
    assert "google" not in markers.lower().replace("contenido de google nunca", "")  # el popup del mapa no lleva Google
    assert ".leaflet-container" in js and "current === 'map'" in js  # guarda del bloque de Google
    assert "No verificamos la calidad de la atención, las instalaciones, los precios ni los permisos locales" in js
    page = re.sub(r"<[^>]+>", "", (APP_DIR / "legal" / "plantillas" / "veterinarias.html").read_text(encoding="utf-8"))
    assert "No verificamos la calidad de la atención, las instalaciones, los precios ni los permisos locales" in page


@needs_frontend
def test_frontend_shows_rules():
    app_js = (APP_DIR / "app.js").read_text(encoding="utf-8")
    assert "Cada $10 suma 1 punto" not in app_js and "casas de paso y donativos" not in app_js
    assert "accepted_policy: true" in app_js and "No puedes donar a tu propio refugio" in app_js
    tienda = (APP_DIR / "tienda.js").read_text(encoding="utf-8")
    assert "/products/sellers/${refugeId}/identity" in tienda and "/comprobante" in tienda
    assert "/refuges/me/orders/${b.dataset.bonusPaid}/bonificacion" in tienda
    compartir = (APP_DIR / "compartir.js").read_text(encoding="utf-8")
    assert "/app/legal/contenido-importado.html?report_id=" in compartir and "#form-solicitud" in compartir
    index = (APP_DIR / "index.html").read_text(encoding="utf-8")
    for el_id in ("pm-category", "pm-warranty-kind", "pm-perishable", "receipt-modal", "pub-found", "co-perishable"):
        assert f'id="{el_id}"' in index, el_id
