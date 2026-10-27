SHELL := /bin/bash

PYTHON ?= .venv/bin/python
COMPOSE ?= docker compose
DB_PASSWORD ?= change-me

-include .env
export

.PHONY: help check lint format test env setup up down logs migrate makemigrations shell createsuperuser

help:
	@echo "make setup      — создать .env и виртуальное окружение, установить зависимости"
	@echo "make check      — ruff + pytest (поднимает только контейнер db)"
	@echo "make up         — собрать и запустить весь стек (web, db, redis, caddy)"
	@echo "make down       — остановить стек"
	@echo "make migrate    — применить миграции"
	@echo "make env        — создать .env из .env.example"

.env:
	cp .env.example .env

check: .env lint test

lint:
	@test -x $(PYTHON) || { echo "Нет $(PYTHON). Выполните: make setup"; exit 1; }
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

test: .env
	@test -x $(PYTHON) || { echo "Нет $(PYTHON). Выполните: make setup"; exit 1; }
	$(COMPOSE) up -d db
	@echo "Ожидание PostgreSQL..."
	@until $(COMPOSE) exec -T db pg_isready -U app -d app >/dev/null 2>&1; do sleep 1; done
	DATABASE_URL="postgres://app:$(DB_PASSWORD)@127.0.0.1:55432/app" $(PYTHON) -m pytest

setup: .env
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -r requirements-dev.txt

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
