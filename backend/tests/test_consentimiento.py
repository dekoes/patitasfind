"""Consentimiento (K-DOCS, K-ACEPT, K-PREF, L-edad): registro con edad, bitácora encadenada de solo inserción,
reaceptación, anexos de aliados, preferencias con constancias, comandos del bot y alertas cercanas con permiso."""
import datetime
import json
import random
import threading
import uuid

import pytest
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AgeCheck, BotInteraction, ComplianceRequest, ConsentRecord, ContentReport, LegalAcceptance, LegalDocument,
    LostReport, Notification, User,
)
from app.services import consent, legal_acceptance as la, whatsapp_bot
from app.tasks import legal_docs, notifications as notif_tasks
from tests.conftest import random_phone

ADULT = {"is_adult": True, "birth_date": "1990-01-01"}


def _email(prefix="consent"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@pruebas.mx"


def _user(email) -> User:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        db.expunge(u)
        return u
    finally:
        db.close()


def _set(email, **values):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        for k, v in values.items():
            setattr(u, k, v)
        db.commit()
        return u.id
    finally:
        db.close()


def _acceptances(user_id):
    db = SessionLocal()
    try:
        return db.query(LegalAcceptance).filter(LegalAcceptance.user_id == user_id).order_by(LegalAcceptance.id).all()
    finally:
        db.close()


def _consents(user_id=None, phone=None):
    db = SessionLocal()
    try:
        q = db.query(ConsentRecord)
        q = q.filter(ConsentRecord.user_id == user_id) if user_id else q.filter(ConsentRecord.phone == phone)
        return q.order_by(ConsentRecord.id).all()
    finally:
        db.close()


@pytest.fixture
def admin(make_user):
    u = make_user("Admin Consentimiento")
    u["id"] = _set(u["email"], role="admin")
    yield u
    _set(u["email"], role="user")


@pytest.fixture
def test_docs():
    """Documentos de prueba con slug propio (no tocan las versiones reales); se borran al terminar."""
    slugs = []

    def make(versions, requires=True):
        slug = f"prueba-{uuid.uuid4().hex[:8]}"
        slugs.append(slug)
        db = SessionLocal()
        try:
            now = datetime.datetime.utcnow()
            rows = []
            for i, (version, effective) in enumerate(versions):
                row = LegalDocument(slug=slug, title=f"Documento de prueba {slug}", version=version,
                                    effective_at=effective, published_at=now - datetime.timedelta(days=10 - i),
                                    sha256=uuid.uuid4().hex + uuid.uuid4().hex, requires_reacceptance=requires,
                                    summary=f"Cambios de {version}", url=f"/app/legal/{slug}.html")
                db.add(row)
                rows.append(row)
            db.commit()
            return slug, [{"version": r.version, "sha256": r.sha256, "id": r.id} for r in rows]
        finally:
            db.close()

    yield make
    db = SessionLocal()
    try:
        db.query(LegalDocument).filter(LegalDocument.slug.in_(slugs)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- edad en el registro
def test_register_requires_separate_adult_checkbox_and_birth_date(client):
    base = {"email": _email(), "password": "Segura123", "full_name": "Edad Prueba", "phone": random_phone(),
            "accepted_terms": True}
    r = client.post("/auth/register", json={**base, "birth_date": "1990-01-01"})
    assert r.status_code == 400 and "18 años" in r.json()["detail"]  # falta la casilla separada
    r = client.post("/auth/register", json={**base, "is_adult": True})
    assert r.status_code == 400 and "nacimiento" in r.json()["detail"]
    minor = (datetime.date.today() - datetime.timedelta(days=17 * 365)).isoformat()
    r = client.post("/auth/register", json={**base, "is_adult": True, "birth_date": minor})
    assert r.status_code == 400 and "18 años" in r.json()["detail"]
    r = client.post("/auth/register", json={**base, "is_adult": True, "birth_date": "2999-01-01"})
    assert r.status_code == 400
    # La casilla de Términos y Aviso es otra: sin ella tampoco (y acepta el alias accept_terms)
    body = {k: v for k, v in base.items() if k != "accepted_terms"}
    assert client.post("/auth/register", json={**body, **ADULT}).status_code == 400
    r = client.post("/auth/register", json={**body, **ADULT, "accept_terms": True},
                    headers={"User-Agent": "pytest-consent/1.0"})
    assert r.status_code == 201, r.text
    me = client.get("/users/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["age_declared"] is True and me["birth_date"] == "1990-01-01"
    assert me["notify_nearby"] is False and me["whatsapp_alerts"] is False and me["email_marketing"] is False

    rows = _acceptances(me["id"])
    assert [a.slug for a in rows] == ["terminos", "privacidad", "mayoria-de-edad"]
    assert all(a.method == "registro" and a.user_agent == "pytest-consent/1.0" and a.ip for a in rows)
    assert all(len(a.sha256) == 64 and len(a.row_hash) == 64 for a in rows)
    age = rows[-1]
    assert age.context == {"birth_date": "1990-01-01"}
    assert age.sha256 == la.sha256_text(la.AGE_DECLARATION["text"])
    terms = la.current_document(SessionLocal(), "terminos")
    if terms is not None:  # registro sincronizado: se guarda la huella publicada
        assert rows[0].version == terms.version and rows[0].sha256 == terms.sha256


def test_register_records_marketing_consent(client):
    body = {"email": _email(), "password": "Segura123", "full_name": "Promos", "phone": random_phone(),
            "accepted_terms": True, "marketing_opt_in": True, **ADULT}
    r = client.post("/auth/register", json=body)
    assert r.status_code == 201
    uid = _user(body["email"]).id
    recs = _consents(uid)
    assert [(c.purpose, c.granted, c.channel) for c in recs] == [("email_marketing", True, "registro")]
    assert recs[0].text_version == consent.text_version("email_marketing")


def test_google_account_must_declare_age_before_writing(client, make_user):
    """Cuenta creada con Google (sin fecha de nacimiento): solo lectura hasta completar la casilla y la fecha."""
    from app.routers import auth as auth_router

    db = SessionLocal()
    try:
        email = _email("google")
        user = auth_router.link_google_account(db, {"sub": "g-" + uuid.uuid4().hex, "email": email,
                                                    "email_verified": True, "name": "Con Google"})
        token = auth_router.create_session_token(user)["access_token"]
        uid = user.id
    finally:
        db.close()
    h = {"Authorization": f"Bearer {token}"}
    _set(email, phone="+52" + random_phone(), phone_verified=True)
    me = client.get("/users/me", headers=h).json()
    assert me["age_declaration_required"] is True and me["age_declared"] is False
    r = client.post("/foster-homes/register", headers=h, json={"description": "Casa", "city": "Pruebas"})
    assert r.status_code == 403 and r.json()["code"] == "age_declaration_required"
    assert client.get("/cumplimiento/pendientes", headers=h).json()["completar_registro"] is True
    # Completar: Términos + casilla separada + fecha (la falta de cualquiera es 400)
    assert client.post("/users/me/terms", headers=h, json={"accepted_terms": True}).status_code == 400
    r = client.post("/users/me/terms", headers=h, json={"accepted_terms": True, "birth_date": "1990-01-01"})
    assert r.status_code == 400  # sin la casilla separada de 18+
    # (una fecha de menor cierra la cuenta: tests/test_cumplimiento_cuentas.py)
    r = client.post("/users/me/terms", headers=h, json={"accepted_terms": True, **ADULT})
    assert r.status_code == 200 and r.json()["age_declared"] is True
    assert {a.slug for a in _acceptances(uid)} == {"terminos", "privacidad", "mayoria-de-edad"}
    # Primera aceptación de una cuenta de Google: es el registro, no una reaceptación
    assert {a.method for a in _acceptances(uid)} == {"registro"}
    assert client.get("/cumplimiento/pendientes", headers=h).json()["completar_registro"] is False


# --------------------------------------------------------------------------- bitácora encadenada
def test_acceptance_chain_is_valid_and_detects_tampering(client, make_user):
    make_user("Cadena")
    db = SessionLocal()
    try:
        assert la.verify_chain(db)["ok"] is True
        last = db.query(LegalAcceptance).order_by(LegalAcceptance.id.desc()).first()
        assert la.row_digest(last.prev_hash, last) == last.row_hash
        # Una fila «editada» ya no cuadra con su huella
        db.expunge(last)
        last.version = "1999-01-01"
        assert la.row_digest(last.prev_hash, last) != last.row_hash
    finally:
        db.close()


def test_concurrent_acceptances_never_fork_the_chain(client, make_user):
    u = make_user("Concurrente")
    uid = _user(u["email"]).id
    errors = []

    def worker():
        db = SessionLocal()
        try:
            user = db.get(User, uid)
            la.record_acceptance(db, user, "terminos", "reaceptacion", commit=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    db = SessionLocal()
    try:
        rows = db.query(LegalAcceptance).filter(LegalAcceptance.user_id == uid).all()
        assert len(rows) == 3 + 6
        assert len({r.prev_hash for r in rows}) == len(rows)
        assert la.verify_chain(db)["ok"] is True
    finally:
        db.close()


def test_append_only_trigger_blocks_update_delete_and_truncate(client, make_user):
    db = SessionLocal()
    try:
        if not la.append_only_active(db):
            pytest.skip("el trigger de solo inserción se instala en la migración 0004")
    finally:
        db.close()
    u = make_user("Trigger")
    uid = _user(u["email"]).id
    client.patch("/cumplimiento/preferencias", headers=u["h"], json={"notify_nearby": True})  # una constancia
    for sql in (f"UPDATE legal_acceptances SET version = 'x' WHERE user_id = {uid}",
                f"DELETE FROM legal_acceptances WHERE user_id = {uid}",
                "TRUNCATE legal_acceptances",
                f"UPDATE consent_records SET granted = NOT granted WHERE user_id = {uid}",
                "TRUNCATE consent_records"):
        db = SessionLocal()
        try:
            with pytest.raises(Exception) as exc:
                db.execute(text(sql))
                db.flush()
            assert "solo inserción" in str(exc.value)
        finally:
            db.rollback()
            db.close()
    # La purga de conservación sí puede borrar dentro de su transacción (aquí se deshace)
    db = SessionLocal()
    try:
        la.allow_purge(db)
        deleted = db.execute(text(f"DELETE FROM legal_acceptances WHERE user_id = {uid}")).rowcount
        assert deleted == 3
    finally:
        db.rollback()
        db.close()
    assert len(_acceptances(uid)) == 3


def test_admin_verify_chain_and_cli(client, admin):
    r = client.get("/admin/cumplimiento/aceptaciones/verificar", headers=admin["h"])
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["rows"] > 0
    assert client.get("/admin/cumplimiento/aceptaciones/verificar", headers=_plain_user_headers(client)).status_code == 403
    from app import cli

    assert cli.verify_acceptances() == 0


def _plain_user_headers(client):
    from tests.conftest import _register

    return _register(client, "Sin permisos", verify=False)["h"]


# --------------------------------------------------------------------------- registro de versiones y reaceptación
def test_sync_documents_registry_and_public_endpoint(client, tmp_path):
    slug = f"prueba-{uuid.uuid4().hex[:8]}"
    sha1, sha2 = uuid.uuid4().hex * 2, uuid.uuid4().hex * 2
    path = tmp_path / "versiones.json"
    path.write_text(json.dumps([
        {"slug": slug, "title": "Prueba", "version": "2026-10-17", "effective_at": None, "sha256": sha1,
         "requires_reacceptance": True, "summary": "Primera versión.", "url": f"/app/legal/{slug}.html"},
        {"slug": "NO VÁLIDO", "version": "x", "sha256": "abc"},
    ]), encoding="utf-8")
    db = SessionLocal()
    try:
        r1 = la.sync_from_file(db, path, notify=False)
        assert len(r1["created"]) == 1 and r1["notice_ids"] == []
        assert la.sync_from_file(db, path, notify=False)["created"] == []  # idempotente
        # Versión nueva con fecha de entrada en vigor en 10 días: pide aviso previo y advierte (< 30 días)
        future = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
        path.write_text(json.dumps([
            {"slug": slug, "title": "Prueba", "version": "2026-10-17", "sha256": sha1, "requires_reacceptance": True,
             "summary": "Primera versión.", "url": f"/app/legal/{slug}.html"},
            {"slug": slug, "title": "Prueba", "version": future, "effective_at": future, "sha256": sha2,
             "requires_reacceptance": True, "summary": "Cambia la comisión.", "url": f"/app/legal/{slug}.html"},
        ]), encoding="utf-8")
        r2 = la.sync_from_file(db, path, notify=False)
        assert len(r2["created"]) == 1 and r2["notice_ids"] == r2["created"]
        assert any(slug in w and "30 días" in w for w in r2["warnings"])
        body = client.get("/cumplimiento/documentos").json()
        doc = next(d for d in body["documentos"] if d["slug"] == slug)
        assert doc["vigente"]["version"] == "2026-10-17" and doc["vigente"]["sha256"] == sha1
        assert doc["proxima"]["version"] == future and doc["proxima"]["summary"] == "Cambia la comisión."
        assert [v["status"] for v in doc["versiones"]] == ["proxima", "vigente"]
        assert doc["requires_reacceptance"] is True and doc["vigente"]["published_at"]
    finally:
        db.query(LegalDocument).filter(LegalDocument.slug == slug).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_pending_reacceptance_flow_and_30_day_notice(client, make_user, test_docs, monkeypatch):
    u = make_user("Reacepta")
    uid = _user(u["email"]).id
    past = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    slug, (v1,) = test_docs([("2026-01-01", None)])
    # El documento de prueba aplica a todas las cuentas y bloquea la app (como Términos y Aviso)
    original = la.applicable
    monkeypatch.setattr(la, "applicable", lambda db, user: {**original(db, user), slug: {"blocking": True, "role": None}})
    pend = client.get("/cumplimiento/pendientes", headers=u["h"]).json()
    item = next(p for p in pend["pendientes"] if p["slug"] == slug)
    assert item["blocking"] is True and item["reason"] == "primera_vez" and item["sha256"] == v1["sha256"]
    # Huella equivocada: 409; la correcta queda en la bitácora como reaceptación
    r = client.post("/cumplimiento/aceptaciones", headers=u["h"], json={"slug": slug, "version": v1["version"], "sha256": "0" * 64})
    assert r.status_code == 409 and r.json()["code"] == "legal_version_mismatch"
    r = client.post("/cumplimiento/aceptaciones", headers=u["h"], json={"slug": slug, "version": v1["version"], "sha256": v1["sha256"]})
    assert r.status_code == 200 and r.json()["aceptacion"]["method"] == "reaceptacion"
    assert slug not in [p["slug"] for p in r.json()["pendientes"]]

    # Nueva versión con fecha futura: aviso previo (banner), todavía no se pide aceptarla
    db = SessionLocal()
    try:
        future = datetime.datetime.utcnow() + datetime.timedelta(days=30)
        nxt = LegalDocument(slug=slug, title="Documento de prueba", version="2026-12-01", effective_at=future,
                            sha256=uuid.uuid4().hex * 2, requires_reacceptance=True, summary="Nuevo plazo",
                            url=f"/app/legal/{slug}.html")
        db.add(nxt)
        db.commit()
        nxt_id = nxt.id
    finally:
        db.close()
    pend = client.get("/cumplimiento/pendientes", headers=u["h"]).json()
    assert slug not in [p["slug"] for p in pend["pendientes"]]
    aviso = next(a for a in pend["avisos"] if a["slug"] == slug)
    assert aviso["version"] == "2026-12-01" and 28 <= aviso["days_left"] <= 30

    # Aviso por correo y en la app (tarea), una sola vez
    monkeypatch.setattr(la, "audience_query", lambda db, s: db.query(User).filter(User.id == uid))
    db = SessionLocal()
    try:
        assert legal_docs.run_notices(db, nxt_id) == 1
        assert legal_docs.run_notices(db, nxt_id) == 0
        notes = db.query(Notification).filter(Notification.user_id == uid, Notification.type == "legal_change").all()
        assert len(notes) == 1 and "2026-12-01" in notes[0].body and "no cuenta como aceptación" in notes[0].body
        # Entra en vigor: ahora sí se pide (nueva_version)
        row = db.get(LegalDocument, nxt_id)
        row.effective_at = past
        db.commit()
    finally:
        db.close()
    pend = client.get("/cumplimiento/pendientes", headers=u["h"]).json()
    item = next(p for p in pend["pendientes"] if p["slug"] == slug)
    assert item["version"] == "2026-12-01" and item["reason"] == "nueva_version"
    hist = client.get("/cumplimiento/aceptaciones/mias", headers=u["h"]).json()["aceptaciones"]
    assert any(a["slug"] == slug for a in hist)


def test_annex_acceptance_for_allies(client, make_user, monkeypatch):
    refugio = make_user("Refugio con anexo")
    r = client.post("/refuges/register", headers=refugio["h"], json={"name": "Refugio Anexo", "accepted_annex": True})
    assert r.status_code == 201, r.text
    uid = _user(refugio["email"]).id
    rows = [a for a in _acceptances(uid) if a.method == "anexo"]
    assert {a.slug for a in rows} == {"terminos-refugios", "acuerdo-datos-refugios"}
    assert all(a.context.get("refuge_id") == r.json()["id"] for a in rows)
    pend = client.get("/cumplimiento/pendientes", headers=refugio["h"]).json()["pendientes"]
    assert not [p for p in pend if p["slug"] in la.ANNEX_SLUGS["refugio"]]

    # Un refugio sin la casilla (desarrollo: no se exige) queda con el anexo pendiente, sin bloquear la app
    sin = make_user("Refugio sin anexo")
    assert client.post("/refuges/register", headers=sin["h"], json={"name": "Refugio Sin"}).status_code == 201
    pend = client.get("/cumplimiento/pendientes", headers=sin["h"]).json()["pendientes"]
    annex = [p for p in pend if p["slug"] in la.ANNEX_SLUGS["refugio"]]
    if la.current_document(SessionLocal(), "terminos-refugios") is not None:
        assert annex and all(p["blocking"] is False and p["method"] == "anexo" for p in annex)

    # Con LEGAL_ANNEX_REQUIRED (producción) la casilla es obligatoria
    monkeypatch.setattr(settings, "legal_annex_required", True)
    casa = make_user("Casa sin anexo")
    r = client.post("/foster-homes/register", headers=casa["h"], json={"description": "Casa", "city": "Pruebas"})
    assert r.status_code == 400 and r.json()["code"] == "annex_required"
    assert [d["slug"] for d in r.json()["documents"]] == ["terminos-casas-de-paso", "acuerdo-datos-refugios"]
    r = client.post("/foster-homes/register", headers=casa["h"],
                    json={"description": "Casa", "city": "Pruebas", "accepted_annex": True})
    assert r.status_code == 201
    assert [a.slug for a in _acceptances(_user(casa["email"]).id) if a.method == "anexo"] == [
        "terminos-casas-de-paso", "acuerdo-datos-refugios"]


# --------------------------------------------------------------------------- preferencias y constancias
def test_preferences_default_off_and_every_change_is_recorded(client, make_user):
    u = make_user("Preferencias")
    uid = _user(u["email"]).id
    prefs = client.get("/cumplimiento/preferencias", headers=u["h"]).json()
    assert (prefs["notify_nearby"], prefs["whatsapp_alerts"], prefs["email_marketing"]) == (False, False, False)
    assert prefs["invite_nearby"] is True and set(prefs["texts"]) == set(consent.PURPOSES)
    assert client.get("/cumplimiento/pendientes", headers=u["h"]).json()["invitar_alertas"] is True

    r = client.patch("/cumplimiento/preferencias", headers={**u["h"], "User-Agent": "pytest"},
                     json={"notify_nearby": True, "email_marketing": True})
    assert r.status_code == 200 and r.json()["notify_nearby"] is True and r.json()["email_marketing"] is True
    assert r.json()["invite_nearby"] is False
    client.patch("/cumplimiento/preferencias", headers=u["h"], json={"notify_nearby": True})  # sin cambio: sin constancia
    client.patch("/users/me", headers=u["h"], json={"notify_nearby": False})  # el perfil también deja constancia
    recs = _consents(uid)
    assert [(c.purpose, c.granted, c.channel) for c in recs] == [
        ("notify_nearby", True, "app"), ("email_marketing", True, "app"), ("notify_nearby", False, "app")]
    assert recs[0].text_version == consent.text_version("notify_nearby") and recs[0].ip and recs[0].user_agent == "pytest"
    assert recs[0].text_version.startswith(consent.CONSENT_VERSION + "#")

    # Cookies: constancia de la elección del banner (solo si cambia)
    assert client.post("/cumplimiento/preferencias/cookies", headers=u["h"], json={"analytics": True}).status_code == 200
    client.post("/cumplimiento/preferencias/cookies", headers=u["h"], json={"analytics": True})
    client.post("/cumplimiento/preferencias/cookies", headers=u["h"], json={"analytics": False})
    cookies = [(c.granted, c.channel) for c in _consents(uid) if c.purpose == "analytics_cookies"]
    assert cookies == [(True, "web"), (False, "web")]
    assert client.get("/cumplimiento/preferencias", headers=u["h"]).json()["analytics"] is False

    # Descargar mis datos incluye la bitácora y los permisos
    data = client.get("/users/me/export", headers=u["h"]).json()
    assert {a["slug"] for a in data["legal_acceptances"]} >= {"terminos", "privacidad", "mayoria-de-edad"}
    assert len(data["consent_records"]) == 5 and data["profile"]["birth_date"] == "1990-01-01"


def test_whatsapp_preference_syncs_with_bot_opt_out(client, make_user):
    u = make_user("WhatsApp app")
    digits = u["phone"].lstrip("+")
    db = SessionLocal()
    try:
        db.add(BotInteraction(phone=digits, stage="welcome", data={}))
        db.commit()
    finally:
        db.close()
    assert client.patch("/cumplimiento/preferencias", headers=u["h"], json={"whatsapp_alerts": True}).json()["whatsapp_alerts"]
    db = SessionLocal()
    try:
        assert db.query(BotInteraction).filter(BotInteraction.phone == digits).one().opted_out_at is None
    finally:
        db.close()
    client.patch("/cumplimiento/preferencias", headers=u["h"], json={"whatsapp_alerts": False})
    db = SessionLocal()
    try:
        assert db.query(BotInteraction).filter(BotInteraction.phone == digits).one().opted_out_at is not None
    finally:
        db.close()


def test_whatsapp_templates_only_with_consent(client, make_user, monkeypatch):
    from app.services import notify

    u = make_user("Plantillas")
    monkeypatch.setattr(settings, "whatsapp_access_token", "EAAG-prueba")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "123")
    assert notify.can_whatsapp(_user(u["email"])) is False
    client.patch("/cumplimiento/preferencias", headers=u["h"], json={"whatsapp_alerts": True})
    assert notify.can_whatsapp(_user(u["email"])) is True


def test_nearby_alerts_require_switch_and_consent_record(client, make_user):
    lat, lon = round(random.uniform(20.5, 21.5), 5), round(random.uniform(-104.5, -103.5), 5)
    opted = make_user("Con permiso")
    legacy = make_user("Interruptor sin constancia")
    revoked = make_user("Lo apagó")
    client.patch("/cumplimiento/preferencias", headers=opted["h"], json={"notify_nearby": True})
    client.patch("/cumplimiento/preferencias", headers=revoked["h"], json={"notify_nearby": True})
    _set(legacy["email"], notify_nearby=True)  # p. ej. una fila anterior a la migración: sin constancia no se avisa
    # La ubicación se guarda en la cuenta solo con las alertas encendidas (privacidad.html §8)
    for u in (opted, legacy, revoked):
        assert client.patch("/users/me", headers=u["h"], json={"latitude": lat + 0.004, "longitude": lon}).status_code == 200
    client.patch("/cumplimiento/preferencias", headers=revoked["h"], json={"notify_nearby": False})
    assert _user(revoked["email"]).latitude is None  # apagar las alertas borra la ubicación guardada
    db = SessionLocal()
    try:
        report = LostReport(reporter_id=None, dog_name="Canela", report_type="lost", status="active", source="app",
                            latitude=lat, longitude=lon, city="Pruebas", photos=[])
        db.add(report)
        db.commit()
        rid = report.id
        ids = {k: db.query(User.id).filter(User.email == v["email"]).scalar()
               for k, v in (("opted", opted), ("legacy", legacy), ("revoked", revoked))}
        recipients = {u.id for u, _ in notif_tasks.nearby_recipients(db, db.get(LostReport, rid))}
    finally:
        db.close()
    assert ids["opted"] in recipients
    assert ids["legacy"] not in recipients and ids["revoked"] not in recipients
    assert notif_tasks.notify_nearby_report(rid) >= 1
    db = SessionLocal()
    try:
        got = {n.user_id for n in db.query(Notification).filter(Notification.type == "nearby_alert",
                                                                Notification.user_id.in_(ids.values())).all()}
    finally:
        db.close()
    assert got == {ids["opted"]}


# --------------------------------------------------------------------------- bot de WhatsApp
def _bot(phone, message):
    db = SessionLocal()
    try:
        return whatsapp_bot.process_message(db, phone, message, None)
    finally:
        db.close()


def _interaction(phone):
    db = SessionLocal()
    try:
        row = db.query(BotInteraction).filter(BotInteraction.phone == phone).first()
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


@pytest.mark.parametrize("word", ["BAJA", "stop", "Alto", "CANCELAR", "no me escriban"])
def test_bot_opt_out_words(client, word):
    phone = "52" + random_phone()
    _bot(phone, "hola")
    r = _bot(phone, word)
    assert "ALTA" in r["response"]
    assert _interaction(phone).opted_out_at is not None
    assert [(c.purpose, c.granted, c.channel) for c in _consents(phone=phone)] == [("whatsapp_alerts", False, "whatsapp")]


def test_bot_baja_hola_alta_with_linked_account(client, make_user):
    u = make_user("Bot ligado")
    client.patch("/cumplimiento/preferencias", headers=u["h"], json={"whatsapp_alerts": True})
    phone = u["phone"].lstrip("+")
    uid = _user(u["email"]).id
    _bot(phone, "BAJA")
    assert _user(u["email"]).whatsapp_alerts is False
    r = _bot(phone, "hola")  # reabre la conversación pero NO reactiva los avisos
    assert "Perdí a mi perro" in r["response"] and "BAJA" in r["response"]
    assert _interaction(phone).opted_out_at is not None and _user(u["email"]).whatsapp_alerts is False
    r = _bot(phone, "ALTA")
    assert "BAJA" in r["response"] and _interaction(phone).opted_out_at is None
    assert _user(u["email"]).whatsapp_alerts is True
    assert [(c.granted, c.channel) for c in _consents(uid) if c.purpose == "whatsapp_alerts"] == [
        (True, "app"), (False, "whatsapp"), (True, "whatsapp")]


def test_bot_persona_notifies_admins_once(client, admin):
    from app import cache

    phone = "52" + random_phone()
    cache.delete(f"wa-human:{phone}")
    r = _bot(phone, "PERSONA")
    assert "equipo" in r["response"]
    _bot(phone, "persona")
    db = SessionLocal()
    try:
        notes = db.query(Notification).filter(Notification.user_id == admin["id"], Notification.type == "support_handoff").all()
        mine = [n for n in notes if (n.data or {}).get("phone") == phone]
    finally:
        db.close()
    assert len(mine) == 1 and phone in mine[0].body


def test_bot_eliminar_confirms_purges_and_opens_request(client):
    phone = "52" + random_phone()
    db = SessionLocal()
    try:
        report = LostReport(reporter_id=None, dog_name="Firulais", report_type="lost", status="active", source="whatsapp",
                            contact_phone=phone, description="Collar rojo", latitude=19.4, longitude=-99.1, photos=[])
        db.add(report)
        db.commit()
        rid = report.id
    finally:
        db.close()
    _bot(phone, "hola")
    r = _bot(phone, "ELIMINAR")
    assert "SÍ" in r["response"] and _interaction(phone).stage == "confirm_delete"
    r = _bot(phone, "no")  # cancelar no borra nada
    assert "no borramos" in r["response"]
    _bot(phone, "eliminar")
    r = _bot(phone, "Sí")
    assert "Borramos tu conversación" in r["response"]
    inter = _interaction(phone)
    assert inter.data == {} and inter.last_message is not None and inter.opted_out_at is not None
    db = SessionLocal()
    try:
        rep = db.get(LostReport, rid)
        assert rep.is_hidden and rep.purged_at is not None and rep.contact_phone is None and rep.latitude is None
        req = db.query(ComplianceRequest).filter(ComplianceRequest.phone == phone).first()
    finally:
        db.close()
    if req is not None:
        assert req.kind == "cancelacion" and req.channel == "whatsapp" and req.folio in r["response"]
        assert req.identity_method == "whatsapp" and (req.details or {}).get("alcance") == "whatsapp"


# --------------------------------------------------------------------------- verificación reforzada de edad
def _report_minor(target_user_id, reporter_id=None):
    """Reporte «involucra a un menor» contra la cuenta. Solo limita al momento si lo envía una cuenta con teléfono
    verificado (reporter_id) o varias personas distintas (services/age_check.should_auto_limit)."""
    db = SessionLocal()
    try:
        cr = ContentReport(reporter_id=reporter_id, target_type="user", target_id=target_user_id,
                           reason="involucra_menor", details="Parece una niña de 14 años", status="open")
        db.add(cr)
        db.commit()
        return cr.id
    finally:
        db.close()


def test_minor_report_limits_account_until_reinforced_check(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    u = make_user("Edad reforzada")
    uid = _user(u["email"]).id
    reporter_id = _user(make_user("Quien reporta")["email"]).id  # cuenta con teléfono verificado
    hip = {**u["h"], "X-Real-IP": u["ip"]}
    report_id = _report_minor(uid, reporter_id)
    me = client.get("/users/me", headers=u["h"]).json()
    assert me["age_check_required"] is True
    db = SessionLocal()
    try:
        check = db.query(AgeCheck).filter(AgeCheck.user_id == uid).one()
        assert check.status == "required" and check.reason == "involucra_menor" and check.content_report_id == report_id
        assert db.query(Notification).filter(Notification.user_id == uid, Notification.type == "age_check").count() == 1
    finally:
        db.close()
    # Cuenta limitada: escribir responde 403 con código; leer sí funciona
    r = client.post("/foster-homes/register", headers=u["h"], json={"description": "Casa", "city": "Pruebas"})
    assert r.status_code == 403 and r.json()["code"] == "age_check_required"
    assert client.get("/notifications", headers=u["h"]).status_code == 200
    status = client.get("/cumplimiento/edad", headers=u["h"]).json()
    assert status["required"] is True and "copia" not in status["declaration_text"].lower()
    assert client.get("/cumplimiento/pendientes", headers=u["h"]).json()["verificacion_edad"]["required"] is True

    # Código NUEVO por SMS; la fecha debe coincidir con la registrada. El código se revisa primero y cada fecha
    # distinta lo gasta (no sirve para adivinar la fecha registrada)
    sent = client.post("/cumplimiento/edad/codigo", headers=hip)
    assert sent.status_code == 200, sent.text
    code = sent.json()["dev_code"]
    r = client.post("/cumplimiento/edad/verificar", headers=u["h"], json={"birth_date": "1991-01-01", "code": "000000", "declaration": True})
    assert r.status_code == 400 and "Código" in r.json()["detail"]
    r = client.post("/cumplimiento/edad/verificar", headers=u["h"], json={"birth_date": "1991-01-01", "code": code, "declaration": True})
    assert r.status_code == 400 and "no coincide" in r.json()["detail"]
    r = client.post("/cumplimiento/edad/verificar", headers=u["h"], json={"birth_date": "1990-01-01", "code": code, "declaration": True})
    assert r.status_code == 400 and "Pide uno nuevo" in r.json()["detail"]  # el código ya se gastó
    code = client.post("/cumplimiento/edad/codigo", headers=hip).json()["dev_code"]
    r = client.post("/cumplimiento/edad/verificar", headers=u["h"], json={"birth_date": "1990-01-01", "code": code, "declaration": False})
    assert r.status_code == 400
    r = client.post("/cumplimiento/edad/verificar", headers=u["h"], json={"birth_date": "1990-01-01", "code": code, "declaration": True})
    assert r.status_code == 200 and r.json()["required"] is False and r.json()["status"] == "passed"
    db = SessionLocal()
    try:
        check = db.query(AgeCheck).filter(AgeCheck.user_id == uid).one()
        assert check.status == "passed" and check.method == "fecha_nacimiento+sms+declaracion" and check.attempts == 1
        assert check.otp_verified_at and check.declaration_at and check.birth_date_confirmed_at
    finally:
        db.close()
    decl = [a for a in _acceptances(uid) if a.slug == "mayoria-de-edad"][-1]
    assert decl.method == "reaceptacion" and decl.context["tipo"] == "verificacion_reforzada"
    assert client.post("/foster-homes/register", headers=u["h"], json={"description": "Casa", "city": "Pruebas"}).status_code == 201

    # Otro reporte justo después de pasarla no vuelve a limitar la cuenta (periodo de gracia)
    _report_minor(uid, reporter_id)
    assert client.get("/users/me", headers=u["h"]).json()["age_check_required"] is False


def test_admin_can_request_and_clear_reinforced_check(client, make_user, admin):
    u = make_user("Edad por admin")
    uid = _user(u["email"]).id
    r = client.post(f"/admin/cumplimiento/edad/{uid}/solicitar", headers=admin["h"], json={"note": "Foto de perfil dudosa"})
    assert r.status_code == 200 and r.json()["status"] == "required"
    assert client.get("/users/me", headers=u["h"]).json()["age_check_required"] is True
    listed = client.get("/admin/cumplimiento/edad", headers=admin["h"]).json()
    assert any(c["user_id"] == uid and c["reason"] == "solicitud_admin" for c in listed)
    r = client.post(f"/admin/cumplimiento/edad/{uid}/liberar", headers=admin["h"], json={"note": "Revisado por teléfono"})
    assert r.status_code == 200 and r.json()["closed"] == 1
    assert client.get("/users/me", headers=u["h"]).json()["age_check_required"] is False
    db = SessionLocal()
    try:
        from app.models import AdminAuditLog

        actions = {a.action for a in db.query(AdminAuditLog).filter(AdminAuditLog.target_type == "user",
                                                                     AdminAuditLog.target_id == uid).all()}
        assert {"age_check.require", "age_check.clear"} <= actions
    finally:
        db.close()
    assert client.post(f"/admin/cumplimiento/edad/{uid}/solicitar", headers=u["h"], json={}).status_code == 403
