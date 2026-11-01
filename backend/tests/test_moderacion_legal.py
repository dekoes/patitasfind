"""Moderación legal (contrato K-REPORTES): reportes públicos sin cuenta, motivos del Decreto NNA, ocultamiento
inmediato de lo que involucra a menores, bóveda de evidencia cifrada con hash encadenado, cuarentena de material de
abuso sexual infantil (nunca servido ni enviado a la IA), apelaciones con la cuenta suspendida, aviso y contra-aviso
de derechos de autor con staydown y reincidentes, y registro de requerimientos de autoridades."""
import datetime
import io
import uuid

import pytest
from PIL import Image

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AdminAuditLog, AuthorityRequest, BlockedImageHash, ContentReport, CopyrightNotice, Dog, EvidenceRecord,
    ModerationAction, ModerationAppeal, Notification, User,
)
from app.services import evidence, images, legal_moderation as lm, staydown, vision
from app.tasks import moderacion_legal as tasks
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
    if not u.get("id"):
        u["id"] = _set(u["email"])
    return u["id"]


def _staff(make_user, role="admin"):
    u = make_user(f"Moderación {role}", verify=False)
    u["id"] = _set(u["email"], role=role)
    return u


def _ip():
    return {"X-Real-IP": random_ip()}


def _seed() -> int:
    """Semilla nueva por corrida: las imágenes retiradas quedan bloqueadas (staydown) en la base de desarrollo."""
    return uuid.uuid4().int % 10**9


def _upload(client, u, data: bytes):
    return client.post("/upload", headers=u["h"], files={"file": ("foto.jpg", data, "image/jpeg")})


