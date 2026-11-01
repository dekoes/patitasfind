"""Moderación (reportes de contenido, ocultar y suspender), alertas de perritos cercanos, avisos de
coincidencias y endurecimiento del webhook de WhatsApp (firma, 404 sin configurar, ventana de 24 h)."""
import hashlib
import hmac
import json
import random
import uuid

from app.config import settings
from app.database import SessionLocal
from app.models import AdminAuditLog, ContentReport, LostReport, Message, Notification, Refuge, User
from app.routers import lost_reports as lost_reports_router
from app.routers import whatsapp as whatsapp_router
from app.services import matching, notify, whatsapp_api, whatsapp_bot
from app.tasks import notifications as notif_tasks
from tests.conftest import random_ip


# --------------------------------------------------------------------------- utilidades
def _set(email, **fields) -> int:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        for k, v in fields.items():
            setattr(u, k, v)
        db.commit()
        return u.id
    finally:
        db.close()


def _uid(u) -> int:
    return u.get("id") or _set(u["email"])


def _staff(make_user, role="admin"):
    u = make_user(f"Moderación {role}", verify=False)
    u["id"] = _set(u["email"], role=role)
    return u


def _dog(client, owner, **extra):
    r = client.post("/dogs", headers=owner["h"], json={"name": f"Perro {uuid.uuid4().hex[:6]}", "size": "Mediano", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _report(client, u, target_type, target_id, reason="fraude", **extra):
    return client.post("/reports", headers=u["h"], json={"target_type": target_type, "target_id": target_id,
                                                         "reason": reason, **extra})


def _notifications(user_id, kind=None):
    db = SessionLocal()
    try:
        q = db.query(Notification).filter(Notification.user_id == user_id)
        if kind:
            q = q.filter(Notification.type == kind)
        return q.order_by(Notification.id).all()
    finally:
        db.close()


def _login(client, u):
    return client.post("/auth/login", data={"username": u["email"], "password": u["password"]},
                       headers={"X-Real-IP": random_ip()})


# --------------------------------------------------------------------------- reportes de contenido
def test_report_create_dedupe_and_rules(client, user, owner, unverified):
    dog = _dog(client, owner)
    body = {"target_type": "dog", "target_id": dog["id"], "reason": "fraude", "details": "Pide dinero por adelantado"}
    r = client.post("/reports", headers=user["h"], json=body)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "open" and r.json()["id"]
    # Mismo usuario, mismo contenido y reporte abierto: devuelve el existente
    again = client.post("/reports", headers=user["h"], json={**body, "reason": "spam"})
    assert again.status_code == 200 and again.json()["id"] == r.json()["id"]

    assert client.post("/reports", headers=owner["h"], json=body).status_code == 400  # su propio contenido
    assert client.post("/reports", headers=user["h"], json={**body, "reason": "no-existe"}).status_code == 422
    assert client.post("/reports", headers=user["h"], json={**body, "target_type": "foto"}).status_code == 422
    assert client.post("/reports", headers=user["h"], json={**body, "details": "x" * 1001}).status_code == 422
    assert client.post("/reports", headers=user["h"], json={**body, "target_id": 987654321}).status_code == 404
    assert client.post("/reports", json=body).status_code == 401
    r = client.post("/reports", headers=unverified["h"], json=body)
    assert r.status_code == 403 and r.json()["code"] == "phone_verification_required"


def test_report_rate_limit(client, user, owner):
    uid = _uid(user)
    db = SessionLocal()
    try:
        for i in range(10):
            db.add(ContentReport(reporter_id=uid, target_type="user", target_id=900000000 + i, reason="spam",
                                 status="dismissed"))
        db.commit()
    finally:
        db.close()
    dog = _dog(client, owner)
    r = _report(client, user, "dog", dog["id"])
    assert r.status_code == 429
    assert "reportes" in r.json()["detail"]


def test_admin_resolve_hide_content_hides_dog(client, make_user, user, owner):
    admin = _staff(make_user)
    city = f"Ciudad Moderación {uuid.uuid4().hex[:6]}"
    dog = _dog(client, owner, city=city)
    assert any(d["id"] == dog["id"] for d in client.get("/dogs/featured", params={"city": city}).json())

    reporters = [user, make_user("Reportante 2"), make_user("Reportante 3")]
    ids = []
    for u in reporters:
        r = _report(client, u, "dog", dog["id"], reason="maltrato")
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    # Al tercer reporte abierto se avisa a los admins
    alerts = [n for n in _notifications(admin["id"], "moderation_alert") if (n.data or {}).get("target_id") == dog["id"]]
    assert len(alerts) == 1 and alerts[0].data["target_type"] == "dog"

    assert client.get("/admin/reports", headers=user["h"]).status_code == 403
    listing = client.get("/admin/reports", headers=admin["h"], params={"status": "open", "target_type": "dog"}).json()
    row = next(x for x in listing if x["id"] == ids[0])
    assert row["target"]["title"] == dog["name"] and row["target"]["is_hidden"] is False
    assert row["open_reports_for_target"] == 3 and row["reporter"]["id"] == _uid(user)
    assert client.get("/admin/reports", headers=admin["h"], params={"status": "raro"}).status_code == 400

    r = client.patch(f"/admin/reports/{ids[0]}", headers=admin["h"],
                     json={"status": "dismissed", "action": "hide_content"})
    assert r.status_code == 400
    r = client.patch(f"/admin/reports/{ids[0]}", headers=admin["h"],
                     json={"status": "resolved", "action": "hide_content", "notes": "Fotos de maltrato"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "resolved" and out["action"] == "hide_content" and out["admin_notes"] == "Fotos de maltrato"
    assert out["target"]["is_hidden"] is True and out["resolved_by"]["id"] == admin["id"]
    assert client.patch(f"/admin/reports/{ids[0]}", headers=admin["h"], json={"status": "dismissed"}).status_code == 400
    # Los otros reportes del mismo contenido quedaron resueltos
    still_open = client.get("/admin/reports", headers=admin["h"], params={"status": "open", "target_type": "dog"}).json()
    assert not [x for x in still_open if x["target_id"] == dog["id"]]

    # El público ya no lo ve; el dueño y los admins sí
    assert client.get(f"/dogs/{dog['id']}").status_code == 404
    assert client.get(f"/dogs/{dog['id']}", headers=user["h"]).status_code == 404
    assert not any(d["id"] == dog["id"] for d in client.get("/dogs/featured", params={"city": city}).json())
    assert not any(d["id"] == dog["id"] for d in client.get("/dogs/discover", headers=user["h"], params={"city": city}).json())
    mine = client.get(f"/dogs/{dog['id']}", headers=owner["h"])
    assert mine.status_code == 200 and mine.json()["is_hidden"] is True
    assert client.get(f"/dogs/{dog['id']}", headers=admin["h"]).status_code == 200
    assert any(d["id"] == dog["id"] for d in client.get("/dogs/me", headers=owner["h"]).json())
    # Ya no se puede reportar lo que no se ve
    assert _report(client, make_user("Otro"), "dog", dog["id"]).status_code == 404

    # Avisos: al dueño (contenido oculto) y a quienes reportaron
    assert _notifications(_uid(owner), "content_hidden")
    for u in reporters:
        assert _notifications(_uid(u), "report_resolved")
    db = SessionLocal()
    try:
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "content.hide", AdminAuditLog.target_type == "dog",
                                              AdminAuditLog.target_id == dog["id"]).count() == 1
    finally:
        db.close()

    # Un admin lo puede volver a mostrar
    r = client.patch(f"/admin/content/dog/{dog['id']}", headers=admin["h"], json={"hidden": False})
    assert r.status_code == 200 and r.json()["target"]["is_hidden"] is False
    assert client.get(f"/dogs/{dog['id']}").status_code == 200


def test_hidden_lost_report_and_message_moderation(client, make_user, user, owner):
    admin = _staff(make_user)
    rep = client.post("/lost-reports", headers=owner["h"], json={"dog_name": "Canela", "report_type": "lost"}).json()
    conv = client.post(f"/lost-reports/{rep['id']}/contact", headers=user["h"]).json()
    msg = client.post(f"/conversations/{conv['id']}/messages", headers=user["h"], json={"content": "Mándame un depósito"})
    assert msg.status_code == 201, msg.text
    stranger = make_user("Ajena")
    assert _report(client, stranger, "message", msg.json()["id"]).status_code == 404  # no participa en el chat
    r = _report(client, owner, "message", msg.json()["id"], reason="fraude")
    assert r.status_code == 201
    out = client.patch(f"/admin/reports/{r.json()['id']}", headers=admin["h"],
                       json={"status": "resolved", "action": "hide_content"})
    assert out.status_code == 200, out.text
    db = SessionLocal()
    try:
        assert db.query(Message).filter(Message.id == msg.json()["id"]).first().content == "Mensaje ocultado por moderación."
        log = db.query(AdminAuditLog).filter(AdminAuditLog.action == "content.hide", AdminAuditLog.target_type == "message",
                                             AdminAuditLog.target_id == msg.json()["id"]).first()
        assert log.details["original_content"] == "Mándame un depósito"
        db.query(LostReport).filter(LostReport.id == rep["id"]).update({LostReport.is_hidden: True})
        db.commit()
    finally:
        db.close()
    # Reporte oculto: fuera de listados y detalle para el público; quien lo creó sí lo ve
    assert client.get(f"/lost-reports/{rep['id']}").status_code == 404
    assert client.get(f"/lost-reports/{rep['id']}/matches").status_code == 404
    assert rep["id"] not in [x["id"] for x in client.get("/lost-reports", params={"limit": 500}).json()]
    assert client.get(f"/lost-reports/{rep['id']}", headers=owner["h"]).status_code == 200
    assert rep["id"] in [x["id"] for x in client.get("/lost-reports/me", headers=owner["h"]).json()]


def test_suspend_user_blocks_login_and_hides_content(client, make_user, user):
    admin = _staff(make_user)
    bad = make_user("Estafador")
    bad_id = _uid(bad)
    dog = _dog(client, bad)
    rep = client.post("/lost-reports", headers=bad["h"], json={"dog_name": "Falso", "report_type": "found"}).json()
    report = _report(client, user, "user", bad_id, reason="fraude").json()

    r = client.patch(f"/admin/reports/{report['id']}", headers=admin["h"],
                     json={"status": "resolved", "action": "hide_content"})
    assert r.status_code == 400  # a un usuario no se le "oculta": se le suspende
    r = client.patch(f"/admin/reports/{report['id']}", headers=admin["h"],
                     json={"status": "resolved", "action": "suspend_user", "notes": "Pedía depósitos"})
    assert r.status_code == 200, r.text
    assert r.json()["target"]["is_active"] is False

    login = _login(client, bad)
    assert login.status_code in (401, 403) and "desactivada" in login.json()["detail"]
    assert client.get("/users/me", headers=bad["h"]).status_code == 401  # su sesión anterior ya no sirve
    assert client.get(f"/dogs/{dog['id']}").status_code == 404
    assert client.get(f"/lost-reports/{rep['id']}").status_code == 404
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == bad_id).first()
        assert u.is_active is False and u.suspended_at is not None
        log = db.query(AdminAuditLog).filter(AdminAuditLog.action == "user.suspend", AdminAuditLog.target_id == bad_id).first()
        assert dog["id"] in log.details["hidden_dogs"] and rep["id"] in log.details["hidden_lost_reports"]
    finally:
        db.close()

    # Un admin no puede suspender a otro admin desde un reporte
    other_admin = _staff(make_user)
    rr = _report(client, user, "user", other_admin["id"], reason="spam").json()
    assert client.patch(f"/admin/reports/{rr['id']}", headers=admin["h"],
                        json={"status": "resolved", "action": "suspend_user"}).status_code == 403

    # Reactivar devuelve la cuenta y lo que se ocultó al suspenderla
    r = client.post(f"/admin/users/{bad_id}/unsuspend", headers=admin["h"])
    assert r.status_code == 200 and dog["id"] in r.json()["restored"]["hidden_dogs"]
    assert _login(client, bad).status_code == 200
    assert client.get(f"/dogs/{dog['id']}").status_code == 200


# --------------------------------------------------------------------------- alertas cercanas
def _spot():
    """Coordenadas aleatorias en el norte de México (lejos de los datos demo de la CDMX)."""
    return round(random.uniform(25.0, 29.0), 5), round(random.uniform(-109.0, -101.0), 5)


def _km_north(lat, km):
    return lat + km / 111.0


def test_nearby_alert_task_only_opted_in_users_in_range(client, make_user):
    lat, lon = _spot()
    near = make_user("Vecina")
    opted_out = make_user("Sin avisos")
    far = make_user("Lejana")
    reporter = make_user("Dueño")
    partner = make_user("Refugio cercano")
    for u, dlat in ((near, 1.0), (opted_out, 0.5), (far, 20.0), (reporter, 0.0), (partner, 10.0)):
        r = client.patch("/users/me", headers=u["h"], json={"latitude": _km_north(lat, dlat), "longitude": lon,
                                                            "notify_nearby": True})  # apagadas hasta activarlas
        assert r.status_code == 200 and r.json()["notify_nearby"] is True
    r = client.patch("/users/me", headers=opted_out["h"], json={"notify_nearby": False})
    assert r.status_code == 200 and r.json()["notify_nearby"] is False
    assert client.get("/users/me", headers=opted_out["h"]).json()["notify_nearby"] is False

    db = SessionLocal()
    try:
        db.add(Refuge(user_id=_uid(partner), name="Refugio Norte", city="Pruebas", status="approved"))
        report = LostReport(reporter_id=_uid(reporter), dog_name="Firulais", report_type="lost", status="active",
                            source="app", latitude=lat, longitude=lon, city="Pruebas", photos=[])
        db.add(report)
        db.commit()
        rid = report.id
    finally:
        db.close()

    # ">= 2": en la base de desarrollo compartida pueden quedar personas de corridas anteriores dentro del radio;
    # lo que importa se revisa abajo persona por persona
    assert notif_tasks.notify_nearby_report(rid) >= 2
    alert = _notifications(_uid(near), "nearby_alert")
    assert len(alert) == 1 and alert[0].data["report_id"] == rid and alert[0].data["distance_km"] == 1.0
    assert "Firulais" in alert[0].body and "1.0 km" in alert[0].body
    assert _notifications(_uid(partner), "nearby_alert")  # refugio aprobado a 10 km (radio de 15 km)
    for u in (opted_out, far, reporter):
        assert not _notifications(_uid(u), "nearby_alert")
    # La misma alerta no se manda dos veces
    assert notif_tasks.notify_nearby_report(rid) == 0


def test_nearby_alert_daily_cap_and_hidden(client, make_user, monkeypatch):
    lat, lon = _spot()
    near = make_user("Vecino tope")
    client.patch("/users/me", headers=near["h"], json={"latitude": lat, "longitude": lon, "notify_nearby": True})
    monkeypatch.setattr(settings, "nearby_alert_daily_cap", 1)
    db = SessionLocal()
    try:
        ids = []
        for hidden in (False, False, True):
            r = LostReport(reporter_id=None, dog_name="Perrito encontrado", report_type="found", status="active",
                           source="whatsapp", latitude=_km_north(lat, 0.3), longitude=lon, photos=[], is_hidden=hidden)
            db.add(r)
            db.flush()
            ids.append(r.id)
        db.commit()
    finally:
        db.close()
    assert notif_tasks.notify_nearby_report(ids[0]) >= 1
    notif_tasks.notify_nearby_report(ids[1])  # ya llegó al tope diario
    assert notif_tasks.notify_nearby_report(ids[2]) == 0  # oculto por moderación
    alerts = _notifications(_uid(near), "nearby_alert")
    assert len(alerts) == 1 and alerts[0].data["report_type"] == "found"
    assert alerts[0].title == "🐾 Encontraron un perrito cerca de ti"


def test_report_creation_dispatches_nearby_alert(client, user, monkeypatch):
    calls = []
    monkeypatch.setattr(lost_reports_router, "dispatch", lambda path, *a, **k: calls.append((path, a)))
    r = client.post("/lost-reports", headers=user["h"], json={"dog_name": "Lola", "report_type": "lost",
                                                              "latitude": 25.5, "longitude": -103.4})
    assert r.status_code == 201
    assert ("app.tasks.notifications.notify_nearby_report", (r.json()["id"],)) in calls


def test_whatsapp_bot_report_dispatches_nearby_alert(client, monkeypatch):
    calls = []
    monkeypatch.setattr(whatsapp_bot, "dispatch", lambda path, *a, **k: calls.append((path, a)))
    monkeypatch.setattr(whatsapp_bot, "_store_media", lambda event: "/uploads/prueba-bot.jpg")
    monkeypatch.setattr(matching, "run_report_matching", lambda db, rid: [])
    phone = "52155" + "".join(random.choice("0123456789") for _ in range(8))
    sim = lambda **kw: client.post("/whatsapp/webhook", json={"phone": phone, **kw}).json()
    sim(message="hola")
    sim(message="1")
    sim(message=None, media_url="https://ejemplo.mx/perro.jpg")
    sim(message="listo")
    sim(message="Torreón, Coahuila")
    ask = sim(message="Max, collar rojo")
    # Antes de publicar, el bot pide aceptar (privacidad-whatsapp.html §4): sin PUBLICAR no hay reporte ni alertas
    assert ask["stage"] == "confirm_publish" and calls == [], ask
    done = sim(message="PUBLICAR")
    assert done["stage"] == "done", done
    assert [p for p, _ in calls] == ["app.tasks.notifications.notify_nearby_report"]


# --------------------------------------------------------------------------- avisos de coincidencias (F3/F4)
def test_match_notification_email_and_whatsapp(client, make_user, monkeypatch):
    u = make_user("Busco a mi perro")
    # Las plantillas de WhatsApp solo van a quien activó «Avisos por WhatsApp» (K-PREF)
    assert client.patch("/cumplimiento/preferencias", headers=u["h"], json={"whatsapp_alerts": True}).status_code == 200
    uid = _uid(u)
    db = SessionLocal()
    try:
        mine = LostReport(reporter_id=uid, dog_name="Toby", report_type="lost", status="active", source="app", photos=[])
        theirs = LostReport(reporter_id=None, dog_name="Perrito encontrado", report_type="found", status="active",
                            source="whatsapp", photos=[])
        db.add_all([mine, theirs])
        db.commit()
        dispatched = []
        monkeypatch.setattr(notify, "_dispatch", lambda path, *args: dispatched.append((path, args)))
        monkeypatch.setattr(settings, "smtp_host", "smtp.pruebas.mx")
        monkeypatch.setattr(settings, "whatsapp_access_token", "EAAG-prueba")
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "123")
        monkeypatch.setattr(settings, "whatsapp_template_match", "patitas_coincidencia")
        n = notify.notify_report_match(db, mine, theirs, 82, f"lr:{mine.id}:{theirs.id}")
        assert n.type == "possible_match" and n.data["dedupe"] == f"lr:{mine.id}:{theirs.id}" and n.data["report_id"] == mine.id
        paths = [p for p, _ in dispatched]
        assert paths == ["app.tasks.notifications.send_notification_email",
                         "app.tasks.notifications.send_whatsapp_notification"]
        email_args = dispatched[0][1]
        assert email_args[0] == u["email"] and email_args[3] == f"/app/?report={theirs.id}"
        wa_args = dispatched[1][1]
        assert wa_args[0] == u["phone"] and wa_args[2] == "patitas_coincidencia"
        assert wa_args[3] == [f"Toby (reporte #{mine.id})", settings.public_url(f"/app/?report={theirs.id}")]
    finally:
        db.close()


def test_render_email_escapes_user_content():
    text, html_doc = notify.render_email("Hola <b>", "Firulais <script>alert(1)</script>\nSegunda línea", "/app/?report=5")
    assert "<script>" not in html_doc and "&lt;script&gt;" in html_doc and "Hola &lt;b&gt;" in html_doc
    assert "<br>" in html_doc and settings.public_url("/app/?report=5") in text
    assert f'href="{settings.public_url("/app/?report=5")}"' in html_doc


# --------------------------------------------------------------------------- WhatsApp: ventana de 24 h y plantillas
def test_whatsapp_template_outside_window_text_inside(monkeypatch):
    sent = []
    monkeypatch.setattr(whatsapp_api, "_post_message", lambda payload: sent.append(payload) or True)
    monkeypatch.setattr(matching, "is_whatsapp_opted_out", lambda phone: False)
    phone = "+5255" + "".join(random.choice("0123456789") for _ in range(8))
    assert notify.send_whatsapp(phone, "Hola", None) is None and sent == []  # sin plantilla y fuera de la ventana
    assert notify.send_whatsapp(phone, "Hola", "patitas_alerta", ["se perdió Max\na 1 km", "https://x.mx/r"]) == "template"
    tpl = sent[-1]
    assert tpl["type"] == "template" and tpl["to"] == phone.lstrip("+")
    assert tpl["template"]["name"] == "patitas_alerta" and tpl["template"]["language"]["code"] == "es_MX"
    params = tpl["template"]["components"][0]["parameters"]
    assert [p["text"] for p in params] == ["se perdió Max a 1 km", "https://x.mx/r"]  # sin saltos de línea

    # Si la persona nos escribió (webhook), dentro de 24 h se manda texto libre
    whatsapp_api.mark_inbound("521" + phone[-10:])
    if whatsapp_api.in_service_window(phone):  # requiere Redis
        assert notify.send_whatsapp(phone, "Hola de nuevo", "patitas_alerta", []) == "text"
        assert sent[-1]["type"] == "text"
    monkeypatch.setattr(matching, "is_whatsapp_opted_out", lambda phone: True)
    assert notify.send_whatsapp(phone, "Hola", "patitas_alerta", []) is None  # BAJA/STOP


# --------------------------------------------------------------------------- webhook de WhatsApp
META = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
    "contacts": [{"profile": {"name": "Pruebas"}, "wa_id": "5210000000002"}],
    "messages": [{"from": "5210000000002", "id": "wamid.MOD", "type": "text", "text": {"body": "hola"}}]}}]}]}


