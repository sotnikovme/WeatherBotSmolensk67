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


DETAILED_PERIOD_KEYS: tuple[str, ...] = (
    "night_00_03",
    "night_03_06",
    "morning_06_09",
    "morning_09_12",
    "day_12_15",
    "day_15_18",
    "evening_18_21",
    "evening_21_24",
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
        return self._render_strict_post(weather_data)

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
        local_now_raw = str(data.get("local_now", ""))
        local_now_text = local_now_raw
        try:
            local_now = datetime.fromisoformat(local_now_raw)
            local_now_text = local_now.strftime("%d.%m.%Y %H:%M")
        except ValueError:
            local_now = None
        forecast_scope = str(data.get("forecast_scope", "full_day"))
        temp_min = GigaChatService._format_temp_value(data.get("temp_min", "?"))
        temp_max = GigaChatService._format_temp_value(data.get("temp_max", "?"))
        detailed_periods = data.get("detailed_periods", {})
        active_period_keys = tuple(key for key in DETAILED_PERIOD_KEYS if key in detailed_periods)
        period_names = {
            "night_00_03": "Ночь (00-03)",
            "night_03_06": "Ночь (03-06)",
            "morning_06_09": "Утро (06-09)",
            "morning_09_12": "Утро (09-12)",
            "day_12_15": "День (12-15)",
            "day_15_18": "День (15-18)",
            "evening_18_21": "Вечер (18-21)",
            "evening_21_24": "Вечер (21-24)",
        }
        period_labels = {
            key: GigaChatService._format_temp_range(
                detailed_periods.get(key, {}).get("temp_min"),
                detailed_periods.get(key, {}).get("temp_max"),
            )
            for key in DETAILED_PERIOD_KEYS
        }

        lines = [
            # "Собери готовый прогноз строго по шаблону ниже.",
            # "Порядок блоков менять нельзя.",
            # f"Дата генерации: {generated_date}",
            # f"Город: {city}",
            # f"Дата прогноза: {forecast_date}",
            # f"День недели: {weekday}",
            # f"Сводка за сутки: {data.get('description', 'нет данных')}",
            # f"Температура за сутки: {temp_min}...{temp_max}",
            # (
            #     "Ветер за сутки: "
            #     f"{data.get('wind_direction_text', 'без направления')} "
            #     f"{data.get('wind_speed', '?')}-{data.get('wind_gust', '?')} м/с"
            # ),
            # (
            #     "Давление за сутки: "
            #     f"{data.get('pressure_mm_min', '?')}...{data.get('pressure_mm_max', '?')} мм рт. ст.; "
            #     f"тренд {data.get('pressure_mm_trend', 'нет данных')}"
            # ),
            # "",
            # "Используй эти точные 3-часовые блоки при заполнении прогноза:",
            # "Температурный диапазон в каждом блоке копируй дословно из строки блока ниже.",
            # "Нельзя усреднять температуру между соседними блоками и нельзя повторять диапазон из другого блока.",
        ]

        if local_now_text:
            lines.extend([
                f"Локальное время в городе на момент генерации: {local_now_text}.",
                f"Дата прогноза: {forecast_date}.",
            ])

        if forecast_scope == "remaining_day":
            lines.extend([
                "Режим прогноза: только оставшееся время текущего дня.",
                "Если часть интервалов уже прошла, их нельзя возвращать в тексте.",
                "Нельзя переключать прогноз на завтра, пока во входных данных есть хотя бы один оставшийся интервал на сегодня.",
            ])

        if active_period_keys:
            remaining_labels = ", ".join(
                detailed_periods.get(key, {}).get("label") or period_names[key]
                for key in active_period_keys
            )
            lines.append(f"Оставшиеся доступные интервалы на сегодня: {remaining_labels}.")
            lines.append("В итоговом сообщении можно добавлять только эти интервалы и никакие другие.")
            lines.append("Если во входных данных нет блока для времени суток, этот блок нужно полностью пропустить в готовом тексте.")

        for key in active_period_keys:
            period = detailed_periods.get(key, {})
            label = period.get("label") or period_names[key]
            lines.append(
                f"- {label}: диапазон {period_labels[key]}, "
                f"ощущается как {GigaChatService._format_temp_value(period.get('feels_like', '?'))}, "
                f"описание {period.get('description', 'нет данных')}, "
                f"облачность {period.get('clouds', '?')}%, "
                f"осадки {period.get('rain', 0)} мм, "
                f"ветер {period.get('wind_speed', '?')}-{period.get('wind_gust', '?')} м/с, направление {period.get('wind_dir', 'нет данных')}, "
                f"давление {period.get('pressure_mm', '?')} мм рт. ст."
            )
        
        lines.extend([
            "",
            "ВАЖНО:",
            "Температурные диапазоны по 3-часовым интервалам уже посчитаны во входных данных.",
            "В финальном тексте переноси их без изменений.",
            "Нельзя усреднять температуры между соседними блоками и нельзя повторять один и тот же диапазон во всех блоках, если во входных данных диапазоны различаются.",
            "Если в данных для блока указано +16...+18, в ответе должен остаться ровно диапазон +16...+18.",
            "",
            "Собери готовый прогноз строго по шаблону ниже.",
            "Отступать от структуры нельзя.",
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
        ])

        for key in ("night", "morning", "day", "evening"):
            period = data.get("periods", {}).get(key, {})
            if period.get("temp_min") is None:
                continue
            lines.append(
                f"- {period.get('label', key)}: "
                f"{GigaChatService._format_temp_range(period.get('temp_min'), period.get('temp_max'))}, "
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

        return "\n".join(lines)

    @staticmethod
    def _fallback(data: dict[str, Any]) -> str:
        """Plain-text fallback when GigaChat is unavailable."""
        return GigaChatService._render_strict_post(data)

    @staticmethod
    def _render_strict_post(data: dict[str, Any]) -> str:
        city = str(data.get("city", "Смоленск"))
        forecast_date = GigaChatService._format_date(str(data.get("forecast_date", "")))
        summary_periods = data.get("periods", {})
        detailed_periods = data.get("detailed_periods", {})
        multi_day = data.get("multi_day", [])
        temp_min = GigaChatService._format_temp_value(data.get("temp_min", "?"))
        temp_max = GigaChatService._format_temp_value(data.get("temp_max", "?"))
        description = GigaChatService._sentence(data.get("description", "переменная погода"))

        parts = [
            f"🇷🇺Прогноз погоды по {city} на {forecast_date}.",
            "",
            GigaChatService._build_intro(city, description),
            "",
            GigaChatService._build_headline(description),
            "",
            GigaChatService._build_analysis_paragraph_1(city, description, temp_min, temp_max),
            "",
            GigaChatService._build_analysis_paragraph_2(data),
            "",
        ]

        for key in DETAILED_PERIOD_KEYS:
            period = detailed_periods.get(key)
            if not period:
                continue
            label = str(period.get("label", key))
            sticker = GigaChatService._pick_sticker(period, label)
            parts.extend(
                [
                    f"{label} {sticker} {GigaChatService._format_temp_range(period.get('temp_min'), period.get('temp_max'))}",
                    f"🌬 {GigaChatService._format_wind(period)}",
                    GigaChatService._sentence(period.get("description", "Без уточнений")),
                    "",
                ]
            )

        for key in ("night", "morning", "day", "evening"):
            period = summary_periods.get(key, {})
            if period.get("temp_min") is None:
                continue
            label = str(period.get("label", key))
            sticker = GigaChatService._pick_sticker(period, label)
            parts.extend(
                [
                    f"{label} {sticker} {GigaChatService._format_temp_range(period.get('temp_min'), period.get('temp_max'))}",
                    GigaChatService._build_summary_line(period),
                ]
            )

        parts.extend(
            [
                "",
                f"🌬 {GigaChatService._build_general_wind_line(data)}",
                "",
                f"📈 Давление будет меняться {GigaChatService._build_pressure_line(data)}",
            ]
        )

        if multi_day:
            parts.extend(["", "", "Погода на несколько дней — ночь/день:", ""])
            for item in multi_day:
                sticker = GigaChatService._pick_sticker(item, item.get("date", ""))
                parts.extend(
                    [
                        f"{GigaChatService._format_date(item.get('date'))} {sticker} "
                        f"{GigaChatService._format_temp_value(item.get('temp_min'))}/"
                        f"{GigaChatService._format_temp_value(item.get('temp_max'))}",
                        GigaChatService._sentence(item.get("description", "Без уточнений")),
                        "",
                    ]
                )
            if parts[-1] == "":
                parts.pop()

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
    def _format_temp_range(min_value: Any, max_value: Any) -> str:
        if min_value == max_value:
            return GigaChatService._format_temp_value(min_value)
        return (
            f"{GigaChatService._format_temp_value(min_value)}..."
            f"{GigaChatService._format_temp_value(max_value)}"
        )

    @staticmethod
    def _filter_unavailable_periods(text: str, data: dict[str, Any]) -> str:
        detailed_periods = data.get("detailed_periods", {})
        allowed_labels = {
            str(period.get("label", "")).strip()
            for period in detailed_periods.values()
            if period.get("label")
        }
        all_labels = {
            "Ночь (00-03)",
            "Ночь (03-06)",
            "Утро (06-09)",
            "Утро (09-12)",
            "День (12-15)",
            "День (15-18)",
            "Вечер (18-21)",
            "Вечер (21-24)",
        }
        blocked_labels = all_labels - allowed_labels
        if not blocked_labels:
            return text

        lines = text.splitlines()
        filtered: list[str] = []
        skip_block = False

        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(label) for label in blocked_labels):
                skip_block = True
                continue

            if skip_block:
                if not stripped:
                    skip_block = False
                continue

            filtered.append(line)

        return "\n".join(filtered).strip()

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

    @staticmethod
    def _sentence(value: Any) -> str:
        text = " ".join(str(value or "").strip().split())
        if not text:
            return "Без уточнений."
        text = text[0].upper() + text[1:]
        if text[-1] not in ".!?":
            text += "."
        return text

    @staticmethod
    def _headline_token(text: str) -> str:
        lowered = text.lower()
        mapping = (
            ("гроза", "ГРОЗОВОЙ"),
            ("лив", "ЛИВНЕВЫЙ"),
            ("дожд", "ДОЖДЛИВЫЙ"),
            ("снег", "СНЕЖНЫЙ"),
            ("туман", "ТУМАННЫЙ"),
            ("дымк", "ТУМАННЫЙ"),
            ("мгла", "ТУМАННЫЙ"),
            ("пасмур", "ПАСМУРНЫЙ"),
            ("облач", "ОБЛАЧНЫЙ"),
            ("ясно", "ЯСНЫЙ"),
        )
        for token, headline in mapping:
            if token in lowered:
                return headline
        return "СПОКОЙНЫЙ"

    @staticmethod
    def _build_intro(city: str, description: str) -> str:
        return f"В {city} сегодня ожидается {description.lower()}."

    @staticmethod
    def _build_headline(description: str) -> str:
        return f"{GigaChatService._headline_token(description)} ДЕНЬ"

    @staticmethod
    def _build_analysis_paragraph_1(
        city: str,
        description: str,
        temp_min: str,
        temp_max: str,
    ) -> str:
        return (
            f"В течение дня в {city} сохранится {description.lower()}. "
            f"Температура в доступных интервалах будет держаться в пределах {temp_min}...{temp_max}. "
            "Основные изменения в прогнозе стоит оценивать по отдельным временным блокам ниже."
        )

    @staticmethod
    def _build_analysis_paragraph_2(data: dict[str, Any]) -> str:
        detailed_periods = data.get("detailed_periods", {})
        if not detailed_periods:
            return "Дальнейшее развитие погоды зависит от следующих обновлений прогноза."

        first_key = next(iter(detailed_periods))
        last_key = next(reversed(detailed_periods))
        first_period = detailed_periods[first_key]
        last_period = detailed_periods[last_key]
        first_label = first_period.get("label", first_key)
        last_label = last_period.get("label", last_key)
        first_desc = GigaChatService._sentence(first_period.get("description", "Без уточнений"))
        last_desc = GigaChatService._sentence(last_period.get("description", "Без уточнений"))
        return (
            f"Ближайший ориентир по погоде — интервал {first_label.lower()}, где ожидается "
            f"{first_desc[:-1].lower()}. "
            f"К финалу дня, в блоке {last_label.lower()}, прогноз показывает, что "
            f"{last_desc[:-1].lower()}. "
            "Такой порядок помогает увидеть, как будет меняться погода по ходу оставшейся части суток."
        )

    @staticmethod
    def _pick_sticker(period: dict[str, Any], label: str) -> str:
        text = " ".join(
            str(period.get(key, "")).lower()
            for key in ("description", "weather")
        )
        is_night = "ноч" in label.lower()

        if "гроз" in text:
            return "⛈️"
        if "лив" in text:
            return "🌦️"
        if "дожд" in text:
            return "🌧️"
        if "снег" in text:
            return "❄️"
        if any(token in text for token in ("туман", "дымк", "мгла")):
            return "🌫️"
        if any(token in text for token in ("пасмур", "облач")):
            return "☁️"
        if any(token in text for token in ("ясно", "clear")):
            return "🌙" if is_night else "☀️"
        return "🌙" if is_night else "⛅"

    @staticmethod
    def _build_summary_line(period: dict[str, Any]) -> str:
        return GigaChatService._sentence(period.get("description", "Без уточнений"))

    @staticmethod
    def _build_general_wind_line(data: dict[str, Any]) -> str:
        direction = str(data.get("wind_direction_text", "")).strip()
        speed = data.get("wind_speed", "?")
        gust = data.get("wind_gust")
        if direction:
            text = f"Ветер {direction} {speed}"
        else:
            text = f"Ветер {speed}"
        if gust not in (None, "", speed, "?"):
            text += f"-{gust} м/с"
        else:
            text += " м/с"
        return text + "."

    @staticmethod
    def _build_pressure_line(data: dict[str, Any]) -> str:
        pressure_min = data.get("pressure_mm_min")
        pressure_max = data.get("pressure_mm_max")
        if pressure_min is None and pressure_max is None:
            return "без выраженного диапазона."
        if pressure_min == pressure_max or pressure_max is None:
            return f"около {pressure_min} мм рт. ст."
        return f"в диапазоне {pressure_min}...{pressure_max} мм рт. ст."
