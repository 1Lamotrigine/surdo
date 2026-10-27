# Состояние проекта

Обновлено: 2026-10-27

## Текущий этап

**A2 — Channels и ASGI: готов.**

## Что готово

- Django-проект (`config`) и приложения `accounts`, `rooms`, `dictionary`, `pipeline`.
- Пакет `services` (пока пустой, без Django-моделей).
- Настройки из переменных окружения: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`,
  `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `REDIS_URL`, `MEDIA_ROOT`, `LOG_LEVEL`.
- PostgreSQL как единственная база (SQLite не используется), доступ через
  `dj-database-url`; соединения с `conn_max_age=60`.
- Статика через WhiteNoise (`CompressedManifestStaticFilesStorage`).
- Стартовая страница `GET /` и health-check `GET /health/` (проверяет БД).
- Docker Compose: `web` (uvicorn), `db` (Postgres 16), `redis` (Redis 7),
  `caddy` (порт 80/443, статика клипов из `/srv/media`).
- **ASGI + Channels:** `ProtocolTypeRouter` (HTTP → Django, WebSocket → Channels),
  `AllowedHostsOriginValidator`, `URLRouter`.
- **Channel layer:** Redis через `REDIS_URL` (`channels_redis`); без `REDIS_URL`
  используется `InMemoryChannelLayer` для локальной разработки.
- **Тестовый `EchoConsumer`** (этап A2): `/ws/echo/<group>/`, каждое сообщение
  рассылается всей группе. Доступен только при `DEBUG=True`, будет заменён
  `RoomConsumer` на A8.
- `Makefile`: `setup`, `check`, `lint`, `format`, `test`, `up`, `down`, `migrate`.
- `pytest-django` + `ruff`, конфигурация в `pyproject.toml`.
- `AGENTS.md`, `.env.example`, `.dockerignore`, `.gitignore`, `README.md`.
- `docs/spec/` — 12 выжимок из ТЗ по разделам.

## Публичные точки входа

| Что | Где |
| --- | --- |
| Стартовая страница | `GET /` → `config.views.home` |
| Health | `GET /health/` → `config.views.health` |
| Админка | `GET /admin/` |
| WebSocket (только A2, DEBUG) | `WS /ws/echo/<group>/` → `config.consumers.EchoConsumer` |
| ASGI-приложение | `config.asgi:application` |
| WSGI-приложение | `config.wsgi:application` |

## Тесты

- `tests/test_smoke.py` — стартовая страница и health.
- `tests/test_websocket.py` — два клиента одной группы получают сообщение,
  изоляция групп, отказ без разрешённого Origin, отключение echo вне DEBUG.
- Тесты WebSocket синхронные: сценарий целиком выполняется в `asyncio.run`,
  `CHANNEL_LAYERS` на время теста подменяется на in-memory через `settings`.

## Решения и особенности

- Проект целиком находится в `app/` (рядом с `../TZ_django.md`).
- В compose база опубликована на `127.0.0.1:55432`, Redis — на `127.0.0.1:6380`,
  чтобы не конфликтовать с локальными сервисами. Внутри сети compose — `db:5432`,
  `redis:6379`.
- `daphne` добавлен только в `requirements-dev.txt`: его импортирует
  `channels.testing` (нужен для `WebsocketCommunicator`). В проде используется uvicorn.
- `services` не является Django-приложением: там будут чистые модули `asr`,
  `gloss`, `compress` за интерфейсами.
- Пустой `frontend/` появится на A3 вместе с Vite.

## Проверка A2

```bash
make check      # ruff + 6 тестов — зелёный
make up         # стек с Redis и Caddy
# два клиента на /ws/echo/a2-live/ получают одно и то же сообщение
```

Проверено вручную: через Caddy два WebSocket-клиента получили сообщение группы,
backend — `channels_redis.core.RedisChannelLayer`.

## Дальше

**A3 — сборка клиента:** Vite и `django-vite`, пример JS-модуля на странице,
HTMX. Читать: `docs/spec/stack.md`, `docs/spec/project-structure.md`.
