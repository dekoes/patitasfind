"""Centro de solicitudes (K-SOLIC) e informe de transparencia (K-TRANSP).

Solicitudes con y sin cuenta, folio PF-AAAA-NNNNN, confirmación por correo, plazos en días hábiles de México
(LFPDPPP art. 31; quejas según la política), requerimiento único, ampliación única, identificación que se borra,
efectos (descarga de «Mis datos», cancelación de la cuenta, revocación y listado de exclusión, retiro de una
publicación importada en menos de 72 h), cola del equipo con semáforo y tareas programadas. Transparencia: dinero
por Refugio con la regla de umbral y el consentimiento de personas físicas, secciones del informe y detalle por
Refugio. Ningún correo sale: se reemplaza el envío.
"""
import datetime
import uuid
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from app.database import SessionLocal
from app.models import (
    ComplianceRequest, ConsentRecord, ContentReport, Donation, LostReport, Notification, Order, Refuge,
    RefugeFiscalProfile, User,
)
from app.routers import cumplimiento_transparencia as tr
from app.routers.documents import private_document_path
from app.services import solicitudes as sol
from app.services import statements
from app.services.order_flow import add_business_days
from tests.conftest import make_jpeg, random_ip

API = "/cumplimiento/solicitudes"
ADMIN = "/admin/cumplimiento/solicitudes"


# --------------------------------------------------------------------------- utilidades
@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    """Captura los correos de las solicitudes y apaga los demás canales externos."""
    sent = []
    monkeypatch.setattr(sol, "_send_email", lambda to, title, body, url=None: sent.append(
        {"to": to, "title": title, "body": body, "url": url}))
    monkeypatch.setattr("app.services.notify._dispatch", lambda *a, **k: None)
    return sent


def _ip():
    return {"X-Real-IP": random_ip()}


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
    u = make_user("Equipo Solicitudes", verify=False)
    u["id"] = _set_user(u["email"], role="admin")
    return u


def _req(folio) -> ComplianceRequest:
    db = SessionLocal()
    try:
        r = db.query(ComplianceRequest).filter(ComplianceRequest.folio == folio).first()
        db.expunge(r)
        return r
    finally:
        db.close()


def _update_req(folio, **fields):
    db = SessionLocal()
    try:
        r = db.query(ComplianceRequest).filter(ComplianceRequest.folio == folio).first()
        for k, v in fields.items():
            setattr(r, k, v)
        db.commit()
    finally:
        db.close()


def _anon_body(**extra):
    body = {"tipo": "acceso", "nombre": "Ana Pruebas López", "email": f"ana-{uuid.uuid4().hex[:8]}@pruebas.mx",
            "descripcion": "Quiero saber qué datos personales tienen de mí.", "acepta_privacidad": True}
    body.update(extra)
    return body


def _create(client, headers=None, **extra):
    r = client.post(API, json=_anon_body(**extra), headers={**_ip(), **(headers or {})})
    assert r.status_code == 201, r.text
    return r.json()


def _param(url, key):
    return parse_qs(urlparse(url).query)[key][0]


def _act(client, admin, folio, **payload):
    return client.post(f"{ADMIN}/{folio}/acciones", headers=admin["h"], json=payload)


def _verified_user(make_user, name="Titular Verificada"):
    u = make_user(name)
    u["id"] = _set_user(u["email"], email_verified=True)
    return u


def _imported_report(source="facebook") -> int:
    db = SessionLocal()
    try:
        r = LostReport(dog_name=f"Firulais {uuid.uuid4().hex[:5]}", report_type="lost", photos=[], source=source,
                       status="active", description="Se perdió en la colonia Roma.",
                       external_url=f"https://www.facebook.com/groups/1234/posts/{uuid.uuid4().int % 10**15}")
        db.add(r)
        db.commit()
        return r.id
    finally:
        db.close()


def _report(rid) -> LostReport:
    db = SessionLocal()
    try:
        r = db.get(LostReport, rid)
        db.expunge(r)
        return r
    finally:
        db.close()


