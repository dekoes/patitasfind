"""Correcciones de revisión (pagos/tienda, moderación/avisos): la alerta cercana se reintenta sin perderse
y la lista pública de productos pagina como espera la app."""
import random

import pytest

from app import cache
from app.database import SessionLocal
from app.models import LostReport, Notification, User
from app.services import notify
from app.tasks import notifications as notif_tasks


def _spot():
    """Coordenadas aleatorias en el norte de México (lejos de los datos demo de la CDMX)."""
    return round(random.uniform(25.0, 29.0), 5), round(random.uniform(-109.0, -101.0), 5)


def _uid(email) -> int:
    db = SessionLocal()
    try:
        return db.query(User.id).filter(User.email == email).scalar()
    finally:
        db.close()


def _alerts(user_id):
    db = SessionLocal()
    try:
        return db.query(Notification).filter(Notification.user_id == user_id, Notification.type == "nearby_alert").all()
    finally:
        db.close()


def _report(lat, lon, **extra) -> int:
    db = SessionLocal()
    try:
        r = LostReport(reporter_id=None, dog_name="Canelo", report_type="lost", status="active", source="whatsapp",
                       latitude=lat, longitude=lon, city="Pruebas", photos=[], **extra)
        db.add(r)
        db.commit()
        return r.id
    finally:
        db.close()


# --------------------------------------------------------------------------- alerta cercana: reintentos
def test_nearby_alert_task_declares_retries():
    assert notif_tasks.notify_nearby_report.max_retries >= 1
    assert notif_tasks.notify_nearby_report.default_retry_delay > 0


def test_nearby_alert_failure_releases_lock_and_daily_cap_then_retries(client, make_user, monkeypatch):
    r = cache._get_redis()
    assert r is not None, "la suite corre con Redis (REDIS_URL) para probar el candado por reporte"
    lat, lon = _spot()
    near = make_user("Vecina reintento")
    assert client.patch("/users/me", headers=near["h"], json={"latitude": lat, "longitude": lon,
                                                              "notify_nearby": True}).status_code == 200
    uid = _uid(near["email"])
    rid = _report(lat + 0.005, lon)
    lock_key = f"nearby:report:{rid}"
    cap_key = notif_tasks._cap_key(uid)

    # Primer intento: la base/el envío falla a la mitad -> la tarea pide reintento (al llamarla directo, relanza el error)
    original = notify.notify_user
    state = {"fail": True}

    def flaky(*a, **kw):
        if state["fail"]:
            raise RuntimeError("se cayó la base de datos")
        return original(*a, **kw)

    monkeypatch.setattr(notify, "notify_user", flaky)
    with pytest.raises(RuntimeError):
        notif_tasks.notify_nearby_report(rid)
    assert r.get(lock_key) is None, "el candado del reporte debe liberarse para que el reintento sí avise"
    assert int(r.get(cap_key) or 0) == 0, "el tope diario no debe contar avisos que nunca se enviaron"
    assert not _alerts(uid)

    # Reintento: ahora sí llega el aviso y el reporte queda marcado como listo. ">= 1": en la base de desarrollo
    # compartida pueden quedar personas de corridas anteriores a menos de 5 km del punto al azar.
    state["fail"] = False
    assert notif_tasks.notify_nearby_report(rid) >= 1
    assert r.get(lock_key) == "listo"
    assert int(r.get(cap_key)) == 1
    alerts = _alerts(uid)
    assert len(alerts) == 1 and alerts[0].data["report_id"] == rid

    # Una vez listo, volver a encolar la tarea no repite el aviso
    assert notif_tasks.notify_nearby_report(rid) == 0
    assert len(_alerts(uid)) == 1


def test_nearby_alert_skipped_report_leaves_no_lock(client, make_user):
    r = cache._get_redis()
    assert r is not None
    lat, lon = _spot()
    rid = _report(lat, lon, is_hidden=True)
    assert notif_tasks.notify_nearby_report(rid) == 0
    assert r.get(f"nearby:report:{rid}") is None


# --------------------------------------------------------------------------- tienda: paginado que usa la app
def test_products_list_pages_with_skip_and_limit_100(client):
    """La app recorre /products?skip=N&limit=100 hasta recibir menos de 100 filas."""
    r = client.get("/products", params={"skip": 0, "limit": 100})
    assert r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) <= 100
    assert client.get("/products", params={"limit": 101}).status_code == 422
    assert client.get("/products", params={"skip": 100000, "limit": 100}).json() == []
