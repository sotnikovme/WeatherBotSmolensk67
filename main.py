"""WeatherBot — entry point."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from src.bot.handlers import inject_services, router
from src.config import settings
from src.database.models import Base
from src.database.session import engine
from src.services.cache import CacheService
from src.services.gigachat_api import GigaChatService
from src.services.scheduler import setup_scheduler
from src.services.weather_api import WeatherService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def on_startup(
    bot: Bot,
    weather: WeatherService,
    gigachat: GigaChatService,
    cache: CacheService,
) -> None:
    """Initialise external connections and tables."""
    # Create DB tables (for development; use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await weather.start()
    await gigachat.start()
    await cache.start()

    inject_services(weather, gigachat, cache)
    logger.info("All services started")


async def on_shutdown(
    weather: WeatherService,
    gigachat: GigaChatService,
    cache: CacheService,
) -> None:
    """Gracefully close external connections."""
    await weather.close()
    await gigachat.close()
    await cache.close()
    await engine.dispose()
    logger.info("All services stopped")


async def main() -> None:
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    # Service instances
    weather = WeatherService()
    gigachat = GigaChatService()
    cache = CacheService()

    # Startup
    await on_startup(bot, weather, gigachat, cache)

    # Scheduler
    scheduler = setup_scheduler(bot, weather, gigachat, cache)
    scheduler.start()
    logger.info("Scheduler started")

    try:
        logger.info("Bot is polling…")
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await on_shutdown(weather, gigachat, cache)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
