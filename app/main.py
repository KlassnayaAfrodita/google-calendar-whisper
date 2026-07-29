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
import os
import re
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
    resolve_oauth_state,
    resolve_chat_id_from_state,
    save_token_for_user,
)
from app.config import settings
from app.db.session import async_session_factory, init_db
from app.models import User
from app.services.scheduler import build_scheduler

logger = logging.getLogger(__name__)
TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
telegram_app: Application | None = None
scheduler = None


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

async def start_runtime() -> None:
    """Start DB, Telegram polling, and scheduler once."""
    global telegram_app, scheduler

    if telegram_app is not None:
        return

    _setup_logging()
    logger.info("Запуск Calendar Bot (oauth_mode=%s)...", settings.oauth_mode)
    logger.info(
        "Telegram token env: BOT_TOKEN=%s TELEGRAM_BOT_TOKEN=%s TELEGRAM_TOKEN=%s selected_len=%s selected_format_ok=%s",
        "set" if os.getenv("BOT_TOKEN") else "missing",
        "set" if os.getenv("TELEGRAM_BOT_TOKEN") else "missing",
        "set" if os.getenv("TELEGRAM_TOKEN") else "missing",
        len(settings.bot_token),
        bool(TOKEN_PATTERN.match(settings.bot_token)),
    )

    await init_db()
    logger.info("БД инициализирована")

    from app.telegram.bot import build_application

    telegram_app = build_application()
    await telegram_app.initialize()
    await telegram_app.start()
    if telegram_app.updater is None:
        raise RuntimeError("Telegram updater не создан")
    await telegram_app.updater.start_polling()
    logger.info("Telegram polling запущен")

    scheduler = build_scheduler()
    scheduler.start()
    logger.info("Планировщик уведомлений запущен")


async def stop_runtime() -> None:
    """Stop background runtime components."""
    global telegram_app, scheduler

    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
    scheduler = None

    if telegram_app is not None:
        if telegram_app.updater is not None and telegram_app.updater.running:
            await telegram_app.updater.stop()
        if telegram_app.running:
            await telegram_app.stop()
        await telegram_app.shutdown()
    telegram_app = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan used by uvicorn on Bothost."""
    await start_runtime()
    try:
        yield
    finally:
        await stop_runtime()


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
    logger.info(
        "OAuth callback received: state_len=%s code_len=%s",
        len(state),
        len(code),
    )
    # Разрешаем state -> chat_id + PKCE verifier (one-time nonce)
    oauth_state = resolve_oauth_state(state)
    if oauth_state is None:
        logger.warning("OAuth callback rejected: state not found or expired")
        return HTMLResponse(
            content="<h2>❌ Недействительный или истёкший запрос.</h2>"
            "<p>Отправьте /start боту снова, чтобы получить новую ссылку.</p>",
            status_code=400,
        )
    chat_id, code_verifier = oauth_state
    logger.info(
        "OAuth callback state resolved: chat_id=%s code_verifier=%s",
        chat_id,
        "set" if code_verifier else "missing",
    )

    # Обмениваем код на токен
    credentials = await exchange_code_for_token(code, code_verifier=code_verifier)
    if credentials is None:
        logger.warning("OAuth callback token exchange failed: chat_id=%s", chat_id)
        return HTMLResponse(
            content="<h2>❌ Ошибка при обмене кода на токен.</h2>"
            "<p>Попробуйте снова: /start</p>"
        )
    logger.info("OAuth callback token exchange succeeded: chat_id=%s", chat_id)

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
    """Запуск бота, планировщика и HTTP callback-сервера."""
    _setup_logging()
    logger.info("Запуск Calendar Bot (oauth_mode=%s)...", settings.oauth_mode)
    logger.info(
        "Telegram token env: BOT_TOKEN=%s TELEGRAM_BOT_TOKEN=%s TELEGRAM_TOKEN=%s selected_len=%s selected_format_ok=%s",
        "set" if os.getenv("BOT_TOKEN") else "missing",
        "set" if os.getenv("TELEGRAM_BOT_TOKEN") else "missing",
        "set" if os.getenv("TELEGRAM_TOKEN") else "missing",
        len(settings.bot_token),
        bool(TOKEN_PATTERN.match(settings.bot_token)),
    )

    # Инициализация БД (единственный вызов — lifespan пустой)
    await init_db()
    logger.info("БД инициализирована")

    # Telegram bot
    from app.telegram.bot import build_application

    telegram_app: Application = build_application()

    sched = build_scheduler()
    try:
        # Ошибка токена должна завершить процесс, а не оставить только health-сервер.
        await telegram_app.initialize()
        await telegram_app.start()
        if telegram_app.updater is None:
            raise RuntimeError("Telegram updater не создан")
        await telegram_app.updater.start_polling()
        logger.info("Telegram polling запущен")

        sched.start()
        logger.info("Планировщик уведомлений запущен")

        if settings.oauth_mode == "server":
            # Bothost завершает TLS на reverse proxy и проксирует HTTP внутрь
            # контейнера. Поэтому сертификаты приложению не требуются.
            config = uvicorn.Config(
                app=fastapi_app,
                host=settings.webhook_host,
                port=settings.app_port,
                log_level=settings.log_level.lower(),
            )
            server = uvicorn.Server(config)
            logger.info(
                "OAuth HTTP-сервер запущен на %s:%s (HTTPS: reverse proxy)",
                settings.webhook_host,
                settings.app_port,
            )
            await server.serve()
        else:
            logger.info("OAuth mode=local — callback-сервер не нужен, используется polling.")
            await asyncio.Event().wait()
    finally:
        if sched.running:
            sched.shutdown(wait=False)
        if telegram_app.updater is not None and telegram_app.updater.running:
            await telegram_app.updater.stop()
        if telegram_app.running:
            await telegram_app.stop()
        await telegram_app.shutdown()


async def run() -> None:
    """Run FastAPI; lifespan starts Telegram polling and scheduler."""
    config = uvicorn.Config(
        app=fastapi_app,
        host=settings.webhook_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


def main() -> None:
    """Точка входа для python -m app.main."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Остановка бота...")


if __name__ == "__main__":
    main()