def _dog(client, owner, photos=None):
    body = {"name": f"Perro {uuid.uuid4().hex[:6]}", "size": "Mediano"}
    if photos:
        body["photos"] = photos
    r = client.post("/dogs", headers=owner["h"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _dog_row(dog_id):
    db = SessionLocal()
    try:
        return db.query(Dog).filter(Dog.id == dog_id).first()
    finally:
        db.close()


def _query(model, *filters):
    db = SessionLocal()
    try:
        return db.query(model).filter(*filters).order_by(model.id).all()
    finally:
        db.close()


def _public_report(client, headers=None, **body):
    payload = {"reason": "otro", "details": "Algo no está bien en esta publicación"} | body
    return client.post("/cumplimiento/reportes-publicos", json=payload, headers=headers or _ip())


def _notice_payload(url, **extra):
    return {
        "ubicacion": url, "obra": "Fotografía «Perro al atardecer» de mi autoría",
        "hechos": "La publicaron sin mi autorización en una ficha de adopción.", "nombre": "Fotógrafa Titular",
        "caracter": "titular", "email": f"titular-{uuid.uuid4().hex[:6]}@pruebas.mx", "telefono": "5512345678",
        "domicilio": "Calle Falsa 123, Ciudad de México", "bajo_protesta": True, "conoce_sancion": True, **extra,
    }


def _resized(data: bytes, size=(500, 375)) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB").resize(size)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


@pytest.fixture
def admin(make_user):
    return _staff(make_user)


@pytest.fixture(autouse=True)
def _fresh_staydown():
    staydown.invalidate_cache()
    yield
    staydown.invalidate_cache()


# --------------------------------------------------------------------------- motivos y formulario público
def test_reasons_include_decree_minors_and_page_reasons(client):
    r = client.get("/cumplimiento/reportes-publicos/motivos")
    assert r.status_code == 200
    values = {x["value"]: x for x in r.json()}
    for reason in lm.DECREE_REASONS:
        assert values[reason]["grupo"] == "decreto"
    assert values["involucra_menor"]["oculta_al_reportar"] is True
    assert values["involucra_menor"]["label"] == "Involucra a una niña, niño o adolescente"
    # Los que pide VERIFICAR_MOTIVOS_DE_REPORTE (moderacion.html §1 y §10)
    for reason in ("maltrato", "venta_animal", "fraude", "contenido_intimo", "mi_imagen", "difamacion", "suplantacion",
                   "resena_falsa", "cedula_falsa", "condiciones_sanitarias", "publicidad_enganosa"):
        assert reason in values, reason
    assert r.json()[0]["value"] == "involucra_menor"  # los de menores van primero


def test_public_report_honeypot_rate_limit_and_status(client, owner):
    dog = _dog(client, owner)
    # Campo trampa: responde como si nada, pero no guarda
    fake = _public_report(client, target_url=f"/app/?dog={dog['id']}", website="http://spam.example")
    assert fake.status_code == 201 and fake.json()["folio"].startswith("REP-")
    assert not _query(ContentReport, ContentReport.folio == fake.json()["folio"])

    email = f"mama-{uuid.uuid4().hex[:6]}@pruebas.mx"
    headers = _ip()
    r = _public_report(client, headers, target_url=f"https://guauwoow.com/app/?dog={dog['id']}", reason="spam",
                       email=email)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["folio"].startswith("REP-") and body["oculto"] is False and body["prioridad"] == "General"
    row = _query(ContentReport, ContentReport.folio == body["folio"])[0]
    assert (row.target_type, row.target_id, row.source, row.reporter_id) == ("dog", dog["id"], "publico", None)
    assert row.contact_email == email and row.due_at is not None
    # Mismo remitente, mismo contenido y motivo: no se duplica
    again = _public_report(client, headers, target_url=f"/app/?dog={dog['id']}", reason="spam", email=email)
    assert again.status_code == 200 and again.json()["folio"] == body["folio"]

    st = client.get(f"/cumplimiento/reportes-publicos/{body['folio']}", params={"email": email.upper()}, headers=_ip())
    assert st.status_code == 200 and st.json()["estado"] == "En revisión"
    assert client.get(f"/cumplimiento/reportes-publicos/{body['folio']}", params={"email": "otra@pruebas.mx"},
                      headers=_ip()).status_code == 404

    # Límite por IP y hora
    limit_ip = _ip()
    for i in range(settings.public_reports_hourly_limit):
        assert _public_report(client, limit_ip, details=f"Reporte número {i} sin enlace").status_code == 201
    assert _public_report(client, limit_ip, details="Uno más de la cuenta").status_code == 429
    # Los mensajes del chat no se reportan desde el formulario público
    assert _public_report(client, target_type="message", target_id=1).status_code == 400
    assert _public_report(client, email="no-es-correo").status_code == 400


def test_unidentified_report_then_linked_by_admin(client, owner, admin):
    dog = _dog(client, owner)
    r = _public_report(client, reason="involucra_menor", details="Una foto con la cara de mi hija en un perfil",
                       target_url="https://otro-sitio.example/foto")
    assert r.status_code == 201, r.text
    row = _query(ContentReport, ContentReport.folio == r.json()["folio"])[0]
    assert row.target_type == "sin_identificar" and row.priority == 0 and r.json()["oculto"] is False
    queue = client.get("/admin/cumplimiento/cola", headers=admin["h"], params={"prioridad": 0, "limit": 200}).json()
    assert any(x["id"] == row.id and x["priority_label"] == "Menores" for x in queue)
    linked = client.patch(f"/admin/cumplimiento/reportes/{row.id}/objetivo", headers=admin["h"],
                          json={"target_type": "dog", "target_id": dog["id"]})
    assert linked.status_code == 200 and linked.json()["auto_hidden"] is True
    assert _dog_row(dog["id"]).is_hidden is True


# --------------------------------------------------------------------------- menores: ocultamiento inmediato
def test_minor_report_hides_immediately_with_encrypted_evidence(client, owner, user, admin, jpeg):
    url = _upload(client, owner, jpeg(_seed())).json()["url"]
    dog = _dog(client, owner, photos=[url])
    r = _public_report(client, target_url=f"/app/?dog={dog['id']}", reason="involucra_menor",
                       details="Sale un niño reconocible en la foto")
    assert r.status_code == 201 and r.json()["oculto"] is True and r.json()["prioridad"] == "Menores"
    assert _dog_row(dog["id"]).is_hidden is True
    assert client.get(f"/dogs/{dog['id']}").status_code == 404

    report = _query(ContentReport, ContentReport.folio == r.json()["folio"])[0]
    assert report.auto_hidden and report.priority == 0
    rec = _query(EvidenceRecord, EvidenceRecord.content_report_id == report.id)[0]
    assert rec.kind == "ocultamiento_preventivo" and rec.files and rec.files[0]["name"] == url
    blob = (evidence.evidence_dir() / rec.storage_path).read_bytes()
    assert blob.startswith(b"PFENC1") and dog["name"].encode() not in blob  # cifrado en disco
    bundle = evidence.read_bundle(rec)
    assert bundle["target"]["data"]["name"] == dog["name"] and bundle["report"]["reason"] == "involucra_menor"
    # Al menos 90 días hábiles (>= 126 naturales)
    assert rec.retained_until - rec.created_at >= datetime.timedelta(days=126)
    # Avisos: a los admins (alerta) y a quien publicó (en revisión)
    assert _query(Notification, Notification.user_id == admin["id"], Notification.type == "moderation_alert")
    owner_notes = _query(Notification, Notification.user_id == _uid(owner), Notification.type == "content_hidden")
    assert owner_notes and "mientras la revisamos" in owner_notes[-1].body

    # Descartar el reporte revierte el ocultamiento preventivo
    d = client.patch(f"/admin/reports/{report.id}", headers=admin["h"], json={"status": "dismissed"})
    assert d.status_code == 200, d.text
    assert _dog_row(dog["id"]).is_hidden is False
    assert _query(Notification, Notification.user_id == _uid(owner), Notification.type == "content_restored")


def test_in_app_minor_report_and_hide_sends_statement_of_reasons(client, owner, user, admin):
    dog = _dog(client, owner)
    r = client.post("/reports", headers=user["h"], json={"target_type": "dog", "target_id": dog["id"],
                                                         "reason": "involucra_menor"})
    assert r.status_code == 201, r.text
    assert _dog_row(dog["id"]).is_hidden is True
    out = client.patch(f"/admin/reports/{r.json()['id']}", headers=admin["h"],
                       json={"status": "resolved", "action": "hide_content", "notes": "Foto de menor"})
    assert out.status_code == 200, out.text
    assert out.json()["priority"] == 0 and out.json()["auto_hidden"] is True
    action = _query(ModerationAction, ModerationAction.content_report_id == r.json()["id"])[0]
    assert action.action == "hide_content" and action.rule == "involucra_menor" and action.detection == "reporte"
    assert action.appeal_until and action.notice_sent_at and action.evidence_id
    note = _query(Notification, Notification.user_id == _uid(owner), Notification.type == "content_hidden")[-1]
    for text in ("Regla aplicada", "Cómo lo detectamos", action.folio, "apelar", "persona distinta"):
        assert text in note.body, text
    rec = _query(EvidenceRecord, EvidenceRecord.id == action.evidence_id)[0]
    assert rec.kind == "contenido_retirado"


# --------------------------------------------------------------------------- material de abuso sexual infantil
def test_csam_quarantine_never_served_never_to_ai(client, owner, admin, jpeg, monkeypatch):
    data = jpeg(_seed())
    url = _upload(client, owner, data).json()["url"]
    dog = _dog(client, owner, photos=[url])
    path = images.local_path_for(url)
    assert path and path.exists()
    r = _public_report(client, target_url=url, reason="abuso_sexual_infantil", details="Material de abuso")
    assert r.status_code == 201 and r.json()["oculto"] is True, r.text

    # Cuarentena PREVENTIVA: oculta y fuera de /uploads (ni la miniatura), pero sin bloqueo por hash ni denuncia
    assert not path.exists() and not path.with_name(f"{path.stem}_thumb.jpg").exists()
    assert client.get(url).status_code == 404
    row = _dog_row(dog["id"])
    assert row.is_hidden is True and row.photos == [url]
    report = _query(ContentReport, ContentReport.folio == r.json()["folio"])[0]
    pending = _query(EvidenceRecord, EvidenceRecord.content_report_id == report.id, EvidenceRecord.is_csam == True)[0]  # noqa: E712
    assert pending.kind == lm.PENDING_QUARANTINE_KIND and pending.legal_hold
    assert not _query(BlockedImageHash, BlockedImageHash.evidence_id == pending.id)
    assert not _query(AuthorityRequest, AuthorityRequest.content_report_id == report.id)
    queue = client.get("/admin/cumplimiento/cola", headers=admin["h"], params={"prioridad": 0, "limit": 200}).json()
    assert next(x for x in queue if x["id"] == report.id)["quarantine_pending"] is True
    signals = client.get(f"/admin/cumplimiento/reportes/{report.id}/senales", headers=admin["h"])
    assert signals.status_code == 200 and len(signals.json()["archivos"]) == 1 and "data_b64" not in signals.text
    # La confirma un superadmin (un admin no puede)
    superadmin = _make_superadmin(client)
    body = {"motivo": "Revisé las señales: coincide con lo reportado"}
    assert client.post(f"/admin/cumplimiento/reportes/{report.id}/confirmar-cuarentena", headers=admin["h"],
                       json=body).status_code == 403
    ok = client.post(f"/admin/cumplimiento/reportes/{report.id}/confirmar-cuarentena", headers=superadmin["h"], json=body)
    assert ok.status_code == 200 and ok.json()["quarantined"] is True, ok.text

    # Confirmada: foto quitada de la ficha, bloqueo por hash, denuncia pendiente y medida sin aviso
    row = _dog_row(dog["id"])
    assert row.is_hidden is True and row.photos == []
    rec = _query(EvidenceRecord, EvidenceRecord.content_report_id == report.id, EvidenceRecord.is_csam == True)[0]  # noqa: E712
    assert rec.legal_hold and "Ministerio Público" in rec.legal_hold_reason
    assert _query(BlockedImageHash, BlockedImageHash.evidence_id == rec.id, BlockedImageHash.kind == "csam")
    alert = _query(AuthorityRequest, AuthorityRequest.content_report_id == report.id)[0]
    assert alert.direction == "saliente" and alert.status == "pendiente_denuncia" and alert.involves_minor
    assert rec.id in alert.evidence_ids
    action = _query(ModerationAction, ModerationAction.evidence_id == rec.id)[0]
    assert action.action == "quarantine" and action.notice_withheld_reason and action.notice_sent_at is None

    # El panel solo muestra metadatos (en la cola mientras estaba abierto y en el listado ya resuelto)
    item = next(x for x in queue if x["id"] == report.id)
    assert "photo" not in item["target"] and "cuarentena" in item["target"]["title"]
    assert _query(ContentReport, ContentReport.id == report.id)[0].status == "resolved"
    listing = client.get("/admin/reports", headers=admin["h"], params={"status": "resolved", "target_type": "dog"}).json()
    assert "photo" not in next(x for x in listing if x["id"] == report.id)["target"]
    ev = client.get("/admin/cumplimiento/evidencia", headers=admin["h"], params={"csam": True}).json()
    assert any(e["id"] == rec.id for e in ev) and all("paquete" not in e for e in ev)

    # Volver a subirla (aunque se recomprima) se rechaza y cuenta el intento
    again = _upload(client, owner, _resized(data))
    assert again.status_code == 400 and "se retiró" in again.json()["detail"]
    assert _query(BlockedImageHash, BlockedImageHash.evidence_id == rec.id)[0].hits >= 1

    # Nunca se manda a la IA
    monkeypatch.setattr(vision, "is_configured", lambda: True)
    monkeypatch.setattr(vision, "_post_chat", lambda *a, **k: pytest.fail("se envió material en cuarentena a la IA"))
    assert vision.analyze_image_bytes(data) is None
    assert vision.analyze_url(url) is None

    # Exportar solo con la denuncia ligada y como superadmin
    assert client.get(f"/admin/cumplimiento/evidencia/{rec.id}/exportar", headers=admin["h"]).status_code == 403
    assert client.get(f"/admin/cumplimiento/evidencia/{rec.id}/exportar", headers=superadmin["h"]).status_code == 403
    exp = client.get(f"/admin/cumplimiento/evidencia/{rec.id}/exportar", headers=superadmin["h"],
                     params={"requerimiento": alert.folio})
    assert exp.status_code == 200 and exp.headers["content-disposition"].startswith("attachment")
    assert "data_b64" not in exp.text and rec.content_sha256 in exp.text  # nunca se descarga el material
    # La retención del material la libera solo un superadmin con instrucciones
    assert client.post(f"/admin/cumplimiento/evidencia/{rec.id}/retencion", headers=admin["h"],
                       json={"legal_hold": False}).status_code == 403

    # Cuarentena equivocada: un superadmin la libera; la ficha sigue oculta y la imagen se puede subir de nuevo
    rel = client.post(f"/admin/cumplimiento/evidencia/{rec.id}/liberar-cuarentena", headers=superadmin["h"],
                      json={"motivo": "Reporte falso: es la foto de un perro"})
    assert rel.status_code == 200 and rel.json()["restored_files"] == 1, rel.text
    row = _dog_row(dog["id"])
    assert row.photos == [url] and row.is_hidden is True and images.local_path_for(url)
    staydown.invalidate_cache()
    assert _upload(client, owner, data).status_code == 200


def _make_superadmin(client):
    from tests.conftest import _register

    u = _register(client, "Superadmin Prueba", verify=False)
    u["id"] = _set(u["email"], role="superadmin")
    return u



# --------------------------------------------------------------------------- bóveda: cadena, retención y purga
def test_evidence_chain_hold_and_purge(client, owner, admin):
    dog = _dog(client, owner)
    db = SessionLocal()
    try:
        obj = db.query(Dog).filter(Dog.id == dog["id"]).first()
        a = evidence.capture(db, kind="contenido_retirado", target_type="dog", target_id=obj.id, obj=obj,
                             owner_user_id=obj.owner_id, reason="spam")
        b = evidence.capture(db, kind="contenido_retirado", target_type="dog", target_id=obj.id, obj=obj,
                             owner_user_id=obj.owner_id, reason="spam")
        db.commit()
        assert b.prev_hash == a.row_hash
        evidence.set_legal_hold(db, b, True, "Orden de conservación de prueba", admin["id"])
        db.commit()
        far = datetime.datetime.utcnow() + datetime.timedelta(days=400)
        assert evidence.purge_expired(db, now=datetime.datetime.utcnow(), only_ids=[a.id, b.id]) == 0  # aún vigentes
        assert evidence.purge_expired(db, now=far, only_ids=[a.id, b.id]) == 1  # la retenida no se purga
        db.refresh(a)
        db.refresh(b)
        assert a.purged_at and a.storage_path is None and b.purged_at is None
        with pytest.raises(evidence.EvidenceError):
            evidence.read_bundle(a)
        assert evidence.read_bundle(b)["target"]["id"] == obj.id
    finally:
        db.close()
    out = client.get("/admin/cumplimiento/evidencia/verificar", headers=admin["h"])
    assert out.status_code == 200 and out.json()["ok"] is True, out.json()


def test_append_only_trigger_sql_blocks_delete_and_tampering(client, owner):
    from sqlalchemy import text

    from app.database import engine

    dog = _dog(client, owner)
    db = SessionLocal()
    try:
        obj = db.query(Dog).filter(Dog.id == dog["id"]).first()
        rec = evidence.capture(db, kind="contenido_retirado", target_type="dog", target_id=obj.id, obj=obj,
                               reason="spam")
        db.commit()
        rec_id = rec.id
    finally:
        db.close()
    # El SQL de la migración es válido y bloquea DELETE y cambios de hash (se prueba en una transacción revertida)
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(evidence.APPEND_ONLY_SQL))
            for stmt in (f"DELETE FROM evidence_records WHERE id = {rec_id}",
                         f"UPDATE evidence_records SET row_hash = 'x' WHERE id = {rec_id}"):
                nested = conn.begin_nested()
                with pytest.raises(Exception, match="solo"):
                    conn.execute(text(stmt))
                nested.rollback()
            nested = conn.begin_nested()
            conn.execute(text(f"UPDATE evidence_records SET legal_hold = true WHERE id = {rec_id}"))  # permitido
            nested.rollback()
        finally:
            trans.rollback()


# --------------------------------------------------------------------------- apelaciones
def test_appeal_works_with_suspended_account_and_needs_another_person(client, make_user, user, admin):
    bad = make_user("Cuenta Sancionada")
    bad_id = _uid(bad)
    dog = _dog(client, bad)
    rep = client.post("/reports", headers=user["h"], json={"target_type": "user", "target_id": bad_id,
                                                           "reason": "suplantacion"}).json()
    r = client.patch(f"/admin/reports/{rep['id']}", headers=admin["h"],
                     json={"status": "resolved", "action": "suspend_user"})
    assert r.status_code == 200, r.text
    action = _query(ModerationAction, ModerationAction.user_id == bad_id, ModerationAction.action == "suspend_user")[0]
    assert action.rule == "suplantacion" and action.notice_sent_at
    assert client.get("/users/me", headers=bad["h"]).status_code == 401  # sin sesión

    body = {"folio": action.folio, "argumentos": "No suplanté a nadie, es mi nombre real y tengo pruebas."}
    assert client.post("/cumplimiento/apelaciones", json=body, headers=_ip()).status_code == 404  # falta el correo
    assert client.post("/cumplimiento/apelaciones", json={**body, "email": "otra@pruebas.mx"},
                       headers=_ip()).status_code == 404
    ap = client.post("/cumplimiento/apelaciones", json={**body, "email": bad["email"]}, headers=_ip())
    assert ap.status_code == 201, ap.text
    folio = ap.json()["folio"]
    assert ap.json()["responde_antes_de"]
    st = client.get(f"/cumplimiento/apelaciones/{folio}", params={"email": bad["email"]}, headers=_ip())
    assert st.status_code == 200 and st.json()["estado"] == "En revisión"

    appeal = _query(ModerationAppeal, ModerationAppeal.folio == folio)[0]
    same = client.post(f"/admin/cumplimiento/apelaciones/{appeal.id}/resolver", headers=admin["h"],
                       json={"decision": "revocar", "nota": "Revisé los documentos de identidad."})
    assert same.status_code == 409  # quien decidió no resuelve su propia medida
    other = _staff(make_user)
    ok = client.post(f"/admin/cumplimiento/apelaciones/{appeal.id}/resolver", headers=other["h"],
                     json={"decision": "revocar", "nota": "Acreditó su identidad: la cuenta no suplanta a nadie."})
    assert ok.status_code == 200 and ok.json()["status"] == "reversed", ok.text
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.id == bad_id).first().is_active is True
        assert db.query(ModerationAction).filter(ModerationAction.id == action.id).first().status == "revoked"
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "appeal.reversed",
                                              AdminAuditLog.target_id == appeal.id).count() == 1
    finally:
        db.close()
    assert client.get(f"/dogs/{dog['id']}").status_code == 200


