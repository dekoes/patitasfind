"""Correcciones de seguridad y privacidad: el radio público se evalúa sobre coordenadas aproximadas (no se
puede bisecar la ubicación exacta), documentos y webhook de WhatsApp sin E/S bloqueante en el event loop, y
el panel del refugio sin acciones que solo puede hacer un admin."""
import os
import random
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Float, literal, select

from app.database import SessionLocal
from app.models import Dog
from app.routers import documents, whatsapp
from app.services import geo, privacy
from app.services.geo import haversine_km

# Raíz del repo: en CI es el checkout completo; dentro del contenedor (/app = backend) no existe app/
REPO = Path(os.environ.get("PATITASFIND_REPO") or Path(__file__).resolve().parents[2])
APP_JS = REPO / "app" / "app.js"
needs_repo = pytest.mark.skipif(not APP_JS.exists(), reason="app/app.js no está disponible (contenedor)")
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def _spot():
    """Punto en el Pacífico a ~0.7 km de su versión aproximada (y lejos del borde de redondeo)."""
    lat = round(random.uniform(-20, 20), 2) + 0.0046
    lon = round(random.uniform(-150, -120), 2) - 0.0044
    return lat, lon


def _phone():
    return "52155" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "123456"))


# --------------------------------------------------------------------------- radio público sin bisección
def test_coarse_sql_matches_python_round():
    db = SessionLocal()
    try:
        rnd = random.Random(3)
        for _ in range(200):
            v = rnd.randint(-1_800_000, 1_800_000) / 10_000
            if round(abs(v) * 10_000) % 100 == 50:
                continue  # empate exacto (x.xx50): Python redondea al par y Postgres hacia afuera
            got = db.execute(select(geo.coarse_sql(literal(v, Float)))).scalar()
            assert got == privacy.coarse(v), v
    finally:
        db.close()


def test_public_radius_uses_coarse_coordinates(client, owner, user):
    lat, lon = _spot()
    r = client.post("/dogs", headers=owner["h"], json={"name": "Bisección", "latitude": lat, "longitude": lon})
    assert r.status_code == 201, r.text
    dog_id = r.json()["id"]
    # Punto de consulta 1 km al norte: el exacto queda más cerca que el aproximado, así que un radio
    # intermedio distingue cuál de los dos usa el filtro
    q_lat, q_lon = lat + 1.0 / 111.0, lon
    d_exact = haversine_km(q_lat, q_lon, lat, lon)
    d_public = haversine_km(q_lat, q_lon, privacy.coarse(lat), privacy.coarse(lon))
    assert d_exact + 0.3 < d_public
    mid = (d_exact + d_public) / 2
    # Otro perrito justo en el punto de consulta: así siempre hay resultados en el radio y apply_distance
    # no cae al listado sin filtro de distancia
    anchor = client.post("/dogs", headers=owner["h"], json={"name": "Ancla", "latitude": q_lat, "longitude": q_lon})
    assert anchor.status_code == 201, anchor.text

    def nearby(radius, **params):
        r = client.get("/dogs/nearby", params={"lat": q_lat, "lon": q_lon, "radius_km": radius, "limit": 100, **params})
        assert r.status_code == 200, r.text
        return {d["id"]: d["distance_km"] for d in r.json()}

    # Con las coordenadas exactas sí entraría: bisecando radius_km se recuperaría la distancia real
    assert dog_id not in nearby(mid)
    assert dog_id not in nearby(d_public - 0.05)
    assert nearby(d_public + 0.05)[dog_id] == round(d_public, 1)  # el borde es la distancia pública
    disc = client.get("/dogs/discover", headers=user["h"], params={"lat": q_lat, "lon": q_lon, "radius_km": mid, "limit": 100})
    assert disc.status_code == 200 and dog_id not in {d["id"] for d in disc.json()}

    # El dueño y los admins siguen teniendo el radio exacto (exact=True)
    db = SessionLocal()
    try:
        q = db.query(Dog).filter(Dog.id == dog_id)
        exact_q, _ = geo.within_radius(q, Dog, q_lat, q_lon, mid, exact=True)
        public_q, _ = geo.within_radius(q, Dog, q_lat, q_lon, mid)
        assert exact_q.count() == 1 and public_q.count() == 0
        dog = db.get(Dog, dog_id)
        assert geo.distance_to(dog, q_lat, q_lon) == round(d_exact, 1)
        assert geo.distance_to(dog, q_lat, q_lon, exact=False) == round(d_public, 1)
        assert geo.nearest(q, Dog, q_lat, q_lon, d_public + 0.05)[0].distance_km == round(d_public, 1)
    finally:
        db.close()


