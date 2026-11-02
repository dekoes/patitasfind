"""Rendimiento: distancia en SQL, caché, consultas acotadas, WebSocket y expiración de reportes."""
import asyncio
import contextlib
import datetime
import math
import random

import pytest
from sqlalchemy import event

from app import cache
from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal, engine
from app.models import Dog, LostReport, User
from app.services import geo, matching, realtime, vision
from app.services.geo import haversine_km
from app.tasks.reports import expire_stale_reports_now
from tests.conftest import random_ip


# --------------------------------------------------------------------------- utilidades
def _spot():
    """Un punto en el Pacífico (sin datos de otras pruebas alrededor)."""
    return round(random.uniform(-20, 20), 4), round(random.uniform(-150, -120), 4)


def _offset(lat, lon, km, bearing_deg):
    """Punto a `km` de (lat, lon) en dirección `bearing_deg` (esfera)."""
    d = km / geo.EARTH_RADIUS_KM
    b = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def _user_id(client, u) -> int:
    return client.get("/users/me", headers=u["h"]).json()["id"]


def _insert_dogs(owner_id, points, **extra) -> list[int]:
    db = SessionLocal()
    try:
        dogs = [Dog(owner_id=owner_id, name=f"PERF-{i}", status="available", photos=[], latitude=la, longitude=lo,
                    **extra) for i, (la, lo) in enumerate(points)]
        db.add_all(dogs)
        db.commit()
        return [d.id for d in dogs]
    finally:
        db.close()


@contextlib.contextmanager
def count_queries():
    statements: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before)


@pytest.fixture
def ring(client, owner):
    """~40 perros alrededor de un punto: dentro, fuera y justo en el borde de un radio de 20 km."""
    lat, lon = _spot()
    rnd = random.Random(7)
    points = [_offset(lat, lon, rnd.uniform(0.2, 30), rnd.uniform(0, 360)) for _ in range(30)]
    for k, bearing in enumerate((0, 90, 180, 270, 45)):  # borde del círculo (sin empates de distancia)
        points.append(_offset(lat, lon, 19.9 + k * 0.01, bearing))
        points.append(_offset(lat, lon, 20.06 + k * 0.01, bearing))
    oid = _user_id(client, owner)
    ids = _insert_dogs(oid, points)
    return {"lat": lat, "lon": lon, "owner_id": oid, "ids": ids, "points": dict(zip(ids, points))}


def _expected(ring, radius_km):
    pairs = [(haversine_km(ring["lat"], ring["lon"], la, lo), i) for i, (la, lo) in ring["points"].items()]
    return sorted((d, i) for d, i in pairs if d <= radius_km)


def _expected_public(ring, radius_km):
    """Lo que ve el público: el radio se evalúa sobre las coordenadas aproximadas (~1 km), no las exactas."""
    pairs = [(haversine_km(ring["lat"], ring["lon"], geo.coarse(la), geo.coarse(lo)), i)
             for i, (la, lo) in ring["points"].items()]
    return sorted((d, i) for d, i in pairs if d <= radius_km)


# --------------------------------------------------------------------------- distancia en SQL
def test_sql_distance_matches_python_haversine(ring):
    db = SessionLocal()
    try:
        q = db.query(Dog).filter(Dog.owner_id == ring["owner_id"])
        items = geo.apply_distance(q, Dog, None, ring["lat"], ring["lon"], 20, 0, 100, exact=True)
        expected = _expected(ring, 20)
        assert [i.id for i in items] == [i for _, i in expected]  # mismo conjunto (incluye el borde) y orden
        for item, (dist, _) in zip(items, expected):
            assert item.distance_km == round(dist, geo.DISTANCE_DECIMALS)
        # la expresión SQL coincide con la de Python (sin redondeo)
        exact = db.query(geo.distance_sql(Dog.latitude, Dog.longitude, ring["lat"], ring["lon"])).filter(
            Dog.id == expected[0][1]).scalar()
        assert abs(exact - expected[0][0]) < 1e-6
        # el JSON pesado no se carga en listados
        from sqlalchemy import inspect

        assert "photo_signature" in inspect(items[0]).unloaded
    finally:
        db.close()


