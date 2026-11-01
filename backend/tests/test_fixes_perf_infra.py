"""Correcciones de la revisión (rendimiento/infraestructura): listados sin JSON pesado, reloj de
expiración de reportes independiente de las escrituras en segundo plano, README de carga, CSP y
archivos internos que ni Nginx ni el servidor local sirven."""
import contextlib
import datetime
import importlib.util
import random
import re

import pytest
from sqlalchemy import event

from app.config import settings
from app.database import SessionLocal, engine
from app.models import Dog, LostReport, User
from app.services import geo
from app.tasks.reports import expire_stale_reports_now
from tests.test_infra import REPO, needs_repo

HEAVY = ("ai_analysis", "photo_signature")
ANALYSIS = {"is_dog": True, "breed_guess": "Mestizo", "colors": ["café"], "url": None}
SIGNATURE = {"v": 1, "photos": []}


# --------------------------------------------------------------------------- utilidades
def _spot():
    """Un punto en el Pacífico (sin datos de otras pruebas alrededor)."""
    return round(random.uniform(-20, 20), 4), round(random.uniform(-150, -120), 4)


def _user_id(client, u) -> int:
    return client.get("/users/me", headers=u["h"]).json()["id"]


def _make_admin(client, make_user) -> dict:
    a = make_user("Admin Correcciones")
    db = SessionLocal()
    try:
        db.query(User).filter(User.email == a["email"]).update({User.role: "admin"})
        db.commit()
    finally:
        db.close()
    token = client.post("/auth/login", data={"username": a["email"], "password": a["password"]}).json()["access_token"]
    a["h"] = {"Authorization": f"Bearer {token}"}
    return a


@contextlib.contextmanager
def statements():
    captured: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield captured
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _report(rid: int) -> LostReport:
    db = SessionLocal()
    try:
        rep = db.query(LostReport).filter(LostReport.id == rid).first()
        db.expunge(rep)
        return rep
    finally:
        db.close()


def _age_report(rid: int, days: int):
    """Deja el reporte como si quien reportó no lo hubiera tocado en `days` días."""
    old = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    db = SessionLocal()
    try:
        rep = db.query(LostReport).filter(LostReport.id == rid).first()
        rep.last_activity_at = rep.updated_at = rep.created_at = old
        db.commit()
    finally:
        db.close()
    return old


# --------------------------------------------------------------------------- D2: JSON pesado fuera de los listados
def test_heavy_json_columns_are_deferred_and_never_serialized(client, owner, user):
    assert set(HEAVY) <= set(geo.HEAVY_LIST_COLUMNS)
    lat, lon = _spot()
    db = SessionLocal()
    try:
        dog = Dog(owner_id=_user_id(client, owner), name="FIX-pesado", status="available", photos=[], latitude=lat,
                  longitude=lon, ai_analysis=ANALYSIS, photo_signature=SIGNATURE)
        rep = LostReport(reporter_id=_user_id(client, user), dog_name="FIX-reporte", report_type="lost", photos=[],
                         latitude=lat, longitude=lon, status="active", ai_analysis=ANALYSIS, photo_signature=SIGNATURE)
        db.add_all([dog, rep])
        db.commit()
        dog_id, rep_id = dog.id, rep.id
    finally:
        db.close()

    geo_params = {"lat": lat, "lon": lon, "radius_km": 5}
    public_lists = [
        ("/dogs/nearby", geo_params, None, dog_id, "dogs"),
        ("/dogs/featured", geo_params, None, dog_id, "dogs"),
        ("/dogs/discover", geo_params, user["h"], dog_id, "dogs"),
        ("/lost-reports", geo_params, None, rep_id, "lost_reports"),
    ]
    for path, params, headers, expected_id, table in public_lists:
        with statements() as sql:
            r = client.get(path, params=params, headers=headers)
        assert r.status_code == 200, (path, r.text)
        items = r.json()
        assert expected_id in [i["id"] for i in items], path
        for item in items:
            assert not set(HEAVY) & set(item), (path, sorted(set(HEAVY) & set(item)))
        # ni en la consulta del listado ni en cargas perezosas posteriores (una por fila sería N+1)
        for stmt in sql:
            if f"FROM {table}" in stmt:
                assert f"{table}.ai_analysis" not in stmt and f"{table}.photo_signature" not in stmt, (path, stmt)

    # Detalles y vistas del dueño/admin: el esquema tampoco los expone
    for path, headers in [(f"/dogs/{dog_id}", None), (f"/lost-reports/{rep_id}", None), ("/dogs/me", owner["h"]),
                          ("/lost-reports/me", user["h"])]:
        body = client.get(path, headers=headers).json()
        for item in body if isinstance(body, list) else [body]:
            assert not set(HEAVY) & set(item), path

    # El matching sigue viendo el análisis completo (lo carga de la fila, no del listado)
    from app.services.matching import attributes_for

    assert attributes_for(_report(rep_id)) == ANALYSIS


