"""Rate limit simple por clave (IP). Usa Redis si está configurado; si no, memoria del proceso."""
import threading
import time

from fastapi import HTTPException, status

from app import cache

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def check(key: str, limit: int, window_seconds: int) -> None:
    r = cache._get_redis()
    if r is not None:
        try:
            bucket = f"rl:{key}:{int(time.time() // window_seconds)}"
            count = r.incr(bucket)
            if count == 1:
                r.expire(bucket, window_seconds)
            if count > limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Hiciste demasiadas búsquedas seguidas. Espera un minuto e inténtalo de nuevo.",
                )
            return
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            pass
    now = time.time()
    with _lock:
        hits = [t for t in _hits.get(key, []) if now - t < window_seconds]
        if len(hits) >= limit:
            _hits[key] = hits
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Hiciste demasiadas búsquedas seguidas. Espera un minuto e inténtalo de nuevo.",
            )
        hits.append(now)
        _hits[key] = hits
