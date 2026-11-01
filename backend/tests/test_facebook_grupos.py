"""Grupos públicos de Facebook (F1–F3): proveedor, limpieza de datos personales, lectura por zona con presupuesto,
deducción del estado, disparo al crear reportes, importación de voluntarios y panel de admin.

Nunca se llama a Apify ni a Facebook: requests y el despacho de tareas se sustituyen en cada prueba.
"""
import datetime
import json
import uuid

import pytest
import requests

from app.config import settings
from app.data import estados_mx
from app.database import SessionLocal
from app.models import AdminAuditLog, BotInteraction, ContentReport, FacebookGroup, LostReport, User
from app.routers import facebook as fb_router
from app.routers import lost_reports as lost_router
from app.services import background, facebook_groups as fbg, facebook_monitor
from app.tasks import facebook_groups as fbg_tasks

from conftest import _register, make_jpeg, random_ip

NOW = datetime.datetime.utcnow


# --------------------------------------------------------------------------- utilidades
def _db():
    return SessionLocal()


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _post_url(tag: str | None = None) -> str:
    return f"https://www.facebook.com/groups/perritos{_uid()}/posts/{tag or uuid.uuid4().int % 10**15}"


class FakeProvider(fbg.BaseProvider):
    name = "fake"

    def __init__(self, posts=None, error: Exception | None = None, cost: float | None = None, partial: bool = False):
        self.posts = posts or []
        self.error = error
        self.calls = []
        self.last_run_id = "run-123"
        self.cost = cost
        self.partial = partial

    def fetch_posts(self, group_url, since, limit, max_charge_usd=None):
        self.calls.append({"group_url": group_url, "since": since, "limit": limit, "max_charge_usd": max_charge_usd})
        self.last_run_cost_usd = self.cost
        self.last_run_partial = self.partial
        if self.error:
            raise self.error
        return list(self.posts)


class Recorder:
    """Sustituye a dispatch: guarda (tarea, args) sin ejecutar nada."""

    def __init__(self):
        self.calls = []

    def __call__(self, task_path, *args, background_tasks=None):
        self.calls.append((task_path, args))
        return "test"

    def tasks(self, name):
        return [args for path, args in self.calls if path == name]


@pytest.fixture
def fb(monkeypatch):
    """Proveedor configurado, presupuesto aislado (clave propia en Redis) y sin red ni Celery."""
    monkeypatch.setattr(settings, "apify_token", "apify-test-token")
    monkeypatch.setattr(settings, "fb_groups_enabled", True)  # interruptor legal (apagado por defecto)
    monkeypatch.setattr(settings, "fb_groups_daily_budget_usd", 2.0)
    monkeypatch.setattr(settings, "fb_groups_cost_per_1000_posts_usd", 7.0)
    monkeypatch.setattr(settings, "fb_groups_cost_per_run_usd", 0.005)
    monkeypatch.setattr(settings, "fb_groups_max_posts_per_run", 100)
    monkeypatch.setattr(settings, "fb_groups_fetch_interval_hours", 12)
    monkeypatch.setattr(settings, "fb_groups_lookback_days", 14)
    monkeypatch.setattr(fbg, "KEY_PREFIX", f"fbg:test:{_uid()}")  # gasto y contadores aislados en Redis
    monkeypatch.setattr(fbg, "_warned_budget_day", None)
    monkeypatch.setattr(fbg_tasks, "ZONE_THROTTLE_SECONDS", 0)
    # Sin descargas ni IA: cada foto remota se "guarda" como una subida local ficticia
    monkeypatch.setattr(facebook_monitor.images, "download_and_store",
                        lambda url, headers=None: f"/uploads/{uuid.uuid4().hex}.jpg")
    monkeypatch.setattr(facebook_monitor.vision, "is_configured", lambda: False)
    rec = Recorder()
    monkeypatch.setattr(background, "dispatch", rec)
    monkeypatch.setattr(fbg, "dispatch", rec)
    monkeypatch.setattr(fb_router, "dispatch", rec)
    monkeypatch.setattr(lost_router, "dispatch", rec)
    yield rec
    fbg.reset_spend()


@pytest.fixture
def groups():
    """Crea grupos de prueba y los borra al final."""
    created = []

    def make(state="Jalisco", city="Guadalajara", last_fetched_at=None, is_active=True, name=None, **extra):
        db = _db()
        try:
            url = f"https://www.facebook.com/groups/prueba{_uid()}"
            g = FacebookGroup(name=name or f"Perritos perdidos {state} {_uid()}", url=url, group_url=url, kind="group",
                              state=state, city=city, is_active=is_active, last_fetched_at=last_fetched_at, **extra)
            db.add(g)
            db.commit()
            db.refresh(g)
            created.append(g.id)
            return g.id
        finally:
            db.close()

    yield make
    db = _db()
    try:
        db.query(FacebookGroup).filter(FacebookGroup.id.in_(created)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _group(group_id) -> FacebookGroup:
    db = _db()
    try:
        return db.query(FacebookGroup).filter(FacebookGroup.id == group_id).first()
    finally:
        db.close()


def _report(report_id) -> LostReport:
    db = _db()
    try:
        return db.query(LostReport).filter(LostReport.id == report_id).first()
    finally:
        db.close()


def _set_role(email, role):
    db = _db()
    try:
        db.query(User).filter(User.email == email).update({User.role: role})
        db.commit()
    finally:
        db.close()


@pytest.fixture
def admin(client):
    u = _register(client, "Admin Facebook")
    _set_role(u["email"], "admin")
    yield u
    _set_role(u["email"], "user")


def _posts(*items):
    return [{"post_url": url, "text": text, "created_at": created, "image_urls": imgs} for url, text, created, imgs in items]


# --------------------------------------------------------------------------- datos personales y URLs
@pytest.mark.parametrize("raw, gone, kept", [
    ("Se perdió mi perrita, llamar al 55 1234 5678 o al +52 1 33-3615-0000", ["1234", "3615", "+52"], ["Se perdió"]),
    ("Informes (81) 8123-4567, recompensa", ["8123"], ["recompensa"]),
    ("Escríbeme a dueña.perrito@gmail.com o @lupita_perritos", ["gmail", "lupita"], ["Escríbeme"]),
    ("Más info https://bit.ly/abc123 y www.ejemplo.mx/perro y wa.me/5215512345678", ["bit.ly", "ejemplo", "wa.me"],
     ["Más info"]),
    ("Tiene 3 años, CP 06700, calle 5 de mayo, desde el 2025", [], ["3 años", "06700", "5 de mayo", "2025"]),
    # Enlaces sin https (perfiles del autor)
    ("Info m.me/juanperez o facebook.com/juan.perez.123 o instagram.com/juan y linktr.ee/x",
     ["m.me", "juanperez", "facebook.com", "juan.perez", "instagram", "linktr"], ["Info"]),
    # Datos de pago: tarjeta y CLABE (con o sin espacios/guiones)
    ("Apoyo a la tarjeta 4152 3138 1234 5678 o CLABE 012180001234567891 o 4152-3138-1234-5678",
     ["4152", "5678", "012180001234567891", "3138"], ["Apoyo a la tarjeta"]),
    # Fechas y años no son teléfonos
    ("Fecha 2025 10 12, se perdió el 12-10-2025. Vacunas 2023 2024", [], ["2025 10 12", "12-10-2025", "2023 2024"]),
    # Nombres de contacto y números de casa; el nombre del perrito se queda
    ("Se llama Rocky. Contacto: Juan Pérez. Pregunta por Lupita en la tienda, calle Hidalgo #123 int. 4",
     ["Juan", "Pérez", "Lupita", "#123", "int. 4"], ["Rocky", "en la tienda", "calle Hidalgo"]),
    # Contrato L-fb: también los nombres que siguen a "soy" (aunque a veces sea el perrito hablando)
    ("Soy Luna y me perdí, comunícate con Sra. María López. Atte. Ana", ["Luna", "María", "López", "Ana"],
     ["y me perdí"]),
    ("Anda sin dueño. Perrito café muy noble", [], ["sin dueño", "Perrito café"]),
])
def test_strip_pii(raw, gone, kept):
    clean = fbg.strip_pii(raw)
    for piece in gone:
        assert piece not in clean, clean
    for piece in kept:
        assert piece in clean, clean
    assert fbg.strip_pii(None) == "" and fbg.strip_pii("") == ""


def test_normalize_urls():
    assert fbg.normalize_group_url("https://m.facebook.com/groups/perdidosgdl/?ref=share") == \
        "https://www.facebook.com/groups/perdidosgdl"
    assert fbg.normalize_group_url("https://www.facebook.com/perdidosgdl") is None
    assert fbg.normalize_group_url("https://evil.example/groups/x") is None
    assert fbg.normalize_post_url("https://m.facebook.com/groups/1/posts/2/?mibextid=abc#x") == \
        "https://www.facebook.com/groups/1/posts/2"
    assert fbg.normalize_post_url("https://www.facebook.com/permalink.php?story_fbid=9&id=7&ref=x") == \
        "https://www.facebook.com/permalink.php?id=7&story_fbid=9"
    assert fbg.normalize_post_url("https://www.facebook.com/permalink.php?ref=x") is None
    assert fbg.normalize_post_url("https://instagram.com/p/abc") is None
    assert fbg.normalize_post_url("") is None


# --------------------------------------------------------------------------- Apify
class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, text=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeApify:
    """Sustituye requests.request: corrida asíncrona (POST runs -> GET actor-runs -> GET items -> DELETE dataset)."""

    def __init__(self, items, polls=1, final_status="SUCCEEDED", cost=0.042):
        self.items = items
        self.polls = polls
        self.final_status = final_status
        self.cost = cost
        self.calls = []

    def __call__(self, method, url, headers=None, timeout=None, params=None, json=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "timeout": timeout, "params": params,
                           "json": json})
        if method == "POST" and url.endswith("/runs"):
            return FakeResponse(201, {"data": {"id": "run-abc", "status": "RUNNING", "defaultDatasetId": "ds-1"}})
        if method == "GET" and "/actor-runs/" in url:
            self.polls -= 1
            status = self.final_status if self.polls <= 0 else "RUNNING"
            return FakeResponse(200, {"data": {"id": "run-abc", "status": status, "defaultDatasetId": "ds-1",
                                               "usageTotalUsd": self.cost, "statusMessage": "actor crashed"}})
        if method == "GET" and url.endswith("/datasets/ds-1/items"):
            return FakeResponse(200, self.items)
        if method == "DELETE" and url.endswith("/datasets/ds-1"):
            return FakeResponse(204, None, text="")
        if method == "POST" and url.endswith("/abort"):
            return FakeResponse(200, {"data": {"id": "run-abc", "status": "ABORTING"}})
        raise AssertionError(f"petición inesperada {method} {url}")

    def methods(self):
        return [(c["method"], c["url"].replace(fbg.APIFY_API, "")) for c in self.calls]


