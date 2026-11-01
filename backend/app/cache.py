"""Caché opcional con Redis. Si REDIS_URL no está configurada (o Redis no responde), funciona como no-op."""
import builtins
import hashlib
import json
import logging
import time

from app.config import settings

logger = logging.getLogger(__name__)

_redis = None
_down_until = 0.0  # si Redis falló, no se reintenta conectar hasta esta hora (evita 1 s extra por petición)
RETRY_AFTER_SECONDS = 30


def _get_redis():
    global _redis, _down_until
    if _redis is not None:
        return _redis
    if not settings.redis_url or time.monotonic() < _down_until:
        return None
    try:
        import redis
        # Timeouts cortos: si Redis se cuelga, la petición sigue sin caché en vez de esperar
        client = redis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1,
            health_check_interval=30,
        )
        client.ping()
        _redis = client
        return _redis
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis no disponible (%s); sin caché por %s s.", exc, RETRY_AFTER_SECONDS)
        _redis = None
        _down_until = time.monotonic() + RETRY_AFTER_SECONDS
        return None


def get(key: str):
    r = _get_redis()
    if not r:
        return None
    try:
        value = r.get(key)
    except Exception:  # noqa: BLE001 - Redis caído o lento: se trata como "no está en caché"
        return None
    if value is None:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def set(key: str, value, ttl: int | None = None):
    r = _get_redis()
    if not r:
        return
    ttl = ttl or settings.cache_ttl_seconds
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


def delete(*keys: str):
    r = _get_redis()
    if not r or not keys:
        return
    try:
        r.delete(*keys)
    except Exception:
        pass


def add(key: str, ttl: int) -> bool:
    """SET NX: True si la clave no existía (sirve para no repetir trabajo). Sin Redis siempre True."""
    r = _get_redis()
    if not r:
        return True
    try:
        return bool(r.set(key, 1, ex=ttl, nx=True))
    except Exception:  # noqa: BLE001
        return True


# --------------------------------------------------------------------------- claves con versión
def version(namespace: str) -> int:
    """Versión actual de un grupo de claves (p. ej. "dogs"). Subirla invalida todo el grupo."""
    r = _get_redis()
    if not r:
        return 0
    try:
        return int(r.get(f"ver:{namespace}") or 0)
    except Exception:  # noqa: BLE001
        return 0


def bump(*namespaces: str):
    """Invalida los listados en caché de esos grupos (se llama al crear o cambiar contenido)."""
    r = _get_redis()
    if not r:
        return
    try:
        for ns in namespaces:
            r.incr(f"ver:{ns}")
    except Exception:  # noqa: BLE001
        pass


def make_key(namespace: str, **params) -> str:
    """Clave estable para `params` dentro de `namespace`, incluyendo su versión actual."""
    payload = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:32]
    return f"c:{namespace}:v{version(namespace)}:{digest}"


# --------------------------------------------------------------------------- invalidación automática
# Tablas con listados públicos en caché -> grupo de claves. Cualquier commit que cree, cambie o borre
# filas de estas tablas (endpoints, moderación, tareas de Celery...) sube la versión del grupo.
CACHED_TABLES = {"dogs": "dogs", "lost_reports": "lost_reports"}
IGNORED_COLUMNS = {"photo_signature"}  # no aparece en ningún listado (la usa el matching)


def _changed_columns(obj) -> "builtins.set[str]":
    from sqlalchemy import inspect

    state = inspect(obj)
    return {a.key for a in state.mapper.column_attrs if state.attrs[a.key].history.has_changes()}


def watch_sessions(session_factory):
    """Registra en `session_factory` (SessionLocal) la invalidación de cachés al hacer commit."""
    from sqlalchemy import event

    @event.listens_for(session_factory, "after_flush")
    def _collect(session, flush_context):
        # builtins.set: este módulo define su propia función set()
        bumps = session.info.setdefault("cache_bump", builtins.set())
        stale = session.info.setdefault("cache_delete", builtins.set())
        changed = [(o, True) for o in list(session.new) + list(session.deleted)]
        changed += [(o, False) for o in session.dirty]
        for obj, whole in changed:
            table = getattr(obj, "__tablename__", None)
            ns = CACHED_TABLES.get(table)
            if not ns or (not whole and not (_changed_columns(obj) - IGNORED_COLUMNS)):
                continue
            bumps.add(ns)
            if table == "lost_reports" and getattr(obj, "id", None):
                stale.add(f"lr-matches:{obj.id}")  # sus coincidencias en caché (ver services/matching.py)

    @event.listens_for(session_factory, "after_commit")
    def _apply(session):
        bumps = session.info.pop("cache_bump", None)
        stale = session.info.pop("cache_delete", None)
        if bumps:
            bump(*sorted(bumps))
        if stale:
            delete(*stale)

    @event.listens_for(session_factory, "after_rollback")
    def _discard(session):
        session.info.pop("cache_bump", None)
        session.info.pop("cache_delete", None)
