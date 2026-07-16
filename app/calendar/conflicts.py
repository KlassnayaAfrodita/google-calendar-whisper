"""Детекция конфликтов при создании событий.

Переносит логику из PHP google_calendar.php: findConflicts().
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from google.auth.credentials import Credentials

from app.calendar.service import get_events, valid_date, valid_time
from app.schemas import CalendarEvent


async def find_conflicts(
    credentials: Credentials,
    event_data: dict[str, Any],
    timezone: str = "Europe/Moscow",
) -> list[CalendarEvent]:
    """Найти события, пересекающиеся с создаваемым.

    Проверяет только timed-события (all-day пропускаются).
    Аналог PHP findConflicts().

    Args:
        credentials: Google Credentials.
        event_data: Словарь с полями date, start_time, end_time.
        timezone: Часовой пояс пользователя.

    Returns:
        Список конфликтующих событий.
    """
    date = event_data.get("date", "")
    start_time = event_data.get("start_time", "")
    end_time = event_data.get("end_time", "")

    if not valid_date(date) or not valid_time(start_time):
        return []

    tz = ZoneInfo(timezone)

    try:
        start_dt = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError:
        return []

    if valid_time(end_time):
        try:
            end_dt = datetime.strptime(f"{date} {end_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        except ValueError:
            end_dt = start_dt + timedelta(minutes=60)
    else:
        end_dt = start_dt + timedelta(minutes=60)

    # Границы дня для запроса
    day_start = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = start_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    all_events = await get_events(
        credentials,
        day_start.isoformat(),
        day_end.isoformat(),
    )

    conflicts: list[CalendarEvent] = []
    for event in all_events:
        # Пропускаем all-day события (start без времени)
        if len(event.start) <= 10:
            continue

        try:
            ev_start = datetime.fromisoformat(event.start)
            ev_end = datetime.fromisoformat(event.end)
        except (ValueError, TypeError):
            continue

        # Проверка пересечения интервалов
        if start_dt < ev_end and end_dt > ev_start:
            conflicts.append(event)

    return conflicts
