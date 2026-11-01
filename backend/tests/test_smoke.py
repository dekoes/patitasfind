import time

from app.config import settings
from app.services.compatibility import compute_compatibility
from app.services import vision


def test_health_and_config(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["checks"]["database"] == "ok"
    cfg = client.get("/auth/config").json()
    for key in ("google_enabled", "demo_enabled", "otp_enabled", "payments_enabled", "ai_enabled", "environment",
                "require_phone_verification", "sms_provider", "sentry_dsn_frontend", "posthog_key", "posthog_host",
                "legal_versions"):
        assert key in cfg
    assert set(cfg["legal_versions"]) == {"terms", "privacy"}
    assert cfg["ai_enabled"] == bool(settings.ai_api_key)
    assert r.headers.get("x-request-id")
    assert client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"] == "abc-123"


def test_register_validation_and_login(client):
    base = {"email": "x@pruebas.mx", "password": "Segura123", "full_name": "X", "phone": "5512345678", "accepted_terms": True}
    assert client.post("/auth/register", json={**base, "password": "123"}).status_code == 400
    assert client.post("/auth/register", json={**base, "email": "nope"}).status_code == 400


def test_me_patch_resets_verification(client, user):
    h = user["h"]
    me = client.get("/users/me", headers=h).json()
    assert {"latitude", "longitude", "phone_verified", "avatar_url", "has_password", "terms_version"} <= set(me)
    assert me["phone_verified"] is True and me["phone_verification_required"] is False and me["has_password"] is True
    # La ubicación se guarda en la cuenta solo con las alertas cercanas encendidas (privacidad.html §8)
    r = client.patch("/users/me", headers=h, json={"latitude": 19.4, "longitude": -99.1, "notify_nearby": True})
    assert r.status_code == 200 and r.json()["latitude"] == 19.4 and r.json()["phone_verified"] is True
    r = client.patch("/users/me", headers=h, json={"phone": "+52 55 " + user["phone"][-8:-4] + " " + user["phone"][-4:]})
    assert r.json()["phone_verified"] is True  # mismo número con otro formato: no cambia
    r = client.patch("/users/me", headers=h, json={"phone": "abc"})
    assert r.status_code == 400


def test_adoption_flow_and_chat(client, user, owner, jpeg):
    url = client.post("/upload", headers=owner["h"], files={"file": ("p.jpg", jpeg(1), "image/jpeg")}).json()["url"]
    assert url.startswith("/uploads/") and client.get(url.rsplit(".", 1)[0] + "_thumb.jpg").status_code == 200
    dog = client.post("/dogs", headers=owner["h"], json={
        "name": "Prueba", "size": "Grande", "city": "Ciudad de México", "latitude": 19.4326, "longitude": -99.1332, "photos": [url],
    }).json()
    other = client.post("/dogs", headers=owner["h"], json={"name": "Otro", "latitude": 19.44, "longitude": -99.14}).json()

    disc = client.get("/dogs/discover", headers=user["h"], params={"lat": 19.4326, "lon": -99.1332, "radius_km": 5, "limit": 100}).json()
    ids = [d["id"] for d in disc]
    assert dog["id"] in ids and all(d["distance_km"] is not None for d in disc)
    assert [d["distance_km"] for d in disc] == sorted(d["distance_km"] for d in disc)
    assert next(d for d in disc if d["id"] == dog["id"])["owner"]["full_name"] == "Dueña Prueba"

    assert client.post(f"/dogs/{other['id']}/pass", headers=user["h"]).status_code == 204
    match = client.post(f"/dogs/{dog['id']}/like", headers=user["h"]).json()
    disc = client.get("/dogs/discover", headers=user["h"], params={"lat": 19.4326, "lon": -99.1332, "limit": 100}).json()
    assert dog["id"] not in [d["id"] for d in disc] and other["id"] not in [d["id"] for d in disc]

    app_ = client.post(f"/matches/{match['id']}/apply", headers=user["h"],
                       json={"answers": {"housing": "departamento_chico", "experience": "ninguna"}}).json()
    assert 0 <= app_["compatibility"] < 70
    conv = client.post(f"/matches/{match['id']}/approve", headers=owner["h"]).json()
    assert client.get(f"/dogs/{dog['id']}").json()["status"] == "in_process"
    reminders = client.get("/reminders", headers=user["h"]).json()
    assert {r["type"] for r in reminders} >= {"vet", "follow_up", "vaccine"}
    m = next(x for x in client.get("/matches", headers=user["h"]).json() if x["id"] == match["id"])
    assert m["conversation_id"] == conv["id"] and m["has_application"] is True

    convs = client.get("/conversations", headers=user["h"]).json()
    assert any(c["id"] == conv["id"] and c["title"] == "Prueba" for c in convs)
    r = client.post(f"/conversations/{conv['id']}/messages", headers=user["h"], json={"content": "Hola"})
    assert r.status_code == 201
    client.post(f"/conversations/{conv['id']}/messages", headers=user["h"], json={"content": "¿Sigue disponible?"})
    unread = client.get("/notifications", headers=owner["h"], params={"unread_only": True}).json()
    assert len([n for n in unread if n["type"] == "new_message"]) == 1
    assert client.get(f"/conversations/{conv['id']}", headers=owner["h"]).json()["unread_count"] == 2
    client.patch(f"/conversations/{conv['id']}/read", headers=owner["h"])
    assert client.get(f"/conversations/{conv['id']}", headers=owner["h"]).json()["unread_count"] == 0

    # WebSocket: dos participantes en la misma conversación
    with client.websocket_connect(f"/ws/chat/{conv['id']}?token={user['token']}") as wa, \
            client.websocket_connect(f"/ws/chat/{conv['id']}?token={owner['token']}") as wo:
        wa.send_json({"type": "message", "content": "por websocket"})
        got = wo.receive_json()
        while got.get("type") != "message":
            got = wo.receive_json()
        assert got["content"] == "por websocket" and got["conversation_id"] == conv["id"]
        wo.send_json({"type": "typing"})
        evt = wa.receive_json()
        while evt.get("type") != "typing":
            evt = wa.receive_json()
        assert "sender_id" in evt

    done = client.post(f"/matches/{match['id']}/complete", headers=owner["h"]).json()
    assert done["status"] == "completed" and client.get(f"/dogs/{dog['id']}").json()["status"] == "adopted"
    assert client.delete(f"/dogs/{other['id']}", headers=owner["h"]).status_code == 204


def test_ws_rejects_non_participant(client, make_user, user, owner):
    dog = client.post("/dogs", headers=owner["h"], json={"name": "WS"}).json()
    match = client.post(f"/dogs/{dog['id']}/like", headers=user["h"]).json()
    conv = client.post(f"/matches/{match['id']}/approve", headers=owner["h"]).json()
    intruder = make_user("Intruso")
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/chat/{conv['id']}?token={intruder['token']}") as ws:
            ws.receive_json()


def test_lost_reports_matching_contact_resolve(client, user, owner, jpeg):
    url = client.post("/upload", headers=user["h"], files={"file": ("p.jpg", jpeg(42), "image/jpeg")}).json()["url"]
    lost = client.post("/lost-reports", headers=user["h"], json={
        "dog_name": "Manchas", "report_type": "lost", "city": "Puebla", "latitude": 19.04, "longitude": -98.2, "photos": [url]}).json()
    found = client.post("/lost-reports", headers=owner["h"], json={
        "dog_name": "Sin nombre", "report_type": "found", "city": "Puebla", "latitude": 19.041, "longitude": -98.201, "photos": [url]}).json()
    # Las firmas de las fotos se calculan en segundo plano (Celery o BackgroundTasks), no en la petición
    top = None
    for _ in range(40):
        matches = client.get(f"/lost-reports/{lost['id']}/matches").json()
        top = next((m for m in matches if m["id"] == found["id"]), None)
        if top:
            break
        time.sleep(0.5)
    assert top and top["type"] == "found" and top["score"] >= 90

    listing = client.get("/lost-reports", params={"lat": 19.04, "lon": -98.2, "radius_km": 20}).json()
    assert all("contact_phone" not in r for r in listing)
    assert any(r["id"] == lost["id"] and r["reporter"]["full_name"] == "Adoptante Prueba" for r in listing)

    # Notificación de posible coincidencia (Celery o BackgroundTasks)
    for _ in range(20):
        notes = client.get("/notifications", headers=user["h"]).json()
        if any(n["type"] == "possible_match" for n in notes):
            break
        time.sleep(0.5)
    assert any(n["type"] == "possible_match" for n in notes)

    conv = client.post(f"/lost-reports/{lost['id']}/contact", headers=owner["h"]).json()
    assert conv["lost_report_id"] == lost["id"] and conv["title"] == "Reporte: Manchas"
    assert client.patch(f"/lost-reports/{lost['id']}/resolve", headers=owner["h"]).status_code == 403
    res = client.patch(f"/lost-reports/{lost['id']}/resolve", headers=user["h"]).json()
    assert res["status"] == "resolved" and res["resolved_at"]


def test_search_by_photo_and_ai(client, user, jpeg):
    data = jpeg(7)
    url = client.post("/upload", headers=user["h"], files={"file": ("p.jpg", data, "image/jpeg")}).json()["url"]
    client.post("/lost-reports", headers=user["h"], json={"dog_name": "Foto", "report_type": "found", "photos": [url]})
    r = client.post("/search/by-photo", files={"file": ("q.jpg", data, "image/jpeg")}, data={"report_type": "found"})
    assert r.status_code == 200
    body = r.json()
    assert body["matches"] and body["matches"][0]["score"] >= 90
    ai = client.post("/ai/analyze-photo", headers=user["h"], files={"file": ("q.jpg", data, "image/jpeg")})
    assert ai.status_code == (503 if not settings.ai_enabled else 200)


def test_orders_and_donations_simulated(client, user):
    if settings.payments_enabled:
        return
    products = client.get("/products").json()
    refuges = client.get("/refuges").json()
    if products:
        order = client.post("/orders", headers=user["h"], json={
            "items": [{"product_id": products[0]["id"], "quantity": 1}], "shipping_address": "Calle 1, CDMX",
            "accepted_terms": True, "consent_prepayment": True}).json()
        assert order["simulated"] is True and order["status"] == "paid" and order["checkout_url"] is None
        assert client.get("/payments/status", headers=user["h"], params={"order": order["id"]}).json()["status"] == "paid"
    if refuges:
        before = client.get(f"/refuges/{refuges[0]['id']}").json()["points"]
        d = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": refuges[0]["id"], "amount": 100}).json()
        assert d["simulated"] is True and d["status"] == "approved"
        # Los donativos no suman puntos de ranking (donativos.html §12)
        assert client.get(f"/refuges/{refuges[0]['id']}").json()["points"] == before
    wh = client.post("/payments/mercadopago/webhook?type=payment&data.id=999", json={"type": "payment", "data": {"id": "999"}})
    assert wh.status_code == 200


def test_whatsapp_webhook(client):
    ok = client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": settings.whatsapp_verify_token, "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    assert client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"}).status_code == 403
    meta = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "contacts": [{"profile": {"name": "Pruebas"}, "wa_id": "5210000000001"}],
        "messages": [{"from": "5210000000001", "id": "wamid.T", "type": "text", "text": {"body": "hola"}}]}}]}]}
    r = client.post("/whatsapp/webhook", json=meta)
    assert r.status_code == 200 and r.json()["events"] == 1
    if not settings.is_production:
        sim = client.post("/whatsapp/webhook", json={"phone": "sim-pytest", "message": "hola"}).json()
        assert sim["stage"] == "menu" and "GuauWoow" in sim["response"]
        sim = client.post("/whatsapp/webhook", json={"phone": "sim-pytest", "message": "3"}).json()
        # El bot no gestiona adopciones: solo envía el enlace a la app (terminos.html 11.3)
        assert "/app/" in sim["response"] and "buscan hogar" not in sim["response"]


