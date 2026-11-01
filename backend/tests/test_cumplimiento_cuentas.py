"""Correcciones de cumplimiento de cuentas: aceptaciones (Google, donativos, anexos de aliados), edad (L-edad en el
chat por WebSocket, reportes anónimos, verificación reforzada con revisión manual), permisos de WhatsApp de los
números del bot, MFA (cambio de app y sesiones sin el segundo paso), documentos antiguos de refugios en /uploads/,
conservación (R42 y tope del congelamiento por incidente) y avisos de incidentes a toda la base.

Nada llama a servicios externos: SMS en modo dev, pagos simulados y WhatsApp sustituido.
"""
import datetime
import time
import uuid
from pathlib import Path

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AdminAuditLog, AgeCheck, ConsentRecord, Conversation, LegalAcceptance, LostReport, Message, ModerationAction,
    Notification, Refuge, SecurityIncident, SecurityIncidentNotice, User,
)
from app.routers import auth as auth_router
from app.routers import cumplimiento_seguridad as seg_router
from app.services import age_check, consent, crypto_storage, legal_acceptance as la, matching, retention, totp
from app.services import whatsapp_bot
from tests.conftest import make_jpeg, random_ip, random_phone

ADULT = {"is_adult": True, "birth_date": "1990-01-01"}


# --------------------------------------------------------------------------- utilidades
def _db():
    return SessionLocal()


def _uid(u) -> int:
    db = _db()
    try:
        return db.query(User.id).filter(User.email == u["email"]).scalar()
    finally:
        db.close()


def _set(user_id, **values):
    db = _db()
    try:
        u = db.get(User, user_id)
        for k, v in values.items():
            setattr(u, k, v)
        db.commit()
    finally:
        db.close()


def _get_user(user_id) -> User:
    db = _db()
    try:
        u = db.get(User, user_id)
        db.expunge(u)
        return u
    finally:
        db.close()


def _refuge(owner_id, status="approved") -> int:
    db = _db()
    try:
        r = Refuge(user_id=owner_id, name=f"Refugio {uuid.uuid4().hex[:6]}", city="Pruebas", country="México",
                   status=status, documents=[])
        db.add(r)
        db.commit()
        return r.id
    finally:
        db.close()


def _accept_annex(user_id, role):
    db = _db()
    try:
        user = db.get(User, user_id)
        for slug in la.ANNEX_SLUGS[role]:
            la.record_acceptance(db, user, slug, "anexo")
        db.commit()
    finally:
        db.close()


def _code(secret: str, offset: int = 0) -> str:
    return totp.totp_at(totp._b32_bytes(secret), time.time() + offset)


@pytest.fixture
def admin(make_user):
    u = make_user("Admin Cuentas")
    u["id"] = _uid(u)
    _set(u["id"], role="admin")
    yield u
    _set(u["id"], role="user")


@pytest.fixture
def superadmin(make_user):
    u = make_user("Superadmin Cuentas")
    u["id"] = _uid(u)
    _set(u["id"], role="superadmin")
    yield u
    _set(u["id"], role="user")


@pytest.fixture
def otp_relaxed(monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "otp_max_sends_per_phone_hour", 50)
    monkeypatch.setattr(settings, "otp_max_sends_per_ip_hour", 50)


def _google_user(phone_verified=True) -> tuple[int, dict]:
    db = _db()
    try:
        email = f"google-{uuid.uuid4().hex[:10]}@pruebas.mx"
        user = auth_router.link_google_account(db, {"sub": "g-" + uuid.uuid4().hex, "email": email,
                                                    "email_verified": True, "name": "Con Google",
                                                    "picture": "https://ejemplo.mx/foto.jpg"})
        token = auth_router.create_session_token(user)["access_token"]
        uid = user.id
    finally:
        db.close()
    if phone_verified:
        _set(uid, phone="+52" + random_phone(), phone_verified=True)
    return uid, {"Authorization": f"Bearer {token}"}


