"""Exposición de datos: documentos privados de refugios, coordenadas aproximadas, contacto de solicitudes,
puntos de refugios y cancelación de cuenta completa."""
import io
import re
import uuid
from pathlib import Path

from PIL import Image

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AdminAuditLog, AdoptionApplication, Dog, LostReport, Notification, PhoneVerificationLog, Product, Refuge, User,
)
from tests.conftest import make_jpeg

LAT, LON = 19.432612, -99.133211  # exactas: el público solo debe ver 19.43, -99.13
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
DOC_ID = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp|pdf)$")


def _db_user(email: str) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email).first()
    finally:
        db.close()


def _make_admin(client, make_user) -> dict:
    a = make_user("Admin Pruebas")
    db = SessionLocal()
    try:
        db.query(User).filter(User.email == a["email"]).update({User.role: "admin"})
        db.commit()
    finally:
        db.close()
    token = client.post("/auth/login", data={"username": a["email"], "password": a["password"]}).json()["access_token"]
    a["h"] = {"Authorization": f"Bearer {token}"}
    return a


def _set_refuge_status(refuge_id: int, status: str):
    db = SessionLocal()
    try:
        db.query(Refuge).filter(Refuge.id == refuge_id).update({Refuge.status: status})
        db.commit()
    finally:
        db.close()


def _upload_doc(client, u, data=PDF, name="acta.pdf", mime="application/pdf"):
    return client.post("/upload/document", headers=u["h"], files={"file": (name, data, mime)})


def _two_decimals(value) -> bool:
    return value is None or round(value, 2) == value


def _private_path(doc_id: str) -> Path:
    return Path(settings.upload_dir) / "private" / doc_id


def _upload_path(url: str) -> Path:
    return Path(settings.upload_dir) / url.rsplit("/", 1)[1]


# --------------------------------------------------------------------------- documentos privados
def test_document_upload_is_private_and_admin_can_download(client, make_user, unverified):
    owner = make_user("Refugio Docs")
    assert _upload_doc(client, unverified).status_code == 403  # sin teléfono verificado
    assert client.post("/upload/document", files={"file": ("a.pdf", PDF, "application/pdf")}).status_code == 401
    assert _upload_doc(client, owner, b"<html>hola</html>", "x.pdf").status_code == 400

    r = _upload_doc(client, owner)
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    assert DOC_ID.match(doc_id) and doc_id.endswith(".pdf")
    # En disco solo queda cifrado (L-seguridad, services/crypto_storage.py); se descifra al servirlo
    from app.services import crypto_storage

    on_disk = _private_path(doc_id).read_bytes()
    assert crypto_storage.is_encrypted(on_disk) and PDF not in on_disk
    assert crypto_storage.read_private(_private_path(doc_id)) == PDF

    # Una imagen con EXIF se guarda re-codificada (sin metadatos)
    img = Image.new("RGB", (64, 48), (200, 10, 10))
    exif = Image.Exif()
    exif[0x010F] = "CamaraSecreta"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    r = _upload_doc(client, owner, buf.getvalue(), "foto.jpg", "image/jpeg")
    img_id = r.json()["id"]
    assert img_id.endswith(".jpg") and b"CamaraSecreta" not in crypto_storage.read_private(_private_path(img_id))

    # Nunca se sirve como estático, ni con trucos de ruta
    for path in (f"/uploads/private/{doc_id}", f"/uploads/PRIVATE/{doc_id}", f"/uploads/%2e%2e/uploads/private/{doc_id}",
                 f"/uploads/private%2f{doc_id}"):
        assert client.get(path).status_code == 404, path

    # Registro del refugio: solo ids existentes o rutas antiguas /uploads/...
    bad = client.post("/refuges/register", headers=owner["h"], json={"name": "X", "documents": ["javascript:alert(1)"]})
    assert bad.status_code == 400
    missing = client.post("/refuges/register", headers=owner["h"], json={"name": "X", "documents": [uuid.uuid4().hex + ".pdf"]})
    assert missing.status_code == 400
    reg = client.post("/refuges/register", headers=owner["h"],
                      json={"name": "Refugio Privado", "documents": [doc_id, img_id, "/uploads/antiguo123.jpg"]})
    assert reg.status_code == 201, reg.text
    refuge = reg.json()
    assert refuge["documents"] == [doc_id, img_id, "/uploads/antiguo123.jpg"]  # el responsable sí los ve
    assert client.get("/refuges/me", headers=owner["h"]).json()["documents"] == refuge["documents"]

    admin = _make_admin(client, make_user)
    pending = client.get("/admin/refuges/pending", headers=admin["h"], params={"limit": 200}).json()
    assert next(x for x in pending if x["id"] == refuge["id"])["documents"][0] == doc_id

    assert client.get(f"/admin/documents/{doc_id}", headers=owner["h"]).status_code == 403
    assert client.get(f"/admin/documents/{doc_id}").status_code == 401
    dl = client.get(f"/admin/documents/{doc_id}", headers=admin["h"])
    assert dl.status_code == 200 and dl.content == PDF and dl.headers["content-type"] == "application/pdf"
    assert "no-store" in dl.headers["cache-control"]
    assert client.get("/admin/documents/..%2f..%2fapp%2fmain.py", headers=admin["h"]).status_code == 404
    assert client.get(f"/admin/documents/{uuid.uuid4().hex}.pdf", headers=admin["h"]).status_code == 404
    db = SessionLocal()
    try:
        log = (db.query(AdminAuditLog).filter(AdminAuditLog.action == "refuge_document.view",
                                              AdminAuditLog.target_id == refuge["id"]).first())
        assert log is not None and log.details["document"] == doc_id
    finally:
        db.close()


