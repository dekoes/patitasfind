"""Pruebas de infraestructura: dependencias fijas, imagen, scripts de respaldo/monitoreo y configuración.

Corren en el contenedor de desarrollo (docker exec patitasfind-backend pytest -q tests/test_infra.py).
Las revisiones de nginx/ y de los docker-compose solo corren cuando la raíz del repositorio está
disponible (CI o un contenedor con el repo montado); dentro del contenedor de desarrollo se omiten.
"""
import http.server
import os
import re
import shutil
import subprocess
import threading
import time
from importlib import metadata
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.config import Settings, settings

BACKEND = Path(__file__).resolve().parent.parent
SCRIPTS = BACKEND / "scripts"
REPO = BACKEND.parent
HAS_REPO = (REPO / "nginx" / "nginx.conf").is_file() and (REPO / "docker-compose.production.yml").is_file()
needs_repo = pytest.mark.skipif(not HAS_REPO, reason="la raíz del repositorio no está montada")
RESTORE_DB = "patitasfind_restore_test"


def _requirements(name: str) -> list[str]:
    lines = []
    for raw in (BACKEND / name).read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _run(args, env=None, timeout=120, **kw):
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(args, env=full_env, capture_output=True, text=True, timeout=timeout, **kw)


def _pg_env() -> dict:
    url = make_url(settings.database_url)
    return {"PGHOST": url.host or "localhost", "PGPORT": str(url.port or 5432), "PGUSER": url.username or "",
            "PGPASSWORD": url.password or "", "PGDATABASE": url.database or ""}


def _pg_versions() -> tuple[int, int] | None:
    """(versión mayor de pg_dump, versión mayor del servidor) o None si faltan herramientas."""
    if not all(shutil.which(t) for t in ("pg_dump", "pg_restore", "psql", "createdb", "dropdb", "openssl")):
        return None
    client = re.search(r"\)\s+(\d+)", _run(["pg_dump", "--version"]).stdout)
    server = _run(["psql", "-tAc", "SHOW server_version_num"], env=_pg_env(), timeout=15)
    if not client or server.returncode != 0:
        return None
    return int(client.group(1)), int(server.stdout.strip()) // 10000


PG_VERSIONS = _pg_versions()
# pg_dump debe ser igual o más nuevo que el servidor; para restaurar, de la misma versión mayor
# (pg_restore 17 emite "SET transaction_timeout", que PostgreSQL 16 no conoce). En producción el
# contenedor de respaldo usa la imagen postgres:16, con las herramientas de la misma versión.
pg_dump_ok = pytest.mark.skipif(not PG_VERSIONS or PG_VERSIONS[0] < PG_VERSIONS[1],
                                reason="sin pg_dump/openssl compatibles con el servidor")
pg_same_major = pytest.mark.skipif(not PG_VERSIONS or PG_VERSIONS[0] != PG_VERSIONS[1],
                                   reason="pg_restore de otra versión mayor que el servidor")


# --------------------------------------------------------------------------- dependencias
def test_requirements_are_pinned():
    for line in _requirements("requirements.txt"):
        assert re.fullmatch(r"[A-Za-z0-9._-]+(\[[a-z0-9,_-]+\])?==[0-9][0-9A-Za-z.]*", line), line


def test_test_tools_only_in_dev_requirements():
    runtime = {re.split(r"[\[=]", r)[0].lower() for r in _requirements("requirements.txt")}
    assert not runtime & {"pytest", "httpx"}
    dev = _requirements("requirements-dev.txt")
    assert dev[0] == "-r requirements.txt"
    assert all("==" in r for r in dev[1:])
    assert {re.split(r"[\[=]", r)[0].lower() for r in dev[1:]} >= {"pytest", "httpx"}


def test_pins_match_installed_versions():
    """La imagen en uso tiene exactamente las versiones fijadas (si no, hay que reconstruirla)."""
    for line in _requirements("requirements.txt") + _requirements("requirements-dev.txt")[1:]:
        name, version = re.sub(r"\[.*\]", "", line).split("==")
        assert metadata.version(name) == version, f"{name}: instalado {metadata.version(name)}, fijado {version}"


