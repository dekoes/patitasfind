"""Seguridad de autenticación: revocación de tokens, bloqueo, contraseñas largas, demo en producción,
reglas de superadmin, bitácora, vinculación con Google y verificación de correo."""
import datetime
import logging
import uuid

from jose import jwt

from app.auth import PASSWORD_TOO_LONG, create_email_verification_token, create_password_reset_token
from app.config import DEMO_EMAIL, settings
from app.database import SessionLocal
from app.models import AdminAuditLog, User
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app import oauth
from tests.conftest import random_ip, random_phone

LONG_PASSWORD = "Á" * 40  # 40 caracteres, 80 bytes en UTF-8


def _email(prefix="sec"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@pruebas.mx"


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _set(email, **fields):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        for k, v in fields.items():
            setattr(u, k, v)
        db.commit()
        return u.id
    finally:
        db.close()


def _get(email) -> User:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        db.expunge(u)
        return u
    finally:
        db.close()


def _login(client, email, password, ip=None):
    return client.post("/auth/login", data={"username": email, "password": password},
                       headers={"X-Real-IP": ip or random_ip()})


# --------------------------------------------------------------------------- /auth/config
def test_config_shop_and_support(client, monkeypatch):
    cfg = client.get("/auth/config").json()
    for key in ("shop_enabled", "support_email", "support_whatsapp", "email_enabled"):
        assert key in cfg
    assert cfg["shop_enabled"] is True  # development => True por defecto
    monkeypatch.setattr(settings, "support_email", "ayuda@guauwoow.com")
    monkeypatch.setattr(settings, "support_whatsapp", "+525512345678")
    monkeypatch.setattr(settings, "environment", "production")
    cfg = client.get("/auth/config").json()
    assert cfg["shop_enabled"] is False  # production => False si no se define SHOP_ENABLED
    assert cfg["support_email"] == "ayuda@guauwoow.com" and cfg["support_whatsapp"] == "+525512345678"
    monkeypatch.setattr(settings, "shop_enabled", True)
    assert client.get("/auth/config").json()["shop_enabled"] is True
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "shop_enabled", False)
    assert settings.effective_shop_enabled is False


# --------------------------------------------------------------------------- revocación (tv)
def test_token_carries_tv_and_admin_expires_in_8h(client, make_user):
    u = make_user("Token")
    claims = jwt.get_unverified_claims(u["token"])
    assert claims["tv"] == 0
    assert claims["exp"] - datetime.datetime.now(datetime.timezone.utc).timestamp() > 6 * 24 * 3600
    _set(u["email"], role="admin")
    token = _login(client, u["email"], u["password"]).json()["access_token"]
    remaining = jwt.get_unverified_claims(token)["exp"] - datetime.datetime.now(datetime.timezone.utc).timestamp()
    assert 7.9 * 3600 < remaining <= 8 * 3600 + 5


def test_password_change_revokes_old_tokens(client, make_user):
    u = make_user("Cambio")
    other = _login(client, u["email"], u["password"]).json()["access_token"]
    r = client.post("/users/me/password", headers=u["h"],
                    json={"current_password": u["password"], "new_password": "OtraClave99"})
    assert r.status_code == 200 and r.json()["ok"] is True
    new_token = r.json()["access_token"]
    assert client.get("/users/me", headers=u["h"]).status_code == 401
    assert client.get("/users/me", headers=_h(other)).status_code == 401
    assert client.get("/users/me", headers=_h(new_token)).status_code == 200
    assert jwt.get_unverified_claims(new_token)["tv"] == 1


def test_logout_all(client, make_user):
    u = make_user("Salir")
    second = _login(client, u["email"], u["password"]).json()["access_token"]
    assert client.post("/auth/logout-all").status_code == 401
    assert client.post("/auth/logout-all", headers=u["h"]).json() == {"ok": True}
    assert client.get("/users/me", headers=u["h"]).status_code == 401
    assert client.get("/users/me", headers=_h(second)).status_code == 401
    fresh = _login(client, u["email"], u["password"])
    assert fresh.status_code == 200
    assert client.get("/users/me", headers=_h(fresh.json()["access_token"])).status_code == 200


