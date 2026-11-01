"""Costuras entre las áreas de cumplimiento (fase de integración):

- Descartar desde la cola general el reporte de una retención automática (reglas de negocio) libera la publicación.
- Una revocación o limitación del centro de solicitudes deja la constancia con el propósito estándar de K-PREF.
- Borrar los datos de WhatsApp desde una solicitud conserva la marca de baja del número (el bot no vuelve a escribir).
- «Soy el autor» (POST /facebook/author-removal) se purga cada hora con el mismo plazo que los retiros del centro
  de solicitudes, dentro de las 72 h que promete contenido-importado.html.
"""
import datetime

from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.models import BotInteraction, ComplianceRequest, ConsentRecord, ContentReport, Dog, LostReport, User
from app.services import facebook_groups as fbg, reglas, solicitudes
from test_tienda import admin  # noqa: F401 - fixture de admin


def _dog(client, who, **extra):
    body = {"name": "Canela", "description": "Muy cariñosa, esterilizada y vacunada.", "city": "Puebla", **extra}
    r = client.post("/dogs", headers=who["h"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_dismissing_automatic_hold_report_releases_post(client, owner, user, admin):  # noqa: F811
    held = _dog(client, owner, description="Se entrega con cuota de recuperación de $500.")
    assert held["is_hidden"] is True
    db = SessionLocal()
    try:
        report = db.query(ContentReport).filter(ContentReport.target_type == "dog", ContentReport.target_id == held["id"],
                                                ContentReport.reason == reglas.HOLD_REPORT_REASON,
                                                ContentReport.status == "open").one()
        report_id = report.id
    finally:
        db.close()
    r = client.patch(f"/admin/reports/{report_id}", headers=admin["h"], json={"status": "dismissed", "notes": "Sin cobro"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dismissed"
    db = SessionLocal()
    try:
        dog = db.get(Dog, held["id"])
        assert dog.review_hold == reglas.HOLD_RELEASED and dog.is_hidden is False
    finally:
        db.close()
    assert client.get(f"/dogs/{held['id']}", headers=user["h"]).status_code == 200


def _request(db, user, permisos, kind="revocacion", phone=None):
    req = ComplianceRequest(
        folio=f"PF-T-{datetime.datetime.utcnow().timestamp():.6f}"[-20:], kind=kind, name=user.full_name,
        email=user.email, phone=phone, description="Prueba de integración", details={"permisos": permisos},
        user_id=user.id, received_at=datetime.datetime.utcnow(), respond_by=datetime.datetime.utcnow(),
    )
    db.add(req)
    db.flush()
    return req


def test_revocation_records_standard_consent_purposes(client, make_user):
    u = make_user("Titular Revocación")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == u["email"]).one()
        user.marketing_opt_in = True
        user.notify_nearby = True
        db.commit()
        req = _request(db, user, ["correos", "alertas"])
        applied = solicitudes.apply_permission_changes(db, req, user, datetime.datetime.utcnow())
        db.commit()
        assert {"marketing_opt_in", "notify_nearby"} <= set(applied)
        rows = db.query(ConsentRecord).filter(ConsentRecord.user_id == user.id, ConsentRecord.channel == "solicitud").all()
        assert {r.purpose for r in rows} == {"email_marketing", "notify_nearby"}
        assert all(r.granted is False for r in rows)
        db.refresh(user)
        assert user.marketing_opt_in is False and user.notify_nearby is False
    finally:
        db.rollback()
        db.close()


def test_whatsapp_data_deletion_keeps_opt_out_mark():
    phone = "+52551" + datetime.datetime.utcnow().strftime("%H%M%S%f")[:7]
    db = SessionLocal()
    try:
        db.add(BotInteraction(phone=phone, stage="report_photo", data={"name": "Ana", "lat": 19.4}, last_message="hola"))
        db.commit()
        out = solicitudes.delete_whatsapp_data(db, phone, datetime.datetime.utcnow())
        db.commit()
        assert out["conversaciones"] == 1
        row = db.query(BotInteraction).filter(BotInteraction.phone == phone).one()
        assert row.data == {} and row.last_message is None and row.stage == "welcome"
        assert row.opted_out_at is not None  # el bot no le vuelve a escribir
    finally:
        db.query(BotInteraction).filter(BotInteraction.phone == phone).delete()
        db.commit()
        db.close()


def test_author_removals_purged_hourly_within_promise():
    entry = celery_app.conf.beat_schedule["imported-author-removals-hourly"]
    assert entry["task"] == "app.tasks.facebook_groups.purge_author_removals"
    from app.tasks import facebook_groups as fb_tasks  # registra las tareas del módulo

    assert fb_tasks.purge_author_removals.name == "app.tasks.facebook_groups.purge_author_removals"
    # Hora a hora con corte de IMPORTED_REMOVAL_PURGE_HOURS: el peor caso queda por debajo de las 72 h
    assert settings.imported_removal_purge_hours + 1 < fbg.AUTHOR_REMOVAL_PURGE_HOURS
    db = SessionLocal()
    try:
        report = LostReport(dog_name="Importado de prueba", report_type="lost", status="active", source="facebook",
                            is_hidden=True, description="Texto original", external_url=None, city="Puebla",
                            created_at=datetime.datetime.utcnow())
        db.add(report)
        db.flush()
        removal = ContentReport(target_type="lost_report", target_id=report.id, reason=fbg.AUTHOR_REMOVAL_REASON,
                                status="open", details="Retiro sin cuenta",
                                created_at=datetime.datetime.utcnow() - datetime.timedelta(
                                    hours=settings.imported_removal_purge_hours + 1))
        db.add(removal)
        db.flush()
        # Solo se borra solo si la persona autora confirmó su correo (solicitudes.imported_removal_ready)
        from app.models import ComplianceRequest
        from app.services import solicitudes as sol

        now = datetime.datetime.utcnow()
        db.add(ComplianceRequest(
            folio=sol.next_folio(db, now=now), kind="retiro_importado", status="recibida", name="Persona autora",
            email="autora@pruebas.mx", channel="web", description="Retiro de mi publicación importada",
            details={"relacion": "autor"}, lost_report_id=report.id, content_report_id=removal.id, received_at=now,
            respond_by=now, identity_verified_at=now, identity_method="correo", created_at=now, updated_at=now))
        db.commit()
        assert report.id in fbg.purge_imported_reports(db, report_ids=[report.id])
        db.refresh(report)
        assert report.purged_at is not None
    finally:
        db.close()
