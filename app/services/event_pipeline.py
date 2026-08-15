"""NL one-shot пайплайн: текст → LLM → Calendar → ответ.

Переносит логику processInstruction() и sendAgenda() из PHP telegram_webhook.php.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update

from app.calendar.auth import get_credentials_for_user
from app.calendar.conflicts import find_conflicts
from app.calendar.service import (
    create_event,
    delete_event,
    get_upcoming_events,
    update_event,
)
from app.db.session import async_session_factory
from app.llm.service import extract_event_details
from app.models import User
from app.state.conversation import clear_state, save_state
from app.telegram.keyboards import (
    confirm_create_conflict_keyboard,
    quick_actions_keyboard,
)
from app.utils.date_resolver import resolve_russian_weekday_date
from app.utils.formatters import escape, format_agenda

logger = logging.getLogger(__name__)


async def process_instruction(
    update: Update,
    chat_id: int,
    text: str,
    is_voice: bool = False,
) -> None:
    """Обработать NL one-shot команду (текстовую или транскрибированную из голоса).

    Аналог PHP processInstruction() из telegram_webhook.php:540-600.
    """
    creds = await get_credentials_for_user(chat_id)
    if not creds:
        await update.message.reply_text(
            "⚠️ Токен Google истёк. Отправьте /start для переподключения.",
            parse_mode="HTML",
        )
        return

    timezone = await _get_user_timezone(chat_id)

    # Получаем предстоящие события для контекста LLM
    calendar = await get_upcoming_events(creds, user_id=chat_id)

    # Разбираем команду через LLM
    event_details = await extract_event_details(text, calendar, timezone)

    heard = f"\n\n📝 Услышано: «{text}»" if is_voice else ""

    if event_details is None:
        await update.message.reply_text(
            "❌ Не удалось распознать запрос." + heard,
            parse_mode="HTML",
        )
        return

    intent = event_details.intent
    event_data = event_details.model_dump()
    _apply_weekday_date_guardrail(event_data, intent, text, timezone)

    if intent == "create_event":
        await _handle_create(update, chat_id, creds, event_data, calendar, timezone, heard)
    elif intent == "update_event":
        await _handle_update(update, chat_id, creds, event_data, timezone, heard)
    elif intent == "delete_event":
        await _handle_delete(update, chat_id, creds, event_data, heard)
    else:
        msg = event_details.message or "Не удалось сопоставить событием."
        await update.message.reply_text(
            f"🤔 {msg}" + heard,
            parse_mode="HTML",
        )


def _apply_weekday_date_guardrail(
    event_data: dict,
    intent: str,
    text: str,
    timezone: str,
) -> None:
    tz = ZoneInfo(timezone)
    resolved_date = resolve_russian_weekday_date(text, datetime.now(tz))
    if not resolved_date:
        return

    if intent == "create_event":
        previous_date = event_data.get("date", "")
        event_data["date"] = resolved_date
    elif intent == "update_event":
        previous_date = event_data.get("new_date", "")
        event_data["new_date"] = resolved_date
    else:
        return

    if previous_date != resolved_date:
        logger.info(
            "Corrected LLM weekday date: intent=%s previous=%s resolved=%s text=%r",
            intent,
            previous_date,
            resolved_date,
            text,
        )


async def _handle_create(
    update: Update,
    chat_id: int,
    creds,
    event_data: dict,
    calendar: list,
    timezone: str,
    heard: str,
) -> None:
    """Обработка intent=create_event."""
    from app.utils.formatters import conflict_text

    # Проверяем конфликты
    conflicts = await find_conflicts(creds, event_data, timezone, user_id=chat_id)

    if conflicts:
        tz = ZoneInfo(timezone)
        # Сохраняем state для callback подтверждения
        from app.schemas import FlowState
        save_state(chat_id, FlowState(flow="create", step="confirm", event=event_data))

        await update.message.reply_text(
            conflict_text(conflicts, tz) + "\n\nСоздать всё равно?" + heard,
            parse_mode="HTML",
            reply_markup=confirm_create_conflict_keyboard(),
        )
        return

    # Без конфликтов — создаём сразу
    result = await create_event(creds, event_data, timezone)
    if result.success:
        reply = (
            f"✅ Создано: <b>{escape(result.title)}</b>\n"
            f"🕒 {result.when}"
        )
        if result.recurring:
            reply += "\n🔁 Повторяющееся"
        if event_data.get("location"):
            reply += f"\n📍 {escape(event_data['location'])}"
        reply += f"\n\n{result.html_link}"

        await update.message.reply_text(
            reply + heard,
            parse_mode="HTML",
            reply_markup=quick_actions_keyboard(result.id),
        )
    else:
        await update.message.reply_text(
            f"❌ Не удалось создать:\n{result.error}",
            parse_mode="HTML",
        )


async def _handle_update(
    update: Update,
    chat_id: int,
    creds,
    event_data: dict,
    timezone: str,
    heard: str,
) -> None:
    """Обработка intent=update_event."""
    result = await update_event(
        creds, event_data.get("target_event_id", ""), event_data, timezone
    )

    if result.success:
        await update.message.reply_text(
            f"✅ Обновлено: <b>{escape(result.title)}</b>\n"
            f"🕒 {result.start}\n\n{result.html_link}" + heard,
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"❌ Не удалось обновить:\n{result.error}",
            parse_mode="HTML",
        )


async def _handle_delete(
    update: Update,
    chat_id: int,
    creds,
    event_data: dict,
    heard: str,
) -> None:
    """Обработка intent=delete_event."""
    result = await delete_event(creds, event_data.get("target_event_id", ""))

    if result.success:
        await update.message.reply_text(
            f"🗑 Удалено: <b>{escape(result.title)}</b>" + heard,
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"❌ Не удалось удалить:\n{result.error}",
            parse_mode="HTML",
        )


async def send_agenda(update: Update, chat_id: int, scope: str) -> None:
    """Отправить повестку дня (today/week).

    Аналог PHP sendAgenda() из telegram_webhook.php:660-699.
    """
    creds = await get_credentials_for_user(chat_id)
    if not creds:
        await update.message.reply_text(
            "⚠️ Сначала подключите Google Calendar: /start",
            parse_mode="HTML",
        )
        return

    timezone = await _get_user_timezone(chat_id)
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)

    from app.calendar.service import get_events

    if scope == "today":
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        time_max = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
    else:
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        time_max = (now + timedelta(days=7)).replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

    events = await get_events(creds, time_min, time_max, user_id=chat_id, purpose="reminders")
    text = format_agenda(events, scope, timezone)

    await update.message.reply_text(text, parse_mode="HTML")


async def _get_user_timezone(chat_id: int) -> str:
    """Получить timezone пользователя из БД."""
    from sqlalchemy import select
    async with async_session_factory() as session:
        result = await session.execute(
            select(User.timezone).where(User.telegram_chat_id == chat_id)
        )
        row = result.scalar_one_or_none()
        return row if row else "Europe/Moscow"
