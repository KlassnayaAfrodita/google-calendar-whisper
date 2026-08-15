"""Тесты валидации дат, времени, RRULE и конфликтов."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.calendar.service import valid_date, valid_time
from app.calendar.conflicts import find_conflicts
from app.schemas import CalendarEvent
from app.utils.date_resolver import resolve_russian_weekday_date


class TestDateValidation:
    """Тесты валидации дат и времени."""

    def test_valid_date(self):
        assert valid_date("2026-07-04") is True

    def test_valid_date_with_padding(self):
        assert valid_date("2026-01-01") is True

    def test_invalid_date_no_year(self):
        assert valid_date("07-04") is False

    def test_invalid_date_empty(self):
        assert valid_date("") is False

    def test_invalid_date_text(self):
        assert valid_date("tomorrow") is False

    def test_invalid_date_with_time(self):
        assert valid_date("2026-07-04T10:00:00") is False

    def test_valid_time(self):
        assert valid_time("09:00") is True

    def test_valid_time_single_digit(self):
        assert valid_time("9:30") is True

    def test_valid_time_full(self):
        assert valid_time("23:59") is True

    def test_invalid_time_empty(self):
        assert valid_time("") is False

    def test_invalid_time_with_seconds(self):
        assert valid_time("09:00:30") is False

    def test_invalid_time_text(self):
        assert valid_time("morning") is False

    def test_invalid_time_no_minutes(self):
        assert valid_time("9") is False


class TestRruleParsing:
    """Базовые проверки формата RRULE."""

    def test_rrule_weekly(self):
        rule = "RRULE:FREQ=WEEKLY;BYDAY=MO"
        assert rule.startswith("RRULE:")
        assert "FREQ=WEEKLY" in rule

    def test_rrule_weekdays(self):
        rule = "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
        assert "MO,TU,WE,TH,FR" in rule

    def test_rrule_with_count(self):
        rule = "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4"
        assert "COUNT=4" in rule

    def test_rrule_with_until(self):
        rule = "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20260630T235959Z"
        assert "UNTIL=20260630T235959Z" in rule


class TestRussianWeekdayDateResolver:
    """Regression tests for Russian weekday phrases."""

    def test_nearest_thursday_from_saturday(self):
        now = datetime(2026, 8, 15, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        text = "Поставь встречу на ближайший четверг с 12 до 2"

        assert resolve_russian_weekday_date(text, now) == "2026-08-20"

    def test_plain_thursday_from_saturday(self):
        now = datetime(2026, 8, 15, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        text = "Поздравить Наташу в четверг"

        assert resolve_russian_weekday_date(text, now) == "2026-08-20"

    def test_next_thursday_on_thursday_means_next_week(self):
        now = datetime(2026, 8, 20, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        text = "Перенеси на следующий четверг"

        assert resolve_russian_weekday_date(text, now) == "2026-08-27"

    def test_no_weekday_returns_none(self):
        now = datetime(2026, 8, 15, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))

        assert resolve_russian_weekday_date("Поставь встречу завтра", now) is None


class TestConflictDetection:
    """Тесты обнаружения пересечений событий."""

    @pytest.mark.asyncio
    async def test_no_conflict_no_events(self):
        """Нет событий — нет конфликтов."""
        event_data = {
            "date": "2026-07-04",
            "start_time": "10:00",
            "end_time": "11:00",
        }

        async def mock_get_events(*args, **kwargs):
            return []

        # Patch get_events to return empty
        import app.calendar.conflicts as conf_mod
        original = conf_mod.get_events
        conf_mod.get_events = mock_get_events

        try:
            conflicts = await find_conflicts(None, event_data, "Europe/Moscow")
            assert conflicts == []
        finally:
            conf_mod.get_events = original

    @pytest.mark.asyncio
    async def test_conflict_detected(self):
        """Пересечение событий обнаруживается."""
        event_data = {
            "date": "2026-07-04",
            "start_time": "09:15",
            "end_time": "09:45",
        }

        # Существующее событие 09:00-09:30 пересекается с 09:15-09:45
        existing = CalendarEvent(
            id="existing001",
            title="Стендап",
            start="2026-07-04T09:00:00+03:00",
            end="2026-07-04T09:30:00+03:00",
            location="Zoom",
        )

        async def mock_get_events(*args, **kwargs):
            return [existing]

        import app.calendar.conflicts as conf_mod
        original = conf_mod.get_events
        conf_mod.get_events = mock_get_events

        try:
            conflicts = await find_conflicts(None, event_data, "Europe/Moscow")
            assert len(conflicts) == 1
            assert conflicts[0].id == "existing001"
        finally:
            conf_mod.get_events = original

    @pytest.mark.asyncio
    async def test_no_conflict_separate_times(self):
        """События в разное время — нет конфликта."""
        event_data = {
            "date": "2026-07-04",
            "start_time": "14:00",
            "end_time": "15:00",
        }

        existing = CalendarEvent(
            id="existing002",
            title="Стендап",
            start="2026-07-04T09:00:00+03:00",
            end="2026-07-04T09:30:00+03:00",
            location="Zoom",
        )

        async def mock_get_events(*args, **kwargs):
            return [existing]

        import app.calendar.conflicts as conf_mod
        original = conf_mod.get_events
        conf_mod.get_events = mock_get_events

        try:
            conflicts = await find_conflicts(None, event_data, "Europe/Moscow")
            assert conflicts == []
        finally:
            conf_mod.get_events = original

    @pytest.mark.asyncio
    async def test_all_day_events_skipped(self):
        """All-day события (без времени) пропускаются при проверке конфликтов."""
        event_data = {
            "date": "2026-07-04",
            "start_time": "10:00",
            "end_time": "11:00",
        }

        # All-day: start без времени (<=10 символов)
        all_day = CalendarEvent(
            id="allday001",
            title="Выходной",
            start="2026-07-04",
            end="2026-07-05",
            location="",
        )

        async def mock_get_events(*args, **kwargs):
            return [all_day]

        import app.calendar.conflicts as conf_mod
        original = conf_mod.get_events
        conf_mod.get_events = mock_get_events

        try:
            conflicts = await find_conflicts(None, event_data, "Europe/Moscow")
            assert conflicts == []
        finally:
            conf_mod.get_events = original

    @pytest.mark.asyncio
    async def test_invalid_date_returns_empty(self):
        """Невалидная дата — пустой результат."""
        event_data = {
            "date": "tomorrow",
            "start_time": "10:00",
        }

        conflicts = await find_conflicts(None, event_data, "Europe/Moscow")
        assert conflicts == []

    @pytest.mark.asyncio
    async def test_no_start_time_returns_empty(self):
        """Нет start_time — пустой результат (all-day не проверяется)."""
        event_data = {
            "date": "2026-07-04",
            "start_time": "",
        }

        conflicts = await find_conflicts(None, event_data, "Europe/Moscow")
        assert conflicts == []