def test_appeal_window_and_copyright_actions_use_counter_notice(client, make_user, user, admin):
    owner = make_user("Dueño Ventana")
    dog = _dog(client, owner)
    rep = client.post("/reports", headers=user["h"], json={"target_type": "dog", "target_id": dog["id"],
                                                           "reason": "venta_animal"}).json()
    assert rep["id"]
    client.patch(f"/admin/reports/{rep['id']}", headers=admin["h"], json={"status": "resolved", "action": "hide_content"})
    action = _query(ModerationAction, ModerationAction.content_report_id == rep["id"])[0]
    db = SessionLocal()
    try:
        db.query(ModerationAction).filter(ModerationAction.id == action.id).update(
            {"appeal_until": datetime.datetime.utcnow() - datetime.timedelta(days=1)})
        db.commit()
    finally:
        db.close()
    late = client.post("/cumplimiento/apelaciones", headers=_ip(), json={
        "folio": action.folio, "email": owner["email"], "argumentos": "No vendía al perro, pedía ayuda para su comida."})
    assert late.status_code == 400 and "plazo" in late.json()["detail"]


# --------------------------------------------------------------------------- derechos de autor
def test_copyright_notice_removal_staydown_counter_notice_and_restore(client, owner, admin, jpeg):
    data = jpeg(_seed())
    url = _upload(client, owner, data).json()["url"]
    dog = _dog(client, owner, photos=[url])

    bad = _notice_payload(url, bajo_protesta=False)
    assert client.post("/cumplimiento/derechos-autor/avisos", json=bad, headers=_ip()).status_code == 400
    r = client.post("/cumplimiento/derechos-autor/avisos", json=_notice_payload(url), headers=_ip())
    assert r.status_code == 201, r.text
    assert r.json()["folio"].startswith("DA-") and len(r.json()["sha256"]) == 64 and r.json()["estado"] == "received"
    notice = _query(CopyrightNotice, CopyrightNotice.folio == r.json()["folio"])[0]
    assert (notice.target_type, notice.target_id, notice.photo_urls) == ("dog", dog["id"], [url])
    assert notice.uploader_user_id == _uid(owner)
    # Representante sin documento: incompleto (no se retira mientras tanto)
    rep = client.post("/cumplimiento/derechos-autor/avisos", headers=_ip(),
                      json=_notice_payload(url, caracter="representante", representado="Agencia Foto S.A."))
    assert rep.status_code == 201 and rep.json()["estado"] == "incomplete"

    out = client.post(f"/admin/cumplimiento/derechos-autor/{notice.id}/retirar", headers=admin["h"], json={})
    assert out.status_code == 200, out.text
    assert out.json()["status"] == "removed" and out.json()["strikes"] == 1
    assert _dog_row(dog["id"]).is_hidden is True
    action = _query(ModerationAction, ModerationAction.copyright_notice_id == notice.id)[0]
    assert action.action == "copyright_removal" and action.appeal_until is None
    notes = _query(Notification, Notification.user_id == _uid(owner))
    assert any("contra-aviso" in n.body and "avisos de derechos de autor procedentes" in n.body.lower() for n in notes)
    assert any(n.type == "copyright_notice_copy" and notice.folio in n.body for n in notes)

    # Staydown: la misma imagen (aunque esté recomprimida o reducida) no se puede volver a subir; otra sí
    assert _upload(client, owner, data).status_code == 400
    assert _upload(client, owner, _resized(data)).status_code == 400
    assert _upload(client, owner, jpeg(_seed())).status_code == 200

    # Apelación no: se usa el contra-aviso
    assert client.post("/cumplimiento/apelaciones", headers=_ip(), json={
        "folio": action.folio, "email": owner["email"],
        "argumentos": "La foto es mía y la tomé yo con mi teléfono."}).status_code == 400

    counter = {"folio": notice.folio, "email_cuenta": "otra@pruebas.mx", "nombre": "Dueña Prueba", "caracter": "propio",
               "domicilio": "Av. Siempre Viva 742, Puebla", "fundamento": "licencia",
               "detalle": "La fotógrafa me dio permiso por escrito el 1 de octubre.", "bajo_protesta": True,
               "conoce_sancion": True}
    assert client.post("/cumplimiento/derechos-autor/contra-avisos", json=counter, headers=_ip()).status_code == 404
    ca = client.post("/cumplimiento/derechos-autor/contra-avisos", json={**counter, "email_cuenta": owner["email"]},
                     headers=_ip())
    assert ca.status_code == 201, ca.text
    assert ca.json()["folio"].startswith("CA-")
    restore_from = datetime.datetime.fromisoformat(ca.json()["restauracion_desde"])
    restore_until = datetime.datetime.fromisoformat(ca.json()["restauracion_hasta"])
    assert restore_until - restore_from >= datetime.timedelta(days=5)
    assert restore_from - datetime.datetime.utcnow() >= datetime.timedelta(days=12)  # 10 días hábiles
    assert client.post("/cumplimiento/derechos-autor/contra-avisos", json={**counter, "email_cuenta": owner["email"]},
                       headers=_ip()).status_code == 409

    # La tarea diaria restaura a partir del día hábil 10 si no se acreditó un procedimiento
    db = SessionLocal()
    try:
        assert tasks.restore_due_copyright(db, now=restore_from - datetime.timedelta(hours=1)) == 0
        assert tasks.restore_due_copyright(db, now=restore_from + datetime.timedelta(minutes=1)) >= 1
        n = db.query(CopyrightNotice).filter(CopyrightNotice.id == notice.id).first()
        assert n.status == "restored" and n.restored_at
        assert lm.copyright_strikes(db, _uid(owner)) == 0  # un aviso deja de contar si prospera el contra-aviso
    finally:
        db.close()
    assert _dog_row(dog["id"]).is_hidden is False
    staydown.invalidate_cache()
    assert _upload(client, owner, data).status_code == 200


