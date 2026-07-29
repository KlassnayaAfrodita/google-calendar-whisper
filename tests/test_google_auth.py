"""Регрессионные тесты Google OAuth credentials."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock

from app.calendar.auth import _normalize_expiry, build_token_from_credentials, get_auth_url, resolve_oauth_state


def _credentials(expiry):
    credentials = MagicMock()
    credentials.token = "access-token"
    credentials.refresh_token = "refresh-token"
    credentials.token_uri = "https://oauth2.googleapis.com/token"
    credentials.expiry = expiry
    credentials.scopes = ["https://www.googleapis.com/auth/calendar"]
    return credentials


def test_build_token_accepts_datetime_expiry():
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    token = build_token_from_credentials(_credentials(expiry))

    assert token.expires_at == expiry.replace(tzinfo=None)


def test_normalize_expiry_accepts_legacy_timestamp():
    expiry = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)

    normalized = _normalize_expiry(expiry.timestamp())

    assert normalized == datetime(2026, 7, 25, 12, 0, 0)


def test_normalize_expiry_preserves_none():
    assert _normalize_expiry(None) is None


def test_auth_url_uses_state_without_pkce():
    url = get_auth_url(chat_id=12345, redirect_uri="https://example.com/oauth/callback")

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert "code_challenge" not in query
    assert "code_challenge_method" not in query
    assert query["redirect_uri"] == ["https://example.com/oauth/callback"]

    state = query["state"][0]
    assert resolve_oauth_state(state) == (12345, None)