def test_lost_reports_radius_uses_coarse_coordinates(client, owner):
    lat, lon = _spot()
    r = client.post("/lost-reports", headers=owner["h"],
                    json={"dog_name": "Bisección", "report_type": "lost", "latitude": lat, "longitude": lon})
    assert r.status_code == 201, r.text
    report_id = r.json()["id"]
    # El listado ya aproxima el punto de consulta: se pregunta desde un punto de la malla de 0.01°
    q_lat, q_lon = privacy.coarse(lat) + 0.01, privacy.coarse(lon)
    d_exact = haversine_km(q_lat, q_lon, lat, lon)
    d_public = haversine_km(q_lat, q_lon, privacy.coarse(lat), privacy.coarse(lon))
    assert d_exact + 0.2 < d_public
    mid = (d_exact + d_public) / 2
    # Otro reporte en el punto de consulta para que el radio nunca quede vacío (sin caer al listado completo)
    anchor = client.post("/lost-reports", headers=owner["h"],
                         json={"dog_name": "Ancla", "report_type": "found", "latitude": q_lat, "longitude": q_lon})
    assert anchor.status_code == 201, anchor.text

    def listed(radius):
        r = client.get("/lost-reports", params={"lat": q_lat, "lon": q_lon, "radius_km": radius, "limit": 500})
        assert r.status_code == 200, r.text
        return {x["id"]: x["distance_km"] for x in r.json()}

    assert report_id not in listed(mid)
    assert listed(d_public + 0.05)[report_id] == round(d_public, 1)


# --------------------------------------------------------------------------- E/S fuera del event loop
def _spy_threadpool(monkeypatch, module):
    seen = []
    real = module.run_in_threadpool

    async def spy(func, *args, **kwargs):
        seen.append(getattr(func, "__name__", repr(func)))
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(module, "run_in_threadpool", spy)
    return seen


def test_upload_document_runs_blocking_io_in_threadpool(client, user, monkeypatch):
    seen = _spy_threadpool(monkeypatch, documents)
    monkeypatch.setattr(documents, "MAX_DOCUMENTS_PER_HOUR", 2)
    upload = lambda: client.post("/upload/document", headers=user["h"], files={"file": ("acta.pdf", PDF, "application/pdf")})
    ids = []
    try:
        r = upload()
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
        # La sesión de BD se suelta y el límite (Redis) se consulta en el threadpool, antes de procesar el archivo
        assert seen == ["close", "check", "_store_document"]
        r = upload()
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
        r = upload()
        assert r.status_code == 429 and r.headers.get("Retry-After")
        assert r.json()["detail"] == "Subiste demasiados documentos. Espera un rato e inténtalo de nuevo."
    finally:
        for doc_id in ids:
            documents.delete_document(doc_id)


def test_whatsapp_simulator_runs_off_event_loop(client, monkeypatch):
    seen = _spy_threadpool(monkeypatch, whatsapp)
    r = client.post("/whatsapp/webhook", json={"phone": _phone(), "message": "hola"})
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "menu"
    assert seen == ["process_message"]


def test_enqueue_events_marks_window_and_dispatches(monkeypatch):
    calls = []
    monkeypatch.setattr(whatsapp.whatsapp_api, "mark_inbound", lambda phone: calls.append(("inbound", phone)))
    monkeypatch.setattr(whatsapp, "dispatch",
                        lambda task, event, background_tasks=None: calls.append((task, event["phone"])))
    whatsapp._enqueue_events([{"phone": "521"}, {"phone": "522"}], None)
    task = "app.tasks.whatsapp.process_whatsapp_event"
    assert calls == [("inbound", "521"), (task, "521"), ("inbound", "522"), (task, "522")]


# --------------------------------------------------------------------------- panel del refugio
@needs_repo
def test_refuge_panel_has_no_admin_only_point_actions():
    js = APP_JS.read_text(encoding="utf-8")
    assert "mr-rescue" not in js
    # rescue/adopt/foster son de admins (require_admin): el refugio no debe tener botones que den 403
    assert not re.search(r"/refuges/\$\{[^}]+\}/(rescue|adopt|foster)\b", js)