def test_repeat_infringer_suspension_cancellation_and_phone_ban(client, make_user, admin, jpeg):
    infractor = make_user("Infractor Reincidente")
    ids = []
    for _ in range(3):
        url = _upload(client, infractor, jpeg(_seed())).json()["url"]
        dog = _dog(client, infractor, photos=[url])
        n = client.post("/cumplimiento/derechos-autor/avisos", json=_notice_payload(f"/app/?dog={dog['id']}"),
                        headers=_ip()).json()
        ids.append(_query(CopyrightNotice, CopyrightNotice.folio == n["folio"])[0].id)
    assert client.post(f"/admin/cumplimiento/derechos-autor/{ids[0]}/retirar", headers=admin["h"], json={}).status_code == 200
    second = client.post(f"/admin/cumplimiento/derechos-autor/{ids[1]}/retirar", headers=admin["h"], json={})
    assert second.status_code == 200 and second.json()["strikes"] == 2
    uid = _uid(infractor)
    susp = _query(ModerationAction, ModerationAction.user_id == uid, ModerationAction.action == "suspend_user")[0]
    assert susp.duration_days == settings.copyright_suspension_days and susp.ends_at
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.id == uid).first().is_active is False
        # Al terminar la suspensión temporal la cuenta vuelve
        assert lm.lift_expired_suspensions(db, now=susp.ends_at + datetime.timedelta(minutes=1)) >= 1
        assert db.query(User).filter(User.id == uid).first().is_active is True
    finally:
        db.close()
    third = client.post(f"/admin/cumplimiento/derechos-autor/{ids[2]}/retirar", headers=admin["h"], json={})
    assert third.status_code == 200 and third.json()["strikes"] == 3
    assert _query(ModerationAction, ModerationAction.user_id == uid, ModerationAction.action == "cancel_account")

    # Bloqueo de nuevos registros: el teléfono de la cuenta cancelada no se puede verificar en otra
    newcomer = make_user("Cuenta Nueva", verify=False, phone=infractor["phone"].removeprefix("+52"))
    sent = client.post("/users/me/phone/send-code", headers=newcomer["hip"])
    assert sent.status_code == 403 and "cancelada" in sent.json()["detail"]


