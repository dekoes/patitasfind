# ADVERTENCIA: SOLO para un entorno local desechable. Este script APAGA Redis y PostgreSQL y mata el backend
# (kill -9 y SIGTERM) a mitad de operaciones. Nunca lo corras en el servidor de producción.
# Supone: backend en 127.0.0.1:8001 (uvicorn), frontend app/server.py en :8082, base "live" sembrada con
# backend/seed_data.py (SEED_PASSWORD=PatitasCI-2026), PostgreSQL en /var/pgdata y redis-server local.
# Uso: python loadtest/caos.py [escenario ...]

"""Pruebas de caos contra el stack local (backend :8001 vía frontend :8082).

Cada escenario: rompe una dependencia o mata un proceso a mitad de una operación, mide qué ve el usuario
(código HTTP, tiempo, cuerpo) y si el sistema se recupera solo al volver la dependencia.
"""
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time

import requests

BASE = "http://127.0.0.1:8082"
API = "http://127.0.0.1:8001"
PGBIN = "/usr/lib/postgresql/16/bin"
ENV = os.environ.copy()
results = []


def log(name, ok, detail):
    results.append((name, ok, detail))
    print(f"{'OK ' if ok else 'MAL'} | {name} | {detail}", flush=True)


def timed(method, url, **kw):
    t = time.time()
    try:
        r = requests.request(method, url, timeout=kw.pop("timeout", 30), **kw)
        return r.status_code, round(time.time() - t, 2), r.text[:160]
    except Exception as exc:  # noqa: BLE001
        return "EXC", round(time.time() - t, 2), type(exc).__name__ + ": " + str(exc)[:120]


def token(email="lucia@patitas.com", pw="PatitasCI-2026"):
    r = requests.post(f"{BASE}/auth/login", data={"username": email, "password": pw}, timeout=20)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def backend_pids():
    # Por la línea de comandos exacta del proceso (no por pgrep -f: también atraparía el shell que lo invoca)
    out = sh("ps -eo pid=,args=").stdout.splitlines()
    return [int(l.split()[0]) for l in out if " ".join(l.split()[1:3]).endswith("bin/uvicorn") or
            (len(l.split()) > 2 and l.split()[2].endswith("/uvicorn"))]


def start_backend():
    subprocess.Popen("cd /home/user/patitasfind/backend && exec uvicorn app.main:app --host 127.0.0.1 --port 8001 "
                     ">> /tmp/backend.log 2>&1", shell=True, env=ENV, start_new_session=True)
    for _ in range(60):
        if timed("GET", f"{API}/health", timeout=2)[0] == 200:
            return True
        time.sleep(0.5)
    return False


def png_bytes(size=(1600, 1200)):
    from PIL import Image
    buf = io.BytesIO()
    Image.effect_noise(size, 80).convert("RGB").save(buf, "JPEG", quality=95)
    return buf.getvalue()


# ------------------------------------------------------------------ 1. Redis caído
def redis_down():
    h = token()
    sh("redis-cli shutdown nosave")
    time.sleep(1)
    s, t, body = timed("GET", f"{BASE}/health")
    log("Redis caído: /health", s == 503, f"{s} en {t}s {body[:90]}")
    s, t, _ = timed("GET", f"{BASE}/dogs/featured")
    log("Redis caído: listado de perros (lectura)", s == 200 and t < 5, f"{s} en {t}s")
    s, t, body = timed("POST", f"{BASE}/auth/login", data={"username": "carlos@patitas.com", "password": "PatitasCI-2026"})
    log("Redis caído: iniciar sesión (usa límite de intentos en Redis)", s == 200 and t < 8, f"{s} en {t}s")
    s, t, body = timed("POST", f"{BASE}/lost-reports", headers=h, json={"dog_name": "Caos-Redis", "report_type": "lost",
                                                                         "latitude": 19.43, "longitude": -99.13})
    log("Redis caído: crear reporte de perro perdido (escritura + tareas)", s == 201 and t < 10, f"{s} en {t}s {body[:80]}")
    sh("redis-server --daemonize yes --dir /tmp")
    time.sleep(2)
    s, t, _ = timed("GET", f"{BASE}/health")
    log("Redis vuelve: /health se recupera sin reiniciar el backend", s == 200, f"{s} en {t}s")


# ------------------------------------------------------------------ 2. PostgreSQL caído
def postgres_down():
    h = token()
    sh(f"su postgres -c '{PGBIN}/pg_ctl -D /var/pgdata stop -m fast'")
    time.sleep(1)
    s, t, body = timed("GET", f"{BASE}/health")
    log("Postgres caído: /health avisa (503) y no se cuelga", s == 503 and t < 15, f"{s} en {t}s {body[:90]}")
    s, t, body = timed("GET", f"{BASE}/dogs/featured")
    log("Postgres caído: listado responde error limpio, sin colgarse", s in (500, 503) and t < 15, f"{s} en {t}s {body[:100]}")
    s, t, body = timed("GET", f"{BASE}/users/me", headers=h)
    log("Postgres caído: /users/me", s in (500, 503) and t < 15, f"{s} en {t}s {body[:100]}")
    sh(f"su postgres -c '{PGBIN}/pg_ctl -D /var/pgdata -l /var/pgdata/log -o \"-p 5432 -k /tmp\" start'")
    time.sleep(3)
    s, t, _ = timed("GET", f"{BASE}/dogs/featured")
    log("Postgres vuelve: el backend se reconecta solo (pool)", s == 200, f"{s} en {t}s")
    s, t, _ = timed("GET", f"{BASE}/users/me", headers=h)
    log("Postgres vuelve: la sesión del usuario sigue válida", s == 200, f"{s} en {t}s")


