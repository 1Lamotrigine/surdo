SHELL := /bin/bash

PYTHON ?= .venv/bin/python
COMPOSE ?= docker compose
NPM ?= npm
DB_PASSWORD ?= change-me
LOAD_URL ?= http://localhost:80
LOAD_CLIENTS ?= 30
BACKUP_DIR ?= ./backups

-include .env
export

.PHONY: help check lint format test env setup up down logs migrate makemigrations shell seed-admin createsuperuser client-build client-typecheck client-test client-dev load backup purge

help:
	@echo "make setup           — .env, venv, Python- и npm-зависимости"
	@echo "make check           — ruff + tsc + vitest + pytest + vite build"
	@echo "make up              — собрать и запустить весь стек (web, db, redis, caddy)"
	@echo "make down            — остановить стек"
	@echo "make migrate         — применить миграции"
	@echo "make seed-admin      — создать/обновить администратора из ADMIN_*"
	@echo "make env             — создать .env из .env.example"
	@echo "make load            — нагрузка: комната и 30 WebSocket-клиентов (G3)"
	@echo "make backup          — дамп базы и копия клипов (G4)"
	@echo "make purge           — удалить данные старше RETENTION_DAYS (dry-run: DRY=1)"
	@echo "make client-dev      — Vite dev-сервер с HMR на :5173"
	@echo "make client-build    — production-сборка в static/dist"
	@echo "make client-typecheck — проверка TypeScript"
	@echo "make client-test     — тесты клиента (vitest)"

.env:
	cp .env.example .env

check: .env lint client-typecheck client-test test

lint:
	@test -x $(PYTHON) || { echo "Нет $(PYTHON). Выполните: make setup"; exit 1; }
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

test: .env client-build
	@test -x $(PYTHON) || { echo "Нет $(PYTHON). Выполните: make setup"; exit 1; }
	$(COMPOSE) up -d db
	@echo "Ожидание PostgreSQL..."
	@until $(COMPOSE) exec -T db pg_isready -U app -d app >/dev/null 2>&1; do sleep 1; done
	# REDIS_URL пуст: тесты используют локальный кэш и in-memory channel layer,
	# не требуя поднятого Redis на хосте.
	DATABASE_URL="postgres://app:$(DB_PASSWORD)@127.0.0.1:55432/app" REDIS_URL="" $(PYTHON) -m pytest

setup: .env
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -r requirements-dev.txt
	$(NPM) ci --no-fund --no-audit

node_modules: package.json package-lock.json
	$(NPM) ci --no-fund --no-audit

client-build: node_modules
	$(NPM) run build

client-typecheck: node_modules
	$(NPM) run typecheck

client-test: node_modules
	$(NPM) test

client-dev: node_modules
	$(NPM) run dev

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f web

migrate:
	$(COMPOSE) exec web python manage.py migrate

seed-admin:
	$(COMPOSE) exec web python manage.py seed_admin

load: .env
	@test -x $(PYTHON) || { echo "Нет $(PYTHON). Выполните: make setup"; exit 1; }
	# Скрипт работает на хосте: база — из compose-порта, мимо Caddy; Redis не
	# нужен (лимиты скрипта локальны, серверный кэш от него не зависит).
	DATABASE_URL="postgres://app:$(DB_PASSWORD)@127.0.0.1:55432/app" REDIS_URL="" \
		$(PYTHON) scripts/load_test.py --url $(LOAD_URL) --clients $(LOAD_CLIENTS)

backup:
	BACKUP_DIR=$(BACKUP_DIR) ./scripts/backup.sh

purge:
	$(COMPOSE) exec -T web python manage.py purge_old_data $(if $(DRY),--dry-run,)

makemigrations:
	$(COMPOSE) exec web python manage.py makemigrations

shell:
	$(COMPOSE) exec web python manage.py shell

createsuperuser:
	$(COMPOSE) exec web python manage.py createsuperuser