# --------------------------------------------------------------------------- autoridades
def test_authority_registry_levels_preservation_and_contact(client, owner, admin, monkeypatch):
    monkeypatch.setattr(settings, "authority_contact_email", "autoridades@guauwoow.com")
    monkeypatch.setattr(settings, "authority_contact_phone", "+52 55 0000 0000")
    contact = client.get("/cumplimiento/autoridades/contacto").json()
    assert contact["configurado"] and contact["correo"] == "autoridades@guauwoow.com"
    assert contact["disponibilidad"].startswith("24 horas")

    owner_id = _uid(owner)
    body = {"kind": "comunicaciones", "authority_name": "Fiscalía General de Justicia de la CDMX",
            "authority_type": "ministerio_publico", "case_number": "CI-FDS/123/2026",
            "legal_basis": "CNPP art. 212", "requested_data": "Mensajes del chat de la cuenta",
            "targets": [{"type": "user", "id": owner_id}], "involves_minor": True}
    assert client.post("/admin/cumplimiento/autoridades", json=body, headers=owner["h"]).status_code == 403
    r = client.post("/admin/cumplimiento/autoridades", json=body, headers=admin["h"])
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["level"] == 2 and item["folio"].startswith("AUT-")
    received = datetime.datetime.fromisoformat(item["received_at"])
    first = datetime.datetime.fromisoformat(item["first_response_due_at"])
    assert first - received == datetime.timedelta(minutes=settings.authority_first_response_urgent_minutes)

    # Nivel 2 sin autorización judicial: no se entrega
    deny = client.patch(f"/admin/cumplimiento/autoridades/{item['id']}", headers=admin["h"],
                        json={"status": "entregado", "authenticity_verified": True})
    assert deny.status_code == 400 and "autorización judicial" in deny.json()["detail"]
    # Conservación inmediata
    keep = client.post(f"/admin/cumplimiento/autoridades/{item['id']}/preservar", headers=admin["h"])
    assert keep.status_code == 200 and keep.json()["copias_nuevas"], keep.text
    rec = _query(EvidenceRecord, EvidenceRecord.id == keep.json()["copias_nuevas"][0])[0]
    assert rec.kind == "preservacion" and rec.legal_hold and rec.authority_request_id == item["id"]
    ok = client.patch(f"/admin/cumplimiento/autoridades/{item['id']}", headers=admin["h"],
                      json={"status": "entregado", "authenticity_verified": True, "judicial_order": True,
                            "decision": "Se entregan los mensajes señalados en la orden.", "user_notified": False,
                            "notice_withheld_reason": "La autoridad lo prohibió"})
    assert ok.status_code == 200 and ok.json()["responded_at"], ok.text
    db = SessionLocal()
    try:
        actions = {a.action for a in db.query(AdminAuditLog).filter(AdminAuditLog.target_type == "authority_request",
                                                                    AdminAuditLog.target_id == item["id"])}
        assert {"authority.create", "authority.update", "authority.preserve"} <= actions
    finally:
        db.close()
    summary = client.get("/admin/cumplimiento/resumen", headers=admin["h"])
    assert summary.status_code == 200 and "reportes_abiertos" in summary.json()


