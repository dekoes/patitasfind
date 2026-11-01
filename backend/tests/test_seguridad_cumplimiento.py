"""Seguridad (L-seguridad): verificación en dos pasos del personal administrador (TOTP RFC 6238), cifrado en reposo
de los documentos privados y de los datos fiscales, purga diaria según la tabla de conservación (K-CONSERV),
registro de incidentes con avisos a personas afectadas y tablero de estado (K-ESTADO).

Ninguna prueba llama a servicios externos: el ping a Celery del tablero se sustituye.
"""
import base64
import datetime
import os
import time
import uuid

import pytest
from sqlalchemy import text

from app import cache
from app.auth import decode_access_token
from app.config import Settings, settings
from app.database import SessionLocal
from app.models import (
    AdminAuditLog, BotInteraction, ContentReport, Conversation, LostReport, Message, MfaRecoveryCode, Notification,
    PhoneVerificationLog, Refuge, RefugeFiscalProfile, SecurityIncident, SecurityIncidentNotice, User, Veterinary,
)
from app.routers import auth as auth_router
from app.routers import cumplimiento_seguridad as seg_router
from app.routers import documents
from app.services import crypto_storage, retention, totp

KEY_A = base64.b64encode(b"A" * 32).decode()
KEY_B = base64.b64encode(b"B" * 32).decode()
NOW = datetime.datetime.utcnow


# --------------------------------------------------------------------------- utilidades
def _db():
    return SessionLocal()


def _set_user(email, **fields) -> int:
    db = _db()
    try:
        u = db.query(User).filter(User.email == email).first()
        for k, v in fields.items():
            setattr(u, k, v)
        db.commit()
        return u.id
    finally:
        db.close()


def _admin(make_user, role="admin"):
    u = make_user("Admin Seguridad", verify=False)
    u["id"] = _set_user(u["email"], role=role)
    return u


def _login(client, email, password="Segura123"):
    return client.post("/auth/login", data={"username": email, "password": password})


def _code(secret: str, offset: int = 0) -> str:
    return totp.totp_at(totp._b32_bytes(secret), time.time() + offset)


def _enroll(client, u) -> dict:
    """Activa la MFA con la sesión del admin (development: opcional). Devuelve secreto, códigos y sesión nueva."""
    setup = client.post("/auth/mfa/setup", json={}, headers=u["h"])
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/GuauWoow:")
    enable = client.post("/auth/mfa/enable", json={"code": _code(secret)}, headers=u["h"])
    assert enable.status_code == 200, enable.text
    body = enable.json()
    u["secret"], u["codes"] = secret, body["recovery_codes"]
    u["h"] = {"Authorization": f"Bearer {body['access_token']}"}
    return body


def _purge(**kwargs) -> dict:
    db = _db()
    try:
        return retention.run_purge(db, **kwargs)
    finally:
        db.close()


def _audit_actions(user_id: int) -> set[str]:
    db = _db()
    try:
        return {a for (a,) in db.query(AdminAuditLog.action).filter(AdminAuditLog.target_type == "user",
                                                                   AdminAuditLog.target_id == user_id).all()}
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _no_celery_ping(monkeypatch):
    """El tablero nunca hace ping real a los workers en las pruebas."""
    monkeypatch.setattr(seg_router, "_check_queue", lambda: ("operativo", None))
    cache.delete(seg_router.ESTADO_CACHE_KEY, seg_router.CONSERVACION_CACHE_KEY)
    yield
    cache.delete(seg_router.ESTADO_CACHE_KEY, seg_router.CONSERVACION_CACHE_KEY)


# =========================================================================== TOTP (RFC 4226 / RFC 6238)
def test_hotp_rfc4226_vectors():
    key = b"12345678901234567890"
    expected = ["755224", "287082", "359152", "969429", "338314", "254676", "287922", "162583", "399871", "520489"]
    assert [totp.hotp(key, i) for i in range(10)] == expected


@pytest.mark.parametrize("algorithm,key,codes", [
    ("sha1", b"12345678901234567890",
     ["94287082", "07081804", "14050471", "89005924", "69279037", "65353130"]),
    ("sha256", b"12345678901234567890123456789012",
     ["46119246", "68084774", "67062674", "91819424", "90698825", "77737706"]),
    ("sha512", b"1234567890123456789012345678901234567890123456789012345678901234",
     ["90693936", "25091201", "99943326", "93441116", "38618901", "47863826"]),
])
def test_totp_rfc6238_vectors(algorithm, key, codes):
    times = [59, 1111111109, 1111111111, 1234567890, 2000000000, 20000000000]
    assert [totp.totp_at(key, t, digits=8, algorithm=algorithm) for t in times] == codes


