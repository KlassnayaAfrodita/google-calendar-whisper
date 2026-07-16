"""Тесты парсинга ответов LLM — валидация EventDetails и DateTimeChange."""

from __future__ import annotations

import pytest

from app.schemas import DateTimeChange, EventDetails


class TestEventDetails:
    """Валидация схем LLM output."""

    def test_valid_create_event(self):
        """Корректный create_event парсится без ошибок."""
        data = {
            "intent": "create_event",
            "message": "",
            "title": "Встреча",
            "date": "2026-07-07",
            "start_time": "10:00",
            "end_time": "11:00",
            "location": "Офис",
            "description": "Обсуждение проекта",
            "recurrence": "",
            "target_event_id": "",
            "new_title": "",
            "new_date": "",
            "new_start_time": "",
            "new_end_time": "",
            "new_location": "",
        }
        event = EventDetails.model_validate(data)
        assert event.intent == "create_event"
        assert event.title == "Встреча"
        assert event.date == "2026-07-07"
        assert event.start_time == "10:00"
        assert event.end_time == "11:00"
        assert event.location == "Офис"

    def test_valid_update_event(self):
        """Корректный update_event с target_event_id."""
        data = {
            "intent": "update_event",
            "message": "",
            "title": "",
            "date": "",
            "start_time": "",
            "end_time": "",
            "location": "",
            "description": "",
            "recurrence": "",
            "target_event_id": "evt001",
            "new_title": "Новое название",
            "new_date": "2026-07-08",
            "new_start_time": "14:00",
            "new_end_time": "",
            "new_location": "",
        }
        event = EventDetails.model_validate(data)
        assert event.intent == "update_event"
        assert event.target_event_id == "evt001"
        assert event.new_title == "Новое название"
        assert event.new_date == "2026-07-08"

    def test_valid_delete_event(self):
        """Корректный delete_event."""
        data = {
            "intent": "delete_event",
            "message": "",
            "target_event_id": "evt002",
        }
        event = EventDetails.model_validate(data)
        assert event.intent == "delete_event"
        assert event.target_event_id == "evt002"

    def test_unknown_intent(self):
        """unknown intent."""
        data = {
            "intent": "unknown",
            "message": "Не найдено подходящих событий.",
        }
        event = EventDetails.model_validate(data)
        assert event.intent == "unknown"
        assert event.message == "Не найдено подходящих событий."

    def test_all_day_event(self):
        """All-day event — без start_time/end_time."""
        data = {
            "intent": "create_event",
            "title": "День рождения",
            "date": "2026-08-15",
            "start_time": "",
            "end_time": "",
        }
        event = EventDetails.model_validate(data)
        assert event.intent == "create_event"
        assert event.date == "2026-08-15"
        assert event.start_time == ""
        assert event.end_time == ""

    def test_recurring_event(self):
        """Recurring event с RRULE."""
        data = {
            "intent": "create_event",
            "title": "Еженедельный стендап",
            "date": "2026-07-06",
            "start_time": "09:00",
            "end_time": "09:30",
            "recurrence": "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
        }
        event = EventDetails.model_validate(data)
        assert event.recurrence == "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"

    def test_minimal_json(self):
        """Минимальный JSON — только intent."""
        data = {"intent": "unknown", "message": ""}
        event = EventDetails.model_validate(data)
        assert event.intent == "unknown"

    def test_defaults(self):
        """Проверка значений по умолчанию."""
        event = EventDetails()
        assert event.intent == "unknown"
        assert event.title == ""
        assert event.date == ""
        assert event.recurrence == ""
        assert event.target_event_id == ""


class TestDateTimeChange:
    """Валидация DateTimeChange."""

    def test_full_change(self):
        data = {"new_date": "2026-07-10", "new_start_time": "15:00", "new_end_time": "16:30"}
        change = DateTimeChange.model_validate(data)
        assert change.new_date == "2026-07-10"
        assert change.new_start_time == "15:00"
        assert change.new_end_time == "16:30"

    def test_partial_change_time_only(self):
        data = {"new_date": "", "new_start_time": "14:00", "new_end_time": ""}
        change = DateTimeChange.model_validate(data)
        assert change.new_date == ""
        assert change.new_start_time == "14:00"

    def test_empty_change(self):
        data = {"new_date": "", "new_start_time": "", "new_end_time": ""}
        change = DateTimeChange.model_validate(data)
        assert change.new_date == ""
        assert change.new_start_time == ""
        assert change.new_end_time == ""

    def test_from_to_format(self):
        """from X to Y → new_start + new_end."""
        data = {"new_date": "", "new_start_time": "10:00", "new_end_time": "12:00"}
        change = DateTimeChange.model_validate(data)
        assert change.new_start_time == "10:00"
        assert change.new_end_time == "12:00"
