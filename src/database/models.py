"""SQLAlchemy ORM models."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all models."""


class User(Base):
    """Telegram bot user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    subscribe_morning: Mapped[bool] = mapped_column(Boolean, default=False)
    subscribe_alerts: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")

    def __repr__(self) -> str:
        return (
            f"<User id={self.id} chat_id={self.chat_id} "
            f"morning={self.subscribe_morning} alerts={self.subscribe_alerts}>"
        )