# =========================================================================== Google: registro y edad
def test_google_signup_records_registro_and_marketing_consent(client):
    uid, h = _google_user()
    user = _get_user(uid)
    assert user.terms_accepted_at is None and user.marketing_opt_in is False  # nada se acepta en el callback
    r = client.post("/users/me/terms", headers=h, json={"accepted_terms": True, "marketing_opt_in": True, **ADULT})
    assert r.status_code == 200, r.text
    db = _db()
    try:
        rows = db.query(LegalAcceptance).filter(LegalAcceptance.user_id == uid).all()
        assert {(a.slug, a.method) for a in rows} >= {("terminos", "registro"), ("privacidad", "registro")}
        cons = db.query(ConsentRecord).filter(ConsentRecord.user_id == uid).all()
        assert [(c.purpose, c.granted) for c in cons] == [("email_marketing", True)]
        assert db.get(User, uid).marketing_opt_in is True
    finally:
        db.close()


def test_google_minor_completion_closes_and_anonymizes_account(client):
    uid, h = _google_user()
    r = client.post("/users/me/terms", headers=h, json={"accepted_terms": True, "is_adult": True,
                                                        "birth_date": "2012-05-05"})
    assert r.status_code == 403 and r.json()["code"] == "underage_account_closed", r.text
    user = _get_user(uid)
    assert user.is_active is False and user.google_sub is None and user.avatar_url is None
    assert user.email.endswith("@patitasfind.invalid") and user.full_name == "Usuario eliminado"
    assert client.get("/users/me", headers=h).status_code == 401
    db = _db()
    try:
        alerts = db.query(Notification).filter(Notification.type == "age_minor_closed").order_by(
            Notification.id.desc()).limit(20).all()
        assert any((n.data or {}).get("user_id") == uid for n in alerts)
        assert db.query(LegalAcceptance).filter(LegalAcceptance.user_id == uid).count() == 0
    finally:
        db.close()


def test_google_minor_with_history_is_deactivated_for_review(client):
    uid, h = _google_user()
    _set(uid, terms_accepted_at=datetime.datetime.utcnow())  # cuenta anterior con historial
    r = client.post("/users/me/terms", headers=h, json={"accepted_terms": True, "is_adult": True,
                                                        "birth_date": "2011-01-01"})
    assert r.status_code == 403 and r.json()["code"] == "underage_account_closed"
    user = _get_user(uid)
    assert user.is_active is False and "reembolsarlos" in r.json()["detail"]


# =========================================================================== donativos
def test_donation_requires_policy_and_links_acceptance(client, make_user):
    donor, seller = make_user("Donante"), make_user("Refugio dueño")
    refuge_id = _refuge(_uid(seller))
    r = client.post("/payments/donations", headers=donor["h"], json={"refuge_id": refuge_id, "amount": 50})
    assert r.status_code == 400 and r.json()["code"] == "policy_required"
    r = client.post("/payments/donations", headers=donor["h"],
                    json={"refuge_id": refuge_id, "amount": 50, "accepted_policy": True})
    assert r.status_code == 201, r.text
    donation_id = r.json()["donation_id"]
    db = _db()
    try:
        row = db.query(LegalAcceptance).filter(LegalAcceptance.user_id == _uid(donor),
                                               LegalAcceptance.slug == "donativos").one()
        assert row.method == "donativo" and row.context["donation_id"] == donation_id
    finally:
        db.close()


