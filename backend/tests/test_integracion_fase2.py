"""Integración de tienda (Marketplace), veterinarias y grupos de Facebook: lo que une las piezas.

- /auth/config expone donations_fallback (la app decide si deja donar a refugios sin Mercado Pago).
- GET /admin/orders filtra por refugio (lo usa el panel de admins).
- Cancelar la cuenta oculta la veterinaria de la persona, borra su cédula (documento privado) y sus reseñas,
  y quita de sus pedidos la dirección de entrega estructurada (quedan ciudad y estado).
"""
import datetime
import random
import uuid
from decimal import Decimal

from app.config import settings
from app.database import SessionLocal
from app.models import Order, Refuge, User, Veterinary, VeterinaryReview
from app.routers.documents import document_path
from conftest import _register


def _set_user(email, **fields) -> int:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        for k, v in fields.items():
            setattr(u, k, v)
        db.commit()
        return u.id
    finally:
        db.close()


def _admin(client):
    u = _register(client, "Admin Integración", verify=False)
    u["id"] = _set_user(u["email"], role="admin")
    return u


def _vet_body(doc_id, photo):
    lat, lon = round(random.uniform(24.0, 26.0), 5), round(random.uniform(-112.0, -110.5), 5)
    return {
        "name": f"Clínica Integración {uuid.uuid4().hex[:8]}", "description": "Consultas y vacunas.",
        "address": "Calle 5 de Mayo 10", "city": "La Paz", "state": "BCS", "postal_code": "23000",
        "latitude": lat, "longitude": lon, "phone": "612 765 4321", "photos": [photo],
        "hours": {"mon": [{"open": "09:00", "close": "18:00"}]}, "services": ["Consulta general"],
        "responsible_vet_name": "Laura Méndez Ruiz", "cedula_profesional": "7654321", "cedula_document_id": doc_id,
        "consent": True,
    }