# --------------------------------------------------------------------------- medidas del equipo y cola
def test_team_hide_has_statement_of_reasons_and_queue_order(client, owner, user, admin):
    dog = _dog(client, owner)
    r = client.patch(f"/admin/content/dog/{dog['id']}", headers=admin["h"], json={"hidden": True, "rule": "venta_animal"})
    assert r.status_code == 200, r.text
    action = _query(ModerationAction, ModerationAction.target_type == "dog", ModerationAction.target_id == dog["id"])[-1]
    assert (action.detection, action.rule, action.status) == ("equipo", "venta_animal", "active") and action.evidence_id
    note = _query(Notification, Notification.user_id == _uid(owner), Notification.type == "content_hidden")[-1]
    assert "una revisión de nuestro equipo" in note.body and "Venta o cobro por un animal" in note.body
    assert client.patch(f"/admin/content/dog/{dog['id']}", headers=admin["h"], json={"hidden": False}).status_code == 200
    assert _query(ModerationAction, ModerationAction.id == action.id)[0].status == "lifted"

    # La cola va por prioridad: menores antes que urgentes y que el resto
    other = _dog(client, owner)
    client.post("/reports", headers=user["h"], json={"target_type": "dog", "target_id": other["id"], "reason": "spam"})
    client.post("/reports", headers=user["h"], json={"target_type": "dog", "target_id": other["id"], "reason": "maltrato"})
    queue = client.get("/admin/cumplimiento/cola", headers=admin["h"], params={"limit": 200}).json()
    priorities = [x["priority"] for x in queue]
    assert priorities == sorted(priorities)
    assert all("overdue" in x and "reason_label" in x for x in queue)
    db = SessionLocal()
    try:
        summary = tasks.overdue_summary(db, now=datetime.datetime.utcnow() + datetime.timedelta(days=30))
        assert summary["reportes"] >= 1
    finally:
        db.close()


def test_authority_ordered_removal_blocks_images_and_cites_order(client, owner, admin, jpeg):
    data = jpeg(_seed())
    url = _upload(client, owner, data).json()["url"]
    dog = _dog(client, owner, photos=[url])
    r = client.patch(f"/admin/content/dog/{dog['id']}", headers=admin["h"], json={
        "hidden": True, "rule": "contenido_intimo", "detection": "autoridad",
        "notes": "Orden de protección del Ministerio Público, carpeta CI-123/2026"})
    assert r.status_code == 200, r.text
    note = _query(Notification, Notification.user_id == _uid(owner), Notification.type == "content_hidden")[-1]
    assert "una orden de autoridad" in note.body and "CI-123/2026" in note.body
    assert _upload(client, owner, data).status_code == 400  # staydown