APIFY_ITEMS = [
    {"facebookUrl": "https://www.facebook.com/groups/874728723021553",
     "url": "https://www.facebook.com/groups/874728723021553/posts/111",
     "time": "2025-12-10T04:37:15.000Z", "text": "Se perdió mi perrita Luna",
     "attachments": [{"photo_image": {"uri": "https://scontent-qro1-1.xx.fbcdn.net/v/t1/a.jpg?oh=1"}},
                     {"photo_image": {"uri": "https://evil.example/b.jpg"}},
                     {"thumbnail": "https://lookaside.fbsbx.com/c.jpg"}],
     "user": {"id": "1", "name": "Alguien"}},
    {"url": "https://www.facebook.com/groups/874728723021553/posts/222", "time": 1765341435, "text": None},
    {"text": "sin URL: se descarta"},
    "no es un dict",
]


def test_apify_request_and_response_mapping(monkeypatch):
    fake = FakeApify(APIFY_ITEMS, polls=2)
    monkeypatch.setattr(fbg.requests, "request", fake)
    provider = fbg.ApifyProvider("tok-123", actor="apify/facebook-groups-scraper")
    since = datetime.datetime(2025, 12, 1, 6, 0, 0)
    posts = provider.fetch_posts("https://www.facebook.com/groups/874728723021553", since, 50, max_charge_usd=0.355)

    # Corrida asíncrona, espera, lectura del dataset y purga del dataset en Apify
    assert fake.methods() == [("POST", "/acts/apify~facebook-groups-scraper/runs"), ("GET", "/actor-runs/run-abc"),
                              ("GET", "/actor-runs/run-abc"), ("GET", "/datasets/ds-1/items"),
                              ("DELETE", "/datasets/ds-1")]
    start = fake.calls[0]
    assert start["headers"]["Authorization"] == "Bearer tok-123"
    assert start["json"] == {"startUrls": [{"url": "https://www.facebook.com/groups/874728723021553"}],
                             "resultsLimit": 50, "viewOption": "CHRONOLOGICAL",
                             "onlyPostsNewerThan": "2025-12-01T06:00:00Z"}
    # Tope de gasto = lo apartado para ESTA corrida
    assert start["params"]["maxItems"] == 50 and float(start["params"]["maxTotalChargeUsd"]) == pytest.approx(0.355)
    assert start["params"]["timeout"] == fbg.APIFY_RUN_TIMEOUT and start["params"]["waitForFinish"] <= 60
    assert fake.calls[1]["params"]["waitForFinish"] <= 60
    assert fake.calls[3]["params"]["limit"] == 50 and fake.calls[3]["params"]["clean"] == "true"
    for call in fake.calls:  # nunca sin timeout, y la lectura espera más que waitForFinish
        assert isinstance(call["timeout"], tuple) and call["timeout"][1] > fbg.APIFY_WAIT_SECONDS
    assert provider.last_run_id == "run-abc" and provider.last_run_cost_usd == pytest.approx(0.042)
    assert provider.last_dataset_deleted is True and provider.last_run_partial is False
    assert len(posts) == 2
    first = posts[0]
    assert first["post_url"].endswith("/posts/111") and first["text"] == "Se perdió mi perrita Luna"
    assert first["created_at"] == datetime.datetime(2025, 12, 10, 4, 37, 15)
    assert first["image_urls"] == ["https://scontent-qro1-1.xx.fbcdn.net/v/t1/a.jpg?oh=1",
                                   "https://lookaside.fbsbx.com/c.jpg"]  # el host ajeno se descarta
    assert posts[1]["text"] == "" and posts[1]["created_at"] == datetime.datetime(2025, 12, 10, 4, 37, 15)


def test_apify_failed_and_timed_out_runs(monkeypatch):
    # FAILED: error con el costo ya cobrado; el dataset se borra igual
    fake = FakeApify(APIFY_ITEMS, final_status="FAILED", cost=0.01)
    monkeypatch.setattr(fbg.requests, "request", fake)
    provider = fbg.ApifyProvider("tok")
    with pytest.raises(fbg.ProviderError) as exc:
        provider.fetch_posts("https://www.facebook.com/groups/x", NOW(), 10)
    assert "falló" in str(exc.value) and "actor crashed" in str(exc.value)
    assert exc.value.cost_usd == pytest.approx(0.01)
    assert ("DELETE", "/datasets/ds-1") in fake.methods()

    # TIMED-OUT: se aprovecha lo leído (ya se pagó) y se marca como incompleta
    fake = FakeApify(APIFY_ITEMS, final_status="TIMED-OUT")
    monkeypatch.setattr(fbg.requests, "request", fake)
    provider = fbg.ApifyProvider("tok")
    assert len(provider.fetch_posts("https://www.facebook.com/groups/x", NOW(), 10)) == 2
    assert provider.last_run_partial is True

    # No termina a tiempo: se aborta la corrida y no se cobra más de lo apartado
    fake = FakeApify(APIFY_ITEMS, polls=10**6)
    monkeypatch.setattr(fbg.requests, "request", fake)
    provider = fbg.ApifyProvider("tok", run_timeout=0, poll_margin=0)
    with pytest.raises(fbg.ProviderError) as exc:
        provider.fetch_posts("https://www.facebook.com/groups/x", NOW(), 10)
    assert "tardó" in str(exc.value)
    assert any(m == "POST" and u.endswith("/abort") for m, u in fake.methods())
    assert ("DELETE", "/datasets/ds-1") in fake.methods()