def test_sql_distance_pagination_and_fallback(ring):
    db = SessionLocal()
    try:
        q = db.query(Dog).filter(Dog.owner_id == ring["owner_id"])
        full = [i for _, i in _expected(ring, 25)]
        pages = []
        for skip in range(0, len(full) + 7, 7):
            pages += [d.id for d in geo.apply_distance(q, Dog, None, ring["lat"], ring["lon"], 25, skip, 7, exact=True)]
        assert pages == full
        # página más allá del final (sí hay resultados en el radio): vacía, sin caer al orden por fecha
        assert geo.apply_distance(q, Dog, None, ring["lat"], ring["lon"], 25, len(full) + 50, 7, exact=True) == []
        # nada en el radio: cae al orden por fecha y calcula la distancia
        far_lat, far_lon = ring["lat"], ring["lon"] + 5
        fallback = geo.apply_distance(q, Dog, None, far_lat, far_lon, 1, 0, 5, exact=True)
        newest = q.order_by(Dog.created_at.desc(), Dog.id.desc()).limit(5).all()
        assert [d.id for d in fallback] == [d.id for d in newest]
        assert all(d.distance_km is not None and d.distance_km > 1 for d in fallback)
        # sin coordenadas: por fecha
        assert [d.id for d in geo.apply_distance(q, Dog, None, None, None, 25, 0, 5)] == [d.id for d in newest]
    finally:
        db.close()


def test_nearby_endpoint_radius_and_order(client, ring):
    r = client.get("/dogs/nearby", params={"lat": ring["lat"], "lon": ring["lon"], "radius_km": 20, "limit": 100})
    assert r.status_code == 200, r.text
    got = [d for d in r.json() if d["id"] in ring["points"]]
    # Público: el radio se mide a las coordenadas aproximadas (no se puede bisecar la ubicación exacta)
    assert {d["id"] for d in got} == {i for _, i in _expected_public(ring, 20)}
    distances = [d["distance_km"] for d in got]
    assert distances == sorted(distances)
    page2 = client.get("/dogs/nearby", params={"lat": ring["lat"], "lon": ring["lon"], "radius_km": 20,
                                               "skip": 5, "limit": 5}).json()
    assert len(page2) == 5 and not {d["id"] for d in page2} & {d["id"] for d in got[:5]}


# --------------------------------------------------------------------------- caché de listados
def test_featured_cached_for_anonymous_and_personal_for_users(client, owner, user, monkeypatch):
    lat, lon = _spot()
    lat = round(lat, 2) + 0.001  # lejos del borde de redondeo a 2 decimales
    r = client.post("/dogs", headers=owner["h"], json={"name": "Destacado", "latitude": lat, "longitude": lon})
    assert r.status_code == 201, r.text
    dog_id = r.json()["id"]
    # Versión fija del grupo: las pruebas de otros procesos que crean perros no invalidan esta caché
    monkeypatch.setattr(cache, "version", lambda namespace: 987_654_321)
    params = {"lat": lat, "lon": lon, "radius_km": 5, "limit": 5}
    first = client.get("/dogs/featured", params=params)
    assert first.status_code == 200 and dog_id in [d["id"] for d in first.json()]

    from app.routers import dogs as dogs_router

    def boom(*a, **kw):
        raise AssertionError("debió responder desde la caché")

    monkeypatch.setattr(dogs_router, "apply_distance", boom)
    # mismo punto aproximado (~1 km): misma clave de caché
    again = client.get("/dogs/featured", params={**params, "lat": lat + 0.001})
    assert again.status_code == 200 and again.json() == first.json()
    monkeypatch.undo()

    # Con sesión no hay caché y se excluyen los que ya le gustaron
    assert client.post(f"/dogs/{dog_id}/like", headers=user["h"]).status_code == 200
    mine = client.get("/dogs/featured", params=params, headers=user["h"])
    assert mine.status_code == 200 and dog_id not in [d["id"] for d in mine.json()]


def test_lost_reports_list_cache_invalidated_on_create(client, user):
    lat, lon = _spot()
    params = {"lat": lat, "lon": lon, "radius_km": 3}
    assert client.get("/lost-reports", params=params).status_code == 200
    r = client.post("/lost-reports", headers=user["h"],
                    json={"dog_name": "Nuevo", "report_type": "lost", "latitude": lat, "longitude": lon})
    assert r.status_code == 201, r.text
    listed = client.get("/lost-reports", params=params).json()
    assert r.json()["id"] in [x["id"] for x in listed]  # el alta sube la versión: no se sirve el listado viejo


