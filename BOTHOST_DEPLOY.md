# Деплой на Bothost

Проект использует Telegram long polling, а публичный HTTP endpoint нужен только
для Google OAuth callback. HTTPS завершается на reverse proxy Bothost; внутри
контейнера FastAPI слушает обычный HTTP на `0.0.0.0:$PORT`.

## 1. Google Cloud

1. Включите Google Calendar API.
2. Настройте OAuth consent screen.
3. Создайте OAuth Client ID типа **Web application**.
4. После создания бота и домена Bothost добавьте точный redirect URI:

   ```text
   https://ВАШ-ДОМЕН.bothost.tech/oauth/callback
   ```

5. В режиме Testing добавьте нужные Google-аккаунты в Test users.

## 2. Настройки Bothost

1. Подключите Git-репозиторий и нужную ветку.
2. Выберите Telegram и укажите токен от BotFather.
3. В дополнительных настройках включите:
   - использование собственного `Dockerfile`;
   - публичный домен.
4. Установите внутренний порт `8000`.
5. Используйте тариф без сна и с постоянным хранилищем: polling, OAuth state,
   SQLite и ежедневный scheduler требуют постоянно работающего процесса.

## 3. Переменные окружения

Добавьте в панели Bothost:

```env
BOT_TOKEN=...
# Если Bothost не дает создать BOT_TOKEN, используйте вместо него:
# TELEGRAM_BOT_TOKEN=...
OPENAI_API_KEY=...

GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
GOOGLE_CALENDAR_ID=primary
GOOGLE_REDIRECT_URI=https://ВАШ-ДОМЕН.bothost.tech/oauth/callback

DEFAULT_TIMEZONE=Europe/Volgograd
REMINDER_TIME=08:00
DATABASE_URL=sqlite+aiosqlite:////app/data/bot.db
LOG_LEVEL=INFO

OAUTH_MODE=server
WEBHOOK_HOST=0.0.0.0
PORT=8000
```

`SSL_CERT_PATH` и `SSL_KEY_PATH` на Bothost не нужны.

## 4. Первый деплой

Выполните полный deploy/redeploy. В логах должны появиться сообщения:

```text
БД инициализирована
Telegram polling запущен
Планировщик уведомлений запущен
OAuth HTTP-сервер запущен
```

Проверьте:

```text
https://ВАШ-ДОМЕН.bothost.tech/health
```

Ответ должен быть `OK`.

Затем отправьте боту `/start`, пройдите Google OAuth и проверьте `/today`,
создание текстового события и голосовое сообщение.

## 5. Проверка постоянного хранения

После успешного OAuth выполните restart в панели и снова отправьте `/today`.
Если повторная авторизация не требуется, SQLite в `/app/data/bot.db` сохраняется
корректно.

Не запускайте одновременно локальную и размещённую копии с одним Telegram
токеном. Если у бота раньше был webhook, удалите его перед первым polling-запуском:

```text
https://api.telegram.org/bot<ТОКЕН>/deleteWebhook?drop_pending_updates=true
```