def test_public_refuge_data_has_no_documents_and_is_paginated(client, make_user):
    owner = make_user("Refugio Público")
    doc_id = _upload_doc(client, owner).json()["id"]
    refuge = client.post("/refuges/register", headers=owner["h"], json={"name": "Refugio Visible", "documents": [doc_id]}).json()
    assert client.get(f"/refuges/{refuge['id']}").status_code == 404  # pendiente: no es público
    assert client.get(f"/refuges/{refuge['id']}", headers=owner["h"]).status_code == 200
    _set_refuge_status(refuge["id"], "approved")

    for url in ("/refuges", "/refuges/ranking"):
        items = client.get(url, params={"limit": 100}).json()
        assert items and all("documents" not in r for r in items), url
    detail = client.get(f"/refuges/{refuge['id']}").json()
    assert detail["name"] == "Refugio Visible" and "documents" not in detail

    assert client.get("/refuges", params={"limit": 101}).status_code == 422
    assert client.get("/refuges/ranking", params={"limit": 101}).status_code == 422
    assert len(client.get("/refuges", params={"limit": 1}).json()) == 1
    page1 = client.get("/refuges/ranking", params={"limit": 2}).json()
    page2 = client.get("/refuges/ranking", params={"limit": 2, "skip": 1}).json()
    assert page1[1]["id"] == page2[0]["id"]

    for i in range(3):
        client.post("/dogs", headers=owner["h"], json={"name": f"Ref{i}", "latitude": LAT, "longitude": LON})
    dogs = client.get(f"/refuges/{refuge['id']}/dogs", params={"limit": 2}).json()
    assert len(dogs) == 2 and all(_two_decimals(d["latitude"]) and d["latitude"] == 19.43 for d in dogs)
    assert client.get(f"/refuges/{refuge['id']}/dogs", params={"limit": 101}).status_code == 422
    assert len(client.get(f"/refuges/{refuge['id']}/dogs", params={"skip": 2, "limit": 2}).json()) == 1