# =========================================================================== anexos de aliados
def test_annexes_gate_approval_donations_and_clinic_verification(client, make_user, admin, monkeypatch):
    monkeypatch.setattr(settings, "legal_annex_required", True)
    owner, donor = make_user("Refugio sin anexo"), make_user("Donante anexo")
    owner_id = _uid(owner)
    pending = _refuge(owner_id, status="pending")
    r = client.post(f"/admin/refuges/{pending}/approve", headers=admin["h"])
    assert r.status_code == 400 and r.json()["code"] == "ally_annex_pending"
    assert set(r.json()["documents"]) == {"terminos-refugios", "acuerdo-datos-refugios"}
    db = _db()
    try:
        assert db.get(Refuge, pending).status == "pending"
        assert db.query(Notification).filter(Notification.user_id == owner_id,
                                             Notification.type == "legal_change").count() >= 1
    finally:
        db.close()
    # Un refugio aprobado sin la versión vigente no recibe donativos
    approved = _refuge(owner_id)
    body = {"refuge_id": approved, "amount": 50, "accepted_policy": True}
    r = client.post("/payments/donations", headers=donor["h"], json=body)
    assert r.status_code == 409 and "condiciones de aliado" in r.json()["detail"]
    _accept_annex(owner_id, "refugio")
    assert client.post(f"/admin/refuges/{pending}/approve", headers=admin["h"]).status_code == 200
    assert client.post("/payments/donations", headers=donor["h"], json=body).status_code == 201
    # Sin LEGAL_ANNEX_REQUIRED (desarrollo) no se bloquea nada
    monkeypatch.setattr(settings, "legal_annex_required", False)
    other = _refuge(_uid(make_user("Otro refugio")))
    assert client.post("/payments/donations", headers=donor["h"],
                       json={**body, "refuge_id": other}).status_code == 201


def test_home_card_text_matches_backend_gates():
    js = (Path(__file__).resolve().parents[2] / "app" / "cumplimiento.js")
    if not js.is_file():
        pytest.skip("frontend no montado en el contenedor")
    text = js.read_text(encoding="utf-8")
    assert "conservar tu verificación" not in text
    assert "no podemos verificar ni renovar tu verificación" in text


# =========================================================================== L-edad
def _conversation(a_id, b_id) -> int:
    db = _db()
    try:
        conv = Conversation(user_a_id=a_id, user_b_id=b_id)
        db.add(conv)
        db.commit()
        return conv.id
    finally:
        db.close()


def _messages(conv_id) -> list[str]:
    db = _db()
    try:
        return [m.content for m in db.query(Message).filter(Message.conversation_id == conv_id).all()]
    finally:
        db.close()


def test_websocket_respects_age_limits(client, make_user):
    a, b = make_user("Chat A"), make_user("Chat B")
    a_id, b_id = _uid(a), _uid(b)
    conv = _conversation(a_id, b_id)
    _set(b_id, age_check_status="required")
    with client.websocket_connect(f"/ws/chat/{conv}?token={b['token']}") as ws:
        ws.send_json({"type": "message", "content": "hola por websocket"})
        evt = ws.receive_json()
        while evt.get("type") != "error":
            evt = ws.receive_json()
        assert evt["code"] == "age_check_required"
    assert _messages(conv) == []
    # La limitación que se abre con la conexión ya abierta también aplica (se vuelve a leer la cuenta)
    _set(b_id, age_check_status=None)
    with client.websocket_connect(f"/ws/chat/{conv}?token={b['token']}") as ws:
        _set(b_id, age_check_status="required")
        ws.send_json({"type": "message", "content": "segundo intento"})
        evt = ws.receive_json()
        while evt.get("type") not in ("error", "message"):
            evt = ws.receive_json()
        assert evt["type"] == "error" and evt["code"] == "age_check_required"
    assert _messages(conv) == []
    # Cuenta de Google sin declarar su edad
    _set(b_id, age_check_status=None, google_sub="g-" + uuid.uuid4().hex, birth_date=None)
    with client.websocket_connect(f"/ws/chat/{conv}?token={b['token']}") as ws:
        ws.send_json({"type": "message", "content": "sin edad"})
        evt = ws.receive_json()
        while evt.get("type") != "error":
            evt = ws.receive_json()
        assert evt["code"] == "age_declaration_required"
    assert _messages(conv) == []


