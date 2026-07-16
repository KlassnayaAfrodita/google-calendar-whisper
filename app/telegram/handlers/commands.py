"""Обработчики Telegram-команд: /start, /help, /cancel, /create, /update, /delete, /today, /week, /reconnect.

Переносит логику команд из PHP telegram_webhook.php.
"""

from __future__ import annotations

import re
import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.calendar.auth import get_auth_url, has_valid_google_auth
from app.config import settings
from app.db.session import async_session_factory
from app.models import User
from app.services.guided_flow import start_create_flow, start_delete_flow, start_update_flow
from app.state.conversation import clear_state
from app.utils.formatters import help_text

logger = logging.getLogger(__name__)

# Паттерн для определения OAuth-кода (4/ signifies Google OAuth code format)
_OAUTH_CODE_RE = re.compile(r'^4/[\w\-_]+')


async def _ensure_user(chat_id: int, username: str | None = None) -> User:
    """Найти или создать пользователя в БД."""
    async with async_session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_chat_id == chat_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(telegram_chat_id=chat_id, telegram_username=username)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info("Новый пользователь: chat_id=%s, username=%s", chat_id, username)
        elif username and user.telegram_username != username:
            user.telegram_username = username
            await session.commit()

        return user


def _build_oauth_instructions(chat_id: int) -> tuple[str, str]:
    """Построить OAuth-ссылку и инструкцию в зависимости от режима.

    Returns:
        (url, instructions_text)
    """
    if settings.oauth_mode == "local":
        # Локальный режим: redirect на localhost, пользователь копирует код
        url = get_auth_url(chat_id=chat_id, redirect_uri="http://localhost")
        instructions = (
            "👋 Привет! Я бот-календарь.\n\n"
            "Для подключения Google Calendar:\n\n"
            "1️⃣ Открой ссылку ниже в браузере\n"
            "2️⃣ Разрешите доступ к календарю\n"
            "3️⃣ В адресной строке появится текст вида:\n"
            "   <code>http://localhost/?state=...&code=4/...</code>\n"
            "4️⃣ Скопируйте часть <code>4/...</code> после <code>code=</code>\n"
            "5️⃣ Отправьте этот код мне в чат\n\n"
            f"🔗 [Подключить Google Calendar]({url})\n\n"
            "Или отправьте /help для справки."
        )
        return url, instructions
    else:
        # Server-режим: redirect на HTTPS-сервер
        url = get_auth_url(chat_id=chat_id)
        instructions = (
            "👋 Привет! Я бот-календарь.\n\n"
            "Для начала подключите свой Google Calendar:\n"
            f"🔗 [Подключить Google Calendar]({url})\n\n"
            "После подключения отправьте мне голосовое или текстовое сообщение "
            "с событием — я добавлю его в ваш календарь.\n\n"
            "Или отправьте /help для справки."
        )
        return url, instructions


async def _handle_oauth_code(update: Update, chat_id: int, code: str) -> None:
    """Обработать OAuth-код, присланный пользователем (локальный режим).

    В local-режиме пользователь присылает только code (без state),
    поэтому state_nonce не проверяем — просто обмениваем код на токен.
    """
    from app.main import oauth_local

    result = await oauth_local(code.strip(), state_nonce="", chat_id_from_chat=chat_id)
    await update.message.reply_text(result, parse_mode="HTML")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start — привествие + проверка Google OAuth."""
    chat_id = update.effective_chat.id
    username = update.effective_user.username if update.effective_user else None

    await _ensure_user(chat_id, username)

    if not await has_valid_google_auth(chat_id):
        _url, instructions = _build_oauth_instructions(chat_id)
        await update.message.reply_text(
            instructions,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await update.message.reply_text(
            "👋 С возвращением!\n\n" + help_text(),
            parse_mode="HTML",
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /help — справка."""
    await update.message.reply_text(help_text(), parse_mode="HTML")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /cancel — отмена текущего флоу."""
    chat_id = update.effective_chat.id
    clear_state(chat_id)
    await update.message.reply_text("❌ Отменено.", parse_mode="HTML")


async def cmd_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /create — начать guided флоу создания."""
    chat_id = update.effective_chat.id
    await _ensure_user(chat_id, update.effective_user.username if update.effective_user else None)
    await start_create_flow(update, chat_id)


async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /update — выбрать событие для редактирования."""
    chat_id = update.effective_chat.id
    await _ensure_user(chat_id, update.effective_user.username if update.effective_user else None)
    await start_update_flow(update, chat_id)


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /delete — выбрать событие для удаления."""
    chat_id = update.effective_chat.id
    await _ensure_user(chat_id, update.effective_user.username if update.effective_user else None)
    await start_delete_flow(update, chat_id)


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /today — расписание на сегодня."""
    chat_id = update.effective_chat.id
    await _ensure_user(chat_id, update.effective_user.username if update.effective_user else None)

    from app.services.event_pipeline import send_agenda
    await send_agenda(update, chat_id, "today")


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /week — расписание на 7 дней."""
    chat_id = update.effective_chat.id
    await _ensure_user(chat_id, update.effective_user.username if update.effective_user else None)

    from app.services.event_pipeline import send_agenda
    await send_agenda(update, chat_id, "week")


async def cmd_reconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /reconnect — переподключить Google Calendar (обновить OAuth)."""
    chat_id = update.effective_chat.id
    await _ensure_user(chat_id, update.effective_user.username if update.effective_user else None)

    _url, instructions = _build_oauth_instructions(chat_id)
    await update.message.reply_text(
        instructions,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def handle_oauth_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверить, является ли текстовое сообщение OAuth-кодом.

    Вызывается из messages.py перед основным пайплайном.
    Возвращает True если это был OAuth-код (и он обработан).
    """
    if not update.message or not update.message.text:
        return False

    text = update.message.text.strip()

    # Проверяем паттерн Google OAuth code: начинается с "4/"
    if _OAUTH_CODE_RE.match(text):
        chat_id = update.effective_chat.id
        logger.info("Получен OAuth-код от chat_id=%s", chat_id)
        await _handle_oauth_code(update, chat_id, text)
        return True

    return False
