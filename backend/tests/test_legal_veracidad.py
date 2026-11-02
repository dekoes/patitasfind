"""Páginas legales contra el código (veracidad): lo que prometen las plantillas de app/legal/plantillas y lo que
hace la Plataforma.

- Bot de WhatsApp: aviso de privacidad al primer contacto (y a los 12 meses), aceptación PUBLICAR antes de crear el
  reporte, «Quiero adoptar» solo envía el enlace y sin perros en adopción entre las coincidencias.
- Correos: el pie dice quién los envía (razón social y domicilio), por qué y enlaza el centro legal.
- Ubicación de la cuenta solo con las alertas cercanas encendidas; apagarlas la borra (privacidad.html §8).
- Comprobante del donativo para quien dona, en la app y por correo (comunicaciones.html §2).
- Nueva versión vigente de Términos o Aviso sin aceptar: el servidor bloquea las acciones de escritura (terminos 29.2).
- Configuración de producción que contradice las páginas (donativos con la cuenta de la plataforma).
- scripts/render-legal.py: enlaces de versiones archivadas, DOMINIO y aviso previo de 30 días (si el script existe).
"""
import datetime
import importlib.util
import json
import re
import os
import shutil
import uuid
from pathlib import Path

import pytest

from app.config import Settings, settings
from app.database import SessionLocal
from app.models import BotInteraction, LegalDocument, LostReport, Notification, Refuge, User
from app.services import legal_acceptance as la
from app.services import matching, notify, whatsapp_bot

from tests.conftest import random_phone


def _db():
    return SessionLocal()


def _bot(phone, message=None, **extra):
    db = _db()
    try:
        return whatsapp_bot.process_message(db, phone, message, extra.get("media_url"), extra.get("latitude"),
                                            extra.get("longitude"))
    finally:
        db.close()


def _interaction(phone):
    db = _db()
    try:
        row = db.query(BotInteraction).filter(BotInteraction.phone == phone).first()
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


def _reports_from(phone):
    db = _db()
    try:
        return db.query(LostReport).filter(LostReport.contact_phone == phone).all()
    finally:
        db.close()


@pytest.fixture
def bot_env(monkeypatch):
    """Sin tareas en segundo plano ni descargas: las fotos se «guardan» y el matching devuelve lo que diga la prueba."""
    calls = []
    found = []
    monkeypatch.setattr(whatsapp_bot, "dispatch", lambda path, *a, **k: calls.append(path))
    monkeypatch.setattr(whatsapp_bot, "_store_media", lambda event: "/uploads/prueba-veracidad.jpg")
    monkeypatch.setattr(whatsapp_bot.facebook_groups, "trigger_zone_fetch", lambda state: None)
    monkeypatch.setattr(matching, "run_report_matching", lambda db, rid: list(found))
    return {"calls": calls, "found": found}


def _until_details(phone):
    _bot(phone, "hola")
    _bot(phone, "1")
    _bot(phone, None, media_url="https://ejemplo.mx/perro.jpg")
    _bot(phone, "listo")
    _bot(phone, "Gómez Palacio, Durango")


# --------------------------------------------------------------------------- bot de WhatsApp
def test_bot_first_contact_notice_once_and_after_12_months(client):
    phone = "52" + random_phone()
    first = _bot(phone, "hola")
    notice = first.get("notice") or ""
    # privacidad-simplificado.html §5.1 y privacidad-whatsapp.html §3
    assert "Usaremos tu número" in notice and "/app/legal/privacidad-whatsapp.html" in notice
    assert "BAJA" in notice and "ELIMINAR" in notice and "PERSONA" in notice
    inter = _interaction(phone)
    assert inter.data["notice_v"] == whatsapp_bot.NOTICE_VERSION and inter.data["notice_at"]
    # El menú enlaza el aviso y las reglas del bot
    assert "/app/legal/privacidad-whatsapp.html" in first["response"]
    second = _bot(phone, "menu")
    assert not second.get("notice")
    # A los 12 meses se vuelve a mostrar (y la versión guardada sobrevive al reinicio de la conversación)
    db = _db()
    try:
        row = db.query(BotInteraction).filter(BotInteraction.phone == phone).first()
        old = (datetime.datetime.utcnow() - datetime.timedelta(days=400)).isoformat()
        row.data = {**row.data, "notice_at": old}
        row.updated_at = datetime.datetime.utcnow() - datetime.timedelta(days=2)
        db.commit()
    finally:
        db.close()
    again = _bot(phone, "hola")
    assert again.get("notice") and _interaction(phone).data["notice_at"] != old