# ------------------------------------------------------------------ 3. Backend muere a mitad de una subida
def backend_killed_mid_upload():
    h = token()
    up_dir = "/home/user/patitasfind/backend/uploads"
    before = set(os.listdir(up_dir))
    count_sql = "select count(*) from lost_reports"
    n0 = sh(f"psql -h 127.0.0.1 -U patitasfind -d live -tAc '{count_sql}'").stdout.strip()
    data = png_bytes((3000, 2200))

    def slow_body():
        # Manda la foto lento para que el kill caiga a mitad de la petición
        yield b""
        for i in range(0, len(data), 64 * 1024):
            yield data[i:i + 64 * 1024]
            time.sleep(0.05)

    out = {}

    def do_upload():
        boundary = "caosboundary"
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"perro.jpg\"\r\n"
                f"Content-Type: image/jpeg\r\n\r\n").encode()
        tail = f"\r\n--{boundary}--\r\n".encode()

        def body():
            yield head
            yield from slow_body()
            yield tail
        out["r"] = timed("POST", f"{API}/upload", headers={**h, "Content-Type": f"multipart/form-data; boundary={boundary}"},
                         data=body(), timeout=60)

    th = threading.Thread(target=do_upload)
    th.start()
    time.sleep(0.8)
    for pid in backend_pids():
        os.kill(pid, signal.SIGKILL)
    th.join()
    log("Backend muere a mitad de subida: el cliente recibe error (no se queda esperando)",
        out["r"][0] == "EXC" or out["r"][0] >= 500, f"{out['r']}")
    ok = start_backend()
    log("Backend reinicia limpio después del kill -9", ok, "uvicorn responde /health")
    after = set(os.listdir(up_dir))
    new_files = sorted(after - before)
    log("Sin archivos a medias en uploads/ tras el kill", not new_files, f"archivos nuevos: {new_files[:5]}")
    n1 = sh(f"psql -h 127.0.0.1 -U patitasfind -d live -tAc '{count_sql}'").stdout.strip()
    log("Base sin registros huérfanos tras el kill", n0 == n1, f"reportes antes={n0} después={n1}")
    # La misma subida, ya con backend sano, funciona
    s, t, body = timed("POST", f"{API}/upload", headers=h, files={"file": ("perro.jpg", data[:], "image/jpeg")})
    log("Reintento de la subida después del reinicio", s in (200, 201), f"{s} en {t}s {body[:80]}")


# ------------------------------------------------------------------ 4. Petición en curso cuando se apaga con SIGTERM
def graceful_shutdown():
    """Simula el apagado de una réplica vieja durante un despliegue: SIGTERM con una subida a medias."""
    h = token()
    data = png_bytes((2000, 1500))
    out = {}

    def body():
        for i in range(0, len(data), 32 * 1024):
            yield data[i:i + 32 * 1024]
            time.sleep(0.04)

    def upload():
        boundary = "gracebound"
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"p.jpg\"\r\n"
                "Content-Type: image/jpeg\r\n\r\n").encode()

        def full():
            yield head
            yield from body()
            yield f"\r\n--{boundary}--\r\n".encode()
        out["r"] = timed("POST", f"{API}/upload", headers={**h, "Content-Type": f"multipart/form-data; boundary={boundary}"},
                         data=full(), timeout=60)

    th = threading.Thread(target=upload)
    th.start()
    time.sleep(0.7)
    for pid in backend_pids():
        os.kill(pid, signal.SIGTERM)
    th.join()
    log("SIGTERM con una subida a medias: la subida termina bien", out["r"][0] == 200, f"{out['r'][:2]}")
    ok = start_backend()
    log("Backend vuelve a arrancar después del SIGTERM", ok, "")


# ------------------------------------------------------------------ 5. Doble clic real en crear reporte
def double_submit():
    h = token()
    body = {"dog_name": f"Doble-{int(time.time())}", "report_type": "lost", "latitude": 19.43, "longitude": -99.13}
    res = []
    ths = [threading.Thread(target=lambda: res.append(timed("POST", f"{BASE}/lost-reports", headers=h, json=body)))
           for _ in range(2)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    n = sh(f"psql -h 127.0.0.1 -U patitasfind -d live -tAc \"select count(*) from lost_reports where dog_name='{body['dog_name']}'\"").stdout.strip()
    log("Doble envío simultáneo de un reporte (API sin protección de UI)", n == "1",
        f"respuestas {[r[0] for r in res]}, filas creadas={n} (la app bloquea el botón; la API no deduplica)")


if __name__ == "__main__":
    which = sys.argv[1:] or ["redis_down", "postgres_down", "backend_killed_mid_upload", "graceful_shutdown", "double_submit"]
    for name in which:
        print(f"\n=== {name} ===", flush=True)
        try:
            globals()[name]()
        except Exception as exc:  # noqa: BLE001
            log(name, False, f"el escenario explotó: {type(exc).__name__}: {exc}")
    print("\n=== RESUMEN ===")
    for name, ok, detail in results:
        print(f"{'OK ' if ok else 'MAL'} | {name}")