def _upload(client, u, jpeg, path="/upload/document"):
    r = client.post(path, headers=u["h"], files={"file": ("f.jpg", jpeg(random.randint(0, 10 ** 6)), "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


def test_auth_config_exposes_donations_fallback(client, monkeypatch):
    assert client.get("/auth/config").json()["donations_fallback"] is settings.effective_donations_fallback
    monkeypatch.setattr(settings, "donations_fallback_to_platform_account", False)
    assert client.get("/auth/config").json()["donations_fallback"] is False


def test_admin_orders_filter_by_refuge(client):
    buyer = _register(client, "Comprador Filtro", verify=False)
    sellers = [_register(client, f"Refugio Filtro {i}", verify=False) for i in range(2)]
    db = SessionLocal()
    try:
        buyer_id = db.query(User.id).filter(User.email == buyer["email"]).scalar()
        refuge_ids = []
        for s in sellers:
            uid = db.query(User.id).filter(User.email == s["email"]).scalar()
            refuge = Refuge(user_id=uid, name=f"Refugio {uuid.uuid4().hex[:5]}", status="approved")
            db.add(refuge)
            db.flush()
            refuge_ids.append(refuge.id)
            db.add(Order(user_id=buyer_id, refuge_id=refuge.id, total=Decimal("50"), subtotal=Decimal("50"),
                         shipping_address="Calle 1", status="paid", created_at=datetime.datetime.utcnow()))
        db.commit()
    finally:
        db.close()

    admin = _admin(client)
    r = client.get("/admin/orders", params={"refuge_id": refuge_ids[0]}, headers=admin["h"])
    assert r.status_code == 200, r.text
    assert [o["refuge_id"] for o in r.json()] == [refuge_ids[0]]
    r = client.get("/admin/orders", params={"refuge_id": refuge_ids[1], "status": "cancelled"}, headers=admin["h"])
    assert r.status_code == 200 and r.json() == []


def test_account_deletion_removes_structured_shipping_address(client, make_user):
    buyer = make_user("Compradora Borrada")
    db = SessionLocal()
    try:
        uid = db.query(User.id).filter(User.email == buyer["email"]).scalar()
        order = Order(user_id=uid, total=Decimal("80"), subtotal=Decimal("80"), status="delivered",
                      shipping_address="Ana Pérez, Av. Reforma 10, Juárez, 06600 Cuauhtémoc, CDMX",
                      shipping_name="Ana Pérez", shipping_phone="5512345678", shipping_street="Av. Reforma",
                      shipping_ext_number="10", shipping_int_number="2", shipping_neighborhood="Juárez",
                      shipping_city="Cuauhtémoc", shipping_state="CDMX", shipping_postal_code="06600",
                      shipping_references="Portón azul", created_at=datetime.datetime.utcnow())
        db.add(order)
        db.commit()
        order_id = order.id
    finally:
        db.close()

    r = client.request("DELETE", "/users/me", headers=buyer["h"], json={"confirm": "ELIMINAR", "password": buyer["password"]})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        o = db.query(Order).filter(Order.id == order_id).first()
        assert o.shipping_address == "[eliminada a solicitud del titular]"
        assert all(getattr(o, f) is None for f in (
            "shipping_name", "shipping_phone", "shipping_street", "shipping_ext_number", "shipping_int_number",
            "shipping_neighborhood", "shipping_postal_code", "shipping_references"))
        assert (o.shipping_city, o.shipping_state) == ("Cuauhtémoc", "CDMX")  # el pedido se conserva (fiscal)
    finally:
        db.close()


def test_account_deletion_hides_clinic_and_removes_cedula_and_reviews(client, make_user, jpeg):
    owner = make_user("Dueño Clínica")
    doc_id = _upload(client, owner, jpeg)["id"]
    photo = _upload(client, owner, jpeg, "/upload")["url"]
    r = client.post("/veterinaries", headers=owner["h"], json=_vet_body(doc_id, photo))
    assert r.status_code == 201, r.text
    vet_id = r.json()["id"]
    admin = _admin(client)
    # La verificación exige la evidencia del cotejo: carrera del RNP y captura privada que sube el admin
    evidence = _upload(client, admin, jpeg)["id"]
    assert client.post(f"/admin/veterinaries/{vet_id}/verify", headers=admin["h"],
                       json={"carrera": "Médico Veterinario Zootecnista", "evidence_document_id": evidence}
                       ).status_code == 200

    # Una persona reseña la clínica y luego cancela su cuenta: su reseña se borra
    reviewer = make_user("Reseñadora")
    assert client.post(f"/veterinaries/{vet_id}/reviews", headers=reviewer["h"],
                       json={"rating": 5, "text": "Muy buena atención"}).status_code == 201
    assert client.get(f"/veterinaries/{vet_id}").json()["rating_count"] == 1
    # Derecho de acceso: la exportación incluye la clínica y las reseñas
    export = client.get("/users/me/export", headers=owner["h"]).json()
    assert [v["id"] for v in export["veterinaries"]] == [vet_id] and export["invoice_requests"] == []
    assert [x["veterinary_id"] for x in client.get("/users/me/export", headers=reviewer["h"]).json()["veterinary_reviews"]] == [vet_id]
    r = client.request("DELETE", "/users/me", headers=reviewer["h"],
                       json={"confirm": "ELIMINAR", "password": reviewer["password"]})
    assert r.status_code == 200, r.text
    assert client.get(f"/veterinaries/{vet_id}").json()["rating_count"] == 0

    # La dueña cancela su cuenta: la clínica se oculta sin contacto, fotos ni cédula
    assert document_path(doc_id) is not None
    r = client.request("DELETE", "/users/me", headers=owner["h"],
                       json={"confirm": "ELIMINAR", "password": owner["password"]})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        vet = db.query(Veterinary).filter(Veterinary.id == vet_id).first()
        assert vet.is_hidden and vet.photos == [] and vet.cedula_document_id is None
        assert vet.phone is None and vet.email is None and vet.description is None
        assert db.query(VeterinaryReview).filter(VeterinaryReview.veterinary_id == vet_id).count() == 0
    finally:
        db.close()
    path = document_path(doc_id)
    assert path is None or not path.exists()
    assert client.get(f"/veterinaries/{vet_id}").status_code == 404