# --------------------------------------------------------------------------- coincidencias
def _report(reporter_id, lat, lon, report_type="lost", **extra) -> int:
    db = SessionLocal()
    try:
        rep = LostReport(reporter_id=reporter_id, dog_name="PERF-reporte", report_type=report_type, latitude=lat,
                         longitude=lon, status="active", source="app", **extra)
        db.add(rep)
        db.commit()
        return rep.id
    finally:
        db.close()


def test_report_matches_never_decode_cached_and_rate_limited(client, user, monkeypatch):
    lat, lon = _spot()
    uid = _user_id(client, user)
    lost_id = _report(uid, lat, lon, "lost", photos=["/uploads/0123456789abcdef0123456789abcdef.jpg"])
    found_id = _report(uid, lat + 0.01, lon, "found", photos=["/uploads/fedcba9876543210fedcba9876543210.jpg"])
    for rid in (lost_id, found_id):
        cache.delete(f"enrich-q:lost_report:{rid}", matching.matches_cache_key(rid))

    def no_decode(*a, **kw):
        raise AssertionError("no se deben decodificar fotos dentro de la petición")

    queued = []
    monkeypatch.setattr(vision, "signature_for_urls", no_decode)
    monkeypatch.setattr(vision, "image_signature", no_decode)
    from app.tasks import matching as matching_tasks

    monkeypatch.setattr(matching_tasks.enrich_signatures, "delay", lambda kind, ids: queued.append((kind, ids)))
    monkeypatch.setattr(settings, "report_matches_ip_minute_limit", 3)
    # Con Celery las firmas van a la cola (.delay, simulado arriba). CI corre con USE_CELERY=false y entonces
    # irían a BackgroundTasks, que TestClient ejecuta en el mismo hilo: forzamos el camino de producción.
    monkeypatch.setattr(settings, "use_celery", True)
    h = {"X-Real-IP": random_ip()}
    r = client.get(f"/lost-reports/{lost_id}/matches", headers=h)
    assert r.status_code == 200, r.text
    enqueued = {i for kind, ids in queued for i in ids if kind == "lost_report"}
    assert {lost_id, found_id} <= enqueued
    assert cache.get(matching.matches_cache_key(lost_id)) is None  # con firmas pendientes no se guarda
    assert client.get(f"/lost-reports/{lost_id}/matches", headers=h).status_code == 200
    assert client.get(f"/lost-reports/{lost_id}/matches", headers=h).status_code == 200
    limited = client.get(f"/lost-reports/{lost_id}/matches", headers=h)
    assert limited.status_code == 429 and "coincidencias" in limited.json()["detail"]
    # otra IP no se ve afectada
    assert client.get(f"/lost-reports/{lost_id}/matches", headers={"X-Real-IP": random_ip()}).status_code == 200


def test_matching_task_refreshes_cache_and_resolve_invalidates(client, user):
    lat, lon = _spot()
    r = client.post("/lost-reports", headers=user["h"],
                    json={"dog_name": "Caché", "report_type": "lost", "latitude": lat, "longitude": lon})
    rid = r.json()["id"]
    db = SessionLocal()
    try:
        matching.run_report_matching(db, rid)
    finally:
        db.close()
    assert cache.get(matching.matches_cache_key(rid)) == []
    assert client.patch(f"/lost-reports/{rid}/resolve", headers=user["h"]).status_code == 200
    assert cache.get(matching.matches_cache_key(rid)) is None
    # sin fotos pendientes, la consulta pública queda en caché
    other = _report(_user_id(client, user), lat, lon, "found")
    assert client.get(f"/lost-reports/{other}/matches", headers={"X-Real-IP": random_ip()}).status_code == 200
    assert isinstance(cache.get(matching.matches_cache_key(other)), list)


def test_bounded_whatsapp_dedupe_set():
    s = matching._BoundedSet(maxlen=3)
    for k in "abcd":
        s.add(k)
    assert "a" not in s and all(k in s for k in "bcd")


