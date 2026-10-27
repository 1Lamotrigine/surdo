# AGENTS.md — правила работы ИИ-агента

Проект: ИИ-аватар сурдопереводчик для лекций (веб, русская речь и РЖЯ).
Читай этот файл и `docs/STATE.md` в начале каждой сессии. В конце этапа обновляй
`docs/STATE.md`.

## Зафиксированные версии (не обновлять без запроса человека)

| Компонент | Версия |
| --- | --- |
| Python | 3.12 (3.12.11 локально, образ `python:3.12-slim`) |
| Django | 5.2.18 (LTS) |
| Channels / channels-redis | 4.3.2 / 4.3.0 |
| uvicorn | 0.54.0 |
| PostgreSQL | 16 |
| Redis | 7 |
| Caddy | 2 |
| Node.js | 22 LTS |
| Vite / TypeScript | 8.3.5 / 7.0.2 |
| three / @pixiv/three-vrm / @types/three | 0.186.1 / 3.5.5 / 0.186.0 |
| kalidokit | 1.1.5 |
| @mediapipe/tasks-vision | 1.1.1 |
| vitest / @types/node | 5.0.5 / 22.20.5 |
| django-vite | 3.2.0 |
| htmx | 2.0.11 |
| segno (QR, SVG) | 1.6.6 |
| pytest / pytest-django / ruff | 9.1.1 / 4.14.0 / 0.17.3 |
| daphne (только тесты Channels) | 4.2.3 |

Версии зафиксированы в `requirements.txt`, `requirements-dev.txt` и Docker-образах.

## Структура

```
app/
├── manage.py
├── config/          # настройки, urls, asgi/wsgi, routing, служебные views
├── accounts/        # пользователь и роли, вход (A4)
├── rooms/           # комнаты, участники, чат, consumer, QR (A5-A11)
├── dictionary/      # жесты, клипы, версии словаря, ревью (блок B)
├── pipeline/        # приём фразы, Utterance, метрики (блок E)
├── services/        # pure-Python: asr, gloss, compress (блок F)
├── frontend/        # JS/TS-модули; точка входа main.ts
├── templates/       # Django-шаблоны + HTMX
├── static/          # статика проекта; static/dist — сборка Vite (не коммитится)
├── tests/           # сквозные тесты проекта
├── docs/spec/       # выжимки из ТЗ по разделам
├── docs/STATE.md    # состояние проекта
├── docker-compose.yml, Dockerfile, Caddyfile
└── Makefile, .env.example
```

## Правила

- Views тонкие, логика — в сервисных функциях приложения. Приложения вызывают друг
  друга только через публичные функции.
- В async-коде нет блокирующих вызовов: ORM только через `database_sync_to_async`
  или async-методы, Whisper и LLM — через `asyncio.to_thread`.
- Новые зависимости добавляются только по явной просьбе человека.
- Перед использованием API библиотеки читай её документацию и исходники в
  `site-packages` / `node_modules`, а не пиши по памяти.
- Тесты пишутся вместе с кодом: pytest (позже vitest). Этап закрыт только когда
  зелёный `make check`.
- Аутентификация — по email (`AUTH_USER_MODEL = "accounts.User"`). Публичная
  регистрация создаёт только `teacher`; роли editor/expert/admin назначает
  администратор в Django Admin, не форма регистрации.
- Студент входит без регистрации: имя хранится в гостевой Django-сессии, участник
  создаётся в `rooms.Participant` (`guest_name` + `session_key`). Маршруты
  студента (`/r/<code>/`) и преподавателя (`/rooms/<code>/`) разделены.
- Rate limit (вход по ID, позже чат и фразы) — через `django.core.cache`. Redis
  подключается при заданном `REDIS_URL`, иначе локальный кэш процесса.
  В `make test` `REDIS_URL` пуст: тесты не требуют Redis на хосте.
- WebSocket комнаты: `RoomConsumer` (`rooms/consumers.py`), группа `room_<id>`.
  Изоляция проверяется в `connect()` на сервере (открытая комната + гостевая
  сессия с именем или владелец/админ), коды закрытия 4401/4403. ASGI оборачивает
  маршруты в `AuthMiddlewareStack`, поэтому в `connect()` доступны сессия и user.
  Presence живёт в `rooms/presence.py` (кэш с TTL), событие — `presence`.