def _public_minor_report(client, target_id, headers=None):
    return client.post("/cumplimiento/reportes-publicos", headers={"X-Real-IP": random_ip(), **(headers or {})},
                       json={"target_type": "user", "target_id": target_id, "reason": "involucra_menor",
                             "details": "Creo que es una niña de 13 años"})


def _limited(client, u) -> bool:
    return client.get("/users/me", headers=u["h"]).json()["age_check_required"]


def test_anonymous_minor_report_does_not_lock_account(client, make_user):
    victim = make_user("Víctima reporte")
    vid = _uid(victim)
    r = _public_minor_report(client, vid)
    assert r.status_code == 201, r.text
    assert _limited(client, victim) is False
    assert client.post("/foster-homes/register", headers=victim["h"],
                       json={"description": "Casa", "city": "Pruebas"}).status_code == 201
    # Tres personas distintas (IP distintas) en la ventana sí la limitan
    assert _public_minor_report(client, vid).status_code == 201
    assert _limited(client, victim) is False
    assert _public_minor_report(client, vid).status_code == 201
    assert _limited(client, victim) is True


def test_verified_reporter_locks_but_allies_go_to_review(client, make_user):
    reporter, victim, ally = make_user("Reporta"), make_user("Señalada"), make_user("Refugio aliado")
    assert _public_minor_report(client, _uid(victim), headers=reporter["h"]).status_code == 201
    assert _limited(client, victim) is True
    _refuge(_uid(ally))  # refugio aprobado
    for _ in range(3):
        assert _public_minor_report(client, _uid(ally), headers=reporter["h"]).status_code == 201
    assert _limited(client, ally) is False
    limit, why = age_check.should_auto_limit(_db(), type("R", (), {"reporter_id": None, "reporter_ip": None})(),
                                             _uid(ally))
    assert (limit, why) == (False, "aliado")


def test_reinforced_check_verifies_code_first_and_goes_to_manual_review(client, make_user, admin, otp_relaxed):
    reporter, u = make_user("Reporta edad"), make_user("Edad revisión")
    uid = _uid(u)
    assert _public_minor_report(client, uid, headers=reporter["h"]).status_code == 201
    hip = {**u["h"], "X-Real-IP": u["ip"]}
    # Sin un código válido no se compara la fecha (no es un oráculo de la fecha registrada)
    r = client.post("/cumplimiento/edad/verificar", headers=u["h"],
                    json={"birth_date": "1985-01-01", "code": "000000", "declaration": True})
    assert r.status_code == 400 and "Pide uno nuevo" in r.json()["detail"]
    for attempt in range(1, age_check.MAX_BIRTH_DATE_MISMATCHES + 1):
        code = client.post("/cumplimiento/edad/codigo", headers=hip).json()["dev_code"]
        r = client.post("/cumplimiento/edad/verificar", headers=u["h"],
                        json={"birth_date": "1985-01-01", "code": code, "declaration": True})
        expected = 409 if attempt == age_check.MAX_BIRTH_DATE_MISMATCHES else 400
        assert r.status_code == expected, (attempt, r.text)
    db = _db()
    try:
        check = db.query(AgeCheck).filter(AgeCheck.user_id == uid).order_by(AgeCheck.id.desc()).first()
        assert check.status == "review" and check.attempts == age_check.MAX_BIRTH_DATE_MISMATCHES
    finally:
        db.close()
    status = client.get("/cumplimiento/edad", headers=u["h"]).json()
    assert status["required"] is True and status["in_review"] is True
    # Ni con la fecha correcta se libera sola: la revisa el equipo
    assert client.post("/cumplimiento/edad/codigo", headers=hip).status_code == 409
    r = client.post("/cumplimiento/edad/verificar", headers=u["h"],
                    json={"birth_date": "1990-01-01", "code": "123456", "declaration": True})
    assert r.status_code == 409
    assert client.post("/foster-homes/register", headers=u["h"],
                       json={"description": "Casa", "city": "Pruebas"}).status_code == 403
    listed = client.get("/admin/cumplimiento/edad", headers=admin["h"], params={"status": "review"}).json()
    assert any(c["user_id"] == uid for c in listed)
    assert client.post(f"/admin/cumplimiento/edad/{uid}/liberar", headers=admin["h"],
                       json={"note": "Llamada de verificación"}).json()["closed"] == 1
    assert _limited(client, u) is False