@pytest.mark.parametrize("response, message", [
    (FakeResponse(401, {"error": {"message": "bad token"}}), "token"),
    (FakeResponse(402, {}), "saldo"),
    (FakeResponse(408, {}), "tardó"),
    (FakeResponse(429, {}), "limitó"),
    (FakeResponse(500, {"error": {"message": "actor crashed"}}), "actor crashed"),
    (FakeResponse(200, ValueError("no json"), text="<html>"), "JSON"),
    (FakeResponse(200, {"items": []}), "formato inesperado"),
    (requests.ConnectionError("boom"), "conectar"),
])
def test_apify_error_mapping(monkeypatch, response, message):
    def fake_request(*args, **kwargs):
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(fbg.requests, "request", fake_request)
    with pytest.raises(fbg.ProviderError) as exc:
        fbg.ApifyProvider("tok").fetch_posts("https://www.facebook.com/groups/x", NOW(), 10)
    assert message in str(exc.value)
    assert not exc.value.cost_usd  # la corrida no arrancó: no se cobró nada


# --------------------------------------------------------------------------- proveedor sin configurar
def test_unconfigured_provider_skips_gracefully(monkeypatch, groups):
    monkeypatch.setattr(settings, "apify_token", None)
    rec = Recorder()
    monkeypatch.setattr(fbg, "dispatch", rec)
    monkeypatch.setattr(background, "dispatch", rec)
    gid = groups(state="Jalisco")
    assert fbg.get_provider() is None
    assert fbg.trigger_zone_fetch("Jalisco") is None
    assert fbg_tasks.fetch_zone("Jalisco")["skipped"] == fbg_tasks.NOT_CONFIGURED
    assert fbg_tasks.run_group_fetch(gid)["skipped"] == fbg_tasks.NOT_CONFIGURED
    assert rec.calls == []
    assert _group(gid).last_fetched_at is None


# --------------------------------------------------------------------------- ingesta
def test_ingest_creates_reports_strips_pii_and_dedupes(fb, groups):
    gid = groups(state="Jalisco", city="Zapopan")
    lost_url, found_url = _post_url(), _post_url()
    t1, t2 = NOW() - datetime.timedelta(hours=5), NOW() - datetime.timedelta(hours=2)
    provider = FakeProvider(_posts(
        (lost_url + "?mibextid=xyz", "Se perdió mi perrito Rocky, se llama Rocky. Llamar al 33 1234 5678", t1,
         ["https://scontent.fbcdn.net/a.jpg"]),
        (found_url, "Encontramos este perrito deambulando, busca a su familia. Escribe a ayuda@correo.mx", t2, []),
        (_post_url(), "Vendo bicicleta en buen estado", t2, []),
        ("", "Perrito perdido sin URL", t2, []),
    ))
    out = fbg_tasks.run_group_fetch(gid, provider=provider)
    assert out["error"] is None and out["posts"] == 4 and len(out["created"]) == 2
    lost, found = (_report(rid) for rid in out["created"])
    assert lost.report_type == "lost" and found.report_type == "found"
    for report in (lost, found):
        assert report.source == "facebook" and report.reporter_id is None
        assert report.state == "Jalisco" and report.city == "Zapopan" and report.status == "active"
        assert "1234 5678" not in report.description and "correo.mx" not in report.description
    assert lost.external_url == lost_url  # sin la query: deduplica variantes del mismo enlace
    assert lost.external_posted_at == t1  # la caducidad cuenta desde la publicación original
    assert lost.dog_name == "Rocky" and len(lost.photos) == 1
    assert f"Publicación original: {lost_url}" in lost.description

    g = _group(gid)
    assert g.posts_fetched_total == 4 and g.reports_created_total == 2
    assert float(g.cost_estimate_total) == pytest.approx(fbg.cost_for(4))
    assert g.last_fetched_at is not None and g.last_attempt_at is not None
    assert g.last_post_at == t2 and g.provider == "fake"
    assert g.provider_ref == "run-123" and g.last_error is None
    assert fbg.spent_today() == pytest.approx(fbg.cost_for(4))
    assert fbg.daily_count("posts") == 4 and fbg.daily_count("reports") == 2

    # Misma publicación otra vez (manual: ignora el intervalo): no se duplica
    again = fbg_tasks.run_group_fetch(gid, manual=True, provider=FakeProvider(_posts(
        (lost_url, "Se perdió mi perrito Rocky", t1, []))))
    assert again["created"] == []
    db = _db()
    try:
        assert db.query(LostReport).filter(LostReport.external_url == lost_url).count() == 1
    finally:
        db.close()


def test_fetch_respects_interval_and_lookback(fb, groups):
    recent = groups(last_fetched_at=NOW() - datetime.timedelta(hours=1))
    provider = FakeProvider()
    assert fbg_tasks.run_group_fetch(recent, provider=provider)["skipped"] == "Aún no toca leerlo"
    assert provider.calls == []

    # Manual: se lee aunque no toque; desde la última lectura (más reciente que el lookback)
    last = _group(recent).last_fetched_at
    fbg_tasks.run_group_fetch(recent, manual=True, provider=provider)
    assert provider.calls[-1]["since"] == last

    # Leído hace 13 h: toca; since = última lectura
    stale_at = NOW() - datetime.timedelta(hours=13)
    stale = groups(last_fetched_at=stale_at)
    fbg_tasks.run_group_fetch(stale, provider=provider)
    assert provider.calls[-1]["since"] == stale_at

    # Leído hace 30 días o nunca: since = ahora - FB_GROUPS_LOOKBACK_DAYS
    for gid in (groups(last_fetched_at=NOW() - datetime.timedelta(days=30)), groups()):
        before = NOW()
        fbg_tasks.run_group_fetch(gid, provider=provider)
        since = provider.calls[-1]["since"]
        assert before - datetime.timedelta(days=14, minutes=1) < since <= NOW() - datetime.timedelta(days=14)

    # Inactivo: no se lee salvo manual
    inactive = groups(is_active=False)
    assert fbg_tasks.run_group_fetch(inactive, provider=provider)["skipped"] == "Aún no toca leerlo"


def test_old_posts_are_ignored(fb, groups):
    gid = groups(last_fetched_at=NOW() - datetime.timedelta(hours=20))
    old = _post_url()
    provider = FakeProvider(_posts((old, "Perrito perdido, se busca", NOW() - datetime.timedelta(days=3), [])))
    out = fbg_tasks.run_group_fetch(gid, provider=provider)
    assert out["posts"] == 1 and out["created"] == []  # fijada o anterior a la última lectura


def test_max_posts_and_daily_budget(fb, groups, monkeypatch):
    monkeypatch.setattr(settings, "fb_groups_max_posts_per_run", 5)
    provider = FakeProvider(_posts(*[(_post_url(), "texto sin perros", NOW(), []) for _ in range(8)]))
    out = fbg_tasks.run_group_fetch(groups(), provider=provider)
    assert provider.calls[-1]["limit"] == 5
    # Tope de gasto de la corrida = lo apartado para ella (5 publicaciones + arranque), no lo que queda del día
    assert provider.calls[-1]["max_charge_usd"] == pytest.approx(fbg.cost_for(5)) == pytest.approx(5 * 0.007 + 0.005)
    # El proveedor devolvió 8 (cobra 8) aunque solo se procesan 5
    assert out["posts"] == 8 and fbg.spent_today() == pytest.approx(fbg.cost_for(8))

    # Con costo real informado por el proveedor (usageTotalUsd) se usa ese
    fbg.reset_spend()
    out = fbg_tasks.run_group_fetch(groups(), provider=FakeProvider(cost=0.0123))
    assert out["cost"] == pytest.approx(0.0123) and fbg.spent_today() == pytest.approx(0.0123)

    # Presupuesto de 0.03 USD a 7 USD/1000 + 0.005 por arranque => caben 3 publicaciones
    fbg.reset_spend()
    monkeypatch.setattr(settings, "fb_groups_daily_budget_usd", 0.03)
    assert fbg.affordable_posts() == 3
    provider = FakeProvider()
    fbg_tasks.run_group_fetch(groups(), provider=provider)
    assert provider.calls[-1]["limit"] == 3

    # Agotado: no se llama al proveedor y la zona no encarga lecturas
    fbg.add_spend(0.03)
    calls = len(provider.calls)
    gid = groups(state="Zacatecas")
    assert fbg_tasks.run_group_fetch(gid, provider=provider)["skipped"] == fbg_tasks.BUDGET_EXHAUSTED
    assert len(provider.calls) == calls
    assert fbg_tasks.fetch_zone("Zacatecas")["skipped"] == fbg_tasks.BUDGET_EXHAUSTED
    assert _group(gid).last_fetched_at is None


