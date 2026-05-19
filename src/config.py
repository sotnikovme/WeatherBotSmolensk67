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
    City("Смоленск",    54.7818,  32.0401),
    City("Вязьма",      55.2103,  34.2850),
    City("Рославль",    53.9528,  32.8639),
    City("Ярцево",      55.0593,  32.6850),
    City("Сафоново",    55.1225,  33.2247),
    City("Гагарин",     55.5500,  34.9833),
    City("Десногорск",   54.1508,  33.2815),
    City("Починок",     54.4100,  32.4500),
    City("Дорогобуж",   54.9150,  33.2972),
    City("Ельня",       54.5791,  33.1787),
    City("Рудня",       54.9500,  31.0833),
    City("Велиж",       55.6000,  31.2000),
    City("Демидов",     55.2645,  31.5178),
    City("Духовщина",   55.1910,  32.4070),
    City("Сычёвка",     55.8300,  34.2770),
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
    temp_alert_threshold: float = -25.0  # °C

    # Cache
    cache_ttl_seconds: int = 3 * 3600  # 3 hours


settings = Settings()  # type: ignore[call-arg]
