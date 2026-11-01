"""Registro, verificación de teléfono obligatoria, contraseña y derechos ARCO."""
import datetime
import uuid

import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.database import SessionLocal
from app.models import User
from tests.conftest import random_ip, random_phone, verify_user

PHONE_403 = {"detail": "Verifica tu teléfono para continuar", "code": "phone_verification_required"}


def _email():
    return f"test-{uuid.uuid4().hex[:10]}@pruebas.mx"


def _rewind_cooldown(email: str, seconds: int = 120):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        u.phone_otp_sent_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=seconds)
        db.commit()
    finally:
        db.close()


def test_register_requires_phone_and_terms(client):
    base = {"email": _email(), "password": "Segura123", "full_name": "Nueva", "is_adult": True, "birth_date": "1990-01-01"}
    r = client.post("/auth/register", json={**base, "accepted_terms": True})
    assert r.status_code == 400 and "celular" in r.json()["detail"]
    r = client.post("/auth/register", json={**base, "phone": "12345", "accepted_terms": True})
    assert r.status_code == 400
    r = client.post("/auth/register", json={**base, "phone": random_phone()})
    assert r.status_code == 400 and "Términos" in r.json()["detail"]
    r = client.post("/auth/register", json={**base, "phone": random_phone(), "accepted_terms": False})
    assert r.status_code == 400
    r = client.post("/auth/register", json={**base, "phone": "+52 1 " + random_phone(), "accepted_terms": True,
                                            "marketing_opt_in": True})
    assert r.status_code == 201
    me = client.get("/users/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["phone"].startswith("+52") and len(me["phone"]) == 13
    assert me["terms_version"] == settings.legal_terms_version and me["privacy_version"] == settings.legal_privacy_version
    assert me["terms_accepted_at"] and me["marketing_opt_in"] is True
    assert me["phone_verified"] is False and me["phone_verification_required"] is True


def test_writes_require_verified_phone(client, unverified, owner):
    h = unverified["h"]
    r = client.post("/lost-reports", headers=h, json={"dog_name": "Bobi", "report_type": "lost"})
    assert r.status_code == 403 and r.json() == PHONE_403
    assert client.post("/dogs", headers=h, json={"name": "X"}).json() == PHONE_403
    assert client.post("/orders", headers=h, json={"items": [], "shipping_address": "x"}).status_code == 403
    assert client.post("/payments/donations", headers=h, json={"accepted_policy": True, "refuge_id": 1, "amount": 50}).status_code == 403
    assert client.post("/refuges/register", headers=h, json={"name": "R"}).status_code == 403
    assert client.post("/foster-homes/register", headers=h, json={"capacity": 1}).status_code == 403
    dog = client.post("/dogs", headers=owner["h"], json={"name": "Lupe"}).json()
    assert client.post(f"/dogs/{dog['id']}/like", headers=h).status_code == 403
    assert client.post(f"/dogs/{dog['id']}/pass", headers=h).status_code == 403
    # Lecturas y perfil siguen abiertos
    assert client.get("/users/me", headers=h).status_code == 200
    assert client.get("/lost-reports").status_code == 200
    assert client.get(f"/dogs/{dog['id']}").status_code == 200
    r = client.patch("/users/me", headers=h, json={"city": "Puebla"})
    assert r.status_code == 200 and r.json()["city"] == "Puebla"

    verify_user(client, unverified)
    r = client.post("/lost-reports", headers=h, json={"dog_name": "Bobi", "report_type": "lost"})
    assert r.status_code == 201, r.text


def test_demo_user_is_exempt(client):
    if not settings.demo_enabled:
        pytest.skip("demo desactivado")
    token = client.post("/auth/demo-login").json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    me = client.get("/users/me", headers=h).json()
    assert me["phone_verification_required"] is False
    r = client.post("/lost-reports", headers=h, json={"dog_name": "Demo", "report_type": "found"})
    assert r.status_code == 201
    client.patch(f"/lost-reports/{r.json()['id']}/resolve", headers=h)


def test_send_code_cooldown_attempts_and_verify(client, unverified):
    u = unverified
    sent = client.post("/users/me/phone/send-code", headers=u["hip"])
    assert sent.status_code == 200
    body = sent.json()
    assert body["sent"] is True and body["phone"] == u["phone"] and body["cooldown"] == 60
    assert len(body["dev_code"]) == 6 and body["dev_code"].isdigit()
    again = client.post("/users/me/phone/send-code", headers=u["hip"])
    assert again.status_code == 429 and "Retry-After" in again.headers

    wrong = "000000" if body["dev_code"] != "000000" else "111111"
    for i in range(settings.otp_max_attempts - 1):
        r = client.post("/users/me/phone/verify", headers=u["h"], json={"code": wrong})
        assert r.status_code == 400 and "Código incorrecto" in r.json()["detail"]
    r = client.post("/users/me/phone/verify", headers=u["h"], json={"code": wrong})
    assert r.status_code == 429 and r.json()["detail"] == "Demasiados intentos, espera unos minutos"
    # Ni el código correcto sirve después de agotar los intentos
    assert client.post("/users/me/phone/verify", headers=u["h"], json={"code": body["dev_code"]}).status_code == 429

    _rewind_cooldown(u["email"])
    code = client.post("/users/me/phone/send-code", headers=u["hip"]).json()["dev_code"]
    assert client.post("/users/me/phone/verify", headers=u["h"], json={"code": code}).json() == {"verified": True}
    assert client.get("/users/me", headers=u["h"]).json()["phone_verified"] is True


def test_code_is_bound_to_phone(client, unverified):
    u = unverified
    code = client.post("/users/me/phone/send-code", headers=u["hip"]).json()["dev_code"]
    client.patch("/users/me", headers=u["h"], json={"phone": random_phone()})
    r = client.post("/users/me/phone/verify", headers=u["h"], json={"code": code})
    assert r.status_code == 400


def test_send_code_with_phone_in_body(client, make_user):
    u = make_user("Google", verify=False)
    new_phone = random_phone()
    r = client.post("/users/me/phone/send-code", headers=u["hip"], json={"phone": new_phone})
    assert r.status_code == 200 and r.json()["phone"] == "+52" + new_phone
    assert client.post("/users/me/phone/send-code", headers=u["hip"], json={"phone": "999"}).status_code == 400


def test_duplicate_verified_phone(client, user, make_user):
    # Registrar con un teléfono ya verificado en otra cuenta
    r = client.post("/auth/register", json={"email": _email(), "password": "Segura123", "full_name": "Dup",
                                            "phone": user["phone"], "accepted_terms": True, "is_adult": True, "birth_date": "1990-01-01"})
    assert r.status_code == 409 and r.json()["detail"] == "Este teléfono ya está verificado en otra cuenta"
    # Cambiar a un teléfono ya verificado y pedir código
    other = make_user("Otro", verify=False)
    client.patch("/users/me", headers=other["h"], json={"phone": user["phone"]})
    r = client.post("/users/me/phone/send-code", headers=other["hip"])
    assert r.status_code == 409


def test_send_limits_per_phone_and_ip(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "otp_max_sends_per_phone_hour", 2)
    u = make_user("Límite", verify=False)
    for _ in range(2):
        assert client.post("/users/me/phone/send-code", headers=u["hip"]).status_code == 200
        _rewind_cooldown(u["email"])
    r = client.post("/users/me/phone/send-code", headers=u["hip"])
    assert r.status_code == 429 and r.json()["detail"] == "Demasiados intentos, espera unos minutos"

    monkeypatch.setattr(settings, "otp_max_sends_per_phone_hour", 5)
    monkeypatch.setattr(settings, "otp_max_sends_per_ip_hour", 2)
    ip = random_ip()
    results = []
    for _ in range(3):
        v = make_user("IP", verify=False)
        results.append(client.post("/users/me/phone/send-code", headers={**v["h"], "X-Real-IP": ip}).status_code)
    assert results == [200, 200, 429]


def test_change_password(client, user):
    h = user["h"]
    assert client.post("/users/me/password", headers=h, json={"current_password": "mal", "new_password": "NuevaClave9"}).status_code == 400
    assert client.post("/users/me/password", headers=h, json={"current_password": user["password"], "new_password": "corta"}).status_code == 400
    r = client.post("/users/me/password", headers=h, json={"current_password": user["password"], "new_password": "NuevaClave9"})
    assert r.json()["ok"] is True and r.json()["access_token"]
    assert client.post("/auth/login", data={"username": user["email"], "password": "NuevaClave9"}).status_code == 200
    assert client.post("/auth/login", data={"username": user["email"], "password": user["password"]}).status_code == 401


def test_passwordless_user_can_set_password(client, user):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == user["email"]).first()
        u.hashed_password = None
        db.commit()
    finally:
        db.close()
    assert client.get("/users/me", headers=user["h"]).json()["has_password"] is False
    r = client.post("/users/me/password", headers=user["h"], json={"new_password": "DesdeGoogle1"})
    assert r.json()["ok"] is True
    # Las sesiones anteriores se cierran; la respuesta trae el token nuevo
    new_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/users/me", headers=new_h).json()["has_password"] is True


