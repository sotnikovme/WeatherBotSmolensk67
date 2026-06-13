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
DETAILED_TARGET_TIMES: tuple[str, ...] = tuple(
    target_time for _, _, target_time in DETAILED_PERIODS
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

        local_now = WeatherService._resolve_local_now(raw)
        target_date = WeatherService._resolve_target_date(raw, items)
        target_date_str = target_date.isoformat()

        day_items = [item for item in items if item.get("dt_txt", "").startswith(target_date_str)]
        if not day_items:
            raise ValueError(f"No forecast data for {city.name} on {target_date_str}")

        hourly_forecast = [WeatherService._parse_item(item) for item in day_items]
        detailed_periods = WeatherService._build_detailed_periods(
            items,
            target_date,
            local_now,
        )
        summary_periods = WeatherService._build_summary_periods(detailed_periods)

        period_values = [
            item for item in summary_periods.values() if item.get("temp_min") is not None
        ]
        if not period_values:
            raise ValueError(f"No usable forecast periods for {city.name} on {target_date_str}")
        description = next(
            (
                summary_periods[name]["description"]
                for name, _, _ in SUMMARY_PERIODS
                if summary_periods[name]["description"] and summary_periods[name]["description"] != "нет данных"
            ),
            "",
        )

        daily_forecast = WeatherService._build_multi_day_forecast(items, target_date)
        pressure_values = [
            period["pressure_mm"]
            for period in detailed_periods.values()
            if period.get("pressure_mm") is not None
        ]
        wind_dirs = [
            period["wind_dir"]
            for period in detailed_periods.values()
            if period.get("wind_dir")
        ]

        return {
            "city": city.name,
            "forecast_date": target_date_str,
            "local_now": local_now.strftime("%Y-%m-%d %H:%M:%S"),
            "forecast_scope": (
                "remaining_day" if target_date == local_now.date() else "full_day"
            ),
            "description": description,
            "temp_min": min(item["temp_min"] for item in period_values),
            "temp_max": max(item["temp_max"] for item in period_values),
            "humidity": max(item["humidity"] for item in period_values),
            "pressure": round(mean(item["pressure"] for item in period_values)),
            "pressure_mm_min": min(pressure_values) if pressure_values else None,
            "pressure_mm_max": max(pressure_values) if pressure_values else None,
            "pressure_mm_trend": ">".join(str(value) for value in pressure_values) if pressure_values else "нет данных",
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
        """Pick today's local date only when it still has active forecast periods."""
        local_now = WeatherService._resolve_local_now(raw)
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

        if today_local in available_dates and WeatherService._has_remaining_periods(
            items,
            today_local,
            local_now,
        ):
            return today_local

        future_dates = [current_date for current_date in available_dates if current_date > today_local]
        if future_dates:
            return future_dates[0]

        return available_dates[-1]

    @staticmethod
    def _resolve_local_now(raw: dict[str, Any]) -> datetime:
        """Return the city's current local time as a naive datetime."""
        city_info = raw.get("city", {})
        timezone_offset = int(city_info.get("timezone", 0))
        utc_now = datetime.now(timezone.utc)
        local_now = utc_now + timedelta(seconds=timezone_offset)
        return local_now.replace(tzinfo=None)

    @staticmethod
    def _has_remaining_periods(
        items: list[dict[str, Any]],
        target_date: date,
        local_now: datetime,
    ) -> bool:
        items_by_datetime = {
            item["dt_txt"]: item
            for item in items
            if item.get("dt_txt")
        }

        for _, _, target_time in DETAILED_PERIODS:
            start_dt = datetime.strptime(
                f"{target_date.isoformat()} {target_time}",
                "%Y-%m-%d %H:%M:%S",
            )
            end_dt = start_dt + timedelta(hours=3)
            if end_dt <= local_now:
                continue

            start_key = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            if start_key in items_by_datetime:
                return True

        return False

    @staticmethod
    def _build_detailed_periods(
        items: list[dict[str, Any]],
        target_date: date,
        local_now: datetime,
    ) -> dict[str, dict[str, Any]]:
        detailed_periods: dict[str, dict[str, Any]] = {}
        items_by_datetime = {
            item["dt_txt"]: item
            for item in items
            if item.get("dt_txt")
        }

        for key, label, target_time in DETAILED_PERIODS:
            start_dt = datetime.strptime(
                f"{target_date.isoformat()} {target_time}",
                "%Y-%m-%d %H:%M:%S",
            )
            end_dt = start_dt + timedelta(hours=3)
            if target_date == local_now.date() and end_dt <= local_now:
                continue

            start_key = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            end_key = end_dt.strftime("%Y-%m-%d %H:%M:%S")

            chosen_item = items_by_datetime.get(start_key)
            if chosen_item is None:
                continue

            parsed = WeatherService._parse_item(chosen_item)
            boundary_temperatures = [
                parsed["temperature"],
                parsed["temp_min"],
                parsed["temp_max"],
            ]
            end_item = items_by_datetime.get(end_key)
            if end_item is not None:
                end_parsed = WeatherService._parse_item(end_item)
                boundary_temperatures.extend(
                    [
                        end_parsed["temperature"],
                        end_parsed["temp_min"],
                        end_parsed["temp_max"],
                    ]
                )

            parsed["temp_min"] = min(boundary_temperatures)
            parsed["temp_max"] = max(boundary_temperatures)
            parsed["label"] = label
            detailed_periods[key] = parsed

        return detailed_periods

    @staticmethod
    def _build_summary_periods(
        detailed_periods: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        summary_periods: dict[str, dict[str, Any]] = {}

        for key, label, members in SUMMARY_PERIODS:
            slots = [
                detailed_periods[member]
                for member in members
                if detailed_periods.get(member) and detailed_periods[member].get("temperature") is not None
            ]
            if not slots:
                summary_periods[key] = WeatherService._empty_period(label)
                continue
            descriptions = [slot["description"] for slot in slots if slot.get("description")]
            wind_dirs = [slot["wind_dir"] for slot in slots if slot.get("wind_dir")]

            summary_periods[key] = {
                "label": label,
                "temp_min": min(slot["temp_min"] for slot in slots),
                "temp_max": max(slot["temp_max"] for slot in slots),
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
            "temperature": float(main.get("temp", 0)),
            "temp_min": float(main.get("temp_min", main.get("temp", 0))),
            "temp_max": float(main.get("temp_max", main.get("temp", 0))),
            "feels_like": float(main.get("feels_like", 0)),
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
    def _empty_period(label: str) -> dict[str, Any]:
        return {
            "label": label,
            "time": "",
            "temperature": None,
            "temp_min": None,
            "temp_max": None,
            "feels_like": None,
            "pressure": None,
            "pressure_mm": None,
            "humidity": None,
            "weather": "",
            "description": "нет данных",
            "clouds": None,
            "wind_speed": None,
            "wind_gust": None,
            "wind_deg": None,
            "wind_dir": "",
            "rain": 0,
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



