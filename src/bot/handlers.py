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
from src.utils.formatting import escape_md

logger = logging.getLogger(__name__)

router = Router(name="main")

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
        "👋 Привет\\! Я — бот погоды для *Смоленской области*\\.\n\n"
        "Выберите действие на клавиатуре ниже\\.",
        parse_mode="MarkdownV2",
        reply_markup=main_menu_kb(),
    )


# ======================================================================
# "Погода сейчас" — city selection
# ======================================================================

@router.message(F.text == "🌤 Погода сейчас")
async def weather_now(message: Message) -> None:
    """Show city picker."""
    await message.answer(
        "Выберите город:",
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
        await callback.answer("Город не найден", show_alert=True)
        return

    await callback.answer()
    wait_msg = await callback.message.answer("⏳ Загружаю прогноз...")

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

        text = escape_md(post)
        await wait_msg.edit_text(text, parse_mode="MarkdownV2")

    except Exception:
        logger.exception("Failed to get weather for %s", city.name)
        await wait_msg.edit_text("❌ Не удалось получить прогноз. Попробуйте позже.")


# ======================================================================
# "Настройки подписки"
# ======================================================================

@router.message(F.text == "⚙️ Настройки подписки")
async def subscription_settings(message: Message) -> None:
    """Show subscription toggles."""
    assert message.from_user is not None

    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)

    await message.answer(
        "Управление подписками:",
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

    status = "включена ✅" if new_val else "отключена ❌"
    await callback.answer(f"Утренняя рассылка {status}")

    await callback.message.edit_reply_markup(reply_markup=settings_kb(user))


@router.callback_query(F.data == "toggle:alerts")
async def on_toggle_alerts(callback: CallbackQuery) -> None:
    """Toggle alerts subscription."""
    assert callback.from_user is not None
    assert callback.message is not None

    async with async_session() as session:
        new_val = await toggle_alerts(session, callback.from_user.id)
        user = await get_or_create_user(session, callback.from_user.id)

    status = "включены ✅" if new_val else "отключены ❌"
    await callback.answer(f"Экстренные оповещения {status}")

    await callback.message.edit_reply_markup(reply_markup=settings_kb(user))


@router.callback_query(F.data == "back_to_menu")
async def on_back_to_menu(callback: CallbackQuery) -> None:
    """Delete the inline message."""
    assert callback.message is not None
    await callback.answer()
    await callback.message.delete()
