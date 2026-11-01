"""Servidor local de desarrollo para el frontend de GuauWoow (puerto 8082).

- Sirve la landing en /, la app en /app/ y el panel en /admin/ (robots.txt, sitemap.xml,
  manifest.webmanifest y favicon en la raíz; 404.html para rutas inexistentes).
- Reemplaza %%SITE_URL%% por http://localhost:<PORT> en HTML/XML/TXT/manifest (en producción lo hace Nginx).
- Centro legal: /app/legal/ muestra centro-legal.html; /legal y /legal/<slug> redirigen a /app/legal/<slug>.html
  y /.well-known/security.txt se sirve como text/plain.
- Reenvía al backend (localhost:8001) todas las rutas de la API, incluidas subidas
  multipart, y hace túnel de WebSockets (/ws/...) para el chat en tiempo real.

Uso:  python3 server.py   (y opcionalmente: cloudflared tunnel --url http://localhost:8082)
"""
import http.client
import http.server
import os
import re
import select
import socket
import socketserver
from pathlib import Path
from urllib.parse import urlparse

PORT = int(os.environ.get("PORT", "8082"))
ROOT = Path(__file__).parent
BACKEND_HOST = os.environ.get("BACKEND_HOST", "localhost")
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8001"))

PROXIED_PREFIXES = (
    "/api/", "/auth/", "/users/",
    "/dogs", "/matches", "/messages/", "/conversations",
    "/notifications", "/refuges", "/products", "/orders",
    "/lost-reports", "/foster-homes", "/reminders", "/reports", "/veterinaries",
    "/whatsapp/", "/facebook/", "/search/", "/ai/", "/payments/", "/cumplimiento/",
    "/upload", "/uploads/", "/ws/",
    "/docs", "/redoc", "/openapi.json", "/health",
)

# Archivos estáticos del panel; cualquier otra ruta /admin/... es API del backend
ADMIN_STATIC = {
    "/admin/": "admin.html",
    "/admin/index.html": "admin.html",
    "/admin/admin.css": "admin.css",
    "/admin/admin.js": "admin.js",
}

# Archivos de texto donde se reemplaza %%SITE_URL%% (en producción lo hace Nginx con sub_filter)
SITE_URL_TOKEN = b"%%SITE_URL%%"
TEXT_TYPES = {".html": "text/html; charset=utf-8", ".xml": "application/xml; charset=utf-8",
              ".txt": "text/plain; charset=utf-8", ".webmanifest": "application/manifest+json; charset=utf-8"}

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "host", "content-length"}

# Archivos de desarrollo/legado y datos internos que nunca se sirven (mismo criterio que la location de
# nginx/snippets/patitasfind-locations.conf): código, pruebas, y los datos/plantillas legales que solo
# alimentan scripts/render-legal.py (lo público son las páginas generadas)
DEV_FILES_RE = re.compile(
    r"(\.(py|pyc|mjs|md|sh|log)$|/package(-lock)?\.json$|/node_modules/|/e2e-shots/|/test-[^/]*$|/_build_index"
    r"|/app-mvp|/app-demo|/index-demo|/legal/datos-legales[^/]*\.json$|/legal/plantillas/|/\.(?!well-known/))",
    re.IGNORECASE,
)


# Centro legal: /legal y /legal/<slug> son atajos de /app/legal/<slug>.html; /app/legal/ muestra el centro legal
# (igual que nginx/snippets/patitasfind-locations.conf)
LEGAL_SHORT_RE = re.compile(r"^/legal/([a-z0-9-]+?)(?:\.html)?/?$")
LEGAL_INDEX = "centro-legal.html"


def legal_redirect(path: str) -> str | None:
    """Destino de los atajos legales (/legal, /legal/<slug>, /app/legal, /security.txt) o None."""
    if path in ("/legal", "/legal/", "/app/legal"):
        return "/app/legal/"
    if path == "/security.txt":
        return "/.well-known/security.txt"
    m = LEGAL_SHORT_RE.match(path)
    return f"/app/legal/{m.group(1)}.html" if m else None


