"""Tests for Telegram text formatting."""

from __future__ import annotations

from app.schemas import CalendarEvent
from app.utils.formatters import format_daily_reminder


def test_daily_reminder_groups_events_by_calendar():
    events = [
        CalendarEvent(
            id="work",
            title="Work meeting",
            start="2026-08-15T10:00:00+03:00",
            end="2026-08-15T11:00:00+03:00",
            calendar_id="work@example.com",
            calendar_name="Work",
        ),
        CalendarEvent(
            id="birthdays",
            title="Birthday",
            start="2026-08-15",
            end="2026-08-16",
            calendar_id="birthdays",
            calendar_name="Birthdays",
        ),
    ]

    text = format_daily_reminder(events, "Europe/Moscow")

    assert "<b>Work</b>" in text
    assert "<b>Birthdays</b>" in text
    assert text.index("<b>Work</b>") < text.index("Work meeting")
    assert text.index("<b>Birthdays</b>") < text.index("Birthday")
