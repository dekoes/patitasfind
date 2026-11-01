"""Fase de integración: esquema solo con Alembic, /health endurecido, docs apagadas en producción,
503 al agotarse el pool y perros ocultos sin "like"."""
import importlib
import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app import migrate
from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import Dog
import app.main as main_module


# --------------------------------------------------------------------------- Alembic
def test_schema_matches_models_and_is_at_head():
    """La base está en la última revisión y no hay diferencias con models.py (equivale a `alembic check`)."""
    head = ScriptDirectory.from_config(migrate._config()).get_current_head()
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert version == head == "0004_cumplimiento"
    assert diffs == [], diffs


def test_migrate_is_idempotent():
    """Una base ya versionada solo hace `upgrade head` (no-op) y conserva la revisión."""
    assert migrate.run() == "upgraded"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0004_cumplimiento"


def test_app_no_longer_creates_schema_at_startup():
    """La app no hace create_all ni ALTERs al arrancar: eso quedó en app/migrate.py (Alembic)."""
    import inspect

    source = inspect.getsource(main_module)
    assert "create_all" not in source and "STARTUP_MIGRATIONS" not in source
    assert migrate.LEGACY_STATEMENTS and not any("demo@" in s for s in migrate.LEGACY_STATEMENTS)


# --------------------------------------------------------------------------- /health
def test_health_in_development_includes_details(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["environment"] == "development"
    assert body["checks"]["database"] == "ok" and body["checks"]["uploads"] == "ok"


def test_health_low_disk_is_degraded_without_details_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(main_module, "uploads_free_percent", lambda: 2.5)
    r = client.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded" and body["checks"]["uploads"] == "error"
    assert "environment" not in body and "2.5" not in r.text


def test_health_hides_exception_class_in_production(client, monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("se cayó la base")

    monkeypatch.setattr(main_module, "engine", BrokenEngine())
    monkeypatch.setattr(settings, "environment", "production")
    body = client.get("/health").json()
    assert body["checks"]["database"] == "error" and "RuntimeError" not in str(body)
    monkeypatch.setattr(settings, "environment", "development")
    assert client.get("/health").json()["checks"]["database"] == "error: RuntimeError"


# --------------------------------------------------------------------------- docs y 503
def test_docs_disabled_in_production(monkeypatch):
    """Con ENVIRONMENT=production la app se crea sin /docs, /redoc ni /openapi.json."""
    monkeypatch.setattr(settings, "environment", "production")
    try:
        prod_app = importlib.reload(main_module).app
        assert prod_app.docs_url is None and prod_app.redoc_url is None and prod_app.openapi_url is None
        with TestClient(prod_app) as c:
            assert {c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")} == {404}
            assert c.get("/health").status_code == 200
    finally:
        monkeypatch.setattr(settings, "environment", "development")
        dev_app = importlib.reload(main_module).app
    assert dev_app.docs_url == "/docs"
    with TestClient(dev_app) as c:
        assert c.get("/openapi.json").status_code == 200


def test_pool_exhausted_returns_503_in_spanish(client, user):
    def exhausted():
        raise PoolTimeoutError("QueuePool limit reached")
        yield  # noqa: unreachable - debe ser generador como get_db

    client.app.dependency_overrides[get_db] = exhausted
    try:
        r = client.get("/notifications", headers=user["h"])
    finally:
        client.app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 503 and "demanda" in r.json()["detail"]


# --------------------------------------------------------------------------- moderación
def test_like_on_hidden_dog_is_404(client, owner, user):
    r = client.post("/dogs", headers=owner["h"], json={"name": f"Oculto {uuid.uuid4().hex[:6]}", "size": "Mediano"})
    assert r.status_code == 201, r.text
    dog_id = r.json()["id"]
    db = SessionLocal()
    try:
        db.get(Dog, dog_id).is_hidden = True
        db.commit()
    finally:
        db.close()
    assert client.post(f"/dogs/{dog_id}/like", headers=user["h"]).status_code == 404