def _set_group(gid, **values):
    db = _db()
    try:
        db.query(FacebookGroup).filter(FacebookGroup.id == gid).update(values)
        db.commit()
    finally:
        db.close()


def test_provider_error_keeps_watermark_and_refunds_reservation(fb, groups):
    ok_at = NOW() - datetime.timedelta(hours=13)
    gid = groups(last_fetched_at=ok_at)
    err = fbg.ProviderError("Apify tardó demasiado en leer el grupo")
    err.cost_usd = 0.005  # la corrida arrancó: se cobró el arranque
    failing = FakeProvider(error=err)
    out = fbg_tasks.run_group_fetch(gid, provider=failing)
    assert out["error"].startswith("Apify tardó") and failing.calls[-1]["since"] == ok_at
    g = _group(gid)
    # El error mueve el intento (intervalo) pero NO la marca de la última lectura correcta
    assert g.last_error.startswith("Apify tardó") and g.last_fetched_at == ok_at and g.last_attempt_at is not None
    assert fbg.spent_today() == pytest.approx(0.005)  # se regresa lo apartado salvo lo ya cobrado
    assert float(g.cost_estimate_total) == pytest.approx(0.005)
    assert not fbg.is_due(g)  # no se reintenta antes del intervalo
    assert fbg_tasks.run_group_fetch(gid, provider=failing)["skipped"] == "Aún no toca leerlo"
    assert gid not in [x.id for x in fbg.groups_due(_db(), "Jalisco")]

    # Pasado el intervalo, la siguiente lectura pide desde la última correcta: no se pierden publicaciones
    _set_group(gid, last_attempt_at=NOW() - datetime.timedelta(hours=13))
    ok = FakeProvider()
    out = fbg_tasks.run_group_fetch(gid, provider=ok)
    assert out["error"] is None and ok.calls[-1]["since"] == ok_at
    g = _group(gid)
    assert g.last_error is None and g.last_fetched_at > ok_at


def test_partial_run_does_not_advance_watermark(fb, groups):
    ok_at = NOW() - datetime.timedelta(hours=20)
    gid = groups(last_fetched_at=ok_at)
    url = _post_url()
    out = fbg_tasks.run_group_fetch(gid, provider=FakeProvider(
        _posts((url, "Perrito perdido, se busca", NOW() - datetime.timedelta(hours=1), [])), partial=True))
    assert len(out["created"]) == 1 and out["error"] == fbg.PARTIAL_RUN_ERROR
    g = _group(gid)
    assert g.last_fetched_at == ok_at and g.last_error == fbg.PARTIAL_RUN_ERROR and not fbg.is_due(g)


def test_budget_reservation_is_atomic(fb, groups, monkeypatch):
    monkeypatch.setattr(settings, "fb_groups_daily_budget_usd", 0.1)
    assert fbg.try_reserve(0.06) is True
    assert fbg.try_reserve(0.06) is False  # no cabe: no aparta nada
    assert fbg.spent_today() == pytest.approx(0.06)
    assert fbg.try_reserve(0.04) is True and fbg.spent_today() == pytest.approx(0.1)

    # Otra corrida en paralelo tomó lo que quedaba entre la revisión y la reserva: no se llama al proveedor
    fbg.reset_spend()
    monkeypatch.setattr(fbg, "try_reserve", lambda usd: False)
    provider = FakeProvider()
    out = fbg_tasks.run_group_fetch(groups(), provider=provider)
    assert out["skipped"] == fbg_tasks.BUDGET_EXHAUSTED and provider.calls == []


def test_fetch_zone_dispatches_only_due_groups_of_state(fb, groups):
    due = groups(state="Durango", city="Gómez Palacio")
    fresh = groups(state="Durango", last_fetched_at=NOW() - datetime.timedelta(hours=2))
    other = groups(state="Sonora")
    off = groups(state="Durango", is_active=False)
    out = fbg_tasks.fetch_zone("dgo")  # alias del estado
    assert out["state"] == "Durango"
    queued = [args[0] for args in fb.tasks("app.tasks.facebook_groups.fetch_group")]
    assert due in queued and fresh not in queued and other not in queued and off not in queued
    assert fbg_tasks.fetch_zone("Atlantis")["skipped"] == "Estado desconocido"


def test_fetch_zone_throttles_bursts(fb, groups, monkeypatch):
    monkeypatch.setattr(fbg_tasks, "ZONE_THROTTLE_SECONDS", 60)
    state = "Tlaxcala"
    from app import cache

    cache.delete(f"fbg:zone:{state}")
    gid = groups(state=state)
    try:
        assert fbg_tasks.fetch_zone(state)["groups_queued"] >= 1
        assert fbg_tasks.fetch_zone(state)["skipped"] == "Revisión reciente"
        assert [a[0] for a in fb.tasks("app.tasks.facebook_groups.fetch_group")].count(gid) == 1
    finally:
        cache.delete(f"fbg:zone:{state}")


def test_fetch_group_task_dispatches_matching(fb, groups, monkeypatch):
    gid = groups()
    url = _post_url()
    monkeypatch.setattr(fbg, "get_provider", lambda: FakeProvider(_posts((url, "Perrito perdido, se busca", NOW(), []))))
    result = fbg_tasks.fetch_group(gid)
    assert len(result["created"]) == 1
    assert fb.tasks("app.tasks.matching.match_lost_report") == [(result["created"][0],)]
    # Las importaciones de Facebook nunca disparan otra lectura por zona
    assert fb.tasks("app.tasks.facebook_groups.fetch_zone") == []


def test_expire_imported_reports():
    db = _db()
    try:
        old = LostReport(dog_name="Viejo", report_type="found", source="facebook", status="active", photos=[],
                         created_at=NOW() - datetime.timedelta(days=31), external_url=_post_url())
        new = LostReport(dog_name="Nuevo", report_type="found", source="facebook", status="active", photos=[],
                         created_at=NOW() - datetime.timedelta(days=5), external_url=_post_url())
        # Importado tarde: la publicación es de hace 40 días aunque se importó hace 14
        late = LostReport(dog_name="Tarde", report_type="lost", source="facebook", status="active", photos=[],
                          created_at=NOW() - datetime.timedelta(days=14),
                          external_posted_at=NOW() - datetime.timedelta(days=40), external_url=_post_url())
        volunteer = LostReport(dog_name="Voluntario", report_type="found", source="volunteer", status="active",
                               photos=[], created_at=NOW() - datetime.timedelta(days=31), external_url=_post_url())
        app_report = LostReport(dog_name="App", report_type="lost", source="app", status="active", photos=[],
                                created_at=NOW() - datetime.timedelta(days=40))
        db.add_all([old, new, late, volunteer, app_report])
        db.commit()
        ids = [old.id, new.id, late.id, volunteer.id, app_report.id]
        expired = fbg.expire_imported_reports(db, report_ids=ids)
        assert sorted(expired) == sorted([old.id, late.id, volunteer.id])
    finally:
        db.close()
    assert _report(ids[0]).status == "expired" and _report(ids[2]).status == "expired"
    assert _report(ids[3]).status == "expired"  # los envíos de voluntarios también caducan (aviso: 30 días)
    assert _report(ids[1]).status == "active" and _report(ids[4]).status == "active"
    out = fbg_tasks.expire_imported_posts()
    assert "expired" in out and "purged" in out


