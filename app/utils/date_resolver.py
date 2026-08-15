"""Deterministic date helpers for natural-language weekday mentions."""

from __future__ import annotations

import re
from datetime import datetime, timedelta


_WEEKDAY_FORMS: dict[str, int] = {
    "понедельник": 0,
    "понедельника": 0,
    "понедельнику": 0,
    "вторник": 1,
    "вторника": 1,
    "вторнику": 1,
    "среда": 2,
    "среду": 2,
    "среды": 2,
    "четверг": 3,
    "четверга": 3,
    "четвергу": 3,
    "пятница": 4,
    "пятницу": 4,
    "пятницы": 4,
    "суббота": 5,
    "субботу": 5,
    "субботы": 5,
    "воскресенье": 6,
    "воскресенья": 6,
    "воскресенью": 6,
}

_WEEKDAY_RE = re.compile(
    r"\b(?P<prefix>ближайш\w*|следующ\w*|эт\w*|в\s+эт\w*|на\s+ближайш\w*|на\s+следующ\w*)?\s*"
    r"(?P<weekday>"
    + "|".join(re.escape(day) for day in sorted(_WEEKDAY_FORMS, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)


def resolve_russian_weekday_date(text: str, now: datetime) -> str | None:
    """Resolve an explicit Russian weekday mention to YYYY-MM-DD.

    The helper intentionally handles only clear weekday words. It is a guardrail
    around LLM output, so returning None is safer than guessing.
    """
    match = _WEEKDAY_RE.search(text.lower())
    if not match:
        return None

    target_weekday = _WEEKDAY_FORMS[match.group("weekday")]
    days_ahead = (target_weekday - now.weekday()) % 7

    prefix = (match.group("prefix") or "").strip()
    if days_ahead == 0 and prefix.startswith("следующ"):
        days_ahead = 7

    return (now.date() + timedelta(days=days_ahead)).isoformat()