- Чат: модель `rooms.Message`, событие `chat_message` (сервер рассылает
  `{type: chat_message, message}`), клиент отправляет `{type: chat, body}`.
  При подключении consumer сразу присылает `chat_history` (последние 50
  сообщений). Текст нормализуется и ограничен 500 символами; есть rate limit
  (`CHAT_RATE_LIMIT_MESSAGES`/`CHAT_RATE_LIMIT_WINDOW`). Границы этапов: чат — A9,
  управление комнатой — A10, heartbeat — A11.
- Heartbeat (A11): клиент шлёт `ping` раз в `ROOM_PING_INTERVAL` (20 с), сервер
  закрывает соединение без пинга за `ROOM_PING_TIMEOUT` (60 с) кодом 4408.
  Реализация — фоновая задача на соединение (`_heartbeat_loop`), не таймер Redis.
  Клиент переподключается с паузой 1, 2, 4, 8…15 с и после подключения
  догружает пропущенное через `GET /api/rooms/<code>/history/`
  (`?after_seq`/`?after_message_id`), отсекая дубликаты по `id` и `seq`.
  Фразовая часть (`utterances`, `seq`) появится в блоке E — сейчас пустой список.
- Управление комнатой (A10): сервис `rooms/management.py` (`close_room`,
  `rotate_join_code`, `remove_participant`) рассылает `room_closed` /
  `participant_removed` в группу `room_<id>` и закрывает соединения кодом 4403.
  HTTP-действия преподавателя (только владелец/админ, POST):
  `/rooms/<code>/close/`, `/rooms/<code>/rotate-code/`,
  `/rooms/<code>/participants/<id>/remove/`. Смена ID не меняет `room.id` —
  группа та же, старый код перестаёт находиться.
- Инструмент записи жеста (D1–D2): страница `/dictionary/record/`
  (`record_gesture`), клиент `frontend/holistic.ts` + `frontend/skeleton.ts` +
  `frontend/record-page.ts`. MediaPipe Tasks Vision (`@mediapipe/tasks-vision`)
  грузит WASM из `static/dist/mediapipe` (копирует плагин `vite.config.ts`) и
  модель из `MEDIAPIPE_HOLISTIC_MODEL_URL`; видео не отправляется на сервер.
  Запись (D2): `frontend/clip-record.ts` — автообрезка краёв, пересэмплирование
  на 30 FPS, добор кистей/лица, One Euro; `frontend/clip-encode.ts` — Float16 →
  gzip → base64 и `.json.gz` формата C2. После сборки страница сразу распаковывает
  файл декодером `frontend/clip.ts` и сверяет кадры/точки. Лимиты — из
  `CLIP_DEFAULT_FPS`/`CLIP_MAX_FRAMES`/`CLIP_MAX_SIZE_BYTES`. Отправка в API — D3,
  запись из очереди — D4.
- Не меняй приложения вне задачи этапа. Не переписывай готовые тесты.
- Один этап — одна ветка и один коммит.
- Секреты только в `.env` (не коммитится). `.env.example` обновляется при
  добавлении переменных.

## Команды

```bash
make setup     # .env + venv + Python- и npm-зависимости
make check     # ruff + tsc + pytest + vite build; поднимает контейнер db
make up        # docker compose up --build (Caddy на :80)
make migrate   # миграции внутри web
make seed-admin # создать/обновить администратора из ADMIN_* в .env
make client-dev # Vite dev-сервер с HMR на :5173
make client-build # production-сборка в static/dist
```

`make test` использует PostgreSQL из compose на `127.0.0.1:55432` (не 5432, чтобы
не конфликтовать с локальной базой). Внутри compose база доступна как `db:5432`.

## Спецификация

Полное ТЗ лежит в `../TZ_django.md`. Для этапов читай только нужные файлы
`docs/spec/`:

| Файл | Содержание |
| --- | --- |
| `overview.md` | цель, роли, сценарии |
| `requirements.md` | FR-1…FR-27 |
| `nfr.md` | НФТ, критерии приёмки, безопасность |
| `architecture.md` | архитектура, поток данных, очереди |
| `project-structure.md` | приложения и правила кода |
| `stack.md` | стек, окружение, docker-compose |
| `api.md` | сервисные модули и HTTP API |
| `ws-events.md` | WebSocket-события и протокол |
| `gloss-format.md` | формат глосс |
| `clip-format.md` | формат клипа и воспроизведение |
| `db-schema.md` | схема БД |
| `dictionary-process.md` | процесс создания словаря |