def test_bot_notice_sent_as_separate_message(client, monkeypatch):
    sent = []
    monkeypatch.setattr(whatsapp_bot.whatsapp_api, "send_text", lambda to, body: sent.append(("text", body)) or True)
    monkeypatch.setattr(whatsapp_bot.whatsapp_api, "send_buttons",
                        lambda to, body, buttons: sent.append(("buttons", body)) or True)
    db = _db()
    try:
        whatsapp_bot.process_event(db, {"phone": "52" + random_phone(), "text": "hola"}, send=True)
    finally:
        db.close()
    assert [kind for kind, _ in sent] == ["text", "buttons"]
    assert "Usaremos tu número" in sent[0][1] and len(sent[1][1]) <= 1024


def test_bot_adopt_only_sends_app_link(client):
    phone = "52" + random_phone()
    _bot(phone, "hola")
    r = _bot(phone, "3")
    # terminos.html 11.3 y privacidad-whatsapp.html §2: no muestra perros en adopción, solo el enlace a la app
    assert settings.public_url("/app/") in r["response"] and "?dog=" not in r["response"]
    assert r["stage"] != "adopt"
    r = _bot(phone, None, latitude=25.56, longitude=-103.41)  # compartir ubicación ya no lista perros
    assert "?dog=" not in r["response"]


def test_bot_requires_publish_consent_before_report_and_ai(client, bot_env):
    phone = "52" + random_phone()
    _until_details(phone)
    ask = _bot(phone, "Canela, collar rojo")
    assert ask["stage"] == "confirm_publish" and "PUBLICAR" in ask["response"] and "público" in ask["response"]
    assert {b["id"] for b in ask["buttons"]} == {"publish_yes", "publish_no"}
    assert _reports_from(phone) == [] and bot_env["calls"] == []  # sin aceptación: ni reporte, ni IA, ni alertas
    # Cualquier otra respuesta vuelve a preguntar
    again = _bot(phone, "qué pasa con mis datos")
    assert again["stage"] == "confirm_publish" and _reports_from(phone) == []
    # NO descarta: no se crea nada
    r = _bot(phone, "no")
    assert "no publicamos nada" in r["response"] and _reports_from(phone) == []
    assert "details" not in (_interaction(phone).data or {})


def test_bot_publish_creates_report_without_adoption_matches(client, bot_env):
    phone = "52" + random_phone()
    bot_env["found"].extend([
        {"type": "adoption", "id": 999001, "name": "Perro en adopción", "score": 95, "distance_km": 1.0},
        {"type": "found", "id": 999002, "name": "Perrito encontrado", "score": 90, "distance_km": 2.0},
    ])
    _until_details(phone)
    _bot(phone, "Canela, collar rojo")
    done = _bot(phone, "PUBLICAR")
    reports = _reports_from(phone)
    assert len(reports) == 1 and reports[0].source == "whatsapp" and "Canela" in reports[0].description
    assert bot_env["calls"] == ["app.tasks.notifications.notify_nearby_report"]
    # El bot no gestiona adopciones: entre las coincidencias no aparecen perros en adopción
    assert "Perrito encontrado" in done["response"] and "Perro en adopción" not in done["response"]
    assert "?dog=" not in done["response"]


# --------------------------------------------------------------------------- correos
def test_email_footer_identifies_operator_and_links_legal_center(monkeypatch):
    monkeypatch.setattr(settings, "emisor_nombre", "PATITAS FIND SA DE CV")
    monkeypatch.setattr(settings, "operator_address", "Calle <Uno> 1, CDMX")
    monkeypatch.setattr(settings, "operator_phone", "+525512345678")
    text, html_doc = notify.render_email("Hola", "Cuerpo", "/app/")
    legal = settings.public_url("/app/legal/")
    assert "operada por PATITAS FIND SA DE CV, Calle <Uno> 1, CDMX" in text and f"Centro legal: {legal}" in text
    assert "Recibes este correo porque" in text and "+525512345678" in text
    assert "Calle &lt;Uno&gt; 1" in html_doc and f'href="{legal}"' in html_doc and "<Uno>" not in html_doc


