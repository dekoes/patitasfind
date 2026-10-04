"""Pruebas de humo contra la base de datos del contenedor (docker exec patitasfind-backend pytest -q)."""
import io
import random
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _register(client, name="Usuario Prueba", **extra):
    email = f"test-{uuid.uuid4().hex[:10]}@pruebas.mx"
    r = client.post("/auth/register", json={"email": email, "password": "Segura123", "full_name": name, **extra})
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return {"email": email, "token": token, "h": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def user(client):
    return _register(client, "Adoptante Prueba")


@pytest.fixture
def owner(client):
    return _register(client, "Dueña Prueba")


@pytest.fixture
def make_user(client):
    return lambda name="Usuario": _register(client, name)


def make_jpeg(seed: int | None = None, size=(640, 480)) -> bytes:
    """Imagen sintética con formas aleatorias (distinta por semilla)."""
    rnd = random.Random(seed)
    img = Image.new("RGB", size, tuple(rnd.randint(0, 255) for _ in range(3)))
    draw = ImageDraw.Draw(img)
    for _ in range(12):
        x0, y0 = rnd.randint(0, size[0] - 50), rnd.randint(0, size[1] - 50)
        draw.ellipse([x0, y0, x0 + rnd.randint(30, 200), y0 + rnd.randint(30, 200)],
                     fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


@pytest.fixture
def jpeg():
    return make_jpeg