def test_matching_step_window_and_replay():
    secret = totp.b32_secret(b"12345678901234567890")
    now = 1_700_000_000
    step = now // 30
    key = totp._b32_bytes(secret)
    assert totp.matching_step(secret, totp.totp_at(key, now), now=now) == step
    assert totp.matching_step(secret, totp.totp_at(key, now - 30), now=now) == step - 1  # reloj atrasado
    assert totp.matching_step(secret, totp.totp_at(key, now + 30), now=now) == step + 1
    assert totp.matching_step(secret, totp.totp_at(key, now + 90), now=now) is None  # fuera de la ventana
    assert totp.matching_step(secret, totp.totp_at(key, now), now=now, last_step=step) is None  # ya usado
    assert totp.matching_step(secret, "12345", now=now) is None and totp.matching_step(secret, "abcdef", now=now) is None
    uri = totp.provisioning_uri(secret, "ana@pruebas.mx", "GuauWoow")
    assert uri.startswith("otpauth://totp/GuauWoow:ana@pruebas.mx?secret=") and "issuer=GuauWoow" in uri


def test_recovery_codes_hash():
    codes = totp.new_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
    stored = totp.hash_recovery_code(codes[0])
    assert stored.startswith("pbkdf2$") and codes[0] not in stored
    assert totp.recovery_code_matches(codes[0].upper().replace("-", " "), stored)
    assert not totp.recovery_code_matches(codes[1], stored)


# =========================================================================== MFA del panel
def test_mfa_login_flow_replay_and_recovery(client, make_user):
    u = _admin(make_user)
    old_headers = dict(u["h"])
    _enroll(client, u)
    # Las sesiones anteriores al alta ya no sirven (se cerraron)
    assert client.get("/admin/cumplimiento/incidentes", headers=old_headers).status_code == 401
    assert client.get("/admin/cumplimiento/incidentes", headers=u["h"]).status_code == 200

    # Primer paso: no hay sesión, solo el comprobante del segundo paso
    first = _login(client, u["email"])
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["mfa_required"] is True and "access_token" not in body and body.get("mfa_enrollment_required") is False
    mfa_token = body["mfa_token"]
    # El comprobante no es una sesión
    assert client.get("/users/me", headers={"Authorization": f"Bearer {mfa_token}"}).status_code == 401

    bad = client.post("/auth/mfa/verify", json={"mfa_token": mfa_token, "code": "000000"})
    assert bad.status_code == 401
    code = _code(u["secret"], 30)  # siguiente intervalo: el actual ya lo consumió el alta
    ok = client.post("/auth/mfa/verify", json={"mfa_token": mfa_token, "code": code})
    assert ok.status_code == 200, ok.text
    session = ok.json()["access_token"]
    assert decode_access_token(session)["mfa"] == 1
    assert client.get("/admin/cumplimiento/mfa", headers={"Authorization": f"Bearer {session}"}).status_code == 200
    # El mismo código no sirve dos veces
    assert client.post("/auth/mfa/verify", json={"mfa_token": mfa_token, "code": code}).status_code == 401

    # Código de recuperación: una sola vez
    recovery = u["codes"][0]
    r1 = client.post("/auth/mfa/verify", json={"mfa_token": mfa_token, "code": recovery})
    assert r1.status_code == 200, r1.text
    assert client.post("/auth/mfa/verify", json={"mfa_token": mfa_token, "code": recovery}).status_code == 401
    status = client.get("/auth/mfa/status", headers={"Authorization": f"Bearer {r1.json()['access_token']}"}).json()
    assert status["enabled"] is True and status["recovery_codes_left"] == 9

    # Una sesión sin "mfa" (p. ej. emitida por otro camino) no entra al panel
    db = _db()
    try:
        user = db.query(User).filter(User.id == u["id"]).first()
        plain = auth_router.create_session_token(user)["access_token"]
    finally:
        db.close()
    assert client.get("/admin/cumplimiento/incidentes", headers={"Authorization": f"Bearer {plain}"}).status_code == 401

    actions = _audit_actions(u["id"])
    assert {"auth.mfa_setup", "auth.mfa_enabled", "auth.mfa_login", "auth.mfa_failed"} <= actions


def test_mfa_token_dies_with_password_change(client, make_user):
    u = _admin(make_user)
    _enroll(client, u)
    mfa_token = _login(client, u["email"]).json()["mfa_token"]
    db = _db()
    try:
        user = db.query(User).filter(User.id == u["id"]).first()
        user.hashed_password = auth_router.get_password_hash("OtraClave123")
        db.commit()
    finally:
        db.close()
    r = client.post("/auth/mfa/verify", json={"mfa_token": mfa_token, "code": _code(u["secret"], 30)})
    assert r.status_code == 401 and "venció" in r.json()["detail"]


def test_mfa_mandatory_enrollment_on_first_login(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "mfa_required_for_admins", True)
    u = _admin(make_user)
    # Su sesión previa (sin MFA) ya no entra al panel
    assert client.get("/admin/cumplimiento/incidentes", headers=u["h"]).status_code == 401
    body = _login(client, u["email"]).json()
    assert body["mfa_required"] is True and body["mfa_enrollment_required"] is True
    token = body["mfa_token"]
    # Sin MFA no hay segundo paso posible: primero el alta con el comprobante
    assert client.post("/auth/mfa/verify", json={"mfa_token": token, "code": "123456"}).status_code == 409
    setup = client.post("/auth/mfa/setup", json={"mfa_token": token})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    enable = client.post("/auth/mfa/enable", json={"mfa_token": token, "code": _code(secret)})
    assert enable.status_code == 200, enable.text
    session = enable.json()["access_token"]
    assert len(enable.json()["recovery_codes"]) == 10
    assert client.get("/admin/cumplimiento/incidentes", headers={"Authorization": f"Bearer {session}"}).status_code == 200
    # Obligatoria: no se puede desactivar
    r = client.post("/auth/mfa/disable", json={"code": _code(secret, 30), "password": "Segura123"},
                    headers={"Authorization": f"Bearer {session}"})
    assert r.status_code == 403
    # Las personas usuarias no se enteran
    plain = make_user("Persona Normal", verify=False)
    assert "access_token" in _login(client, plain["email"]).json()


