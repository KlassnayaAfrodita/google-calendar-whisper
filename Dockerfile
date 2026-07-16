# ============================================================
# Stage 1: зависимости
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Системные зависимости для компиляции (cffi, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

# Устанавливаем зависимости в отдельный venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]"

# ============================================================
# Stage 2: финальный образ
# ============================================================
FROM python:3.12-slim AS runtime

# Системные зависимости для работы (libssl для google-auth)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

# Создаём непривилегированного пользователя
RUN groupadd -r bot && useradd -r -g bot -d /app -s /sbin/nologin bot

WORKDIR /app

# Копируем venv из builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Копируем код приложения
COPY app/ ./app/
COPY tests/ ./tests/
COPY README.md MIGRATION_NOTES.md ./

# Создаём директорию для данных (SQLite БД)
RUN mkdir -p /data && chown bot:bot /data

# Переменные окружения
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATABASE_URL=sqlite+aiosqlite:///data/bot.db

# healthcheck — HTTPS-сервер
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsk https://localhost:8443/health || exit 1

# Переключаемся на непривилегированного пользователя
USER bot

EXPOSE 8443

# Запуск
CMD ["python", "-m", "app.main"]
