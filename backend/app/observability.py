"""Observabilidad: Sentry (opcional), request id y logs estructurados de cada petición.

Todo es no-op si SENTRY_DSN no está definido.
"""
import contextvars
import json
import logging
import re
import time
import uuid

from app.config import settings

logger = logging.getLogger("patitasfind.request")
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
_SENSITIVE_KEYS = ("authorization", "cookie", "set-cookie", "password", "token", "secret", "phone", "email",
                   "apikey", "api_key", "contact_phone", "x-api-key", "code")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-]{8,}\d")
_sentry_ready = False


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging() -> None:
    root = logging.getLogger()
    if not getattr(root, "_patitasfind_configured", False):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] [%(request_id)s] %(message)s")
        for handler in root.handlers:
            handler.addFilter(RequestIdFilter())
        root._patitasfind_configured = True  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- Sentry
def _scrub(value, depth: int = 0):
    if depth > 8:
        return value
    if isinstance(value, dict):
        return {k: ("[Filtrado]" if any(s in str(k).lower() for s in _SENSITIVE_KEYS) else _scrub(v, depth + 1))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, depth + 1) for v in value]
    if isinstance(value, str):
        return _PHONE_RE.sub("[tel]", _EMAIL_RE.sub("[correo]", value))
    return value


def _before_send(event, hint):  # noqa: ARG001
    try:
        request = event.get("request") or {}
        for key in ("headers", "cookies", "data", "query_string", "env"):
            if key in request:
                request[key] = _scrub(request[key]) if key != "cookies" else "[Filtrado]"
        if "user" in event:
            event["user"] = {"id": (event.get("user") or {}).get("id")}
        for key in ("extra", "contexts", "breadcrumbs"):
            if key in event:
                event[key] = _scrub(event[key])
        if "logentry" in event:
            event["logentry"] = _scrub(event["logentry"])
        for exc in (event.get("exception") or {}).get("values", []) or []:
            if isinstance(exc.get("value"), str):
                exc["value"] = _scrub(exc["value"])
    except Exception:  # noqa: BLE001 - nunca romper el envío por el filtro
        pass
    return event


def init_sentry(component: str = "backend") -> bool:
    global _sentry_ready
    if _sentry_ready or not settings.sentry_dsn:
        return _sentry_ready
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logging.getLogger(__name__).warning("SENTRY_DSN definido pero sentry-sdk no está instalado.")
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment or settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        before_send=_before_send,
        integrations=[StarletteIntegration(), FastApiIntegration(), CeleryIntegration()],
    )
    sentry_sdk.set_tag("component", component)
    _sentry_ready = True
    return True


# --------------------------------------------------------------------------- middleware ASGI
class RequestContextMiddleware:
    """Asigna X-Request-ID (respeta el del cliente si es válido) y registra una línea JSON por petición."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        if _sentry_ready:
            try:
                import sentry_sdk

                sentry_sdk.get_isolation_scope().set_tag("request_id", rid)
            except Exception:  # noqa: BLE001
                pass
        if scope["type"] == "websocket":
            try:
                return await self.app(scope, receive, send)
            finally:
                request_id_var.reset(token)

        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            entry = {
                "event": "request",
                "request_id": rid,
                "method": scope.get("method"),
                "path": path,
                "status": status_holder["status"],
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            }
            level = logging.DEBUG if path == "/health" else (logging.WARNING if status_holder["status"] >= 500 else logging.INFO)
            logger.log(level, json.dumps(entry, ensure_ascii=False))
            request_id_var.reset(token)
