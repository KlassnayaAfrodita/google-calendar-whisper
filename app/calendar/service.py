"""Google Calendar CRUD сервис.

Переносит логику из PHP google_calendar.php:
- createGoogleCalendarEvent()
- updateGoogleEventById()
- deleteGoogleEventById()
- getGoogleEventTitle()
- getCalendarEvents()
- getUpcomingEvents()
- validDate(), validTime()

Async (исправление CRITICAL #2):
- Все sync вызовы Google API (.execute()) обёрнуты в asyncio.to_thread,
  чтобы не блокировать event loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from google.auth.credentials import Credentials
from googleapiclient.discovery import build
from app.config import settings
from app.schemas import CalendarEvent, CreateResult, DeleteResult, UpdateResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def valid_date(d: str) -> bool:
    """Проверить формат даты YYYY-MM-DD."""
    return bool(d) and bool(_DATE_RE.match(d))


def valid_time(t: str) -> bool:
    """Проверить формат времени HH:MM."""
    return bool(t) and bool(_TIME_RE.match(t))


# ---------------------------------------------------------------------------
# Вспомогательный: получение Calendar service
# ---------------------------------------------------------------------------

def _get_service(credentials: Credentials):
    """Получить Google Calendar API service."""
    return build("calendar", "v3", credentials=credentials)


# ---------------------------------------------------------------------------
# Sync helpers — выполняются в потоке через asyncio.to_thread
# ---------------------------------------------------------------------------

def _create_event_sync(
    credentials: Credentials,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Синхронное создание события. Выполняется в потоке."""
    service = _get_service(credentials)
    return service.events().insert(
        calendarId=settings.google_calendar_id, body=payload
    ).execute()


def _get_event_sync(
    credentials: Credentials, event_id: str
) -> dict[str, Any] | None:
    """Синхронное получение события. Выполняется в потоке."""
    service = _get_service(credentials)
    try:
        return service.events().get(
            calendarId=settings.google_calendar_id, eventId=event_id
        ).execute()
    except Exception:
        logger.exception("Ошибка получения события из Google Calendar")
        return None


def _update_event_sync(
    credentials: Credentials, event_id: str, body: dict[str, Any]
) -> dict[str, Any] | None:
    """Синхронное обновление события. Выполняется в потоке."""
    service = _get_service(credentials)
    return service.events().update(
        calendarId=settings.google_calendar_id, eventId=event_id, body=body
    ).execute()


def _delete_event_sync(
    credentials: Credentials, event_id: str
) -> None:
    """Синхронное удаление события. Выполняется в потоке."""
    service = _get_service(credentials)
    service.events().delete(
        calendarId=settings.google_calendar_id, eventId=event_id
    ).execute()


