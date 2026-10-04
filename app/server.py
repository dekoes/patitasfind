"""Servidor local de desarrollo para el frontend de PatitasFind (puerto 8082).

- Sirve la landing en /, la app en /app/ y el panel en /admin/.
- Reenvía al backend (localhost:8001) todas las rutas de la API, incluidas subidas
  multipart, y hace túnel de WebSockets (/ws/...) para el chat en tiempo real.

Uso:  python3 server.py   (y opcionalmente: cloudflared tunnel --url http://localhost:8082)
"""
import http.client
import http.server
import os
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
    "/lost-reports", "/foster-homes", "/reminders",
    "/whatsapp/", "/facebook/", "/search/", "/ai/", "/payments/",
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

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "host", "content-length"}


def is_backend_path(path: str) -> bool:
    if path.startswith("/admin/") and path not in ADMIN_STATIC:
        return True
    return path.startswith(PROXIED_PREFIXES)


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

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
        if path.startswith("/app/"):
            return super().translate_path(path[4:])
        return super().translate_path(path)

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _dispatch(self, static_ok: bool):
        path = urlparse(self.path).path
        if path == "/app":
            return self._redirect("/app/")
        if path == "/admin":
            return self._redirect("/admin/")
        if is_backend_path(path):
            return self._proxy_to_backend()
        if static_ok:
            return super().do_GET() if self.command == "GET" else super().do_HEAD()
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
        print(f"Sirviendo PatitasFind en http://localhost:{PORT}")
        print(f"Landing: http://localhost:{PORT}/")
        print(f"App:     http://localhost:{PORT}/app/")
        print(f"Admin:   http://localhost:{PORT}/admin/")
        print(f"Backend: http://{BACKEND_HOST}:{BACKEND_PORT}")
        httpd.serve_forever()
