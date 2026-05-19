"""Reply and inline keyboards for the weather bot."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from src.config import SMOLENSK_CITIES
from src.database.models import User


# ---------------------------------------------------------------------------
# Reply keyboard (main menu)
# ---------------------------------------------------------------------------

def main_menu_kb() -> ReplyKeyboardMarkup:
    """Persistent bottom keyboard with two main actions."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌤 Погода сейчас")],
            [KeyboardButton(text="⚙️ Настройки подписки")],
        ],
        resize_keyboard=True,
    )


# ---------------------------------------------------------------------------
# Inline keyboards
# ---------------------------------------------------------------------------

def cities_kb() -> InlineKeyboardMarkup:
    """Grid of city buttons (3 per row) for selecting a forecast location."""
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for city in SMOLENSK_CITIES:
        row.append(
            InlineKeyboardButton(
                text=city.name,
                callback_data=f"city:{city.name}",
            )
        )
        if len(row) == 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def settings_kb(user: User) -> InlineKeyboardMarkup:
    """Subscription toggle buttons showing current state."""
    morning_icon = "✅" if user.subscribe_morning else "❌"
    alerts_icon = "✅" if user.subscribe_alerts else "❌"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{morning_icon} Утренний прогноз",
                    callback_data="toggle:morning",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"{alerts_icon} Экстренные оповещения",
                    callback_data="toggle:alerts",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data="back_to_menu",
                ),
            ],
        ],
    )