def test_whatsapp_bot_refuses_reports_from_limited_accounts(client, make_user):
    u = make_user("Bot limitado")
    uid = _uid(u)
    _set(uid, age_check_status="required")
    phone = _get_user(uid).phone.lstrip("+")
    db = _db()
    try:
        interaction = whatsapp_bot._get_interaction(db, phone)
        out = whatsapp_bot._create_report(db, interaction, "Max")
        db.commit()
    finally:
        db.close()
    assert out["response"] == whatsapp_bot.AGE_LIMITED_TEXT
    db = _db()
    try:
        assert db.query(LostReport).filter(LostReport.contact_phone == phone).count() == 0
    finally:
        db.close()


# =========================================================================== WhatsApp: permiso de los números del bot
def test_bot_numbers_get_match_alerts_only_after_saying_yes(client, monkeypatch):
    monkeypatch.setattr(whatsapp_bot, "dispatch", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp_bot, "_store_media", lambda event: "/uploads/prueba-bot.jpg")
    monkeypatch.setattr(whatsapp_bot.facebook_groups, "trigger_zone_fetch", lambda *a, **k: None)
    monkeypatch.setattr(matching, "run_report_matching", lambda db, rid: [])
    phone = "52155" + random_phone()[2:]
    sim = lambda **kw: client.post("/whatsapp/webhook", json={"phone": phone, **kw}).json()
    sim(message="hola")
    sim(message="2")
    sim(message=None, media_url="https://ejemplo.mx/perro.jpg")
    sim(message="listo")
    sim(message="Torreón, Coahuila")
    sim(message="Collar azul")
    done = sim(message="PUBLICAR")  # aceptación antes de publicar
    assert done["stage"] == "done" and whatsapp_bot.ALERTS_QUESTION in done["response"], done
    assert consent.latest_phone_consent(_db(), phone) is None

    sent = []
    from app.services import notify

    monkeypatch.setattr(notify, "send_whatsapp", lambda *a, **k: sent.append(a) or "template")
    target = LostReport(id=987654, contact_phone=phone, report_type="found", dog_name="Perrito encontrado")
    new = LostReport(id=987655, report_type="lost", dog_name="Max")
    matching._notify_whatsapp(target, new, 90, f"sin-permiso-{uuid.uuid4().hex}")
    assert sent == []  # sin constancia de permiso no hay avisos proactivos

    yes = sim(message="Sí")
    assert yes["response"] == whatsapp_bot.ALERTS_YES_TEXT
    db = _db()
    try:
        row = db.query(ConsentRecord).filter(ConsentRecord.phone == phone).order_by(ConsentRecord.id.desc()).first()
        assert row.purpose == "whatsapp_alerts" and row.granted is True and row.channel == "whatsapp"
    finally:
        db.close()
    matching._notify_whatsapp(target, new, 90, f"con-permiso-{uuid.uuid4().hex}")
    assert len(sent) == 1
    # Otro reporte ya no pregunta (ya dio permiso)
    sim(message="menu")
    sim(message="2")
    sim(message=None, media_url="https://ejemplo.mx/perro2.jpg")
    sim(message="listo")
    sim(message="Saltillo")
    sim(message="no sé")
    again = sim(button_id="publish_yes", message="Publicar")
    assert again["stage"] == "done" and whatsapp_bot.ALERTS_QUESTION not in again["response"], again