# --------------------------------------------------------------------------- estado
@pytest.mark.parametrize("state, city, coords, expected", [
    ("jal", None, None, "Jalisco"),
    ("Edo. de México", None, None, "México"),
    ("CDMX", None, None, "Ciudad de México"),
    ("Nuevo Leon", "Saltillo", None, "Nuevo León"),  # lo que manda la app gana
    (None, "Torreón, Coahuila", None, "Coahuila"),
    (None, "Zapopan", None, "Jalisco"),
    (None, "Cancún, Q. Roo", None, "Quintana Roo"),
    (None, "Ecatepec de Morelos", None, "México"),  # gana la coincidencia más larga, no "Morelos"
    (None, "Dolores Hidalgo", None, "Guanajuato"),
    (None, "Monterrey, Nuevo León, México", None, "Nuevo León"),  # el país al final no es el Estado de México
    (None, "Toluca, México", None, "México"),
    (None, "León, Gto", None, "Guanajuato"),
    (None, "Manzanillo, Col.", None, "Colima"),  # abreviatura sola en su tramo sí cuenta
    (None, "Col. Centro, sin número", None, None),  # "col"/"sin" no son Colima/Sinaloa dentro de un texto
    ("Atlantis", "Springfield", None, None),
    (None, "León México", None, "Guanajuato"),  # "México" suelto es el país, no el Estado de México
    (None, "Benito Juárez, Cancún", None, "Quintana Roo"),  # el tramo más general (el último) manda
    (None, "Polanco, Miguel Hidalgo", None, "Ciudad de México"),
    (None, None, (25.67, -100.31), "Nuevo León"),
    (None, None, (0.0, 0.0), None),
    # Coordenadas: municipios grandes además de las capitales (zonas metropolitanas que cruzan estados)
    (None, None, (19.60, -99.05), "México"),  # Ecatepec
    (None, None, (19.4006, -98.9888), "México"),  # Nezahualcóyotl
    (None, None, (19.4785, -99.2396), "México"),  # Naucalpan
    (None, None, (19.54, -99.195), "México"),  # Tlalnepantla
    (None, None, (19.4326, -99.1332), "Ciudad de México"),  # Centro
    (None, None, (20.6534, -105.2253), "Jalisco"),  # Puerto Vallarta (no Nayarit)
    (None, None, (21.1619, -86.8515), "Quintana Roo"),  # Cancún
    (None, None, (31.6904, -106.4245), "Chihuahua"),  # Ciudad Juárez
    (None, None, (25.5428, -103.4068), "Coahuila"),  # Torreón
    (None, None, (25.5611, -103.4983), "Durango"),  # Gómez Palacio
    (None, None, (20.676, -105.262), None),  # entre Puerto Vallarta y Nuevo Vallarta: ambiguo, no se adivina
])
def test_state_derivation(state, city, coords, expected):
    lat, lon = coords or (None, None)
    assert estados_mx.derive_state(state, city, lat, lon) == expected


def test_lost_report_sets_state_and_triggers_zone_fetch(client, user, fb):
    r = client.post("/lost-reports", headers=user["h"], json={
        "dog_name": "Canela", "report_type": "lost", "city": "Guadalajara", "state": "Jalisco"})
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "Jalisco"
    assert fb.tasks("app.tasks.facebook_groups.fetch_zone") == [("Jalisco",)]

    # Sin estado: se deduce de la ciudad
    r = client.post("/lost-reports", headers=user["h"], json={
        "dog_name": "Sin nombre", "report_type": "found", "city": "Torreón"})
    assert r.status_code == 201 and r.json()["state"] == "Coahuila"
    assert fb.tasks("app.tasks.facebook_groups.fetch_zone")[-1] == ("Coahuila",)

    # Sin estado reconocible: no se encarga nada
    before = len(fb.calls)
    r = client.post("/lost-reports", headers=user["h"], json={"dog_name": "Pinto", "city": "Springfield"})
    assert r.status_code == 201 and r.json()["state"] is None
    assert [c for c in fb.calls[before:] if c[0].endswith("fetch_zone")] == []


def test_lost_report_without_provider_does_not_trigger(client, user, fb, monkeypatch):
    monkeypatch.setattr(settings, "apify_token", None)
    r = client.post("/lost-reports", headers=user["h"], json={"dog_name": "Toby", "state": "Puebla"})
    assert r.status_code == 201 and r.json()["state"] == "Puebla"
    assert fb.tasks("app.tasks.facebook_groups.fetch_zone") == []


def test_whatsapp_report_triggers_zone_fetch(fb, monkeypatch):
    from app.services import whatsapp_bot

    monkeypatch.setattr(whatsapp_bot, "dispatch", fb)
    monkeypatch.setattr(whatsapp_bot.matching, "run_report_matching", lambda db, rid: [])
    db = _db()
    try:
        interaction = BotInteraction(phone=f"+52155{uuid.uuid4().int % 10**8:08d}", stage="details",
                                     data={"flow": "found", "city": "León, Gto", "photos": []})
        db.add(interaction)
        db.commit()
        whatsapp_bot._create_report(db, interaction, "no sé")
        report = db.query(LostReport).filter(LostReport.contact_phone == interaction.phone).first()
        assert report.state == "Guanajuato" and report.source == "whatsapp"
    finally:
        db.close()
    assert fb.tasks("app.tasks.facebook_groups.fetch_zone") == [("Guanajuato",)]


# --------------------------------------------------------------------------- voluntarios
def test_volunteer_import(client, user, fb, unverified):
    url = _post_url()
    body = {"url": url + "?mibextid=abc", "text": "Encontré este perrito en Zapopan, busca a su familia. Tel 33 1111 2222",
            "city": "Zapopan", "consent": True}
    assert client.post("/facebook/volunteer-import", json=body).status_code == 401
    assert client.post("/facebook/volunteer-import", headers=unverified["h"], json=body).status_code == 403

    photo = client.post("/upload", headers=user["h"], files={"file": ("p.jpg", make_jpeg(7), "image/jpeg")})
    assert photo.status_code == 200, photo.text
    r = client.post("/facebook/volunteer-import", headers=user["h"], json={**body, "photos": [photo.json()["url"]]})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["source"] == "volunteer" and data["state"] == "Jalisco" and data["report_type"] == "found"
    assert data["photos"] == [photo.json()["url"]]
    assert "1111 2222" not in data["description"]
    report = _report(data["id"])
    assert report.external_url == url and report.reporter_id is not None
    # Aceptación del voluntario guardada con fecha y versión de los términos
    assert report.consent_at is not None and report.consent_version == settings.legal_terms_version
    assert data["external_url"] == url  # enlace al original para la etiqueta (solo en importados)
    assert fb.tasks("app.tasks.matching.match_lost_report") == [(data["id"],)]
    assert fb.tasks("app.tasks.notifications.notify_nearby_report") == [(data["id"],)]
    assert fb.tasks("app.tasks.facebook_groups.fetch_zone") == []  # importación de Facebook: no dispara lectura

    dup = client.post("/facebook/volunteer-import", headers=user["h"], json={**body, "url": url})
    assert dup.status_code == 409 and dup.json()["report_id"] == data["id"]

    bad = client.post("/facebook/volunteer-import", headers=user["h"], json={**body, "url": "https://example.com/x"})
    assert bad.status_code == 400
    empty = client.post("/facebook/volunteer-import", headers=user["h"],
                        json={"url": _post_url(), "text": "  @solo_un_usuario  ", "consent": True})
    assert empty.status_code == 400
    without = {k: v for k, v in body.items() if k != "consent"}
    r = client.post("/facebook/volunteer-import", headers=user["h"], json={**without, "url": _post_url()})
    assert r.status_code == 400 and "Confirma" in r.json()["detail"]
    typed = client.post("/facebook/volunteer-import", headers=user["h"],
                        json={"url": _post_url(), "text": "Ayuda a compartir", "report_type": "lost", "state": "Yuc",
                              "consent": True})
    assert typed.status_code == 201 and typed.json()["report_type"] == "lost" and typed.json()["state"] == "Yucatán"


