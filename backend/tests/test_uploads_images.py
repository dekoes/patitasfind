"""Fotos: SSRF, bombas de descompresión, subidas (verificación y cuota), limpieza de huérfanos,
reintentos del backfill, límites de IA/búsqueda y fallback del rate limit sin Redis."""
import asyncio
import io
import os
import struct
import threading
import time
import uuid
import zlib

import pytest
import urllib3.util.connection
from PIL import Image

from app import cache
from app.config import settings
from app.database import SessionLocal
from app.models import Dog, LostReport
from app.services import images, ratelimit, vision
from app.tasks import images as image_tasks
from tests.conftest import make_jpeg, random_ip


def _png_with_size(width: int, height: int) -> bytes:
    """PNG de unos cuantos bytes que declara width × height en su cabecera (bomba de descompresión)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" * 64)) + chunk(b"IEND", b"")


def _upload(client, u, data=None, name="p.jpg"):
    return client.post("/upload", headers=u["h"], files={"file": (name, data or make_jpeg(), "image/jpeg")})


def _me_id(client, u) -> int:
    return client.get("/users/me", headers=u["h"]).json()["id"]


# --------------------------------------------------------------------------- I1: URLs de fotos
@pytest.mark.parametrize("value", [
    "https://evil.example/perro.jpg",
    "http://169.254.169.254/latest/meta-data/",
    "//evil.example/uploads/perro.jpg",
    "/uploads/../secreto.jpg",
    "/uploads/private/0123456789abcdef0123456789abcdef.pdf",
    "/uploads/perro.jpg?x=1",
    "/uploads/perro.svg",
    "/uploads/%2e%2e/perro.jpg",
    "file:///etc/passwd",
    "/etc/passwd",
    "",
])
def test_validate_upload_url_rejects(value):
    with pytest.raises(ValueError):
        images.validate_upload_url(value)


def test_validate_upload_url_accepts_local_and_own_domain():
    assert images.validate_upload_url("/uploads/0123456789abcdef0123456789abcdef.jpg") == \
        "/uploads/0123456789abcdef0123456789abcdef.jpg"
    assert images.validate_upload_url(settings.public_url("/uploads/foto_vieja-1.webp")) == "/uploads/foto_vieja-1.webp"


def test_remote_photo_urls_rejected_by_schemas(client, user):
    r = client.post("/dogs", headers=user["h"], json={"name": "Remoto", "photos": ["https://evil.example/perro.jpg"]})
    assert r.status_code == 422, r.text
    r = client.post("/lost-reports", headers=user["h"], json={
        "dog_name": "Remoto", "report_type": "lost", "photos": ["http://169.254.169.254/latest/meta-data/"]})
    assert r.status_code == 422, r.text
    r = client.patch("/users/me", headers=user["h"], json={"avatar_url": "https://evil.example/a.png"})
    assert r.status_code == 422, r.text
    r = client.post("/dogs", headers=user["h"], json={"name": "Muchas", "photos": ["/uploads/a.jpg"] * 11})
    assert r.status_code == 422, r.text

    # Una URL absoluta a nuestro propio dominio se acepta y se guarda relativa
    url = _upload(client, user).json()["url"]
    r = client.post("/dogs", headers=user["h"], json={"name": "Local", "photos": [settings.public_url(url)]})
    assert r.status_code in (200, 201), r.text
    assert r.json()["photos"] == [url]


def test_load_image_bytes_is_local_only(monkeypatch, client, user):
    url = _upload(client, user).json()["url"]
    assert images.load_image_bytes(url)[:2] == b"\xff\xd8"
    assert images.load_image_bytes(settings.public_url(url))[:2] == b"\xff\xd8"
    assert images.load_image_bytes("/uploads/../app/main.py") is None

    def no_dns(*a, **k):
        raise AssertionError("no debe resolver DNS para URLs remotas sin allow_remote")

    monkeypatch.setattr(images.socket, "getaddrinfo", no_dns)
    assert images.load_image_bytes("https://scontent.xx.fbcdn.net/v/foto.jpg") is None
    assert images.load_image_bytes("http://127.0.0.1:8001/health") is None


# --------------------------------------------------------------------------- I1: descargas remotas
def test_ip_is_public():
    for ip in ("127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254", "100.64.0.1",
               "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "224.0.0.1", "no-es-ip"):
        assert images._ip_is_public(ip) is False, ip
    assert images._ip_is_public("8.8.8.8") and images._ip_is_public("2a03:2880:f12f:83:face:b00c:0:25de")


def test_fetch_remote_media_blocks_ssrf(monkeypatch):
    connections = []
    monkeypatch.setattr(urllib3.util.connection, "create_connection",
                        lambda *a, **k: connections.append(a) or (_ for _ in ()).throw(OSError("sin red")))
    for url in ("https://evil.example/x.jpg", "http://lookaside.fbsbx.com/x.jpg",
                "https://usuario:clave@lookaside.fbsbx.com/x.jpg", "https://lookaside.fbsbx.com:8443/x.jpg",
                "https://fbcdn.net.evil.example/x.jpg", "ftp://graph.facebook.com/x"):
        assert images.fetch_remote_media(url) is None, url

    # Host permitido pero que resuelve a una IP privada o de loopback: no se abre ningún socket
    monkeypatch.setattr(settings, "remote_media_hosts", "localhost,*.fbcdn.net")
    assert images.fetch_remote_media("https://localhost/x.jpg") is None
    monkeypatch.setattr(images.socket, "getaddrinfo",
                        lambda host, port, **k: [(2, 1, 6, "", ("10.0.0.5", port))])
    assert images.fetch_remote_media("https://scontent.xx.fbcdn.net/x.jpg") is None
    assert connections == []


class _FakeResp:
    def __init__(self, status=200, headers=None, chunks=(b"\xff\xd8datos",)):
        self.status_code = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self._chunks = chunks

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308) and "location" in self.headers

    def iter_content(self, size):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_remote_media_redirects_headers_and_size(monkeypatch):
    def use(responses):
        session = _FakeSession(responses)
        monkeypatch.setattr(images, "_remote_session", lambda: session)
        return session

    # Redirección a un host no permitido: se corta sin seguirla
    s = use([_FakeResp(302, {"Location": "https://evil.example/robado"})])
    assert images.fetch_remote_media("https://lookaside.fbsbx.com/m?id=1", headers={"Authorization": "Bearer x"}) is None
    assert len(s.calls) == 1 and s.calls[0][1]["allow_redirects"] is False

    # Redirección permitida: el token solo va al host original
    s = use([_FakeResp(302, {"Location": "https://scontent.xx.fbcdn.net/foto.jpg"}), _FakeResp(200)])
    assert images.fetch_remote_media("https://lookaside.fbsbx.com/m?id=1", headers={"Authorization": "Bearer x"}) == b"\xff\xd8datos"
    assert s.calls[0][1]["headers"]["Authorization"] == "Bearer x"
    assert "Authorization" not in s.calls[1][1]["headers"]

    # Demasiadas redirecciones
    use([_FakeResp(302, {"Location": "https://scontent.xx.fbcdn.net/otra.jpg"})] * (images.MAX_REDIRECTS + 1))
    assert images.fetch_remote_media("https://scontent.xx.fbcdn.net/foto.jpg") is None

    # Tamaño: por Content-Length y leyendo en streaming
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    use([_FakeResp(200, {"Content-Length": str(5 * 1024 * 1024)})])
    assert images.fetch_remote_media("https://scontent.xx.fbcdn.net/grande.jpg") is None
    use([_FakeResp(200, chunks=[b"x" * 512 * 1024] * 3)])
    assert images.fetch_remote_media("https://scontent.xx.fbcdn.net/grande.jpg") is None
    use([_FakeResp(404)])
    assert images.fetch_remote_media("https://scontent.xx.fbcdn.net/no-existe.jpg") is None


# --------------------------------------------------------------------------- I2: bombas de descompresión
def test_decompression_bomb_png_rejected(client, user):
    for width, height in ((7000, 7000), (50_000, 50_000)):  # 49 MP (Pillow solo avisaría) y 2500 MP
        bomb = _png_with_size(width, height)
        assert len(bomb) < 200
        r = _upload(client, user, bomb, "bomba.png")
        assert r.status_code == 400, r.text
        assert "megapíxeles" in r.json()["detail"]
        with pytest.raises(images.ImageError):
            images.probe_image(bomb)
    r = client.post("/search/by-photo", headers={"X-Real-IP": random_ip()},
                    files={"file": ("bomba.png", _png_with_size(7000, 7000), "image/png")})
    assert r.status_code == 400 and "megapíxeles" in r.json()["detail"]


def test_large_jpeg_is_decoded_reduced(client, user):
    data = make_jpeg(21, size=(4000, 3000))
    with images.open_image(data) as img:
        assert img.size[0] < 4000  # draft: el JPEG se decodifica directo a escala
    url = _upload(client, user, data).json()["url"]
    with Image.open(images.local_path_for(url)) as stored:
        assert max(stored.size) == images.MAX_DIMENSION
    assert images.local_path_for(images.thumb_url(url))


# --------------------------------------------------------------------------- I5: subidas
def test_unverified_user_cannot_upload(client, unverified):
    r = _upload(client, unverified)
    assert r.status_code == 403 and r.json()["code"] == "phone_verification_required"
    r = client.post("/upload/multiple", headers=unverified["h"], files=[("files", ("a.jpg", make_jpeg(1), "image/jpeg"))])
    assert r.status_code == 403


def test_upload_limits_and_daily_quota(client, make_user, monkeypatch):
    u = make_user("Cuota")
    six = [("files", (f"{i}.jpg", make_jpeg(i), "image/jpeg")) for i in range(6)]
    assert client.post("/upload/multiple", headers=u["h"], files=six).status_code == 400

    monkeypatch.setattr(settings, "upload_daily_quota", 2)
    assert _upload(client, u).status_code == 200
    two = [("files", (f"{i}.jpg", make_jpeg(i), "image/jpeg")) for i in range(2)]
    r = client.post("/upload/multiple", headers=u["h"], files=two)
    assert r.status_code == 429 and "2 fotos por día" in r.json()["detail"]
    assert _upload(client, u).status_code == 200  # lo rechazado no se descontó de la cuota
    r = _upload(client, u)
    assert r.status_code == 429 and r.headers.get("retry-after")


# --------------------------------------------------------------------------- I5: huérfanos
def test_orphan_cleanup_deletes_unreferenced_old_files(client, user, tmp_path):
    old = time.time() - 72 * 3600
    orphan, referenced, recent, no_thumb = (uuid.uuid4().hex for _ in range(4))

    def write(name, data=b"x", age=old):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (age, age))
        return path

    jpeg = make_jpeg(5)
    files = {
        "orphan": write(f"{orphan}.jpg", jpeg), "orphan_thumb": write(f"{orphan}_thumb.jpg", jpeg),
        "ref": write(f"{referenced}.jpg", jpeg), "ref_thumb": write(f"{referenced}_thumb.jpg", jpeg),
        "no_thumb": write(f"{no_thumb}.jpg", jpeg),
        "recent": write(f"{recent}.jpg", jpeg, age=time.time()),
        "legacy": write("foto-vieja.jpg"),
        "private": write(f"private/{uuid.uuid4().hex}.jpg"),
        "restore": write(f".pre-restore-20261001/{uuid.uuid4().hex}.jpg"),
    }
    db = SessionLocal()
    dog = Dog(owner_id=_me_id(client, user), name="Referencias", status="adopted",
              photos=[f"/uploads/{referenced}.jpg", settings.public_url(f"/uploads/{no_thumb}.jpg")])
    db.add(dog)
    db.commit()
    try:
        dry = image_tasks.remove_orphan_uploads(db, folder=tmp_path, dry_run=True)
        assert sorted(dry["deleted"]) == sorted([f"{orphan}.jpg", f"{orphan}_thumb.jpg"])
        assert files["orphan"].exists()

        result = image_tasks.remove_orphan_uploads(db, folder=tmp_path)
        assert sorted(result["deleted"]) == sorted([f"{orphan}.jpg", f"{orphan}_thumb.jpg"])
        assert not files["orphan"].exists() and not files["orphan_thumb"].exists()
        for key in ("ref", "ref_thumb", "no_thumb", "recent", "legacy", "private", "restore"):
            assert files[key].exists(), key
        assert (tmp_path / f"{no_thumb}_thumb.jpg").exists() and result["thumbnails"] == 1
    finally:
        db.delete(dog)
        db.commit()
        db.close()


def test_orphan_cleanup_task_uses_upload_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    path = tmp_path / f"{uuid.uuid4().hex}.jpg"
    path.write_bytes(b"x")
    os.utime(path, (time.time() - 72 * 3600,) * 2)
    out = image_tasks.cleanup_orphan_uploads()
    assert out["deleted"] == 1 and not path.exists()


# --------------------------------------------------------------------------- I7: backfill
def test_backfill_marks_rows_and_backs_off(client, user, monkeypatch):
    url = _upload(client, user).json()["url"]
    uid = _me_id(client, user)
    db = SessionLocal()
    no_photo = Dog(owner_id=uid, name="SinFoto", status="adopted", photos=[])
    with_photo = Dog(owner_id=uid, name="ConFoto", status="adopted", photos=[url])
    remote = LostReport(dog_name="Remoto", report_type="lost", status="resolved", photos=["https://evil.example/x.jpg"])
    db.add_all([no_photo, with_photo, remote])
    db.commit()
    ids = [no_photo.id, with_photo.id]

    def pending(now):
        q = image_tasks._backfill_query(db, Dog, True, now=now).filter(Dog.id.in_(ids))
        return {d.name for d in q.all()}

    try:
        now = time.time()
        assert pending(now) == {"SinFoto", "ConFoto"}
        monkeypatch.setattr(vision, "analyze_url", lambda u: None)  # la IA falla siempre

        assert image_tasks._backfill_one(no_photo, True, now) == "skipped"
        assert image_tasks._backfill_one(remote, True, now) == "skipped"  # solo archivos locales
        assert image_tasks._backfill_one(with_photo, True, now) == "ai_failed"
        db.commit()
        assert no_photo.photo_signature["backfill"]["done"] is True
        assert with_photo.photo_signature["photos"][0]["url"] == url
        assert with_photo.photo_signature["backfill"]["ai_attempts"] == 1
        assert pending(now + 10) == set()  # en espera: no bloquea la cola
        assert pending(now + 3601) == {"ConFoto"}

        t = now
        for attempt in range(2, image_tasks.MAX_AI_ATTEMPTS + 1):
            t += image_tasks.AI_BACKOFF_SECONDS * 2 ** attempt
            assert image_tasks._backfill_one(with_photo, True, t) == "ai_failed"
            db.commit()
        meta = with_photo.photo_signature["backfill"]
        assert meta["ai_attempts"] == image_tasks.MAX_AI_ATTEMPTS and meta["done"] is True
        assert pending(t + 10 ** 9) == set()  # se abandonó

        # Si la IA vuelve a responder (p. ej. cambió la foto y se borró la marca), se guarda el análisis
        with_photo.photo_signature = {k: v for k, v in with_photo.photo_signature.items() if k != "backfill"}
        monkeypatch.setattr(vision, "analyze_url", lambda u: {"is_dog": True, "breed_guess": "Mestizo", "url": u})
        assert image_tasks._backfill_one(with_photo, True, t) == "processed"
        db.commit()
        assert with_photo.ai_analysis["breed_guess"] == "Mestizo" and "backfill" not in with_photo.photo_signature
    finally:
        for obj in (no_photo, with_photo, remote):
            db.delete(obj)
        db.commit()
        db.close()


def test_backfill_task_runs(monkeypatch):
    monkeypatch.setattr(vision, "analyze_url", lambda u: None)
    out = image_tasks.backfill_photo_signatures(batch=1)
    assert set(out) == {"processed", "skipped", "ai_failed"}


# --------------------------------------------------------------------------- I4: IA y búsqueda
class _AIResp:
    status_code = 200
    text = ""

    def json(self):
        return {"choices": [{"message": {"content": '{"is_dog": true, "breed_guess": "Chihuahua", "size": "Pequeño"}'}}]}


def _ai_on(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "sk-prueba")
    monkeypatch.setattr(settings, "ai_base_url", "https://ia.ejemplo/v1")
    vision._memory_cache.clear()
    monkeypatch.setattr(vision.cache, "get", lambda k: None)
    monkeypatch.setattr(vision.cache, "set", lambda *a, **k: None)
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: _AIResp())


def test_ai_analyze_hourly_limit(client, make_user, monkeypatch):
    _ai_on(monkeypatch)
    monkeypatch.setattr(settings, "ai_user_hourly_limit", 1)
    u = make_user("IA")
    r = client.post("/ai/analyze-photo", headers=u["h"], files={"file": ("q.jpg", make_jpeg(31), "image/jpeg")})
    assert r.status_code == 200 and r.json()["breed"] == "Chihuahua"
    r = client.post("/ai/analyze-photo", headers=u["h"], files={"file": ("q.jpg", make_jpeg(32), "image/jpeg")})
    assert r.status_code == 429 and "IA" in r.json()["detail"]


def test_search_by_photo_limits(client, make_user, monkeypatch):
    form = {"report_type": "found", "city": "Ciudad Sin Perros"}

    def search(headers, seed=40):
        return client.post("/search/by-photo", headers=headers, data=form,
                           files={"file": ("q.jpg", make_jpeg(seed, size=(320, 240)), "image/jpeg")})

    u = make_user("Busca")
    monkeypatch.setattr(settings, "search_user_hourly_limit", 1)
    assert search({**u["h"], "X-Real-IP": random_ip()}).status_code == 200
    r = search({**u["h"], "X-Real-IP": random_ip()})  # otra IP, mismo usuario
    assert r.status_code == 429 and "hora" in r.json()["detail"]

    monkeypatch.setattr(settings, "search_anon_minute_limit", 1)
    ip = random_ip()
    assert search({"X-Real-IP": ip}).status_code == 200
    assert search({"X-Real-IP": ip}).status_code == 429

    monkeypatch.setattr(settings, "search_anon_minute_limit", 100)
    monkeypatch.setattr(settings, "search_anon_daily_limit", 1)
    ip = random_ip()
    assert search({"X-Real-IP": ip}).status_code == 200
    r = search({"X-Real-IP": ip})
    assert r.status_code == 429 and "diario" in r.json()["detail"]


def test_search_with_ai_calls_model_once(client, monkeypatch):
    _ai_on(monkeypatch)
    calls = []
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: calls.append(1) or _AIResp())
    r = client.post("/search/by-photo", headers={"X-Real-IP": random_ip()}, data={"report_type": "found"},
                    files={"file": ("q.jpg", make_jpeg(77, size=(320, 240)), "image/jpeg")})
    assert r.status_code == 200 and r.json()["analysis"]["breed_guess"] == "Chihuahua"
    assert len(calls) == 1  # la consulta a la BD reutiliza el análisis de la caché en memoria


def test_ai_semaphore_limits_concurrency(monkeypatch):
    monkeypatch.setattr(vision, "_ai_slots", None)
    monkeypatch.setattr(vision, "_ai_slots_loop", None)
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def slow(data, cache_key=None):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.15)
        with lock:
            state["now"] -= 1
        return {"ok": True}

    monkeypatch.setattr(vision, "analyze_image_bytes", slow)

    async def run(n):
        return await asyncio.gather(*(vision.analyze_image_bytes_async(b"x") for _ in range(n)))

    monkeypatch.setattr(settings, "ai_max_concurrency", 2)
    assert asyncio.run(run(6)) == [{"ok": True}] * 6 and state["max"] == 2

    # Sin turno a tiempo: None (igual que si la IA fallara)
    monkeypatch.setattr(settings, "ai_max_concurrency", 1)
    monkeypatch.setattr(settings, "ai_timeout_seconds", 0.05)
    assert sorted(asyncio.run(run(2)), key=str) == [None, {"ok": True}]


def test_vision_memory_cache_is_bounded():
    lru = vision._LRUCache(maxsize=3)
    for i in range(5):
        lru.set(f"k{i}", {"i": i})
    assert len(lru) == 3 and lru.get("k0") is None and lru.get("k2") == {"i": 2}
    lru.set("k5", {"i": 5})  # k2 se usó hace poco: sale k3
    assert lru.get("k3") is None and lru.get("k2") is not None
    assert vision._memory_cache.maxsize <= 1024


# --------------------------------------------------------------------------- I6: rate limit sin Redis
def test_ratelimit_falls_back_to_memory_and_warns(monkeypatch):
    class BrokenRedis:
        def pipeline(self, *a, **k):
            raise ConnectionError("Redis caído")

    warnings_ = []
    monkeypatch.setattr(cache, "_get_redis", lambda: BrokenRedis())
    monkeypatch.setattr(ratelimit.logger, "warning", lambda *a, **k: warnings_.append(a))
    monkeypatch.setattr(ratelimit, "_last_warning", 0.0)
    key = f"prueba:{uuid.uuid4().hex}"
    ratelimit.check(key, 2, 60)
    ratelimit.check(key, 2, 60)
    with pytest.raises(Exception) as exc:
        ratelimit.check(key, 2, 60, detail="Demasiadas pruebas.")
    assert exc.value.status_code == 429 and exc.value.detail == "Demasiadas pruebas."
    assert len(warnings_) == 1 and "Redis no disponible" in warnings_[0][0]

    # Sin conexión (cache devuelve None) pero con REDIS_URL configurada: también avisa
    monkeypatch.setattr(cache, "_get_redis", lambda: None)
    monkeypatch.setattr(settings, "redis_url", "redis://redis:6379/0")
    monkeypatch.setattr(ratelimit, "_last_warning", 0.0)
    assert ratelimit.hit(f"prueba:{uuid.uuid4().hex}", 3, 60, cost=3) is True
    assert len(warnings_) == 2


def test_ratelimit_redis_cost_and_refund():
    r = cache._get_redis()
    if r is None:
        pytest.skip("Sin Redis")
    key = f"prueba:{uuid.uuid4().hex}"
    assert ratelimit.hit(key, 5, 60, cost=3) is True
    assert ratelimit.hit(key, 5, 60, cost=3) is False  # 6 > 5: se rechaza y no cuenta
    assert ratelimit.hit(key, 5, 60, cost=2) is True
    assert ratelimit.hit(key, 5, 60) is False