# --------------------------------------------------------------------------- plazos
def test_deadlines_use_mexican_business_days():
    # Viernes 13 de noviembre de 2026, 12:00 en la Ciudad de México (18:00 UTC): el lunes 16 es día de descanso
    received = datetime.datetime(2026, 11, 13, 18, 0)
    due = sol.business_deadline(received, 20)
    expected_day = add_business_days(datetime.date(2026, 11, 13), 20)
    assert expected_day == datetime.date(2026, 12, 14)
    assert sol._local_date(due) == expected_day
    assert due == datetime.datetime(2026, 12, 15, 5, 59, 59)  # 23:59:59 en la Ciudad de México
    first, respond_by, effective = sol.initial_deadlines("acceso", {}, received)
    assert first is None and effective is None and respond_by == due
    # Acceso a la información usada para publicidad: el menor entre 20 días hábiles y 30 naturales
    _, adv, _ = sol.initial_deadlines("acceso", {"publicidad": True}, received)
    assert adv == min(due, sol.calendar_deadline(received, 30))
    # Queja por producto defectuoso: el menor entre la política y 15 días naturales (LFPC art. 93)
    first, q_due, _ = sol.initial_deadlines("queja", {"motivo": "producto_defectuoso"}, received)
    assert first == sol.business_deadline(received, 2)
    assert q_due == min(sol.business_deadline(received, 10), sol.calendar_deadline(received, 15))
    # Retiro de una publicación importada por su autor: 72 horas
    _, r_due, r_eff = sol.initial_deadlines("retiro_importado", {"relacion": "autor"}, received)
    assert r_due == r_eff == received + datetime.timedelta(hours=72)
    _, aludido, _ = sol.initial_deadlines("retiro_importado", {"relacion": "aparezco"}, received)
    assert aludido == due


def test_folios_are_sequential_per_year(client):
    a, b = _create(client), _create(client)
    assert sol.FOLIO_RE.match(a["folio"]) and sol.FOLIO_RE.match(b["folio"])
    year = datetime.datetime.now().year
    assert a["folio"].startswith(f"PF-{year}-") or a["folio"].startswith(f"PF-{year + 1}-")
    # Consecutivo y sin repetirse (la base es compartida: otra solicitud puede colarse entre las dos)
    assert int(b["folio"].rsplit("-", 1)[1]) > int(a["folio"].rsplit("-", 1)[1])


# --------------------------------------------------------------------------- persona sin cuenta
def test_anonymous_request_needs_privacy_and_rejects_bots(client):
    body = _anon_body()
    body.pop("acepta_privacidad")
    r = client.post(API, json=body, headers=_ip())
    assert r.status_code == 400 and "Aviso de Privacidad" in r.json()["detail"]
    r = client.post(API, json=_anon_body(website="http://spam.example"), headers=_ip())
    assert r.status_code == 400
    r = client.post(API, json=_anon_body(tipo="revocacion"), headers=_ip())
    assert r.status_code == 400 and "permiso" in r.json()["detail"]


def test_anonymous_request_confirm_and_track(client, make_user, outbox):
    owner = make_user("Dueña de la Cuenta")
    ack = _create(client, email=owner["email"].upper())
    assert ack["requiere_confirmacion"] is True and ack["estado"] == "recibida"
    mail = outbox[-1]
    assert mail["to"] == owner["email"] and ack["folio"] in mail["title"] and "20 días hábiles" in mail["body"]
    token = _param(mail["url"], "confirmar")
    assert mail["url"].startswith("/app/legal/derechos-arco.html?")
    # Seguimiento: folio y correo; sin datos personales
    assert client.get(f"{API}/{ack['folio']}", params={"email": "otra@pruebas.mx"}, headers=_ip()).status_code == 404
    view = client.get(f"{API}/{ack['folio']}", params={"email": owner["email"]}, headers=_ip()).json()
    assert view["estado"] == "recibida" and view["identidad_confirmada"] is False
    assert "descripcion" not in view and view["historial"][0]["tipo"] == "creada"
    # Confirmación: comprueba el correo y liga la solicitud a la cuenta con ese correo
    r = client.post(f"{API}/confirmar", json={"token": token}, headers=_ip())
    assert r.status_code == 200 and r.json()["identidad_confirmada"] is True
    assert client.post(f"{API}/confirmar", json={"token": token}, headers=_ip()).status_code == 404
    req = _req(ack["folio"])
    assert req.identity_method == "correo" and req.user_id is not None
    mine = client.get(f"{API}/mias", headers=owner["h"]).json()
    assert any(m["folio"] == ack["folio"] and m["descripcion"] for m in mine)


