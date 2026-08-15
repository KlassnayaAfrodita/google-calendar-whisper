"""Pydantic схемы — для валидации данных и структурированного вывода LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# LLM вывод
# ---------------------------------------------------------------------------

class EventDetails(BaseModel):
    """Структурированный результат разбора команды через LLM.
    Поля соответствуют JSON-схеме из промпта extractEventDetails().
    """

    intent: str = Field(
        default="unknown",
        description="create_event | update_event | delete_event | unknown",
    )
    message: str = Field(
        default="",
        description="Текст ответа при unknown intent",
    )

    # Поля для create
    title: str = Field(default="")
    date: str = Field(default="", description="YYYY-MM-DD")
    start_time: str = Field(default="", description="HH:MM (24h)")
    end_time: str = Field(default="", description="HH:MM (24h)")
    location: str = Field(default="")
    description: str = Field(default="")
    recurrence: str = Field(default="", description="RRULE:...")

    # Поля для update / delete
    target_event_id: str = Field(default="")

    # Новые значения для update
    new_title: str = Field(default="")
    new_date: str = Field(default="")
    new_start_time: str = Field(default="")
    new_end_time: str = Field(default="")
    new_location: str = Field(default="")


class DateTimeChange(BaseModel):
    """Результат parseDateTimeChange() — частичное обновление даты/времени."""

    new_date: str = Field(default="")
    new_start_time: str = Field(default="")
    new_end_time: str = Field(default="")


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------

class CalendarEvent(BaseModel):
    """Представление события Google Calendar."""

    id: str
    title: str
    start: str  # ISO datetime или date string
    end: str
    location: str = ""
    calendar_id: str = ""
    calendar_name: str = ""


class CreateResult(BaseModel):
    """Результат создания события в Google Calendar."""

    success: bool
    id: str = ""
    html_link: str = ""
    title: str = ""
    when: str = ""
    recurring: bool = False
    error: str = ""


class UpdateResult(BaseModel):
    """Результат обновления события."""

    success: bool
    title: str = ""
    start: str = ""
    html_link: str = ""
    error: str = ""


class DeleteResult(BaseModel):
    """Результат удаления события."""

    success: bool
    title: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Транскрипция
# ---------------------------------------------------------------------------

class TranscriptionResult(BaseModel):
    """Результат транскрипции голосового сообщения."""

    success: bool
    text: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Guided flow state
# ---------------------------------------------------------------------------

class FlowState(BaseModel):
    """Конверсационный state для guided-флоу (/create, /update, /delete)."""

    flow: str = ""  # "create" | "update" | "delete"
    step: str = ""  # "title" | "when" | "location" | "confirm" | "pick" | "field" | "value"
    data: dict = Field(default_factory=dict)
    event: dict | None = None
    events: list[dict] = Field(default_factory=list)
    event_id: str = ""
    event_title: str = ""
    field: str = ""