def test_bot_no_answer_records_refusal(client, monkeypatch):
    monkeypatch.setattr(whatsapp_bot, "dispatch", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp_bot, "_store_media", lambda event: "/uploads/prueba-bot.jpg")
    monkeypatch.setattr(whatsapp_bot.facebook_groups, "trigger_zone_fetch", lambda *a, **k: None)
    monkeypatch.setattr(matching, "run_report_matching", lambda db, rid: [])
    phone = "52155" + random_phone()[2:]
    sim = lambda **kw: client.post("/whatsapp/webhook", json={"phone": phone, **kw}).json()
    for step in ({"message": "hola"}, {"message": "1"}, {"message": None, "media_url": "https://ejemplo.mx/p.jpg"},
                 {"message": "listo"}, {"message": "Monterrey"}, {"message": "Luna"}, {"message": "PUBLICAR"}):
        sim(**step)
    no = sim(button_id="alerts_no", message="No, gracias")
    assert no["response"] == whatsapp_bot.ALERTS_NO_TEXT
    assert consent.latest_phone_consent(_db(), phone) is False
    assert matching.has_whatsapp_consent(phone) is False


# =========================================================================== MFA
def _enroll(client, u) -> str:
    setup = client.post("/auth/mfa/setup", json={}, headers=u["h"])
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    enable = client.post("/auth/mfa/enable", json={"code": _code(secret)}, headers=u["h"])
    assert enable.status_code == 200, enable.text
    u["h"] = {"Authorization": f"Bearer {enable.json()['access_token']}"}
    return secret


def test_mfa_rotation_needs_password_and_current_code(client, admin):
    secret = _enroll(client, admin)
    r = client.post("/auth/mfa/setup", json={}, headers=admin["h"])
    assert r.status_code == 400 and "contraseña" in r.json()["detail"]
    r = client.post("/auth/mfa/setup", json={"code": _code(secret, 30), "password": "Incorrecta1"}, headers=admin["h"])
    assert r.status_code == 400
    r = client.post("/auth/mfa/setup", json={"code": "000000", "password": admin["password"]}, headers=admin["h"])
    assert r.status_code == 400
    r = client.post("/auth/mfa/setup", json={"code": _code(secret, 30), "password": admin["password"]},
                    headers=admin["h"])
    assert r.status_code == 200, r.text
    new_secret = r.json()["secret"]
    r = client.post("/auth/mfa/enable", json={"code": _code(new_secret)}, headers=admin["h"])
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10
    db = _db()
    try:
        actions = {a for (a,) in db.query(AdminAuditLog.action).filter(AdminAuditLog.actor_id == admin["id"]).all()}
        assert {"auth.mfa_rotate_failed", "auth.mfa_replaced"} <= actions
    finally:
        db.close()


def test_admin_session_without_mfa_claim_is_rejected_everywhere(client, admin):
    _enroll(client, admin)
    db = _db()
    try:
        plain = auth_router.create_session_token(db.get(User, admin["id"]))["access_token"]
    finally:
        db.close()
    h = {"Authorization": f"Bearer {plain}"}
    # No solo el panel: también las rutas normales (comprobaciones de personal fuera de require_admin)
    assert client.get("/users/me", headers=h).status_code == 401
    assert client.get("/users/me", headers=admin["h"]).status_code == 200