# --------------------------------------------------------------------------- conversaciones
def _conversation_with(client, reporter, report_id, make_user, text="hola"):
    other = make_user("Ayudante")
    conv = client.post(f"/lost-reports/{report_id}/contact", headers=other["h"])
    assert conv.status_code == 200, conv.text
    m = client.post(f"/conversations/{conv.json()['id']}/messages", headers=other["h"], json={"content": text})
    assert m.status_code == 201, m.text
    return conv.json()["id"]


def test_conversations_constant_number_of_queries(client, user, make_user):
    lat, lon = _spot()
    report = client.post("/lost-reports", headers=user["h"],
                         json={"dog_name": "Chat", "report_type": "lost", "latitude": lat, "longitude": lon}).json()
    convs = [_conversation_with(client, user, report["id"], make_user, f"mensaje {i}") for i in range(2)]
    with count_queries() as few:
        r = client.get("/conversations", headers=user["h"])
    assert r.status_code == 200
    for _ in range(4):
        convs.append(_conversation_with(client, user, report["id"], make_user, "otro"))
    with count_queries() as many:
        r = client.get("/conversations", headers=user["h"])
    assert r.status_code == 200
    assert len(many) == len(few) <= 8, many
    data = r.json()
    assert [c["id"] for c in data[:6]] == list(reversed(convs))  # el último mensaje primero
    assert all(c["unread_count"] == 1 and c["last_message"]["content"] for c in data[:6])
    assert data[0]["title"] == "Reporte: Chat" and data[0]["other_user"]["full_name"] == "Ayudante"
    # paginación
    page = client.get("/conversations", params={"skip": 1, "limit": 2}, headers=user["h"]).json()
    assert [c["id"] for c in page] == [c["id"] for c in data[1:3]]
    # un solo resumen (usado por GET /conversations/{id})
    one = client.get(f"/conversations/{convs[0]}", headers=user["h"]).json()
    assert one["unread_count"] == 1 and one["last_message"]["content"] == "mensaje 0"


def test_websocket_ping_pong(client, user, make_user):
    lat, lon = _spot()
    report = client.post("/lost-reports", headers=user["h"],
                         json={"dog_name": "Ping", "report_type": "found", "latitude": lat, "longitude": lon}).json()
    conv_id = _conversation_with(client, user, report["id"], make_user)
    with client.websocket_connect(f"/ws/chat/{conv_id}?token={user['token']}") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_deliver_local_drops_slow_sockets(monkeypatch):
    monkeypatch.setattr(realtime, "SEND_TIMEOUT_SECONDS", 0.2)

    class FakeWS:
        def __init__(self, delay=0.0, fail=False):
            self.delay, self.fail, self.got, self.closed = delay, fail, [], False

        async def send_json(self, event):
            if self.fail:
                raise RuntimeError("socket roto")
            await asyncio.sleep(self.delay)
            self.got.append(event)

        async def close(self, code=1000):
            self.closed = True

    async def run():
        hub = realtime.ChatHub()
        fast, slow, broken = FakeWS(), FakeWS(delay=5), FakeWS(fail=True)
        hub.local[1] = {fast, slow, broken}
        started = asyncio.get_running_loop().time()
        await hub.deliver_local(1, {"type": "message"})
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(0.05)  # deja correr el cierre en segundo plano
        return hub, fast, slow, broken, elapsed

    hub, fast, slow, broken, elapsed = asyncio.run(run())
    assert fast.got == [{"type": "message"}]
    assert elapsed < 1  # en paralelo y con timeout: el lento no bloquea
    assert hub.local[1] == {fast} and slow.closed