def test_logged_in_with_verified_email_is_identified(client, make_user):
    u = _verified_user(make_user)
    r = client.post(API, headers={**u["h"], **_ip()}, json={
        "tipo": "rectificacion", "nombre": "Titular Verificada", "descripcion": "Mi ciudad aparece mal: es Puebla."})
    assert r.status_code == 201, r.text
    ack = r.json()
    assert ack["requiere_confirmacion"] is False
    req = _req(ack["folio"])
    assert req.identity_method == "cuenta" and req.email == u["email"] and req.channel == "app"
    # La cuenta ligada ve el detalle completo al consultar su folio
    view = client.get(f"{API}/{ack['folio']}", headers={**u["h"], **_ip()}).json()
    assert view["descripcion"].startswith("Mi ciudad")


# --------------------------------------------------------------------------- cola y acciones del equipo
def test_admin_queue_requires_staff_and_shows_sla(client, make_user):
    admin, user = _staff(make_user), make_user("Sin Permisos")
    ack = _create(client)
    assert client.get(ADMIN, headers=user["h"]).status_code == 403
    _update_req(ack["folio"], respond_by=datetime.datetime.utcnow() - datetime.timedelta(days=1))
    data = client.get(ADMIN, headers=admin["h"], params={"q": ack["folio"]}).json()
    item = next(i for i in data["items"] if i["folio"] == ack["folio"])
    assert item["sla"]["color"] == "rojo" and item["sla"]["vencida"] is True
    summary = client.get(f"{ADMIN}/resumen", headers=admin["h"]).json()
    assert summary["vencidas"] >= 1
    detail = client.get(f"{ADMIN}/{ack['folio']}", headers=admin["h"]).json()
    assert {t["id"] for t in detail["plantillas"]} >= {"revision", "req_identidad", "acceso_procede", "negativa"}
    assert ack["folio"] in detail["plantillas"][0]["texto"]
    assert "requerir_info" in detail["acciones"] and "responder" in detail["acciones"]


def test_positive_answer_requires_identity_and_denial_closes(client, make_user, outbox):
    admin = _staff(make_user)
    ack = _create(client)
    r = _act(client, admin, ack["folio"], accion="responder", resultado="procede", mensaje="Procede tu solicitud.")
    assert r.status_code == 409 and "identidad" in r.json()["detail"]
    r = _act(client, admin, ack["folio"], accion="responder", resultado="no_procede", mensaje="No procede la solicitud.")
    assert r.status_code == 400  # falta la causa de la negativa
    r = _act(client, admin, ack["folio"], accion="responder", resultado="no_procede",
             motivo_negativa="identidad_no_acreditada", mensaje="No pudimos comprobar tu identidad.")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "cerrada"
    assert "Secretaría Anticorrupción y Buen Gobierno" in outbox[-1]["body"]