def test_refuge_cannot_inflate_its_own_points(client, make_user):
    owner = make_user("Refugio Honesto")
    refuge = client.post("/refuges/register", headers=owner["h"], json={"name": "Refugio Puntos"}).json()
    _set_refuge_status(refuge["id"], "approved")
    for action in ("rescue", "adopt", "foster"):
        r = client.post(f"/refuges/{refuge['id']}/{action}", headers=owner["h"], json={"description": "yo mismo"})
        assert r.status_code == 403, action
    me = client.get("/refuges/me", headers=owner["h"]).json()
    assert (me["points"], me["rescued_count"], me["adopted_count"], me["foster_count"]) == (0, 0, 0, 0)

    admin = _make_admin(client, make_user)
    r = client.post(f"/refuges/{refuge['id']}/rescue", headers=admin["h"], json={"description": "Verificado"})
    assert r.status_code == 200 and r.json()["points"] == 5 and r.json()["rescued_count"] == 1
    db = SessionLocal()
    try:
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "refuge.rescue",
                                              AdminAuditLog.target_id == refuge["id"]).count() == 1
    finally:
        db.close()


# --------------------------------------------------------------------------- coordenadas
def test_dog_coordinates_rounded_for_public_exact_for_owner(client, owner, user, make_user):
    created = client.post("/dogs", headers=owner["h"], json={"name": "Coordenadas", "latitude": LAT, "longitude": LON})
    assert created.status_code == 201
    dog = created.json()
    assert (dog["latitude"], dog["longitude"]) == (LAT, LON)  # quien publica ve lo exacto
    mine = next(d for d in client.get("/dogs/me", headers=owner["h"]).json() if d["id"] == dog["id"])
    assert (mine["latitude"], mine["longitude"]) == (LAT, LON)
    own_detail = client.get(f"/dogs/{dog['id']}", headers=owner["h"]).json()
    assert (own_detail["latitude"], own_detail["longitude"]) == (LAT, LON)

    pub = client.get(f"/dogs/{dog['id']}", params={"lat": LAT, "lon": LON}).json()
    assert (pub["latitude"], pub["longitude"]) == (19.43, -99.13)
    # La distancia sale de las coordenadas aproximadas (no sirve para triangular) y con 1 decimal
    assert pub["distance_km"] == 0.4

    near = client.get("/dogs/nearby", params={"lat": LAT, "lon": LON, "radius_km": 2, "limit": 100}).json()
    hit = next(d for d in near if d["id"] == dog["id"])
    assert (hit["latitude"], hit["longitude"]) == (19.43, -99.13)
    assert all(_two_decimals(d["latitude"]) and _two_decimals(d["longitude"]) for d in near)
    assert all(d["distance_km"] is None or round(d["distance_km"], 1) == d["distance_km"] for d in near)
    assert client.get("/dogs/nearby", params={"lat": LAT, "lon": LON, "limit": 101}).status_code == 422
    first2 = client.get("/dogs/nearby", params={"lat": LAT, "lon": LON, "radius_km": 2, "limit": 2}).json()
    skip1 = client.get("/dogs/nearby", params={"lat": LAT, "lon": LON, "radius_km": 2, "limit": 2, "skip": 1}).json()
    if len(first2) == 2 and skip1:
        assert {d["id"] for d in first2} & {d["id"] for d in skip1}

    feat = client.get("/dogs/featured", params={"lat": LAT, "lon": LON, "radius_km": 2, "limit": 20}).json()
    assert all(_two_decimals(d["latitude"]) for d in feat)
    disc = client.get("/dogs/discover", headers=user["h"], params={"lat": LAT, "lon": LON, "radius_km": 2, "limit": 100}).json()
    assert any(d["id"] == dog["id"] for d in disc) and all(_two_decimals(d["latitude"]) for d in disc)
    assert [d["distance_km"] for d in disc] == sorted(d["distance_km"] for d in disc)

    admin = _make_admin(client, make_user)
    admin_dogs = client.get("/admin/dogs", headers=admin["h"], params={"limit": 200}).json()
    assert next(d for d in admin_dogs if d["id"] == dog["id"])["latitude"] == LAT
    admin_detail = client.get(f"/dogs/{dog['id']}", headers=admin["h"]).json()
    assert admin_detail["latitude"] == LAT


