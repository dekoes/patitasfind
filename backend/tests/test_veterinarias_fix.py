"""Correcciones de la revisión de veterinarias: documentos privados (y su borrado al cancelar la cuenta), límite
por cuenta e IP del bloque de Google, datos mínimos en las respuestas públicas, evidencia del cotejo en el RNP,
consentimiento y retención, nombres de terceros en reseñas, aclaraciones y quejas sin cuenta, y el aviso de
vencimiento para el dueño. Nunca se llama a Google (cliente HTTP sustituido)."""
import datetime
import random
import uuid
from pathlib import Path

from app.config import settings
from app.database import SessionLocal
from app.models import Notification, User, Veterinary, VeterinaryRequest
from app.routers import veterinaries as vet_router
from app.routers.documents import delete_private_document, private_document_path
from app.tasks import veterinaries as vet_tasks
from tests.conftest import random_ip
from tests.test_veterinarias import (  # noqa: F401 - fake_google y no_google son fixtures
    _audit, _body, _create, _doc, _evidence, _get_vet, _set_user, _set_vet, _staff, _verified, fake_google, no_google,
)


def _photo(client, u, jpeg) -> str:
    r = client.post("/upload", headers=u["h"],
                    files={"file": ("foto.jpg", jpeg(random.randint(0, 10 ** 6)), "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()["url"]


def _types(email) -> list[str]:
    db = SessionLocal()
    try:
        uid = db.query(User.id).filter(User.email == email).scalar()
        return [n.type for n in db.query(Notification).filter(Notification.user_id == uid)]
    finally:
        db.close()


def _delete_account(client, u):
    r = client.request("DELETE", "/users/me", headers=u["h"], json={"confirm": "ELIMINAR", "password": u["password"]})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- documentos privados
def test_public_photo_is_not_a_cedula_and_account_deletion_keeps_it(client, make_user, jpeg, no_google):
    victim = make_user("Víctima Foto")
    url = _photo(client, victim, jpeg)
    name = url.rsplit("/", 1)[-1]
    thumb = url.replace(".jpg", "_thumb.jpg")
    assert client.get(url).status_code == 200

    attacker = make_user("Atacante Documentos")
    # El nombre de una foto pública (<uuid>.jpg) no es un documento privado
    r = client.post("/veterinaries", headers=attacker["h"], json=_body(name))
    assert r.status_code == 400 and "cédula" in r.json()["detail"]
    # Tampoco el documento privado que subió otra cuenta
    assert client.post("/veterinaries", headers=attacker["h"], json=_body(_doc(client, victim, jpeg))).status_code == 400
    # Refugios: mismo filtro para sus documentos
    r = client.post("/refuges/register", headers=attacker["h"], json={"name": "Refugio Prueba", "documents": [name]})
    assert r.status_code == 400

    vet = _create(client, attacker, jpeg)
    r = client.patch(f"/veterinaries/{vet['id']}", headers=attacker["h"], json={"cedula_document_id": name})
    assert r.status_code == 400
    _delete_account(client, attacker)
    # La foto de la otra persona (y su miniatura) siguen ahí
    assert client.get(url).status_code == 200
    assert Path(settings.upload_dir, name).is_file()
    if Path(settings.upload_dir, name.replace(".jpg", "_thumb.jpg")).exists():
        assert client.get(thumb).status_code == 200
    # El borrado de documentos privados ignora cualquier archivo fuera de private/
    assert private_document_path(name) is None and delete_private_document(name) is False
    assert Path(settings.upload_dir, name).is_file()


# --------------------------------------------------------------------------- Google: límite por cuenta e IP
def test_google_block_throttled_per_user_and_anonymous_ip(client, make_user, jpeg, fake_google, monkeypatch):
    _owner, vet, _ = _verified(client, make_user, jpeg)
    _set_vet(vet["id"], google_place_id=f"ChIJ{uuid.uuid4().hex[:16]}")
    url = f"/veterinaries/{vet['id']}"
    monkeypatch.setattr(vet_router, "GOOGLE_DETAIL_PER_USER_HOUR", 2)
    monkeypatch.setattr(vet_router, "GOOGLE_DETAIL_ANON_PER_IP_HOUR", 1)
    viewer = make_user("Curiosa")
    before = len(fake_google["calls"])
    assert client.get(url, headers=viewer["h"]).json()["google"]["available"] is True
    assert client.get(url, headers=viewer["h"]).json()["google"]["available"] is True
    g = client.get(url, headers=viewer["h"]).json()["google"]
    assert g["available"] is False and g["reviews"] == [] and g["rating"] is None and g["google_maps_url"]
    assert len(fake_google["calls"]) == before + 2  # la tercera vista no consultó a Google

    assert client.get(url).json()["google"]["available"] is True
    assert client.get(url).json()["google"]["available"] is False
    assert len(fake_google["calls"]) == before + 3


# --------------------------------------------------------------------------- respuestas públicas sin ids de cuenta
def test_public_payloads_hide_account_ids(client, make_user, jpeg, no_google):
    owner, vet, admin = _verified(client, make_user, jpeg)
    ana = make_user("Ana Gómez Ruiz")
    r = client.post(f"/veterinaries/{vet['id']}/reviews", headers=ana["h"], json={"rating": 4, "text": "Buen trato"})
    assert r.status_code == 201 and r.json()["mine"] is True and "user_id" not in r.json()
    url = f"/veterinaries/{vet['id']}"

    anon = client.get(url).json()
    assert "owner_user_id" not in anon and anon["is_owner"] is False
    review = anon["reviews"][0]
    assert "user_id" not in review and "id" not in review["user"] and review["mine"] is False
    assert review["user"]["full_name"] == "Ana G."
    assert client.get(url, headers=ana["h"]).json()["reviews"][0]["mine"] is True
    assert client.get(url, headers=owner["h"]).json()["is_owner"] is True
    listed = client.get("/veterinaries", params={"q": vet["name"]}).json()
    assert listed and all("owner_user_id" not in v for v in listed)
    assert all("user_id" not in x for x in client.get(f"{url}/reviews").json())
    # La dueña y los admins sí ven los ids
    me = client.get("/veterinaries/me", headers=owner["h"]).json()
    assert me["owner_user_id"] and me["is_owner"] is True
    held = client.get("/admin/veterinary-reviews", headers=admin["h"], params={"veterinary_id": vet["id"]}).json()
    assert held and held[0]["user_id"]


# --------------------------------------------------------------------------- evidencia del cotejo
def test_verify_requires_rnp_evidence_and_carrera(client, make_user, jpeg, no_google):
    admin = _staff(make_user)
    owner = make_user("Clínica Evidencia")
    vet = _create(client, owner, jpeg)
    verify = f"/admin/veterinaries/{vet['id']}/verify"
    assert client.post(verify, headers=admin["h"], json={"carrera": "MVZ"}).status_code == 422
    # La cédula de la clínica no es la captura del cotejo, ni un documento de otra cuenta, ni una foto pública
    for doc in (vet["cedula_document_id"], _doc(client, owner, jpeg)):
        r = client.post(verify, headers=admin["h"], json={"carrera": "Médico Veterinario", "evidence_document_id": doc})
        assert r.status_code == 400, doc
    public = _photo(client, admin, jpeg).rsplit("/", 1)[-1]
    assert client.post(verify, headers=admin["h"],
                       json={"carrera": "Médico Veterinario", "evidence_document_id": public}).status_code == 400

    r = _evidence(client, admin, jpeg, vet["id"], carrera="  Médico   Veterinario Zootecnista ")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cedula_carrera"] == "Médico Veterinario Zootecnista" and body["verified_by_id"] == admin["id"]
    first = body["verification_evidence_document_id"]
    assert first and private_document_path(first) and body["unpublished_at"] is None
    audit = _audit("veterinary.verify", vet["id"])[-1]
    assert audit.details["evidence"] == first and audit.details["carrera"] == "Médico Veterinario Zootecnista"

    doc = client.get(f"/admin/veterinaries/{vet['id']}/evidence", headers=admin["h"])
    assert doc.status_code == 200 and doc.headers["content-type"] == "image/jpeg" and "no-store" in doc.headers["cache-control"]
    assert _audit("veterinary_evidence.view", vet["id"])
    assert client.get(f"/admin/veterinaries/{vet['id']}/evidence", headers=owner["h"]).status_code == 403
    me = client.get("/veterinaries/me", headers=owner["h"]).json()
    assert "verification_evidence_document_id" not in me  # la evidencia es del equipo
    assert "cedula_carrera" not in client.get(f"/veterinaries/{vet['id']}").json()

    # Reverificación: la captura nueva sustituye a la anterior
    second = _evidence(client, admin, jpeg, vet["id"]).json()["verification_evidence_document_id"]
    assert second != first and private_document_path(first) is None and private_document_path(second)


# --------------------------------------------------------------------------- consentimiento y retención
def test_consent_is_required_and_stored(client, make_user, jpeg, no_google):
    u = make_user("Clínica Consentimiento")
    doc = _doc(client, u, jpeg)
    body = _body(doc)
    body.pop("consent")
    r = client.post("/veterinaries", headers=u["h"], json=body)
    assert r.status_code == 400 and "consentimiento" in r.json()["detail"]
    assert client.post("/veterinaries", headers=u["h"], json=_body(doc, consent=False)).status_code == 400
    r = client.post("/veterinaries", headers=u["h"], json=_body(doc))
    assert r.status_code == 201
    vet = r.json()
    assert vet["consent_at"] and vet["consent_terms_version"] == settings.legal_terms_version

    # Al reemplazar la cédula se borra la anterior
    new_doc = _doc(client, u, jpeg)
    r = client.patch(f"/veterinaries/{vet['id']}", headers=u["h"], json={"cedula_document_id": new_doc})
    assert r.status_code == 200 and r.json()["cedula_document_id"] == new_doc
    assert private_document_path(doc) is None and private_document_path(new_doc)
    # Reenviar la misma cédula no cambia nada
    assert client.patch(f"/veterinaries/{vet['id']}", headers=u["h"],
                        json={"cedula_document_id": new_doc}).status_code == 200
    assert private_document_path(new_doc)


def test_documents_purged_12_months_after_rejection(client, make_user, jpeg, no_google):
    _owner, vet, admin = _verified(client, make_user, jpeg)
    _owner2, recent, _ = _verified(client, make_user, jpeg, admin=admin)
    for v in (vet, recent):
        r = client.post(f"/admin/veterinaries/{v['id']}/reject", headers=admin["h"], json={"note": "Revocada por prueba."})
        assert r.status_code == 200 and r.json()["unpublished_at"]
    old = _get_vet(vet["id"])
    assert old.cedula_document_id and old.verification_evidence_document_id  # se conservan tras el rechazo
    _set_vet(vet["id"], unpublished_at=datetime.datetime.utcnow() - datetime.timedelta(days=366))
    db = SessionLocal()
    try:
        stats = vet_tasks.purge_documents_now(db, ids=[vet["id"], recent["id"]])
    finally:
        db.close()
    assert stats["veterinaries"] == 1 and stats["files"] == 2
    purged = _get_vet(vet["id"])
    assert purged.cedula_document_id is None and purged.verification_evidence_document_id is None
    assert private_document_path(old.cedula_document_id) is None
    assert private_document_path(old.verification_evidence_document_id) is None
    kept = _get_vet(recent["id"])
    assert kept.cedula_document_id and private_document_path(kept.cedula_document_id)


def test_yearly_expiry_notifies_owner_with_owner_type(client, make_user, jpeg, no_google):
    owner, vet, admin = _verified(client, make_user, jpeg)
    _set_vet(vet["id"], verification_expires_at=datetime.datetime.utcnow() - datetime.timedelta(days=1))
    db = SessionLocal()
    try:
        assert vet_tasks.expire_verifications_now(db, ids=[vet["id"]]) == [vet["id"]]
    finally:
        db.close()
    owner_types = _types(owner["email"])
    assert "veterinary_expired" in owner_types and "veterinary_pending" not in owner_types
    assert "veterinary_pending" in _types(admin["email"])
    assert _get_vet(vet["id"]).unpublished_at is not None


# --------------------------------------------------------------------------- nombres de terceros
def test_third_party_full_names_are_held_for_review(client, make_user, jpeg, no_google):
    owner, vet, _admin = _verified(client, make_user, jpeg)  # responsable: María López Pérez
    url = f"/veterinaries/{vet['id']}/reviews"
    held = client.post(url, headers=make_user("Reseña Nombre")["h"],
                       json={"rating": 2, "text": "La recepcionista Juana Martínez nos trató mal"})
    assert held.status_code == 201 and held.json()["is_hidden"] is True
    ok = client.post(url, headers=make_user("Reseña Responsable")["h"],
                     json={"rating": 5, "text": "La Dra. María López atendió muy bien a mi perro"})
    assert ok.status_code == 201 and ok.json()["is_hidden"] is False
    plain = client.post(url, headers=make_user("Reseña Sin Nombre")["h"],
                        json={"rating": 5, "text": "La doctora fue muy amable y paciente"})
    assert plain.json()["is_hidden"] is False
    reply = client.post(f"{url}/{ok.json()['id']}/reply", headers=owner["h"],
                        json={"text": "Gracias, se lo diremos a la Sra. Juana Martínez"})
    assert reply.status_code == 400


# --------------------------------------------------------------------------- aclaraciones y quejas
def test_business_days():
    # Viernes 16 de octubre de 2026, mediodía en la Ciudad de México (18:00 UTC)
    friday = datetime.datetime(2026, 10, 16, 18, 0)
    assert vet_router.add_business_days(friday, 5) == datetime.datetime(2026, 10, 23, 18, 0)
    assert vet_router.add_business_days(datetime.datetime(2026, 10, 17, 18, 0), 3) == datetime.datetime(2026, 10, 21, 18, 0)


def test_complaint_without_account_and_clarification_flow(client, make_user, jpeg, no_google, monkeypatch):
    ip = random_ip()
    monkeypatch.setattr(vet_router, "client_ip", lambda request: ip)
    owner, vet, admin = _verified(client, make_user, jpeg)
    author = make_user("Autora Reseña Aclaración")
    rev = client.post(f"/veterinaries/{vet['id']}/reviews", headers=author["h"],
                      json={"rating": 1, "text": "Nos hicieron esperar dos horas"}).json()
    url = f"/veterinaries/{vet['id']}/requests"
    email = f"aludida-{uuid.uuid4().hex[:8]}@pruebas.mx"
    complaint = {"kind": "queja", "relation": "aludido", "reason": "honor_reputacion", "review_id": rev["id"],
                 "text": "La reseña me menciona y no es cierto lo que dice."}

    # Sin cuenta: nombre, correo y aviso de privacidad obligatorios
    assert client.post(url, json=complaint).status_code == 400
    assert client.post(url, json={**complaint, "name": "Ana Aludida", "email": "no-es-correo"}).status_code == 400
    assert client.post(url, json={**complaint, "name": "Ana Aludida", "email": email}).status_code == 400
    r = client.post(url, json={**complaint, "name": "Ana Aludida", "email": email, "accept_privacy": True})
    assert r.status_code == 201, r.text
    queja = r.json()
    assert queja["status"] == "pending" and queja["kind"] == "queja"
    created = datetime.datetime.fromisoformat(queja["created_at"])
    assert (datetime.datetime.fromisoformat(queja["due_at"]) - created).days >= 3
    again = client.post(url, json={**complaint, "name": "Ana Aludida", "email": email, "accept_privacy": True})
    assert again.status_code == 409
    no_reason = {**complaint, "reason": None, "name": "Ana", "email": email, "accept_privacy": True}
    assert client.post(url, json=no_reason).status_code == 400

    # Aclaración de la clínica (con cuenta): requiere la reseña y no lleva datos de contacto
    clar = {"kind": "aclaracion", "relation": "otro", "text": "Ese día atendimos una urgencia; ofrecimos reagendar."}
    assert client.post(url, headers=owner["h"], json=clar).status_code == 400
    assert client.post(url, headers=owner["h"],
                       json={**clar, "review_id": rev["id"], "text": "Llámanos al 55 1234 5678"}).status_code == 400
    r = client.post(url, headers=owner["h"], json={**clar, "review_id": rev["id"]})
    assert r.status_code == 201, r.text
    aclaracion = r.json()
    db = SessionLocal()
    try:
        row = db.query(VeterinaryRequest).filter(VeterinaryRequest.id == aclaracion["id"]).first()
        assert row.relation == "clinica" and row.user_id and row.email == owner["email"]
    finally:
        db.close()

    # Cola del equipo y avisos a los admins
    queue = client.get("/admin/veterinary-requests", headers=admin["h"], params={"limit": 200}).json()
    ids = {x["id"]: x for x in queue}
    assert queja["id"] in ids and aclaracion["id"] in ids and ids[queja["id"]]["overdue"] is False
    assert ids[queja["id"]]["email"] == email and ids[aclaracion["id"]]["review_text"] == rev["text"]
    assert "veterinary_request" in _types(admin["email"])
    assert client.get("/admin/veterinary-requests", headers=owner["h"]).status_code == 403

    # Una queja no se "publica"; se resuelve o se rechaza
    resolve = f"/admin/veterinary-requests/{queja['id']}/resolve"
    assert client.post(resolve, headers=admin["h"], json={"action": "publish", "note": "No aplica"}).status_code == 400
    r = client.post(resolve, headers=admin["h"], json={"action": "reject", "note": "La reseña narra una experiencia."})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.post(resolve, headers=admin["h"], json={"action": "resolve", "note": "Otra vez"}).status_code == 409

    # Aclaración publicada sin comentarios junto a la reseña
    r = client.post(f"/admin/veterinary-requests/{aclaracion['id']}/resolve", headers=admin["h"],
                    json={"action": "publish", "note": "Publicamos tu aclaración."})
    assert r.status_code == 200 and r.json()["status"] == "published"
    shown = client.get(f"/veterinaries/{vet['id']}").json()["reviews"]
    target = next(x for x in shown if x["id"] == rev["id"])
    assert target["clarification"] == clar["text"] and target["clarification_at"]
    assert "veterinary_request_resolved" in _types(owner["email"])
    assert _audit("veterinary_request.publish", aclaracion["id"]) and _audit("veterinary_request.reject", queja["id"])

    # Una clínica pendiente no recibe solicitudes de personas sin cuenta
    pending = _create(client, make_user("Pendiente Solicitudes"), jpeg)
    r = client.post(f"/veterinaries/{pending['id']}/requests",
                    json={**complaint, "review_id": None, "name": "Ana", "email": email, "accept_privacy": True})
    assert r.status_code == 404


def test_anonymous_requests_rate_limited_per_ip(client, make_user, jpeg, no_google, monkeypatch):
    ip = random_ip()
    monkeypatch.setattr(vet_router, "client_ip", lambda request: ip)
    monkeypatch.setattr(vet_router, "REQUESTS_PER_DAY_IP", 1)
    _owner, vet, _ = _verified(client, make_user, jpeg)
    body = {"kind": "queja", "relation": "cliente", "reason": "publicidad_enganosa", "name": "Persona Sin Cuenta",
            "text": "Anuncian servicios que no tienen.", "accept_privacy": True}
    url = f"/veterinaries/{vet['id']}/requests"
    assert client.post(url, json={**body, "email": f"a-{uuid.uuid4().hex[:6]}@pruebas.mx"}).status_code == 201
    assert client.post(url, json={**body, "email": f"b-{uuid.uuid4().hex[:6]}@pruebas.mx"}).status_code == 429


def test_account_deletion_anonymizes_requests(client, make_user, jpeg, no_google):
    _owner, vet, _ = _verified(client, make_user, jpeg)
    u = make_user("Quejosa Con Cuenta")
    r = client.post(f"/veterinaries/{vet['id']}/requests", headers=u["h"],
                    json={"kind": "queja", "relation": "cliente", "reason": "otro", "text": "No respetaron el precio."})
    assert r.status_code == 201
    _set_user(u["email"])  # existe
    _delete_account(client, u)
    db = SessionLocal()
    try:
        row = db.query(VeterinaryRequest).filter(VeterinaryRequest.id == r.json()["id"]).first()
        assert row.name is None and row.email is None and row.text  # la evidencia se conserva sin contacto
        assert db.query(Veterinary).filter(Veterinary.id == vet["id"]).first().is_hidden is False
    finally:
        db.close()


def test_deleted_owner_keeps_evidence_12_months_then_purged(client, make_user, jpeg, no_google):
    owner, vet, _admin = _verified(client, make_user, jpeg)
    evidence = _get_vet(vet["id"]).verification_evidence_document_id
    _delete_account(client, owner)
    gone = _get_vet(vet["id"])
    assert gone.cedula_document_id is None and gone.is_hidden and gone.unpublished_at is not None
    assert gone.verification_evidence_document_id == evidence and private_document_path(evidence)  # 12 meses
    _set_vet(vet["id"], unpublished_at=datetime.datetime.utcnow() - datetime.timedelta(days=400))
    db = SessionLocal()
    try:
        assert vet_tasks.purge_documents_now(db, ids=[vet["id"]])["files"] == 1
    finally:
        db.close()
    assert _get_vet(vet["id"]).verification_evidence_document_id is None and private_document_path(evidence) is None


def test_admin_list_filters_by_text(client, make_user, jpeg, no_google):
    admin = _staff(make_user)
    tag = uuid.uuid4().hex[:8]
    owner = make_user("Dueña Búsqueda")
    vet = _create(client, owner, jpeg, name=f"Clínica Búsqueda {tag}")
    for q in (tag, owner["email"]):
        found = client.get("/admin/veterinaries", headers=admin["h"], params={"status": "pending", "q": q}).json()
        assert [v["id"] for v in found] == [vet["id"]], q