def test_superadmin_resets_mfa(client, make_user):
    boss = _admin(make_user, role="superadmin")
    u = _admin(make_user)
    _enroll(client, u)
    assert client.post(f"/admin/cumplimiento/mfa/{u['id']}/reset", headers=u["h"]).status_code == 403
    assert client.post(f"/admin/cumplimiento/mfa/{boss['id']}/reset", headers=boss["h"]).status_code == 400
    r = client.post(f"/admin/cumplimiento/mfa/{u['id']}/reset", headers=boss["h"])
    assert r.status_code == 200, r.text
    db = _db()
    try:
        user = db.query(User).filter(User.id == u["id"]).first()
        assert user.mfa_secret_enc is None and user.mfa_enabled_at is None
        assert db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == u["id"]).count() == 0
    finally:
        db.close()
    assert "access_token" in _login(client, u["email"]).json()  # development: vuelve a entrar sin segundo paso
    listing = client.get("/admin/cumplimiento/mfa", headers=boss["h"]).json()
    assert any(a["id"] == u["id"] and a["mfa_enabled"] is False for a in listing["admins"])


def test_mfa_secret_is_encrypted_in_the_database(client, make_user):
    u = _admin(make_user)
    _enroll(client, u)
    db = _db()
    try:
        raw = db.execute(text("SELECT mfa_secret_enc FROM users WHERE id = :i"), {"i": u["id"]}).scalar()
        assert raw.startswith(crypto_storage.COLUMN_PREFIX) and u["secret"] not in raw
        assert db.query(User).filter(User.id == u["id"]).first().mfa_secret_enc == u["secret"]
    finally:
        db.close()


@pytest.fixture
def clean_env(monkeypatch):
    """Quita del entorno del contenedor las variables que afectarían a Settings()."""
    prefixes = ("CORS_", "WHATSAPP_", "SMS", "SMSMASIVOS_", "TWILIO_", "POSTGRES_", "ALLOW_DEMO", "SECRET_KEY",
                "DATABASE_URL", "PUBLIC_BASE_URL", "SMTP_", "MERCADOPAGO_", "SHOP_", "REQUIRE_PHONE", "ENVIRONMENT",
                "PRIVATE_FILES", "MFA_", "PAC_", "EMISOR_")
    for key in list(os.environ):
        if key.startswith(prefixes):
            monkeypatch.delenv(key, raising=False)


def test_production_requires_private_key_and_mfa(clean_env):
    base = dict(
        _env_file=None, environment="production", secret_key="s" * 64,
        database_url="postgresql+psycopg2://patitasfind:Clave-Larga-De-Prod@postgres:5432/patitasfind",
        public_base_url="https://guauwoow.com", cors_origins="https://guauwoow.com",
        sms_provider="smsmasivos", smsmasivos_api_key="llave", smtp_host="smtp.ejemplo.mx",
        smtp_from="GuauWoow <no-reply@guauwoow.com>",
    )
    with pytest.raises(Exception) as exc:
        Settings(**base)
    assert "PRIVATE_FILES_KEY" in str(exc.value)
    with pytest.raises(Exception) as exc:
        Settings(**base, private_files_key=KEY_A, mfa_required_for_admins=False)
    assert "MFA_REQUIRED_FOR_ADMINS" in str(exc.value)
    assert Settings(**base, private_files_key=KEY_A).production_problems() == []
    with pytest.raises(Exception) as exc:
        Settings(_env_file=None, private_files_key="corta")
    assert "PRIVATE_FILES_KEY no es válida" in str(exc.value)


# =========================================================================== cifrado en reposo
def test_encrypt_roundtrip_tamper_and_plaintext_passthrough():
    data = b"%PDF-1.4 INE de prueba " + os.urandom(64)
    blob = crypto_storage.encrypt_bytes(data)
    assert blob.startswith(crypto_storage.MAGIC) and data not in blob and b"INE de prueba" not in blob
    assert crypto_storage.decrypt_bytes(blob) == data
    assert crypto_storage.encrypt_bytes(data) != blob  # nonce aleatorio
    broken = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(crypto_storage.DecryptionError):
        crypto_storage.decrypt_bytes(broken)
    assert crypto_storage.decrypt_bytes(b"antiguo en claro") == b"antiguo en claro"
    value = crypto_storage.encrypt_text("XAXX010101000")
    assert value.startswith("enc1:") and "XAXX" not in value
    assert crypto_storage.decrypt_text(value) == "XAXX010101000" and crypto_storage.decrypt_text("en claro") == "en claro"