def test_lost_report_coordinates_rounded_for_public(client, owner, make_user):
    created = client.post("/lost-reports", headers=owner["h"], json={
        "dog_name": "Perdida Exacta", "report_type": "lost", "latitude": LAT, "longitude": LON})
    report = created.json()
    assert (report["latitude"], report["longitude"]) == (LAT, LON)
    mine = next(r for r in client.get("/lost-reports/me", headers=owner["h"]).json() if r["id"] == report["id"])
    assert mine["latitude"] == LAT
    assert client.get(f"/lost-reports/{report['id']}", headers=owner["h"]).json()["longitude"] == LON

    pub = client.get(f"/lost-reports/{report['id']}", params={"lat": LAT, "lon": LON}).json()
    assert (pub["latitude"], pub["longitude"], pub["distance_km"]) == (19.43, -99.13, 0.4)
    listing = client.get("/lost-reports", params={"lat": LAT, "lon": LON, "radius_km": 2}).json()
    assert any(r["id"] == report["id"] for r in listing)
    assert all(_two_decimals(r["latitude"]) and _two_decimals(r["longitude"]) for r in listing)
    every = client.get("/lost-reports", params={"status": "all", "limit": 500}).json()
    assert all(_two_decimals(r["latitude"]) for r in every)

    admin = _make_admin(client, make_user)
    rows = client.get("/admin/lost-reports", headers=admin["h"], params={"limit": 200}).json()
    assert next(r for r in rows if r["id"] == report["id"])["latitude"] == LAT


# --------------------------------------------------------------------------- contacto de solicitudes
def test_match_contact_hidden_until_approved(client, owner, user, make_user):
    dog = client.post("/dogs", headers=owner["h"], json={"name": "Contacto"}).json()
    match = client.post(f"/dogs/{dog['id']}/like", headers=user["h"]).json()
    assert match["user"]["email"] is None and match["user"]["phone"] is None
    assert match["user"]["contact_visible"] is False

    seen = next(m for m in client.get("/matches", headers=owner["h"]).json() if m["id"] == match["id"])
    assert seen["user"]["email"] is None and seen["user"]["phone"] is None and seen["user"]["contact_visible"] is False
    assert seen["user"]["full_name"] == "Adoptante Prueba"

    admin = _make_admin(client, make_user)
    rows = client.get("/admin/matches", headers=admin["h"], params={"limit": 200}).json()
    adm = next(m for m in rows if m["id"] == match["id"])
    assert adm["user"]["email"] == user["email"] and adm["user"]["contact_visible"] is True

    assert client.post(f"/matches/{match['id']}/approve", headers=owner["h"]).status_code == 200
    after = client.get(f"/matches/{match['id']}", headers=owner["h"]).json()
    assert after["user"]["email"] == user["email"] and after["user"]["phone"] == user["phone"]
    assert after["user"]["contact_visible"] is True


