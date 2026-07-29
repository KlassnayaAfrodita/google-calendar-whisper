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

    # HTTP-сервер. В production HTTPS завершается на reverse proxy хостинга.
    webhook_host: str = "0.0.0.0"
    port: int = 8000
    # Устаревшее имя оставлено для совместимости со старыми .env.
    webhook_port: int | None = None
    ssl_cert_path: str = ""
    ssl_key_path: str = ""

    # OAuth режим: "local" (localhost, для разработки) или "server" (HTTPS, для продакшна)
    oauth_mode: str = "local"
    # Порт для локального OAuth callback (только при oauth_mode=local)
    oauth_local_port: int = 8765

    @property
    def app_port(self) -> int:
        """Порт HTTP-сервера: Bothost задаёт PORT, старые конфиги — WEBHOOK_PORT."""
        return self.webhook_port or self.port


settings = Settings()