def test_key_rotation(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "private_files_key", KEY_A)
    monkeypatch.setattr(settings, "private_files_old_keys", None)
    path = tmp_path / "doc.pdf"
    crypto_storage.write_private(path, b"%PDF-contenido")
    old_blob = path.read_bytes()
    column = crypto_storage.encrypt_text("RFC123")
    monkeypatch.setattr(settings, "private_files_key", KEY_B)
    with pytest.raises(crypto_storage.DecryptionError):
        crypto_storage.read_private(path)  # sin la llave anterior no se puede leer
    monkeypatch.setattr(settings, "private_files_old_keys", KEY_A)
    assert crypto_storage.read_private(path) == b"%PDF-contenido"
    assert crypto_storage.decrypt_text(column) == "RFC123" and crypto_storage.column_needs_reencryption(column)
    assert crypto_storage.encrypt_file_in_place(path, rotate=True) == "rotated"
    assert path.read_bytes()[6:10] != old_blob[6:10]  # id de llave nuevo
    monkeypatch.setattr(settings, "private_files_old_keys", None)
    assert crypto_storage.read_private(path) == b"%PDF-contenido"
    plain = tmp_path / "viejo.pdf"
    plain.write_bytes(b"%PDF-en-claro")
    assert crypto_storage.encrypt_file_in_place(plain) == "encrypted"
    assert crypto_storage.is_encrypted(plain.read_bytes()) and crypto_storage.read_private(plain) == b"%PDF-en-claro"
    assert crypto_storage.encrypt_file_in_place(plain) == "skipped"


def test_production_without_key_refuses_to_write(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "private_files_key", None)
    with pytest.raises(crypto_storage.CryptoConfigError):
        crypto_storage.write_private(tmp_path / "x.pdf", b"%PDF-")


def test_uploaded_document_is_encrypted_on_disk_and_served_decrypted(client, make_user, jpeg):
    owner = make_user("Refugio Cifrado")
    admin = _admin(make_user)
    pdf = b"%PDF-1.4\n% Acta constitutiva de prueba " + uuid.uuid4().hex.encode() + b"\n%%EOF"
    r = client.post("/upload/document", files={"file": ("acta.pdf", pdf, "application/pdf")}, headers=owner["h"])
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    on_disk = (documents.private_dir() / doc_id).read_bytes()
    assert crypto_storage.is_encrypted(on_disk) and b"Acta constitutiva" not in on_disk and b"%PDF" not in on_disk
    got = client.get(f"/admin/documents/{doc_id}", headers=admin["h"])
    assert got.status_code == 200 and got.content == pdf
    assert got.headers["content-type"] == "application/pdf" and "no-store" in got.headers["cache-control"]
    # Imágenes: también cifradas (sin EXIF) y se sirven como imagen válida
    r = client.post("/upload/document", files={"file": ("ine.jpg", jpeg(7), "image/jpeg")}, headers=owner["h"])
    img_id = r.json()["id"]
    raw = (documents.private_dir() / img_id).read_bytes()
    assert crypto_storage.is_encrypted(raw) and not raw.startswith(b"\xff\xd8")
    served = client.get(f"/admin/documents/{img_id}", headers=admin["h"])
    assert served.status_code == 200 and served.content.startswith(b"\xff\xd8")


def test_fiscal_columns_are_encrypted(client, make_user):
    u = make_user("Refugio Fiscal", verify=False)
    db = _db()
    try:
        uid = db.query(User.id).filter(User.email == u["email"]).scalar()
        refuge = Refuge(user_id=uid, name="Refugio Cifrado", status="approved", documents=[])
        db.add(refuge)
        db.flush()
        db.add(RefugeFiscalProfile(refuge_id=refuge.id, person_type="fisica", rfc="GODE561231GR8",
                                   legal_name="EVA GOMEZ DIAZ", regimen_fiscal="612", postal_code="06600"))
        db.commit()
        raw = db.execute(text("SELECT rfc, legal_name, postal_code FROM refuge_fiscal_profiles WHERE refuge_id = :r"),
                         {"r": refuge.id}).one()
        assert all(v.startswith("enc1:") for v in raw)
        assert "GODE561231GR8" not in raw[0] and "EVA" not in raw[1] and "06600" not in raw[2]
        db.expire_all()
        profile = db.query(RefugeFiscalProfile).filter(RefugeFiscalProfile.refuge_id == refuge.id).first()
        assert (profile.rfc, profile.legal_name, profile.postal_code) == ("GODE561231GR8", "EVA GOMEZ DIAZ", "06600")
    finally:
        db.close()


# =========================================================================== purga de conservación
def _private_doc(content: bytes = None) -> str:
    return documents._store_document(content or (b"%PDF-1.4 " + os.urandom(16)))


