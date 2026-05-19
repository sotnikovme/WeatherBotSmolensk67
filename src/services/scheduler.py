"""APScheduler jobs: morning post broadcast and alert checks."""

from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import settings
from src.database.crud import get_alert_subscribers, get_morning_subscribers
from src.database.session import async_session
from src.services.cache import CacheService
from src.services.gigachat_api import GigaChatService
from src.services.weather_api import WeatherService
from src.utils.formatting import escape_md

logger = logging.getLogger(__name__)


async def job_morning_post(
    bot: Bot,
    weather: WeatherService,
    gigachat: GigaChatService,
    cache: CacheService,
) -> None:
    """Send morning weather post to all subscribed users."""
    logger.info("Running morning post job")

    try:
        # Use Smolensk as the primary city for the morning digest
        from src.config import SMOLENSK_CITIES

        city = SMOLENSK_CITIES[0]  # Смоленск
        data = await weather.get_current(city)

        # Check cache first
        post = await cache.get_post(city.name)
        if not post:
            post = await gigachat.generate_post(data)
            await cache.set_post(city.name, post)

        text = f"☀️ *Доброе утро\\!*\n\n{escape_md(post)}"

        async with async_session() as session:
            subscribers = await get_morning_subscribers(session)

        for user in subscribers:
            try:
                await bot.send_message(
                    chat_id=user.chat_id,
                    text=text,
                    parse_mode="MarkdownV2",
                )
            except Exception:
                logger.exception("Failed to send morning post to %s", user.chat_id)

    except Exception:
        logger.exception("Morning post job failed")


async def job_alert_check(
    bot: Bot,
    weather: WeatherService,
    gigachat: GigaChatService,
) -> None:
    """Check for extreme weather and notify subscribed users."""
    logger.info("Running alert check job")

    try:
        alerts = await weather.check_alerts()
        if not alerts:
            return

        text_raw = await gigachat.generate_alert(alerts)
        text = f"🚨 *Погодное предупреждение\\!*\n\n{escape_md(text_raw)}"

        async with async_session() as session:
            subscribers = await get_alert_subscribers(session)

        for user in subscribers:
            try:
                await bot.send_message(
                    chat_id=user.chat_id,
                    text=text,
                    parse_mode="MarkdownV2",
                )
            except Exception:
                logger.exception("Failed to send alert to %s", user.chat_id)

    except Exception:
        logger.exception("Alert check job failed")


def setup_scheduler(
    bot: Bot,
    weather: WeatherService,
    gigachat: GigaChatService,
    cache: CacheService,
) -> AsyncIOScheduler:
    """Create and configure the APScheduler instance."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    scheduler.add_job(
        job_morning_post,
        "cron",
        hour=settings.morning_post_hour,
        minute=settings.morning_post_minute,
        kwargs={
            "bot": bot,
            "weather": weather,
            "gigachat": gigachat,
            "cache": cache,
        },
        id="morning_post",
        replace_existing=True,
    )

    scheduler.add_job(
        job_alert_check,
        "interval",
        minutes=settings.alert_check_interval_minutes,
        kwargs={
            "bot": bot,
            "weather": weather,
            "gigachat": gigachat,
        },
        id="alert_check",
        replace_existing=True,
    )

    return scheduler
