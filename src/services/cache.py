"""Redis caching layer for weather data and GigaChat responses."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from src.config import Settings, settings

logger = logging.getLogger(__name__)
POST_CACHE_VERSION = "v2"


def _hour_key() -> str:
    """Current UTC hour as string for cache key segmentation."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d%H")


class CacheService:
    """Thin async Redis wrapper with weather-specific helpers."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self._cfg = cfg or settings
        self._redis: aioredis.Redis | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._redis = aioredis.from_url(
            self._cfg.redis_url,
            decode_responses=True,
        )

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    # ------------------------------------------------------------------
    # Weather data cache
    # ------------------------------------------------------------------

    async def get_weather(self, city_name: str) -> dict[str, Any] | None:
        """Return cached weather data or None."""
        assert self._redis is not None
        key = f"weather:{city_name}:{_hour_key()}"
        raw = await self._redis.get(key)
        if raw:
            return json.loads(raw)
        return None

    async def set_weather(self, city_name: str, data: dict[str, Any]) -> None:
        """Store weather data in cache."""
        assert self._redis is not None
        key = f"weather:{city_name}:{_hour_key()}"
        await self._redis.set(key, json.dumps(data, ensure_ascii=False), ex=self._cfg.cache_ttl_seconds)

    # ------------------------------------------------------------------
    # GigaChat post cache
    # ------------------------------------------------------------------

    async def get_post(self, city_name: str) -> str | None:
        """Return cached GigaChat post or None."""
        assert self._redis is not None
        key = f"gigachat:{POST_CACHE_VERSION}:{city_name}:{_hour_key()}"
        return await self._redis.get(key)

    async def set_post(self, city_name: str, text: str) -> None:
        """Store GigaChat post in cache."""
        assert self._redis is not None
        key = f"gigachat:{POST_CACHE_VERSION}:{city_name}:{_hour_key()}"
        await self._redis.set(key, text, ex=self._cfg.cache_ttl_seconds)
