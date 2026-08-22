"""Тесты Google Calendar service (mocked Google API)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.calendar.service import (
    create_event,
    delete_event,
    filter_events_for_day,
    get_event_title,
    get_events,
    get_upcoming_events,
    update_event,
    valid_date,
    valid_time,
)
from app.schemas import CalendarEvent, CreateResult, DeleteResult, UpdateResult


def _mock_credentials():
    """Создать моковые Google Credentials."""
    creds = MagicMock()
    creds.token = "mock_access_token"
    creds.refresh_token = "mock_refresh_token"
    creds.expiry = datetime.utcnow().timestamp() + 3600
    creds.token_uri = "https://oauth2.googleapis.com/token"
    creds.client_id = "mock_client_id"
    creds.client_secret = "mock_secret"
    return creds


@pytest.fixture()
def mock_google_service():
    """Мок Google Calendar API service."""
    service_mock = MagicMock()

    events_mock = MagicMock()
    service_mock.events.return_value = events_mock

    insert_mock = MagicMock()
    insert_mock.execute.return_value = {
        "id": "new_evt_001",
        "summary": "Тестовая встреча",
        "htmlLink": "https://calendar.google.com/event?id=new_evt_001",
    }
    events_mock.insert.return_value = insert_mock

    get_mock = MagicMock()
    get_mock.execute.return_value = {
        "id": "evt001",
        "summary": "Стендап",
        "start": {"dateTime": "2026-07-04T09:00:00", "timeZone": "Europe/Moscow"},
        "end": {"dateTime": "2026-07-04T09:30:00", "timeZone": "Europe/Moscow"},
    }
    events_mock.get.return_value = get_mock

    update_mock = MagicMock()
    update_mock.execute.return_value = {
        "id": "evt001",
        "summary": "Обновлённый стендап",
        "htmlLink": "https://calendar.google.com/event?id=evt001",
    }
    events_mock.update.return_value = update_mock

    delete_mock = MagicMock()
    delete_mock.execute.return_value = None
    events_mock.delete.return_value = delete_mock

    list_mock = MagicMock()
    list_mock.execute.return_value = {
        "items": [
            {
                "id": "evt001",
                "summary": "Стендап",
                "start": {"dateTime": "2026-07-04T09:00:00"},
                "end": {"dateTime": "2026-07-04T09:30:00"},
                "location": "Zoom",
            },
        ]
    }
    events_mock.list.return_value = list_mock

    return service_mock


class TestCreateEvent:
    @pytest.mark.asyncio
    @patch("app.calendar.service._get_service")
    async def test_create_timed_event(self, mock_build, mock_google_service):
        """Создание timed-события."""
        mock_build.return_value = mock_google_service

        event_data = {
            "title": "Встреча",
            "date": "2026-07-07",
            "start_time": "10:00",
            "end_time": "11:00",
            "location": "Офис",
        }

        result = await create_event(_mock_credentials(), event_data)

        assert result.success is True
        assert result.id == "new_evt_001"
        assert result.title == "Тестовая встреча"

        # Проверяем что insert был вызван
        mock_google_service.events().insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_invalid_date(self):
        """Невалидная дата — ошибка."""
        event_data = {
            "title": "Встреча",
            "date": "tomorrow",
            "start_time": "10:00",
        }

        result = await create_event(_mock_credentials(), event_data)
        assert result.success is False
        assert "дату" in result.error

    @pytest.mark.asyncio
    @patch("app.calendar.service._get_service")
    async def test_create_all_day_event(self, mock_build, mock_google_service):
        """Создание all-day события."""
        mock_build.return_value = mock_google_service

        event_data = {
            "title": "Выходной",
            "date": "2026-08-15",
            "start_time": "",
            "end_time": "",
        }

        result = await create_event(_mock_credentials(), event_data)
        assert result.success is True

        # Проверяем payload
        call_args = mock_google_service.events().insert.call_args
        body = call_args.kwargs["body"] if call_args.kwargs else call_args[1].get("body", {})
        assert "date" in body["start"]
        assert "dateTime" not in body["start"]

    @pytest.mark.asyncio
    @patch("app.calendar.service._get_service")
    async def test_create_with_recurrence(self, mock_build, mock_google_service):
        """Создание recurring-события."""
        mock_build.return_value = mock_google_service

        event_data = {
            "title": "Стендап",
            "date": "2026-07-06",
            "start_time": "09:00",
            "end_time": "09:30",
            "recurrence": "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
        }

        result = await create_event(_mock_credentials(), event_data)
        assert result.success is True
        assert result.recurring is True


class TestUpdateEvent:
    @pytest.mark.asyncio
    @patch("app.calendar.service._get_service")
    async def test_update_title(self, mock_build, mock_google_service):
        """Обновление названия события."""
        mock_build.return_value = mock_google_service

        changes = {"new_title": "Новое название"}

        result = await update_event(_mock_credentials(), "evt001", changes)
        assert result.success is True
        assert result.title == "Обновлённый стендап"

    @pytest.mark.asyncio
    async def test_update_empty_id(self):
        """Пустой ID — ошибка."""
        result = await update_event(_mock_credentials(), "", {})
        assert result.success is False
        assert "не найден" in result.error


class TestDeleteEvent:
    @pytest.mark.asyncio
    @patch("app.calendar.service._get_service")
    async def test_delete_event(self, mock_build, mock_google_service):
        """Удаление события."""
        mock_build.return_value = mock_google_service

        result = await delete_event(_mock_credentials(), "evt001")
        assert result.success is True
        assert result.title == "Стендап"

    @pytest.mark.asyncio
    async def test_delete_empty_id(self):
        """Пустой ID — ошибка."""
        result = await delete_event(_mock_credentials(), "")
        assert result.success is False


class TestGetEvents:
    @pytest.mark.asyncio
    @patch("app.calendar.service._get_service")
    async def test_get_events(self, mock_build, mock_google_service):
        """Получение списка событий."""
        mock_build.return_value = mock_google_service

        now = datetime.utcnow()
        events = await get_events(
            _mock_credentials(),
            now.isoformat() + "Z",
            (now + timedelta(days=7)).isoformat() + "Z",
        )

        assert len(events) == 1
        assert events[0].id == "evt001"
        assert events[0].title == "Стендап"


class TestFilterEventsForDay:
    def test_previous_all_day_event_is_not_repeated(self):
        events = [
            CalendarEvent(
                id="birthday",
                title="День рождения Ольги",
                start="2026-08-20",
                end="2026-08-21",
            )
        ]

        result = filter_events_for_day(
            events, date(2026, 8, 21), "Europe/Volgograd"
        )

        assert result == []

    def test_all_day_event_is_included_on_its_start_day(self):
        event = CalendarEvent(
            id="birthday",
            title="День рождения Ольги",
            start="2026-08-20",
            end="2026-08-21",
        )

        result = filter_events_for_day(
            [event], date(2026, 8, 20), "Europe/Volgograd"
        )

        assert result == [event]


class TestGetEventTitle:
    @pytest.mark.asyncio
    @patch("app.calendar.service._get_service")
    async def test_get_event_title(self, mock_build, mock_google_service):
        """Получение заголовка события."""
        mock_build.return_value = mock_google_service

        title = await get_event_title(_mock_credentials(), "evt001")
        assert title == "Стендап"

    @pytest.mark.asyncio
    @patch("app.calendar.service._get_service")
    async def test_get_event_title_error(self, mock_build):
        """Ошибка при получении заголовка."""
        mock_build.side_effect = Exception("API error")

        title = await get_event_title(_mock_credentials(), "nonexistent")
        assert title == ""