def test_auth_emails_carry_the_footer(client, monkeypatch):
    from app.routers import auth as auth_router

    monkeypatch.setattr(settings, "emisor_nombre", "PATITAS FIND SA DE CV")
    monkeypatch.setattr(settings, "operator_address", "Calle Uno 1, CDMX")
    sent = []
    monkeypatch.setattr(auth_router, "send_email", lambda to, subject, text, html: sent.append((text, html)) or True)
    auth_router.send_verification_email(1, "persona@pruebas.mx", "Persona")
    text, html_doc = sent[0]
    assert "operada por PATITAS FIND SA DE CV" in text and "/app/legal/" in text
    assert "Recibes este correo porque alguien pidió" in text and "/app/legal/" in html_doc


# --------------------------------------------------------------------------- ubicación (privacidad.html §8)
def _user_row(email):
    db = _db()
    try:
        return db.query(User).filter(User.email == email).first()
    finally:
        db.close()


def test_location_saved_only_with_nearby_alerts(client, make_user):
    u = make_user("Ubicación Prueba")
    r = client.patch("/users/me", headers=u["h"], json={"latitude": 19.43251, "longitude": -99.13321, "city": "CDMX"})
    assert r.status_code == 200 and r.json()["latitude"] is None and r.json()["city"] == "CDMX"
    assert client.patch("/cumplimiento/preferencias", headers=u["h"], json={"notify_nearby": True}).status_code == 200
    r = client.patch("/users/me", headers=u["h"], json={"latitude": 19.43251, "longitude": -99.13321})
    assert r.json()["latitude"] == 19.43251
    # Apagar las alertas borra la ubicación guardada
    assert client.patch("/cumplimiento/preferencias", headers=u["h"], json={"notify_nearby": False}).status_code == 200
    row = _user_row(u["email"])
    assert row.latitude is None and row.longitude is None
    prefs = client.get("/cumplimiento/preferencias", headers=u["h"]).json()
    assert prefs["has_location"] is False


# --------------------------------------------------------------------------- comprobante del donativo
def test_donor_gets_receipt_in_app_and_email(client, user, owner, monkeypatch):
    if settings.payments_enabled:
        pytest.skip("Con Mercado Pago real el donativo no se aprueba en la prueba")
    db = _db()
    try:
        o = db.query(User).filter(User.email == owner["email"]).first()
        ref = Refuge(user_id=o.id, name=f"Refugio Veracidad {uuid.uuid4().hex[:5]}", status="approved")
        db.add(ref)
        db.commit()
        refuge_id = ref.id
    finally:
        db.close()
    dispatched = []
    monkeypatch.setattr(notify, "_dispatch", lambda path, *args: dispatched.append((path, args)))
    monkeypatch.setattr(settings, "smtp_host", "smtp.pruebas.mx")
    d = client.post("/payments/donations", headers=user["h"],
                    json={"accepted_policy": True, "refuge_id": refuge_id, "amount": 75})
    assert d.status_code in (200, 201), d.text
    assert d.json()["status"] == "approved"
    donor = _user_row(user["email"])
    db = _db()
    try:
        notes = db.query(Notification).filter(Notification.user_id == donor.id,
                                              Notification.type == "donation_receipt").all()
    finally:
        db.close()
    assert len(notes) == 1
    body = notes[0].body
    assert "Folio: D-" in body and "$75.00 MXN" in body and "no es un CFDI" in body
    emails = [args for path, args in dispatched if path == "app.tasks.notifications.send_notification_email"]
    assert any(args[0] == user["email"] and "Recibimos tu donativo" in args[1] for args in emails)