# --------------------------------------------------------------------------- imagen
def test_dockerfile_multistage_non_root():
    text = (BACKEND / "Dockerfile").read_text()
    stages = text.split("\nFROM ")
    assert len(stages) == 3, "builder + runtime"
    runtime = stages[2]
    assert "gcc" not in runtime and "libpq-dev" not in runtime
    assert re.search(r"^USER app$", runtime, re.M)
    assert "--uid 1000" in runtime
    assert "PYTHONDONTWRITEBYTECODE=1" in runtime and "PYTHONUNBUFFERED=1" in runtime
    assert 'INSTALL_DEV" = "true"' in text
    assert re.search(r"^ARG PYTHON_IMAGE=python:3\.11\.\d+-slim-\w+$", text, re.M), "versión exacta de Python"


def test_dockerignore_excludes_dev_files():
    entries = set((BACKEND / ".dockerignore").read_text().split())
    assert {"tests/", "seed_data.py", "uploads/", "backups/", "__pycache__/", ".pytest_cache/",
            "celerybeat-schedule*", ".env"} <= entries


def test_entrypoint_checks_upload_dir():
    text = (BACKEND / "entrypoint.sh").read_text()
    assert "check_upload_dir" in text and "chown -R 1000:1000" in text


# --------------------------------------------------------------------------- scripts
@pytest.mark.parametrize("script", sorted(p.name for p in SCRIPTS.glob("*.sh")))
def test_script_syntax(script):
    path = SCRIPTS / script
    shell = "bash" if path.read_text().startswith("#!/usr/bin/env bash") else "sh"
    r = _run([shell, "-n", str(path)])
    assert r.returncode == 0, r.stderr


class _Recorder(http.server.BaseHTTPRequestHandler):
    hits: list = []

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else ""
        _Recorder.hits.append((self.path, body))
        self.send_response(200)
        self.end_headers()

    do_GET = _record
    do_POST = _record

    def log_message(self, *args):  # silencio
        pass


@pytest.fixture
def heartbeat_server():
    _Recorder.hits = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _Recorder.hits
    server.shutdown()


def _backup_env(tmp_path, **extra):
    return {"BACKUP_DIR": str(tmp_path / "backups"), "UPLOADS_DIR": str(tmp_path / "uploads"),
            "BACKUP_ENCRYPTION_PASSWORD": "clave-de-prueba", "BACKUP_S3_BUCKET": "", "BACKUP_HEARTBEAT_URL": "",
            "TZ": "America/Mexico_City", **extra}


def _snapshots(tmp_path):
    return sorted(p for p in (tmp_path / "backups" / "uploads").iterdir() if re.fullmatch(r"\d{8}-\d{6}", p.name))


def test_uploads_snapshot_is_incremental(tmp_path):
    up = tmp_path / "uploads"
    (up / "private").mkdir(parents=True)
    (up / ".pre-restore-20260101-000000").mkdir()
    (up / "a.jpg").write_text("a")
    (up / "b.jpg").write_text("b")
    (up / "private" / "acta.pdf").write_text("documento")
    (up / ".pre-restore-20260101-000000" / "viejo.jpg").write_text("x")
    env = _backup_env(tmp_path)

    r = _run(["sh", str(SCRIPTS / "backup.sh"), "uploads"], env=env)
    assert r.returncode == 0, r.stderr
    time.sleep(1.1)
    (up / "b.jpg").unlink()
    (up / "c.jpg").write_text("c")
    r = _run(["sh", str(SCRIPTS / "backup.sh"), "uploads"], env=env)
    assert r.returncode == 0, r.stderr

    first, second = _snapshots(tmp_path)
    files = lambda d: sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())  # noqa: E731
    assert files(first) == ["a.jpg", "b.jpg", "private/acta.pdf"]
    assert files(second) == ["a.jpg", "c.jpg", "private/acta.pdf"]  # sin .pre-restore-*, con private/
    # Lo que no cambió es un enlace duro (no ocupa espacio otra vez)
    assert (first / "a.jpg").stat().st_ino == (second / "a.jpg").stat().st_ino
    assert (first / "private" / "acta.pdf").stat().st_ino == (second / "private" / "acta.pdf").stat().st_ino
    assert (first / "b.jpg").read_text() == "b"  # la instantánea anterior conserva lo borrado
    assert "1 borrados" in r.stdout