def test_verification_documents_purged_30_days_after_decision(client, make_user):
    u = make_user("Refugio Purga", verify=False)
    db = _db()
    try:
        uid = db.query(User.id).filter(User.email == u["email"]).scalar()
        old_doc, new_doc, audit_doc = _private_doc(), _private_doc(), _private_doc()
        old = Refuge(user_id=uid, name="Decidido hace 31 días", status="approved", documents=[old_doc],
                     verification_decided_at=NOW() - datetime.timedelta(days=31))
        recent = Refuge(user_id=uid, name="Decidido hace 10 días", status="rejected", documents=[new_doc],
                        verification_decided_at=NOW() - datetime.timedelta(days=10))
        by_audit = Refuge(user_id=uid, name="Decisión en la bitácora", status="approved", documents=[audit_doc])
        db.add_all([old, recent, by_audit])
        db.flush()
        db.add(AdminAuditLog(actor_id=None, action="refuge.approve", target_type="refuge", target_id=by_audit.id,
                             created_at=NOW() - datetime.timedelta(days=45)))
        db.commit()
        ids = (old.id, recent.id, by_audit.id)
    finally:
        db.close()
    result = _purge(only=("documentos_verificacion",), force=True)
    assert result["status"] == "ok", result
    db = _db()
    try:
        old, recent, by_audit = (db.query(Refuge).filter(Refuge.id == i).first() for i in ids)
        assert old.documents == [] and old.documents_purged_at is not None
        assert by_audit.documents == [] and by_audit.documents_purged_at is not None
        assert recent.documents == [new_doc] and recent.documents_purged_at is None
        assert documents.private_document_path(old_doc) is None and documents.private_document_path(audit_doc) is None
        assert documents.private_document_path(new_doc) is not None
        # Queda la constancia: estado y bitácora del borrado
        assert old.status == "approved"
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "retention.refuge_documents_purged",
                                              AdminAuditLog.target_id == old.id).count() == 1
    finally:
        db.close()


def test_vet_cedula_purged_after_decision_and_clinic_can_still_edit(client, make_user):
    owner = make_user("Clínica Purga")
    admin = _admin(make_user)
    doc = client.post("/upload/document", files={"file": ("cedula.pdf", b"%PDF-1.4 cedula", "application/pdf")},
                      headers=owner["h"]).json()["id"]
    db = _db()
    try:
        uid = db.query(User.id).filter(User.email == owner["email"]).scalar()
        vet = Veterinary(owner_user_id=uid, name=f"Clínica {uuid.uuid4().hex[:6]}", address="Calle 1", city="CDMX",
                         state="Ciudad de México", phone="5512345678", responsible_vet_name="Dra. Ana Pérez",
                         cedula_profesional="1234567", cedula_document_id=doc, status="verified",
                         verified_at=NOW() - datetime.timedelta(days=31), latitude=19.4, longitude=-99.1)
        rejected_doc = _private_doc()
        other = db.query(User).filter(User.email == admin["email"]).first()
        rejected = Veterinary(owner_user_id=other.id, name=f"Rechazada {uuid.uuid4().hex[:6]}", address="Calle 2",
                              city="CDMX", state="Ciudad de México", phone="5512345679",
                              responsible_vet_name="Dr. Luis Gómez", cedula_profesional="7654321",
                              cedula_document_id=rejected_doc, status="rejected",
                              unpublished_at=NOW() - datetime.timedelta(days=31))
        db.add_all([vet, rejected])
        db.commit()
        vid, rid = vet.id, rejected.id
    finally:
        db.close()
    _purge(only=("documentos_verificacion",), force=True)
    db = _db()
    try:
        vet = db.query(Veterinary).filter(Veterinary.id == vid).first()
        rej = db.query(Veterinary).filter(Veterinary.id == rid).first()
        assert vet.cedula_document_id is None and vet.cedula_document_purged_at is not None
        assert vet.cedula_profesional == "1234567" and vet.status == "verified"  # la constancia se queda
        assert rej.cedula_document_id is None and rej.cedula_document_purged_at is None
        assert documents.private_document_path(doc) is None and documents.private_document_path(rejected_doc) is None
    finally:
        db.close()
    # La clínica edita su ficha sin volver a subir la cédula...
    r = client.patch(f"/veterinaries/{vid}", json={"description": "Atendemos perritos rescatados"}, headers=owner["h"])
    assert r.status_code == 200, r.text
    assert r.json()["cedula_document_purged_at"] is not None
    # ...pero si cambia los datos de la cédula tiene que subir la nueva
    r = client.patch(f"/veterinaries/{vid}", json={"cedula_profesional": "7777777"}, headers=owner["h"])
    assert r.status_code == 400


def test_chats_of_deleted_accounts_purged_unless_reported(client, make_user):
    a, b, c = (make_user(n, verify=False) for n in ("Chat A", "Chat B", "Chat C"))
    db = _db()
    try:
        ua, ub, uc = (db.query(User).filter(User.email == x["email"]).first() for x in (a, b, c))
        conv = Conversation(user_a_id=ua.id, user_b_id=ub.id)
        kept = Conversation(user_a_id=uc.id, user_b_id=ub.id)
        db.add_all([conv, kept])
        db.flush()
        db.add_all([Message(conversation_id=conv.id, sender_id=ua.id, content="hola"),
                    Message(conversation_id=conv.id, sender_id=ub.id, content="¿sigue disponible?")])
        reported = Message(conversation_id=kept.id, sender_id=uc.id, content="mensaje reportado")
        db.add(reported)
        db.flush()
        db.add(ContentReport(reporter_id=ub.id, target_type="message", target_id=reported.id, reason="fraude"))
        ua.deleted_at = NOW() - datetime.timedelta(days=91)
        uc.deleted_at = NOW() - datetime.timedelta(days=91)
        db.commit()
        conv_id, kept_id = conv.id, kept.id
    finally:
        db.close()
    out = _purge(only=("chats_cuentas_eliminadas",), force=True)
    assert out["results"]["chats_cuentas_eliminadas"]["mensajes"] >= 2
    db = _db()
    try:
        assert db.query(Message).filter(Message.conversation_id == conv_id).count() == 0
        assert db.query(Message).filter(Message.conversation_id == kept_id).count() == 1  # tiene un reporte abierto
    finally:
        db.close()