# --------------------------------------------------------------------------- cancelación de cuenta
def test_account_deletion_removes_files_and_hides_content(client, make_user):
    name = f"Borrable{uuid.uuid4().hex[:6]}"
    u = make_user(name)
    adopter = make_user("Adoptante Restante")
    neighbor = make_user("Vecina Restante")
    up = lambda who, seed: client.post("/upload", headers=who["h"], files={"file": ("p.jpg", make_jpeg(seed), "image/jpeg")}).json()["url"]
    dog_photo, report_photo, avatar, shared = up(u, 101), up(u, 102), up(u, 103), up(u, 104)
    client.patch("/users/me", headers=u["h"], json={"avatar_url": avatar})

    doc_id = _upload_doc(client, u).json()["id"]
    refuge = client.post("/refuges/register", headers=u["h"], json={"name": f"Refugio de {name}", "documents": [doc_id]}).json()
    _set_refuge_status(refuge["id"], "approved")
    db = SessionLocal()
    try:
        product = Product(refuge_id=refuge["id"], name="Taza", price=100, stock=3, photos=[])
        db.add(product)
        db.commit()
        product_id = product.id
    finally:
        db.close()

    dog = client.post("/dogs", headers=u["h"], json={
        "name": "Se Va", "description": "Llámame al 5512345678", "latitude": LAT, "longitude": LON,
        "photos": [dog_photo, shared]}).json()
    # Otra persona usa la misma URL de foto: ese archivo no se puede borrar
    other_dog = client.post("/dogs", headers=neighbor["h"], json={"name": "Copia", "photos": [shared]}).json()
    report = client.post("/lost-reports", headers=u["h"], json={
        "dog_name": "Reporte Se Va", "report_type": "lost", "latitude": LAT, "longitude": LON, "photos": [report_photo]}).json()
    resolved = client.post("/lost-reports", headers=u["h"], json={"dog_name": "Resuelto Se Va", "report_type": "found"}).json()
    client.patch(f"/lost-reports/{resolved['id']}/resolve", headers=u["h"])

    # Solicitud de adopción del usuario a otro perro, y chat con quien adopta su perro
    neighbor_dog = client.post("/dogs", headers=neighbor["h"], json={"name": "Del Vecino"}).json()
    my_match = client.post(f"/dogs/{neighbor_dog['id']}/like", headers=u["h"]).json()
    client.post(f"/matches/{my_match['id']}/apply", headers=u["h"], json={"answers": {"housing": "casa", "motivo": "Vivo en Calle Falsa 123"}})
    their_match = client.post(f"/dogs/{dog['id']}/like", headers=adopter["h"]).json()
    conv = client.post(f"/matches/{their_match['id']}/approve", headers=u["h"]).json()
    client.post(f"/conversations/{conv['id']}/messages", headers=u["h"], json={"content": "Hola, soy yo"})
    uid = client.get("/users/me", headers=u["h"]).json()["id"]

    r = client.request("DELETE", "/users/me", headers=u["h"], json={"confirm": "ELIMINAR", "password": u["password"]})
    assert r.status_code == 200 and r.json() == {"ok": True}

    # Fotos y miniaturas borradas del disco; la compartida se conserva
    for url in (dog_photo, report_photo, avatar):
        thumb = url.rsplit(".", 1)[0] + "_thumb.jpg"
        assert not _upload_path(url).exists() and not _upload_path(thumb).exists(), url
        assert client.get(url).status_code == 404
    assert _upload_path(shared).exists()
    assert client.get(f"/dogs/{other_dog['id']}").json()["photos"] == [shared]
    assert not _private_path(doc_id).exists()

    # Nada público de la cuenta eliminada
    assert client.get(f"/dogs/{dog['id']}").status_code == 404
    assert client.get(f"/lost-reports/{report['id']}").status_code == 404
    assert client.get(f"/lost-reports/{report['id']}/matches").status_code == 404
    for status in ("all", "resolved", "closed", "active"):
        ids = {x["id"] for x in client.get("/lost-reports", params={"status": status, "limit": 500}).json()}
        assert report["id"] not in ids and resolved["id"] not in ids, status
    assert client.get(f"/refuges/{refuge['id']}").status_code == 404
    assert client.get(f"/refuges/{refuge['id']}/dogs", params={"status": "all"}).status_code == 404
    assert refuge["id"] not in {x["id"] for x in client.get("/refuges", params={"limit": 100}).json()}
    assert refuge["id"] not in {x["id"] for x in client.get("/refuges/ranking", params={"limit": 100}).json()}
    assert client.post(f"/refuges/{refuge['id']}/donate", headers=adopter["h"], json={"amount": 50}).status_code in (400, 404)
    near = client.get("/dogs/nearby", params={"lat": LAT, "lon": LON, "radius_km": 2, "limit": 100}).json()
    assert dog["id"] not in {d["id"] for d in near}

    # La otra persona sigue leyendo el chat, firmado como "Usuario eliminado"
    msgs = client.get(f"/conversations/{conv['id']}/messages", headers=adopter["h"]).json()
    assert any(m["content"] == "Hola, soy yo" for m in msgs)
    summary = client.get(f"/conversations/{conv['id']}", headers=adopter["h"]).json()
    assert summary["other_user"]["full_name"] == "Usuario eliminado"
    seen_match = next(m for m in client.get("/matches", headers=neighbor["h"]).json() if m["id"] == my_match["id"])
    assert seen_match["user"]["full_name"] == "Usuario eliminado" and seen_match["status"] == "rejected"

    db = SessionLocal()
    try:
        d = db.get(Dog, dog["id"])
        assert d.is_hidden and d.photos == [] and d.description is None and d.latitude is None
        rep = db.get(LostReport, report["id"])
        assert rep.is_hidden and rep.photos == [] and rep.status == "closed" and rep.latitude is None
        ref = db.get(Refuge, refuge["id"])
        assert ref.status == "closed" and ref.documents == []
        assert db.get(Product, product_id).is_active is False
        app_row = db.query(AdoptionApplication).filter(AdoptionApplication.match_id == my_match["id"]).first()
        assert app_row.answers == {}
        logs = db.query(PhoneVerificationLog).filter(PhoneVerificationLog.user_id == uid).all()
        assert logs and all(lg.phone == "eliminado" and lg.ip is None for lg in logs)
        assert db.query(PhoneVerificationLog).filter(PhoneVerificationLog.phone == u["phone"]).count() == 0
        # Avisos de otras cuentas sin su nombre
        others = db.query(Notification).filter(Notification.user_id.in_([adopter_id(db, adopter), adopter_id(db, neighbor)])).all()
        assert others and not any(name in (n.title + n.body) for n in others)
    finally:
        db.close()


