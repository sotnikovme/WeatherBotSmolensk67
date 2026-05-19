"""GigaChat LLM bridge — generates literary weather posts."""

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
    "Роль: Ты — ведущий синоптик Смоленской области с 20-летним стажем и талантом писателя. "
    "Твоя задача — превращать сухие цифры прогноза в захватывающие и информативные посты для telegram для жителей региона.\n\n"
    "Стиль текста:\n"
    "Заголовки: Всегда используй яркие метафоры (например, «СЕВЕРНЫЙ ТАНЕЦ ЦИКЛОНОВ», «ДЫХАНИЕ АРКТИКИ»).\n"
    "Тон: Сочетай строгость метеоролога (используй термины: фронт окклюзии, циклоническая депрессия, "
    "тыл циклона, инверсия, барическая гора) с уютом (эпитеты: колючий ветер, робкое солнце, чехарда погоды).\n\n"
    "Структура:\n"
    "1. Эпичный заголовок.\n"
    "2. Аналитический блок (описание ситуации: кто виноват — циклон, антициклон или фронт).\n"
    "3. Детальный прогноз по Смоленску (утро, день, вечер, ночь).\n"
    "4. Краткий обзор по частям области (Север, Восток, Юг, Запад, Центр).\n"
    "5. Блок предупреждений (гололедица, метель, давление).\n"
    # "6. Астрономия.\n\n"
    "Контекст данных: Тебе будут переданы цифры: температура, влажность, давление, скорость ветра. "
    "Твоя работа — «одеть» их в текст. Если в данных есть резкий перепад давления или сильный ветер — "
    "выноси это в предупреждения.\n\n"
    "Важное правило: Никогда не выдумывай названия городов вне Смоленской области. "
    "Не используй markdown разметку."
    "Не используй знак звёздочки '*'."
    "Используй только: Смоленск, Вязьма, Рославль, Ярцево, Сафоново, Гагарин, Десногорск, Починок, Дорогобуж, Ельня, Рудня, Велиж, Демидов, Духовщина, Сычёвка.\n\n"
    "добавляй в пост тематические стикеры для telegram, например ⛅, ☁, ☁, 🌨, ❄, 🌬, ⚡️"
    "В прогноз добавляй отдельно блок с температурой например:"
    "Ночь 🌨 -10...-11"
    "Облачно. Снег. "
    "Утро ❄ -11"
    "Облачно. Небольшой снег. "
    "День ☁ -12...-13"
    "Облачно. "
    "Вечер ⛅ -14...-16"
    # "В прогноз добавляй отдельно в тексте точные цифровые данные(например: какой-то текст 'перенос строки' температура: днем ... ночью ...)"
)


class GigaChatService:
    """Async wrapper over GigaChat SDK."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self._cfg = cfg or settings
        self._client: GigaChat | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_post(self, weather_data: dict[str, Any]) -> str:
        """Generate a literary weather post from raw weather data."""
        assert self._client is not None, "Call start() first"

        user_content = self._build_user_prompt(weather_data)

        chat = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=SYSTEM_PROMPT),
                Messages(role=MessagesRole.USER, content=user_content),
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
            "ВНИМАНИЕ! Погодное предупреждение для Смоленской области.\n"
            "Данные:\n" + json.dumps(alerts, ensure_ascii=False, indent=2) + "\n"
            "Напиши краткое и чёткое предупреждение для жителей на русском языке. "
            "Тон — серьёзный, но не паникующий. 2-3 предложения."
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
            parts = []
            for a in alerts:
                reasons = ", ".join(a.get("alert_reasons", []))
                parts.append(f"⚠️ {a['city']}: {reasons}")
            return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_prompt(data: dict[str, Any]) -> str:
        """Format weather data into a structured text prompt."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%d %B %Y")
        city = data.get("city", "Смоленск")

        lines = [
            f"Сгенерируй пост на основе данных:",
            f"Дата: {date_str}",
            f"Город: {city}",
            f"Температура: {data.get('temp', '?')}°C (ощущается как {data.get('feels_like', '?')}°C)",
            f"Описание: {data.get('description', '?')}",
            f"Давление: {data.get('pressure', '?')} гПа",
            f"Влажность: {data.get('humidity', '?')}%",
            f"Ветер: {data.get('wind_speed', '?')} м/с (порывы до {data.get('wind_gust', '?')} м/с)",
        ]

        return "\n".join(lines)

    @staticmethod
    def _fallback(data: dict[str, Any]) -> str:
        """Plain-text fallback when GigaChat is unavailable."""
        return (
            f"🌡 {data.get('city', '?')}: {data.get('temp', '?')}°C "
            f"(ощущается как {data.get('feels_like', '?')}°C), "
            f"ветер {data.get('wind_speed', '?')} м/с, "
            f"влажность {data.get('humidity', '?')}%"
        )