def test_snapshot_retention_keeps_newest(tmp_path):
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "a.jpg").write_text("a")
    old = tmp_path / "backups" / "uploads" / "20200101-000000"
    old.mkdir(parents=True)
    env = _backup_env(tmp_path, BACKUP_MIN_KEEP="1", BACKUP_RETENTION_DAYS="14")
    r = _run(["sh", str(SCRIPTS / "backup.sh"), "uploads"], env=env)
    assert r.returncode == 0, r.stderr
    assert not old.exists()
    assert len(_snapshots(tmp_path)) == 1


def _encrypted_dump(tmp_path):
    env = _backup_env(tmp_path, **_pg_env(), BACKUP_REQUIRE_ENCRYPTION="true")
    r = _run(["sh", str(SCRIPTS / "backup.sh"), "db"], env=env, timeout=300)
    assert r.returncode == 0, r.stderr
    dumps = list((tmp_path / "backups" / "db").glob("db-*.dump.enc"))
    assert len(dumps) == 1
    return env, dumps[0]


@pg_dump_ok
def test_db_backup_is_encrypted(tmp_path):
    env, dump = _encrypted_dump(tmp_path)
    assert dump.read_bytes()[:8] == b"Salted__"  # cifrado con openssl, nunca en claro
    assert oct(dump.stat().st_mode & 0o777) == "0o600"
    # Se descifra con la misma contraseña y es un dump válido
    check = _run(["sh", "-c", f'. "{SCRIPTS}/lib-backup.sh"; openssl enc -d $OPENSSL_ENC_ARGS '
                              f'-pass env:BACKUP_ENCRYPTION_PASSWORD -in "{dump}" | pg_restore --list | grep -c "TABLE public"'],
                 env=env)
    assert check.returncode == 0 and int(check.stdout.strip()) > 5, check.stderr

    # Contraseña incorrecta: restore.sh no toca nada (ni crea la base destino)
    bad = _run(["sh", str(SCRIPTS / "restore.sh"), str(dump)],
               env={**env, "BACKUP_ENCRYPTION_PASSWORD": "otra", "PGDATABASE": RESTORE_DB, "RESTORE_YES": "1",
                    "RESTORE_CREATE_DB": "1"})
    assert bad.returncode == 1 and "No se cambió nada" in bad.stderr


@pg_same_major
def test_restore_into_scratch_db(tmp_path):
    env, dump = _encrypted_dump(tmp_path)
    # Restauración real SOLO en una base de prueba que se borra al final (nunca la de desarrollo)
    target = {**env, "PGDATABASE": RESTORE_DB, "RESTORE_YES": "1", "RESTORE_CREATE_DB": "1"}
    assert target["PGDATABASE"].endswith("_restore_test")
    _run(["dropdb", "--if-exists", RESTORE_DB], env=env)
    try:
        ok = _run(["sh", str(SCRIPTS / "restore.sh"), str(dump)], env=target, timeout=300)
        assert ok.returncode == 0, ok.stderr + ok.stdout
        count = _run(["psql", "-tAc", "SELECT count(*) FROM users"], env=target)
        assert count.returncode == 0 and int(count.stdout.strip()) >= 0
    finally:
        _run(["dropdb", "--if-exists", RESTORE_DB], env=env)


def test_backup_requires_encryption_and_reports_failure(tmp_path, heartbeat_server):
    url, hits = heartbeat_server
    env = _backup_env(tmp_path, BACKUP_ENCRYPTION_PASSWORD="", BACKUP_REQUIRE_ENCRYPTION="true",
                      BACKUP_HEARTBEAT_URL=f"{url}/hc")
    r = _run(["sh", str(SCRIPTS / "backup.sh"), "db"], env=env)
    assert r.returncode == 1
    assert "BACKUP_ENCRYPTION_PASSWORD" in r.stderr
    paths = [p for p, _ in hits]
    assert paths == ["/hc/start", "/hc/fail"]
    assert not list((tmp_path / "backups").rglob("*.dump*"))  # nada sin cifrar


