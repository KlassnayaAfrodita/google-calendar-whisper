"""Тесты защиты от ошибочного обновления существующих событий."""

from app.utils.intent_guardrails import is_explicit_create_instruction


def test_reminder_is_explicit_creation():
    assert is_explicit_create_instruction(
        "Напомни позвонить Разгулову сегодня в два часа дня"
    )


def test_update_request_is_not_explicit_creation():
    assert not is_explicit_create_instruction(
        "Перенеси объект Мосфильмовская сегодня на два часа"
    )
