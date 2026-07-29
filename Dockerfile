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
COPY app/ ./app/

# Устанавливаем зависимости в отдельный venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

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

# Bothost монтирует исходники в /app. Код образа держим отдельно, чтобы этот
# mount не скрывал установленные файлы.
WORKDIR /srv/bot

# Копируем venv из builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Копируем код приложения
COPY app/ ./app/

# Bothost создает persistent-хранилище в /app/data.
RUN mkdir -p /app/data && chmod 0777 /app/data

# Переменные окружения
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv/bot \
    PORT=3000 \
    DATABASE_URL=sqlite+aiosqlite:////app/data/bot.db

# healthcheck — внутренний HTTP-сервер (TLS завершает reverse proxy)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD sh -c 'curl -fsS "http://localhost:${PORT:-3000}/health" || exit 1'

# Bothost монтирует persistent storage в /app/data; root гарантирует доступ на запись.

EXPOSE 3000

# Запуск
CMD ["sh", "-c", "uvicorn app.main:fastapi_app --host 0.0.0.0 --port ${PORT:-3000}"]