def _list_events_sync(
    credentials: Credentials,
    time_min: str,
    time_max: str,
    calendar_id: str | None = None,
) -> dict[str, Any] | None:
    """Синхронный список событий. Выполняется в потоке."""
    service = _get_service(credentials)
    return (
        service.events()
        .list(
            calendarId=calendar_id or settings.google_calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )


# ---------------------------------------------------------------------------
# CRUD (async обёртки)
# ---------------------------------------------------------------------------

async def create_event(
    credentials: Credentials,
    event_data: dict[str, Any],
    timezone: str = "Europe/Moscow",
) -> CreateResult:
    """Создать событие в Google Calendar.

    Аналог PHP createGoogleCalendarEvent().
    """
    if not valid_date(event_data.get("date", "")):
        return CreateResult(success=False, error="Не удалось определить дату. Попробуйте снова.")

    tz = ZoneInfo(timezone)
    all_day = not valid_time(event_data.get("start_time", ""))

    payload: dict[str, Any] = {
        "summary": event_data.get("title") or "(без названия)",
        "location": event_data.get("location", ""),
        "description": event_data.get("description", ""),
    }

    if all_day:
        start = datetime.strptime(event_data["date"], "%Y-%m-%d").date()
        end = start + timedelta(days=1)  # Google end date is exclusive
        payload["start"] = {"date": start.isoformat()}
        payload["end"] = {"date": end.isoformat()}
        when_label = start.strftime("%d %b") + " (весь день)"
    else:
        start_dt = datetime.strptime(
            f"{event_data['date']} {event_data['start_time']}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=tz)
        if valid_time(event_data.get("end_time", "")):
            end_dt = datetime.strptime(
                f"{event_data['date']} {event_data['end_time']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=tz)
        else:
            end_dt = start_dt + timedelta(minutes=60)

        payload["start"] = {
            "dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": timezone,
        }
        payload["end"] = {
            "dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": timezone,
        }
        when_label = (
            start_dt.strftime("%a %d %b, %H:%M")
            + " – "
            + end_dt.strftime("%H:%M")
        )

    recurring = False
    if event_data.get("recurrence"):
        rule = event_data["recurrence"].strip()
        if not rule.upper().startswith("RRULE"):
            rule = "RRULE:" + rule
        payload["recurrence"] = [rule]
        recurring = True

    try:
        created = await asyncio.to_thread(
            _create_event_sync, credentials, payload
        )
        return CreateResult(
            success=True,
            id=created["id"],
            html_link=created.get("htmlLink", ""),
            title=created.get("summary", ""),
            when=when_label,
            recurring=recurring,
        )
    except Exception:
        logger.exception("Ошибка создания события в Google Calendar")
        return CreateResult(success=False, error="Ошибка при создании события в Google Calendar")


async def update_event(
    credentials: Credentials,
    event_id: str,
    changes: dict[str, Any],
    timezone: str = "Europe/Moscow",
) -> UpdateResult:
    """Обновить событие в Google Calendar.

    Аналог PHP updateGoogleEventById().
    """
    if not event_id:
        return UpdateResult(success=False, error="Событие не найдено.")

    try:
        event = await asyncio.to_thread(_get_event_sync, credentials, event_id)
        if event is None:
            return UpdateResult(success=False, error="Событие не найдено.")

        tz = ZoneInfo(timezone)
        old_start_str = event["start"].get("dateTime") or event["start"].get("date")
        old_end_str = event["end"].get("dateTime") or event["end"].get("date")

        old_start = datetime.fromisoformat(old_start_str).astimezone(tz)
        old_end = datetime.fromisoformat(old_end_str).astimezone(tz)
        duration = (old_end - old_start).total_seconds()

        # Определяем новые дату и время
        new_date = changes.get("new_date", "")
        new_start_time = changes.get("new_start_time", "")
        new_end_time = changes.get("new_end_time", "")

        date_str = new_date if valid_date(new_date) else old_start.strftime("%Y-%m-%d")
        time_str = new_start_time if valid_time(new_start_time) else old_start.strftime("%H:%M")

        new_start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)

        if valid_time(new_end_time):
            new_end = datetime.strptime(
                f"{date_str} {new_end_time}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=tz)
        else:
            new_end = new_start + timedelta(seconds=duration)

        # Применяем изменения
        if changes.get("new_title"):
            event["summary"] = changes["new_title"]
        if changes.get("new_location"):
            event["location"] = changes["new_location"]

        event["start"] = {
            "dateTime": new_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": timezone,
        }
        event["end"] = {
            "dateTime": new_end.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": timezone,
        }

        updated = await asyncio.to_thread(
            _update_event_sync, credentials, event_id, event
        )

        return UpdateResult(
            success=True,
            title=updated.get("summary", ""),
            start=new_start.strftime("%a %d %b, %H:%M"),
            html_link=updated.get("htmlLink", ""),
        )
    except Exception:
        logger.exception("Ошибка обновления события в Google Calendar")
        return UpdateResult(success=False, error="Ошибка при обновлении события")


async def delete_event(
    credentials: Credentials,
    event_id: str,
) -> DeleteResult:
    """Удалить событие из Google Calendar.

    Аналог PHP deleteGoogleEventById().
    """
    if not event_id:
        return DeleteResult(success=False, error="Событие не найдено.")

    try:
        event = await asyncio.to_thread(_get_event_sync, credentials, event_id)
        if event is None:
            return DeleteResult(success=False, error="Событие не найдено.")

        title = event.get("summary", "")

        await asyncio.to_thread(_delete_event_sync, credentials, event_id)

        return DeleteResult(success=True, title=title)
    except Exception:
        logger.exception("Ошибка удаления события из Google Calendar")
        return DeleteResult(success=False, error="Ошибка при удалении события")


async def get_event_title(credentials: Credentials, event_id: str) -> str:
    """Получить заголовок события по ID.

    Аналог PHP getGoogleEventTitle().
    """
    try:
        event = await asyncio.to_thread(_get_event_sync, credentials, event_id)
        return event.get("summary") or "" if event else ""
    except Exception:
        logger.exception("Ошибка получения заголовка события")
        return ""


async def get_events(
    credentials: Credentials,
    time_min: str,
    time_max: str,
    user_id: int | None = None,
    calendar_ids: list[str] | None = None,
    purpose: str = "reminders",
) -> list[CalendarEvent]:
    """Получить список событий за период.

    Аналог PHP getCalendarEvents().
    """
    try:
        if calendar_ids is None:
            if user_id is None:
                calendar_map = {settings.google_calendar_id: settings.google_calendar_id}
            else:
                from app.calendar.calendars import get_selected_calendar_map

                calendar_map = await get_selected_calendar_map(user_id, purpose)  # type: ignore[arg-type]
            calendar_ids = list(calendar_map.keys())
        else:
            calendar_map = {calendar_id: calendar_id for calendar_id in calendar_ids}

        events: list[CalendarEvent] = []
        for calendar_id in calendar_ids:
            try:
                result = await asyncio.to_thread(
                    _list_events_sync, credentials, time_min, time_max, calendar_id
                )
            except Exception:
                logger.exception(
                    "Ошибка получения событий из Google Calendar: calendar_id=%s",
                    calendar_id,
                )
                continue

            for item in result.get("items", []):
                start = item["start"].get("dateTime") or item["start"].get("date", "")
                end = item["end"].get("dateTime") or item["end"].get("date", "")
                events.append(
                    CalendarEvent(
                        id=item["id"],
                        title=item.get("summary") or "(без названия)",
                        start=start,
                        end=end,
                        location=item.get("location") or "",
                        calendar_id=calendar_id,
                        calendar_name=calendar_map.get(calendar_id, calendar_id),
                    )
                )
        events.sort(key=lambda event: event.start)
        return events

    except Exception:
        logger.exception("Ошибка получения событий из Google Calendar")
        return []


async def get_upcoming_events(
    credentials: Credentials,
    days: int = 30,
    user_id: int | None = None,
) -> list[CalendarEvent]:
    """Получить предстоящие события (по умолчанию за 30 дней).

    Аналог PHP getUpcomingEvents().
    """
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days)).isoformat()
    return await get_events(credentials, time_min, time_max, user_id=user_id, purpose="context")
