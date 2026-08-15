"""Форматирование дат, событий и текстов для Telegram.

Переносит HTML-форматирование из PHP telegram_webhook.php:
- helpText()
- fmtEventLine()
- conflictText()
- sendAgenda() (форматирование списка)
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.schemas import CalendarEvent


def escape(text: str) -> str:
    """HTML-экранирование для Telegram."""
    return html.escape(str(text))


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

def help_text() -> str:
    """Текст справки. Аналог PHP helpText()."""
    return (
        "🤖 <b>Календарь-бот</b>\n"
        "Отправьте /create для пошагового создания, или просто напишите "
        "или запишите голосовое сообщение:\n\n"
        "• Создать встречу с Иваном в понедельник в 10:00 в офисе\n"
        "• Запланировать стендап каждый будний день в 9:00\n"
        "• Синхронизация каждый понедельник в июне с 10:00 до 12:00\n"
        "• Перенести понедельничную встречу на среду\n"
        "• Переименовать понедельничную встречу в 10:00 на «Обзор дизайна»\n"
        "• Отменить встречу во вторник в 15:00\n\n"
        "Я предупрежу, если новое событие пересекается с существующим.\n\n"
        "<b>Команды</b>\n"
        "/create — пошаговое создание события\n"
        "/update — изменить существующее событие\n"
        "/delete — удалить событие\n"
        "/today — расписание на сегодня\n"
        "/week — расписание на 7 дней\n"
        "/calendars — обновить список календарей Google\n"
        "/cancel — отменить текущий флоу\n"
        "/help — показать справку"
    )


# ---------------------------------------------------------------------------
# Форматирование одной строки события
# ---------------------------------------------------------------------------

def fmt_event_line(event: CalendarEvent, tz: ZoneInfo) -> str:
    """Отформатировать одну строку события для списка.

    Аналог PHP fmtEventLine().
    """
    try:
        start_dt = datetime.fromisoformat(event.start)
        if len(event.start) > 10:  # timed event
            end_dt = datetime.fromisoformat(event.end)
            s = start_dt.astimezone(tz).strftime("%H:%M")
            e = end_dt.astimezone(tz).strftime("%H:%M")
            time_str = f"{s} – {e}"
        else:
            time_str = "Весь день"
    except (ValueError, TypeError):
        time_str = "?"

    loc = f"  📍 {escape(event.location)}" if event.location else ""
    return f"🕒 {time_str}  <b>{escape(event.title)}</b>{loc}"


# ---------------------------------------------------------------------------
# Форматирование конфликтов
# ---------------------------------------------------------------------------

def conflict_text(conflicts: list[CalendarEvent], tz: ZoneInfo) -> str:
    """Отформатировать список конфликтов.

    Аналог PHP conflictText().
    """
    lines: list[str] = []
    for event in conflicts:
        try:
            s = datetime.fromisoformat(event.start).astimezone(tz).strftime("%H:%M")
            lines.append(f"• {escape(event.title)} ({s})")
        except (ValueError, TypeError):
            lines.append(f"• {escape(event.title)}")
    return "⚠️ <b>Пересекается с:</b>\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Форматирование when (дата/время) для превью
# ---------------------------------------------------------------------------

def format_when(event_data: dict, timezone: str) -> str:
    """Отформатировать дату и время для превью события."""
    tz = ZoneInfo(timezone)
    from app.calendar.service import valid_time

    if valid_time(event_data.get("start_time", "")):
        try:
            dt = datetime.strptime(
                f"{event_data['date']} {event_data['start_time']}",
                "%Y-%m-%d %H:%M",
            ).replace(tzinfo=tz)
            return dt.strftime("%a %d %b, %H:%M")
        except ValueError:
            pass

    try:
        dt = datetime.strptime(event_data["date"], "%Y-%m-%d").date()
        return dt.strftime("%a %d %b") + " (весь день)"
    except (ValueError, KeyError):
        return event_data.get("date", "?")


# ---------------------------------------------------------------------------
# Форматирование повестки дня
# ---------------------------------------------------------------------------

def format_agenda(
    events: list[CalendarEvent],
    scope: str,
    timezone: str,
) -> str:
    """Отформатировать повестку дня (today/week).

    Аналог PHP sendAgenda() — формирует текст сообщения.
    """
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)

    if scope == "today":
        header = f"📅 <b>Сегодня</b> — {now.strftime('%a %d %b')}"
        if not events:
            return header + "\n\nНичего не запланировано. 🎉"

        msg = header + "\n"
        for event in events:
            msg += "\n" + fmt_event_line(event, tz)
        return msg

    # week
    header = "📅 <b>Ближайшие 7 дней</b>"
    if not events:
        return header + "\n\nНичего не запланировано. 🎉"

    # Группируем по дням
    by_day: dict[str, list[CalendarEvent]] = {}
    for event in events:
        day = event.start[:10]  # YYYY-MM-DD
        by_day.setdefault(day, []).append(event)

    msg = header + "\n"
    for day, day_events in by_day.items():
        try:
            day_dt = datetime.strptime(day, "%Y-%m-%d").date()
            msg += f"\n<b>{day_dt.strftime('%a %d %b')}</b>\n"
        except ValueError:
            msg += f"\n<b>{day}</b>\n"
        for event in day_events:
            msg += fmt_event_line(event, tz) + "\n"

    return msg.rstrip()


# ---------------------------------------------------------------------------
# Ежедневное уведомление
# ---------------------------------------------------------------------------

def format_daily_reminder(events: list[CalendarEvent], timezone: str) -> str:
    """Отформатировать ежедневное утреннее уведомление."""
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    date_str = now.strftime("%d.%m.%Y")

    header = f"☀️ <b>Доброе утро!</b>\n📅 {date_str}\n\nРасписание на сегодня:"

    if not events:
        return header + "\n\nНичего не запланировано. 🎉"

    lines: list[str] = [header]
    for event in events:
        lines.append(fmt_event_line(event, tz))

    return "\n".join(lines)
