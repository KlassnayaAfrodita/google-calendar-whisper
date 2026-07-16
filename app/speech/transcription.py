"""Транскрипция голосовых сообщений через OpenAI Whisper.

Переносит логику из PHP openai.php: transcribeAudio().
Использует официальный OpenAI Python SDK.
"""

from __future__ import annotations

import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings
from app.llm.prompts import TRANSCRIPTION_PROMPT
from app.schemas import TranscriptionResult

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def transcribe_audio(file_path: str | Path) -> TranscriptionResult:
    """Транскрибировать .ogg файл голосового сообщения.

    Args:
        file_path: Путь к .ogg файлу, скачанному из Telegram.

    Returns:
        TranscriptionResult с текстом или ошибкой.
    """
    client = _get_client()
    path = Path(file_path)

    if not path.exists():
        return TranscriptionResult(success=False, error=f"Файл не найден: {file_path}")

    try:
        with open(path, "rb") as audio_file:
            response = await client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio_file,
                response_format="json",
                prompt=TRANSCRIPTION_PROMPT,
                timeout=60.0,
            )

        text = response.text.strip() if response.text else ""
        if not text:
            return TranscriptionResult(success=False, error="Транскрипция вернула пустой текст")

        return TranscriptionResult(success=True, text=text)

    except FileNotFoundError:
        return TranscriptionResult(success=False, error="Файл не найден")
    except Exception:
        logger.exception("Ошибка при транскрипции аудио")
        return TranscriptionResult(success=False, error="Не удалось транскрибировать голосовое сообщение")
