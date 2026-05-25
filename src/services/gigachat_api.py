"""GigaChat bridge for weather posts and alerts."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

from src.config import Settings, settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Твоя задача — превращать сухие цифры прогноза в захватывающие и информативные посты для telegram для жителей региона.\n\n"
    "Стиль текста:\n"
    "Заголовки: Всегда используй яркие метафоры (например, «СЕВЕРНЫЙ ТАНЕЦ ЦИКЛОНОВ», «ДЫХАНИЕ АРКТИКИ»).\n"
    "Тон: Сочетай строгость метеоролога (используй термины: фронт окклюзии, циклоническая депрессия, "
    "тыл циклона, инверсия, барическая гора) с уютом (эпитеты: колючий ветер, робкое солнце, чехарда погоды).\n\n"
    "Структура:\n"
    "1. Эпичный заголовок.\n"
    "2. Аналитический блок (описание ситуации: кто виноват — циклон, антициклон или фронт).\n"
    "3. Прогноз по Смоленску (утро, день, вечер, ночь) в сдержанном стиле, без лишнего текста с добавлянием стикеров.\n"
    "Нужны четкие данные, например:\n"
    "Ночь от +10 до +11"
    "Утро от +11 до +12"
    "День от +12 до +13"
    "Вечер от +14 до +16"
    "4. Краткий обзор по частям (Север, Восток, Юг, Запад, Центр).\n"
    "5. Блок предупреждений.\n"
    # "6. Астрономия.\n\n"
    "Контекст данных: Тебе будут переданы цифры: температура, влажность, давление, скорость ветра. "
    "Твоя работа — «одеть» их в текст. Если в данных есть резкий перепад давления или сильный ветер — "
    "выноси это в предупреждения.\n\n"
    "Важное правило: Никогда не выдумывай названия городов вне Смоленской области. "
    "Не используй markdown разметку."
    "Не выделяй заговоки(жирным шрифтом, курсивом и так далее)."
    "Используй только: Смоленск, Вязьма, Рославль, Ярцево, Сафоново, Гагарин, Десногорск, Починок, Дорогобуж, Ельня, Рудня, Велиж, Демидов, Духовщина, Сычёвка.\n\n"
    "добавляй в пост тематические стикеры для telegram, например ⛅, ☁, ☁, 🌨, ❄, 🌬, ⚡️"
    # "В прогноз добавляй отдельно блок с температурой без лишнего текста и украшения"
    # "Он долджен выглядеть строго так:"
    # "Ночь от +10 до +11"
    # "Утро от +11 до +12"
    # "День от +12 до +13"
    # "Вечер от +14 до +16"
)


class GigaChatService:
    """Async wrapper over GigaChat SDK."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self._cfg = cfg or settings
        self._client: GigaChat | None = None

    async def start(self) -> None:
        self._client = GigaChat(
            credentials=self._cfg.gigachat_credentials,
            model=self._cfg.gigachat_model,
            scope=self._cfg.gigachat_scope,
            verify_ssl_certs=False,
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate_post(self, weather_data: dict[str, Any]) -> str:
        """Generate a literary weather post from forecast data."""
        assert self._client is not None, "Call start() first"

        chat = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=SYSTEM_PROMPT),
                Messages(
                    role=MessagesRole.USER,
                    content=self._build_user_prompt(weather_data),
                ),
            ],
        )

        try:
            response = await self._client.achat(chat)
            return response.choices[0].message.content
        except Exception:
            logger.exception("GigaChat request failed")
            return self._fallback(weather_data)

    async def generate_alert(self, alerts: list[dict[str, Any]]) -> str:
        """Generate an alert message for extreme weather."""
        assert self._client is not None, "Call start() first"

        prompt = (
            "Составь краткое и четкое погодное предупреждение для жителей Смоленской области.\n"
            "Данные:\n"
            f"{json.dumps(alerts, ensure_ascii=False, indent=2)}\n"
            "Тон спокойный и серьезный. 2-3 предложения."
        )

        chat = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=SYSTEM_PROMPT),
                Messages(role=MessagesRole.USER, content=prompt),
            ],
        )

        try:
            response = await self._client.achat(chat)
            return response.choices[0].message.content
        except Exception:
            logger.exception("GigaChat alert request failed")
            return "\n".join(
                f"⚠️ {alert['city']}: {', '.join(alert.get('alert_reasons', []))}"
                for alert in alerts
            )

    @staticmethod
    def _build_user_prompt(data: dict[str, Any]) -> str:
        """Format weather data into a structured text prompt."""
        now = datetime.now(timezone.utc)
        generated_date = now.strftime("%d.%m.%Y")
        city = data.get("city", "Смоленск")
        period_labels = {
            "night": "Ночь",
            "morning": "Утро",
            "day": "День",
            "evening": "Вечер",
        }

        lines = [
            "Сгенерируй прогноз на основе данных ниже.",
            f"Дата составления: {generated_date}",
            f"Дата прогноза: {data.get('forecast_date', generated_date)}",
            f"Город: {city}",
            f"Общее описание: {data.get('description', 'нет данных')}",
            f"Температура за день: от {data.get('temp_min', '?')}°C до {data.get('temp_max', '?')}°C",
            f"Среднее давление: {data.get('pressure', '?')} гПа",
            f"Максимальная влажность: {data.get('humidity', '?')}%",
            f"Ветер: до {data.get('wind_speed', '?')} м/с, порывы до {data.get('wind_gust', '?')} м/с",
            "Прогноз по частям суток:",
        ]

        periods = data.get("periods", {})
        for key in ("night", "morning", "day", "evening"):
            period = periods.get(key, {})
            lines.append(
                f"{period_labels[key]}: "
                f"температура {period.get('temperature', '?')}°C, "
                f"ощущается как {period.get('feels_like', '?')}°C, "
                f"погода: {period.get('description', 'нет данных')}, "
                f"влажность {period.get('humidity', '?')}%, "
                f"давление {period.get('pressure', '?')} гПа, "
                f"ветер {period.get('wind_speed', '?')} м/с, "
                f"порывы {period.get('wind_gust', '?')} м/с, "
                f"облачность {period.get('clouds', '?')}%, "
                f"осадки {period.get('rain', 0)} мм"
            )

        return "\n".join(lines)

    @staticmethod
    def _fallback(data: dict[str, Any]) -> str:
        """Plain-text fallback when GigaChat is unavailable."""
        labels = {
            "night": "Ночь",
            "morning": "Утро",
            "day": "День",
            "evening": "Вечер",
        }
        lines = [
            f"🌡 {data.get('city', '?')}: {data.get('description', 'нет данных')}",
            f"Температура за день от {data.get('temp_min', '?')}°C до {data.get('temp_max', '?')}°C.",
        ]
        periods = data.get("periods", {})
        for key in ("night", "morning", "day", "evening"):
            period = periods.get(key, {})
            lines.append(
                f"{labels[key]}: {period.get('temperature', '?')}°C, "
                f"{period.get('description', 'нет данных')}, "
                f"ветер {period.get('wind_speed', '?')} м/с."
            )
        return "\n".join(lines)
