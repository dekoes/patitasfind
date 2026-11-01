"""Directorio de veterinarias: registro con cédula, verificación por admins, listado con distancia y "Abierto
ahora", reseñas propias, Google Places (siempre con el cliente HTTP sustituido: nunca se llama a Google en las
pruebas), tareas programadas y moderación."""
import datetime
import random
import uuid

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import AdminAuditLog, Notification, User, Veterinary, VeterinaryReview
from app.routers import veterinaries as vet_router
from app.services import google_places
from app.tasks import veterinaries as vet_tasks
from tests.conftest import random_ip

UTC = datetime.timezone.utc


# --------------------------------------------------------------------------- utilidades
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


def _staff(make_user):
    u = make_user("Admin Veterinarias", verify=False)
    u["id"] = _set_user(u["email"], role="admin")
    return u


def _set_vet(vid, **fields):
    db = SessionLocal()
    try:
        vet = db.query(Veterinary).filter(Veterinary.id == vid).first()
        for k, v in fields.items():
            setattr(vet, k, v)
        db.commit()
    finally:
        db.close()


def _get_vet(vid) -> Veterinary:
    db = SessionLocal()
    try:
        vet = db.query(Veterinary).filter(Veterinary.id == vid).first()
        db.expunge(vet)
        return vet
    finally:
        db.close()


