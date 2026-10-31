SHELL := /bin/bash
.DEFAULT_GOAL := help
.ONESHELL:

PYTHON := .venv/bin/python
PID_FILE := .run/api.pid
LOG_FILE := .run/api.log

.PHONY: help up tdown health logs logs-follow test e2e interactive

# Справка по командам
help:
	@echo "RLT.Startup MVP — команды управления"
	@echo
	@echo "Запуск и остановка:"
	@echo "  make up           Запустить API в фоне"
	@echo "  make down         Остановить API"
	@echo "  make health       Проверить доступность API"
	@echo
	@echo "Логи:"
	@echo "  make logs         Показать последние 30 строк лога"
	@echo "  make logs-follow  Следить за логом в реальном времени"
	@echo
	@echo "Проверки:"
	@echo "  make test         Запустить pytest и Ruff"
	@echo
	@echo "Демонстрация:"
	@echo "  make e2e          Запустить автоматический E2E-сценарий"
	@echo "  make interactive  Запустить интерактивную демонстрацию"
	@echo
	@echo "Требования:"
	@echo "  - виртуальное окружение .venv"
	@echo "  - файл .env.demo для запуска и демонстрации"
	@echo "  - локальная Ollama с настроенной моделью для интерактивного сценария"
	@echo
	@echo "Для E2E и интерактивной демонстрации API должен быть запущен (make up)."

# Запуск API в фоне
up:
	@set -eu
	test -x "$(PYTHON)" || { echo "Не найдено .venv"; exit 1; }
	test -f .env.demo || { echo "Не найден .env.demo"; exit 1; }
	mkdir -p .run

	if [[ -f "$(PID_FILE)" ]]; then
		pid="$$(cat "$(PID_FILE)")"
		if kill -0 "$$pid" 2>/dev/null; then
			echo "API уже запущен, PID=$$pid"
			exit 1
		fi
		rm -f "$(PID_FILE)"
	fi

	nohup bash -c \
		'source .venv/bin/activate; set -a; source .env.demo; set +a; exec uvicorn rlt_startup.demo_api:app --host 127.0.0.1 --port 8000' \
		> "$(LOG_FILE)" 2>&1 &
	echo $$! > "$(PID_FILE)"

	echo "Ожидание запуска API..."
	for i in {1..15}; do
		if curl -fsS --silent --max-time 1 http://127.0.0.1:8000/health >/dev/null 2>&1; then
			echo "API готов: http://127.0.0.1:8000"
			echo "Лог: $(LOG_FILE)"
			exit 0
		fi
		sleep 1
	done

	echo "API не прошёл health check. Последние строки лога:"
	tail -n 30 "$(LOG_FILE)"
	pid="$$(cat "$(PID_FILE)" 2>/dev/null || true)"
	if [[ -n "$$pid" ]] && kill -0 "$$pid" 2>/dev/null; then
		kill "$$pid" 2>/dev/null || true
	fi
	rm -f "$(PID_FILE)"
	exit 1

# Проверка доступности API
health:
	@curl -fsS --max-time 3 http://127.0.0.1:8000/health || { echo "API недоступен"; exit 1; }
	echo

# Последние строки лога
logs:
	@tail -n 30 "$(LOG_FILE)"

# Непрерывный просмотр лога
logs-follow:
	@tail -n 30 -f "$(LOG_FILE)"

# Тесты и линтер
test:
	@set -e
	source .venv/bin/activate
	"$(PYTHON)" -m pytest -q
	"$(PYTHON)" -m ruff check

# Полная сквозная демонстрация
e2e:
	@set -e
	source .venv/bin/activate
	set -a
	source .env.demo
	set +a
	"$(PYTHON)" scripts/e2e_demo.py

# Интерактивная демонстрация
interactive:
	@set -e
	source .venv/bin/activate
	set -a
	source .env.demo
	set +a
	"$(PYTHON)" scripts/e2e_demo.py --interactive

# Остановка API
down:
	@set -eu
	if [[ ! -f "$(PID_FILE)" ]]; then
		echo "PID-файл не найден; API мог быть запущен не через make"
		exit 0
	fi

	pid="$$(cat "$(PID_FILE)")"
	if ! kill -0 "$$pid" 2>/dev/null; then
		echo "Процесс API уже остановлен"
		rm -f "$(PID_FILE)"
		exit 0
	fi

	kill "$$pid"
	for i in {1..10}; do
		if ! kill -0 "$$pid" 2>/dev/null; then
			rm -f "$(PID_FILE)"
			echo "API остановлен"
			exit 0
		fi
		sleep 1
	done

	echo "API не завершился за 10 секунд; PID-файл сохранён: $(PID_FILE)"
	exit 1