def _signed(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_whatsapp_webhook_404_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "whatsapp_access_token", None)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", None)
    assert client.post("/whatsapp/webhook", json=META).status_code == 404
    assert client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x",
                                                   "hub.challenge": "1"}).status_code == 404
    # En staging tampoco existe sin llaves
    monkeypatch.setattr(settings, "environment", "staging")
    assert client.post("/whatsapp/webhook", json=META).status_code == 404
    # El simulador fuera de development es solo para admins
    assert client.post("/whatsapp/webhook", json={"phone": "sim-x", "message": "hola"}).status_code == 403


def test_whatsapp_webhook_requires_signature_in_production(client, monkeypatch):
    calls = []
    monkeypatch.setattr(whatsapp_router, "dispatch", lambda path, *a, **k: calls.append(path))
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "whatsapp_access_token", "EAAG-prueba")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "123")
    raw = json.dumps(META).encode()
    headers = {"Content-Type": "application/json"}

    # Sin WHATSAPP_APP_SECRET en producción se rechaza todo, aunque traiga firma
    monkeypatch.setattr(settings, "whatsapp_app_secret", None)
    assert client.post("/whatsapp/webhook", content=raw, headers=headers).status_code == 403
    assert client.post("/whatsapp/webhook", content=raw,
                       headers={**headers, "X-Hub-Signature-256": _signed("x", raw)}).status_code == 403

    monkeypatch.setattr(settings, "whatsapp_app_secret", "secreto-de-meta")
    assert client.post("/whatsapp/webhook", content=raw, headers=headers).status_code == 403
    assert client.post("/whatsapp/webhook", content=raw,
                       headers={**headers, "X-Hub-Signature-256": _signed("otro", raw)}).status_code == 403
    # Una firma válida de un cuerpo distinto tampoco sirve
    assert client.post("/whatsapp/webhook", content=raw + b" ",
                       headers={**headers, "X-Hub-Signature-256": _signed("secreto-de-meta", raw)}).status_code == 403
    ok = client.post("/whatsapp/webhook", content=raw,
                     headers={**headers, "X-Hub-Signature-256": _signed("secreto-de-meta", raw)})
    assert ok.status_code == 200 and ok.json()["events"] == 1
    assert calls == ["app.tasks.whatsapp.process_whatsapp_event"]

    # Verificación de Meta: el token de desarrollo nunca sirve en producción
    params = {"hub.mode": "subscribe", "hub.challenge": "777"}
    monkeypatch.setattr(settings, "whatsapp_verify_token", "patitasfind-dev-token")
    assert client.get("/whatsapp/webhook", params={**params, "hub.verify_token": "patitasfind-dev-token"}).status_code == 403
    monkeypatch.setattr(settings, "whatsapp_verify_token", "token-largo-de-produccion")
    good = client.get("/whatsapp/webhook", params={**params, "hub.verify_token": "token-largo-de-produccion"})
    assert good.status_code == 200 and good.text == "777"
    assert client.get("/whatsapp/webhook", params={**params, "hub.verify_token": "otro"}).status_code == 403
