"""SQLAlchemy ORM модели."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    """Пользователь бота — связывает Telegram-аккаунт с настройками."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)

    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Moscow")
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_time: Mapped[str] = mapped_column(String(5), default="08:00")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Связь 1:1 с токеном
    oauth_token: Mapped["OAuthToken | None"] = relationship(
        "OAuthToken", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class OAuthToken(Base):
    """Токены Google OAuth для пользователя."""

    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True)

    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_uri: Mapped[str] = mapped_column(String(500), default="https://oauth2.googleapis.com/token")
    client_id: Mapped[str] = mapped_column(String(200))
    client_secret: Mapped[str] = mapped_column(String(200))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array string

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped["User"] = relationship("User", back_populates="oauth_token")
