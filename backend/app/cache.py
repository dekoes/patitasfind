"""Caché opcional con Redis. Si REDIS_URL no está configurada, funciona como no-op."""
import json
import hashlib
from functools import wraps

from app.config import settings

_redis = None


def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    if not settings.redis_url:
        return None
    try:
        import redis
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
        _redis.ping()
        return _redis
    except Exception:
        _redis = None
        return None


def get(key: str):
    r = _get_redis()
    if not r:
        return None
    value = r.get(key)
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


def delete(key: str):
    r = _get_redis()
    if not r:
        return
    try:
        r.delete(key)
    except Exception:
        pass


def _cache_key(prefix: str, *args, **kwargs):
    payload = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    return f"{prefix}:{hashlib.sha256(payload.encode()).hexdigest()}"


def cached(prefix: str, ttl: int | None = None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = _cache_key(prefix, *args, **kwargs)
            cached_value = get(key)
            if cached_value is not None:
                return cached_value
            result = func(*args, **kwargs)
            set(key, result, ttl)
            return result
        return wrapper
    return decorator
