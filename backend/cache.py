import json
import time
from typing import Any

from fastapi import FastAPI

from backend.settings import settings


class SimpleCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[dict[str, Any], float | None]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        item = self._data.get(key)
        if not item:
            return None
        value, expires_at = item
        if expires_at is not None and time.time() > expires_at:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else None
        self._data[key] = (value, expires_at)


async def _cache_get(app: FastAPI, key: str) -> dict[str, Any] | None:
    if not settings.use_cache:
        return None
    redis_client = getattr(app.state, "redis", None)
    if redis_client is not None:
        try:
            raw = await redis_client.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return None
    if getattr(app.state, "local_cache", None) is not None:
        return app.state.local_cache.get(key)
    return None


async def _cache_set(app: FastAPI, key: str, value: dict[str, Any]) -> None:
    if not settings.use_cache:
        return
    ttl = settings.cache_ttl_seconds
    redis_client = getattr(app.state, "redis", None)
    if redis_client is not None:
        try:
            await redis_client.set(key, json.dumps(value), ex=ttl)
        except Exception:
            pass
        return
    if getattr(app.state, "local_cache", None) is not None:
        app.state.local_cache.set(key, value, ttl)