def test_logs_reports_notifications_and_bot_purged(client, make_user):
    u = make_user("Purga Registros", verify=False)
    phone = "+52" + uuid.uuid4().hex[:10].translate(str.maketrans("abcdef", "123456"))
    db = _db()
    try:
        uid = db.query(User.id).filter(User.email == u["email"]).scalar()
        old_log = PhoneVerificationLog(user_id=uid, phone=phone, ip="10.1.2.3", provider="dev", success=True,
                                       created_at=NOW() - datetime.timedelta(days=91))
        mid_log = PhoneVerificationLog(user_id=uid, phone=phone, ip="10.9.8.7", provider="dev", success=True,
                                       created_at=NOW() - datetime.timedelta(days=31))
        audit = AdminAuditLog(actor_id=None, action="test.ip", target_type="user", target_id=uid, ip="2001:db8:1:2::5",
                              created_at=NOW() - datetime.timedelta(days=31))
        report = LostReport(reporter_id=uid, dog_name="Firulais", report_type="lost", description="Collar rojo",
                            contact_phone="5511112222", latitude=19.43, longitude=-99.13, city="CDMX", status="resolved",
                            resolved_at=NOW() - datetime.timedelta(days=91), photos=[])
        fresh = LostReport(reporter_id=uid, dog_name="Manchas", report_type="found", status="resolved",
                           resolved_at=NOW() - datetime.timedelta(days=5), city="CDMX", photos=[])
        note = Notification(user_id=uid, type="test", title="viejo", body="x",
                            created_at=NOW() - datetime.timedelta(days=400))
        bot_old = BotInteraction(phone=f"sim-{uuid.uuid4().hex[:8]}", data={"x": 1}, last_message="hola",
                                 updated_at=NOW() - datetime.timedelta(days=400))
        bot_opted = BotInteraction(phone=f"sim-{uuid.uuid4().hex[:8]}", data={"x": 1}, last_message="baja",
                                   opted_out_at=NOW() - datetime.timedelta(days=500),
                                   updated_at=NOW() - datetime.timedelta(days=400))
        db.add_all([old_log, mid_log, audit, report, fresh, note, bot_old, bot_opted])
        db.commit()
        ids = dict(old_log=old_log.id, mid_log=mid_log.id, audit=audit.id, report=report.id, fresh=fresh.id,
                   note=note.id, bot_old=bot_old.id, bot_opted=bot_opted.id)
    finally:
        db.close()
    out = _purge(only=("registros_otp_ip", "bitacora_admin", "reportes_anonimizar", "notificaciones",
                       "bot_whatsapp"), force=True)
    assert out["status"] == "ok", out
    db = _db()
    try:
        assert db.get(PhoneVerificationLog, ids["old_log"]) is None
        assert db.get(PhoneVerificationLog, ids["mid_log"]).ip == "10.9.8.0"
        assert db.get(AdminAuditLog, ids["audit"]).ip == "2001:db8:1::"
        rep = db.get(LostReport, ids["report"])
        assert rep.purged_at and rep.description is None and rep.contact_phone is None and rep.latitude is None
        assert rep.reporter_id is None and rep.city == "CDMX" and rep.status == "resolved" and rep.is_hidden
        assert db.get(LostReport, ids["fresh"]).purged_at is None
        assert db.get(Notification, ids["note"]) is None
        assert db.get(BotInteraction, ids["bot_old"]) is None
        opted = db.get(BotInteraction, ids["bot_opted"])
        assert opted is not None and opted.opted_out_at and opted.data == {} and opted.last_message is None
    finally:
        db.close()


def test_abandoned_private_documents_purged(client, make_user):
    orphan, used = _private_doc(), _private_doc()
    week_ago = time.time() - 8 * 86400
    for doc in (orphan, used):
        os.utime(documents.private_dir() / doc, (week_ago, week_ago))
    u = make_user("Refugio Usado", verify=False)
    db = _db()
    try:
        uid = db.query(User.id).filter(User.email == u["email"]).scalar()
        db.add(Refuge(user_id=uid, name="Usa el documento", status="pending", documents=[used]))
        db.commit()
    finally:
        db.close()
    _purge(only=("documentos_abandonados",), force=True)
    assert documents.private_document_path(orphan) is None
    assert documents.private_document_path(used) is not None


