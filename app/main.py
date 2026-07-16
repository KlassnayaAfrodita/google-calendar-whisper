"""Точка входа — запуск Telegram-бота + FastAPI HTTPS-сервера + APScheduler.

Два режима (OAUTH_MODE):
  - "local" — OAuth без HTTPS: пользователь копирует код из браузера → отправляет боту.
             Подходит для тестирования на localhost без домена.
  - "server" — OAuth через HTTPS callback. Нужен домен + SSL сертификат.
              Подходит для продакшна на VPS.

Запуск: python -m app.main
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from telegram.ext import Application

from app.calendar.auth import (
    build_token_from_credentials,
    exchange_code_for_token,
    resolve_chat_id_from_state,
    save_token_for_user,
)
from app.config import settings
from app.db.session import async_session_factory, init_db
from app.models import User
from app.services.scheduler import build_scheduler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level, logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


# ---------------------------------------------------------------------------
# FastAPI app для OAuth callback (только при oauth_mode=server)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan: пустой. init_db() вызывается в run() явно."""
    yield


fastapi_app = FastAPI(title="Calendar Bot OAuth", lifespan=lifespan)


@fastapi_app.get("/health")
async def health_check() -> PlainTextResponse:
    """Health check endpoint."""
    return PlainTextResponse("OK")


@fastapi_app.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(default=""),
) -> HTMLResponse:
    """Обработчик OAuth callback от Google (режим server).

    Безопасность (CRITICAL #1): state — это случайный nonce, привязанный к chat_id.
    nonce одноразовый и имеет TTL (см. oauth_state.py).
    Подмена state чужим chat_id невозможна — nonce не угадать.
    """
    # Разрешаем state → chat_id (one-time nonce)
    chat_id = resolve_chat_id_from_state(state)
    if chat_id is None:
        return HTMLResponse(
            content="<h2>❌ Недействительный или истёкший запрос.</h2>"
            "<p>Отправьте /start боту снова, чтобы получить новую ссылку.</p>",
            status_code=400,
        )

    # Обмениваем код на токен
    credentials = await exchange_code_for_token(code)
    if credentials is None:
        return HTMLResponse(
            content="<h2>❌ Ошибка при обмене кода на токен.</h2>"
            "<p>Попробуйте снова: /start</p>"
        )

    # Ищем пользователя по chat_id
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_chat_id == chat_id)
        )
        user = result.scalar_one_or_none()

    if user is None:
        return HTMLResponse(
            content="<h2>❌ Пользователь не найден.</h2>"
            "<p>Сначала отправьте /start боту.</p>"
        )

    # Сохраняем токен
    token = build_token_from_credentials(credentials)
    await save_token_for_user(user.id, token)

    # Уведомляем пользователя через бота
    await _notify_user(chat_id, "✅ Google Calendar успешно подключён!\n\nТеперь вы можете отправлять мне голосовые и текстовые команды для управления вашим календарём.\n\n/help — справка.")

    return HTMLResponse(
        content=(
            "<html><body style='text-align:center;padding:50px;font-family:sans-serif'>"
            "<h2>✅ Google Calendar подключён!</h2>"
            "<p>Вернитесь в Telegram — бот готов к работе.</p>"
            "<p>Теперь можно закрыть эту вкладку.</p>"
            "</body></html>"
        )
    )


async def _notify_user(chat_id: int, text: str) -> None:
    """Отправить уведомление пользователю через бота. Ошибки логируем, не пробрасываем."""
    try:
        from telegram import Bot
        bot = Bot(token=settings.bot_token)
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception:
        logger.warning("Не удалось отправить уведомление chat_id=%s", chat_id, exc_info=True)


# ---------------------------------------------------------------------------
# Локальный OAuth (oauth_mode=local)
# ---------------------------------------------------------------------------

async def oauth_local(code: str, state_nonce: str, chat_id_from_chat: int) -> str:
    """Локальный OAuth: пользователь прислал код из браузера.

    В local-режиме пользователь копирует только code из адресной строки,
    поэтому state_nonce обычно пустой. Проверка state пропускается —
    безопасность обеспечивается привязкой кода к redirect_uri (http://localhost).

    Если state_nonce передан — дополнительно верифицируем (опционально).

    Args:
        code: OAuth-код из адресной строки браузера.
        state_nonce: state из адресной строки (обычно пустой в local-режиме).
        chat_id_from_chat: chat_id из Telegram-чата (кто прислал код).
    """
    # Если state передан — проверяем его; если пустой — пропускаем
    if state_nonce:
        expected_chat_id = resolve_chat_id_from_state(state_nonce)
        if expected_chat_id is None or expected_chat_id != chat_id_from_chat:
            return (
                "❌ Недействительный код авторизации.\n"
                "Возможно, ссылка устарела или код был отправлен из другого чата.\n"
                "Отправьте /start, чтобы получить новую ссылку."
            )

    # Обмениваем код на токен
    credentials = await exchange_code_for_token(code, redirect_uri="http://localhost")
    if credentials is None:
        return "❌ Не удалось обменять код на токен. Попробуйте /start снова."

    # Ищем пользователя
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_chat_id == chat_id_from_chat)
        )
        user = result.scalar_one_or_none()

    if user is None:
        return "❌ Пользователь не найден. Отправьте /start."

    # Сохраняем токен
    token = build_token_from_credentials(credentials)
    await save_token_for_user(user.id, token)

    return (
        "✅ Google Calendar успешно подключён!\n\n"
        "Теперь вы можете отправлять мне голосовые и текстовые команды.\n\n"
        "/help — справка"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run() -> None:
    """Запуск бота + FastAPI сервера (при server-режиме) + планировщика."""
    _setup_logging()
    logger.info("Запуск Calendar Bot (oauth_mode=%s)...", settings.oauth_mode)

    # Инициализация БД (единственный вызов — lifespan пустой)
    await init_db()
    logger.info("БД инициализирована")

    # Telegram bot
    from app.telegram.bot import build_application

    telegram_app: Application = build_application()

    # Запускаем polling в фоне
    async def _run_bot():
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling()
        logger.info("Telegram polling запущен")

    asyncio.create_task(_run_bot())

    # Планировщик уведомлений
    sched = build_scheduler()
    sched.start()
    logger.info("Планировщик уведомлений запущен")

    # FastAPI HTTPS-сервер (только при oauth_mode=server)
    if settings.oauth_mode == "server":
        # CRITICAL security: в server-режиме SSL обязателен
        if not (settings.ssl_cert_path and settings.ssl_key_path):
            raise RuntimeError(
                "В OAUTH_MODE=server требуются SSL_CERT_PATH и SSL_KEY_PATH. "
                "OAuth callback MUST be served over HTTPS. "
                "Либо настройте SSL, либо используйте OAUTH_MODE=local."
            )

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(settings.ssl_cert_path, settings.ssl_key_path)
        logger.info("HTTPS включён: cert=%s", settings.ssl_cert_path)

        config = uvicorn.Config(
            app=fastapi_app,
            host=settings.webhook_host,
            port=settings.webhook_port,
            ssl=ssl_context,
            log_level=settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        logger.info("OAuth-сервер запущен на %s:%s", settings.webhook_host, settings.webhook_port)
        await server.serve()
    else:
        logger.info("OAuth mode=local — HTTPS-сервер не нужен. Бот работает через polling.")
        # При local-режиме без HTTPS-сервера — просто держим event loop
        # Telegram polling уже запущен в фоне
        await asyncio.Event().wait()


def main() -> None:
    """Точка входа для python -m app.main."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Остановка бота...")


if __name__ == "__main__":
    main()
