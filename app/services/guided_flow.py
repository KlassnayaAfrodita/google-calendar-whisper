"""Guided-флоу: пошаговые /create, /update, /delete.

Переносит логику из PHP telegram_webhook.php:
- startCreateFlow, advanceCreate, showCreatePreview
- startPickFlow (update/delete)
- applyUpdateValue
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update

from app.calendar.auth import get_credentials_for_user
from app.calendar.conflicts import find_conflicts
from app.calendar.service import get_upcoming_events, update_event
from app.db.session import async_session_factory
from app.llm.service import extract_event_details, parse_datetime_change
from app.models import User
from app.schemas import FlowState
from app.state.conversation import clear_state, save_state
from app.telegram.keyboards import pick_events_keyboard, skip_location_keyboard
from app.utils.formatters import escape, format_when

logger = logging.getLogger(__name__)


async def _get_user_timezone(chat_id: int) -> str:
    """Получить timezone пользователя."""
    from sqlalchemy import select
    async with async_session_factory() as session:
        result = await session.execute(
            select(User.timezone).where(User.telegram_chat_id == chat_id)
        )
        row = result.scalar_one_or_none()
        return row if row else "Europe/Moscow"


# ======================================================================
# /create flow
# ======================================================================

async def start_create_flow(update: Update, chat_id: int) -> None:
    """Начать guided /create флоу — спросить название."""
    state = FlowState(flow="create", step="title", data={})
    save_state(chat_id, state)
    await update.message.reply_text(
        "📝 Как называется событие?\n<i>(напр. «Встреча с Иваном»)</i>",
        parse_mode="HTML",
    )


async def advance_flow(
    update: Update,
    chat_id: int,
    state: FlowState,
    text: str,
) -> None:
    """Продвинуть guided флоу на следующий шаг.

    Аналог PHP advanceFlow() из telegram_webhook.php:188-203.
    """
    if state.flow == "create":
        await advance_create(update, chat_id, state, text)
        return

    if state.flow == "update" and state.step == "value":
        await apply_update_value(update, chat_id, state, text)
        return

    # Mid-flow: ожидаем нажатие кнопки
    await update.message.reply_text(
        "👆 Нажмите кнопку выше или отправьте /cancel.",
        parse_mode="HTML",
    )


async def advance_create(
    update: Update,
    chat_id: int,
    state: FlowState,
    text: str,
) -> None:
    """Пошаговый guided /create флоу.

    Аналог PHP advanceCreate() из telegram_webhook.php:205-247.
    """
    if state.step == "title":
        state.data["title"] = text
        state.step = "when"
        save_state(chat_id, state)
        await update.message.reply_text(
            "🕒 Когда?\n<i>(напр. «понедельник в 15:00» или «5 июня с 14:00 до 16:00»)</i>",
            parse_mode="HTML",
        )

    elif state.step == "when":
        state.data["when"] = text
        state.step = "location"
        save_state(chat_id, state)
        await update.message.reply_text(
            "📍 Где? Введите место или нажмите Пропустить.",
            parse_mode="HTML",
            reply_markup=skip_location_keyboard(),
        )

    elif state.step == "location":
        state.data["location"] = text
        # Показываем превью
        text, markup = await _build_create_preview(chat_id, state)

        if text is None:
            clear_state(chat_id)
            await update.message.reply_text(
                f"❌ Не удалось разобрать дату из «{state.data.get('when', '')}».\nНачните заново: /create.",
                parse_mode="HTML",
            )
            return

        await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)

    elif state.step == "confirm":
        event = state.event
        if not event:
            clear_state(chat_id)
            await update.message.reply_text(
                "Нет ожидающего события. Отправьте /create.",
                parse_mode="HTML",
            )
            return

        timezone = await _get_user_timezone(chat_id)
        when = format_when(event, timezone)

        from app.telegram.keyboards import confirm_create_keyboard
        await update.message.reply_text(
            f"У вас есть неподтверждённое событие:\n\n"
            f"📝 <b>{escape(event.get('title', ''))}</b>\n"
            f"🕒 {when}\n\n"
            f"Подтвердите или отправьте /cancel.",
            parse_mode="HTML",
            reply_markup=confirm_create_keyboard(),
        )


async def _build_create_preview(
    chat_id: int,
    state: FlowState,
) -> tuple[str | None, object | None]:
    """Построить текст превью и клавиатуру для guided create.

    Аналог PHP showCreatePreview() из telegram_webhook.php:249-298.
    Возвращает (text, markup) или (None, None) при ошибке.

    Экспортируется для использования в callbacks.py.
    """
    from app.telegram.keyboards import confirm_create_keyboard

    d = state.data
    timezone = await _get_user_timezone(chat_id)

    instruction = f"Создать событие «{d['title']}» {d['when']}"
    if d.get("location"):
        instruction += f" в {d['location']}"

    creds = await get_credentials_for_user(chat_id)
    if not creds:
        return "⚠️ Токен Google истёк. Отправьте /reconnect.", None

    calendar = await get_upcoming_events(creds)
    event_details = await extract_event_details(instruction, calendar, timezone)

    if event_details is None:
        return None, None

    event = event_details.model_dump()
    if not event.get("date") or not event.get("start_time"):
        # Проверяем all-day
        if not event.get("date"):
            return None, None

    event["title"] = d["title"]
    event["location"] = d.get("location", "")
    event["intent"] = "create_event"

    state.step = "confirm"
    state.event = event
    save_state(chat_id, state)

    when = format_when(event, timezone)

    extra = ""
    if event.get("recurrence"):
        extra += "\n🔁 Повторяющееся"

    # Проверяем конфликты
    conflicts = await find_conflicts(creds, event, timezone)
    if conflicts:
        tz = ZoneInfo(timezone)
        from app.utils.formatters import conflict_text
        extra += "\n\n" + conflict_text(conflicts, tz)

    preview = (
        f"Подтвердите:\n\n"
        f"📝 <b>{escape(event.get('title', ''))}</b>\n"
        f"🕒 {when}"
    )
    if event.get("location"):
        preview += f"\n📍 {escape(event['location'])}"
    preview += extra

    return preview, confirm_create_keyboard()


# ======================================================================
# /update flow
# ======================================================================

async def start_update_flow(update: Update, chat_id: int) -> None:
    """Начать guided /update — показать список событий."""
    await _start_pick_flow(update, chat_id, "update")


async def start_delete_flow(update: Update, chat_id: int) -> None:
    """Начать guided /delete — показать список событий."""
    await _start_pick_flow(update, chat_id, "delete")


async def _start_pick_flow(update: Update, chat_id: int, flow: str) -> None:
    """Показать список предстоящих событий для выбора.

    Аналог PHP startPickFlow() из telegram_webhook.php:303-329.
    """
    creds = await get_credentials_for_user(chat_id)
    if not creds:
        await update.message.reply_text(
            "⚠️ Токен Google истёк. Отправьте /start.",
            parse_mode="HTML",
        )
        return

    timezone = await _get_user_timezone(chat_id)
    events = await get_upcoming_events(creds)

    if not events:
        await update.message.reply_text(
            "📭 Нет предстоящих событий в ближайшие 30 дней.",
            parse_mode="HTML",
        )
        return

    events = events[:15]
    prefix = "u_pick:" if flow == "update" else "d_pick:"

    rows = []
    event_list = []
    for i, event in enumerate(events):
        try:
            from datetime import datetime as dt
            start_dt = dt.fromisoformat(event.start)
            tz = ZoneInfo(timezone)
            when_label = start_dt.astimezone(tz).strftime("%a %d %b, %H:%M")
        except (ValueError, TypeError):
            when_label = event.start

        label = f"{event.title} — {when_label}"
        if len(label) > 60:
            label = label[:57] + "…"

        rows.append({"label": label})
        event_list.append({"id": event.id, "title": event.title})

    state = FlowState(flow=flow, step="pick", events=event_list)
    save_state(chat_id, state)

    verb = "изменить" if flow == "update" else "удалить"
    await update.message.reply_text(
        f"Какое событие вы хотите {verb}?",
        parse_mode="HTML",
        reply_markup=pick_events_keyboard(rows, prefix),
    )


async def apply_update_value(
    update: Update,
    chat_id: int,
    state: FlowState,
    text: str,
) -> None:
    """Применить новое значение поля в guided /update.

    Аналог PHP applyUpdateValue() из telegram_webhook.php:331-367.
    """
    event_id = state.event_id
    field = state.field

    if not event_id:
        clear_state(chat_id)
        await update.message.reply_text(
            "Запрос устарел. Отправьте /update.",
            parse_mode="HTML",
        )
        return

    creds = await get_credentials_for_user(chat_id)
    if not creds:
        await update.message.reply_text(
            "⚠️ Токен Google истёк.",
            parse_mode="HTML",
        )
        return

    timezone = await _get_user_timezone(chat_id)
    changes: dict = {}

    if field == "title":
        changes["new_title"] = text
    elif field == "location":
        changes["new_location"] = text
    elif field == "datetime":
        result = await parse_datetime_change(text, timezone)
        if result is None:
            clear_state(chat_id)
            await update.message.reply_text(
                f"❌ Не удалось разобрать дату/время из «{text}». Отправьте /update.",
                parse_mode="HTML",
            )
            return

        changes["new_date"] = result.new_date
        changes["new_start_time"] = result.new_start_time
        changes["new_end_time"] = result.new_end_time

        from app.calendar.service import valid_date, valid_time
        if not valid_date(changes["new_date"]) and not valid_time(changes["new_start_time"]) and not valid_time(changes["new_end_time"]):
            clear_state(chat_id)
            await update.message.reply_text(
                f"❌ Не удалось разобрать дату/время из «{text}». Отправьте /update.",
                parse_mode="HTML",
            )
            return

    result = await update_event(creds, event_id, changes, timezone)
    clear_state(chat_id)

    if result.success:
        await update.message.reply_text(
            f"✅ Обновлено: <b>{escape(result.title)}</b>\n"
            f"🕒 {result.start}\n\n{result.html_link}",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"❌ Не удалось обновить:\n{result.error}",
            parse_mode="HTML",
        )