def test_info_request_once_restarts_deadline_and_id_is_purged(client, make_user, outbox):
    admin = _staff(make_user)
    ack = _create(client, tipo="cancelacion", alcance="datos")
    r = _act(client, admin, ack["folio"], accion="requerir_info", pedir_identificacion=True,
             mensaje="Necesitamos tu identificación para comprobar que eres tú.")
    assert r.status_code == 200, r.text
    assert r.json()["esperando_titular"] is True and r.json()["sla"]["color"] == "azul"
    clave = _param(outbox[-1]["url"], "clave")
    r = _act(client, admin, ack["folio"], accion="requerir_info", mensaje="Otra vez, por favor, más datos.")
    assert r.status_code == 409  # una sola vez
    access = client.get(f"{API}/{ack['folio']}/acceso", params={"clave": clave}, headers=_ip()).json()
    assert access["pendiente"]["informacion"] and access["pendiente"]["identificacion"]
    assert "identificación" in access["lo_que_pedimos"]
    assert client.get(f"{API}/{ack['folio']}/acceso", params={"clave": "x" * 30}, headers=_ip()).status_code == 404
    before = datetime.datetime.utcnow()
    r = client.post(f"{API}/{ack['folio']}/respuesta", headers=_ip(), data={"clave": clave, "mensaje": "Aquí está."},
                    files={"archivo": ("ine.jpg", make_jpeg(7), "image/jpeg")})
    assert r.status_code == 200, r.text
    req = _req(ack["folio"])
    assert req.info_received_at and req.status == "en_revision" and req.id_document_id and req.id_document_sha256
    assert req.respond_by == sol.business_deadline(req.info_received_at, 20) and req.info_received_at >= before
    doc = private_document_path(req.id_document_id)
    assert doc is not None and doc.is_file()
    r = _act(client, admin, ack["folio"], accion="verificar_identidad", metodo="identificacion")
    assert r.status_code == 200 and r.json()["identidad_confirmada"] is True
    req = _req(ack["folio"])
    assert req.id_document_id is None and req.id_document_purged_at and req.id_document_sha256
    assert not doc.exists()


def test_info_request_only_within_five_business_days(client, make_user):
    admin = _staff(make_user)
    ack = _create(client)
    _update_req(ack["folio"], received_at=datetime.datetime.utcnow() - datetime.timedelta(days=12))
    r = _act(client, admin, ack["folio"], accion="requerir_info", mensaje="Necesitamos más información, por favor.")
    assert r.status_code == 409 and "5 días hábiles" in r.json()["detail"]


def test_extension_only_once(client, make_user, outbox):
    admin = _staff(make_user)
    ack = _create(client)
    before = _req(ack["folio"]).respond_by
    r = _act(client, admin, ack["folio"], accion="ampliar", mensaje="La información está en varios sistemas.")
    assert r.status_code == 200, r.text
    after = _req(ack["folio"]).respond_by
    assert sol._local_date(after) == add_business_days(sol._local_date(before), 20)
    assert "una sola vez" in outbox[-1]["body"]
    r = _act(client, admin, ack["folio"], accion="ampliar", mensaje="Otra ampliación más, por favor.")
    assert r.status_code == 409


def test_access_procede_delivers_my_data_export(client, make_user, outbox):
    admin = _staff(make_user)
    u = _verified_user(make_user, "Titular Acceso")
    folio = client.post(API, headers={**u["h"], **_ip()}, json={
        "tipo": "acceso", "nombre": "Titular Acceso", "descripcion": "Quiero una copia de todos mis datos."}).json()["folio"]
    assert _act(client, admin, folio, accion="en_revision").status_code == 200
    r = _act(client, admin, folio, accion="responder", resultado="procede", mensaje="Procede tu solicitud de acceso.")
    assert r.status_code == 200 and r.json()["estado"] == "respondida" and r.json()["efectiva_antes_de"]
    assert client.get(f"{API}/{folio}/descarga", headers={**u["h"], **_ip()}).status_code == 409  # aún no es efectiva
    r = _act(client, admin, folio, accion="hacer_efectiva")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "efectiva" and r.json()["hecho"]["descarga"] is True
    clave = _param(outbox[-1]["url"], "clave")
    r = client.get(f"{API}/{folio}/descarga", params={"clave": clave}, headers=_ip())
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["profile"]["email"] == u["email"]
    assert any(c["folio"] == folio for c in data["compliance_requests"])
    assert client.get(f"{API}/{folio}/descarga", headers={**u["h"], **_ip()}).status_code == 200  # la cuenta ligada también


