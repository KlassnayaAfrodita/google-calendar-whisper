"""Ежедневные утренние уведомления через APScheduler.

НОВОЕ — не было в PHP-оригинале.
Отправляет ежедневный дайджест событий пользователя.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.calendar.auth import get_credentials_for_user
from app.calendar.service import get_events
from app.config import settings
from app.db.session import async_session_factory
from app.models import User
from app.utils.formatters import format_daily_reminder

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None


def _get_bot_instance():
    """Получить экземпляр бота для отправки сообщений."""
    try:
        from telegram import Bot
        return Bot(token=settings.bot_token)
    except Exception:
        logger.exception("Не удалось создать экземпляр Bot")
        return None


async def _send_daily_reminders() -> None:
    """Отправить утренние уведомления всем пользователям с enabled reminders."""
    bot = _get_bot_instance()
    if not bot:
        logger.error("Не удалось отправить уведомления: бот не инициализирован")
        return

    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.reminder_enabled == True)  # noqa: E712
        )
        users = result.scalars().all()

    for user in users:
        try:
            creds = await get_credentials_for_user(user.id)
            if not creds:
                logger.warning("Нет OAuth для user_id=%s, пропускаем уведомление", user.id)
                continue

            timezone = user.timezone or settings.default_timezone
            tz = ZoneInfo(timezone)
            now = datetime.now(tz)

            time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            time_max = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

            events = await get_events(
                creds,
                time_min,
                time_max,
                user_id=user.id,
                purpose="reminders",
            )
            text = format_daily_reminder(events, timezone)

            await bot.send_message(
                chat_id=user.telegram_chat_id,
                text=text,
                parse_mode="HTML",
            )

            logger.info("Уведомление отправлено: chat_id=%s", user.telegram_chat_id)

        except Exception:
            logger.exception(
                "Ошибка отправки уведомления: chat_id=%s", user.telegram_chat_id
            )


def build_scheduler() -> AsyncIOScheduler:
    """Создать и настроить APScheduler.

    Запускается каждый день в configured time (по умолчанию 08:00).
    """
    global scheduler

    hour, minute = _parse_reminder_time(settings.reminder_time)

    scheduler = AsyncIOScheduler(timezone=settings.default_timezone)

    scheduler.add_job(
        _send_daily_reminders,
        CronTrigger(hour=hour, minute=minute, timezone=settings.default_timezone),
        id="daily_reminder",
        replace_existing=True,
        misfire_grace_time=3600,  # 1 час
    )

    logger.info(
        "Планировщик настроен: ежедневное уведомление в %02d:%02d (%s)",
        hour, minute, settings.default_timezone,
    )

    return scheduler


def _parse_reminder_time(time_str: str) -> tuple[int, int]:
    """Разобрать HH:MM в (hour, minute)."""
    try:
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return 8, 0
