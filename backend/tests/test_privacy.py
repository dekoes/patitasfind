"""Requisitos del Aviso de Privacidad: donante anónimo, baja del bot de WhatsApp, presupuesto con consentimiento."""
import uuid

from app.config import settings
from app.database import SessionLocal
from app.models import BotInteraction, LostReport, Notification, PointLog, Refuge
from app.services import matching, whatsapp_api


def _refuge_for(owner_email: str):
    db = SessionLocal()
    try:
        from app.models import User
        u = db.query(User).filter(User.email == owner_email).first()
        ref = Refuge(user_id=u.id, name=f"Refugio {uuid.uuid4().hex[:5]}", status="approved")
        db.add(ref)
        db.commit()
        return ref.id, u.id
    finally:
        db.close()


def test_donation_anonymous_by_default(client, user, owner):
    if settings.payments_enabled:
        return
    refuge_id, owner_id = _refuge_for(owner["email"])
    me = client.get("/users/me", headers=user["h"]).json()
    d1 = client.post("/payments/donations", headers=user["h"], json={"accepted_policy": True, "refuge_id": refuge_id, "amount": 50}).json()
    d2 = client.post("/payments/donations", headers=user["h"],
                     json={"accepted_policy": True, "refuge_id": refuge_id, "amount": 60, "share_name": True}).json()
    assert d1["status"] == "approved" and d2["status"] == "approved"
    db = SessionLocal()
    try:
        bodies = [n.body for n in db.query(Notification).filter(Notification.user_id == owner_id,
                                                                Notification.type == "donation_received")]
        logs = [p.description for p in db.query(PointLog).filter(PointLog.refuge_id == refuge_id)]
    finally:
        db.close()
    assert any(b.startswith("Donante anónimo donó $50") for b in bodies)
    assert any(b.startswith(f"{me['full_name']} donó $60") for b in bodies)
    # Los donativos ya no dejan registro de puntos (donativos.html §12): ni con nombre ni anónimos
    assert not any("Donación" in l for l in logs) and not any(me["full_name"] in l for l in logs)
    mine = client.get("/payments/donations/me", headers=user["h"]).json()
    assert {d["share_name"] for d in mine} == {True, False}


def test_whatsapp_opt_out_and_resubscribe(client, monkeypatch):
    phone = "52155" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "123456"))
    sim = lambda msg: client.post("/whatsapp/webhook", json={"phone": phone, "message": msg}).json()
    assert sim("hola")["stage"] == "menu"
    r = sim("Bája")
    assert r["response"].startswith("Listo, ya no te enviaremos avisos por WhatsApp") and "ALTA" in r["response"]
    assert matching.is_whatsapp_opted_out(phone) is True
    # Dado de baja puede seguir usando el bot (la conversación la inicia la persona), sin avisos proactivos
    assert sim("1")["stage"] == "photos"
    assert matching.is_whatsapp_opted_out(phone) is True
    # Las alertas de coincidencia no se envían
    sent = []
    monkeypatch.setattr(whatsapp_api, "send_text", lambda to, body: sent.append(to) or True)
    target = LostReport(id=999999, contact_phone=phone, report_type="lost", dog_name="x")
    new = LostReport(id=999998, report_type="found", dog_name="y")
    matching._notify_whatsapp(target, new, 90, f"test-{phone}")
    assert sent == []
    # HOLA reabre la conversación pero no reactiva los avisos; solo ALTA (comunicaciones.html §5)
    assert sim("HOLA")["stage"] == "menu"
    assert matching.is_whatsapp_opted_out(phone) is True
    assert "BAJA" in sim("ALTA")["response"]
    assert matching.is_whatsapp_opted_out(phone) is False
    assert sim("stop")["response"].startswith("Listo")
    db = SessionLocal()
    try:
        assert db.query(BotInteraction).filter(BotInteraction.phone == phone).first().opted_out_at is not None
    finally:
        db.close()


def test_budget_requires_consent(client, user, owner):
    dog = client.post("/dogs", headers=owner["h"], json={"name": "Presu", "size": "Grande"}).json()
    match = client.post(f"/dogs/{dog['id']}/like", headers=user["h"]).json()
    r = client.post(f"/matches/{match['id']}/apply", headers=user["h"],
                    json={"answers": {"housing": "casa_con_jardin", "budget": "bajo"}})
    assert r.status_code == 200 and "budget" not in r.json()["answers"] and r.json()["compatibility"] is not None
    r = client.post(f"/matches/{match['id']}/apply", headers=user["h"],
                    json={"answers": {"housing": "casa_con_jardin", "budget": "alto", "budget_consent": True}})
    assert r.json()["answers"]["budget"] == "alto"
    r = client.post(f"/matches/{match['id']}/apply", headers=user["h"], json={"answers": {"housing": "casa_con_jardin"}})
    assert r.status_code == 200 and r.json()["compatibility"] is not None
