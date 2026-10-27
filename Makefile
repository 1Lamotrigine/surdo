SHELL := /bin/bash

PYTHON ?= .venv/bin/python
COMPOSE ?= docker compose
NPM ?= npm
DB_PASSWORD ?= change-me

-include .env
export

.PHONY: help check lint format test env setup up down logs migrate makemigrations shell createsuperuser client-build client-typecheck client-dev

help:
	@echo "make setup           — .env, venv, Python- и npm-зависимости"
	@echo "make check           — ruff + tsc + pytest + vite build"
	@echo "make up              — собрать и запустить весь стек (web, db, redis, caddy)"
	@echo "make down            — остановить стек"
	@echo "make migrate         — применить миграции"
	@echo "make env             — создать .env из .env.example"
	@echo "make client-dev      — Vite dev-сервер с HMR на :5173"
	@echo "make client-build    — production-сборка в static/dist"
	@echo "make client-typecheck — проверка TypeScript"

.env:
	cp .env.example .env

check: .env lint client-typecheck test

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
	DATABASE_URL="postgres://app:$(DB_PASSWORD)@127.0.0.1:55432/app" $(PYTHON) -m pytest

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

makemigrations:
	$(COMPOSE) exec web python manage.py makemigrations

shell:
	$(COMPOSE) exec web python manage.py shell

createsuperuser:
	$(COMPOSE) exec web python manage.py createsuperuser
