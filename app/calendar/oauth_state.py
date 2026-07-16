"""OAuth state management — защита от CSRF через случайный nonce.

Решение CRITICAL-бага: state больше не содержит chat_id в открытом виде.
Вместо этого state = случайный nonce, который привязан к chat_id с TTL.
После использования nonce удаляется (one-time).

In-memory хранилище: nonce -> (chat_id, expires_at)
Для multi-process/multi-instance деплоя стоит заменить на Redis.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

# In-memory хранилище: nonce -> {"chat_id": int, "expires_at": float}
_states: dict[str, dict[str, Any]] = {}

# TTL — 10 минут на прохождение OAuth flow
_TTL_SECONDS = 600


def create_state(chat_id: int) -> str:
    """Создать одноразовый state nonce для chat_id.

    Возвращает случайную строку, которую можно безопасно передавать в URL.
    """
    nonce = secrets.token_urlsafe(32)
    _states[nonce] = {
        "chat_id": chat_id,
        "expires_at": time.monotonic() + _TTL_SECONDS,
        "used": False,
    }
    return nonce


def resolve_state(nonce: str) -> int | None:
    """Разрешить state nonce обратно в chat_id.

    Возвращает chat_id если nonce валиден и не истёк, иначе None.
    Nonce становится недействительным после первого использования (one-time).
    """
    data = _states.get(nonce)
    if data is None:
        return None

    # Проверка TTL
    if time.monotonic() > data["expires_at"]:
        del _states[nonce]
        return None

    # Проверка что не использован (one-time)
    if data["used"]:
        del _states[nonce]
        return None

    # Помечаем как использованный и удаляем
    del _states[nonce]
    return data["chat_id"]


def cleanup_expired() -> int:
    """Удалить истёкшие state. Возвращает количество удалённых."""
    now = time.monotonic()
    expired = [n for n, d in _states.items() if now > d["expires_at"]]
    for n in expired:
        del _states[n]
    return len(expired)
