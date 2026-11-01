"""Rate limit simple por clave (IP, usuario...). Usa Redis si está configurado; si no, memoria del proceso.

Si REDIS_URL está configurada pero Redis no responde, se sigue limitando con la memoria del proceso
(cada worker lleva su propia cuenta) y se registra un aviso como máximo una vez por minuto.
"""
import logging
import threading
import time

from fastapi import HTTPException, status

from app import cache
from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_DETAIL = "Hiciste demasiadas búsquedas seguidas. Espera un minuto e inténtalo de nuevo."
_WARN_EVERY_SECONDS = 60
_MAX_KEYS = 20_000  # tope de claves en memoria; al rebasarlo se purgan las vencidas

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}
_expires: dict[str, float] = {}
_last_warning = 0.0


def _warn_fallback(reason: str) -> None:
    global _last_warning
    now = time.monotonic()
    with _lock:
        if now - _last_warning < _WARN_EVERY_SECONDS:
            return
        _last_warning = now
    logger.warning(
        "Redis no disponible para el límite de solicitudes (%s): se usa la memoria de este proceso "
        "y el límite no se comparte entre workers.", reason,
    )


def _redis_hit(r, key: str, limit: int, window_seconds: int, cost: int) -> bool:
    bucket = f"rl:{key}:{int(time.time() // window_seconds)}"
    pipe = r.pipeline(transaction=False)
    pipe.incrby(bucket, cost)
    pipe.expire(bucket, window_seconds)
    count = int(pipe.execute()[0])
    if count > limit:
        r.decrby(bucket, cost)  # lo rechazado no cuenta
        return False
    return True


def _memory_hit(key: str, limit: int, window_seconds: int, cost: int) -> bool:
    now = time.time()
    with _lock:
        if len(_hits) > _MAX_KEYS:
            for k in [k for k, exp in _expires.items() if exp < now]:
                _hits.pop(k, None)
                _expires.pop(k, None)
        hits = [t for t in _hits.get(key, []) if now - t < window_seconds]
        if len(hits) + cost > limit:
            _hits[key] = hits
            return False
        hits.extend([now] * cost)
        _hits[key] = hits
        _expires[key] = now + window_seconds
        return True


def hit(key: str, limit: int, window_seconds: int, cost: int = 1) -> bool:
    """Cuenta `cost` usos de `key`. True si caben en `limit` por `window_seconds`; False (sin contarlos) si no."""
    r = cache._get_redis()
    if r is not None:
        try:
            return _redis_hit(r, key, limit, window_seconds, cost)
        except Exception as exc:  # noqa: BLE001
            _warn_fallback(exc.__class__.__name__)
    elif settings.redis_url:
        _warn_fallback("sin conexión")
    return _memory_hit(key, limit, window_seconds, cost)


def check(key: str, limit: int, window_seconds: int, detail: str | None = None, cost: int = 1) -> None:
    """Lanza 429 con `detail` (en español) si `key` rebasa `limit` usos en `window_seconds`."""
    if not hit(key, limit, window_seconds, cost):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail or DEFAULT_DETAIL,
            headers={"Retry-After": str(window_seconds - int(time.time()) % window_seconds)},
        )