# =========================================================================== documentos antiguos de refugios
def test_legacy_refuge_documents_move_to_private_encrypted(client, make_user):
    owner = make_user("Refugio antiguo")
    base = Path(settings.upload_dir)
    name, shared = f"legacy{uuid.uuid4().hex}.jpg", f"legacy{uuid.uuid4().hex}.jpg"
    data = make_jpeg(7)
    (base / name).write_bytes(data)
    (base / f"{name.rsplit('.', 1)[0]}_thumb.jpg").write_bytes(data)
    (base / shared).write_bytes(data)
    db = _db()
    try:
        refuge = Refuge(user_id=_uid(owner), name="Refugio legado", status="approved",
                        documents=[f"/uploads/{name}", f"/uploads/{shared}", "/uploads/no-existe-123.jpg"])
        db.add(refuge)
        # La segunda imagen también es la foto pública de un reporte: esa copia pública se conserva
        db.add(LostReport(reporter_id=None, dog_name="Foto compartida", report_type="found", status="active",
                          source="app", photos=[f"/uploads/{shared}"]))
        db.commit()
        refuge_id = refuge.id
        stats = crypto_storage.migrate_legacy_documents(db)
    finally:
        db.close()
    assert stats["migrated"] >= 2 and stats["errors"] == 0
    db = _db()
    try:
        docs = db.get(Refuge, refuge_id).documents
    finally:
        db.close()
    new_ids = [d for d in docs if not d.startswith("/uploads/")]
    assert len(new_ids) == 2 and docs[-1] == "/uploads/no-existe-123.jpg"  # la referencia rota se deja igual
    for doc_id in new_ids:
        blob = (base / "private" / doc_id).read_bytes()
        assert crypto_storage.is_encrypted(blob) and crypto_storage.decrypt_bytes(blob) == data
    assert not (base / name).exists() and not (base / f"{name.rsplit('.', 1)[0]}_thumb.jpg").exists()
    assert (base / shared).exists()
    # Idempotente
    db = _db()
    try:
        again = crypto_storage.migrate_legacy_documents(db)
    finally:
        db.close()
    assert again["migrated"] == 0


def test_deploy_fails_if_encryption_fails():
    script = Path(__file__).resolve().parents[1] / "scripts" / "deploy.sh"
    text = script.read_text(encoding="utf-8")
    assert 'encrypt-private-files \\\n    || die "falló encrypt-private-files' in text


# =========================================================================== conservación: R42 y congelamiento
def _cancel_action(user_id, days_ago) -> None:
    db = _db()
    try:
        db.add(ModerationAction(folio=f"MOD-T{uuid.uuid4().hex[:10].upper()}", user_id=user_id, target_type="user",
                                target_id=user_id, action="cancel_account", rule="fraude", rule_text="Fraude",
                                detection="equipo", status="active",
                                created_at=datetime.datetime.utcnow() - datetime.timedelta(days=days_ago)))
        db.commit()
    finally:
        db.close()


def test_r42_sanctioned_fingerprints_expire_after_24_months(client, make_user):
    old, recent = make_user("Cancelada vieja"), make_user("Cancelada reciente")
    old_id, recent_id = _uid(old), _uid(recent)
    for uid, days in ((old_id, retention.SANCIONADAS_DIAS + 10), (recent_id, 30)):
        _set(uid, is_active=False, google_sub="g-" + uuid.uuid4().hex)
        _cancel_action(uid, days)
    db = _db()
    try:
        out = retention.run_purge(db, only=("cuentas_sancionadas",), force=True)
    finally:
        db.close()
    assert out["results"]["cuentas_sancionadas"]["cuentas"] >= 1
    gone, kept = _get_user(old_id), _get_user(recent_id)
    assert gone.phone is None and gone.google_sub is None and gone.email.endswith("@patitasfind.invalid")
    assert kept.phone and kept.google_sub and kept.email == recent["email"]
    row = retention.category("cuentas_sancionadas")
    assert row["aplicacion"] == "automatica" and row["dias"] == retention.SANCIONADAS_DIAS
    assert "Hoy no se guardan" not in row["plazo"]