def test_backup_heartbeat_and_offsite_warning(tmp_path, heartbeat_server):
    url, hits = heartbeat_server
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "a.jpg").write_text("a")
    env = _backup_env(tmp_path, BACKUP_HEARTBEAT_URL=f"{url}/hc")
    r = _run(["sh", str(SCRIPTS / "backup.sh"), "uploads"], env=env)
    assert r.returncode == 0, r.stderr
    assert [p for p, _ in hits] == ["/hc/start", "/hc"]
    assert "sin copia externa" in hits[-1][1]
    assert "SIN COPIA EXTERNA" in r.stderr  # advertencia visible en cada corrida sin BACKUP_S3_BUCKET


def test_backup_health(tmp_path):
    state = tmp_path / "backups" / ".state"
    state.mkdir(parents=True)
    env = _backup_env(tmp_path)
    health = lambda: _run(["sh", str(SCRIPTS / "backup.sh"), "health"], env=env)  # noqa: E731
    assert health().returncode == 1  # el ciclo no ha arrancado
    (state / "loop-heartbeat").touch()
    assert health().returncode == 0
    (state / "last-success").touch()
    time.sleep(1.1)
    (state / "last-failure").touch()
    assert health().returncode == 1  # el último intento falló
    time.sleep(1.1)
    (state / "last-success").touch()
    assert health().returncode == 0


def test_disk_check_alerts(tmp_path, heartbeat_server):
    url, hits = heartbeat_server
    env = {"DISK_CHECK_PATHS": str(tmp_path), "DISK_ALERT_URL": f"{url}/disco"}
    ok = _run(["sh", str(SCRIPTS / "disk-check.sh")], env={**env, "DISK_ALERT_THRESHOLD": "100"})
    assert ok.returncode == 0, ok.stderr
    alert = _run(["sh", str(SCRIPTS / "disk-check.sh")], env={**env, "DISK_ALERT_THRESHOLD": "0"})
    assert alert.returncode == 1
    assert "ALERTA de disco" in alert.stderr
    assert [p for p, _ in hits] == ["/disco", "/disco/fail"]
    assert "ALERTA" in hits[-1][1]


def test_is_due_schedule(tmp_path):
    stamp = tmp_path / "stamp"
    lib = SCRIPTS / "lib-backup.sh"

    def due(hour, interval=86400):
        return _run(["sh", "-c", f'. "{lib}"; is_due "{stamp}" "{hour}" {interval}']).returncode == 0

    assert due(3)  # nunca corrió
    stamp.touch()
    assert not due(0)  # ya corrió hoy
    old = time.time() - 3 * 86400
    os.utime(stamp, (old, old))
    assert due(23)  # atrasado: corre aunque no sea la hora
    assert due("", 86400)


# --------------------------------------------------------------------------- nginx y compose (raíz del repo)
@needs_repo
def test_nginx_locations_follow_rules():
    loc = (REPO / "nginx" / "snippets" / "patitasfind-locations.conf").read_text()
    code = "\n".join(line.split("#", 1)[0] for line in loc.splitlines())
    assert "add_header" not in code, "las location no usan add_header (anularía los de seguridad)"
    assert re.search(r"location \^~ /uploads/private/ \{\s*return 404;", code)
    assert re.search(r"location = /upload \{[^}]*client_max_body_size 25m;", code)
    assert re.search(r"location /upload/ \{[^}]*client_max_body_size 25m;", code)
    assert "sub_filter '%%SITE_URL%%' $site_url;" in code and "sub_filter_once off;" in code
    assert "error_page 404 /404.html;" in code
    # datos y plantillas legales (notas internas VERIFICAR_*) nunca se sirven; lo público son las páginas generadas
    deny = re.search(r"location ~\* \((?P<re>[^\n]+)\) \{\s*return 404;", code).group("re")
    for blocked in ("/app/legal/datos-legales.json", "/app/legal/datos-legales.example.json",
                    "/app/legal/plantillas/privacidad.html", "/app/server.py", "/app/test-e2e.mjs"):
        assert re.search(deny, blocked, re.IGNORECASE), blocked
    for allowed in ("/app/legal/privacidad.html", "/app/legal/terminos.html", "/app/legal/legal.css"):
        assert not re.search(deny, allowed, re.IGNORECASE), allowed


