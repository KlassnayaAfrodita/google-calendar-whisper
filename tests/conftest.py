"""Общие фикстуры для тестов."""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock

import pytest


# Конфигурация-заглушка должна быть установлена до импорта модулей app во время
# collection. В production значения всегда приходят из панели Bothost.
os.environ.setdefault("BOT_TOKEN", "123456789:test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "https://example.test/oauth/callback")


@pytest.fixture()
def event_loop():
    """Создать event loop для async тестов."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def sample_calendar_events() -> list[dict[str, Any]]:
    """Пример списка событий для тестов."""
    return [
        {
            "id": "evt001",
            "title": "Стендап",
            "start": "2026-07-04T09:00:00",
            "end": "2026-07-04T09:30:00",
            "location": "Zoom",
        },
        {
            "id": "evt002",
            "title": "Обед с командой",
            "start": "2026-07-04T12:00:00",
            "end": "2026-07-04T13:00:00",
            "location": "Кафе",
        },
        {
            "id": "evt003",
            "title": "Встреча по проекту",
            "start": "2026-07-06T15:00:00",
            "end": "2026-07-06T16:00:00",
            "location": "",
        },
    ]


@pytest.fixture()
def mock_openai_response() -> dict[str, Any]:
    """Моковый ответ OpenAI для extract_event_details."""
    return {
        "intent": "create_event",
        "message": "",
        "title": "Встреча с Иваном",
        "date": "2026-07-07",
        "start_time": "10:00",
        "end_time": "11:00",
        "location": "Офис",
        "description": "",
        "recurrence": "",
        "target_event_id": "",
        "new_title": "",
        "new_date": "",
        "new_start_time": "",
        "new_end_time": "",
        "new_location": "",
    }
