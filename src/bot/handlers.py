"""Telegram bot handlers (commands, messages, callbacks)."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import cities_kb, main_menu_kb, settings_kb
from src.config import SMOLENSK_CITIES
from src.database.crud import (
    get_or_create_user,
    toggle_alerts,
    toggle_morning,
)
from src.database.session import async_session
from src.services.cache import CacheService
from src.services.gigachat_api import GigaChatService
from src.services.weather_api import WeatherService

logger = logging.getLogger(__name__)

router = Router(name="main")
MAX_TELEGRAM_TEXT_LENGTH = 4096

# These will be injected from main.py via router context or middleware
_weather: WeatherService | None = None
_gigachat: GigaChatService | None = None
_cache: CacheService | None = None


def inject_services(
    weather: WeatherService,
    gigachat: GigaChatService,
    cache: CacheService,
) -> None:
    """Set service instances for handlers to use."""
    global _weather, _gigachat, _cache
    _weather = weather
    _gigachat = gigachat
    _cache = cache


def _split_message(text: str, limit: int = MAX_TELEGRAM_TEXT_LENGTH) -> list[str]:
    """Split long text into Telegram-sized chunks, preferring paragraph boundaries."""
    normalized = text.strip()
    if len(normalized) <= limit:
        return [normalized]

    chunks: list[str] = []
    remaining = normalized
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit

        chunk = remaining[:split_at].strip()
        if not chunk:
            chunk = remaining[:limit].strip()
            split_at = limit

        chunks.append(chunk)
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


async def _send_forecast_text(wait_msg: Message, text: str) -> None:
    """Edit the waiting message and continue in follow-up messages if needed."""
    chunks = _split_message(text)
    await wait_msg.edit_text(chunks[0])
    for chunk in chunks[1:]:
        await wait_msg.answer(chunk)


# ======================================================================
# /start command
# ======================================================================


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Register user and show main menu."""
    assert message.from_user is not None

    async with async_session() as session:
        await get_or_create_user(session, message.from_user.id)

    await message.answer(
        "\U0001f44b \u041f\u0440\u0438\u0432\u0435\u0442\\! \u042f \u2014 \u0431\u043e\u0442 \u043f\u043e\u0433\u043e\u0434\u044b \u0434\u043b\u044f *\u0421\u043c\u043e\u043b\u0435\u043d\u0441\u043a\u043e\u0439 \u043e\u0431\u043b\u0430\u0441\u0442\u0438*\\.\n\n"
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u043d\u0430 \u043a\u043b\u0430\u0432\u0438\u0430\u0442\u0443\u0440\u0435 \u043d\u0438\u0436\u0435\\.",
        parse_mode="MarkdownV2",
        reply_markup=main_menu_kb(),
    )


# ======================================================================
# "\u041f\u043e\u0433\u043e\u0434\u0430 \u0441\u0435\u0439\u0447\u0430\u0441" - city selection
# ======================================================================


@router.message(F.text == "\U0001f324 \u041f\u043e\u0433\u043e\u0434\u0430 \u0441\u0435\u0439\u0447\u0430\u0441")
async def weather_now(message: Message) -> None:
    """Show city picker."""
    await message.answer(
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043d\u0430\u0441\u0435\u043b\u0435\u043d\u043d\u044b\u0439 \u043f\u0443\u043d\u043a\u0442:",
        reply_markup=cities_kb(),
    )


@router.callback_query(F.data.startswith("city:"))
async def on_city_selected(callback: CallbackQuery) -> None:
    """Fetch weather + generate post for the chosen city."""
    assert callback.data is not None
    assert callback.message is not None
    assert _weather is not None and _gigachat is not None and _cache is not None

    city_name = callback.data.split(":", 1)[1]
    city = next((c for c in SMOLENSK_CITIES if c.name == city_name), None)

    if city is None:
        await callback.answer(
            "\u041d\u0430\u0441\u0435\u043b\u0435\u043d\u043d\u044b\u0439 \u043f\u0443\u043d\u043a\u0442 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d",
            show_alert=True,
        )
        return

    await callback.answer()
    wait_msg = await callback.message.answer("\u23f3 \u0417\u0430\u0433\u0440\u0443\u0436\u0430\u044e \u043f\u0440\u043e\u0433\u043d\u043e\u0437...")

    try:
        # 1. Check post cache
        post = await _cache.get_post(city.name)

        if post is None:
            # 2. Check weather cache
            weather_data = await _cache.get_weather(city.name)

            if weather_data is None:
                # 3. Fetch from OWM
                weather_data = await _weather.get_forecast(city)
                await _cache.set_weather(city.name, weather_data)

            # 4. Generate post via GigaChat
            post = await _gigachat.generate_post(weather_data)
            await _cache.set_post(city.name, post)

        await _send_forecast_text(wait_msg, post)

    except Exception:
        logger.exception("Failed to get weather for %s", city.name)
        await wait_msg.edit_text(
            "\u274c \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c "
            "\u043f\u0440\u043e\u0433\u043d\u043e\u0437. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435."
        )


# ======================================================================
# "\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438"
# ======================================================================


@router.message(F.text == "\u2699\ufe0f \u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438")
async def subscription_settings(message: Message) -> None:
    """Show subscription toggles."""
    assert message.from_user is not None

    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)

    await message.answer(
        "\u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430\u043c\u0438:",
        reply_markup=settings_kb(user),
    )


@router.callback_query(F.data == "toggle:morning")
async def on_toggle_morning(callback: CallbackQuery) -> None:
    """Toggle morning subscription."""
    assert callback.from_user is not None
    assert callback.message is not None

    async with async_session() as session:
        new_val = await toggle_morning(session, callback.from_user.id)
        user = await get_or_create_user(session, callback.from_user.id)

    status = "\u0432\u043a\u043b\u044e\u0447\u0435\u043d\u0430 \u2705" if new_val else "\u043e\u0442\u043a\u043b\u044e\u0447\u0435\u043d\u0430 \u274c"
    await callback.answer(f"\u0423\u0442\u0440\u0435\u043d\u043d\u044f\u044f \u0440\u0430\u0441\u0441\u044b\u043b\u043a\u0430 {status}")

    await callback.message.edit_reply_markup(reply_markup=settings_kb(user))


@router.callback_query(F.data == "toggle:alerts")
async def on_toggle_alerts(callback: CallbackQuery) -> None:
    """Toggle alerts subscription."""
    assert callback.from_user is not None
    assert callback.message is not None

    async with async_session() as session:
        new_val = await toggle_alerts(session, callback.from_user.id)
        user = await get_or_create_user(session, callback.from_user.id)

    status = "\u0432\u043a\u043b\u044e\u0447\u0435\u043d\u044b \u2705" if new_val else "\u043e\u0442\u043a\u043b\u044e\u0447\u0435\u043d\u044b \u274c"
    await callback.answer(f"\u042d\u043a\u0441\u0442\u0440\u0435\u043d\u043d\u044b\u0435 \u043e\u043f\u043e\u0432\u0435\u0449\u0435\u043d\u0438\u044f {status}")

    await callback.message.edit_reply_markup(reply_markup=settings_kb(user))


@router.callback_query(F.data == "back_to_menu")
async def on_back_to_menu(callback: CallbackQuery) -> None:
    """Delete the inline message."""
    assert callback.message is not None
    await callback.answer()
    await callback.message.delete()
