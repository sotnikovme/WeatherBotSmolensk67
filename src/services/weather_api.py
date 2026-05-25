"""OpenWeatherMap forecast client for the Smolensk region."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from src.config import City, Settings, SMOLENSK_CITIES, settings

logger = logging.getLogger(__name__)

OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
FORECAST_PERIODS: tuple[tuple[str, str], ...] = (
    ("night", "00:00:00"),
    ("morning", "09:00:00"),
    ("day", "15:00:00"),
    ("evening", "21:00:00"),
)


class WeatherService:
    """Fetches forecast data from OpenWeatherMap."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self._cfg = cfg or settings
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def get_forecast(self, city: City) -> dict[str, Any]:
        """Return next-day forecast split by parts of day."""
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

        return self._parse_forecast(city, data)

    async def get_current(self, city: City) -> dict[str, Any]:
        """Backward-compatible alias for the forecast payload."""
        return await self.get_forecast(city)

    async def get_all(self) -> list[dict[str, Any]]:
        """Fetch next-day forecast for every city in the region."""
        results: list[dict[str, Any]] = []
        for city in SMOLENSK_CITIES:
            try:
                results.append(await self.get_forecast(city))
            except Exception:
                logger.exception("Failed to fetch weather for %s", city.name)
        return results

    async def check_alerts(self) -> list[dict[str, Any]]:
        """Return cities with risky forecast conditions."""
        alerts: list[dict[str, Any]] = []
        all_weather = await self.get_all()

        for forecast in all_weather:
            reasons: list[str] = []
            if forecast["wind_speed"] > self._cfg.wind_alert_threshold:
                reasons.append(f"ветер до {forecast['wind_speed']} м/с")
            if forecast["temp_min"] < self._cfg.temp_alert_threshold:
                reasons.append(f"температура до {forecast['temp_min']}°C")
            if reasons:
                alerts.append({**forecast, "alert_reasons": reasons})

        return alerts

    @staticmethod
    def _parse_forecast(city: City, raw: dict[str, Any]) -> dict[str, Any]:
        """Extract period forecast and aggregate fields from OWM response."""
        items = raw.get("list", [])
        if not items:
            raise ValueError(f"Empty forecast response for {city.name}")

        first_dt = datetime.strptime(items[0]["dt_txt"], "%Y-%m-%d %H:%M:%S")
        target_date = first_dt.date() + timedelta(days=1)
        target_date_str = target_date.isoformat()
        target_times = {name: time_str for name, time_str in FORECAST_PERIODS}

        day_items = [item for item in items if item.get("dt_txt", "").startswith(target_date_str)]
        if not day_items:
            raise ValueError(f"No forecast data for {city.name} on {target_date_str}")

        periods: dict[str, dict[str, Any]] = {}
        for item in day_items:
            _, time_part = item["dt_txt"].split(" ")
            for period_name, target_time in target_times.items():
                if time_part == target_time:
                    periods[period_name] = WeatherService._parse_item(item)

        # If an exact slot is absent, use the nearest available time for that period.
        for period_name, target_time in FORECAST_PERIODS:
            if period_name not in periods:
                periods[period_name] = WeatherService._parse_item(
                    min(
                        day_items,
                        key=lambda item: abs(
                            WeatherService._time_distance_seconds(
                                item["dt_txt"].split(" ")[1],
                                target_time,
                            )
                        ),
                    )
                )

        ordered_periods = {
            period_name: periods[period_name]
            for period_name, _ in FORECAST_PERIODS
        }
        period_values = list(ordered_periods.values())
        description = next(
            (
                ordered_periods[name]["description"]
                for name in ("day", "morning", "evening", "night")
                if ordered_periods[name]["description"]
            ),
            "",
        )

        return {
            "city": city.name,
            "forecast_date": target_date_str,
            "description": description,
            "temp_min": min(item["temperature"] for item in period_values),
            "temp_max": max(item["temperature"] for item in period_values),
            "humidity": max(item["humidity"] for item in period_values),
            "pressure": round(sum(item["pressure"] for item in period_values) / len(period_values)),
            "wind_speed": max(item["wind_speed"] for item in period_values),
            "wind_gust": max(item["wind_gust"] for item in period_values),
            "periods": ordered_periods,
        }

    @staticmethod
    def _parse_item(item: dict[str, Any]) -> dict[str, Any]:
        main = item.get("main", {})
        wind = item.get("wind", {})
        weather = item.get("weather", [{}])[0]

        return {
            "time": item.get("dt_txt", ""),
            "temperature": main.get("temp", 0),
            "feels_like": main.get("feels_like", 0),
            "pressure": main.get("pressure", 0),
            "humidity": main.get("humidity", 0),
            "weather": weather.get("main", ""),
            "description": weather.get("description", ""),
            "clouds": item.get("clouds", {}).get("all", 0),
            "wind_speed": wind.get("speed", 0),
            "wind_gust": wind.get("gust", 0),
            "rain": item.get("rain", {}).get("3h", 0),
        }

    @staticmethod
    def _time_distance_seconds(actual_time: str, target_time: str) -> int:
        actual = datetime.strptime(actual_time, "%H:%M:%S")
        target = datetime.strptime(target_time, "%H:%M:%S")
        return int((actual - target).total_seconds())
