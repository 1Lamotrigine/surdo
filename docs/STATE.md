# Состояние проекта

Обновлено: 2026-10-27

## Текущий этап

**A8 — RoomConsumer и presence: готов.**

## Что готово

- Django-проект (`config`) и приложения `accounts`, `rooms`, `dictionary`, `pipeline`.
- Пакет `services` (пока пустой, без Django-моделей).
- Настройки из переменных окружения: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`,
  `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `REDIS_URL`, `MEDIA_ROOT`, `LOG_LEVEL`,
  `DJANGO_VITE_DEV_MODE`, `DJANGO_VITE_DEV_SERVER_HOST`, `DJANGO_VITE_DEV_SERVER_PORT`.
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
- **Клиент (A3):** Vite + TypeScript + `django-vite`, HTMX 2, точка входа
  `frontend/main.ts`. Модуль отмечает загрузку в шапке и инициализирует HTMX.
- **HTMX-демо:** кнопка на главной загружает фрагмент
  `GET /partials/htmx-demo/` без перезагрузки страницы.
- **Сборка клиента:** `npm run dev` (HMR) и `npm run build` (`static/dist`,
  manifest). В Docker образ попадает только результат сборки из `node:22-slim`.
- **Пользователи (A4):** кастомная модель `accounts.User` (email вместо username,
  имя, роль, `created_at`), роли `teacher/editor/expert/admin`, менеджер с
  нормализацией email и регистронезависимым входом.
- **Аутентификация (A4):** вход по email и паролю, публичная регистрация создаёт
  преподавателя, выход только POST-запросом. Редакторов, экспертов и
  администраторов назначает администратор в Django Admin.
- **Seed администратора:** `python manage.py seed_admin` читает `ADMIN_EMAIL`,
  `ADMIN_PASSWORD`, `ADMIN_NAME` или аргументы `--email/--password/--name`,
  идемпотентно создаёт/обновляет администратора.
- **Комнаты (A5):** модель `rooms.Room` (владелец, название, язык, статус,
  `join_code`, демо-режим, даты), генератор кода из 6 символов без O/0/I/1,
  частичный уникальный индекс кода среди открытых комнат, закрытие комнаты
  с `closed_at`, сервис `create_room` с повтором при коллизии кода.
- **Админка комнат:** список, фильтры по статусу/демо-режиму/языку, поиск,
  действие «Закрыть выбранные комнаты».
- **Создание комнаты (A6):** страница `GET/POST /rooms/new/` (только teacher/admin),
  `POST /api/rooms/` с ответом `{id, join_code, join_url}` для будущего PWA.
- **QR-код (A6):** `segno` рисует inline SVG со ссылкой вида
  `https://<домен>/r/<ID>/`; ссылка собирается из запроса (`build_absolute_uri`).
- **Страница комнаты (A6):** `GET /rooms/<code>/` показывает крупный ID, QR,
  абсолютную ссылку, копирование в буфер обмена и кнопку «Крупный режим» для
  проектора (fullscreen + упрощённый вид, выход по Esc).
- **Участники (A7):** модель `rooms.Participant` (`room`, `user` или `guest_name`,
  `session_key`, `joined_at`, `removed_at`) и инлайны в админке комнаты.
- **Вход студента (A7):** форма ID на главной (`POST /`), страница
  `GET/POST /r/<code>/` с вводом имени и согласием на обработку данных,
  гостевая Django-сессия, страница `GET /r/<code>/live/`. Неверный ID → 404,
  закрытая комната → 410.
- **Rate limit (A7):** перебор ID ограничен через `django.core.cache`
  (`JOIN_RATE_LIMIT_ATTEMPTS`/`JOIN_RATE_LIMIT_WINDOW` на IP), при превышении 429.
- **RoomConsumer (A8):** `WS /ws/rooms/<code>/`, группа `room_<id>`. `connect()`
  проверяет, что комната открыта и код верный, и что у гостя есть сессия с именем
  (или это владелец комнаты/админ). Коды закрытия: 4401 нет сессии, 4403 нет
  доступа или комната закрыта.
