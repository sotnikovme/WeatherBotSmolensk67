"""Application settings loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# City coordinates for the Smolensk region (lat, lon)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class City:
    name: str
    lat: float
    lon: float


SMOLENSK_CITIES: tuple[City, ...] = (
    City("\u0421\u043c\u043e\u043b\u0435\u043d\u0441\u043a", 54.7818, 32.0401),
    City("\u0412\u044f\u0437\u044c\u043c\u0430", 55.2103, 34.2850),
    City("\u0420\u043e\u0441\u043b\u0430\u0432\u043b\u044c", 53.9528, 32.8639),
    City("\u042f\u0440\u0446\u0435\u0432\u043e", 55.0593, 32.6850),
    City("\u0421\u0430\u0444\u043e\u043d\u043e\u0432\u043e", 55.1225, 33.2247),
    City("\u0413\u0430\u0433\u0430\u0440\u0438\u043d", 55.5500, 34.9833),
    City("\u0414\u0435\u0441\u043d\u043e\u0433\u043e\u0440\u0441\u043a", 54.1508, 33.2815),
    City("\u041f\u043e\u0447\u0438\u043d\u043e\u043a", 54.4100, 32.4500),
    City("\u0414\u043e\u0440\u043e\u0433\u043e\u0431\u0443\u0436", 54.9150, 33.2972),
    City("\u0415\u043b\u044c\u043d\u044f", 54.5791, 33.1787),
    City("\u0420\u0443\u0434\u043d\u044f", 54.9500, 31.0833),
    City("\u0412\u0435\u043b\u0438\u0436", 55.6000, 31.2000),
    City("\u0414\u0435\u043c\u0438\u0434\u043e\u0432", 55.2645, 31.5178),
    City("\u0414\u0443\u0445\u043e\u0432\u0449\u0438\u043d\u0430", 55.1910, 32.4070),
    City("\u0421\u044b\u0447\u0451\u0432\u043a\u0430", 55.8300, 34.2770),
    City("\u0428\u0443\u043c\u044f\u0447\u0438", 53.85833, 32.424171),
    City("\u0412\u0435\u0440\u0445\u043d\u0435\u0434\u043d\u0435\u043f\u0440\u043e\u0432\u0441\u043a\u0438\u0439", 54.981312, 33.34573),
    City("\u041a\u0430\u0440\u0434\u044b\u043c\u043e\u0432\u043e", 54.89016, 32.43111),
)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Bot configuration. Values are read from `.env` file or env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str

    # GigaChat
    gigachat_credentials: str
    gigachat_model: str = "GigaChat"
    gigachat_scope: str = "GIGACHAT_API_PERS"

    # OpenWeatherMap
    owm_api_key: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/weatherbot"

    # Scheduler
    morning_post_hour: int = 8
    morning_post_minute: int = 0
    alert_check_interval_minutes: int = 15

    # Thresholds
    wind_alert_threshold: float = 15.0   # m/s
    temp_alert_threshold: float = -25.0  # C

    # Cache
    cache_ttl_seconds: int = 3 * 3600  # 3 hours


settings = Settings()  # type: ignore[call-arg]
