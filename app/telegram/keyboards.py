"""Фабрики inline-клавиатур для Telegram.

Все callback_data соответствуют PHP-оригиналу из telegram_webhook.php.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def confirm_create_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения создания события."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data="create_confirm"),
            InlineKeyboardButton("❌ Отменить", callback_data="create_cancel"),
        ]
    ])


def confirm_create_conflict_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура при конфликте — «создать trotzdem»."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Создать всё равно", callback_data="create_confirm"),
            InlineKeyboardButton("❌ Отменить", callback_data="create_cancel"),
        ]
    ])


def skip_location_keyboard() -> InlineKeyboardMarkup:
    """Кнопка «Пропустить» для поля «Где?»."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустить", callback_data="create_skip_loc")]
    ])


def update_field_keyboard() -> InlineKeyboardMarkup:
    """Выбор поля для редактирования."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Дата/Время", callback_data="u_field:datetime"),
            InlineKeyboardButton("📝 Название", callback_data="u_field:title"),
            InlineKeyboardButton("📍 Место", callback_data="u_field:location"),
        ]
    ])


def delete_confirm_keyboard(event_id: str) -> InlineKeyboardMarkup:
    """Подтверждение удаления."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"qa_delyes:{event_id}"),
            InlineKeyboardButton("❌ Нет", callback_data="qa_delno"),
        ]
    ])


def pick_events_keyboard(
    events: list[dict],
    prefix: str,
) -> InlineKeyboardMarkup:
    """Клавиатура выбора события из списка.

    Args:
        events: Список dicts с ключами title, when_label.
        prefix: Префикс callback_data ('u_pick:' или 'd_pick:').
    """
    rows = []
    for i, event in enumerate(events):
        label = event.get("label", str(i))
        rows.append([InlineKeyboardButton(label, callback_data=f"{prefix}{i}")])

    return InlineKeyboardMarkup(rows)


def quick_actions_keyboard(event_id: str) -> InlineKeyboardMarkup | None:
    """Кнопки быстрых действий после создания события.

    Аналог PHP quickActions().
    """
    if not event_id or len(f"qa_delyes:{event_id}") > 64:
        return None

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"qa_edit:{event_id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"qa_del:{event_id}"),
        ]
    ])
