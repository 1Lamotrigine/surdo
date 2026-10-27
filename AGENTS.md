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
| vad-web | 0.7.0 |
| vitest / @types/node | 5.0.5 / 22.20.5 |
| django-vite | 3.2.0 |
| htmx | 2.0.11 |
| segno (QR, SVG) | 1.6.6 |
| pymorphy3 | 2.0.6 |
| faster-whisper | 1.2.1 |
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
- Инструмент записи жеста (D1–D4): страница `/dictionary/record/`
  (`record_gesture`), клиент `frontend/holistic.ts` + `frontend/skeleton.ts` +
  `frontend/record-page.ts`. MediaPipe Tasks Vision (`@mediapipe/tasks-vision`)
  грузит WASM из `static/dist/mediapipe` (копирует плагин `vite.config.ts`) и
  модель из `MEDIAPIPE_HOLISTIC_MODEL_URL`; видео не отправляется на сервер.
  Запись (D2): `frontend/clip-record.ts` — автообрезка краёв, пересэмплирование
  на 30 FPS, добор кистей/лица, One Euro; `frontend/clip-encode.ts` — Float16 →
  gzip → base64 и `.json.gz` формата C2. После сборки страница сразу распаковывает
  файл декодером `frontend/clip.ts` и сверяет кадры/точки. Лимиты — из
  `CLIP_DEFAULT_FPS`/`CLIP_MAX_FRAMES`/`CLIP_MAX_SIZE_BYTES`.
  Предпросмотр (D3): `Avatar` + `ClipPlayer` загружаются лениво после сборки
  клипа, `AVATAR_MODEL_URL` необязателен; `frontend/sign-draft.ts` валидирует
  глоссу/язык/описание и отправляет multipart в `POST /api/signs/` с CSRF,
  жест создаётся черновиком и виден в Django Admin. Очередь (D4): ссылка
  `/dictionary/record/?word=<id>` подставляет лемму/язык; API принимает
  `unknown_word` и в одной транзакции создаёт жест и переводит слово
  `queued → recorded`. Слово должно быть взято в работу; `new` и `recorded`
  по прямой ссылке возвращают в очередь.
- Упрощённые глоссы (E1): `pipeline/glosses.py` — чистый разбор текста без
  Django; `pipeline/services.py:create_utterance` выбирает язык жестов по
  комнате (`ru` → `rsl`, `kk` → `ksl`), ищет слово среди проверенных глосс по
  точной нормализованной форме (регистр, ё→е), остальное раскладывает в
  `fingerspell` и пишет в очередь `UnknownWord` (каждое вхождение). Глоссы —
  ТЗ 7.2: `tokens` (`sign`/`number`/`fingerspell`), `unknown`,
  `sentence_type`. `seq` выдаётся под `select_for_update` строки комнаты в
  одной транзакции с записью очереди. Морфология и LLM — блок F, не E1.
- Приём текста (E2): `POST /api/rooms/<code>/text/` (`pipeline.api.text_api`)
  только владелец комнаты/админ, ответ 202. Задание ставится в
  `pipeline/queue.py:PipelineQueue`: один `asyncio.Queue` и воркер на комнату,
  глобальный семафор `ASR_MAX_CONCURRENCY`, лимит `ROOM_QUEUE_MAX` со сбросом
  самого старого ожидающего задания. Цикл очереди — в отдельном daemon-потоке
  (Django-вью синхронное). Обработчик может быть sync (уходит в
  `asyncio.to_thread`) или async (по умолчанию `process_phrase_job_async`,
  который различает текст и аудио). Ошибка одного задания не убивает воркер;
  `Future` нужен тестам, HTTP его не ждёт. Очереди в памяти → один процесс
  uvicorn.
- LLM-глоссы в конвейере (F4): `pipeline/gloss_engine.py` собирает словарь из
  проверенных жестов и `DictionaryVersion.current`, вызывает `to_glosses`.
  В async-пути `compute_glosses_async` читает словарь через
  `database_sync_to_async`, а блокирующий провайдер — через
  `asyncio.to_thread` под `asyncio.wait_for(..., LLM_TIMEOUT)`. Нет
  `LLM_MODEL`/ключа → F2-резерв и `degraded=True`; ошибка/битый ответ/таймаут
  настроенной LLM → пустые `tokens` и `degraded=True` (только субтитры).
  Провайдер `services/llm.py` — stdlib `urlopen`, OpenAI-compatible API или
  Ollama, `LLM_API_URL`/`LLM_TIMEOUT` в настройках. `create_utterance` без
  `glosses` остаётся путём E1; F4 передаёт готовые глоссы, `gloss_ms` и
  `degraded`. Очередь по умолчанию использует `process_text_job_async`.
