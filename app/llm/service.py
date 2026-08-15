"""LLM-сервис — OpenAI GPT для разбора команд и изменения даты/времени.

Переносит логику из PHP openai.php:
- extractEventDetails() → extract_event_details()
- parseDateTimeChange() → parse_datetime_change()
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from openai import AsyncOpenAI

from app.config import settings
from app.llm.prompts import (
    build_datetime_change_prompt,
    build_event_details_prompt,
)
from app.schemas import CalendarEvent, DateTimeChange, EventDetails
from app.utils.date_resolver import resolve_russian_weekday_date

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    """Ленивый singleton для OpenAI клиента."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def extract_event_details(
    text: str,
    calendar: list[CalendarEvent],
    timezone: str = "Europe/Moscow",
) -> EventDetails | None:
    """Разобрать текстовую команду в структурированные данные события.

    Аналог PHP extractEventDetails() из openai.php:54-159.
    Возвращает None при ошибке LLM.
    """
    client = get_openai_client()

    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    day_name = now.strftime("%A")

    system_prompt = build_event_details_prompt(today, day_name, timezone, calendar)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            timeout=60.0,
        )

        content = response.choices[0].message.content or ""
        data = json.loads(content)
        event = EventDetails.model_validate(data)
        resolved_date = resolve_russian_weekday_date(text, now)
        if resolved_date:
            if event.intent == "create_event":
                event.date = resolved_date
            elif event.intent == "update_event":
                event.new_date = resolved_date
        return event

    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("LLM вернул невалидный JSON: %s", exc)
        return None
    except Exception:
        logger.exception("Ошибка при вызове LLM (extract_event_details)")
        return None


async def parse_datetime_change(
    text: str,
    timezone: str = "Europe/Moscow",
) -> DateTimeChange | None:
    """Извлечь частичные изменения даты/времени из текста.

    Аналог PHP parseDateTimeChange() из openai.php:166-201.
    Используется в guided /update флоу.
    """
    client = get_openai_client()

    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    day_name = now.strftime("%A")

    system_prompt = build_datetime_change_prompt(today, day_name, timezone)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            timeout=60.0,
        )

        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        change = DateTimeChange.model_validate(data)
        resolved_date = resolve_russian_weekday_date(text, now)
        if resolved_date:
            change.new_date = resolved_date
        return change

    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("LLM вернул невалидный JSON (datetime change): %s", exc)
        return None
    except Exception:
        logger.exception("Ошибка при вызове LLM (parse_datetime_change)")
        return None