def test_reset_password_revokes_tokens_and_verifies_email(client, make_user):
    u = make_user("Reset")
    r = client.post("/auth/forgot-password", json={"email": u["email"]})
    token = r.json()["dev_link"].split("reset=")[1]
    assert client.post("/auth/reset-password", json={"token": token, "password": "Restablecida1"}).json() == {"ok": True}
    assert client.get("/users/me", headers=u["h"]).status_code == 401
    assert _get(u["email"]).email_verified is True
    # El mismo enlace ya no sirve
    assert client.post("/auth/reset-password", json={"token": token, "password": "OtraVez1234"}).status_code == 400
    assert _login(client, u["email"], "Restablecida1").status_code == 200


def test_ws_rejects_revoked_token(client, make_user):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    u = make_user("WS")
    client.post("/auth/logout-all", headers=u["h"])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/chat/1?token={u['token']}") as ws:
            ws.receive_json()


# --------------------------------------------------------------------------- bloqueo por cuenta
def test_login_lockout_unknown_email(client):
    email = _email("nadie")
    codes = [_login(client, email, f"mala{i}").status_code for i in range(10)]
    assert codes == [401] * 10
    r = _login(client, email, "otra")
    assert r.status_code == 429 and r.json()["detail"] == "Demasiados intentos, intenta de nuevo en 15 minutos"


def test_login_lockout_existing_account(client, make_user):
    u = make_user("Bloqueo", verify=False)
    for i in range(10):
        assert _login(client, u["email"], f"incorrecta{i}").status_code == 401
    # Bloqueada aunque ahora sí sea la contraseña correcta (y desde otra IP)
    r = _login(client, u["email"], u["password"])
    assert r.status_code == 429 and "15 minutos" in r.json()["detail"]
    # Mismo mensaje que para un correo inexistente: no revela si la cuenta existe
    other = _email("nadie")
    for i in range(10):
        _login(client, other, "x")
    assert _login(client, other, "x").json() == r.json()
    # Al restablecer la contraseña se levanta el bloqueo
    token = create_password_reset_token(_get(u["email"]).id, _get(u["email"]).hashed_password)
    assert client.post("/auth/reset-password", json={"token": token, "password": "Desbloqueo1"}).status_code == 200
    assert _login(client, u["email"], "Desbloqueo1").status_code == 200


def test_login_lockout_memory_fallback(monkeypatch):
    # Sin Redis el bloqueo se cuenta en la memoria del proceso
    monkeypatch.setattr(auth_router.cache, "_get_redis", lambda: None)
    key = auth_router._login_key(_email("memoria"))
    for i in range(10):
        assert not auth_router._login_locked(key), i
        auth_router._register_login_failure(key)
    assert auth_router._login_locked(key)
    auth_router._clear_login_failures(key)
    assert not auth_router._login_locked(key) and key not in auth_router._fail_local


def test_successful_login_resets_failures(client, make_user):
    u = make_user("Reinicio", verify=False)
    for _ in range(9):
        _login(client, u["email"], "mala")
    assert _login(client, u["email"], u["password"]).status_code == 200
    for _ in range(9):
        assert _login(client, u["email"], "mala").status_code == 401
    assert _login(client, u["email"], u["password"]).status_code == 200


# --------------------------------------------------------------------------- contraseñas > 72 bytes
def test_password_longer_than_72_bytes(client, make_user):
    body = {"email": _email(), "password": LONG_PASSWORD, "full_name": "Larga", "phone": random_phone(),
            "accepted_terms": True, "is_adult": True, "birth_date": "1990-01-01"}
    r = client.post("/auth/register", json=body)
    assert r.status_code == 422 and r.json()["detail"] == PASSWORD_TOO_LONG
    # 72 bytes exactos sí se aceptan
    assert client.post("/auth/register", json={**body, "password": "a" * 72}).status_code == 201

    u = make_user("Larga", verify=False)
    r = client.post("/users/me/password", headers=u["h"],
                    json={"current_password": u["password"], "new_password": LONG_PASSWORD})
    assert r.status_code == 422 and r.json()["detail"] == PASSWORD_TOO_LONG
    token = create_password_reset_token(_get(u["email"]).id, _get(u["email"]).hashed_password)
    r = client.post("/auth/reset-password", json={"token": token, "password": LONG_PASSWORD})
    assert r.status_code == 422 and r.json()["detail"] == PASSWORD_TOO_LONG
    # En el inicio de sesión no truena: simplemente no coincide
    assert _login(client, u["email"], LONG_PASSWORD).status_code == 401


