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

SYSTEM_PROMPT = """
Ты — главный синоптик телеграм-канала о погоде в Смоленской области.
Пишешь как готовый редакторский пост: живо, уверенно, без канцелярита.

Твоя задача:
сформировать прогноз строго по заданному шаблону. Отступать от структуры нельзя.
Свободно можно варьировать только:
1. первую короткую фразу после заголовка с городом;
2. креативный заголовок;
3. два аналитических абзаца.

Все остальные блоки обязаны идти именно в том порядке и именно в том формате,
который задан во входных инструкциях.
Если нет вступительной фразы, креативного заголовка и двух аналитических абзацев,
ответ считается неправильным.

Жесткие правила:
1. Пиши только на русском языке.
2. Не добавляй markdown, пояснения, служебные ремарки и комментарии о генерации.
3. Не выдумывай данные, которых нет во входе.
4. Если каких-то данных нет, используй только то, что передано, и не дорисовывай детали.
5. Город выводи ровно в том виде, как он пришел во входе.
6. Температуры всегда округляй до целых.
7. В блоках по времени обязательно ставь подходящий погодный стикер.
8. Подбирай стикер по фактическому описанию периода, а не случайно.
9. Если есть дождь или ливень, не ставь солнечный стикер.
10. Если ясно ночью, используй 🌙, а не ☀️.
11. Если туман, дымка или мгла, используй 🌫️.
12. Не меняй названия блоков и не добавляй свои подзаголовки.
13. После строки с городом и датой оставляй пустую строку.
14. Между смысловыми блоками сохраняй пустые строки как в шаблоне.
15. Ветер и давление формулируй естественно, но в рамках шаблона.
16. Заголовок пиши обычной строкой заглавными буквами, без символов `#`, `*` и других markdown-элементов.
17. После заголовка обязательно дай два отдельных аналитических абзаца по 2-4 предложения каждый.
18. Нельзя переходить к блокам "Ночь (00-03)" и далее, пока не написаны оба аналитических абзаца.
19. Короткая вступительная фраза должна звучать по-человечески и образно, а не как сухая сводка.
20. Аналитические абзацы должны объяснять развитие погоды по ходу суток, а не просто повторять температуры.

Подбор стикеров:
- ясно ночью: 🌙
- ясно днем: ☀️
- малооблачно или переменная облачность: ⛅
- облачно, облачно с прояснениями, пасмурно: ☁️
- дождь: 🌧️
- ливень: 🌦️
- гроза: ⛈️
- туман, дымка, мгла: 🌫️
- снег: ❄️

Ответ должен быть готовым текстом для публикации и строго соответствовать шаблону.
""".strip()

ALERT_SYSTEM_PROMPT = """
Ты пишешь краткое погодное предупреждение для жителей Смоленской области.
Тон спокойный, серьезный, без лишней лирики.
2-3 предложения, только готовый текст.
""".strip()

WEEKDAYS = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

