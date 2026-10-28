# ИИ-аватар сурдопереводчик для лекций

Прототип веб-сервиса: преподаватель говорит в микрофон, аватар в браузере показывает
фразу жестами, студенты видят субтитры и пишут вопросы в чат. Язык первой версии —
русский (русская речь и РЖЯ).

> Это прототип помощника, а не замена живому сурдопереводчику.

## Архитектура

Одно Django-приложение (ASGI, uvicorn) владеет схемой БД. Распознавание речи и
LLM живут в нём же как модули `services.*` за интерфейсами и выполняются в
пулах потоков, а не в цикле событий. Браузер студента получает готовые глоссы и
ссылки на клипы — никакого ИИ на клиенте студента.

```
 Браузер преподавателя                    Браузер студента
  микрофон + VAD, текст, чат               VRM-аватар, субтитры, чат
        │ HTTP (фраза/текст) + WebSocket         ▲ WebSocket (asr_text, utterance)
        ▼                                        │
 ┌──────────── Caddy (HTTPS, статика, клипы /media) ────────────┐
 └──────────────────────────────┬───────────────────────────────┘
                                ▼
 ┌──────────────── Django (ASGI, uvicorn --workers 1) ──────────────┐
 │ Auth · Комнаты (Channels, RoomConsumer) · Админка · HTMX         │
 │ pipeline: очередь фраз (asyncio.Queue на комнату, семафор)       │
 │ services: asr (faster-whisper) · gloss (LLM) · compress           │
 │           · clips (хранилище .json.gz)                            │
 └──────────┬───────────────────────────────┬──────────────────────┘
            │ SQL (ORM)                     │ группы Channels room_<id>
            ▼                               ▼
     ┌──────────────┐                ┌──────────────┐
     │ PostgreSQL   │                │ Redis        │ (channel layer,
     └──────────────┘                └──────────────┘  rate limit, presence)
     ┌──────────────┐
     │ Клипы (volume)│  ← раздаёт Caddy, не Django
     └──────────────┘
```

Путь одной фразы: VAD в браузере отдаёт аудио → `POST /api/rooms/<code>/phrase/`
(202, аудио только в памяти) → фоновый воркер комнаты: `services.asr.transcribe`
→ событие `asr_text` (субтитры сразу) → `services.gloss.to_glosses` →
`Utterance` с `seq` → событие `utterance` с клипами → студент ставит клипы в
очередь и подсвечивает слова, шлёт `display_started` → `lag_status` преподавателю.
Подробности — в `docs/spec/architecture.md` и `docs/spec/ws-events.md`.

## Требования

