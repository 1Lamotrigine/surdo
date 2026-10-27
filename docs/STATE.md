# Состояние проекта

Обновлено: 2026-10-27

## Текущий этап

**A1 — каркас проекта: готов.**

## Что готово

- Django-проект (`config`) и приложения `accounts`, `rooms`, `dictionary`, `pipeline`.
- Пакет `services` (пока пустой, без Django-моделей).
- Настройки из переменных окружения: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`,
  `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `MEDIA_ROOT`, `LOG_LEVEL`.
- PostgreSQL как единственная база (SQLite не используется), доступ через
  `dj-database-url`; соединения с `conn_max_age=60`.
- Статика через WhiteNoise (`CompressedManifestStaticFilesStorage`).
- Стартовая страница `GET /` и health-check `GET /health/` (проверяет БД).
- Docker Compose: `web` (uvicorn), `db` (Postgres 16), `redis` (Redis 7),
  `caddy` (порт 80/443, статика клипов из `/srv/media`).
- `Makefile`: `setup`, `check`, `lint`, `format`, `test`, `up`, `down`, `migrate`.
- `pytest-django` + `ruff`, конфигурация в `pyproject.toml`; тесты стартовой
  страницы и health.
- `AGENTS.md`, `.env.example`, `.dockerignore`, `.gitignore`, `README.md`.
- `docs/spec/` — 12 выжимок из ТЗ по разделам.

## Публичные точки входа

| Что | Где |
| --- | --- |
| Стартовая страница | `GET /` → `config.views.home` |
| Health | `GET /health/` → `config.views.health` |
| Админка | `GET /admin/` |
| ASGI-приложение | `config.asgi:application` |
| WSGI-приложение | `config.wsgi:application` |

## Решения и особенности

- Проект целиком находится в `app/` (рядом с `../TZ_django.md`).
- В compose база опубликована на `127.0.0.1:55432`, Redis — на `127.0.0.1:6380`,
  чтобы не конфликтовать с локальными сервисами. Внутри сети compose — `db:5432`,
  `redis:6379`.
- Канальный слой Channels ещё не настроен: зависимости установлены, но
  `channels` не добавлен в `INSTALLED_APPS`, ASGI работает как обычное Django-приложение.
  Это задача A2.
- `services` не является Django-приложением: там будут чистые модули `asr`,
  `gloss`, `compress` за интерфейсами.
- Пустой `frontend/` появится на A3 вместе с Vite.

## Проверка A1

```bash
make setup
make check      # ruff + pytest — зелёный
make up         # стартовая страница на http://localhost/
```

## Дальше

**A2 ★ — Channels и ASGI:** uvicorn (уже используется), channel layer на Redis,
тестовый consumer-эхо, тест `WebsocketCommunicator` на двух клиентов одной группы.
Читать: `docs/spec/architecture.md`, `docs/spec/stack.md`,
`docs/spec/ws-events.md`, `docs/spec/project-structure.md`.