def test_cancellation_reuses_account_deletion(client, make_user):
    admin = _staff(make_user)
    u = _verified_user(make_user, "Titular Cancelación")
    folio = client.post(API, headers={**u["h"], **_ip()}, json={
        "tipo": "cancelacion", "alcance": "cuenta", "nombre": "Titular Cancelación",
        "descripcion": "Quiero que borren mi cuenta y mis datos."}).json()["folio"]
    assert _act(client, admin, folio, accion="hacer_efectiva").status_code == 409  # primero se responde
    assert _act(client, admin, folio, accion="responder", resultado="procede",
                mensaje="Procede la cancelación de tu cuenta.").status_code == 200
    r = _act(client, admin, folio, accion="hacer_efectiva", eliminar_cuenta=True)
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        user = db.get(User, u["id"])
        assert user.is_active is False and user.deleted_at is not None and user.email.endswith("@patitasfind.invalid")
    finally:
        db.close()
    req = _req(folio)
    assert req.status == "efectiva" and req.email == u["email"]  # el expediente conserva el correo para responder


def test_limitation_for_advertising_enters_exclusion_list(client, make_user):
    admin = _staff(make_user)
    u = _verified_user(make_user, "Titular Publicidad")
    _set_user(u["email"], marketing_opt_in=True)
    folio = client.post(API, headers={**u["h"], **_ip()}, json={
        "tipo": "limitacion", "permisos": ["publicidad"], "nombre": "Titular Publicidad",
        "descripcion": "No quiero recibir publicidad por ningún medio."}).json()["folio"]
    db = SessionLocal()
    try:
        assert sol.is_marketing_excluded(db, email=u["email"]) is False
    finally:
        db.close()
    assert _act(client, admin, folio, accion="responder", resultado="procede",
                mensaje="Procede: te incluimos en el listado de exclusión.").status_code == 200
    r = _act(client, admin, folio, accion="hacer_efectiva")
    assert r.status_code == 200, r.text
    assert "marketing_opt_in" in r.json()["hecho"]["permisos"]
    db = SessionLocal()
    try:
        assert db.get(User, u["id"]).marketing_opt_in is False
        assert sol.is_marketing_excluded(db, email=u["email"].upper()) is True
        rec = db.query(ConsentRecord).filter(ConsentRecord.user_id == u["id"], ConsentRecord.channel == "solicitud").all()
        assert rec and all(r.granted is False for r in rec)
    finally:
        db.close()


def test_complaint_first_response_and_second_review(client, make_user, outbox):
    admin = _staff(make_user)
    ack = _create(client, tipo="queja", motivo="producto_defectuoso",
                  descripcion="El collar llegó roto y el refugio no responde.")
    assert ack["primera_respuesta_antes_de"]
    req = _req(ack["folio"])
    assert req.respond_by == min(sol.business_deadline(req.received_at, 10), sol.calendar_deadline(req.received_at, 15))
    assert outbox[-1]["url"].startswith("/app/legal/atencion-y-quejas.html")
    assert _act(client, admin, ack["folio"], accion="primera_respuesta",
                mensaje="Ya pedimos al Refugio que revise tu pedido.").status_code == 200
    # Una queja se puede responder sin comprobar identidad
    r = _act(client, admin, ack["folio"], accion="responder", resultado="procede",
             mensaje="El Refugio te enviará un collar nuevo esta semana.")
    assert r.status_code == 200 and r.json()["estado"] == "respondida"
    # Segunda revisión: la persona contesta desde el enlace del correo de la respuesta, sin cuenta
    token = _param(outbox[-1]["url"], "clave")
    assert "segunda revisión" in outbox[-1]["body"]
    r = client.post(f"{API}/{ack['folio']}/respuesta", headers=_ip(), data={"clave": token, "mensaje": "No estoy conforme."})
    assert r.status_code == 200 and _req(ack["folio"]).status == "en_revision"


