# 🗓️ Telegram Google Calendar Bot — Python

> Python-порт [telegram-google-calendar-bot](https://github.com/sana2k/telegram-google-calendar-bot) с сохранением всей бизнес-логики, но с чистой архитектурой, multi-user поддержкой, ежедневными уведомлениями и polling-режимом.

Бот превращает **голосовые и текстовые сообщения** в события Google Calendar с помощью OpenAI Whisper + GPT-4o-mini.

## ✨ Возможности

- **Голос и текст** — отправьте голосовое или текстовое сообщение, оба проходят один пайплайн
- **Создание / обновление / удаление** событий на естественном языке
- **Умный поиск событий** — привязка по дню и времени, а не по точному названию
- **Пошаговые флоу** — `/create`, `/update`, `/delete` с inline-кнопками
- **Повторяющиеся события** — «каждый будний день в 9:00», «каждый понедельник в июне с 10:00 до 12:00»
- **Детекция конфликтов** — предупреждение при пересечении с существующими событиями
- **Весь день** — дата без времени создаёт событие на весь день
- **Быстрые действия** — кнопки ✏️ Редактировать / 🗑 Удалить после создания
- **Ежедневные уведомления** — утренний дайджест расписания (NEW)
- **Multi-user** — каждый пользователь подключает свой Google Calendar через OAuth
- **Polling** — не нужен HTTPS для Telegram (только для OAuth callback)

## 🛠 Стек

| Слой | Технология |
|---|---|
| Язык | Python 3.12+ |
| Транскрипция | OpenAI Whisper (`gpt-4o-mini-transcribe`) |
| NLU | OpenAI `gpt-4o-mini` (JSON mode) |
| Календарь | Google Calendar API (`google-api-python-client`) |
| Telegram | `python-telegram-bot` (polling) |
| OAuth | `google-auth-oauthlib` + FastAPI |
| БД | SQLite + SQLAlchemy async |
| Планировщик | APScheduler |
| Валидация | Pydantic v2 |
| Логирование | structlog |

## 📋 Установка

Есть **два режима запуска** — выберите нужный:

| | Локально (тест) | На сервере (продакшн) |
|---|---|---|
| **OAUTH_MODE** | `local` | `server` |
| HTTPS / домен | не нужен | обязателен |
| OAuth flow | ручное копирование кода | автоматический redirect |
| Пользователи | только вы | кто угодно |

---

### 🏠 Вариант А — Локальный запуск (без домена, для теста)

#### 1. Получить ключи (нужны 3 штуки)

**Telegram-бот:**
1. [@BotFather](https://t.me/BotFather) → `/newbot` → получите токен `123456789:ABC...`
2. Узнайте свой chat_id: отправьте боту любое сообщение, затем откройте `https://api.telegram.org/bot<ТОКЕН>/getUpdates` → найдите `chat.id`

**OpenAI:**
1. [platform.openai.com](https://platform.openai.com/api-keys) → Create new secret key → `sk-...`
2. Пополните баланс (Settings → Billing)

**Google OAuth:**
1. [Google Cloud Console](https://console.cloud.google.com/) → создать проект
2. **APIs & Services → Library** → включить **Google Calendar API**
3. **OAuth consent screen** → External → добавить свой Google-аккаунт в **Test users**
4. **Credentials → Create credentials → OAuth client ID** → **Web application**
5. В **Authorized redirect URIs** добавить: `http://localhost`
6. Скопировать **Client ID** и **Client secret**

#### 2. Установить зависимости

```bash
cd google-calendar-whisper
pip install -e ".[dev]"
```

#### 3. Настроить `.env`

```bash
cp .env.example .env
```

Заполните:
```env
BOT_TOKEN=123456789:ABC...
OPENAI_API_KEY=sk-...
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxx

GOOGLE_CALENDAR_ID=primary
GOOGLE_REDIRECT_URI=http://localhost
DEFAULT_TIMEZONE=Europe/Moscow
REMINDER_TIME=08:00
DATABASE_URL=sqlite+aiosqlite:///bot.db
LOG_LEVEL=INFO

# ВАЖНО: локальный режим
OAUTH_MODE=local
```

#### 4. Запустить

```bash
python -m app.main
```

В консоли увидите:
```
Запуск Calendar Bot (oauth_mode=local)...
OAuth mode=local — HTTPS-сервер не нужен. Бот работает через polling.
```

#### 5. Подключить Google Calendar (один раз)

1. Отправьте боту `/start`
2. Бот пришлёт ссылку → откройте её → разрешите доступ
3. Браузер попытается открыть `http://localhost/?...` — страница не загрузится (это нормально)
4. В **адресной строке** будет: `http://localhost/?state=...&code=4/0AX4Xf-xxx...`
5. Скопируйте часть **после** `code=` (начинается с `4/`)
6. Отправьте этот код боту в Telegram
7. Бот ответит «✅ Google Calendar подключён!»

Готово! Можно тестировать команды.

---

### 🌐 Вариант Б — Запуск на VPS (с доменом, для реальных пользователей)

#### 1. Подготовить сервер

```bash
ssh root@SERVER_IP
apt update && apt install -y docker.io docker-compose-plugin git certbot
systemctl enable --now docker
```

#### 2. Настроить DNS и SSL

```bash
# A-запись у регистратора домена: calendar.example.com → IP сервера
certbot certonly --standalone -d calendar.example.com
# Сертификаты: /etc/letsencrypt/live/calendar.example.com/{fullchain,privkey}.pem
```

#### 3. Получить ключи (как в варианте А, но в Google OAuth указать redirect):
- **Authorized redirect URIs**: `https://calendar.example.com/oauth/callback`

#### 4. Залить код и настроить

```bash
cd /opt
git clone https://github.com/вы/calendar-bot.git && cd calendar-bot
cp .env.example .env
```

Заполните `.env`:
```env
BOT_TOKEN=...
OPENAI_API_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://calendar.example.com/oauth/callback
OAUTH_MODE=server
SSL_CERT_PATH=/ssl/cert.pem
SSL_KEY_PATH=/ssl/key.pem
WEBHOOK_PORT=8443
```

В `docker-compose.yml` замените пути к SSL:
```yaml
volumes:
  - bot-data:/data
  - /etc/letsencrypt/live/calendar.example.com/fullchain.pem:/ssl/cert.pem:ro
  - /etc/letsencrypt/live/calendar.example.com/privkey.pem:/ssl/key.pem:ro
```

#### 5. Запустить через Docker

```bash
docker compose up -d --build
docker compose logs -f  # смотреть логи
```

Проверка: `curl https://calendar.example.com/health` → `OK`

#### 6. Авто-обновление SSL (cron)

```bash
crontab -e
# Добавить:
0 3 1 * * certbot renew --quiet && docker compose -f /opt/calendar-bot/docker-compose.yml restart
```

Пользователи подключают календарь автоматически: `/start` → ссылка → разрешить → готово (без копирования кода).

---

## 💬 Использование

**Естественный язык (одним сообщением):**

```
Создать встречу с командой в понедельник в 10:00 в офисе
Запланировать стендап каждый будний день в 9:00
Синхронизация каждый понедельник в июне с 10:00 до 12:00
Перенести понедельничную встречу на среду
Переименовать встречу в 10:00 на «Обзор дизайна»
Отменить встречу во вторник в 15:00
День рождения 15 августа
```

**Пошаговые команды:**

| Команда | Описание |
|---|---|
| `/start` | Начало работы + подключение Google Calendar |
| `/create` | Пошаговое создание: Что → Когда → Где → Подтвердить |
| `/update` | Выбрать событие → поле → новое значение |
| `/delete` | Выбрать событие → подтвердить удаление |
| `/today` | Расписание на сегодня |
| `/week` | Расписание на 7 дней |
| `/cancel` | Отменить текущий флоу |
| `/reconnect` | Переподключить Google Calendar |
| `/help` | Справка |

## 📁 Структура проекта

```
app/
├── main.py                     # Точка входа (bot + FastAPI + scheduler)
├── config.py                   # Pydantic Settings (.env)
├── models.py                   # SQLAlchemy ORM (User, OAuthToken)
├── schemas.py                  # Pydantic схемы (EventDetails, FlowState, ...)
├── db/
│   └── session.py              # Async engine + session factory
├── calendar/
│   ├── auth.py                 # Google OAuth (client, refresh, token management)
│   ├── service.py              # Google Calendar CRUD
│   └── conflicts.py            # Конфликт-детекция
├── llm/
│   ├── service.py              # OpenAI: extract_event_details, parse_datetime_change
│   └── prompts.py              # Системные промпты (перенесены из PHP)
├── speech/
│   └── transcription.py        # Whisper транскрипция
├── telegram/
│   ├── bot.py                  # Application + диспетчеризация хендлеров
│   ├── keyboards.py             # Inline-клавиатуры
│   └── handlers/
│       ├── commands.py         # /start, /help, /create, /update, /delete, ...
│       ├── messages.py         # Текстовые + голосовые сообщения
│       └── callbacks.py        # Inline-кнопки callback queries
├── services/
│   ├── event_pipeline.py       # NL one-shot: текст → LLM → Calendar → ответ
│   ├── guided_flow.py          # Пошаговые флоу (/create, /update, /delete)
│   └── scheduler.py            # APScheduler: ежедневные уведомления
├── state/
│   └── conversation.py         # In-memory conversation state (TTL 10 мин)
└── utils/
    └── formatters.py           # Форматирование дат, событий для Telegram
tests/
├── conftest.py
├── test_llm_parsing.py        # Pydantic schema валидация
├── test_calendar_parsing.py    # Валидация дат, RRULE, конфликты
└── test_calendar_service.py   # CRUD (mocked Google API)
```

## 🧪 Тесты

```bash
# Запустить все тесты
pytest

# С подробным выводом
pytest -v

# С покрытием
pytest --cov=app tests/
```

## ⚙️ Настройка `.env`

| Переменная | Описание | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | Telegram bot token от @BotFather | — |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | — |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret | — |
| `GOOGLE_CALENDAR_ID` | ID календаря (`primary`) | `primary` |
| `GOOGLE_REDIRECT_URI` | OAuth callback URL | — |
| `DEFAULT_TIMEZONE` | Часовой пояс по умолчанию | `Europe/Moscow` |
| `REMINDER_TIME` | Время утреннего уведомления | `08:00` |
| `DATABASE_URL` | SQLite путь | `sqlite+aiosqlite:///bot.db` |
| `LOG_LEVEL` | Уровень логирования | `INFO` |
| `WEBHOOK_HOST` | Хост HTTPS-сервера | `0.0.0.0` |
| `WEBHOOK_PORT` | Порт HTTPS-сервера | `8443` |
| `SSL_CERT_PATH` | Путь к SSL сертификату | — |
| `SSL_KEY_PATH` | Путь к SSL ключу | — |

## ⚠️ Безопасность

- **Никогда не коммитьте `.env`, `credentials.json`, `token.json`** — они в `.gitignore`
- **OAuth redirect URI** должен точно совпадать с registered URI в Google Cloud Console
- **SSL** обязателен для OAuth callback (Google требует HTTPS)

## 📄 Лицензия

MIT