# --------------------------------------------------------------------------- demo en producción
def test_demo_and_reserved_emails_rejected_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    base = {"password": "Segura123", "full_name": "Demo", "phone": random_phone(), "accepted_terms": True,
            "is_adult": True, "birth_date": "1990-01-01"}
    for email in (DEMO_EMAIL, "alguien@example.com", "x@sub.example.com", "x@example.org",
                  "y@patitasfind.example.com"):
        r = client.post("/auth/register", json={**base, "email": email})
        assert r.status_code == 400 and "reservado" in r.json()["detail"], email
        assert _login(client, email, "Segura123").status_code == 401
    assert client.post("/auth/demo-login").status_code == 403
    assert client.post("/auth/forgot-password", json={"email": DEMO_EMAIL}).json() == {"ok": True}
    demo = User(email=DEMO_EMAIL, role="user", phone_verified=False)
    assert demo.is_phone_exempt is False and demo.phone_verification_required is True
    assert User(email="a@b.mx", role="admin").is_phone_exempt is True
    monkeypatch.setattr(settings, "environment", "development")
    assert demo.is_phone_exempt is True
    assert auth_router.is_reserved_email("x@notexample.com") is False


# --------------------------------------------------------------------------- correos sin fugas
def test_forgot_password_production_never_logs_link(client, make_user, monkeypatch, capsys, caplog):
    u = make_user("Sin Fugas", verify=False)
    monkeypatch.setattr(settings, "environment", "production")
    with caplog.at_level(logging.DEBUG):
        r = client.post("/auth/forgot-password", json={"email": u["email"]})
    assert r.json() == {"ok": True}
    out = capsys.readouterr()
    assert "reset=" not in out.out and "reset=" not in out.err and "reset=" not in caplog.text
    assert "SMTP" in caplog.text


def test_email_html_escapes_user_values(client, make_user, monkeypatch):
    sent = []
    monkeypatch.setattr(auth_router, "send_email", lambda to, subject, text, html=None: sent.append(html) or True)
    u = make_user('<img src=x onerror="alert(1)">', verify=False)
    client.post("/auth/forgot-password", json={"email": u["email"]})
    auth_router.send_verification_email(1, u["email"], "<b>Hola</b>")
    assert sent and all("<img" not in html and "<b>Hola" not in html for html in sent)
    assert "&lt;img" in sent[-2] and "&lt;b&gt;Hola" in sent[-1]