def test_incident_freeze_is_capped_and_renewed_by_superadmin(client, admin, superadmin):
    r = client.post("/admin/cumplimiento/incidentes", headers=admin["h"],
                    json={"title": "Prueba de congelamiento", "category": "disponibilidad", "severity": "S3"})
    assert r.status_code == 201, r.text
    inc = r.json()
    try:
        until = datetime.datetime.fromisoformat(inc["freeze_until"].rstrip("Z"))
        assert inc["purges_frozen"] is True
        assert abs((until - datetime.datetime.utcnow()) - datetime.timedelta(days=retention.FREEZE_MAX_DIAS)) \
            < datetime.timedelta(minutes=5)
        r = client.patch(f"/admin/cumplimiento/incidentes/{inc['id']}", headers=admin["h"], json={"renew_freeze": True})
        assert r.status_code == 403
        # Vencido: deja de congelar aunque el incidente siga abierto
        db = _db()
        try:
            row = db.get(SecurityIncident, inc["id"])
            row.freeze_purges_until = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
            db.commit()
            assert row.id not in {i.id for i in retention.freezing_incidents(db)}
        finally:
            db.close()
        got = client.get(f"/admin/cumplimiento/incidentes/{inc['id']}", headers=admin["h"]).json()
        assert got["purges_frozen"] is False and got["freeze_expired"] is True
        # Volver a activarlo vencido también es una renovación: solo superadmin
        r = client.patch(f"/admin/cumplimiento/incidentes/{inc['id']}", headers=superadmin["h"],
                         json={"renew_freeze": True, "freeze_purges": True})
        assert r.status_code == 200 and r.json()["purges_frozen"] is True, r.text
        assert any("congeladas hasta" in (t.get("text") or "") for t in r.json()["timeline"])
    finally:
        db = _db()
        try:
            row = db.get(SecurityIncident, inc["id"])
            row.freeze_purges = False
            row.status = "cerrado"
            db.commit()
        finally:
            db.close()


def test_freeze_keeps_deleting_verification_documents_unless_listed(monkeypatch):
    monkeypatch.setattr(settings, "retention_purge_enabled", True)
    fake = SecurityIncident(id=-1, folio="INC-PRUEBA", title="x", systems_affected=["api"], data_categories=["contacto"])
    monkeypatch.setattr(retention, "freezing_incidents", lambda db, now=None: [fake])
    db = _db()
    try:
        out = retention.run_purge(db, dry_run=True)
        assert out["status"] == "frozen" and set(out["results"]) == set(retention.FREEZE_EXEMPT)
        fake.systems_affected = ["uploads/private"]
        out = retention.run_purge(db, dry_run=True)
        assert out == {"status": "frozen", "results": {}}
        fake.systems_affected, fake.data_categories = ["api"], ["INE de refugios"]
        assert retention.freeze_covers_documents([fake]) is True
    finally:
        db.close()


# =========================================================================== avisos de incidente a toda la base
def test_all_users_notice_skips_already_notified_before_the_cap(client, superadmin, monkeypatch):
    monkeypatch.setattr(seg_router, "MAX_NOTICE_RECIPIENTS", 3)
    r = client.post("/admin/cumplimiento/incidentes", headers=superadmin["h"],
                    json={"title": "Aviso a toda la base", "category": "vulneracion", "freeze_purges": False})
    inc = r.json()
    notice = {"resumen": "un acceso indebido", "fecha": "18 de octubre de 2026", "que_paso": "alguien entró.",
              "datos": "tu correo", "acciones": "cerramos el acceso.", "recomendaciones": "cambia tu contraseña."}
    url = f"/admin/cumplimiento/incidentes/{inc['id']}/avisos"
    first = client.post(url, headers=superadmin["h"], json={"notice": notice, "all_users": True}).json()
    second = client.post(url, headers=superadmin["h"], json={"notice": notice, "all_users": True}).json()
    assert first["app"] == 3 and second["app"] == 3 and first["version"] == second["version"]
    assert second["pendientes"] == first["pendientes"] - 3 and second["omitidos"] == first["omitidos"] + 3
    db = _db()
    try:
        ids = [u for (u,) in db.query(SecurityIncidentNotice.user_id).filter(
            SecurityIncidentNotice.incident_id == inc["id"], SecurityIncidentNotice.channel == "app").all()]
        assert len(ids) == 6 and len(set(ids)) == 6  # nadie lo recibe dos veces; el segundo envío avanza
    finally:
        db.close()
    # Solo un superadmin avisa a toda la base
    assert client.post(url, headers={"Authorization": "Bearer x"}, json={"notice": notice, "all_users": True}
                       ).status_code == 401