def test_open_incident_freezes_purges(client, make_user):
    db = _db()
    try:
        inc = SecurityIncident(title="Prueba de congelamiento", freeze_purges=True, status="abierto")
        uid = db.query(User.id).filter(User.email == make_user("Congelada", verify=False)["email"]).scalar()
        note = Notification(user_id=uid, type="test", title="viejo", body="x",
                            created_at=NOW() - datetime.timedelta(days=400))
        db.add_all([inc, note])
        db.commit()
        inc_id, note_id = inc.id, note.id
    finally:
        db.close()
    try:
        assert _purge(only=("notificaciones",))["status"] == "frozen"
        db = _db()
        try:
            assert db.get(Notification, note_id) is not None
        finally:
            db.close()
    finally:
        db = _db()
        try:
            db.query(SecurityIncident).filter(SecurityIncident.id == inc_id).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
    db = _db()
    try:
        still_frozen = retention.purges_frozen(db)  # otro incidente abierto (p. ej. de otra corrida) también congela
    finally:
        db.close()
    if not still_frozen:
        assert _purge(only=("notificaciones",))["status"] == "ok"
        db = _db()
        try:
            assert db.get(Notification, note_id) is None
        finally:
            db.close()


def test_dry_run_changes_nothing(client, make_user):
    db = _db()
    try:
        uid = db.query(User.id).filter(User.email == make_user("Simulación", verify=False)["email"]).scalar()
        note = Notification(user_id=uid, type="test", title="viejo", body="x",
                            created_at=NOW() - datetime.timedelta(days=400))
        db.add(note)
        db.commit()
        nid = note.id
    finally:
        db.close()
    out = _purge(only=("notificaciones",), dry_run=True, force=True)
    assert out["results"]["notificaciones"]["borradas"] >= 1
    db = _db()
    try:
        assert db.get(Notification, nid) is not None
    finally:
        db.close()


def test_retention_task_runs(client):
    from app.tasks import retention as retention_task

    out = retention_task.run_retention.run(dry_run=True)
    assert out["status"] in ("ok", "frozen", "disabled")


# =========================================================================== /cumplimiento/conservacion
def test_conservacion_matches_retention_config(client):
    r = client.get("/cumplimiento/conservacion")
    assert r.status_code == 200
    body = r.json()
    expected = [{k: row[k] for k in retention.PUBLIC_FIELDS} for row in retention.categories()]
    assert body["categorias"] == expected
    assert body["version"] == retention.VERSION and "purga" in body
    by_key = {row["clave"]: row for row in retention.categories()}
    # Cada purga de la tarea tiene su fila en la tabla publicada, marcada como automática
    for clave, _fn in retention.PURGERS:
        assert by_key[clave]["aplicacion"] == "automatica", clave
    # Los plazos que promete la página salen de la misma configuración que usa la purga
    assert by_key["documentos_verificacion"]["dias"] == retention.DOCUMENTOS_VERIFICACION_DIAS == 30
    assert "30 días" in by_key["documentos_verificacion"]["plazo"]
    assert by_key["reportes_expiracion"]["dias"] == settings.report_expiry_days
    assert by_key["importados_facebook"]["dias"] == settings.fb_groups_post_ttl_days
    assert retention.plazo_dias("chats_cuentas_eliminadas") == 90
    assert all(row["aplicacion_texto"] for row in body["categorias"])
    # Sin datos internos
    assert all("tarea" not in row and "dias" not in row for row in body["categorias"])


def test_truncate_ip():
    assert retention.truncate_ip("187.190.12.34") == "187.190.12.0"
    assert retention.truncate_ip("2806:10a6:1:2:3::9") == "2806:10a6:1::"
    assert retention.truncate_ip("unknown") == "unknown" and retention.truncate_ip(None) is None


# =========================================================================== /cumplimiento/estado e incidentes
def test_estado_shape(client):
    r = client.get("/cumplimiento/estado")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estado"] in ("operativo", "degradado", "mantenimiento", "interrupcion")
    for key in ("api", "base_de_datos", "cola", "correo", "pagos"):
        assert key in body["componentes"] and body["componentes"][key]["estado"]
    assert body["componentes"]["base_de_datos"]["estado"] == "operativo"
    assert isinstance(body["incidentes"], list) and isinstance(body["mantenimientos"], list)