# --------------------------------------------------------------------------- retiro de publicaciones importadas
def test_imported_removal_hides_now_and_purges_before_72h(client, make_user, outbox):
    admin = _staff(make_user)
    rid = _imported_report()
    link = f"https://guauwoow.com/app/?report={rid}"
    r = client.post(API, headers=_ip(), json={
        "tipo": "retiro_importado", "nombre": "Autora Original", "email": f"autora-{uuid.uuid4().hex[:6]}@pruebas.mx",
        "descripcion": "Pido el retiro de mi publicación.", "enlace": link, "relacion": "autor", "acepta_privacidad": True})
    assert r.status_code == 201, r.text
    ack = r.json()
    assert ack["publicacion_oculta"] is True and "72 horas" in ack["mensaje"]
    assert _report(rid).is_hidden is True
    req = _req(ack["folio"])
    assert req.respond_by == req.received_at + datetime.timedelta(hours=72)
    db = SessionLocal()
    try:
        removal = db.get(ContentReport, req.content_report_id)
        assert removal.reason == "retiro_autor" and removal.status == "open"
        assert db.query(Notification).filter(Notification.user_id == admin["id"], Notification.type == "compliance_request",
                                             Notification.title.contains(ack["folio"])).count() == 1
    finally:
        db.close()
    # La misma publicación otra vez: el mismo folio
    again = client.post(API, headers=_ip(), json={
        "tipo": "retiro_importado", "nombre": "Autora Original", "email": f"otra-{uuid.uuid4().hex[:6]}@pruebas.mx",
        "descripcion": "Pido el retiro de mi publicación.", "enlace": link, "relacion": "autor", "acepta_privacidad": True})
    assert again.status_code == 200 and again.json()["folio"] == ack["folio"]
    # La tarea de cada hora la borra antes de 72 h si el equipo no la descartó, pero solo cuando la persona autora
    # confirmó su correo (sin eso, cualquiera podría borrar una alerta ajena)
    db = SessionLocal()
    try:
        assert ack["folio"] not in sol.enforce_imported_removals(db, now=datetime.datetime.utcnow() + datetime.timedelta(hours=49))
    finally:
        db.close()
    assert _report(rid).purged_at is None
    mail = next(m for m in outbox if m["url"] and "confirmar=" in m["url"] and ack["folio"] in m["url"])
    assert client.post(f"{API}/confirmar", json={"token": _param(mail["url"], "confirmar")}, headers=_ip()).status_code == 200
    db = SessionLocal()
    try:
        assert ack["folio"] not in sol.enforce_imported_removals(db, now=datetime.datetime.utcnow() + datetime.timedelta(hours=1))
        done = sol.enforce_imported_removals(db, now=datetime.datetime.utcnow() + datetime.timedelta(hours=49))
        assert ack["folio"] in done
    finally:
        db.close()
    report = _report(rid)
    assert report.purged_at is not None and report.photos == []
    assert _req(ack["folio"]).status == "efectiva"
    assert "Retiramos la publicación" in outbox[-1]["title"]


def test_imported_removal_not_procede_restores_and_rejects_own_reports(client, make_user):
    admin = _staff(make_user)
    rid = _imported_report(source="volunteer")
    ack = _create(client, tipo="retiro_importado", relacion="aparezco", enlace=f"https://x.mx/app/?report={rid}",
                  descripcion="Aparezco en la foto y no di permiso.")
    req = _req(ack["folio"])
    assert _report(rid).is_hidden is True
    assert req.respond_by == sol.business_deadline(req.received_at, 20)  # quien aparece: plazo ARCO
    r = _act(client, admin, ack["folio"], accion="responder", resultado="no_procede", motivo_negativa="otro",
             mensaje="Revisamos y no apareces en la publicación.")
    assert r.status_code == 200 and r.json()["estado"] == "cerrada"
    assert _report(rid).is_hidden is False
    # Un reporte normal de la app no se retira por este formulario
    db = SessionLocal()
    try:
        own = LostReport(dog_name="Propio", report_type="lost", photos=[], source="app", status="active")
        db.add(own)
        db.commit()
        own_id = own.id
    finally:
        db.close()
    r = client.post(API, headers=_ip(), json=_anon_body(tipo="retiro_importado", relacion="autor",
                                                         enlace=f"https://x.mx/app/?report={own_id}"))
    assert r.status_code == 400 and "Reportar" in r.json()["detail"]