# --------------------------------------------------------------------------- reaceptación (terminos.html 29.2)
def test_write_actions_blocked_until_current_terms_are_accepted(client):
    db = _db()
    try:
        if la.current_document(db, la.TERMS_SLUG) is None or la.current_document(db, la.PRIVACY_SLUG) is None:
            pytest.skip("El registro de versiones legales no está sincronizado")
        user = User(email=f"sin-aceptar-{uuid.uuid4().hex[:8]}@pruebas.mx", full_name="Sin Aceptar",
                    hashed_password=None, phone="+52" + random_phone(), phone_verified=True,
                    birth_date=datetime.date(1990, 1, 1), adult_declared_at=datetime.datetime.utcnow())
        db.add(user)
        db.commit()
        uid = user.id
        assert set(la.blocking_pending(db, user)) == {la.TERMS_SLUG, la.PRIVACY_SLUG}
        from app.routers.auth import create_session_token

        token = create_session_token(user)["access_token"]
    finally:
        db.close()
    h = {"Authorization": f"Bearer {token}"}
    r = client.post("/lost-reports", headers=h, json={"dog_name": "Bloqueado", "report_type": "x"})
    assert r.status_code == 403 and r.json()["code"] == "legal_acceptance_required"
    # Aceptar la versión vigente desbloquea (la petición inválida ya llega a la validación: 400, no 403)
    pend = client.get("/cumplimiento/pendientes", headers=h).json()["pendientes"]
    for item in [p for p in pend if p["blocking"]]:
        ok = client.post("/cumplimiento/aceptaciones", headers=h,
                         json={"slug": item["slug"], "version": item["version"], "sha256": item["sha256"]})
        assert ok.status_code == 200, ok.text
    db = _db()
    try:
        assert la.blocking_pending(db, db.get(User, uid)) == []
    finally:
        db.close()
    r = client.post("/lost-reports", headers=h, json={"dog_name": "Bloqueado", "report_type": "x"})
    assert r.status_code == 400


def test_sync_dry_run_reports_short_notice_without_writing():
    slug = f"prueba-{uuid.uuid4().hex[:8]}"
    now = datetime.datetime.utcnow()
    base = {"slug": slug, "title": "Documento de prueba", "requires_reacceptance": True, "summary": "x",
            "url": f"/app/legal/{slug}.html"}
    db = _db()
    try:
        old = LegalDocument(**base, version="2026-01-01", effective_at=None, published_at=now - datetime.timedelta(days=9),
                            sha256=uuid.uuid4().hex * 2)
        db.add(old)
        db.commit()
        entries = [{**base, "version": "2026-10-18", "effective_at": now + datetime.timedelta(days=5),
                    "sha256": uuid.uuid4().hex * 2}]
        preview = la.sync_documents(db, entries, dry_run=True)
        assert preview["warnings"] and "30" in preview["warnings"][0]
        assert db.query(LegalDocument).filter(LegalDocument.slug == slug).count() == 1  # nada se escribió
    finally:
        db.query(LegalDocument).filter(LegalDocument.slug == slug).delete(synchronize_session=False)
        db.commit()
        db.close()