- Распознавание речи (F5): `services/asr.py` — контракт
  `transcribe(audio, lang) -> AsrResult(text, duration_ms)` и провайдер
  `FasterWhisperProvider` (ленивая загрузка модели один раз под замком,
  `WHISPER_MODEL`, `WHISPER_DEVICE`; CPU → int8, CUDA → float16).
  `AsrService` держит отдельный `ThreadPoolExecutor` и
  `BoundedSemaphore(ASR_MAX_CONCURRENCY)`, даёт sync `transcribe` и async
  `transcribe_async`; аудио передаётся байтами в памяти и не сохраняется.
  Тесты используют валидный короткий WAV и подменённую модель, без скачивания
  весов.
- Приём аудиофразы (F6): `POST /api/rooms/<code>/phrase/`
  (`pipeline.api.phrase_api`) — multipart, только владелец комнаты/админ,
  ответ 202. Файл читается в память (лимит 2 МиБ), загруженный файл сразу
  закрывается, на диск и в БД аудио не пишется. `PipelineQueue.submit_audio`
  ставит `AudioJob` в ту же очередь комнаты; `process_audio_job_async`
  вызывает `services.asr.transcribe_async` под `ASR_TIMEOUT` (20 с),
  измеряет `asr_ms`, затем идёт общим путём: `asr_text` → глоссы → `Utterance`
  с `seq` → `utterance`. Пустой результат ASR не создаёт фразу; ошибка/таймаут
  ASR логируется и завершает `Future` ошибкой, не убивая воркер.
- Микрофон и VAD (F7): карточка `_microphone.html` на панели преподавателя,
  `frontend/microphone.ts` + `frontend/audio-phrase.ts`. `vad-web@0.7.0`
  импортируется динамически только по кнопке, работает в Web Worker, отдаёт
  фразу 16 кГц mono по паузе; она кодируется в PCM16 WAV и уходит multipart в
  F6 endpoint с `X-CSRFToken`. Отправка последовательная, ошибка не выключает
  микрофон и не блокирует текстовую форму FR-7. `pagehide` и `room_closed`
  останавливают запись. Первый запуск скачивает модель Silero VAD; нужен
  HTTPS/localhost. Vite сам собирает worker и wasm-ассет `vad-web`.
- Живые фразы (E3): `pipeline/events.py` рассылает в группу `room_<id>`
  `asr_text` (сразу распознанный текст) и `utterance` (глоссы E1 + клипы
  проверенных жестов/чисел/дактиля в порядке показа). Фоновый поток очереди
  ставит `group_send` в запомненный цикл ASGI через
  `run_coroutine_threadsafe`; `RoomConsumer` отдаёт оба события клиенту.
  Студент (`frontend/room-live.ts` + ленивый `room-phrase.ts`) показывает текст
  сразу, ставит фразы в `PhraseQueue`, подгружает клипы и подсвечивает слова.
  История фраз после переподключения пока не реализована.
- Отставание (E4): студент шлёт `display_started` из `RoomPhrasePlayer` в момент
  начала показа; `RoomConsumer` сохраняет `Utterance.display_lag_ms` от
  `started_at` и рассылает `lag_status` (`green` ≤5 с, `yellow` ≤10 с, `red`
  >10 с). `unknown_words` (`glosses["unknown"]`) уходит вместе с `utterance`.
  Оба события отдаются только преподавательским соединениям; студенческий
  consumer их игнорирует. Панель преподавателя показывает индикатор и слова без
  жеста. `ts` клиента принимается с защитой от сдвига часов; повторный
  `display_started` метрику не перезаписывает.
- Панель преподавателя (E5): форма фразы на `/rooms/<code>/live/` отправляется
  через HTMX в `POST .../live/phrase/` (нормализация и очередь общие с E2),
  лента — `GET .../live/feed/` с последними 20 `Utterance` и словами без жеста.
  Лента обновляется по `HX-Trigger: phrase-saved`, событию WebSocket
  `phrase-saved` и опросу раз в 3 с; без HTMX форма делает обычный POST с
  редиректом. Начальные слова без жеста берутся из последней фразы.