# --------------------------------------------------------------------------- verificación de correo
def test_email_verification_flow(client, make_user):
    u = make_user("Correo", verify=False)
    me = client.get("/users/me", headers=u["h"]).json()
    assert me["email_verified"] is False
    token = create_email_verification_token(me["id"], u["email"])
    # No sirve como token de sesión
    assert client.get("/users/me", headers=_h(token)).status_code == 401
    assert client.post("/auth/verify-email", json={"token": "basura"}).status_code == 400
    wrong = create_email_verification_token(me["id"], "otro@pruebas.mx")
    assert client.post("/auth/verify-email", json={"token": wrong}).status_code == 400
    expired = jwt.encode({"sub": str(me["id"]), "purpose": "email_verify", "em": jwt.get_unverified_claims(token)["em"],
                          "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)},
                         settings.secret_key, algorithm=settings.algorithm)
    assert client.post("/auth/verify-email", json={"token": expired}).status_code == 400
    r = client.post("/auth/verify-email", json={"token": token})
    assert r.status_code == 200 and r.json()["email_verified"] is True
    assert client.get("/users/me", headers=u["h"]).json()["email_verified"] is True
    # Un solo uso
    r = client.post("/auth/verify-email", json={"token": token})
    assert r.status_code == 400 and "ya se usó" in r.json()["detail"]
    assert client.post("/auth/resend-verification", headers=u["h"]).json()["email_verified"] is True


def test_verification_token_expires_in_48h(client, make_user):
    token = create_email_verification_token(1, "a@pruebas.mx")
    remaining = jwt.get_unverified_claims(token)["exp"] - datetime.datetime.now(datetime.timezone.utc).timestamp()
    assert 47.9 * 3600 < remaining <= 48 * 3600 + 5


def test_resend_verification_rate_limited(client, make_user):
    u = make_user("Reenvío", verify=False)
    assert client.post("/auth/resend-verification").status_code == 401
    for _ in range(3):
        r = client.post("/auth/resend-verification", headers=u["h"])
        assert r.status_code == 200 and "verify_email=" in r.json()["dev_link"]
    link = r.json()["dev_link"]
    assert link.startswith(settings.public_url("/app/#verify_email="))
    r = client.post("/auth/resend-verification", headers=u["h"])
    assert r.status_code == 429 and "verificación" in r.json()["detail"]
    token = link.split("verify_email=")[1]
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200


def test_register_sends_verification_email_when_smtp(client, monkeypatch):
    sent = []
    monkeypatch.setattr(auth_router, "send_email", lambda to, subject, text, html=None: sent.append((to, text)) or True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.pruebas.mx")
    email = _email("smtp")
    r = client.post("/auth/register", json={"email": email, "password": "Segura123", "full_name": "SMTP",
                                            "phone": random_phone(), "accepted_terms": True, "is_adult": True, "birth_date": "1990-01-01"})
    assert r.status_code == 201
    assert sent and sent[0][0] == email and "/app/#verify_email=" in sent[0][1]


# --------------------------------------------------------------------------- Google
def test_google_link_unverified_account_clears_password(client, make_user):
    u = make_user("Víctima", verify=False)
    old_tv = _get(u["email"]).token_version
    db = SessionLocal()
    try:
        user = auth_router.link_google_account(db, {"sub": "g-" + uuid.uuid4().hex, "email": u["email"].upper(),
                                                    "email_verified": True})
        assert user.hashed_password is None and user.email_verified is True
        assert user.token_version == old_tv + 1 and user.google_sub
    finally:
        db.close()
    # La contraseña y los tokens del "atacante" ya no sirven
    assert client.get("/users/me", headers=u["h"]).status_code == 401
    assert _login(client, u["email"], u["password"]).status_code == 401
    token = auth_router.create_session_token(_get(u["email"]))["access_token"]
    notes = client.get("/notifications", headers=_h(token)).json()
    items = notes if isinstance(notes, list) else notes.get("items", [])
    assert any(n["type"] == "security" for n in items)


def test_google_link_verified_account_keeps_password(client, make_user):
    u = make_user("Verificada", verify=False)
    _set(u["email"], email_verified=True)
    db = SessionLocal()
    try:
        user = auth_router.link_google_account(db, {"sub": "g-" + uuid.uuid4().hex, "email": u["email"],
                                                    "email_verified": "true"})
        assert user.hashed_password and user.token_version == 0
    finally:
        db.close()
    assert client.get("/users/me", headers=u["h"]).status_code == 200
    assert _login(client, u["email"], u["password"]).status_code == 200


def test_google_new_account_verified_and_errors(client, monkeypatch):
    import pytest

    db = SessionLocal()
    try:
        email = f"g-{uuid.uuid4().hex[:8]}@gmail.com"
        user = auth_router.link_google_account(db, {"sub": uuid.uuid4().hex, "email": email, "email_verified": True},
                                               {"t": 1, "m": 1})
        # Las banderas del state no cuentan como aceptación: Términos, edad y permisos se dan en POST /users/me/terms
        assert user.email_verified is True and user.hashed_password is None and user.terms_accepted_at is None
        assert user.marketing_opt_in is False
        with pytest.raises(oauth.OAuthError):
            auth_router.link_google_account(db, {"sub": "x", "email": email, "email_verified": False})
        with pytest.raises(oauth.OAuthError):
            auth_router.link_google_account(db, {"sub": "x", "email": ""})
        monkeypatch.setattr(settings, "environment", "production")
        with pytest.raises(oauth.OAuthError):
            auth_router.link_google_account(db, {"sub": "x", "email": "a@example.com", "email_verified": True})
    finally:
        db.close()


def test_google_callback_uses_fragment(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cliente.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "secreto")
    monkeypatch.setattr(settings, "google_redirect_uri", None)
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8082")
    email = f"g-{uuid.uuid4().hex[:8]}@gmail.com"
    monkeypatch.setattr(oauth, "get_google_userinfo",
                        lambda code, uri: {"sub": uuid.uuid4().hex, "email": email, "email_verified": True})
    r = client.get("/auth/google/login", follow_redirects=False)
    state = r.headers["location"].split("state=")[1].split("&")[0]
    from urllib.parse import unquote

    r = client.get("/auth/google/callback", params={"code": "c", "state": unquote(state)},
                   cookies={"pf_oauth_state": r.cookies.get("pf_oauth_state")}, follow_redirects=False)
    loc = r.headers["location"]
    assert r.status_code == 302 and loc.startswith("http://localhost:8082/app/#token=") and "?token=" not in loc
    me = client.get("/users/me", headers=_h(loc.split("#token=")[1])).json()
    assert me["email"] == email and me["email_verified"] is True
    client.cookies.clear()


# --------------------------------------------------------------------------- casas de paso
def test_foster_registration_never_overwrites_privileged_roles(client, make_user):
    for role in ("admin", "refuge"):
        u = make_user(f"Rol {role}")
        _set(u["email"], role=role)
        r = client.post("/foster-homes/register", headers=u["h"], json={"capacity": 2, "city": "CDMX"})
        assert r.status_code == 201, r.text
        assert _get(u["email"]).role == role
    u = make_user("Normal")
    assert client.post("/foster-homes/register", headers=u["h"], json={"capacity": 1}).status_code == 201
    assert _get(u["email"]).role == "foster"


def test_foster_list_pagination(client):
    assert client.get("/foster-homes", params={"limit": 101}).status_code == 422
    assert client.get("/foster-homes", params={"skip": -1}).status_code == 422
    r = client.get("/foster-homes", params={"limit": 100, "skip": 0})
    assert r.status_code == 200 and len(r.json()) <= 100


# --------------------------------------------------------------------------- roles y bitácora
def _staff(make_user, role):
    u = make_user(f"Staff {role}", verify=False)
    u["id"] = _set(u["email"], role=role)
    return u


def test_admin_cannot_grant_or_touch_admin_roles(client, make_user):
    admin = _staff(make_user, "admin")
    target = make_user("Objetivo", verify=False)
    tid = _get(target["email"]).id
    r = client.patch(f"/admin/users/{tid}/role", headers=admin["h"], json={"role": "admin"})
    assert r.status_code == 403 and "superadmin" in r.json()["detail"]
    r = client.patch(f"/admin/users/{tid}/role", headers=admin["h"], json={"role": "superadmin"})
    assert r.status_code == 403
    other_admin = _staff(make_user, "admin")
    assert client.patch(f"/admin/users/{other_admin['id']}/role", headers=admin["h"],
                        json={"role": "user"}).status_code == 403
    assert client.patch(f"/admin/users/{other_admin['id']}/active", headers=admin["h"],
                        json={"is_active": False}).status_code == 403
    # Roles normales sí
    r = client.patch(f"/admin/users/{tid}/role", headers=admin["h"], json={"role": "refuge"})
    assert r.status_code == 200 and r.json()["role"] == "refuge"
    # Nunca el propio
    assert client.patch(f"/admin/users/{admin['id']}/role", headers=admin["h"], json={"role": "user"}).status_code == 400
    r = client.patch(f"/admin/users/{admin['id']}/active", headers=admin["h"], json={"is_active": False})
    assert r.status_code == 400
    # Un admin no puede leer la bitácora
    assert client.get("/admin/audit-log", headers=admin["h"]).status_code == 403


def test_superadmin_manages_admins_and_audit_log(client, make_user):
    sa = _staff(make_user, "superadmin")
    target = make_user("Ascendido", verify=False)
    tid = _get(target["email"]).id
    r = client.patch(f"/admin/users/{tid}/role", headers={**sa["h"], "X-Real-IP": "10.9.8.7"}, json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    # Sus sesiones anteriores se cierran (el nuevo token de admin dura 8 h)
    assert client.get("/users/me", headers=target["h"]).status_code == 401
    assert client.patch(f"/admin/users/{tid}/role", headers=sa["h"], json={"role": "user"}).status_code == 200
    # Superadmin no puede cambiarse ni desactivarse
    assert client.patch(f"/admin/users/{sa['id']}/role", headers=sa["h"], json={"role": "admin"}).status_code == 400
    assert client.patch(f"/admin/users/{sa['id']}/active", headers=sa["h"],
                        json={"is_active": False}).status_code == 400
    # Suspender y reactivar a un usuario
    victim = make_user("Suspendido", verify=False)
    vid = _get(victim["email"]).id
    r = client.patch(f"/admin/users/{vid}/active", headers=sa["h"], json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/users/me", headers=victim["h"]).status_code == 401
    assert client.patch(f"/admin/users/{vid}/active", headers=sa["h"], json={"is_active": True}).json()["is_active"]

    log = client.get("/admin/audit-log", headers=sa["h"], params={"target_type": "user", "limit": 50}).json()
    mine = [e for e in log if e["actor_id"] == sa["id"]]
    actions = [e["action"] for e in mine]
    assert actions.count("user.role_change") == 2 and "user.deactivate" in actions and "user.activate" in actions
    promo = next(e for e in mine if e["action"] == "user.role_change" and e["details"]["to"] == "admin")
    assert promo["target_id"] == tid and promo["details"]["from"] == "user"
    assert promo["ip"] == "10.9.8.7" and promo["actor_email"] == sa["email"]
    assert client.get("/admin/audit-log", headers=sa["h"], params={"limit": 201}).status_code == 422


def test_last_superadmin_cannot_be_demoted():
    import pytest
    from fastapi import HTTPException

    class FakeQuery:
        def filter(self, *a):
            return self

        def count(self):
            return 0

    class FakeDB:
        def query(self, *a):
            return FakeQuery()

    actor = User(id=-1, role="superadmin", is_active=True)
    last = User(id=-2, role="superadmin", is_active=True)
    with pytest.raises(HTTPException) as exc:
        admin_router.check_user_management(FakeDB(), actor, last, new_role="admin")
    assert exc.value.status_code == 400 and "último superadmin" in exc.value.detail
    with pytest.raises(HTTPException):
        admin_router.check_user_management(FakeDB(), actor, last, deactivate=True)
    # Con otro superadmin activo sí se puede
    FakeQuery.count = lambda self: 1
    admin_router.check_user_management(FakeDB(), actor, last, new_role="admin")


def test_admin_mutations_are_audited(client, make_user):
    sa = _staff(make_user, "superadmin")
    u = make_user("Refugio Auditado")
    ref = client.post("/refuges/register", headers=u["h"], json={"name": "Refugio Auditoría", "city": "CDMX"})
    assert ref.status_code in (200, 201), ref.text
    rid = ref.json()["id"]
    assert client.post(f"/admin/refuges/{rid}/reject", headers=sa["h"], json={"reason": "Faltan papeles"}).status_code == 200
    dog = client.post("/dogs", headers=u["h"], json={"name": "Auditado"}).json()
    assert client.patch(f"/admin/dogs/{dog['id']}/status", headers=sa["h"], json={"status": "unavailable"}).status_code == 200
    db = SessionLocal()
    try:
        rows = db.query(AdminAuditLog).filter(AdminAuditLog.actor_id == sa["id"]).all()
        got = {(r.action, r.target_type, r.target_id) for r in rows}
        assert ("refuge.reject", "refuge", rid) in got and ("dog.status_change", "dog", dog["id"]) in got
        reject = next(r for r in rows if r.action == "refuge.reject")
        assert reject.details == {"reason": "Faltan papeles"}
    finally:
        db.close()