# --------------------------------------------------------------------------- configuración de producción
def test_production_rejects_platform_donation_fallback(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("DONATIONS_", "ENVIRONMENT", "SECRET_KEY", "DATABASE_URL", "PUBLIC_BASE_URL", "CORS_")):
            monkeypatch.delenv(key, raising=False)
    base = dict(
        _env_file=None, environment="production", secret_key="s" * 64,
        database_url="postgresql+psycopg2://patitasfind:Clave-Larga-De-Prod@postgres:5432/patitasfind",
        public_base_url="https://guauwoow.com", cors_origins="https://guauwoow.com",
        sms_provider="smsmasivos", smsmasivos_api_key="llave", smtp_host="smtp.ejemplo.mx",
        smtp_from="GuauWoow <no-reply@guauwoow.com>",
        private_files_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    with pytest.raises(Exception) as exc:
        Settings(**base, donations_fallback_to_platform_account=True)
    assert "DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT" in str(exc.value)
    assert Settings(**base, donations_fallback_to_platform_account=False).effective_donations_fallback is False


# --------------------------------------------------------------------------- scripts/render-legal.py
REPO = Path(os.environ.get("PATITASFIND_REPO") or Path(__file__).resolve().parents[2])
RENDER_SCRIPT = REPO / "scripts" / "render-legal.py"
needs_script = pytest.mark.skipif(not RENDER_SCRIPT.exists(), reason="scripts/render-legal.py no está disponible")


@pytest.fixture(scope="module")
def rl():
    spec = importlib.util.spec_from_file_location("render_legal_veracidad", RENDER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mini_repo(tmp_path, monkeypatch):
    for name in ("DOMAIN", "EMISOR_NOMBRE", "OPERATOR_ADDRESS", "DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT",
                 "LEGAL_NOTICE_DAYS", "LEGAL_TERMS_VERSION", "LEGAL_PRIVACY_VERSION"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "repo"
    legal = root / "app" / "legal"
    shutil.copytree(REPO / "app" / "legal" / "plantillas", legal / "plantillas")
    shutil.copy(REPO / "app" / "legal" / "datos-legales.example.json", legal)
    shutil.copy(REPO / "app" / "legal" / "legal.css", legal)
    (legal / "js").mkdir()
    for name in ("cookies", "solicitudes", "reportes", "transparencia", "conservacion", "estado", "historial"):
        (legal / "js" / f"{name}.js").write_text("", encoding="utf-8")
    (root / "app" / "landing.html").write_text("<!doctype html><title>x</title>\n", encoding="utf-8")
    (root / "backend" / "app").mkdir(parents=True)
    shutil.copy(REPO / "backend" / "app" / "config.py", root / "backend" / "app" / "config.py")
    (legal / "datos-legales.json").write_text("{}", encoding="utf-8")
    return root


@needs_script
def test_archived_pages_are_link_checked(rl, mini_repo, capsys):
    legal = mini_repo / "app" / "legal"
    assert rl.main(["--root", str(mini_repo)]) == 0
    # Una versión archivada (texto fijo) que enlaza un ancla que ya no existe en la página vigente
    archive = legal / "terminos-2026-01-01.html"
    archive.write_text('<!doctype html><title>Términos · GuauWoow</title>\n'
                       '<p><a href="privacidad.html#ancla-que-no-existe">Aviso</a></p>\n', encoding="utf-8")
    versiones = json.loads((legal / "versiones.json").read_text(encoding="utf-8"))
    versiones.append({"slug": "terminos", "title": "Términos", "version": "2026-01-01", "effective_at": None,
                      "sha256": __import__("hashlib").sha256(archive.read_text(encoding="utf-8").encode()).hexdigest(),
                      "requires_reacceptance": True, "summary": "x", "url": "/app/legal/terminos-2026-01-01.html"})
    (legal / "versiones.json").write_text(json.dumps(versiones, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert rl.main(["--root", str(mini_repo)]) == 0
    capsys.readouterr()
    assert rl.main(["--check-generated", "--root", str(mini_repo)]) == 1
    out = capsys.readouterr().out
    assert "terminos-2026-01-01.html (versión archivada)" in out and "#ancla-que-no-existe" in out


@needs_script
def test_check_requires_domain_identity_and_30_days_notice(rl, mini_repo, capsys):
    legal = mini_repo / "app" / "legal"
    assert rl.main(["--root", str(mini_repo)]) == 0
    # Simula una versión anterior de terminos ya publicada: la nueva pide 30 días de aviso
    versiones = json.loads((legal / "versiones.json").read_text(encoding="utf-8"))
    versiones.append({"slug": "terminos", "title": "Términos", "version": "2026-01-01", "effective_at": "2026-01-01",
                      "sha256": "0" * 64, "requires_reacceptance": True, "summary": "x",
                      "url": "/app/legal/terminos-2026-01-01.html"})
    (legal / "versiones.json").write_text(json.dumps(versiones, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    datos = {"FECHA_DE_ENTRADA_EN_VIGOR": "2026-10-20", "RAZON_SOCIAL": "Patitas, S.A. de C.V."}
    (legal / "datos-legales.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    (mini_repo / ".env").write_text("DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT=true\n", encoding="utf-8")
    capsys.readouterr()
    assert rl.main(["--check", "--root", str(mini_repo), "--hoy", "2026-10-18"]) == 1
    out = capsys.readouterr().out
    assert "DOMINIO está vacío" in out
    assert "terminos.html versión" in out and "30 días de aviso previo" in out
    assert "RAZON_SOCIAL dice" in out and "EMISOR_NOMBRE" in out
    assert "DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT=true" in out


@needs_script
def test_repo_privacidad_keeps_archived_anchor_alias(rl):
    text = (REPO / "app" / "legal" / "privacidad.html").read_text(encoding="utf-8")
    assert 'id="secundarias"' in text  # terminos-2026-10-16.html enlaza privacidad.html#secundarias
    assert "[PLAZO DE CONSERVACIÓN DE RESPALDOS]" not in text
    # Copia local: el marcador sin llenar o el plazo ya calculado desde la configuración de respaldos
    assert re.search(r"Copia local (<span class=\"ph\">\[PLAZO LOCAL DE RESPALDOS\]</span>|\d+ días)", text)
