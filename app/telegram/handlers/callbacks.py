"""Обработчик callback queries — нажатия inline-кнопок.

Переносит логику handleCallback() из PHP telegram_webhook.php:369-533.
Все callback_data совпадают с PHP-оригиналом.

Исправления:
- CRITICAL #4: _create_confirm передаёт timezone пользователя в create_gcal_event.
- CRITICAL #5: InlineKeyboardButton импортирован на уровне модуля.
- CRITICAL #6: Все Bot.get_instance() заменены на context.bot.
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.calendar.auth import get_credentials_for_user
from app.calendar.service import delete_event, get_event_title, update_event
from app.calendar.service import create_event as create_gcal_event
from app.state.conversation import clear_state, load_state, save_state
from app.telegram.keyboards import (
    confirm_create_keyboard,
    delete_confirm_keyboard,
    quick_actions_keyboard,
    update_field_keyboard,
)
from app.utils.formatters import escape

logger = logging.getLogger(__name__)


async def _get_user_timezone(chat_id: int) -> str:
    """Получить timezone пользователя из БД."""
    from sqlalchemy import select
    from app.db.session import async_session_factory
    from app.models import User

    async with async_session_factory() as session:
        result = await session.execute(
            select(User.timezone).where(User.telegram_chat_id == chat_id)
        )
        row = result.scalar_one_or_none()
        return row if row else "Europe/Moscow"


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Главный диспетчер callback queries."""
    callback = update.callback_query
    await callback.answer()

    chat_id = update.effective_chat.id
    data = callback.data or ""
    message_id = callback.message.message_id if callback.message else None

    if message_id is None:
        return

    state = load_state(chat_id)

    # ------------------------------------------------------------------
    # Quick actions (без state — работают по event_id)
    # ------------------------------------------------------------------
    if data.startswith("qa_edit:"):
        await _qa_edit(update, context, chat_id, data[8:], message_id)
        return

    if data.startswith("qa_del:"):
        await _qa_del(update, context, chat_id, data[7:], message_id)
        return

    if data.startswith("qa_delyes:"):
        await _qa_del_yes(update, context, chat_id, data[10:], message_id)
        return

    if data == "qa_delno":
        await callback.edit_message_text("❌ Удаление отменено.", parse_mode="HTML")
        return

    # ------------------------------------------------------------------
    # Guided create
    # ------------------------------------------------------------------
    if data == "create_skip_loc":
        await _create_skip_loc(update, context, chat_id, state, message_id)
        return

    if data == "create_cancel":
        clear_state(chat_id)
        await callback.edit_message_text("❌ Отменено.", parse_mode="HTML")
        return

    if data == "create_confirm":
        await _create_confirm(update, context, chat_id, state, message_id)
        return

    # ------------------------------------------------------------------
    # Guided update: pick event
    # ------------------------------------------------------------------
    if data.startswith("u_pick:"):
        await _update_pick(update, context, chat_id, state, data[7:], message_id)
        return

    # Guided update: pick field
    if data.startswith("u_field:"):
        await _update_field(update, context, chat_id, state, data[8:], message_id)
        return

    # ------------------------------------------------------------------
    # Guided delete: pick event
    # ------------------------------------------------------------------
    if data.startswith("d_pick:"):
        await _delete_pick(update, context, chat_id, state, data[7:], message_id)
        return

    if data == "d_confirm":
        await _delete_confirm(update, context, chat_id, state, message_id)
        return

    if data == "d_cancel":
        clear_state(chat_id)
        await callback.edit_message_text("❌ Отменено.", parse_mode="HTML")
        return


# ======================================================================
# Quick actions helpers
# ======================================================================

async def _qa_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    event_id: str,
    message_id: int,
) -> None:
    """Быстрое редактирование — показать выбор поля."""
    bot = context.bot

    creds = await get_credentials_for_user(chat_id)
    if not creds:
        await bot.edit_message_text(
            "⚠️ Токен Google истёк. Отправьте /reconnect.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    title = await get_event_title(creds, event_id)
    if not title:
        await bot.edit_message_text(
            "Это событие больше не существует.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    save_state(chat_id, _make_state(
        flow="update", step="field", event_id=event_id, event_title=title
    ))

    await bot.edit_message_text(
        f"✏️ Что вы хотите изменить в <b>{escape(title)}</b>?",
        chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        reply_markup=update_field_keyboard(),
    )