def test_accept_terms_endpoint(client, user):
    assert client.post("/users/me/terms", headers=user["h"], json={"accepted_terms": False}).status_code == 400
    r = client.post("/users/me/terms", headers=user["h"], json={"accepted_terms": True, "marketing_opt_in": False})
    assert r.status_code == 200 and r.json()["marketing_opt_in"] is False


def test_export_my_data(client, user, owner):
    client.post("/lost-reports", headers=user["h"], json={"dog_name": "Export", "report_type": "lost"})
    client.post("/dogs", headers=user["h"], json={"name": "MiPerro"})
    r = client.get("/users/me/export", headers=user["h"])
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"] and ".json" in r.headers["content-disposition"]
    data = r.json()
    for key in ("profile", "dogs", "lost_reports", "matches", "adoption_applications", "messages_sent", "orders",
                "donations", "notifications"):
        assert key in data
    assert data["profile"]["email"] == user["email"] and "hashed_password" not in data["profile"]
    assert any(d["name"] == "MiPerro" for d in data["dogs"])
    assert any(rep["dog_name"] == "Export" for rep in data["lost_reports"])


def test_delete_account(client, make_user):
    u = make_user("Para Borrar")
    h = u["h"]
    uid = client.get("/users/me", headers=h).json()["id"]
    dog = client.post("/dogs", headers=h, json={"name": "Borrable"}).json()
    rep = client.post("/lost-reports", headers=h, json={"dog_name": "Rep", "report_type": "lost"}).json()
    assert client.request("DELETE", "/users/me", headers=h, json={"confirm": "no"}).status_code == 400
    assert client.request("DELETE", "/users/me", headers=h, json={"confirm": "ELIMINAR", "password": "mala"}).status_code == 400
    r = client.request("DELETE", "/users/me", headers=h, json={"confirm": "ELIMINAR", "password": u["password"]})
    assert r.json() == {"ok": True}
    assert client.get("/users/me", headers=h).status_code == 401
    assert client.post("/auth/login", data={"username": u["email"], "password": u["password"]}).status_code == 401
    # El contenido de cuentas eliminadas deja de ser público (más casos en test_privacy_exposure.py)
    assert client.get(f"/dogs/{dog['id']}").status_code == 404
    assert client.get(f"/lost-reports/{rep['id']}").status_code == 404
    db = SessionLocal()
    try:
        row = db.query(User).filter(User.email == f"eliminado-{uid}@patitasfind.invalid").first()
        assert row and row.full_name == "Usuario eliminado" and row.phone is None and row.is_active is False
        assert row.hashed_password is None and row.deleted_at is not None
    finally:
        db.close()
    # El teléfono queda libre para otra cuenta
    r = client.post("/auth/register", json={"email": _email(), "password": "Segura123", "full_name": "Nuevo",
                                            "phone": u["phone"], "accepted_terms": True, "is_adult": True, "birth_date": "1990-01-01"})
    assert r.status_code == 201


