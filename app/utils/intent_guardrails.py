"""Детерминированные ограничения для опасных календарных действий."""

from __future__ import annotations

import re


_CREATE_MARKER_RE = re.compile(
    r"\b(?:напомни(?:те)?|напоминание|создай(?:те)?|добавь(?:те)?|"
    r"запланируй(?:те)?|назначь(?:те)?|remind|create|add|schedule)\b",
    re.IGNORECASE,
)


def is_explicit_create_instruction(text: str) -> bool:
    """Есть ли в команде явный запрос создать новое событие/напоминание."""
    return bool(_CREATE_MARKER_RE.search(text))
