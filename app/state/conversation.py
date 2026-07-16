"""Конверсационный state — in-memory хранилище guided-флоу.

Аналог PHP loadState/saveState/clearState из telegram_webhook.php:143-176.
Использует in-memory dict с TTL вместо JSON файлов.
"""

from __future__ import annotations

import time
from typing import Any

from app.schemas import FlowState

# In-memory хранилище: chat_id -> FlowState
_states: dict[int, dict[str, Any]] = {}

# TTL — 10 минут как в PHP
_TTL_SECONDS = 600


def _now() -> float:
    return time.monotonic()


def load_state(chat_id: int) -> FlowState | None:
    """Загрузить state для чата. Возвращает None если истёк или отсутствует."""
    data = _states.get(chat_id)
    if data is None:
        return None

    if (_now() - data.get("_ts", 0)) > _TTL_SECONDS:
        del _states[chat_id]
        return None

    # Убираем служебное поле _ts
    state_data = {k: v for k, v in data.items() if k != "_ts"}
    try:
        return FlowState.model_validate(state_data)
    except Exception:
        return None


def save_state(chat_id: int, state: FlowState) -> None:
    """Сохранить state для чата."""
    data = state.model_dump()
    data["_ts"] = _now()
    _states[chat_id] = data


def clear_state(chat_id: int) -> None:
    """Удалить state для чата."""
    _states.pop(chat_id, None)