def test_ws_unverified_cannot_send(client, unverified, owner):
    dog = client.post("/dogs", headers=owner["h"], json={"name": "WSV"}).json()
    verify_user(client, unverified)
    match = client.post(f"/dogs/{dog['id']}/like", headers=unverified["h"]).json()
    conv = client.post(f"/matches/{match['id']}/approve", headers=owner["h"]).json()
    # Le quitamos la verificación al adoptante (p. ej. cambió de número)
    client.patch("/users/me", headers=unverified["h"], json={"phone": random_phone()})
    r = client.post(f"/conversations/{conv['id']}/messages", headers=unverified["h"], json={"content": "hola"})
    assert r.status_code == 403 and r.json()["code"] == "phone_verification_required"
    with client.websocket_connect(f"/ws/chat/{conv['id']}?token={unverified['token']}") as ws:
        ws.send_json({"type": "message", "content": "hola"})
        evt = ws.receive_json()
        while evt.get("type") != "error":
            evt = ws.receive_json()
        assert evt["code"] == "phone_verification_required"
    assert client.get(f"/conversations/{conv['id']}/messages", headers=unverified["h"]).status_code == 200


def test_inactive_token_rejected(client, make_user):
    u = make_user("Inactivo")
    db = SessionLocal()
    try:
        row = db.query(User).filter(User.email == u["email"]).first()
        row.is_active = False
        db.commit()
    finally:
        db.close()
    assert client.get("/users/me", headers=u["h"]).status_code == 401
    assert client.post("/auth/login", data={"username": u["email"], "password": u["password"]}).status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/chat/1?token={u['token']}") as ws:
            ws.receive_json()
