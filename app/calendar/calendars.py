"""Persist and select Google calendars for a connected user."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Literal

from google.auth.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy import select

from app.config import settings
from app.db.session import async_session_factory
from app.models import GoogleCalendar, User

logger = logging.getLogger(__name__)

CalendarPurpose = Literal["reminders", "conflicts", "context"]


def _list_google_calendars_sync(credentials: Credentials) -> list[dict[str, Any]]:
    service = build("calendar", "v3", credentials=credentials)
    calendars: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        result = service.calendarList().list(pageToken=page_token).execute()
        calendars.extend(result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return calendars


async def sync_google_calendars(user_id: int, credentials: Credentials) -> int:
    """Refresh the user's visible Google calendars in the local database."""
    items = await asyncio.to_thread(_list_google_calendars_sync, credentials)
    now = datetime.utcnow()

    async with async_session_factory() as session:
        result = await session.execute(
            select(GoogleCalendar).where(GoogleCalendar.user_id == user_id)
        )
        existing = {row.calendar_id: row for row in result.scalars().all()}
        seen: set[str] = set()

        for item in items:
            calendar_id = item.get("id")
            if not calendar_id:
                continue

            seen.add(calendar_id)
            row = existing.get(calendar_id)
            if row is None:
                row = GoogleCalendar(
                    user_id=user_id,
                    calendar_id=calendar_id,
                    selected_for_reminders=not item.get("hidden", False),
                    selected_for_conflicts=not item.get("hidden", False),
                    selected_for_context=not item.get("hidden", False),
                )
                session.add(row)

            row.summary = item.get("summary") or calendar_id
            row.access_role = item.get("accessRole") or ""
            row.is_primary = bool(item.get("primary"))
            row.is_hidden = bool(item.get("hidden"))
            row.is_deleted = bool(item.get("deleted"))
            row.synced_at = now

        for calendar_id, row in existing.items():
            if calendar_id not in seen:
                row.is_deleted = True
                row.synced_at = now

        await session.commit()

    logger.info("Synced %s Google calendars for user_id=%s", len(seen), user_id)
    return len(seen)


async def resolve_internal_user_id(user_id_or_chat_id: int) -> int | None:
    """Accept either internal user id or Telegram chat id and return internal user id."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(User.id).where(User.id == user_id_or_chat_id)
        )
        user_id = result.scalar_one_or_none()
        if user_id is not None:
            return user_id

        result = await session.execute(
            select(User.id).where(User.telegram_chat_id == user_id_or_chat_id)
        )
        return result.scalar_one_or_none()


async def get_selected_calendar_ids(
    user_id_or_chat_id: int | None,
    purpose: CalendarPurpose,
) -> list[str]:
    """Return calendar ids enabled for the requested purpose."""
    calendar_map = await get_selected_calendar_map(user_id_or_chat_id, purpose)
    return list(calendar_map.keys())


async def get_selected_calendar_map(
    user_id_or_chat_id: int | None,
    purpose: CalendarPurpose,
) -> dict[str, str]:
    """Return enabled calendar ids mapped to their display names."""
    if user_id_or_chat_id is None:
        return {settings.google_calendar_id: settings.google_calendar_id}

    user_id = await resolve_internal_user_id(user_id_or_chat_id)
    if user_id is None:
        return {settings.google_calendar_id: settings.google_calendar_id}

    column = {
        "reminders": GoogleCalendar.selected_for_reminders,
        "conflicts": GoogleCalendar.selected_for_conflicts,
        "context": GoogleCalendar.selected_for_context,
    }[purpose]

    async with async_session_factory() as session:
        result = await session.execute(
            select(GoogleCalendar.calendar_id, GoogleCalendar.summary)
            .where(GoogleCalendar.user_id == user_id)
            .where(GoogleCalendar.is_deleted == False)  # noqa: E712
            .where(GoogleCalendar.is_hidden == False)  # noqa: E712
            .where(column == True)  # noqa: E712
        )
        rows = result.all()

    calendar_map = {
        calendar_id: summary or calendar_id
        for calendar_id, summary in rows
    }
    if settings.google_calendar_id not in calendar_map:
        calendar_map = {
            settings.google_calendar_id: settings.google_calendar_id,
            **calendar_map,
        }
    return calendar_map


async def list_saved_calendars(user_id_or_chat_id: int) -> list[GoogleCalendar]:
    user_id = await resolve_internal_user_id(user_id_or_chat_id)
    if user_id is None:
        return []

    async with async_session_factory() as session:
        result = await session.execute(
            select(GoogleCalendar)
            .where(GoogleCalendar.user_id == user_id)
            .order_by(GoogleCalendar.is_primary.desc(), GoogleCalendar.summary)
        )
        return list(result.scalars().all())
