"""Seguridad de seed_data.py (las pruebas de scripts/render-legal.py están en test_render_legal.py)."""
import uuid

import pytest

import seed_data


# --------------------------------------------------------------------------- seed_data.py
def test_refusal_reason_production_always():
    url = "postgresql+psycopg2://patitasfind:x@postgres:5432/patitasfind"
    assert "producción" in seed_data.refusal_reason("production", url)
    assert "producción" in seed_data.refusal_reason(" Production ", url, force=True)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "postgres"])
def test_refusal_reason_local_hosts_ok(host):
    assert seed_data.refusal_reason("development", f"postgresql+psycopg2://u:p@{host}:5432/db") is None


def test_refusal_reason_remote_host_needs_force():
    url = "postgresql+psycopg2://u:p@db.ejemplo.com:5432/db"
    reason = seed_data.refusal_reason("development", url)
    assert reason and "db.ejemplo.com" in reason and "--force" in reason
    assert seed_data.refusal_reason("development", url, force=True) is None


def test_seed_password(monkeypatch):
    monkeypatch.setenv("SEED_PASSWORD", "ClaveDePrueba1")
    assert seed_data.seed_password() == ("ClaveDePrueba1", False)
    monkeypatch.setenv("SEED_PASSWORD", "corta")
    with pytest.raises(SystemExit):
        seed_data.seed_password()
    monkeypatch.delenv("SEED_PASSWORD")
    first, generated = seed_data.seed_password()
    assert generated and len(first) >= 16 and first != seed_data.seed_password()[0]


@pytest.fixture
def fake_seed(monkeypatch):
    calls = []

    def _seed(password, reset=False):
        calls.append({"password": password, "reset": reset})
        return 0

    monkeypatch.setattr(seed_data, "seed", _seed)
    monkeypatch.setenv("SEED_PASSWORD", "ClaveDePrueba1")
    return calls


def test_main_refuses_production(monkeypatch, fake_seed, capsys):
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert seed_data.main(["--reset", "--force"]) == 2
    assert fake_seed == [] and "producción" in capsys.readouterr().err


def test_main_refuses_remote_database(monkeypatch, fake_seed):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@db.ejemplo.com:5432/db")
    assert seed_data.main([]) == 2 and fake_seed == []


def test_main_defaults_to_no_reset(monkeypatch, fake_seed, capsys):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert seed_data.main([]) == 0
    assert fake_seed == [{"password": "ClaveDePrueba1", "reset": False}]
    assert "ClaveDePrueba1" in capsys.readouterr().out
    assert seed_data.main(["--reset"]) == 0 and fake_seed[-1]["reset"] is True


def test_seed_without_reset_never_deletes(client):
    """Con datos de prueba existentes y sin --reset, seed() se niega y no borra nada."""
    from app.database import SessionLocal
    from app.models import Dog, User

    db = SessionLocal()
    marker = User(email=f"pytest-seed-{uuid.uuid4().hex[:8]}@patitas.com", full_name="Semilla Prueba", role="user")
    db.add(marker)
    db.commit()
    try:
        dogs_before = db.query(Dog).count()
        db.rollback()  # sin transacciones abiertas mientras corre seed()
        assert seed_data.seed("ClaveDePrueba1", reset=False) == 1
        db.expire_all()
        assert db.query(Dog).count() == dogs_before
        assert db.get(User, marker.id) is not None
    finally:
        db.delete(db.get(User, marker.id))
        db.commit()
        db.close()


# --------------------------------------------------------------------------- render-legal.py
# Las pruebas del generador del centro legal están en tests/test_render_legal.py.