- **Presence (A8):** участники комнаты в `rooms/presence.py` (кэш Django с TTL),
  учёт нескольких вкладок по счётчику; изменения рассылаются событием `presence`.
- **Ping/pong (заготовка A11):** `{type: ping}` → `{type: pong}`, продлевает TTL.
- **ASGI:** `AuthMiddlewareStack` кладёт в scope сессию Django и пользователя —
  без этого `connect()` не видит гостевую сессию.
- **Клиент комнаты (A8):** `frontend/room-socket.ts` подключается к WebSocket,
  рисует список участников и статус соединения, шлёт `ping` раз в 20 с, не
  переподключается на 4401/4403.
- `Makefile`: `setup`, `check`, `lint`, `format`, `test`, `up`, `down`, `migrate`,
  `seed-admin`, `client-dev`, `client-build`, `client-typecheck`.
- `pytest-django` + `ruff`, конфигурация в `pyproject.toml`.
- `AGENTS.md`, `.env.example`, `.dockerignore`, `.gitignore`, `README.md`.
- `docs/spec/` — 12 выжимок из ТЗ по разделам.

## Публичные точки входа

| Что | Где |
| --- | --- |
| Стартовая страница | `GET /` → `config.views.home` |
| Health | `GET /health/` → `config.views.health` |
| HTMX-фрагмент | `GET /partials/htmx-demo/` → `config.views.htmx_demo` |
| Вход | `GET/POST /accounts/login/` → `LoginView` + `EmailAuthenticationForm` |
| Регистрация | `GET/POST /accounts/register/` → `accounts.views.register` |
| Выход | `POST /accounts/logout/` → `LogoutView` |
| Создание комнаты | `GET/POST /rooms/new/` → `rooms.views.create_room_view` |
| Страница комнаты (QR + ID) | `GET /rooms/<code>/` → `rooms.views.room_detail` |
| API создания комнаты | `POST /api/rooms/` → `rooms.api.create_room_api` |
| Вход по ID (форма главной) | `POST /` → `config.views.home` |
| Вход студента по ссылке/QR | `GET/POST /r/<code>/` → `rooms.views.room_join` |
| Комната студента | `GET /r/<code>/live/` → `rooms.views.room_student` |
| WebSocket комнаты | `WS /ws/rooms/<code>/` → `rooms.consumers.RoomConsumer` |
| Админка | `GET /admin/` |
| WebSocket-эхо (только A2, DEBUG) | `WS /ws/echo/<group>/` → `config.consumers.EchoConsumer` |
| ASGI-приложение | `config.asgi:application` |
| WSGI-приложение | `config.wsgi:application` |
| JS-точка входа | `frontend/main.ts` → `{% vite_asset 'frontend/main.ts' %}` |
| JS страницы комнаты | `frontend/rooms.ts` → крупный режим и копирование ссылки |

## Клиент: режимы

- **Production / образ:** `DJANGO_VITE_DEV_MODE=False`. Django читает
  `static/dist/manifest.json`, отдаёт хэшированные файлы через WhiteNoise.
- **Разработка:** `DJANGO_VITE_DEV_MODE=True`, `make client-dev`. Страница
  подключает `http://localhost:5173/static/dist/frontend/main.ts` и `@vite/client`.
- `base` в `vite.config.ts` (`/static/dist/`) и `static_url_prefix="dist"`
  согласованы: один URL работает в обоих режимах.

## Тесты

- `tests/test_smoke.py` — стартовая страница, health, HTMX-фрагмент.
- `tests/test_frontend.py` — манифест Vite и URL собранного ассета.
- `tests/test_websocket.py` — два клиента одной группы получают сообщение,
  изоляция групп, отказ без разрешённого Origin, отключение echo вне DEBUG.
- `accounts/tests/` — модель и роли, регистрация/вход/выход, доступ к админке,
  команда `seed_admin` (создание, обновление, ошибки).
- `rooms/tests/` — формат и алфавит `join_code`, автогенерация кода, уникальность
  среди открытых комнат, повторное использование после закрытия, идемпотентное
  закрытие, повторы сервиса при коллизии, QR и ссылка `/r/<code>/`, страницы
  создания/просмотра комнаты, доступ по ролям, JSON API создания, вход студента
  (гостевая сессия, 404/410/429, name-валидация), rate limit, модель участника,
  `RoomConsumer` (изоляция комнат, 4401/4403, presence, второй участник, ping/pong).