def _doc(client, u, jpeg) -> str:
    r = client.post("/upload/document", headers=u["h"],
                    files={"file": ("cedula.jpg", jpeg(random.randint(0, 10 ** 6)), "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _spot():
    """Coordenadas aleatorias lejos de otras pruebas (la base de desarrollo es compartida)."""
    return round(random.uniform(24.0, 26.0), 5), round(random.uniform(-112.0, -110.5), 5)


def _body(doc_id, **extra):
    lat, lon = _spot()
    body = {
        "name": f"Clínica Patitas {uuid.uuid4().hex[:8]}",
        "description": "Consultas, vacunas y cirugías de rutina.",
        "address": "Av. Siempre Viva 742", "city": "La Paz", "state": "BCS", "postal_code": "23000",
        "latitude": lat, "longitude": lon, "phone": "612 123 4567",
        "hours": {"mon": [{"open": "09:00", "close": "18:00"}], "sun": []},
        "services": ["Consulta general", "vacunas"], "emergency_24h": False,
        "responsible_vet_name": "María López Pérez", "cedula_profesional": "1234567",
        "cedula_document_id": doc_id, "consent": True,
    }
    body.update(extra)
    return body


def _create(client, u, jpeg, **extra):
    r = client.post("/veterinaries", headers=u["h"], json=_body(_doc(client, u, jpeg), **extra))
    assert r.status_code == 201, r.text
    return r.json()


def _evidence(client, admin, jpeg, vid, carrera="Médico Veterinario Zootecnista"):
    """Verificación con la evidencia del cotejo: carrera del RNP y captura privada que sube el admin."""
    return client.post(f"/admin/veterinaries/{vid}/verify", headers=admin["h"],
                       json={"carrera": carrera, "evidence_document_id": _doc(client, admin, jpeg)})


def _verified(client, make_user, jpeg, admin=None, **extra):
    owner = make_user("Dueña Veterinaria")
    vet = _create(client, owner, jpeg, **extra)
    admin = admin or _staff(make_user)
    r = _evidence(client, admin, jpeg, vet["id"])
    assert r.status_code == 200, r.text
    return owner, r.json(), admin


def _audit(action, vid):
    db = SessionLocal()
    try:
        return db.query(AdminAuditLog).filter(AdminAuditLog.action == action, AdminAuditLog.target_id == vid).all()
    finally:
        db.close()


@pytest.fixture
def no_google(monkeypatch):
    monkeypatch.setattr(settings, "google_maps_api_key", None)

    def boom(*a, **k):  # pragma: no cover - si se llega aquí la prueba falla
        raise AssertionError("No se debe llamar a Google sin llave")

    monkeypatch.setattr(google_places, "_http", boom)


@pytest.fixture
def fake_google(monkeypatch):
    """Sustituye la única salida HTTP del módulo de Places; registra las llamadas."""
    monkeypatch.setattr(settings, "google_maps_api_key", "llave-de-prueba")
    monkeypatch.setattr(google_places, "budget_available", lambda: True)
    ip = random_ip()  # el límite por IP vive en Redis compartido: cada prueba usa una IP nueva
    monkeypatch.setattr(vet_router, "client_ip", lambda request: ip)
    state = {"calls": [], "missing": set(), "renamed": {}, "fail": False, "reviews": 6}

    def http(method, url, headers, json=None, params=None):
        state["calls"].append({"method": method, "url": url, "headers": headers, "json": json, "params": params})
        assert headers["X-Goog-Api-Key"] == "llave-de-prueba" and headers["X-Goog-FieldMask"]
        if state["fail"]:
            raise google_places.requests.ConnectionError("sin red")
        if url.endswith("/places:searchText"):
            return 200, {"places": [
                {"id": "ChIJcandidato000001", "displayName": {"text": "Clínica Candidata"},
                 "formattedAddress": "Calle 1, La Paz", "rating": 4.6, "userRatingCount": 120},
                {"displayName": {"text": "Sin id"}},
            ]}
        place_id = url.rsplit("/", 1)[-1]
        if place_id in state["missing"]:
            return 404, {"error": {"status": "NOT_FOUND"}}
        current = state["renamed"].get(place_id, place_id)
        if headers["X-Goog-FieldMask"] == google_places.FIELDS_ID_ONLY:
            return 200, {"id": current}
        reviews = [{
            "rating": 5 - (i % 5), "relativePublishTimeDescription": f"hace {i + 1} semanas",
            "text": {"text": f"Reseña {i}", "languageCode": "es"},
            "originalText": {"text": f"Review {i}" if i == 0 else f"Reseña {i}", "languageCode": "en" if i == 0 else "es"},
            "authorAttribution": {"displayName": f"Autor {i}", "uri": f"https://www.google.com/maps/contrib/{i}",
                                  "photoUri": f"https://lh3.googleusercontent.com/a/{i}"},
            "publishTime": "2026-09-01T10:00:00Z", "googleMapsUri": f"https://www.google.com/maps/reviews/{i}",
            "flagContentUri": f"https://www.google.com/local/review/rap/report?i={i}",
        } for i in range(state["reviews"])]
        return 200, {"id": current, "googleMapsUri": f"https://maps.google.com/?cid={current}", "rating": 4.4,
                     "userRatingCount": 87, "reviews": reviews}

    monkeypatch.setattr(google_places, "_http", http)
    return state


# --------------------------------------------------------------------------- "Abierto ahora"
def test_is_open_now_rules():
    hours = {"mon": [{"open": "09:00", "close": "18:00"}], "fri": [{"open": "20:00", "close": "02:00"}], "sat": []}
    # 2026-10-19 es lunes; Ciudad de México es UTC-6 todo el año
    assert vet_router.is_open_now(hours, "Ciudad de México", now=datetime.datetime(2026, 10, 19, 15, 0, tzinfo=UTC))
    assert vet_router.is_open_now(hours, "CDMX", now=datetime.datetime(2026, 10, 20, 0, 30, tzinfo=UTC)) is False
    # Rango que cruza la medianoche: viernes 20:00 a sábado 02:00
    assert vet_router.is_open_now(hours, "Jalisco", now=datetime.datetime(2026, 10, 24, 7, 0, tzinfo=UTC))
    assert vet_router.is_open_now(hours, "Jalisco", now=datetime.datetime(2026, 10, 24, 9, 0, tzinfo=UTC)) is False
    # Quintana Roo va una hora adelante del centro (UTC-5)
    t = datetime.datetime(2026, 10, 19, 14, 30, tzinfo=UTC)
    assert vet_router.is_open_now(hours, "Quintana Roo", now=t) is True
    assert vet_router.is_open_now(hours, "Ciudad de México", now=t) is False
    # Urgencias 24 h siempre abierta; sin horario = desconocido
    assert vet_router.is_open_now({}, "Sonora", emergency_24h=True) is True
    assert vet_router.is_open_now({}, "Sonora") is None
    assert vet_router.is_open_now({"tue": [{"open": "00:00", "close": "00:00"}]}, None,
                                  now=datetime.datetime(2026, 10, 20, 12, 0, tzinfo=UTC)) is True


# --------------------------------------------------------------------------- registro
def test_register_pending_and_one_per_user(client, make_user, jpeg, no_google):
    owner = make_user("Veterinaria Uno")
    vet = _create(client, owner, jpeg)
    assert vet["status"] == "pending" and vet["state"] == "Baja California Sur"
    assert vet["services"] == ["Consulta general", "Vacunas"]  # normalizado al catálogo
    assert vet["cedula_document_id"] and vet["badge_text"] is None and vet["google_linked"] is False

    again = client.post("/veterinaries", headers=owner["h"], json=_body(_doc(client, owner, jpeg)))
    assert again.status_code == 409

    me = client.get("/veterinaries/me", headers=owner["h"])
    assert me.status_code == 200 and me.json()["id"] == vet["id"]
    # Pendiente: la ve su dueña, no el público
    assert client.get(f"/veterinaries/{vet['id']}").status_code == 404
    assert client.get(f"/veterinaries/{vet['id']}", headers=owner["h"]).json()["status"] == "pending"
    # Avisa a los admins
    db = SessionLocal()
    try:
        assert db.query(Notification).filter(Notification.type == "veterinary_pending",
                                             Notification.data["veterinary_id"].as_integer() == vet["id"]).count() >= 1
    finally:
        db.close()


def test_register_requires_verified_phone_cedula_and_clean_profile(client, make_user, unverified, jpeg, no_google):
    r = client.post("/veterinaries", headers=unverified["h"], json=_body("x" * 32 + ".jpg"))
    assert r.status_code == 403 and r.json()["code"] == "phone_verification_required"

    u = make_user("Veterinaria Dos")
    doc = _doc(client, u, jpeg)
    assert client.post("/veterinaries", headers=u["h"], json=_body(None)).status_code == 400
    assert client.post("/veterinaries", headers=u["h"], json=_body("0" * 32 + ".jpg")).status_code == 400
    bad_cedula = client.post("/veterinaries", headers=u["h"], json=_body(doc, cedula_profesional="ABC"))
    assert bad_cedula.status_code == 422
    ad = client.post("/veterinaries", headers=u["h"], json=_body(doc, description="La mejor clínica, resultados garantizados"))
    assert ad.status_code == 400 and "garantizado" in ad.json()["detail"]
    service = client.post("/veterinaries", headers=u["h"], json=_body(doc, services=["Venta de medicamentos sin receta"]))
    assert service.status_code == 400 and "Servicio no válido" in service.json()["detail"]
    no_phone = client.post("/veterinaries", headers=u["h"], json=_body(doc, phone=None, whatsapp=None))
    assert no_phone.status_code == 400
    bad_state = client.post("/veterinaries", headers=u["h"], json=_body(doc, state="Narnia"))
    assert bad_state.status_code == 400
    assert client.post("/veterinaries", headers=u["h"], json=_body(doc)).status_code == 201


def test_edit_sensitive_fields_back_to_pending(client, make_user, jpeg, no_google):
    owner, vet, _admin = _verified(client, make_user, jpeg)
    r = client.patch(f"/veterinaries/{vet['id']}", headers=owner["h"], json={"description": "Nuevo horario de verano"})
    assert r.status_code == 200 and r.json()["status"] == "verified"
    r = client.patch(f"/veterinaries/{vet['id']}", headers=owner["h"], json={"website": "patitas.mx"})
    assert r.json()["website"] == "https://patitas.mx" and r.json()["hours"]  # el horario no se borra
    r = client.patch(f"/veterinaries/{vet['id']}", headers=owner["h"], json={"cedula_profesional": "7654321"})
    assert r.status_code == 200 and r.json()["status"] == "pending" and r.json()["verified_at"] is None
    other = make_user("Intrusa")
    assert client.patch(f"/veterinaries/{vet['id']}", headers=other["h"], json={"name": "Mía"}).status_code == 403


# --------------------------------------------------------------------------- listado
def test_listing_only_verified_visible_with_distance_and_open_now(client, make_user, jpeg, no_google):
    admin = _staff(make_user)
    tag = uuid.uuid4().hex[:8]
    owner, vet, _ = _verified(client, make_user, jpeg, admin=admin, name=f"Vet Lista {tag}", emergency_24h=True)
    pending = _create(client, make_user("Pendiente"), jpeg, name=f"Vet Pendiente {tag}")
    _owner2, hidden, _ = _verified(client, make_user, jpeg, admin=admin, name=f"Vet Oculta {tag}")
    _set_vet(hidden["id"], is_hidden=True)

    ids = [v["id"] for v in client.get("/veterinaries", params={"q": tag}).json()]
    assert vet["id"] in ids and pending["id"] not in ids and hidden["id"] not in ids

    lat, lon = vet["latitude"], vet["longitude"]
    near = client.get("/veterinaries", params={"lat": lat + 0.05, "lon": lon, "radius_km": 20, "q": tag}).json()
    item = next(v for v in near if v["id"] == vet["id"])
    assert 5 <= item["distance_km"] <= 6.2 and item["open_now"] is True  # urgencias 24 h
    assert item["badge_text"] and "Registro Nacional de Profesionistas" in item["badge_text"]
    assert item["verified_label"].startswith("Cédula consultada en el Registro Nacional de Profesionistas el ")
    far = client.get("/veterinaries", params={"lat": lat + 1.5, "lon": lon, "radius_km": 20, "q": tag}).json()
    assert vet["id"] not in [v["id"] for v in far]
    emergency = client.get("/veterinaries", params={"emergency": "true", "q": tag}).json()
    assert [v["id"] for v in emergency] == [vet["id"]]
    assert vet["id"] in [v["id"] for v in client.get("/veterinaries", params={"city": "la paz", "q": tag}).json()]
    by_service = client.get("/veterinaries", params={"q": "vacunas", "lat": lat, "lon": lon, "radius_km": 1}).json()
    assert vet["id"] in [v["id"] for v in by_service]
    accents = client.get("/veterinaries", params={"q": "Desparasitación", "lat": lat, "lon": lon, "radius_km": 1}).json()
    assert vet["id"] not in [v["id"] for v in accents]
    _set_vet(vet["id"], services=["Desparasitación"])
    for term in ("Desparasitación", "desparasitacion"):
        found = client.get("/veterinaries", params={"q": term, "lat": lat, "lon": lon, "radius_km": 1}).json()
        assert vet["id"] in [v["id"] for v in found], term

    # Cuenta suspendida: su clínica sale del directorio
    _set_user(owner["email"], is_active=False)
    assert vet["id"] not in [v["id"] for v in client.get("/veterinaries", params={"q": tag}).json()]


def test_meta_and_detail_notices(client, make_user, jpeg, no_google):
    meta = client.get("/veterinaries/meta").json()
    assert "Consulta general" in meta["services"] and "Ciudad de México" in meta["states"]
    assert meta["google_enabled"] is False and "emergencias" in meta["notices"]["emergency"]
    _owner, vet, _ = _verified(client, make_user, jpeg)
    d = client.get(f"/veterinaries/{vet['id']}").json()
    assert d["google"] is None and d["reviews"] == [] and d["rating_count"] == 0
    assert set(d["notices"]) >= {"disclaimer", "emergency", "reviews", "google"}


# --------------------------------------------------------------------------- reseñas
def test_reviews_upsert_one_per_user_not_own(client, make_user, jpeg, no_google):
    owner, vet, _ = _verified(client, make_user, jpeg)
    url = f"/veterinaries/{vet['id']}/reviews"
    assert client.post(url, headers=owner["h"], json={"rating": 5}).status_code == 400  # su propia clínica

    ana = make_user("Ana Gómez Ruiz")
    r = client.post(url, headers=ana["h"], json={"rating": 4, "text": "Muy amables con mi perrita", "visited_month": "2026-09"})
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["user"]["full_name"] == "Ana G." and first["author_name"] == "Ana G."
    r = client.post(url, headers=ana["h"], json={"rating": 2, "text": "Cambié de opinión", "incentivized": True})
    assert r.status_code == 200 and r.json()["id"] == first["id"] and r.json()["rating"] == 2
    assert r.json()["incentivized"] is True

    beto = make_user("Beto")
    assert client.post(url, headers=beto["h"], json={"rating": 5}).status_code == 201
    d = client.get(f"/veterinaries/{vet['id']}", headers=ana["h"]).json()
    assert d["rating_count"] == 2 and d["rating_avg"] == 3.5 and d["my_review"]["id"] == first["id"]
    assert len(d["reviews"]) == 2 and d["reviews"][0]["user"]["full_name"] == "Beto"  # más reciente primero

    lowest = client.get(url, params={"order": "lowest"}).json()
    assert [x["rating"] for x in lowest] == [2, 5]
    assert len(client.get(url, params={"skip": 1, "limit": 10}).json()) == 1

    # Las negativas no se ocultan; la reseña se borra solo por su autor
    assert client.delete(f"{url}/me", headers=ana["h"]).status_code == 204
    assert client.delete(f"{url}/me", headers=ana["h"]).status_code == 404
    assert client.get(f"/veterinaries/{vet['id']}").json()["rating_count"] == 1

    # No se reseña una clínica pendiente
    pending = _create(client, make_user("Otra"), jpeg)
    assert client.post(f"/veterinaries/{pending['id']}/reviews", headers=ana["h"], json={"rating": 5}).status_code == 404


def test_review_filters_pii_hold_and_min_age(client, make_user, jpeg, no_google, monkeypatch):
    owner, vet, admin = _verified(client, make_user, jpeg)
    url = f"/veterinaries/{vet['id']}/reviews"
    u = make_user("Reseñadora")
    pii = client.post(url, headers=u["h"], json={"rating": 1, "text": "Llámame al 55 1234 5678 o a yo@correo.mx"})
    assert pii.status_code == 400 and "teléfonos" in pii.json()["detail"]

    held = client.post(url, headers=u["h"], json={"rating": 1, "text": "Son unos estafadores"})
    assert held.status_code == 201 and held.json()["is_hidden"] is True
    assert client.get(f"/veterinaries/{vet['id']}").json()["rating_count"] == 0
    queue = client.get("/admin/veterinary-reviews", headers=admin["h"], params={"hidden": "true", "veterinary_id": vet["id"]})
    assert queue.status_code == 200 and [x["id"] for x in queue.json()] == [held.json()["id"]]
    # El admin la publica tras revisarla
    r = client.patch(f"/admin/content/veterinary_review/{held.json()['id']}", headers=admin["h"], json={"hidden": False})
    assert r.status_code == 200
    assert client.get(f"/veterinaries/{vet['id']}").json()["rating_count"] == 1

    monkeypatch.setattr(settings, "veterinary_review_min_account_days", 7)
    nueva = make_user("Cuenta Nueva")
    r = client.post(url, headers=nueva["h"], json={"rating": 5})
    assert r.status_code == 403 and "7 días" in r.json()["detail"]


def test_owner_reply(client, make_user, jpeg, no_google):
    owner, vet, _ = _verified(client, make_user, jpeg)
    u = make_user("Cliente")
    rev = client.post(f"/veterinaries/{vet['id']}/reviews", headers=u["h"], json={"rating": 3, "text": "Tardaron mucho"}).json()
    url = f"/veterinaries/{vet['id']}/reviews/{rev['id']}/reply"
    assert client.post(url, headers=u["h"], json={"text": "Hola"}).status_code == 403
    assert client.post(url, headers=owner["h"], json={"text": "Escríbenos a hola@vet.mx"}).status_code == 400
    r = client.post(url, headers=owner["h"], json={"text": "Gracias, ya reforzamos el turno de la tarde."})
    assert r.status_code == 200 and r.json()["owner_reply"].startswith("Gracias") and r.json()["rating"] == 3
    assert client.delete(url, headers=owner["h"]).json()["owner_reply"] is None


# --------------------------------------------------------------------------- administración
def test_admin_verify_reject_audit_and_cedula(client, make_user, jpeg, no_google):
    admin = _staff(make_user)
    owner = make_user("Clínica Por Revisar")
    vet = _create(client, owner, jpeg)
    assert client.get("/admin/veterinaries", headers=owner["h"]).status_code == 403
    queue = client.get("/admin/veterinaries", headers=admin["h"], params={"status": "pending", "limit": 200}).json()
    row = next((v for v in queue if v["id"] == vet["id"]), None)
    if row is None:  # la cola compartida de la base de desarrollo puede ser larga: se revisa por id
        row = next(v for v in client.get("/admin/veterinaries", headers=admin["h"],
                                          params={"status": "all", "limit": 5}).json() if v["id"] == vet["id"])
    assert row["owner_email"] == owner["email"] and row["cedula_document_id"]

    # Cédula: solo admins, queda en la bitácora
    assert client.get(f"/admin/veterinaries/{vet['id']}/cedula", headers=owner["h"]).status_code == 403
    doc = client.get(f"/admin/veterinaries/{vet['id']}/cedula", headers=admin["h"])
    assert doc.status_code == 200 and doc.headers["content-type"] == "image/jpeg"
    assert "no-store" in doc.headers["cache-control"] and doc.content[:2] == b"\xff\xd8"
    assert _audit("veterinary_cedula.view", vet["id"])
    # El documento privado no se sirve como archivo estático
    assert client.get(f"/uploads/private/{row['cedula_document_id']}").status_code == 404

    r = client.post(f"/admin/veterinaries/{vet['id']}/reject", headers=admin["h"], json={"note": "La cédula no coincide."})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["rejection_note"] == "La cédula no coincide."
    assert _audit("veterinary.reject", vet["id"])
    # Corregir una rechazada la regresa a revisión
    r = client.patch(f"/veterinaries/{vet['id']}", headers=owner["h"], json={"phone": "6121112233"})
    assert r.json()["status"] == "pending" and r.json()["rejection_note"] is None

    assert client.post(f"/admin/veterinaries/{vet['id']}/verify", headers=admin["h"]).status_code == 422
    r = _evidence(client, admin, jpeg, vet["id"])
    body = r.json()
    assert r.status_code == 200 and body["status"] == "verified" and body["verified_at"]
    expires = datetime.datetime.fromisoformat(body["verification_expires_at"])
    assert 364 <= (expires - datetime.datetime.fromisoformat(body["verified_at"])).days <= 365
    assert _audit("veterinary.verify", vet["id"])
    db = SessionLocal()
    try:
        kinds = {n.type for n in db.query(Notification).filter(Notification.user_id == _set_user(owner["email"]))}
    finally:
        db.close()
    assert {"veterinary_rejected", "veterinary_verified"} <= kinds
    assert client.get(f"/veterinaries/{vet['id']}").status_code == 200


def test_expire_verifications_task(client, make_user, jpeg, no_google):
    _owner, vet, _ = _verified(client, make_user, jpeg)
    _set_vet(vet["id"], verification_expires_at=datetime.datetime.utcnow() - datetime.timedelta(days=1))
    db = SessionLocal()
    try:
        assert vet_tasks.expire_verifications_now(db, ids=[vet["id"]]) == [vet["id"]]
    finally:
        db.close()
    assert _get_vet(vet["id"]).status == "pending"
    assert client.get(f"/veterinaries/{vet['id']}").status_code == 404


# --------------------------------------------------------------------------- Google Places
def test_google_not_configured(client, make_user, jpeg, no_google):
    owner, vet, _ = _verified(client, make_user, jpeg)
    r = client.post(f"/veterinaries/{vet['id']}/google-search", headers=owner["h"], json={"query": "Clínica Patitas"})
    assert r.status_code == 503 and "GOOGLE_MAPS_API_KEY" in r.json()["detail"]
    r = client.post(f"/veterinaries/{vet['id']}/google-link", headers=owner["h"], json={"place_id": "ChIJabcdefghijk"})
    assert r.status_code == 503
    # Aunque tenga place_id guardado, sin llave no hay bloque de Google
    _set_vet(vet["id"], google_place_id="ChIJguardado000001")
    assert client.get(f"/veterinaries/{vet['id']}").json()["google"] is None
    db = SessionLocal()
    try:
        assert vet_tasks.refresh_google_places_now(db)["skipped"] is True
    finally:
        db.close()


def test_google_search_link_and_realtime_block(client, make_user, jpeg, fake_google):
    owner, vet, _ = _verified(client, make_user, jpeg)
    other = make_user("Otra Persona")
    url = f"/veterinaries/{vet['id']}"
    assert client.post(f"{url}/google-search", headers=other["h"], json={"query": "Patitas"}).status_code == 403

    r = client.post(f"{url}/google-search", headers=owner["h"], json={"query": "Clínica Patitas La Paz"})
    assert r.status_code == 200, r.text
    assert r.json() == [{"place_id": "ChIJcandidato000001", "name": "Clínica Candidata", "address": "Calle 1, La Paz",
                         "rating": 4.6, "ratings_total": 120}]
    call = fake_google["calls"][-1]
    assert call["method"] == "POST" and call["json"]["textQuery"] == "Clínica Patitas La Paz"
    assert call["json"]["includedType"] == "veterinary_care"
    assert call["json"]["locationBias"]["circle"]["center"] == {"latitude": vet["latitude"], "longitude": vet["longitude"]}
    assert call["headers"]["X-Goog-FieldMask"] == google_places.FIELDS_SEARCH

    fake_google["missing"].add("ChIJnoexiste0000001")
    r = client.post(f"{url}/google-link", headers=owner["h"], json={"place_id": "ChIJnoexiste0000001"})
    assert r.status_code == 400
    assert client.post(f"{url}/google-link", headers=owner["h"], json={"place_id": "no válido"}).status_code == 400

    place = f"ChIJ{uuid.uuid4().hex[:16]}"
    r = client.post(f"{url}/google-link", headers=owner["h"], json={"place_id": place})
    assert r.status_code == 200, r.text
    linked = r.json()
    assert linked["google_place_id"] == place and linked["google_linked"] is True
    assert f"query_place_id={place}" in linked["google_maps_url"]
    assert fake_google["calls"][-1]["headers"]["X-Goog-FieldMask"] == "id"  # validación sin costo

    # Otra clínica no puede vincular la misma ficha
    owner2, vet2, _ = _verified(client, make_user, jpeg)
    taken = client.post(f"/veterinaries/{vet2['id']}/google-link", headers=owner2["h"], json={"place_id": place})
    assert taken.status_code == 409

    before = len(fake_google["calls"])
    detail = client.get(url)
    assert detail.status_code == 200 and detail.headers["cache-control"] == "no-store"
    g = detail.json()["google"]
    assert len(fake_google["calls"]) == before + 1  # una consulta en tiempo real por vista
    assert fake_google["calls"][-1]["headers"]["X-Goog-FieldMask"] == google_places.FIELDS_DETAIL
    assert g["available"] is True and g["rating"] == 4.4 and g["ratings_total"] == 87
    assert g["attribution"] == "Google Maps" and g["google_maps_url"] == f"https://maps.google.com/?cid={place}"
    assert [x["author_name"] for x in g["reviews"]] == [f"Autor {i}" for i in range(5)]  # máximo 5, mismo orden
    first = g["reviews"][0]
    assert first["profile_photo_url"] and first["author_url"] and first["flag_content_url"] and first["google_maps_url"]
    assert first["original_text"] == "Review 0" and g["translated_notice"]
    assert g["order_notice"] and detail.json()["rating_count"] == 0  # no se mezcla con las reseñas propias

    # Nada de Google se guarda en la base (solo place_id, URL y fechas)
    stored = _get_vet(vet["id"])
    assert not any("Reseña" in str(getattr(stored, c.name) or "") for c in Veterinary.__table__.columns)

    # Si Google falla, el perfil se muestra con el enlace a Maps y sin reseñas
    fake_google["fail"] = True
    g = client.get(url).json()["google"]
    assert g["available"] is False and g["reviews"] == [] and place in g["google_maps_url"]
    fake_google["fail"] = False

    r = client.post(f"{url}/google-link", headers=owner["h"], json={"place_id": None})
    assert r.status_code == 200 and r.json()["google_place_id"] is None and r.json()["google_maps_url"] is None
    assert client.get(url).json()["google"] is None


def test_google_daily_budget(client, make_user, jpeg, fake_google, monkeypatch):
    owner, vet, _ = _verified(client, make_user, jpeg)
    _set_vet(vet["id"], google_place_id=f"ChIJ{uuid.uuid4().hex[:16]}")
    monkeypatch.setattr(google_places, "budget_available", lambda: False)
    before = len(fake_google["calls"])
    g = client.get(f"/veterinaries/{vet['id']}").json()["google"]
    assert g["available"] is False and len(fake_google["calls"]) == before


def test_weekly_google_refresh(client, make_user, jpeg, fake_google):
    now = datetime.datetime.utcnow()
    _o1, renamed, admin = _verified(client, make_user, jpeg)
    _o2, gone, _ = _verified(client, make_user, jpeg, admin=admin)
    _o3, gone_long, _ = _verified(client, make_user, jpeg, admin=admin)
    _o4, fresh, _ = _verified(client, make_user, jpeg, admin=admin)
    ids = {k: f"ChIJ{uuid.uuid4().hex[:16]}" for k in ("renamed", "gone", "gone_long", "fresh", "new")}
    old = now - datetime.timedelta(days=8)
    _set_vet(renamed["id"], google_place_id=ids["renamed"], google_place_checked_at=old)
    _set_vet(gone["id"], google_place_id=ids["gone"], google_place_checked_at=old)
    _set_vet(gone_long["id"], google_place_id=ids["gone_long"], google_place_checked_at=old,
             google_place_error_at=now - datetime.timedelta(days=31))
    _set_vet(fresh["id"], google_place_id=ids["fresh"], google_place_checked_at=now - datetime.timedelta(days=2))
    fake_google["renamed"][ids["renamed"]] = ids["new"]
    fake_google["missing"].update({ids["gone"], ids["gone_long"]})

    db = SessionLocal()
    try:
        stats = vet_tasks.refresh_google_places_now(
            db, now=now, ids=[renamed["id"], gone["id"], gone_long["id"], fresh["id"]])
    finally:
        db.close()
    assert stats == {"checked": 3, "updated": 1, "not_found": 2, "unlinked": 1, "errors": 0, "skipped": False}
    assert all(c["headers"]["X-Goog-FieldMask"] == "id" for c in fake_google["calls"])

    r = _get_vet(renamed["id"])
    assert r.google_place_id == ids["new"] and ids["new"] in r.google_maps_url and r.google_place_checked_at == now
    g = _get_vet(gone["id"])
    assert g.google_place_id == ids["gone"] and g.google_place_error_at == now  # menos de 30 días: se conserva
    gl = _get_vet(gone_long["id"])
    assert gl.google_place_id is None and gl.google_maps_url is None  # más de 30 días sin existir: se desvincula
    assert _get_vet(fresh["id"]).google_place_checked_at < now - datetime.timedelta(days=1)  # no tocaba revisarla

    # Error pasajero: no se marca como revisada ni se desvincula
    _set_vet(gone["id"], google_place_checked_at=old)
    fake_google["fail"] = True
    db = SessionLocal()
    try:
        stats = vet_tasks.refresh_google_places_now(db, now=now, ids=[gone["id"]])
    finally:
        db.close()
    assert stats["errors"] == 1 and _get_vet(gone["id"]).google_place_id == ids["gone"]


# --------------------------------------------------------------------------- moderación
def test_reports_and_hide_veterinary_and_review(client, make_user, jpeg, no_google):
    owner, vet, admin = _verified(client, make_user, jpeg)
    reviewer = make_user("Autora Reseña")
    rev = client.post(f"/veterinaries/{vet['id']}/reviews", headers=reviewer["h"], json={"rating": 1, "text": "No me gustó"}).json()
    reporter = make_user("Reportante")

    assert client.post("/reports", headers=owner["h"], json={"target_type": "veterinary", "target_id": vet["id"],
                                                             "reason": "otro"}).status_code == 400  # la propia
    r = client.post("/reports", headers=reporter["h"], json={"target_type": "veterinary_review", "target_id": rev["id"],
                                                             "reason": "honor_reputacion"})
    assert r.status_code == 201, r.text
    resolved = client.patch(f"/admin/reports/{r.json()['id']}", headers=admin["h"],
                            json={"status": "resolved", "action": "hide_content"})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["target"]["veterinary_id"] == vet["id"]
    assert client.get(f"/veterinaries/{vet['id']}").json()["rating_count"] == 0
    # Su autora la sigue viendo como oculta; editarla no la vuelve a publicar
    mine = client.post(f"/veterinaries/{vet['id']}/reviews", headers=reviewer["h"], json={"rating": 2}).json()
    assert mine["is_hidden"] is True

    r = client.post("/reports", headers=reporter["h"], json={"target_type": "veterinary", "target_id": vet["id"],
                                                             "reason": "cedula_falsa", "details": "No aparece en la SEP"})
    assert r.status_code == 201
    assert client.patch(f"/admin/reports/{r.json()['id']}", headers=admin["h"],
                        json={"status": "resolved", "action": "hide_content"}).status_code == 200
    assert client.get(f"/veterinaries/{vet['id']}").status_code == 404
    assert client.get(f"/veterinaries/{vet['id']}", headers=owner["h"]).json()["is_hidden"] is True
    # Una clínica oculta (o pendiente) no se puede reportar desde fuera
    again = client.post("/reports", headers=make_user("Otro")["h"],
                        json={"target_type": "veterinary", "target_id": vet["id"], "reason": "fraude"})
    assert again.status_code == 404
    assert client.patch(f"/admin/content/veterinary/{vet['id']}", headers=admin["h"], json={"hidden": False}).status_code == 200
    assert client.get(f"/veterinaries/{vet['id']}").status_code == 200

    db = SessionLocal()
    try:
        assert db.query(VeterinaryReview).filter(VeterinaryReview.id == rev["id"]).first().is_hidden is True
    finally:
        db.close()