@needs_repo
def test_nginx_main_config():
    conf = (REPO / "nginx" / "nginx.conf").read_text()
    assert "worker_rlimit_nofile 65535;" in conf and "worker_connections 8192;" in conf
    assert "resolver 127.0.0.11" in conf and "server backend:8000 resolve;" in conf
    assert '"public, max-age=31536000, immutable"' in conf
    assert '"request_id":"$req_id"' in conf
    proxy = (REPO / "nginx" / "snippets" / "proxy.conf").read_text()
    assert "proxy_set_header X-Request-ID $req_id;" in proxy
    for mode in ("https", "http-only"):
        tpl = (REPO / "nginx" / "templates" / mode / "patitasfind.conf.template").read_text()
        csp = re.search(r'Content-Security-Policy "([^"]+)"', tpl).group(1)
        assert "unpkg.com" not in csp and "wss://${DOMAIN}" in csp
        # mapas: OSM (clásico) y CARTO (claro/voyager/oscuro en app/theme.js); sin esto los mosaicos salen en blanco
        img_src = set(re.search(r"img-src ([^;]+)", csp).group(1).split())
        assert {"https://tile.openstreetmap.org", "https://*.tile.openstreetmap.org",
                "https://*.basemaps.cartocdn.com", "https://*.googleusercontent.com"} <= img_src
        assert "add_header Cache-Control $uploads_cache_control;" in tpl
        assert "map $host $site_url" in tpl
    realip = (REPO / "nginx" / "snippets" / "cloudflare-realip.conf").read_text()
    assert "real_ip_header CF-Connecting-IP;" in realip and realip.count("set_real_ip_from") >= 20


def _compose(name):
    import yaml

    return yaml.safe_load((REPO / name).read_text())


@needs_repo
def test_production_compose():
    c = _compose("docker-compose.production.yml")
    svc = c["services"]
    assert "container_name" not in svc["backend"] and "ports" not in svc["backend"]
    assert "${WEB_CONCURRENCY:-4}" in svc["backend"]["command"]
    assert "${CELERY_CONCURRENCY:-4}" in svc["celery-worker"]["command"]
    assert "/var/lib/celery/celerybeat-schedule" in svc["celery-beat"]["command"]
    assert "healthcheck" in svc["celery-beat"] and "healthcheck" in svc["backup"]
    assert "volatile-lru" in svc["redis"]["command"]
    assert svc["postgres"]["shm_size"] == "1g" and "max_connections=150" in svc["postgres"]["command"]
    for name, s in svc.items():
        image = s["image"]
        if image.startswith("patitasfind-"):
            continue
        assert re.search(r":v?\d+\.\d+(\.\d+)?(-[a-z0-9.]+)?$", image), f"{name}: imagen sin versión fija ({image})"
    assert "FROM postgres:16." in svc["backup"]["build"]["dockerfile_inline"]


@needs_repo
@pytest.mark.parametrize("name", ["docker-compose.production.yml", "docker-compose.yml"])
def test_compose_passes_every_setting(name):
    """Toda variable de app/config.py llega al backend (salvo constantes internas)."""
    internal = {"smsmasivos_url", "zernio_sms_url", "otp_ttl_minutes", "otp_max_attempts", "otp_resend_cooldown_seconds",
                "otp_max_sends_per_phone_hour", "otp_max_sends_per_ip_hour", "default_phone_country_code",
                "currency", "facebook_groups", "git_sha", "postgres_password", "upload_dir", "environment",
                "redis_url", "use_celery"}
    env = _compose(name)["x-backend-env"]
    services = _compose(name)["services"]
    available = set(env) | set(services["backend"].get("environment", {}))
    missing = [f.upper() for f in Settings.model_fields if f not in internal and f.upper() not in available]
    assert not missing, f"faltan en x-backend-env de {name}: {', '.join(missing)}"