- Тесты WebSocket синхронные: сценарий целиком выполняется в `asyncio.run`,
  `CHANNEL_LAYERS` на время теста подменяется на in-memory через `settings`.

## Решения и особенности

- Проект целиком находится в `app/` (рядом с `../TZ_django.md`).
- В compose база опубликована на `127.0.0.1:55432`, Redis — на `127.0.0.1:6380`,
  чтобы не конфликтовать с локальными сервисами. Внутри сети compose — `db:5432`,
  `redis:6379`.
- `daphne` добавлен только в `requirements-dev.txt`: его импортирует
  `channels.testing` (нужен для `WebsocketCommunicator`). В проде используется uvicorn.
- `static/dist` не коммитится: `make check` и Docker собирают его заново.
- Версии клиента фиксируются `package-lock.json`; `npm ci` используется и локально,
  и в Docker.
- `services` не является Django-приложением: там будут чистые модули `asr`,
  `gloss`, `compress` за интерфейсами.
- `AUTH_USER_MODEL = "accounts.User"` задан до первых миграций A4. Если локальная
  база создавалась на A1–A3, её нужно пересоздать: `docker compose down -v`
  (реальных данных ещё нет), затем `make up`, `make migrate`, `make seed-admin`.
- Публичная регистрация всегда создаёт `teacher`; роль нельзя выбрать в форме.
  Повышение роли выполняется в Django Admin.
- `Room.join_code` уникален только среди открытых комнат (частичный
  `UniqueConstraint`), поэтому после закрытия код можно выдать новой комнате.
  Старый QR перестанет работать, потому что поиск комнаты идёт по открытым.
- `join_code` генерируется криптографическим `secrets.choice` из алфавита
  `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`; O/0 и I/1 исключены.
- QR строится на сервере через `segno.svg_inline` (inline SVG, не `<img>`), поэтому
  код масштабируется в «крупном режиме» без потери качества и не требует запроса.
  Ссылка внутри QR собирается из запроса, а маршрут всегда `/r/<ID>/`.
- Создавать и смотреть комнату может только `teacher` (владелец) или `admin`;
  редактор получает 403, гость — редирект на вход.
- Маршруты студента живут в корне (`/r/<code>/`), преподавателя — под `/rooms/`.
  Так ссылка из QR-кода (`/r/<ID>/`) остаётся короткой и не зависит от префикса
  приложения.
- Кэш (`CACHES`) и channel layer разделены: счётчики rate limit идут через кэш
  (Redis при `REDIS_URL`), presence появится на A8 через channel layer.
- `make test` запускается без `REDIS_URL`, поэтому тесты используют локальный кэш
  и in-memory channel layer и не требуют Redis на хосте.
- Presence хранится в кэше (`rooms/presence.py`) как словарь соединений комнаты с
  TTL, а не в отдельном Redis-множестве: так одна абстракция работает и с Redis, и
  с локальным кэшем. Участник онлайн, пока у него есть хотя бы одна вкладка
  (`count > 0`).
- `RoomConsumer` не принимает `chat` и события фраз: это A9/A11. Сейчас он умеет
  только `ping`/`pong` и рассылку `presence`.

## Проверка A8

```bash
make check          # ruff + tsc + vite build + 88 тестов — зелёный
```

Тесты `WebsocketCommunicator` проверяют: гость с сессией подключается и получает
`presence`; без сессии — 4401; неизвестная или закрытая комната — 4403; два гостя
видят друг друга; владелец подключается как не-гость; presence очищается после
отключения; `ping` → `pong`; гость одной комнаты не проходит в другую. Проверено
вручную на in-memory и на Redis-кэше.

## Дальше

**A9 — чат:** модель `Message`, история, событие `chat_message`, интерфейс
преподавателя и студента, догрузка по `last_message_id` при переподключении.
Критерий: тесты consumer и views. Читать: `docs/spec/ws-events.md`,
`docs/spec/requirements.md` (раздел 3.1), `docs/spec/db-schema.md`.
