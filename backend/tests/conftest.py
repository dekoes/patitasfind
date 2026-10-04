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


def random_phone() -> str:
    """Celular CDMX aleatorio de 10 dígitos (evita choques con el índice único de teléfonos verificados)."""
    return "55" + "".join(random.choice("0123456789") for _ in range(8))


def random_ip() -> str:
    return "10.%d.%d.%d" % (random.randint(0, 255), random.randint(0, 255), random.randint(1, 254))


def _register(client, name="Usuario Prueba", verify=True, **extra):
    email = f"test-{uuid.uuid4().hex[:10]}@pruebas.mx"
    phone = extra.pop("phone", None) or random_phone()
    body = {"email": email, "password": "Segura123", "full_name": name, "phone": phone, "accepted_terms": True, **extra}
    r = client.post("/auth/register", json=body)
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    # X-Real-IP distinto por usuario: el límite de 10 SMS por IP/hora no afecta a la suite
    u = {"email": email, "phone": "+52" + phone, "token": token, "ip": random_ip(),
         "h": {"Authorization": f"Bearer {token}"}, "password": "Segura123"}
    u["hip"] = {**u["h"], "X-Real-IP": u["ip"]}
    if verify:
        verify_user(client, u)
    return u


def verify_user(client, u):
    sent = client.post("/users/me/phone/send-code", headers=u["hip"])
    assert sent.status_code == 200, sent.text
    code = sent.json()["dev_code"]
    r = client.post("/users/me/phone/verify", headers=u["h"], json={"code": code})
    assert r.status_code == 200 and r.json() == {"verified": True}, r.text
    return u


@pytest.fixture
def user(client):
    return _register(client, "Adoptante Prueba")


@pytest.fixture
def owner(client):
    return _register(client, "Dueña Prueba")


@pytest.fixture
def unverified(client):
    return _register(client, "Sin Verificar", verify=False)


@pytest.fixture
def make_user(client):
    return lambda name="Usuario", **kw: _register(client, name, **kw)


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
