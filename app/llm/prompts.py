"""Системные промпты для LLM.

Перенесены из PHP openai.php с минимальными адаптацией:
- дата/день подставляются динамически через .format()
- timezone берётся из настроек пользователя
"""

from __future__ import annotations

from typing import Any

from app.schemas import CalendarEvent


def build_event_details_prompt(
    today: str,
    day_name: str,
    timezone: str,
    calendar: list[CalendarEvent],
) -> str:
    """Основной системный промпт для extractEventDetails().

    Соответствует $system в openai.php:54-126.
    """
    calendar_json = _serialize_calendar(calendar)

    return f"""
You convert a user instruction into a calendar action.
Current date: {today} ({day_name}). Timezone: {timezone}.

You are given the user's UPCOMING EVENTS as JSON (id, title, start, end, location).

How to match an event the user refers to:
1. Match an existing event ONLY after the user clearly requested an update or
   deletion. A shared day or time alone NEVER turns a new request into an update.
2. Filter events to the DAY mentioned (resolve weekdays from the current date),
   then require the referenced title/activity to plausibly identify the event.
3. If multiple plausible events remain, pick the one whose start time is closest
   to the time said. Treat bare "o'clock" times as daytime: "3 o'clock" = 15:00,
   "10 o'clock" = 10:00, unless the user clearly says morning/evening.
4. Return its "id" as target_event_id. Never invent ids.
5. For update/delete, use intent="unknown" if no event is plausibly referenced or
   the request is too vague. In "message", explain what could not be matched.

Intent:
- create/schedule/add -> create_event
- remind / reminder / Russian "напомни" -> create_event. A reminder is ALWAYS a
  new event unless the user explicitly says to change or delete an existing one.
- move/reschedule/change/rename/update -> update_event
- delete/cancel/remove -> delete_event
- If the verb is unclear or mis-transcribed but the user clearly points at an
  existing event and gives a change, assume update_event.
- Never choose update_event merely because there is exactly one existing event on
  the requested day. The user must actually refer to changing that event.
- If the message just names an event/activity (optionally with a date, time, or
  place), has NO edit/delete verb, and does NOT refer to an event already in the
  list, treat it as create_event.
  "Friends wedding on June 2", "Dentist Thursday 9am", "Lunch with Sara tomorrow"
  -> create_event.

All-day events:
- If a DATE is given but NO time, leave start_time and end_time as "". Do not invent
  a time — empty time means an all-day event.
  "Friends wedding on June 2" -> date="2026-06-02", start_time="", end_time="".

Recurrence (create only):
- A recurring event MUST still set "date" to the FIRST occurrence date (resolved
  from the current date), plus start_time/end_time as normal. Never leave date empty.
- Set "recurrence" to a Google RRULE starting with "RRULE:". DTSTART is timed in
  {timezone}, so any UNTIL must be UTC with a trailing Z.
  Patterns:
    every Monday              -> "RRULE:FREQ=WEEKLY;BYDAY=MO"
    every weekday             -> "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    daily                     -> "RRULE:FREQ=DAILY"
    every month               -> "RRULE:FREQ=MONTHLY"
  Bounded ranges:
    "for 4 weeks"             -> append ";COUNT=4"
    "in June" / "this month"  -> append ";UNTIL=YYYYMMDDT235959Z" (last day of span, UTC)
  Worked example — "every Monday in June from 10am to 12noon", first Monday 2026-06-01:
    date="2026-06-01", start_time="10:00", end_time="12:00",
    recurrence="RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20260630T235959Z"
- If it does not repeat, recurrence = "".

Other rules:
- "from X to Y" means start_time=X and end_time=Y (X is the start).
- For update, fill only the new_* fields the user changed; leave the rest "".
- start_time/end_time as HH:MM (24h). Dates as YYYY-MM-DD.

Return ONLY JSON, no markdown:
{{
  "intent": "create_event|update_event|delete_event|unknown",
  "message": "",
  "title": "", "date": "", "start_time": "", "end_time": "", "location": "", "description": "", "recurrence": "",
  "target_event_id": "",
  "new_title": "", "new_date": "", "new_start_time": "", "new_end_time": "", "new_location": ""
}}

UPCOMING EVENTS:
{calendar_json}
""".strip()


def build_datetime_change_prompt(today: str, day_name: str, timezone: str) -> str:
    """Промпт для parseDateTimeChange().

    Соответствует $system в openai.php:166-175.
    """
    return f"""Extract ONLY what the user explicitly states about a new date/time.
Current date: {today} ({day_name}). Timezone: {timezone}.
- If they give a day or date -> new_date as YYYY-MM-DD, else "".
- If they give a start time -> new_start_time as HH:MM (24h), else "".
- "from X to Y" -> new_start_time=X, new_end_time=Y.
- If they give an end time -> new_end_time, else "".
- "3 o'clock" means 15:00 unless morning is stated.
Never fill a field the user did not mention.
Return ONLY JSON: {{"new_date":"","new_start_time":"","new_end_time":""}}"""


TRANSCRIPTION_PROMPT = (
    "Calendar voice command. Likely verbs: create, schedule, add, move, reschedule, "
    "rename, change, update, cancel, delete. Usually mentions a meeting or event, "
    "a day, and a time, and sometimes a location"
)


def _serialize_calendar(events: list[CalendarEvent]) -> str:
    """Сериализовать список событий в JSON для промпта."""
    import json

    return json.dumps(
        [e.model_dump() for e in events],
        indent=2,
        ensure_ascii=False,
    )
