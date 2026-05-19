"""CRUD helpers for the User model."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import User


async def get_or_create_user(session: AsyncSession, chat_id: int) -> User:
    """Return existing user or create a new one."""
    stmt = select(User).where(User.chat_id == chat_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        user = User(chat_id=chat_id)
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return user


async def get_morning_subscribers(session: AsyncSession) -> list[User]:
    """Return all active users subscribed to morning posts."""
    stmt = select(User).where(
        User.is_active.is_(True),
        User.subscribe_morning.is_(True),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_alert_subscribers(session: AsyncSession) -> list[User]:
    """Return all active users subscribed to weather alerts."""
    stmt = select(User).where(
        User.is_active.is_(True),
        User.subscribe_alerts.is_(True),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def toggle_morning(session: AsyncSession, chat_id: int) -> bool:
    """Toggle morning subscription. Returns new value."""
    user = await get_or_create_user(session, chat_id)
    new_val = not user.subscribe_morning
    await session.execute(
        update(User)
        .where(User.chat_id == chat_id)
        .values(subscribe_morning=new_val)
    )
    await session.commit()
    return new_val


async def toggle_alerts(session: AsyncSession, chat_id: int) -> bool:
    """Toggle alerts subscription. Returns new value."""
    user = await get_or_create_user(session, chat_id)
    new_val = not user.subscribe_alerts
    await session.execute(
        update(User)
        .where(User.chat_id == chat_id)
        .values(subscribe_alerts=new_val)
    )
    await session.commit()
    return new_val
