"""Google OAuth — управление клиентами и токенами.

Переносит логику из PHP:
- google_calendar.php: getGoogleClient() (token refresh, credentials)
- google_oauth.php: OAuth flow

Безопасность (исправление CRITICAL #1):
- state больше не содержит chat_id в открытом виде
- state = случайный nonce, привязанный к chat_id с TTL (см. oauth_state.py)
- После использования nonce удаляется (one-time)

Async (исправление CRITICAL #2):
- Сетевые вызовы sync Google API обёрнуты в asyncio.to_thread

ORM (исправление CRITICAL #3):
- Используется SQLAlchemy 2.0 стиль select() вместо session.query()
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select

from app.calendar.oauth_state import create_state, resolve_state, resolve_state_data
from app.config import settings
from app.db.session import async_session_factory
from app.models import OAuthToken

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def build_oauth_flow(redirect_uri: str | None = None) -> Flow:
    """Создать OAuth flow для генерации авторизационной ссылки."""
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [redirect_uri or settings.google_redirect_uri],
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
    )
    flow.redirect_uri = redirect_uri or settings.google_redirect_uri
    return flow


def get_auth_url(
    chat_id: int = 0,
    redirect_uri: str | None = None,
) -> str:
    """Сгенерировать URL для авторизации Google Calendar.

    Безопасность: state = случайный nonce, привязанный к chat_id (см. oauth_state.py).
    Никогда не передаёт chat_id в открытом виде.
    """
    flow = build_oauth_flow(redirect_uri)
    flow.code_verifier = secrets.token_urlsafe(64)
    state_nonce = create_state(chat_id, flow.code_verifier)
    url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state_nonce,
    )
    return url


# ---------------------------------------------------------------------------
# State resolution (безопасный способ узнать chat_id из state)
# ---------------------------------------------------------------------------

def resolve_chat_id_from_state(state_nonce: str) -> int | None:
    """Разрешить state nonce в chat_id (one-time, с TTL).

    Возвращает chat_id если nonce валиден, иначе None.
    Используется в /oauth/callback и в локальном OAuth flow.
    """
    return resolve_state(state_nonce)


# ---------------------------------------------------------------------------
# Token exchange (CRITICAL #2: fetch_token обёрнут в to_thread)
# ---------------------------------------------------------------------------

def resolve_oauth_state(state_nonce: str) -> tuple[int, str | None] | None:
    """Resolve one-time OAuth state into chat_id and optional PKCE code verifier."""
    data = resolve_state_data(state_nonce)
    if data is None:
        return None
    return data["chat_id"], data.get("code_verifier")


def _fetch_token_sync(
    code: str,
    redirect_uri: str | None = None,
    code_verifier: str | None = None,
) -> Credentials | None:
    """Синхронная функция для обмена кода на токен. Выполняется в потоке."""
    flow = build_oauth_flow(redirect_uri)
    if code_verifier:
        flow.code_verifier = code_verifier
    try:
        flow.fetch_token(code=code)
        return flow.credentials
    except Exception:
        logger.exception("Ошибка обмена кода на токен Google OAuth")
        return None


async def exchange_code_for_token(
    code: str,
    redirect_uri: str | None = None,
    code_verifier: str | None = None,
) -> Credentials | None:
    """Обменять авторизационный код на Credentials.

    CRITICAL #2: синхронный fetch_token обёрнут в asyncio.to_thread,
    чтобы не блокировать event loop.
    """
    return await asyncio.to_thread(_fetch_token_sync, code, redirect_uri, code_verifier)


def build_token_from_credentials(credentials: Credentials) -> OAuthToken:
    """Создать ORM-объект OAuthToken из Credentials."""
    expires_at = _normalize_expiry(credentials.expiry)

    return OAuthToken(
        access_token=credentials.token,
        refresh_token=credentials.refresh_token,
        token_uri=credentials.token_uri or "https://oauth2.googleapis.com/token",
        # client_id/client_secret НЕ храним в БД (CRITICAL HIGH #3 из security review)
        # — берём из settings при построении Credentials
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        expires_at=expires_at,
        scopes=json.dumps(credentials.scopes) if credentials.scopes else None,
    )


def _normalize_expiry(expiry: datetime | int | float | None) -> datetime | None:
    """Нормализовать expiry в naive UTC для SQLAlchemy/SQLite и google-auth."""
    if expiry is None:
        return None
    if isinstance(expiry, datetime):
        if expiry.tzinfo is None:
            return expiry
        return expiry.astimezone(timezone.utc).replace(tzinfo=None)
    return datetime.fromtimestamp(expiry, tz=timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Token storage (CRITICAL #3: select() вместо session.query())
# ---------------------------------------------------------------------------

async def save_token_for_user(user_id: int, token: OAuthToken) -> None:
    """Сохранить/обновить OAuth токен для пользователя."""
    async with async_session_factory() as session:
        # Удаляем старый токен если есть (SQLAlchemy 2.0 стиль)
        result = await session.execute(
            select(OAuthToken).where(OAuthToken.user_id == user_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            await session.delete(existing)
            await session.flush()

        token.user_id = user_id
        session.add(token)
        await session.commit()

    logger.info("Токен Google OAuth сохранён для user_id=%s", user_id)


# ---------------------------------------------------------------------------
# Credentials retrieval with auto-refresh
# (CRITICAL #2: refresh обёрнут в to_thread; CRITICAL #3: select())
# ---------------------------------------------------------------------------

def _refresh_credentials_sync(credentials: Credentials) -> Credentials | None:
    """Синхронный refresh токена. Выполняется в потоке."""
    try:
        credentials.refresh(Request())
        return credentials
    except Exception:
        logger.exception("Не удалось обновить токен")
        return None


async def get_credentials_for_user(user_id: int) -> Credentials | None:
    """Получить Google Credentials для пользователя с auto-refresh.

    Аналог PHP getGoogleClient().
    Загружает токен из БД, проверяет срок, обновляет при необходимости.

    CRITICAL #2: sync refresh обёрнут в asyncio.to_thread.
    CRITICAL #3: используется select() вместо session.query().
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(OAuthToken).where(OAuthToken.user_id == user_id)
        )
        token = result.scalar_one_or_none()

        if token is None:
            logger.warning("OAuth токен не найден для user_id=%s", user_id)
            return None

        credentials = Credentials(
            token=token.access_token,
            refresh_token=token.refresh_token,
            token_uri=token.token_uri,
            # Берём из settings, а не из БД (безопасность)
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=json.loads(token.scopes) if token.scopes else SCOPES,
            expiry=token.expires_at,
        )

        # Проверяем и обновляем при необходимости
        if credentials.expired:
            if not credentials.refresh_token:
                logger.warning(
                    "Токен истёк и нет refresh_token для user_id=%s", user_id
                )
                return None

            # CRITICAL #2: refresh в потоке, не блокируем event loop
            refreshed = await asyncio.to_thread(_refresh_credentials_sync, credentials)
            if refreshed is None:
                return None
            credentials = refreshed

            # Сохраняем обновлённый access_token
            token.access_token = credentials.token
            if credentials.expiry:
                token.expires_at = _normalize_expiry(credentials.expiry)
            await session.commit()
            logger.info("Токен обновлён для user_id=%s", user_id)

        return credentials


async def has_valid_google_auth(user_id: int) -> bool:
    """Проверить, есть ли у пользователя действующий Google OAuth."""
    creds = await get_credentials_for_user(user_id)
    return creds is not None