def test_volunteer_import_daily_limit(client, make_user, fb):
    u = make_user("Voluntaria")
    for i in range(fb_router.VOLUNTEER_DAILY_LIMIT):
        r = client.post("/facebook/volunteer-import", headers=u["h"],
                        json={"url": _post_url(), "text": f"Perrito perdido número {i}", "city": "Mérida",
                              "consent": True})
        assert r.status_code == 201, r.text
    r = client.post("/facebook/volunteer-import", headers=u["h"],
                    json={"url": _post_url(), "text": "Uno más", "city": "Mérida", "consent": True})
    assert r.status_code == 429


# --------------------------------------------------------------------------- admin
def _audit(action, target_id=None):
    db = _db()
    try:
        q = db.query(AdminAuditLog).filter(AdminAuditLog.action == action)
        if target_id is not None:
            q = q.filter(AdminAuditLog.target_id == target_id)
        return q.count()
    finally:
        db.close()


def test_admin_groups_crud(client, admin, user, fb):
    slug = f"perdidosmerida{_uid()}"
    body = {"name": "Perros perdidos Mérida", "state": "yuc", "city": "Mérida",
            "group_url": f"https://m.facebook.com/groups/{slug}/?ref=share"}
    assert client.post("/admin/facebook/groups", headers=user["h"], json=body).status_code == 403
    r = client.post("/admin/facebook/groups", headers=admin["h"], json=body)
    assert r.status_code == 201, r.text
    g = r.json()
    try:
        assert g["kind"] == "group" and g["state"] == "Yucatán"
        assert g["group_url"] == g["url"] == f"https://www.facebook.com/groups/{slug}"
        assert g["posts_fetched_total"] == 0 and g["cost_estimate_total"] == 0
        assert _audit("facebook_group.create", g["id"]) == 1

        assert client.post("/admin/facebook/groups", headers=admin["h"], json=body).status_code == 409
        assert client.post("/admin/facebook/groups", headers=admin["h"],
                           json={**body, "group_url": "https://facebook.com/perdidos"}).status_code == 400
        assert client.post("/admin/facebook/groups", headers=admin["h"],
                           json={**body, "state": "Narnia", "group_url": _post_url()}).status_code == 400

        listed = client.get("/admin/facebook/groups", headers=admin["h"], params={"state": "Yucatán"})
        assert listed.status_code == 200 and g["id"] in [x["id"] for x in listed.json()]

        r = client.patch(f"/admin/facebook/groups/{g['id']}", headers=admin["h"],
                         json={"is_active": False, "state": "Campeche", "city": ""})
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False and r.json()["state"] == "Campeche" and r.json()["city"] is None
        assert client.patch(f"/admin/facebook/groups/{g['id']}", headers=admin["h"],
                            json={"group_url": "nope"}).status_code == 400
        inactive = client.get("/admin/facebook/groups", headers=admin["h"], params={"active": False})
        assert g["id"] in [x["id"] for x in inactive.json()]
    finally:
        assert client.delete(f"/admin/facebook/groups/{g['id']}", headers=admin["h"]).status_code == 204
    assert client.delete(f"/admin/facebook/groups/{g['id']}", headers=admin["h"]).status_code == 404
    assert _audit("facebook_group.delete", g["id"]) == 1