# --------------------------------------------------------------------------- tareas programadas
def test_daily_maintenance_closes_unconfirmed_and_unanswered(client, make_user):
    admin = _staff(make_user)
    unconfirmed = _create(client)
    waiting = _create(client, tipo="oposicion", descripcion="Me opongo al puntaje de compatibilidad.")
    assert _act(client, admin, waiting["folio"], accion="requerir_info",
                mensaje="¿De qué postulación hablas? Danos el nombre del perro.").status_code == 200
    past = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
    _update_req(unconfirmed["folio"], confirm_expires_at=past)
    _update_req(waiting["folio"], info_due_at=past, created_at=datetime.datetime.utcnow() - datetime.timedelta(days=40),
                user_agent="pytest", ip="10.20.30.40")
    db = SessionLocal()
    try:
        out = sol.daily_maintenance(db)
    finally:
        db.close()
    assert out["sin_confirmar"] >= 1 and out["sin_info"] >= 1
    a, b = _req(unconfirmed["folio"]), _req(waiting["folio"])
    assert a.status == "cerrada" and a.denial_reason == "identidad_no_acreditada"
    assert b.status == "cerrada" and b.denial_reason == "informacion_incompleta"
    assert b.ip == "10.20.30.0" and b.user_agent is None  # IP acortada a los 30 días


def test_create_solicitud_for_internal_callers():
    """Entrada para el bot de WhatsApp: sin correo, con la identidad comprobada por el número."""
    db = SessionLocal()
    try:
        req = sol.create_solicitud(db, kind="cancelacion", name="Persona del Bot", phone="+525512345678",
                                   description="Escribió ELIMINAR en el bot de WhatsApp.", channel="whatsapp",
                                   identity_method="whatsapp", details={"alcance": "whatsapp"})
        assert sol.FOLIO_RE.match(req.folio) and req.identity_method == "whatsapp" and req.email is None
        with pytest.raises(sol.SolicitudError):
            sol.create_solicitud(db, kind="acceso", name="Sin Correo", description="Quiero mis datos, por favor.")
    finally:
        db.rollback()
        db.close()


# --------------------------------------------------------------------------- transparencia
def _refuge(owner_email, person_type=None, donations=0, orders=0, opt_in=False) -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == owner_email).first()
        refuge = Refuge(user_id=user.id, name=f"Refugio Transparencia {uuid.uuid4().hex[:6]}", status="approved",
                        city="Puebla", documents=[], transparency_opt_in_at=datetime.datetime.utcnow() if opt_in else None)
        db.add(refuge)
        db.flush()
        if person_type:
            db.add(RefugeFiscalProfile(refuge_id=refuge.id, person_type=person_type, rfc="XAXX010101000",
                                       legal_name="Refugio de Prueba AC", regimen_fiscal="603", postal_code="72000"))
        now = datetime.datetime.utcnow()
        for _ in range(donations):
            db.add(Donation(user_id=user.id, refuge_id=refuge.id, amount=Decimal("100.00"), status="approved",
                            approved_at=now, fee_amount=Decimal("0"), net_amount=Decimal("100.00"), payment_mode="split"))
        for _ in range(orders):
            db.add(Order(user_id=user.id, refuge_id=refuge.id, total=Decimal("300.00"), shipping_address="Calle 1",
                         status="paid", paid_at=now, fee_amount=Decimal("30.00"), isr_retenido=Decimal("6.47"),
                         iva_retenido=Decimal("20.69")))
        db.commit()
        return refuge.id
    finally:
        db.close()


def _row(report, rid):
    return next((r for r in report["fondos"]["refugios"] if r["id"] == rid), None)


