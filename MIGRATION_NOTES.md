# 📋 Заметки о миграции: PHP → Python

## Общая стратегия

Не механический построчный перевод, а **поведенческий порт**:
- Изучена вся бизнес-логика PHP
- Сохранено всё пользовательское поведение
- Реализация переписана идиоматично для Python
- Добавлен новый функционал (daily reminders, multi-user)

## Маппинг модулей

| PHP файл | Функция | Python модуль | Комментарий |
|---|---|---|---|
| `config.php` | Константы | `app/config.py` | Pydantic Settings + `.env` вместо PHP define() |
| `telegram.php` → `telegramApi()` | HTTP к Telegram API | `python-telegram-bot` | Вся библиотека заменяет ручные curl-запросы |
| `telegram.php` → `sendTelegramMessage()` | Отправка сообщений | `update.message.reply_text()` | Методы библиотеки |
| `telegram.php` → `editMessageText()` | Редактирование сообщений | `callback.edit_message_text()` | Методы библиотеки |
| `telegram.php` → `answerCallback()` | Ответ на callback | `await callback.answer()` | Метод библиотеки |
| `telegram.php` → `downloadTelegramFile()` | Скачивание файлов | `await voice.get_file()` + `download_to_drive()` | Методы библиотеки |
| `openai.php` → `transcribeAudio()` | Whisper транскрипция | `app/speech/transcription.py` | Official OpenAI SDK вместо curl |
| `openai.php` → `extractEventDetails()` | LLM разбор команды | `app/llm/service.py` + `app/llm/prompts.py` | Official SDK, промпты 1:1 |
| `openai.php` → `parseDateTimeChange()` | LLM разбор даты/времени | `app/llm/service.py` | Отдельный метод в том же сервисе |
| `openai.php` → `$system` prompt | Системный промпт | `app/llm/prompts.py` | Функция `build_event_details_prompt()` |
| `google_calendar.php` → `getGoogleClient()` | OAuth client + refresh | `app/calendar/auth.py` | SQLAlchemy + auto-refresh |
| `google_calendar.php` → `createGoogleCalendarEvent()` | Создание события | `app/calendar/service.py` → `create_event()` | google-api-python-client |
| `google_calendar.php` → `updateGoogleEventById()` | Обновление события | `app/calendar/service.py` → `update_event()` | — |
| `google_calendar.php` → `deleteGoogleEventById()` | Удаление события | `app/calendar/service.py` → `delete_event()` | — |
| `google_calendar.php` → `getCalendarEvents()` | Получение событий | `app/calendar/service.py` → `get_events()` | — |
| `google_calendar.php` → `getUpcomingEvents()` | Предстоящие события | `app/calendar/service.py` → `get_upcoming_events()` | — |
| `google_calendar.php` → `getGoogleEventTitle()` | Заголовок по ID | `app/calendar/service.py` → `get_event_title()` | — |
| `google_calendar.php` → `findConflicts()` | Конфликт-детекция | `app/calendar/conflicts.py` | Выделен в отдельный модуль |
| `google_calendar.php` → `validDate/validTime()` | Валидация | `app/calendar/service.py` | regex валидация, те же паттерны |
| `google_oauth.php` | OAuth flow | `app/calendar/auth.py` + `main.py` `/oauth/callback` | FastAPI endpoint вместо PHP-страницы |
| `telegram_webhook.php` → `ack()` | Мгновенный ответ | **Не нужен** | Polling не требует ack (нет double-post) |
| `telegram_webhook.php` → `loadState/saveState/clearState` | Conversation state | `app/state/conversation.py` | In-memory dict с TTL вместо JSON-файлов |
| `telegram_webhook.php` → `startCreateFlow/advanceCreate` | Guided /create | `app/services/guided_flow.py` | Очистка: state-машина + Pydantic |
| `telegram_webhook.php` → `startPickFlow` | Guided /update, /delete | `app/services/guided_flow.py` | Обобщён для обоих флоу |
| `telegram_webhook.php` → `applyUpdateValue` | Применить update | `app/services/guided_flow.py` | — |
| `telegram_webhook.php` → `showCreatePreview` | Превью события | `app/services/guided_flow.py` → `_build_create_preview()` | Reused из callbacks.py |
| `telegram_webhook.php` → `processInstruction` | NL one-shot | `app/services/event_pipeline.py` | Оркестратор |
| `telegram_webhook.php` → `handleCallback` | Callback queries | `app/telegram/handlers/callbacks.py` | Все callback_data совпадают |
| `telegram_webhook.php` → `helpText` | Справка | `app/utils/formatters.py` → `help_text()` | На русском |
| `telegram_webhook.php` → `fmtEventLine` | Строка события | `app/utils/formatters.py` → `fmt_event_line()` | — |
| `telegram_webhook.php` → `conflictText` | Текст конфликтов | `app/utils/formatters.py` → `conflict_text()` | — |
| `telegram_webhook.php` → `sendAgenda` | Повестка дня | `app/services/event_pipeline.py` → `send_agenda()` | — |
| `telegram_webhook.php` → `quickActions` | Кнопки действий | `app/telegram/keyboards.py` → `quick_actions_keyboard()` | — |
| (нет) | — | `app/services/scheduler.py` | **NEW:** APScheduler daily reminders |
| (нет) | — | `app/models.py` | **NEW:** SQLAlchemy User + OAuthToken |
| (нет) | — | `app/schemas.py` | **NEW:** Pydantic EventDetails, FlowState |
| (нет) | — | `app/db/session.py` | **NEW:** Async SQLAlchemy engine |