async def _qa_del(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    event_id: str,
    message_id: int,
) -> None:
    """Быстрое удаление — спросить подтверждение."""
    bot = context.bot

    creds = await get_credentials_for_user(chat_id)
    if not creds:
        await bot.edit_message_text(
            "⚠️ Токен Google истёк. Отправьте /reconnect.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    title = await get_event_title(creds, event_id)
    if not title:
        await bot.edit_message_text(
            "Это событие больше не существует.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    await bot.edit_message_text(
        f"🗑 Удалить <b>{escape(title)}</b>?",
        chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        reply_markup=delete_confirm_keyboard(event_id),
    )


async def _qa_del_yes(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    event_id: str,
    message_id: int,
) -> None:
    """Подтверждение быстрого удаления."""
    bot = context.bot

    creds = await get_credentials_for_user(chat_id)
    if not creds:
        await bot.edit_message_text(
            "⚠️ Токен Google истёк.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    result = await delete_event(creds, event_id)
    if result.success:
        await bot.edit_message_text(
            f"🗑 Удалено: <b>{escape(result.title)}</b>",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
    else:
        await bot.edit_message_text(
            f"❌ Не удалось удалить:\n{result.error}",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )


# ======================================================================
# Guided create helpers
# ======================================================================

async def _create_skip_loc(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state,
    message_id: int,
) -> None:
    """Skip location в guided create."""
    if state and state.step == "location":
        state.data["location"] = ""
        await _show_create_preview(update, context, chat_id, state, message_id)


async def _create_confirm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state,
    message_id: int,
) -> None:
    """Подтверждение создания в guided create."""
    bot = context.bot

    if not state or not state.event:
        await bot.edit_message_text(
            "Этот запрос устарел. Начните заново: /create.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    creds = await get_credentials_for_user(chat_id)
    if not creds:
        await bot.edit_message_text(
            "⚠️ Токен Google истёк. Отправьте /reconnect.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    # CRITICAL #4: берём timezone пользователя, а не hardcoded default
    tz = await _get_user_timezone(chat_id)
    event_data = state.event
    result = await create_gcal_event(creds, event_data, timezone=tz)
    loc = event_data.get("location", "")
    clear_state(chat_id)

    if result.success:
        text = (
            f"✅ Создано: <b>{escape(result.title)}</b>\n"
            f"🕒 {result.when}"
        )
        if result.recurring:
            text += "\n🔁 Повторяющееся"
        if loc:
            text += f"\n📍 {escape(loc)}"
        text += f"\n\n{result.html_link}"

        await bot.edit_message_text(
            text,
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
            reply_markup=quick_actions_keyboard(result.id),
        )
    else:
        await bot.edit_message_text(
            f"❌ Не удалось создать:\n{result.error}",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )


async def _show_create_preview(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state,
    message_id: int,
) -> None:
    """Показать превью создания и кнопки подтверждения.

    Вынесено из guided_flow.py, т.к. вызывается и из callbacks.
    """
    from app.services.guided_flow import _build_create_preview

    bot = context.bot

    text, markup = await _build_create_preview(chat_id, state)

    if text is None:
        clear_state(chat_id)
        msg = f"❌ Не удалось разобрать дату из «{state.data.get('when', '')}».\nНачните заново: /create."
        await bot.edit_message_text(
            msg, chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    await bot.edit_message_text(
        text, chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        reply_markup=markup,
    )


# ======================================================================
# Guided update helpers
# ======================================================================

async def _update_pick(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state,
    index_str: str,
    message_id: int,
) -> None:
    """Выбор события для обновления."""
    bot = context.bot

    try:
        idx = int(index_str)
    except ValueError:
        return

    if not state or state.flow != "update" or idx >= len(state.events):
        await bot.edit_message_text(
            "Список устарел. Отправьте /update снова.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    state.event_id = state.events[idx]["id"]
    state.event_title = state.events[idx]["title"]
    state.step = "field"
    save_state(chat_id, state)

    await bot.edit_message_text(
        f"✏️ Что вы хотите изменить в <b>{escape(state.event_title)}</b>?",
        chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        reply_markup=update_field_keyboard(),
    )


async def _update_field(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state,
    field: str,
    message_id: int,
) -> None:
    """Выбор поля для обновления."""
    bot = context.bot

    if not state or state.flow != "update":
        await bot.edit_message_text(
            "Этот запрос устарел. Отправьте /update снова.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    state.field = field
    state.step = "value"
    save_state(chat_id, state)

    prompts = {
        "datetime": "🕒 Введите новую дату/время\n<i>(напр. «среда в 15:00» или «с 14:00 до 16:00»)</i>",
        "title": "📝 Введите новое название",
        "location": "📍 Введите новое место",
    }
    await bot.edit_message_text(
        prompts.get(field, "Введите новое значение:"),
        chat_id=chat_id, message_id=message_id, parse_mode="HTML",
    )


# ======================================================================
# Guided delete helpers
# ======================================================================

async def _delete_pick(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state,
    index_str: str,
    message_id: int,
) -> None:
    """Выбор события для удаления."""
    bot = context.bot

    try:
        idx = int(index_str)
    except ValueError:
        return

    if not state or state.flow != "delete" or idx >= len(state.events):
        await bot.edit_message_text(
            "Список устарел. Отправьте /delete снова.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    state.event_id = state.events[idx]["id"]
    state.event_title = state.events[idx]["title"]
    state.step = "confirm"
    save_state(chat_id, state)

    await bot.edit_message_text(
        f"🗑 Удалить <b>{escape(state.event_title)}</b>?",
        chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data="d_confirm"),
                InlineKeyboardButton("❌ Нет", callback_data="d_cancel"),
            ]
        ]),
    )


async def _delete_confirm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state,
    message_id: int,
) -> None:
    """Подтверждение удаления в guided delete."""
    bot = context.bot

    if not state or not state.event_id:
        await bot.edit_message_text(
            "Этот запрос устарел. Отправьте /delete снова.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    creds = await get_credentials_for_user(chat_id)
    if not creds:
        await bot.edit_message_text(
            "⚠️ Токен Google истёк. Отправьте /reconnect.",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
        return

    result = await delete_event(creds, state.event_id)
    clear_state(chat_id)

    if result.success:
        await bot.edit_message_text(
            f"🗑 Удалено: <b>{escape(result.title)}</b>",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
    else:
        await bot.edit_message_text(
            f"❌ Не удалось удалить:\n{result.error}",
            chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )


# ======================================================================
# Helpers
# ======================================================================

def _make_state(
    flow: str,
    step: str,
    event_id: str = "",
    event_title: str = "",
    **extra,
):
    from app.schemas import FlowState
    return FlowState(
        flow=flow,
        step=step,
        event_id=event_id,
        event_title=event_title,
        **extra,
    )