def test_transparency_named_refuges_threshold_and_consent(client, make_user):
    owner_m, owner_f = make_user("Refugio Moral"), make_user("Refugio Física")
    moral = _refuge(owner_m["email"], "moral", donations=6, orders=2)
    fisica = _refuge(owner_f["email"], "fisica", donations=6, orders=0)
    db = SessionLocal()
    try:
        report = tr.build_report(db, statements.current_period(), "fondos")
    finally:
        db.close()
    row = _row(report, moral)
    assert row is not None and row["forma_juridica"] == "Persona moral"
    assert row["donativos"]["casos"] == 6 and row["donativos"]["bruto"] == Decimal("600.00")
    assert row["ventas"] == {"suprimido": True, "casos": None}  # 2 pedidos < 5: no se publica
    assert _row(report, fisica) is None  # persona física sin consentimiento: va en «Otros Refugios»
    assert report["fondos"]["otros_refugios"]["refugios"] >= 1
    assert len(report["fondos"]["serie_mensual"]) == 1
    # El Refugio persona física acepta publicar sus cifras con su nombre
    r = client.post("/cumplimiento/transparencia/mi-refugio", headers=owner_f["h"], json={"publicar": True})
    assert r.status_code == 200 and r.json()["publicar"] is True and r.json()["requiere_consentimiento"] is True
    db = SessionLocal()
    try:
        report = tr.build_report(db, statements.current_period(), "general")
        assert db.query(ConsentRecord).filter(ConsentRecord.purpose == "transparencia_refugio").count() >= 1
    finally:
        db.close()
    assert _row(report, fisica)["donativos"]["neto"] == Decimal("600.00")
    for key in ("moderacion", "privacidad", "importados", "verificados", "autoridades"):
        assert key in report
    assert report["verificados"]["refugios_verificados"] >= 2


def test_transparency_refuge_detail_and_endpoint(client, make_user):
    owner_m, owner_f = make_user("Detalle Moral"), make_user("Detalle Física")
    moral = _refuge(owner_m["email"], "moral", donations=5, orders=5)
    fisica = _refuge(owner_f["email"], None, donations=1)
    r = client.get(f"/cumplimiento/transparencia/refugios/{moral}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["publicado"] is True and len(d["serie_mensual"]) == 12 and d["calculado_en"]
    assert d["totales"]["ventas"]["casos"] == 5
    assert d["totales"]["ventas"]["neto"] == pytest.approx(5 * (300 - 30 - 6.47 - 20.69), abs=0.01)
    hidden = client.get(f"/cumplimiento/transparencia/refugios/{fisica}").json()
    assert hidden["publicado"] is False and "totales" not in hidden
    assert client.get("/cumplimiento/transparencia/refugios/999999999").status_code == 404
    r = client.get("/cumplimiento/transparencia", params={"vista": "general", "periodo": "12m"})
    assert r.status_code == 200 and r.json()["umbral"] == 5 and r.json()["calculado_en"]
    assert client.get("/cumplimiento/transparencia", params={"vista": "otra"}).status_code == 400
    assert client.get("/cumplimiento/transparencia", params={"periodo": "2026-13"}).status_code == 400
    assert client.get("/cumplimiento/transparencia", params={"periodo": "2999-01"}).status_code == 400


def test_transparency_arco_stats_and_collapse(client, make_user):
    admin = _staff(make_user)
    u = _verified_user(make_user, "Titular Estadística")
    start = datetime.datetime.utcnow() - datetime.timedelta(seconds=5)
    folio = client.post(API, headers={**u["h"], **_ip()}, json={
        "tipo": "oposicion", "nombre": "Titular Estadística", "descripcion": "Me opongo al uso de mis datos."}).json()["folio"]
    assert _act(client, admin, folio, accion="responder", resultado="procede",
                mensaje="Procede tu oposición al puntaje.").status_code == 200
    db = SessionLocal()
    try:
        stats = sol.arco_stats(db, start, datetime.datetime.utcnow() + datetime.timedelta(seconds=5))
    finally:
        db.close()
    assert stats["respondidas"] >= 1 and stats["respondidas_a_tiempo"] >= 1 and stats["porcentaje_a_tiempo"] == 100.0
    out = tr._collapse({"a": 7, "b": 2, "c": 1}, {"a": "A"}, 5)
    assert out[0] == {"clave": "a", "texto": "A", "casos": 7}
    assert out[1]["clave"] == "suprimido" and out[1]["casos"] is None
    out = tr._collapse({"a": 3, "b": 3}, {}, 5)
    assert out == [{"clave": "otros", "texto": "Otras categorías (cada una con menos de 5 casos)", "casos": 6}]