- Python 3.12 и [uv](https://docs.astral.sh/uv/) для локальной разработки;
- Docker и Docker Compose для полного стека и тестов;
- Node.js 22 и npm для сборки клиента (Vite, TypeScript, HTMX).

## Быстрый старт

```bash
cp .env.example .env     # при необходимости поменяйте пароль и SECRET_KEY
make setup               # venv, Python- и npm-зависимости
make check               # ruff + tsc + vitest + vite build + pytest (поднимает контейнер db)
docker compose up --build -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_admin
```

Перед `seed_admin` задайте `ADMIN_EMAIL`, `ADMIN_PASSWORD` и `ADMIN_NAME` в `.env`
(или передайте `--email`, `--password`, `--name`). Команда идемпотентна.

Стартовая страница: <http://localhost/> (через Caddy), health: <http://localhost/health/>.

> Если база создавалась до этапа A4, пересоздайте локальный volume
> (`docker compose down -v`): добавлена кастомная модель пользователя. Делайте это
> только пока в базе нет реальных данных.

На этапе A2 доступен тестовый WebSocket-эхо `ws://localhost/ws/echo/<group>/`
(только при `DEBUG=True`). Два клиента одной группы получают общие сообщения.

## Аккаунты и роли

Вход выполняется по email и паролю: `/accounts/login/`. Публичная регистрация
(`/accounts/register/`) создаёт пользователя с ролью `teacher`. Роли `editor`,
`expert` и `admin` назначает администратор в Django Admin (`/admin/`).
Начальный администратор создаётся командой `seed_admin`. Выход — POST на
`/accounts/logout/`.

## Комнаты

Преподаватель (роль `teacher`) создаёт комнату на `/rooms/new/`. После создания
страница `/rooms/<ID>/` показывает короткий ID и QR-код (inline SVG через `segno`)
со ссылкой вида `https://<домен>/r/<ID>/`. Кнопка «Крупный режим» оставляет на
экране только QR и ID — удобно вывести на проектор. Ссылку можно скопировать в
буфер обмена. Комнату также можно создать через `POST /api/rooms/`.

## Вход студента

Студент входит без регистрации: либо сканирует QR-код, либо вводит ID комнаты на
главной странице. На странице `/r/<ID>/` он указывает имя и попадает в комнату
(`/r/<ID>/live/`). Имя и ключ сессии хранятся в записи `Participant`. Неверный ID
даёт 404, закрытая комната — 410, при переборе ID срабатывает ограничение частоты
(429). Значения лимита настраиваются через `JOIN_RATE_LIMIT_ATTEMPTS` и
`JOIN_RATE_LIMIT_WINDOW`.

Страница комнаты подключается по WebSocket `WS /ws/rooms/<ID>/`: сервер проверяет
доступ в `connect()`, добавляет соединение в группу комнаты и рассылает событие
`presence` со списком участников. Коды закрытия: 4401 — нет сессии, 4403 — нет
доступа или комната закрыта.

## Чат

В комнате есть чат: студенты пишут вопросы, преподаватель отвечает. Сообщения
приходят всем участникам событием `chat_message` и сохраняются (`rooms.Message`);
при подключении клиент сразу получает историю (`chat_history`), а при
переподключении может догрузить пропущенное через
`GET /api/rooms/<ID>/history/?after_message_id=<id>`. Текст ограничен 500
символами, действует ограничение частоты (`CHAT_RATE_LIMIT_MESSAGES` за
`CHAT_RATE_LIMIT_WINDOW` секунд). Панель преподавателя с чатом и участниками —
`/rooms/<ID>/live/`.

## Словарь жестов

Словарь наполняют редакторы и эксперты-носители: редактор записывает жест с
камеры, эксперт проверяет смысл, скорость, положение и мимику. Словам, которые
встретились на занятиях и ещё не имеют жеста, автоматически ведётся очередь.
Страницы словаря: запись `/dictionary/record/`, очередь слов
`/dictionary/queue/`, проверка жестов `/dictionary/review/`; полный словарь —
в Django Admin (`/admin/dictionary/`).

Публичный список проверенных жестов — `GET /api/dictionary/?lang=rsl`; студентам
видны только утверждённые жесты. Утверждение жеста растит версию словаря, и это
сбрасывает кэш PWA.

Пошаговая инструкция для редактора и эксперта — `docs/DICTIONARY.md`.

Жест можно не только записать с камеры, но и сделать готовой анимацией
(`.vrma`/`.glb`, например в Blender) и загрузить тем же API. Как готовить,
загружать и что ещё осталось подключить — `docs/ANIMATIONS.md`.

## PWA и установка на телефон

Сайт работает как PWA: он отдаёт веб-манифест с корня (`/manifest.webmanifest`),
иконки и service worker (`/sw.js`). Service worker кэширует статику клиента и
клипы жестов, поэтому при повторном заходе жесты не скачиваются заново; новая
версия словаря или новая сборка клиента сбрасывает устаревший кэш. Приложение
устанавливается на домашний экран Android (Chrome) и iPhone (Safari, «На экран
Домой»), при этом сайт полностью работает и во вкладке без установки.

Регистрация service worker идёт только по HTTPS или на `localhost` — браузер
больше нигде его не отдаёт. Иконки PWA пересобираются скриптом
`python scripts/make_pwa_icons.py` (без внешних зависимостей).

После входа в комнату студенту предлагается установить приложение на домашний
экран. Предложение необязательное: его можно закрыть, и оно больше не появится.
На Android (Chrome) кнопка «Установить» открывает системный диалог, на iPhone
(Safari) показывается инструкция «Поделиться → На экран Домой».

## Развёртывание

Прод-развёртывание на сервере (HTTPS через Caddy, резервные копии, очистка
данных) описано в `docs/DEPLOY.md`. Кратко:

```bash
cp .env.example .env      # заполните SECRET_KEY, DEBUG=False, домен, ADMIN_*
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_admin
```

`docker compose up` поднимает `web` (uvicorn), `db`, `redis` и `caddy`;
Caddy сам получает TLS-сертификат для домена из `SITE_ADDRESS` и раздаёт клипы.
Проверка: `curl https://<домен>/health/`. Бэкап — `make backup`, очистка старых
данных по сроку хранения — `make purge`.

## Нагрузка

Критерий приёмки №5 (комната на 30 одновременных подключений) проверяется
скриптом `scripts/load_test.py`. Он поднимает виртуальных студентов,
подключает их к WebSocket комнаты и измеряет время подключения, доставку
сообщений чата, presence и рост памяти сервера.

```bash
# при поднятом стеке (make up): Caddy на :80
make load LOAD_CLIENTS=30
# или напрямую против локального uvicorn
.venv/bin/python scripts/load_test.py --url http://localhost:8000 --clients 30
```

Без `--room` создаётся новая комната, её код печатается. `--json` даёт машинную
сводку, `--max-rss-growth` добавляет предел роста памяти. Скрипт завершается
кодом 1, если превышены пороги ТЗ (медиана ≤ 4 с, p95 ≤ 7 с). Важно: скрипт и
сервер должны использовать один и тот же `SECRET_KEY` (гостевые сессии).

## Клиент в разработке

По умолчанию `DJANGO_VITE_DEV_MODE=False`: Django отдаёт собранные файлы из
`static/dist` (они попадают в Docker-образ). Для HMR:

```bash
# в .env: DJANGO_VITE_DEV_MODE=True
make client-dev          # Vite на http://localhost:5173
make up                  # страница подключает модуль с dev-сервера
```

`make client-build` пересобирает `static/dist`, `make client-typecheck` проверяет
TypeScript, `make client-test` гоняет тесты клиента (vitest).

## Структура

| Путь | Назначение |
| --- | --- |
| `config/` | настройки, маршруты, ASGI/WSGI, служебные views |
| `accounts/` | пользователи и роли |
| `rooms/` | комнаты, участники, чат, WebSocket |
| `dictionary/` | словарь жестов и клипы |
| `pipeline/` | обработка фраз |
| `services/` | ASR, глоссы, сжатие (pure Python) |
| `frontend/` | TypeScript-модули, точка входа `main.ts` |
| `vite.config.ts` | сборка в `static/dist` |
| `templates/`, `static/` | шаблоны, статика, иконки PWA и HTMX |
| `docs/spec/` | выжимки из ТЗ |
| `docs/STATE.md` | текущее состояние проекта |

## Команды

```bash
make check            # ruff + tsc + vitest + vite build + pytest
make lint             # только ruff
make test             # vite build + только pytest
make client-dev       # Vite dev-сервер с HMR
make client-build     # production-сборка клиента
make client-typecheck # проверка TypeScript
make client-test      # тесты клиента (vitest)
make up               # docker compose up --build
make down             # остановить стек
make migrate          # применить миграции
make seed-admin       # создать/обновить администратора из ADMIN_* в .env
make logs             # логи web
```

Скрипт нагрузки: `.venv/bin/python scripts/load_test.py --url http://localhost:8000`.

## Документация

- Полное ТЗ: `../TZ_django.md`
- Выжимки из ТЗ по разделам: `docs/spec/`
- Развёртывание на сервере: `docs/DEPLOY.md`
- Инструкция редактору словаря: `docs/DICTIONARY.md`
- Анимационные жесты (VRMA/glTF): `docs/ANIMATIONS.md`
- Правила для агента: `AGENTS.md`
- Состояние и план этапов: `docs/STATE.md`
