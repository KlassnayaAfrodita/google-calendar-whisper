"""Конфигурация приложения — загрузка из .env через Pydantic Settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все настройки бота в одном месте. Значения берутся из .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str

    # OpenAI
    openai_api_key: str

    # Google Calendar
    google_client_id: str
    google_client_secret: str
    google_calendar_id: str = "primary"
    google_redirect_uri: str

    # Настройки по умолчанию
    default_timezone: str = "Europe/Moscow"
    reminder_time: str = "08:00"

    # БД
    database_url: str = "sqlite+aiosqlite:///bot.db"

    # Логирование
    log_level: str = "INFO"

    # HTTPS-сервер
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8443
    ssl_cert_path: str = ""
    ssl_key_path: str = ""

    # OAuth режим: "local" (localhost, для разработки) или "server" (HTTPS, для продакшна)
    oauth_mode: str = "local"
    # Порт для локального OAuth callback (только при oauth_mode=local)
    oauth_local_port: int = 8765


settings = Settings()