- PWA (G1, FR-23/FR-24): `config/pwa.py` отдаёт манифест `/manifest.webmanifest`
  и service worker `/sw.js` **с корня сайта** (иначе SW не получил бы область
  видимости `/`). Там же `cache_version()` — версия кэша из номеров
  `DictionaryVersion` обоих языков и хэша имён файлов сборки Vite; она
  подставляется в шаблон `templates/pwa/sw.js` при отдаче. SW `cache-first`
  кэширует клипы (`/media/clips/*.json.gz`) и статику, `network-first` —
  навигацию с офлайн-фолбэком; при смене версии старые кэши удаляются в
  `activate`. Иконки — `static/img/pwa/*.png` (генерирует
  `scripts/make_pwa_icons.py`, без внешних зависимостей). Документ подключает
  манифест и иконки в `templates/base.html`; `frontend/pwa.ts` добавляет
  `<link rel="manifest">`, если его ещё нет, и регистрирует SW по `load` только
  на HTTPS или localhost. Манифест и `sw.js` открыты без авторизации.
- Предложение установки PWA (G2, FR-27): `frontend/install-prompt.ts` — чистая
  `installEnvironment` (iOS/iPadOS по `userAgent` + `maxTouchPoints`) и
  `installOffer` (`native` для Chromium с `beforeinstallprompt`, `ios` для
  Safari, иначе ничего; `null` в standalone и при закрытом предложении), плюс
  класс `InstallPrompt`. Карточка `[data-install-prompt]` есть в
  `templates/rooms/student.html` и скрыта до решения клиента; на iOS кнопка
  «Установить» прячется (системного диалога там нет) и остаётся инструкция
  «Поделиться → На экран Домой». Отказ запоминается в `localStorage`
  (`gluho-nemye:install-prompt:v1`) и больше не показывается. Включается в
  `frontend/room-live.ts` только для студенческой страницы. Предложение
  необязательное: страница работает и без установки.
- Скрипт нагрузки (G3): `scripts/load_test.py` — поднимает виртуальных
  студентов и подключает их к `WS /ws/rooms/<code>/`. Комната и гостевые
  сессии создаются тем же путём, что у студента (`POST /r/<code>/` через
  Django test client), поэтому сервер принимает соединения без обхода проверок
  A8; у каждого клиента свой `X-Forwarded-For`, чтобы не упираться в лимит
  перебора ID. Меряет handshake, доставку чата (медиана/p95), presence и рост
  RSS процесса сервера; пороги — из ТЗ (медиана ≤ 4 с, p95 ≤ 7 с), память —
  по необязательному `--max-rss-growth`. Коды возврата: 0 — ок, 1 — превышены
  пороги, 2 — ошибка запуска. Требует запущенного сервера и одинакового
  `SECRET_KEY` у скрипта и сервера; новых зависимостей нет (`websockets` уже
  приходит с `uvicorn[standard]`). Память читается из `/proc`/`ps` (хост) или
  через `docker exec` в контейнер (`--server-container`).
- Прод-конфигурация (G4): `docker-compose.yml` — `restart: unless-stopped`,
  healthcheck `web` через `/health/` (caddy ждёт healthy), логи с ротацией,
  порты db/redis только на loopback. `Caddyfile` — адрес из `SITE_ADDRESS`
  (`:80` локально, домен с автоматическим HTTPS в проде), HSTS и заголовки
  безопасности, клипы из `/srv/media`, `reverse_proxy web:8000` (WebSocket
  Caddy проксирует сам). `config/settings.py` при `DEBUG=False` включает
  `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`/HSTS/`X_FRAME_OPTIONS`, а
  `RETENTION_DAYS` задаёт срок хранения. Команда `purge_old_data`
  (`pipeline/retention.py`) удаляет чат/фразы и закрытые комнаты старше срока;
  `scripts/backup.sh` делает `pg_dump` + копию клипов с ротацией копий.
  Инструкция — `docs/DEPLOY.md`, секреты только в `.env`.
- Документация (G5): `README.md` — входная точка (архитектурная схема и путь
  фразы, быстрый старт, разделы по блокам), `docs/DEPLOY.md` — развёртывание,
  `docs/DICTIONARY.md` — инструкция редактору и эксперту словаря (роли, запись
  жеста, проверка, очередь слов). При изменении процесса или маршрутов обновляй
  и эти документы, и `docs/STATE.md`.
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
