"""Fallos de dependencias (pruebas de caos, ver docs/auditoria-produccion.md)."""
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.main import app


def test_database_down_returns_clean_503(client, user):
    """Con PostgreSQL caído la app recibía «Internal Server Error» (500 en texto plano); ahora un 503 en JSON."""

    class DownSession:
        def __getattr__(self, name):
            def fail(*a, **kw):
                raise OperationalError("SELECT 1", {}, Exception("connection refused"))
            return fail

    def down_db():
        yield DownSession()

    app.dependency_overrides[get_db] = down_db
    try:
        r = client.get("/users/me", headers=user["h"])  # siempre consulta la base (sin caché)
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 503
    assert r.headers["retry-after"] == "15"
    assert "no está disponible" in r.json()["detail"]
