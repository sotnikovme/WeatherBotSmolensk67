"""OpenWeatherMap forecast client for the Smolensk region."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any

import aiohttp

from src.config import City, Settings, SMOLENSK_CITIES, settings

logger = logging.getLogger(__name__)

OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
DETAILED_PERIODS: tuple[tuple[str, str, str], ...] = (
    ("night_00_03", "Ночь (00-03)", "00:00:00"),
    ("night_03_06", "Ночь (03-06)", "03:00:00"),
    ("morning_06_09", "Утро (06-09)", "06:00:00"),
    ("morning_09_12", "Утро (09-12)", "09:00:00"),
    ("day_12_15", "День (12-15)", "12:00:00"),
    ("day_15_18", "День (15-18)", "15:00:00"),
    ("evening_18_21", "Вечер (18-21)", "18:00:00"),
    ("evening_21_24", "Вечер (21-24)", "21:00:00"),
)
SUMMARY_PERIODS: tuple[tuple[str, str, tuple[str, str]], ...] = (
    ("night", "Ночь", ("night_00_03", "night_03_06")),
    ("morning", "Утро", ("morning_06_09", "morning_09_12")),
    ("day", "День", ("day_12_15", "day_15_18")),
    ("evening", "Вечер", ("evening_18_21", "evening_21_24")),
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
        """Return current local-day forecast with detailed and summary periods."""
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
        """Fetch current local-day forecast for every city in the region."""
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
        """Extract detailed/summarized forecast data from OWM response."""
        items = raw.get("list", [])
        if not items:
            raise ValueError(f"Empty forecast response for {city.name}")

        target_date = WeatherService._resolve_target_date(raw, items)
        target_date_str = target_date.isoformat()

        day_items = [item for item in items if item.get("dt_txt", "").startswith(target_date_str)]
        if not day_items:
            raise ValueError(f"No forecast data for {city.name} on {target_date_str}")

        hourly_forecast = [WeatherService._parse_item(item) for item in day_items]
        detailed_periods = WeatherService._build_detailed_periods(day_items)
        summary_periods = WeatherService._build_summary_periods(detailed_periods)

        period_values = list(summary_periods.values())
        description = next(
            (
                summary_periods[name]["description"]
                for name, _, _ in SUMMARY_PERIODS
                if summary_periods[name]["description"]
            ),
            "",
        )

        daily_forecast = WeatherService._build_multi_day_forecast(items, target_date)
        pressure_values = [period["pressure_mm"] for period in detailed_periods.values()]
        wind_dirs = [
            period["wind_dir"]
            for period in detailed_periods.values()
            if period.get("wind_dir")
        ]

        return {
            "city": city.name,
            "forecast_date": target_date_str,
            "description": description,
            "temp_min": min(item["temp_min"] for item in period_values),
            "temp_max": max(item["temp_max"] for item in period_values),
            "humidity": max(item["humidity"] for item in period_values),
            "pressure": round(mean(item["pressure"] for item in period_values)),
            "pressure_mm_min": min(pressure_values),
            "pressure_mm_max": max(pressure_values),
            "pressure_mm_trend": ">".join(str(value) for value in pressure_values),
            "wind_speed": max(item["wind_speed"] for item in period_values),
            "wind_gust": max(item["wind_gust"] for item in period_values),
            "wind_direction_text": WeatherService._join_wind_directions(wind_dirs),
            "hourly_forecast": hourly_forecast,
            "periods": summary_periods,
            "detailed_periods": detailed_periods,
            "multi_day": daily_forecast,
        }

    @staticmethod
    def _resolve_target_date(raw: dict[str, Any], items: list[dict[str, Any]]) -> date:
        """Pick the forecast date for the city's current local day.

        OWM returns forecast items in 3-hour steps starting from the next available slot.
        When there are no remaining slots for the current local day, fall back to the
        first available forecast date instead of incorrectly shifting to "tomorrow".
        """
        city_info = raw.get("city", {})
        timezone_offset = int(city_info.get("timezone", 0))
        local_now = datetime.now(timezone.utc) + timedelta(seconds=timezone_offset)
        today_local = local_now.date()

        available_dates = sorted(
            {
                datetime.strptime(item["dt_txt"], "%Y-%m-%d %H:%M:%S").date()
                for item in items
                if item.get("dt_txt")
            }
        )
        if not available_dates:
            raise ValueError("Forecast payload does not contain valid dt_txt values")

        if today_local in available_dates:
            return today_local

        return available_dates[0]

    @staticmethod
    def _build_detailed_periods(day_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        detailed_periods: dict[str, dict[str, Any]] = {}

        for key, label, target_time in DETAILED_PERIODS:
            chosen_item = min(
                day_items,
                key=lambda item: abs(
                    WeatherService._time_distance_seconds(
                        item["dt_txt"].split(" ")[1],
                        target_time,
                    )
                ),
            )
            parsed = WeatherService._parse_item(chosen_item)
            parsed["label"] = label
            detailed_periods[key] = parsed

        return detailed_periods

    @staticmethod
    def _build_summary_periods(
        detailed_periods: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        summary_periods: dict[str, dict[str, Any]] = {}

        for key, label, members in SUMMARY_PERIODS:
            slots = [detailed_periods[member] for member in members]
            descriptions = [slot["description"] for slot in slots if slot.get("description")]
            wind_dirs = [slot["wind_dir"] for slot in slots if slot.get("wind_dir")]

            summary_periods[key] = {
                "label": label,
                "temp_min": min(slot["temperature"] for slot in slots),
                "temp_max": max(slot["temperature"] for slot in slots),
                "temperature": round(mean(slot["temperature"] for slot in slots)),
                "feels_like": round(mean(slot["feels_like"] for slot in slots)),
                "pressure": round(mean(slot["pressure"] for slot in slots)),
                "pressure_mm": round(mean(slot["pressure_mm"] for slot in slots)),
                "humidity": max(slot["humidity"] for slot in slots),
                "description": WeatherService._pick_description(descriptions),
                "weather": WeatherService._pick_description(
                    [slot["weather"] for slot in slots if slot.get("weather")]
                ),
                "clouds": round(mean(slot["clouds"] for slot in slots)),
                "wind_speed": max(slot["wind_speed"] for slot in slots),
                "wind_gust": max(slot["wind_gust"] for slot in slots),
                "wind_dir": WeatherService._join_wind_directions(wind_dirs),
                "rain": round(sum(slot["rain"] for slot in slots), 1),
            }

        return summary_periods

    @staticmethod
    def _build_multi_day_forecast(
        items: list[dict[str, Any]],
        start_date: date,
        days: int = 5,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            date_str = item.get("dt_txt", "").split(" ")[0]
            if date_str:
                grouped.setdefault(date_str, []).append(item)

        result: list[dict[str, Any]] = []
        for offset in range(days):
            date_value = start_date + timedelta(days=offset)
            date_str = date_value.isoformat()
            day_items = grouped.get(date_str)
            if not day_items:
                continue

            parsed_items = [WeatherService._parse_item(item) for item in day_items]
            descriptions = [item["description"] for item in parsed_items if item.get("description")]
            result.append(
                {
                    "date": date_str,
                    "temp_min": min(item["temperature"] for item in parsed_items),
                    "temp_max": max(item["temperature"] for item in parsed_items),
                    "description": WeatherService._pick_description(descriptions),
                }
            )

        return result

    @staticmethod
    def _parse_item(item: dict[str, Any]) -> dict[str, Any]:
        main = item.get("main", {})
        wind = item.get("wind", {})
        weather = item.get("weather", [{}])[0]
        pressure_hpa = main.get("pressure", 0)

        return {
            "time": item.get("dt_txt", ""),
            "temperature": round(main.get("temp", 0)),
            "feels_like": round(main.get("feels_like", 0)),
            "pressure": pressure_hpa,
            "pressure_mm": WeatherService._hpa_to_mmhg(pressure_hpa),
            "humidity": main.get("humidity", 0),
            "weather": weather.get("main", ""),
            "description": weather.get("description", ""),
            "clouds": item.get("clouds", {}).get("all", 0),
            "wind_speed": round(wind.get("speed", 0)),
            "wind_gust": round(wind.get("gust", 0)),
            "wind_deg": wind.get("deg"),
            "wind_dir": WeatherService._deg_to_direction(wind.get("deg")),
            "rain": round(item.get("rain", {}).get("3h", 0), 1),
        }

    @staticmethod
    def _pick_description(descriptions: list[str]) -> str:
        if not descriptions:
            return ""

        priority = (
            "гроза",
            "лив",
            "сильн",
            "дожд",
            "снег",
            "туман",
            "дымк",
            "мгла",
            "пасмур",
            "облач",
            "ясно",
        )
        lowered = [description.lower() for description in descriptions]
        for token in priority:
            for index, description in enumerate(lowered):
                if token in description:
                    return descriptions[index]
        return descriptions[0]

    @staticmethod
    def _join_wind_directions(directions: list[str]) -> str:
        ordered_unique: list[str] = []
        for direction in directions:
            if direction and direction not in ordered_unique:
                ordered_unique.append(direction)
        return " и ".join(ordered_unique)

    @staticmethod
    def _deg_to_direction(deg: float | None) -> str:
        if deg is None:
            return ""

        directions = (
            "С",
            "ССВ",
            "СВ",
            "ВСВ",
            "В",
            "ВЮВ",
            "ЮВ",
            "ЮЮВ",
            "Ю",
            "ЮЮЗ",
            "ЮЗ",
            "ЗЮЗ",
            "З",
            "ЗСЗ",
            "СЗ",
            "ССЗ",
        )
        index = round(deg / 22.5) % len(directions)
        return directions[index]

    @staticmethod
    def _hpa_to_mmhg(value: float | int) -> int:
        return round(float(value) * 0.75006156)

    @staticmethod
    def _time_distance_seconds(actual_time: str, target_time: str) -> int:
        actual = datetime.strptime(actual_time, "%H:%M:%S")
        target = datetime.strptime(target_time, "%H:%M:%S")
        return int((actual - target).total_seconds())