def is_backend_path(path: str) -> bool:
    if path.startswith("/admin/") and path not in ADMIN_STATIC:
        return True
    return path.startswith(PROXIED_PREFIXES)


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".webmanifest": "application/manifest+json", ".webp": "image/webp", ".mjs": "text/javascript"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    # ------------------------------------------------------------------ cuerpo
    def _read_body(self) -> bytes | None:
        length = self.headers.get("Content-Length")
        if length:
            return self.rfile.read(int(length))
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            chunks = []
            while True:
                size_line = self.rfile.readline().strip()
                size = int(size_line.split(b";")[0], 16) if size_line else 0
                if size == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            return b"".join(chunks)
        return None

    # ------------------------------------------------------------------ proxy HTTP
    def _proxy_to_backend(self):
        if self.path.startswith("/ws/") and (self.headers.get("Upgrade") or "").lower() == "websocket":
            return self._tunnel_websocket()

        body = self._read_body()
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        headers["Host"] = f"{BACKEND_HOST}:{BACKEND_PORT}"
        headers["X-Forwarded-For"] = self.client_address[0]
        headers["X-Forwarded-Host"] = self.headers.get("Host", f"localhost:{PORT}")
        headers["X-Forwarded-Proto"] = self.headers.get("X-Forwarded-Proto", "http")
        if body is not None:
            headers["Content-Length"] = str(len(body))
        try:
            conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=120)
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status, resp.reason)
            for header, value in resp.getheaders():
                if header.lower() in HOP_BY_HOP:
                    continue
                self.send_header(header, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            conn.close()
        except Exception as exc:  # noqa: BLE001
            payload = f'{{"detail":"No se pudo conectar con el backend: {exc}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    # ------------------------------------------------------------------ túnel WebSocket
    def _tunnel_websocket(self):
        try:
            upstream = socket.create_connection((BACKEND_HOST, BACKEND_PORT), timeout=10)
        except OSError as exc:
            self.send_error(502, f"Backend no disponible: {exc}")
            return
        lines = [f"{self.command} {self.path} HTTP/1.1", f"Host: {BACKEND_HOST}:{BACKEND_PORT}"]
        for k, v in self.headers.items():
            if k.lower() != "host":
                lines.append(f"{k}: {v}")
        upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        upstream.settimeout(None)
        client = self.connection
        client.settimeout(None)
        sockets = [client, upstream]
        try:
            while True:
                readable, _, errored = select.select(sockets, [], sockets, 300)
                if errored or not readable:
                    break
                for s in readable:
                    data = s.recv(65536)
                    if not data:
                        return
                    (upstream if s is client else client).sendall(data)
        except OSError:
            pass
        finally:
            upstream.close()
            self.close_connection = True

    # ------------------------------------------------------------------ estáticos
    def translate_path(self, path):
        path = urlparse(path).path
        if path in ("/", "/index.html"):
            return str(ROOT / "landing.html")
        if path in ADMIN_STATIC:
            return str(ROOT / ADMIN_STATIC[path])
        if path == "/app/":
            return str(ROOT / "index.html")
        if path == "/app/legal/":
            return str(ROOT / "legal" / LEGAL_INDEX)
        if path.startswith("/app/"):
            return super().translate_path(path[4:])
        return super().translate_path(path)

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_bytes(self, status: int, content_type: str, data: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _not_found(self):
        page = ROOT / "404.html"
        data = page.read_bytes().replace(SITE_URL_TOKEN, self._site_url()) if page.is_file() else b"No encontrado"
        return self._send_bytes(404, "text/html; charset=utf-8", data)

    def _serve_static(self):
        """Como SimpleHTTPRequestHandler, pero reemplaza %%SITE_URL%% en HTML/XML/TXT/manifest,
        niega los archivos de desarrollo/datos internos y responde con 404.html cuando el archivo no existe."""
        if DEV_FILES_RE.search(urlparse(self.path).path):
            return self._not_found()
        fs_path = Path(self.translate_path(self.path))
        if fs_path.is_dir() and urlparse(self.path).path.startswith("/app/legal/"):
            return self._not_found()  # sin listado de directorios en el centro legal (js/, plantillas/)
        if fs_path.is_dir():
            return super().do_GET() if self.command == "GET" else super().do_HEAD()
        if not fs_path.is_file():
            return self._not_found()
        content_type = TEXT_TYPES.get(fs_path.suffix.lower())
        if not content_type:
            return super().do_GET() if self.command == "GET" else super().do_HEAD()
        return self._send_bytes(200, content_type, fs_path.read_bytes().replace(SITE_URL_TOKEN, self._site_url()))

    def _site_url(self) -> bytes:
        return f"http://localhost:{PORT}".encode()

    def _dispatch(self, static_ok: bool):
        path = urlparse(self.path).path
        if path == "/app":
            return self._redirect("/app/")
        if path == "/admin":
            return self._redirect("/admin/")
        legal = legal_redirect(path)
        if legal:
            return self._redirect(legal)
        if is_backend_path(path):
            return self._proxy_to_backend()
        if static_ok:
            return self._serve_static()
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._dispatch(True)

    def do_HEAD(self):
        self._dispatch(True)

    def do_POST(self):
        self._dispatch(False)

    def do_PATCH(self):
        self._dispatch(False)

    def do_PUT(self):
        self._dispatch(False)

    def do_DELETE(self):
        self._dispatch(False)

    def do_OPTIONS(self):
        self._dispatch(False)


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    with ThreadingServer(("", PORT), Handler) as httpd:
        print(f"Sirviendo GuauWoow en http://localhost:{PORT}")
        print(f"Landing: http://localhost:{PORT}/")
        print(f"App:     http://localhost:{PORT}/app/")
        print(f"Admin:   http://localhost:{PORT}/admin/")
        print(f"Backend: http://{BACKEND_HOST}:{BACKEND_PORT}")
        httpd.serve_forever()