MONTHS = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


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
            f"{json.dumps(alerts, ensure_ascii=False, indent=2)}"
        )

        chat = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=ALERT_SYSTEM_PROMPT),
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
        """Format weather data into a strict prompt for the forecast template."""
        now = datetime.now(timezone.utc)
        generated_date = now.strftime("%d.%m.%Y")
        city = data.get("city", "Смоленск")
        forecast_date_iso = str(data.get("forecast_date", now.date().isoformat()))
        forecast_date = GigaChatService._format_date(forecast_date_iso)
        weekday = GigaChatService._weekday_name(forecast_date_iso)

        temp_min = GigaChatService._format_temp_value(data.get("temp_min", "?"))
        temp_max = GigaChatService._format_temp_value(data.get("temp_max", "?"))


        lines = [
            "Собери готовый прогноз строго по шаблону ниже.",
            "Отступать от структуры нельзя.",
            f"Дата генерации: {generated_date}",
            f"Город: {city}",
            f"Дата прогноза: {forecast_date}",
            f"День недели прогноза: {weekday}",
            f"Сводка за сутки: {data.get('description', 'нет данных')}",
            f"Температура за сутки: {temp_min}...{temp_max}",
            (
                "Ветер за сутки: "
                f"{data.get('wind_direction_text', 'без уточнения направления')} "
                f"{data.get('wind_speed', '?')}-{data.get('wind_gust', '?')} м/с"
            ),
            (
                "Давление за сутки: "
                f"{data.get('pressure_mm_min', '?')}...{data.get('pressure_mm_max', '?')} мм рт. ст.; "
                f"тренд {data.get('pressure_mm_trend', 'нет данных')}"
            ),
            "",
            "Шаблон ответа:",
            "🇷🇺Прогноз погоды по {Город Смоленской области} на {Дата}.",
            "",
            "{Короткая вступительная фраза}",
            "{Обязательно: 1 живая фраза, не короче 8-12 слов}",
            "",
            "{КРЕАТИВНЫЙ ЗАГОЛОВОК}",
            "{Обязательно: БЕЗ #, БЕЗ markdown, БЕЗ точки в конце}",
            "",
            "{Аналитический абзац 1}",
            "{Обязательно: 2-4 предложения с синоптической и бытовой логикой}",
            "",
            "{Аналитический абзац 2}",
            "{Обязательно: 2-4 предложения, развитие погоды к вечеру/ночи}",
            "",
            "Ночь (00-03) {стикер} {температура-диапазон}",
            "🌬 {ветер}",
            "{краткое описание}",
            "",
            "Ночь (03-06) {стикер} {температура-диапазон}",
            "🌬 {ветер}",
            "{краткое описание}",
            "",
            "Утро (06-09) {стикер} {температура-диапазон}",
            "🌬 {ветер}",
            "{краткое описание}",
            "",
            "Утро (09-12) {стикер} {температура-диапазон}",
            "🌬 {ветер}",
            "{краткое описание}",
            "",
            "День (12-15) {стикер} {температура-диапазон}",
            "🌬 {ветер}",
            "{краткое описание}",
            "",
            "День (15-18) {стикер} {температура-диапазон}",
            "🌬 {ветер}",
            "{краткое описание}",
            "",
            "Вечер (18-21) {стикер} {температура-диапазон}",
            "🌬 {ветер}",
            "{краткое описание}",
            "",
            "Вечер (21-24) {стикер} {температура-диапазон}",
            "🌬 {ветер}",
            "{краткое описание}",
            "",
            "Ночь {стикер} {температура-диапазон}",
            "{краткое резюме}",
            "Утро {стикер} {температура-диапазон}",
            "{краткое резюме}",
            "День {стикер} {температура-диапазон}",
            "{краткое резюме}",
            "Вечер {стикер} {температура-диапазон}",
            "{краткое резюме}",
            "",
            "🌬 {общая строка по ветру}",
            "",
            "📈Давление будет меняться {формулировка}: {тренд} мм.рт.ст.",
            "",
            "Погода на несколько дней — ночь/день:",
            "",
            "{дата} {стикер} {ночь}/{день}",
            "{краткое описание}",
            "",
            "{следующая дата} {стикер} {ночь}/{день}",
            "{краткое описание}",
            "",
            "и так далее по переданным дням.",
            "",
            "Данные по 8 интервалам:",
        ]

        for key, period in data.get("detailed_periods", {}).items():
            label = period.get("label", key)
            wind = GigaChatService._format_wind(period)
            lines.append(
                f"- {label}: температура {GigaChatService._format_temp_value(period.get('temperature'))}, "
                f"ощущается как {GigaChatService._format_temp_value(period.get('feels_like'))}, "
                f"описание {period.get('description', 'нет данных')}, "
                f"облачность {period.get('clouds', '?')}%, "
                f"осадки {period.get('rain', 0)} мм, "
                f"ветер {wind}, "
                f"давление {period.get('pressure_mm', '?')} мм рт. ст."
            )

        lines.extend(["", "Данные по 4 сводным периодам:"])
        for key in ("night", "morning", "day", "evening"):
            period = data.get("periods", {}).get(key, {})
            lines.append(
                f"- {period.get('label', key)}: "
                f"{GigaChatService._format_temp_value(period.get('temp_min'))}..."
                f"{GigaChatService._format_temp_value(period.get('temp_max'))}, "
                f"{period.get('description', 'нет данных')}, "
                f"ветер {GigaChatService._format_wind(period)}, "
                f"давление {period.get('pressure_mm', '?')} мм рт. ст."
            )

        lines.extend(["", "Прогноз на несколько дней:"])
        for item in data.get("multi_day", []):
            lines.append(
                f"- {GigaChatService._format_date(item.get('date'))}: "
                f"ночью {GigaChatService._format_temp_value(item.get('temp_min'))}, "
                f"днем {GigaChatService._format_temp_value(item.get('temp_max'))}, "
                f"{item.get('description', 'нет данных')}"
            )

        lines.extend(
            [
                "",
                "Ключевые требования к финальному тексту:",
                "1. Сохрани порядок блоков один в один.",
                "2. Не добавляй лишние заголовки вроде 'Суммарно', 'Ветер', 'Давление'.",
                "3. В каждом временном блоке обязательно поставь подходящий стикер.",
                "4. Стикер должен соответствовать описанию периода.",
                "5. Во всех температурных строках используй целые значения и формат с плюсом, например +17.",
                "6. Для диапазонов используй формат +17…+21.",
                "7. Если в периоде есть дождь, ливень, гроза или туман, это должно отражаться и в тексте, и в стикере.",
                "8. Блок 'Погода на несколько дней' заполни по всем переданным дням, без выдуманных дат.",
                "9. Не сокращай ответ до короткой сводки.",
                "10. Верни только готовый текст прогноза.",
                "11. Не пропускай вступительную фразу, заголовок и два аналитических абзаца.",
                "12. Если заголовок начинается с # или похож на markdown-заголовок, это ошибка.",
                "13. Не начинай блоки с погодой, пока не завершена творческая часть в начале.",
            ]
        )

        return "\n".join(lines)

    @staticmethod
    def _fallback(data: dict[str, Any]) -> str:
        """Plain-text fallback when GigaChat is unavailable."""
        city = data.get("city", "Смоленск")
        forecast_date = GigaChatService._format_date(str(data.get("forecast_date", "")))
        parts = [
            f"🇷🇺Прогноз погоды по {city} на {forecast_date}.",
            "",
            "Прогноз подготовлен по данным модели без художественной обработки.",
            "",
            "СПОКОЙНЫЙ ДЕНЬ БЕЗ ЛИШНИХ СЮРПРИЗОВ",
            "",
            (
                f"В течение суток в {city} ожидается "
                f"{data.get('description', 'переменный характер погоды')}."
            ),
            "Основные параметры собраны автоматически из погодного прогноза.",
            "",
        ]

        for key in (
            "night_00_03",
            "night_03_06",
            "morning_06_09",
            "morning_09_12",
            "day_12_15",
            "day_15_18",
            "evening_18_21",
            "evening_21_24",
        ):
            period = data.get("detailed_periods", {}).get(key)
            if not period:
                continue
            parts.extend(
                [
                    f"{period.get('label', key)} ⛅ "
                    f"{GigaChatService._format_temp_value(period.get('temperature'))}",
                    f"🌬 {GigaChatService._format_wind(period)}",
                    period.get("description", "Без уточнений."),
                    "",
                ]
            )

        for key in ("night", "morning", "day", "evening"):
            period = data.get("periods", {}).get(key)
            if not period:
                continue
            parts.append(
                f"{period.get('label', key)} ⛅ "
                f"{GigaChatService._format_temp_value(period.get('temp_min'))}..."
                f"{GigaChatService._format_temp_value(period.get('temp_max'))}"
            )
            parts.append(period.get("description", "Без уточнений."))

        parts.extend(
            [
                "",
                (
                    "🌬 "
                    f"Ветер {data.get('wind_direction_text', 'переменного направления')} "
                    f"{data.get('wind_speed', '?')}-{data.get('wind_gust', '?')} м/с."
                ),
                "",
                (
                    "📈Давление будет меняться слабо: "
                    f"{data.get('pressure_mm_trend', 'нет данных')} мм.рт.ст."
                ),
                "",
                "Погода на несколько дней — ночь/день:",
                "",
            ]
        )

        for item in data.get("multi_day", []):
            parts.append(
                f"{GigaChatService._format_date(item.get('date'))} ⛅ "
                f"{GigaChatService._format_temp_value(item.get('temp_min'))}/"
                f"{GigaChatService._format_temp_value(item.get('temp_max'))}"
            )
            parts.append(item.get("description", "Без уточнений."))
            parts.append("")

        return "\n".join(parts).strip()

    @staticmethod
    def _format_date(value: Any) -> str:
        if not value:
            return "дата не указана"
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
        return f"{parsed.day} {MONTHS[parsed.month]}"

    @staticmethod
    def _weekday_name(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return "не указан"
        return WEEKDAYS[parsed.weekday()]

    @staticmethod
    def _format_temp_value(value: Any) -> str:
        if isinstance(value, (int, float)):
            rounded = round(value)
            return f"{rounded:+d}"
        return str(value)

    @staticmethod
    def _format_wind(period: dict[str, Any]) -> str:
        direction = str(period.get("wind_dir", "")).strip()
        speed = period.get("wind_speed", "?")
        gust = period.get("wind_gust")
        if direction:
            base = f"{direction} {speed}"
        else:
            base = f"{speed}"
        if gust not in (None, "", speed, "?"):
            return f"{base}-{gust} м/с"
        return f"{base} м/с"
