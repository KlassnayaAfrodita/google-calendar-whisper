"""Сборка Telegram Application — регистрация всех хендлеров.

Переносит диспетчеризацию из PHP telegram_webhook.php в декларативную форму
через python-telegram-bot ConversationHandler и handlers.
"""

from __future__ import annotations

import logging

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from app.config import settings
from app.telegram.handlers.callbacks import handle_callback
from app.telegram.handlers.commands import (
    cmd_cancel,
    cmd_calendars,
    cmd_create,
    cmd_delete,
    cmd_help,
    cmd_reconnect,
    cmd_start,
    cmd_today,
    cmd_update,
    cmd_week,
)
from app.telegram.handlers.messages import handle_message

logger = logging.getLogger(__name__)


def build_application() -> Application:
    """Создать и настроить Telegram Application."""
    app = (
        Application.builder()
        .token(settings.bot_token)
        .connect_timeout(settings.telegram_connect_timeout)
        .read_timeout(settings.telegram_read_timeout)
        .write_timeout(settings.telegram_write_timeout)
        .pool_timeout(settings.telegram_pool_timeout)
        .get_updates_connect_timeout(settings.telegram_connect_timeout)
        .get_updates_read_timeout(settings.telegram_read_timeout)
        .build()
    )

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("create", cmd_create))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("calendars", cmd_calendars))
    app.add_handler(CommandHandler("reconnect", cmd_reconnect))

    # Callback queries (inline-кнопки)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Текстовые и голосовые сообщения (последний handler — catch-all)
    app.add_handler(
        MessageHandler(
            filters.TEXT | filters.VOICE,
            handle_message,
        )
    )

    logger.info("Telegram Application настроен")
    return app