def test_admin_import_csv(client, admin, fb, groups):
    existing = groups(state="Jalisco", name="Nombre viejo")
    existing_url = _group(existing).group_url
    a, b = f"perdidos{_uid()}", f"rescate{_uid()}"
    csv_text = (
        "name,state,city,group_url\n"
        f"Perros perdidos Puebla,Puebla,Puebla,https://www.facebook.com/groups/{a}\n"
        f"Duplicado en el archivo,Puebla,,https://facebook.com/groups/{a}/\n"
        "Estado raro,Narnia,,https://www.facebook.com/groups/x1\n"
        "URL mala,Puebla,,https://example.com/x\n"
        ",Puebla,,https://www.facebook.com/groups/sin_nombre\n"
        f"Nombre nuevo,Jalisco,Tlaquepaque,{existing_url}\n"
        "\n"
    )
    r = client.post("/admin/facebook/groups/import-csv", headers=admin["h"],
                    files={"file": ("grupos.csv", csv_text.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    out = r.json()
    try:
        assert out["created"] == 1 and out["updated"] == 1 and out["skipped"] == 1
        assert sorted(e["line"] for e in out["errors"]) == [4, 5, 6]
        g = _group(existing)
        assert g.name == "Nombre nuevo" and g.city == "Tlaquepaque"
        assert g.is_active is True  # sin columna "active" un grupo existente conserva su situación
        db = _db()
        try:  # los nuevos quedan PAUSADOS (docs §3: se prueban antes de activarlos)
            new = db.query(FacebookGroup).filter(FacebookGroup.group_url == f"https://www.facebook.com/groups/{a}").first()
            assert new.is_active is False
        finally:
            db.close()
        assert out["created_paused"] == 1 and "pausados" in out["message"]
        assert _audit("facebook_group.import_csv") >= 1

        # JSON con encabezados en español y punto y coma (Excel)
        r = client.post("/admin/facebook/groups/import-csv", headers=admin["h"], json={
            "csv": f"nombre;estado;ciudad;url\nRescate Oaxaca;oax;Oaxaca;https://www.facebook.com/groups/{b}\n"})
        assert r.status_code == 200 and r.json()["created"] == 1, r.text
        # Texto plano; repetir no crea nada
        r = client.post("/admin/facebook/groups/import-csv", content=csv_text.encode(),
                        headers={**admin["h"], "Content-Type": "text/csv"})
        assert r.status_code == 200 and r.json()["created"] == 0 and r.json()["updated"] == 0
        bad = client.post("/admin/facebook/groups/import-csv", headers=admin["h"], json={"csv": "foo,bar\n1,2\n"})
        assert bad.status_code == 400 and "Faltan columnas" in bad.json()["detail"]
    finally:
        db = _db()
        try:
            db.query(FacebookGroup).filter(FacebookGroup.group_url.in_(
                [f"https://www.facebook.com/groups/{a}", f"https://www.facebook.com/groups/{b}"])
            ).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


def test_admin_stats_and_manual_fetch(client, admin, fb, groups, monkeypatch):
    gid = groups(state="Sinaloa", posts_fetched_total=7, reports_created_total=2)
    r = client.get("/admin/facebook/stats", headers=admin["h"])
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["provider_configured"] is True and stats["message"] is None
    assert stats["budget"]["daily_budget_usd"] == 2.0 and stats["budget"]["exhausted"] is False
    assert len(stats["history"]) == 7 and stats["history"][0]["date"] == NOW().date().isoformat()
    assert stats["settings"]["cost_per_1000_posts_usd"] == 7.0 and stats["settings"]["cost_per_run_usd"] == 0.005
    assert stats["budget"]["max_run_cost_usd"] == pytest.approx(fbg.cost_for(100))
    row = next(x for x in stats["groups"] if x["id"] == gid)
    assert row["posts_fetched_total"] == 7 and row["due"] is True
    assert any(s["state"] == "Sinaloa" for s in stats["by_state"])

    r = client.post(f"/admin/facebook/groups/{gid}/fetch", headers=admin["h"])
    assert r.status_code == 202, r.text
    assert fb.tasks("app.tasks.facebook_groups.fetch_group") == [(gid, True)]
    assert _audit("facebook_group.fetch", gid) == 1

    fbg.add_spend(5.0)
    assert client.post(f"/admin/facebook/groups/{gid}/fetch", headers=admin["h"]).status_code == 429
    assert client.get("/admin/facebook/stats", headers=admin["h"]).json()["budget"]["exhausted"] is True

    monkeypatch.setattr(settings, "apify_token", None)
    r = client.post(f"/admin/facebook/groups/{gid}/fetch", headers=admin["h"])
    assert r.status_code == 503 and r.json()["detail"] == "Proveedor no configurado (APIFY_TOKEN)"
    stats = client.get("/admin/facebook/stats", headers=admin["h"]).json()
    assert stats["provider_configured"] is False and stats["message"] == "Proveedor no configurado (APIFY_TOKEN)"
    assert client.get("/facebook/status", headers=admin["h"]).json()["groups_enabled"] is False


# --------------------------------------------------------------------------- Páginas y manual (sin cambios)
def test_page_ingestion_and_manual_import_still_work(client, admin, fb, monkeypatch):
    monkeypatch.setattr(settings, "facebook_page_access_token", "page-token")
    permalink = f"https://www.facebook.com/patitas/posts/{uuid.uuid4().int % 10**12}"

    def fake_get(url, params=None, timeout=None):
        assert "graph.facebook.com" in url and timeout
        return FakeResponse(200, {"data": [
            {"message": "Se perdió mi perrito Max en Monterrey, llama al 81 8123 4567", "permalink_url": permalink,
             "full_picture": "https://scontent.fbcdn.net/p.jpg", "created_time": "2026-10-01T15:00:00+0000"},
            {"message": "Promoción de croquetas"},
        ]})

    monkeypatch.setattr(facebook_monitor.requests, "get", fake_get)
    db = _db()
    try:
        page = FacebookGroup(name="Página prueba", url="https://www.facebook.com/patitas", page_id="patitas",
                             kind="page", city="Monterrey")
        db.add(page)
        db.commit()
        created = facebook_monitor.ingest_page(db, page)
        assert len(created) == 1
        report = db.query(LostReport).filter(LostReport.id == created[0]).first()
        assert report.source == "facebook" and report.state == "Nuevo León" and report.external_url == permalink
        assert report.external_posted_at == datetime.datetime(2026, 10, 1, 15, 0, 0)
        assert "8123" not in report.description  # create_report_from_post limpia todas las fuentes
        db.delete(page)
        db.commit()
    finally:
        db.close()

    post_url = _post_url()
    r = client.post("/facebook/import", headers=admin["h"], json={
        "post_url": post_url, "text": "Perrito encontrado en Xalapa. Informes 228 123 4567 o ana@correo.mx",
        "report_type": "found", "city": "Xalapa"})
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "Veracruz" and r.json()["external_url"] == post_url
    assert "4567" not in r.json()["description"] and "correo.mx" not in r.json()["description"]
    assert client.post("/facebook/import", headers=admin["h"], json={
        "post_url": post_url, "text": "otra vez", "report_type": "found"}).status_code == 409


# --------------------------------------------------------------------------- enlaces de publicación y deduplicación
@pytest.mark.parametrize("url, problem", [
    ("https://www.facebook.com/groups/revisorgrp", fbg.GROUP_LINK_PROBLEM),
    ("https://m.facebook.com/groups/revisorgrp/?ref=share", fbg.GROUP_LINK_PROBLEM),
    ("https://www.facebook.com/groups/revisorgrp/about", fbg.GROUP_LINK_PROBLEM),
    ("https://www.facebook.com/", fbg.NOT_FACEBOOK_PROBLEM),
    ("https://www.facebook.com/home.php", fbg.GROUP_LINK_PROBLEM),
    ("https://www.facebook.com/marketplace", fbg.GROUP_LINK_PROBLEM),
    ("https://www.facebook.com/watch", fbg.NOT_FACEBOOK_PROBLEM),
    ("https://www.facebook.com/juan.perez.123", fbg.PROFILE_LINK_PROBLEM),
    ("https://example.com/groups/1/posts/2", fbg.NOT_FACEBOOK_PROBLEM),
    ("https://www.facebook.com/groups/revisorgrp/posts/123", None),
    ("https://www.facebook.com/groups/revisorgrp/permalink/123/", None),
    ("https://www.facebook.com/permalink.php?story_fbid=9&id=7", None),
    ("https://www.facebook.com/share/p/abc123/", None),
    ("https://www.facebook.com/juan.perez/posts/pfbid0abc", None),
    ("https://fb.watch/abc123/", None),
])
def test_post_url_problem(url, problem):
    assert fbg.post_url_problem(url) == problem


def test_volunteer_rejects_group_links(client, user, fb):
    root = f"https://www.facebook.com/groups/revisor{_uid()}"
    r = client.post("/facebook/volunteer-import", headers=user["h"], json={
        "url": root, "text": "Perrito perdido en el grupo", "city": "Zapopan", "consent": True})
    assert r.status_code == 400 and "del grupo" in r.json()["detail"]
    db = _db()
    try:  # no se creó nada con ese enlace (antes bloqueaba el grupo para siempre con 409)
        assert db.query(LostReport).filter(LostReport.external_url == root).count() == 0
    finally:
        db.close()


def test_dedupe_is_canonical_and_race_safe(client, user, admin, fb, monkeypatch):
    base = _post_url()
    # Importación de admins y de Páginas guardan el enlace canónico: cuenta como duplicado entre fuentes
    r = client.post("/facebook/import", headers=admin["h"], json={
        "post_url": base.replace("www.", "m.") + "/?__cft__[0]=AZX&__tn__=R", "text": "Perrito encontrado en Xalapa",
        "report_type": "found", "city": "Xalapa"})
    assert r.status_code == 201, r.text
    assert r.json()["external_url"] == base
    dup = client.post("/facebook/volunteer-import", headers=user["h"], json={
        "url": base + "?mibextid=1", "text": "Perrito encontrado", "consent": True})
    assert dup.status_code == 409 and dup.json()["report_id"] == r.json()["id"]

    # Carrera: dos envíos pasan la revisión a la vez; el índice único deja solo uno y el otro recibe 409
    url = _post_url()
    first = client.post("/facebook/volunteer-import", headers=user["h"], json={
        "url": url, "text": "Perrito perdido, se busca", "consent": True})
    assert first.status_code == 201, first.text
    real_find = facebook_monitor.find_by_post_url
    calls = {"n": 0}

    def blind_once(db, post_url):  # la primera revisión de cada capa "no ve" el reporte que ya existe
        calls["n"] += 1
        return None if calls["n"] <= 2 else real_find(db, post_url)

    monkeypatch.setattr(fb_router, "find_by_post_url", blind_once)
    monkeypatch.setattr(facebook_monitor, "find_by_post_url", blind_once)
    second = client.post("/facebook/volunteer-import", headers=user["h"], json={
        "url": url, "text": "Perrito perdido, se busca", "consent": True})
    assert second.status_code == 409 and second.json()["report_id"] == first.json()["id"]
    db = _db()
    try:
        assert db.query(LostReport).filter(LostReport.external_url == url).count() == 1
    finally:
        db.close()


# --------------------------------------------------------------------------- caducidad, purga y visibilidad
def _imported(source="facebook", **extra) -> int:
    db = _db()
    try:
        values = {"dog_name": "Importado", "report_type": "found", "source": source, "status": "active", "photos": [],
                  "external_url": _post_url(), "description": "Perrito encontrado", **extra}
        r = LostReport(**values)
        db.add(r)
        db.commit()
        return r.id
    finally:
        db.close()


def test_withdrawn_imported_reports_are_not_public(client, user, fb):
    # Envío de voluntario (tiene dueño) que luego caduca
    r = client.post("/facebook/volunteer-import", headers=user["h"], json={
        "url": _post_url(), "text": "Encontré este perrito, busca a su familia", "city": "Mérida", "consent": True})
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    fid = _imported("facebook")
    app_id = client.post("/lost-reports", headers=user["h"], json={"dog_name": "Propio", "city": "Mérida"}).json()["id"]
    # Públicos mientras están activos; external_url solo en los importados
    assert client.get(f"/lost-reports/{fid}").json()["external_url"]
    assert client.get(f"/lost-reports/{app_id}").json()["external_url"] is None
    db = _db()
    try:
        db.query(LostReport).filter(LostReport.id.in_([vid, fid, app_id])).update(
            {LostReport.status: "expired"}, synchronize_session=False)
        db.commit()
    finally:
        db.close()
    assert client.get(f"/lost-reports/{fid}").status_code == 404
    assert client.get(f"/lost-reports/{vid}").status_code == 404  # anónimo
    assert client.get(f"/lost-reports/{vid}", headers=user["h"]).status_code == 200  # quien lo envió sí lo ve
    assert client.get(f"/lost-reports/{app_id}").status_code == 200  # los de la app expirados siguen visibles
    listed = [x["id"] for x in client.get("/lost-reports", params={"status": "expired", "limit": 500}).json()]
    assert fid not in listed and vid not in listed
    listed_all = [x["id"] for x in client.get("/lost-reports", params={"status": "all", "limit": 500}).json()]
    assert fid not in listed_all
    # Importados caducados: no se renuevan
    renew = client.post(f"/lost-reports/{vid}/renew", headers=user["h"])
    assert renew.status_code == 400 and "30 días" in renew.json()["detail"]


def test_purge_imported_reports_deletes_text_and_files(client, user, fb, monkeypatch):
    up = client.post("/upload", headers=user["h"], files={"file": ("p.jpg", make_jpeg(21), "image/jpeg")})
    assert up.status_code == 200, up.text
    photo = up.json()["url"]
    from app.services import images

    path = images.local_path_for(photo)
    assert path is not None and path.exists()
    old = NOW() - datetime.timedelta(days=31)
    rid = _imported("facebook", created_at=old, photos=[photo],
                    ai_analysis={"is_dog": True}, photo_signature={"v": 1})
    keep = _imported("facebook", created_at=NOW() - datetime.timedelta(days=3))
    monkeypatch.setattr(settings, "fb_imported_purge_after_days", 0)
    db = _db()
    try:
        assert fbg.expire_imported_reports(db, report_ids=[rid, keep]) == [rid]
        assert fbg.purge_imported_reports(db, report_ids=[rid, keep]) == [rid]
    finally:
        db.close()
    report = _report(rid)
    assert report.purged_at is not None and report.status == "expired"
    assert report.photos == [] and report.ai_analysis is None and report.photo_signature is None
    assert report.description == fbg.PURGED_DESCRIPTION and report.external_url  # el enlace evita reimportarla
    assert not path.exists()  # el archivo se borró del disco (nadie más lo usaba)
    assert _report(keep).purged_at is None
    # Con FB_IMPORTED_PURGE_AFTER_DAYS se espera ese margen después de caducar
    monkeypatch.setattr(settings, "fb_imported_purge_after_days", 10)
    later = _imported("volunteer", created_at=old)
    db = _db()
    try:
        assert fbg.purge_imported_reports(db, report_ids=[later]) == []
    finally:
        db.close()


# --------------------------------------------------------------------------- «Soy el autor: retirar» sin cuenta
def test_author_removal_without_account(client, admin, fb):
    rid = _imported("facebook")
    ip = {"X-Real-IP": random_ip()}
    autora, otra = f"autora-{_uid()}@correo.mx", f"otra-{_uid()}@correo.mx"  # tope diario de acuses por correo
    bad = client.post("/facebook/author-removal", headers=ip, json={"report_id": rid, "email": "no-es-correo"})
    assert bad.status_code == 400
    r = client.post("/facebook/author-removal", headers=ip, json={
        "report_id": rid, "relation": "autor", "email": autora, "details": "Es mi publicación"})
    assert r.status_code == 201, r.text
    ack = r.json()
    assert ack["folio"].startswith("PF-") and ack["report_id"] == rid and "72 horas" in ack["message"]
    assert ack["requiere_confirmacion"] is True
    # Retiro inmediato: el reporte ya no es público
    assert _report(rid).is_hidden is True
    assert client.get(f"/lost-reports/{rid}").status_code == 404
    # La solicitud queda en la cola de moderación, sin cuenta (reporter None) y con el contacto
    queue = client.get("/admin/reports", headers=admin["h"], params={"status": "open", "target_type": "lost_report",
                                                                      "limit": 200})
    assert queue.status_code == 200, queue.text
    item = next(x for x in queue.json() if x["id"] == ack["content_report_id"])
    assert item["reason"] == fbg.AUTHOR_REMOVAL_REASON and item["reporter"] is None
    assert autora in item["details"]
    # Repetir no crea otra solicitud
    again = client.post("/facebook/author-removal", headers=ip, json={"report_id": rid, "email": autora})
    assert again.status_code == 200 and again.json()["folio"] == ack["folio"]
    # Por enlace de la publicación también se encuentra
    other = _imported("volunteer")
    by_url = client.post("/facebook/author-removal", headers=ip, json={
        "url": _report(other).external_url + "?mibextid=x", "email": otra, "relation": "aparezco"})
    assert by_url.status_code == 201 and by_url.json()["report_id"] == other

    # A las 72 h (si el admin no la descartó) se borra el contenido, solo si la persona autora confirmó su correo;
    # quien aparece en la publicación no la borra sin que el equipo lo apruebe
    from app.models import ComplianceRequest

    db = _db()
    try:
        old = NOW() - datetime.timedelta(hours=73)
        other_removal = by_url.json()["content_report_id"]
        db.query(ContentReport).filter(ContentReport.id.in_([ack["content_report_id"], other_removal])).update(
            {ContentReport.created_at: old}, synchronize_session=False)
        db.commit()
        assert fbg.purge_imported_reports(db, report_ids=[rid, other]) == []  # sin confirmar el correo
        db.query(ComplianceRequest).filter(ComplianceRequest.folio.in_([ack["folio"], by_url.json()["folio"]])).update(
            {ComplianceRequest.identity_verified_at: NOW()}, synchronize_session=False)
        db.commit()
        assert fbg.purge_imported_reports(db, report_ids=[rid, other]) == [rid]
    finally:
        db.close()
    assert _report(rid).purged_at is not None
    assert _report(other).purged_at is None and _report(other).is_hidden is True

    # Resolver la solicitud no falla aunque no haya cuenta a quién avisar
    res = client.patch(f"/admin/reports/{ack['content_report_id']}", headers=admin["h"],
                       json={"status": "resolved", "action": "hide_content", "notes": "Retirado a petición del autor"})
    assert res.status_code == 200, res.text


def test_author_removal_only_for_imported_and_rate_limited(client, user, fb):
    own = client.post("/lost-reports", headers=user["h"], json={"dog_name": "Mío", "city": "Mérida"}).json()["id"]
    ip = {"X-Real-IP": random_ip()}
    r = client.post("/facebook/author-removal", headers=ip, json={"report_id": own, "email": "a@correo.mx"})
    assert r.status_code == 400 and "importadas" in r.json()["detail"]
    assert client.post("/facebook/author-removal", headers=ip,
                       json={"report_id": 10**9, "email": "a@correo.mx"}).status_code == 404
    assert client.post("/facebook/author-removal", headers=ip, json={"email": "a@correo.mx"}).status_code == 400
    for _ in range(fb_router.AUTHOR_REMOVAL_HOURLY_LIMIT - 3):
        client.post("/facebook/author-removal", headers=ip, json={"report_id": 10**9, "email": "a@correo.mx"})
    limited = client.post("/facebook/author-removal", headers=ip, json={"report_id": 10**9, "email": "a@correo.mx"})
    assert limited.status_code == 429


def test_admin_csv_active_column(client, admin, fb):
    a, b, c = (f"https://www.facebook.com/groups/act{_uid()}" for _ in range(3))
    csv_text = ("name,state,city,group_url,active\n"
                f"Activo (prueba),Jalisco,,{a},sí\n"
                f"Pausado (prueba),Jalisco,,{b},no\n"
                f"Vacío (prueba),Jalisco,,{c},\n"
                f"Raro (prueba),Jalisco,,https://www.facebook.com/groups/raro{_uid()},quizá\n")
    try:
        r = client.post("/admin/facebook/groups/import-csv", headers=admin["h"], json={"csv": csv_text})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["created"] == 3 and out["created_paused"] == 2 and out["errors"][0]["line"] == 5
        db = _db()
        try:
            state = {g.group_url: g.is_active for g in db.query(FacebookGroup).filter(
                FacebookGroup.group_url.in_([a, b, c])).all()}
        finally:
            db.close()
        assert state == {a: True, b: False, c: False}
        # La columna "activo" también cambia la situación de un grupo existente
        r = client.post("/admin/facebook/groups/import-csv", headers=admin["h"],
                        json={"csv": f"nombre,estado,ciudad,url,activo\nPausado (prueba),Jalisco,,{b},1\n"})
        assert r.status_code == 200 and r.json()["updated"] == 1
        assert client.get("/admin/facebook/groups", headers=admin["h"],
                          params={"active": True, "state": "Jalisco"}).json()
    finally:
        db = _db()
        try:
            db.query(FacebookGroup).filter(FacebookGroup.group_url.in_([a, b, c])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
