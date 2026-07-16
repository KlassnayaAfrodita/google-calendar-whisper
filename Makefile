.PHONY: help install dev test test-cov lint clean run docker-build docker-up docker-down

PYTHON   := py -3
PYTEST   := $(PYTHON) -m pytest
PROJECT  := google-calendar-whisper

# ===================================================================
# Основные команды
# ===================================================================

help: ## Показать справку
	@echo "Расписание команд:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

install: ## Установить зависимости
	$(PYTHON) -m pip install -e ".[dev]"

dev: install ## Установить зависимости для разработки
	@echo "Готово для разработки."

# ===================================================================
# Тесты
# ===================================================================

test: ## Запустить все тесты
	$(PYTEST) tests/ -v

test-cov: ## Запустить тесты с покрытием
	$(PYTEST) tests/ -v --cov=app --cov-report=term-missing --cov-report=html

# ===================================================================
# Код
# ===================================================================

lint: ## Проверить код (ruff если установлен)
	$(PYTHON) -m ruff check app/ tests/ 2>/dev/null || echo "ruff не установлен. pip install ruff"

format: ## Отформатировать код
	$(PYTHON) -m ruff format app/ tests/ 2>/dev/null || echo "ruff не установлен. pip install ruff"

# ===================================================================
# Запуск
# ===================================================================

run: ## Запустить бота (требуется .env)
	$(PYTHON) -m app.main

run-ssl: ## Запустить бота с SSL (требуются SSL_CERT_PATH и SSL_KEY_PATH в .env)
	$(PYTHON) -m app.main

# ===================================================================
# Docker
# ===================================================================

docker-build: ## Собрать Docker-образ
	docker build -t $(PROJECT) .

docker-up: ## Запустить через docker-compose
	docker compose up -d

docker-down: ## Остановить docker-compose
	docker compose down

docker-logs: ## Логи docker-compose
	docker compose logs -f

# ===================================================================
# Очистка
# ===================================================================

clean: ## Удалить артефакты
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -f bot.db test_bot.db .coverage
	@echo "Очищено."