def adopter_id(db, who) -> int:
    return db.query(User.id).filter(User.email == who["email"]).scalar()


def test_legacy_documents_download_and_cli_move(client, make_user, jpeg, capsys):
    from app.cli import move_private_docs

    owner = make_user("Refugio Antiguo")
    # Documento antiguo: subido con /upload (público, con miniatura) antes de la carpeta privada
    legacy = client.post("/upload", headers=owner["h"], files={"file": ("d.jpg", jpeg(201), "image/jpeg")}).json()["url"]
    shared = client.post("/upload", headers=owner["h"], files={"file": ("d.jpg", jpeg(202), "image/jpeg")}).json()["url"]
    client.post("/dogs", headers=owner["h"], json={"name": "Usa la foto", "photos": [shared]})
    refuge = client.post("/refuges/register", headers=owner["h"], json={"name": "Refugio Legado", "documents": [legacy, shared]})
    assert refuge.status_code == 201, refuge.text
    refuge_id = refuge.json()["id"]
    legacy_name, shared_name = legacy.rsplit("/", 1)[1], shared.rsplit("/", 1)[1]

    admin = _make_admin(client, make_user)
    assert client.get(f"/admin/documents/{legacy_name}", headers=admin["h"]).status_code == 200

    assert move_private_docs(dry_run=True) == 0
    assert _upload_path(legacy).exists()  # la simulación no toca nada
    assert move_private_docs() == 0
    assert "Documentos movidos" in capsys.readouterr().out
    db = SessionLocal()
    try:
        assert db.get(Refuge, refuge_id).documents == [legacy_name, shared_name]
    finally:
        db.close()
    assert _private_path(legacy_name).exists() and not _upload_path(legacy).exists()
    from app.services import crypto_storage  # la copia privada queda cifrada en disco, nunca en claro

    assert crypto_storage.is_encrypted(_private_path(legacy_name).read_bytes())
    assert crypto_storage.is_encrypted(_private_path(shared_name).read_bytes())
    assert client.get(legacy).status_code == 404 and client.get(legacy.rsplit(".", 1)[0] + "_thumb.jpg").status_code == 404
    # La que también es foto de un perro se copia: el perro la sigue mostrando
    assert _private_path(shared_name).exists() and client.get(shared).status_code == 200
    dl = client.get(f"/admin/documents/{legacy_name}", headers=admin["h"])
    assert dl.status_code == 200 and dl.headers["content-type"] == "image/jpeg"
    assert move_private_docs() == 0  # idempotente
