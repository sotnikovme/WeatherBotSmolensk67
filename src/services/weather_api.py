"""OpenWeatherMap API client for the Smolensk region."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.config import City, Settings, SMOLENSK_CITIES, settings

logger = logging.getLogger(__name__)

OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/weather"


class WeatherService:
    """Fetches current weather data from OpenWeatherMap."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self._cfg = cfg or settings
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_current(self, city: City) -> dict[str, Any]:
        """Return current weather dict for a single city."""
        assert self._session is not None, "Call start() first"

        params = {
            "lat": city.lat,
            "lon": city.lon,
            "appid": self._cfg.owm_api_key,
            "units": "metric",
            "lang": "ru",
        }

        async with self._session.get(OWM_FORECAST_URL, params=params) as resp:
            resp.raise_for_status()
            data: dict[str, Any] = await resp.json()

        return self._parse(city, data)

    async def get_all(self) -> list[dict[str, Any]]:
        """Fetch current weather for every city in the region."""
        results: list[dict[str, Any]] = []
        for city in SMOLENSK_CITIES:
            try:
                result = await self.get_current(city)
                results.append(result)
            except Exception:
                logger.exception("Failed to fetch weather for %s", city.name)
        return results

    async def check_alerts(self) -> list[dict[str, Any]]:
        """Return list of cities with extreme weather conditions."""
        alerts: list[dict[str, Any]] = []
        all_weather = await self.get_all()

        for w in all_weather:
            reasons: list[str] = []
            if w["wind_speed"] > self._cfg.wind_alert_threshold:
                reasons.append(f"ветер {w['wind_speed']} м/с")
            if w["temp"] < self._cfg.temp_alert_threshold:
                reasons.append(f"температура {w['temp']}°C")
            if reasons:
                alerts.append({**w, "alert_reasons": reasons})

        return alerts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse(city: City, raw: dict[str, Any]) -> dict[str, Any]:
        """Extract useful fields from raw OWM response."""
        main = raw.get("main", {})
        wind = raw.get("wind", {})
        weather_desc = ""
        if raw.get("weather"):
            weather_desc = raw["weather"][0].get("description", "")

        print({
            "city": city.name,
            "temp": main.get("temp", 0),
            "feels_like": main.get("feels_like", 0),
            "pressure": main.get("pressure", 0),
            "humidity": main.get("humidity", 0),
            "wind_speed": wind.get("speed", 0),
            "wind_gust": wind.get("gust", 0),
            "description": weather_desc,
        })
        
        return {
            "city": city.name,
            "temp": main.get("temp", 0),
            "feels_like": main.get("feels_like", 0),
            "pressure": main.get("pressure", 0),
            "humidity": main.get("humidity", 0),
            "wind_speed": wind.get("speed", 0),
            "wind_gust": wind.get("gust", 0),
            "description": weather_desc,
        }