## Архитектурные отличия

| Аспект | PHP | Python |
|---|---|---|
| Webhook vs Polling | Webhook (fastcgi_finish_request) | **Polling** (run_polling) |
| State storage | JSON-файлы на диске | In-memory dict (TTL 10 мин) |
| БД | Нет (только файлы) | SQLite + SQLAlchemy async |
| Пользователи | Single (OWNER_CHAT_ID) | **Multi-user** (OAuth per user) |
| Timezone | Жёстко Asia/Dubai | Настраиваемый (default Europe/Moscow) |
| Язык интерфейса | English | **Русский** |
| Промпты LLM | English | English (как в оригинале — LLM prompt ≠ UI) |
| Daily reminders | Нет (в roadmap) | **APScheduler** |
| OAuth | PHP-страница | FastAPI endpoint |
| Конфигурация | PHP define() | Pydantic Settings + .env |
| HTTP-клиент | curl | Official SDK (openai, google-api) |
| Типизация | Нет | Type hints + Pydantic |
| Логирование | file_put_contents (debug) | structlog |

## Сохранённые callback_data

Все идентификаторы кнопок из PHP сохранены без изменений:

| Callback | PHP функция | Python обработчик |
|---|---|---|
| `create_skip_loc` | `handleCallback` line 423 | `callbacks._create_skip_loc` |
| `create_confirm` | `handleCallback` line 435 | `callbacks._create_confirm` |
| `create_cancel` | `handleCallback` line 430 | `callbacks.handle_callback` |
| `u_pick:N` | `handleCallback` line 457 | `callbacks._update_pick` |
| `u_field:datetime` | `handleCallback` line 479 | `callbacks._update_field` |
| `u_field:title` | — | `callbacks._update_field` |
| `u_field:location` | — | `callbacks._update_field` |
| `d_pick:N` | `handleCallback` line 498 | `callbacks._delete_pick` |
| `d_confirm` | `handleCallback` line 517 | `callbacks._delete_confirm` |
| `d_cancel` | `handleCallback` line 529 | `callbacks.handle_callback` |
| `qa_edit:ID` | `handleCallback` line 375 | `callbacks._qa_edit` |
| `qa_del:ID` | `handleCallback` line 393 | `callbacks._qa_del` |
| `qa_delyes:ID` | `handleCallback` line 409 | `callbacks._qa_del_yes` |
| `qa_delno` | `handleCallback` line 417 | `callbacks.handle_callback` |

## Промпты

Все промпты перенесены из `openai.php` в `app/llm/prompts.py`:

1. **EVENT_DETAILS_PROMPT** → `build_event_details_prompt()` — основной промпт для разбора команд
2. **DATETIME_CHANGE_PROMPT** → `build_datetime_change_prompt()` — для update-флоу
3. **TRANSCRIPTION_PROMPT** → константа — подсказка для Whisper

Адаптация: дата/день и timezone подставляются динамически.