def test_incident_registry_status_board_and_notices(client, make_user):
    admin = _admin(make_user)
    affected = make_user("Persona Afectada", verify=False)
    affected_id = _set_user(affected["email"])
    r = client.post("/admin/cumplimiento/incidentes", headers=admin["h"], json={
        "title": "Falla al cargar el sitio", "category": "disponibilidad", "severity": "S2",
        "components": ["web"], "public": True, "public_summary": "El sitio carga de forma intermitente.",
        "description": "Detalle interno que no debe publicarse", "started_at": NOW().isoformat(),
    })
    assert r.status_code == 201, r.text
    inc = r.json()
    assert inc["folio"].startswith("INC-") and inc["purges_frozen"] is True
    cache.delete(seg_router.ESTADO_CACHE_KEY)
    board = client.get("/cumplimiento/estado").json()
    assert board["componentes"]["web"]["estado"] == "interrumpido" and board["estado"] in ("degradado", "interrupcion")
    assert board["componentes"]["web"]["detalle"] == "El sitio carga de forma intermitente."
    public = [i for i in board["incidentes"] if i["folio"] == inc["folio"]]
    assert public and public[0]["resumen"] == "El sitio carga de forma intermitente." and public[0]["estado"] == "en_curso"
    assert "Detalle interno" not in str(board)

    # Mantenimiento programado: aparece en la lista de mantenimientos, no congela purgas
    m = client.post("/admin/cumplimiento/incidentes", headers=admin["h"], json={
        "title": "Actualización de la base de datos", "category": "mantenimiento", "components": ["api"],
        "public": True, "public_summary": "La app no estará disponible 30 minutos.",
        "started_at": (NOW() + datetime.timedelta(days=2)).isoformat(),
        "ended_at": (NOW() + datetime.timedelta(days=2, minutes=30)).isoformat(),
    }).json()
    assert m["freeze_purges"] is False
    cache.delete(seg_router.ESTADO_CACHE_KEY)
    assert any(x["folio"] == m["folio"] for x in client.get("/cumplimiento/estado").json()["mantenimientos"])

    # Una vulneración no se cierra sin causa raíz ni decisión razonada sobre la afectación significativa
    v = client.post("/admin/cumplimiento/incidentes", headers=admin["h"], json={
        "title": "Acceso indebido a documentos", "category": "vulneracion", "severity": "S1",
        "incident_type": "uso_no_autorizado", "affected_count": 1,
    }).json()
    assert client.patch(f"/admin/cumplimiento/incidentes/{v['id']}", headers=admin["h"],
                        json={"status": "cerrado"}).status_code == 400
    preview = client.post(f"/admin/cumplimiento/incidentes/{v['id']}/avisos/vista-previa", headers=admin["h"], json={
        "resumen": "un acceso no autorizado", "fecha": "17 de octubre de 2026", "que_paso": "una persona entró sin permiso.",
        "datos": "tu nombre y tu correo", "no_afectados": "tus contraseñas", "acciones": "cerramos el acceso.",
        "recomendaciones": "cambia tu contraseña.",
    }).json()
    for needle in ("1. Qué pasó", "2. Qué datos", "3. Qué hicimos", "4. Qué te recomendamos", "5. Dónde obtener"):
        assert needle in preview["email_body"], needle
    notice = {"resumen": "un acceso no autorizado", "fecha": "17 de octubre de 2026",
              "que_paso": "una persona entró sin permiso.", "datos": "tu nombre y tu correo",
              "acciones": "cerramos el acceso.", "recomendaciones": "cambia tu contraseña."}
    sent = client.post(f"/admin/cumplimiento/incidentes/{v['id']}/avisos", headers=admin["h"],
                       json={"notice": notice, "emails": [affected["email"].upper()]})
    assert sent.status_code == 200, sent.text
    assert sent.json()["app"] == 1 and sent.json()["version"] == 1
    again = client.post(f"/admin/cumplimiento/incidentes/{v['id']}/avisos", headers=admin["h"],
                        json={"notice": notice, "user_ids": [affected_id]}).json()
    assert again["app"] == 0 and again["omitidos"] == 1  # misma versión: no se duplica
    assert client.post(f"/admin/cumplimiento/incidentes/{v['id']}/avisos", headers=admin["h"],
                       json={"notice": notice, "all_users": True}).status_code == 403  # solo superadmin
    db = _db()
    try:
        rows = db.query(SecurityIncidentNotice).filter(SecurityIncidentNotice.incident_id == v["id"]).all()
        assert {(r.channel, r.user_id, r.notice_version) for r in rows} >= {("app", affected_id, 1), ("email", affected_id, 1)}
        assert db.query(Notification).filter(Notification.user_id == affected_id,
                                             Notification.type == "security_incident").count() == 1
    finally:
        db.close()
    closed = client.patch(f"/admin/cumplimiento/incidentes/{v['id']}", headers=admin["h"], json={
        "status": "cerrado", "root_cause": "Credencial filtrada", "significant_impact": True,
        "significant_impact_reason": "Se expusieron datos de contacto", "note": "Cierre y post-mortem",
    })
    assert closed.status_code == 200, closed.text
    assert closed.json()["closed_at"] and closed.json()["purges_frozen"] is False
    assert any(t["text"] == "Cierre y post-mortem" for t in closed.json()["timeline"])
    for x in (inc, m):
        client.patch(f"/admin/cumplimiento/incidentes/{x['id']}", headers=admin["h"], json={"status": "cerrado"})
    # Solo admins
    assert client.get("/admin/cumplimiento/incidentes", headers=affected["h"]).status_code == 403
    # Limpieza: los incidentes de prueba no se quedan en el tablero público de desarrollo
    db = _db()
    try:
        ids = [inc["id"], m["id"], v["id"]]
        db.query(SecurityIncidentNotice).filter(SecurityIncidentNotice.incident_id.in_(ids)).delete(
            synchronize_session=False)
        db.query(SecurityIncident).filter(SecurityIncident.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_admin_security_overview(client, make_user):
    boss = _admin(make_user, role="superadmin")
    s = client.get("/admin/cumplimiento/cifrado", headers=boss["h"]).json()
    assert s["ok"] is True and "plaintext_files" in s and "private_files" in s
    c = client.get("/admin/cumplimiento/conservacion", headers=boss["h"]).json()
    assert c["categorias"] and "corridas" in c
    r = client.post("/admin/cumplimiento/conservacion/ejecutar", headers=boss["h"], json={"dry_run": True})
    assert r.status_code == 200 and r.json()["status"] in ("ok", "frozen", "disabled", "error")