def test_forgot_and_reset(client, user):
    r = client.post("/auth/forgot-password", json={"email": user["email"]}).json()
    assert r["ok"] is True
    if "dev_link" in r:
        token = r["dev_link"].split("reset=")[1]
        assert client.post("/auth/reset-password", json={"token": token, "password": "NuevaClave1"}).json() == {"ok": True}
        assert client.post("/auth/reset-password", json={"token": token, "password": "OtraClave1"}).status_code == 400
        assert client.post("/auth/login", data={"username": user["email"], "password": "NuevaClave1"}).status_code == 200


def test_compatibility_heuristic():
    class Dog:
        size, age_years = "Grande", 3
    low = compute_compatibility({"housing": "departamento chico", "experience": "ninguna", "hours_alone": "10"}, Dog())
    high = compute_compatibility({"housing": "casa_con_jardin", "experience": "mucha", "outdoor": "jardin"}, Dog())
    assert 0 <= low < 50 < high <= 100
    assert compute_compatibility({}, Dog()) is None


def test_visual_similarity(jpeg):
    a, b = vision.image_signature(jpeg(1)), vision.image_signature(jpeg(2))
    same = vision.combined_score({"photos": [a]}, None, {"photos": [a]}, None)
    diff = vision.combined_score({"photos": [a]}, None, {"photos": [b]}, None)
    assert same == 100 and diff < 60
