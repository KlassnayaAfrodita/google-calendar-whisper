"""Обработчики текстовых и голосовых сообщений.

Переносит логику NL one-shot и guided-флоу из PHP telegram_webhook.php.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from telegram import Update
from telegram.error import TimedOut
from telegram.ext import ContextTypes

from app.config import settings
from app.calendar.auth import has_valid_google_auth
from app.speech.transcription import transcribe_audio
from app.services.event_pipeline import process_instruction
from app.services.guided_flow import advance_flow
from app.state.conversation import load_state

logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Общий обработчик текстовых и голосовых сообщений.

    Логика:
    1. Если текст — проверить, не OAuth-код ли это (локальный режим)
    2. Если голос → скачать .ogg → транскрибировать → текст
    3. Если есть active guided flow → advance_flow
    4. Иначе → NL one-shot (process_instruction)
    """
    chat_id = update.effective_chat.id
    message = update.message

    # Перехват OAuth-кода (локальный режим) — до проверки авторизации
    if message and message.text:
        from app.telegram.handlers.commands import handle_oauth_code
        if await handle_oauth_code(update, context):
            return

    # Проверяем авторизацию Google
    if not await has_valid_google_auth(chat_id):
        await update.message.reply_text(
            "⚠️ Сначала подключите Google Calendar: отправьте /start",
            parse_mode="HTML",
        )
        return

    is_voice = message.voice is not None

    if is_voice:
        # Голосовое сообщение → транскрипция
        text = await _process_voice(update, context)
        if text is None:
            return
    else:
        text = (message.text or "").strip()

    if not text:
        return

    # Если есть активный guided flow
    state = load_state(chat_id)
    if state:
        await advance_flow(update, chat_id, state, text)
        return

    # NL one-shot
    await process_instruction(update, chat_id, text, is_voice)


async def _process_voice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> str | None:
    """Скачать и транскрибировать голосовое сообщение. Возвращает текст или None."""
    chat_id = update.effective_chat.id
    voice = update.message.voice
    tmp_path: str | None = None

    try:
        file = await _telegram_retry(voice.get_file)

        # Скачиваем во временный файл
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name

        await _telegram_retry(file.download_to_drive, tmp_path)

        # Транскрибируем
        result = await transcribe_audio(tmp_path)

        if not result.success:
            await update.message.reply_text(
                f"❌ Не удалось распознать речь:\n{result.error}",
                parse_mode="HTML",
            )
            return None

        logger.info("Транскрипция: chat_id=%s, text='%s'", chat_id, result.text)
        return result.text

    except Exception:
        logger.exception("Ошибка обработки голосового сообщения")
        await update.message.reply_text(
            "❌ Не удалось обработать голосовое сообщение.",
            parse_mode="HTML",
        )
        return None
    finally:
        if tmp_path is not None:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


async def _telegram_retry(func, *args):
    attempts = max(1, settings.telegram_voice_download_retries)
    for attempt in range(1, attempts + 1):
        try:
            return await func(*args)
        except TimedOut:
            if attempt == attempts:
                raise
            await asyncio.sleep(attempt)