# --------------------------------------------------------------------------- expiración y renovación
def test_report_expiry_and_renew(client, user, make_user):
    lat, lon = _spot()
    r = client.post("/lost-reports", headers=user["h"],
                    json={"dog_name": "Viejito", "report_type": "lost", "latitude": lat, "longitude": lon})
    rid = r.json()["id"]
    db = SessionLocal()
    try:
        rep = db.query(LostReport).filter(LostReport.id == rid).first()
        rep.last_activity_at = rep.updated_at = rep.created_at = (
            datetime.datetime.utcnow() - datetime.timedelta(days=settings.report_expiry_days + 1)
        )
        db.commit()
        assert expire_stale_reports_now(db, report_ids=[rid]) == [rid]
        assert expire_stale_reports_now(db, report_ids=[rid]) == []  # idempotente
    finally:
        db.close()
    params = {"lat": lat, "lon": lon, "radius_km": 3}
    assert rid not in [x["id"] for x in client.get("/lost-reports", params=params).json()]
    assert client.get(f"/lost-reports/{rid}").json()["status"] == "expired"
    notes = client.get("/notifications", headers=user["h"]).json()
    assert any(n["type"] == "report_expired" and (n["data"] or {}).get("report_id") == rid for n in notes)

    other = make_user("Ajeno")
    assert client.post(f"/lost-reports/{rid}/renew", headers=other["h"]).status_code == 403
    renewed = client.post(f"/lost-reports/{rid}/renew", headers=user["h"])
    assert renewed.status_code == 200 and renewed.json()["status"] == "active"
    assert rid in [x["id"] for x in client.get("/lost-reports", params=params).json()]
    db = SessionLocal()
    try:  # renovar reinicia el plazo
        assert expire_stale_reports_now(db, report_ids=[rid]) == []
    finally:
        db.close()
    assert client.patch(f"/lost-reports/{rid}/resolve", headers=user["h"]).status_code == 200
    closed = client.post(f"/lost-reports/{rid}/renew", headers=user["h"])
    assert closed.status_code == 400 and closed.json()["detail"]


# --------------------------------------------------------------------------- configuración
def test_pool_and_celery_settings():
    assert engine.pool.size() == settings.db_pool_size
    assert engine.pool.timeout() == settings.db_pool_timeout
    conf = celery_app.conf
    assert conf.task_acks_late and conf.task_reject_on_worker_lost
    assert (conf.task_soft_time_limit, conf.task_time_limit, conf.worker_max_tasks_per_child) == (300, 600, 200)
    assert conf.beat_schedule["lost-reports-expire-daily"]["task"] == "app.tasks.reports.expire_stale_reports"


def test_redis_down_does_not_slow_requests(monkeypatch):
    """Si Redis no responde, la caché se apaga unos segundos en vez de esperar en cada petición."""
    monkeypatch.setattr(cache, "_redis", None)
    monkeypatch.setattr(cache, "_down_until", 0.0)
    monkeypatch.setattr(settings, "redis_url", "redis://10.255.255.1:6379/0")  # no enrutable
    import time

    started = time.monotonic()
    assert cache.get("x") is None
    assert cache.get("y") is None and cache.version("dogs") == 0
    assert time.monotonic() - started < 2.5  # un solo intento de conexión (timeout ~1 s)


def test_cache_invalidated_automatically_on_commit(client, owner, monkeypatch):
    """Cualquier commit que cambie perros o reportes (p. ej. moderación) invalida sus listados en caché."""
    bumped, deleted = [], []
    monkeypatch.setattr(cache, "bump", lambda *ns: bumped.extend(ns))
    monkeypatch.setattr(cache, "delete", lambda *keys: deleted.extend(keys))
    oid = _user_id(client, owner)
    lat, lon = _spot()
    dog_id = _insert_dogs(oid, [(lat, lon)])[0]
    assert bumped == ["dogs"]
    rid = _report(oid, lat, lon)
    assert bumped[-1] == "lost_reports"
    db = SessionLocal()
    try:
        bumped.clear()
        dog = db.query(Dog).filter(Dog.id == dog_id).first()
        dog.photo_signature = {"v": 1, "photos": []}  # solo la firma: no cambia ningún listado
        db.commit()
        assert bumped == []
        dog.is_hidden = True  # ocultar por moderación sí
        db.commit()
        assert bumped == ["dogs"]
        rep = db.query(LostReport).filter(LostReport.id == rid).first()
        rep.status = "resolved"
        db.flush()
        db.rollback()  # lo que se revierte no invalida nada
        assert bumped == ["dogs"]
        rep = db.query(LostReport).filter(LostReport.id == rid).first()
        rep.status = "resolved"
        db.commit()
        assert bumped[-1] == "lost_reports" and matching.matches_cache_key(rid) in deleted
    finally:
        db.close()