# --------------------------------------------------------------------------- expiración: reloj de quien reporta
def test_background_writes_do_not_extend_report_expiry(client, user, make_user):
    lat, lon = _spot()
    rid = client.post("/lost-reports", headers=user["h"],
                      json={"dog_name": "Olvidado", "report_type": "lost", "latitude": lat, "longitude": lon}).json()["id"]
    assert _report(rid).last_activity_at is not None  # se fija al crear
    old = _age_report(rid, settings.report_expiry_days + 1)

    # Enriquecimiento en segundo plano (firma + IA) y moderación: updated_at cambia, el reloj no
    db = SessionLocal()
    try:
        rep = db.query(LostReport).filter(LostReport.id == rid).first()
        rep.photo_signature, rep.ai_analysis = SIGNATURE, ANALYSIS
        db.commit()
        rep.is_hidden = True
        db.commit()
        rep.is_hidden = False
        db.commit()
        db.refresh(rep)
        assert rep.updated_at > old + datetime.timedelta(days=1)  # onupdate sí lo movió...
        assert rep.last_activity_at == old  # ...pero la actividad del reportante sigue siendo la vieja
        assert expire_stale_reports_now(db, report_ids=[rid]) == [rid]
    finally:
        db.close()
    assert client.get(f"/lost-reports/{rid}").json()["status"] == "expired"

    # Renovar sí reinicia el plazo
    before = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
    assert client.post(f"/lost-reports/{rid}/renew", headers=user["h"]).json()["status"] == "active"
    assert _report(rid).last_activity_at >= before
    db = SessionLocal()
    try:
        assert expire_stale_reports_now(db, report_ids=[rid]) == []
    finally:
        db.close()

    # Reactivación por un admin: cuenta como actividad (si no, expiraría al día siguiente)
    _age_report(rid, settings.report_expiry_days + 1)
    admin = _make_admin(client, make_user)
    r = client.patch(f"/admin/lost-reports/{rid}/status", headers=admin["h"], json={"status": "active"})
    assert r.status_code == 200, r.text
    assert _report(rid).last_activity_at >= before
    db = SessionLocal()
    try:
        assert expire_stale_reports_now(db, report_ids=[rid]) == []
    finally:
        db.close()

    # Resolver también es actividad de quien reporta
    _age_report(rid, 10)
    assert client.patch(f"/lost-reports/{rid}/resolve", headers=user["h"]).status_code == 200
    rep = _report(rid)
    assert rep.status == "resolved" and rep.last_activity_at >= before


def test_report_without_activity_timestamp_uses_created_at(client, user):
    """Filas creadas por SQL directo (datos sintéticos) o anteriores a la columna: cuenta desde created_at."""
    lat, lon = _spot()
    rid = client.post("/lost-reports", headers=user["h"],
                      json={"dog_name": "Antiguo", "report_type": "found", "latitude": lat, "longitude": lon}).json()["id"]
    db = SessionLocal()
    try:
        rep = db.query(LostReport).filter(LostReport.id == rid).first()
        rep.created_at = datetime.datetime.utcnow() - datetime.timedelta(days=settings.report_expiry_days + 1)
        rep.last_activity_at = None
        db.commit()
        assert expire_stale_reports_now(db, report_ids=[rid]) == [rid]
    finally:
        db.close()


# --------------------------------------------------------------------------- D8 / O1: documentación y archivos servidos
@needs_repo
def test_loadtest_readme_matches_backend_limits():
    import yaml

    backend = yaml.safe_load((REPO / "docker-compose.production.yml").read_text())["services"]["backend"]
    limits = backend["deploy"]["resources"]["limits"]
    cpus = str(limits["cpus"]).rstrip("0").rstrip(".")
    memory = str(limits["memory"]).upper().rstrip("G")
    section = (REPO / "loadtest" / "README.md").read_text().split("## Qué mirar mientras corre", 1)[1]
    assert f"{cpus} CPU / {memory} GB" in section and "WEB_CONCURRENCY=4" in section
    assert "${WEB_CONCURRENCY:-4}" in backend["command"]


BLOCKED_PATHS = ("/app/legal/datos-legales.json", "/app/legal/datos-legales.example.json",
                 "/app/legal/plantillas/privacidad.html", "/app/legal/plantillas/aviso-simplificado.txt",
                 "/app/server.py", "/app/test-e2e.mjs", "/app/package.json", "/app/e2e-shots/x.png", "/app/.env")
ALLOWED_PATHS = ("/app/legal/privacidad.html", "/app/legal/terminos.html", "/app/legal/legal.css",
                 "/app/legal/aviso-simplificado.txt", "/app/app.js", "/app/index.html", "/app/", "/",
                 "/.well-known/acme-challenge/token")


@needs_repo
def test_internal_files_denied_by_nginx_and_dev_server():
    loc = (REPO / "nginx" / "snippets" / "patitasfind-locations.conf").read_text()
    code = "\n".join(line.split("#", 1)[0] for line in loc.splitlines())
    nginx_re = re.compile(re.search(r"location ~\* \(([^\n]+)\) \{\s*return 404;", code).group(1), re.IGNORECASE)
    dotfiles_re = re.compile(re.search(r"location ~ (/\\\.\(\?!well-known/\))", code).group(1))

    spec = importlib.util.spec_from_file_location("dev_server", REPO / "app" / "server.py")
    dev_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev_server)

    for path in BLOCKED_PATHS:
        assert nginx_re.search(path) or dotfiles_re.search(path), f"nginx sirve {path}"
        assert dev_server.DEV_FILES_RE.search(path), f"server.py sirve {path}"
    for path in ALLOWED_PATHS:
        assert not nginx_re.search(path) and not dotfiles_re.search(path), f"nginx bloquea {path}"
        assert not dev_server.DEV_FILES_RE.search(path), f"server.py bloquea {path}"
