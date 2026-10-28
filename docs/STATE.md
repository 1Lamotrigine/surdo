# Состояние проекта

Обновлено: 2026-10-28

## Текущий этап

**H1 — каркас анимационных жестов (VRMA/glTF): готов.
Этап вне плана A–G, добавлен после G5 по запросу человека.**

Проект по-прежнему функционально завершён по ТЗ (блоки A–G). H1 нужен для
второго способа производства жестов: команда делает анимации вручную в Blender
на готовой модели с правильным скелетом. Сервер уже принимает и хранит такие
клипы, клиент умеет их грузить и проигрывать; осталось подключить саму модель и
(при желании) пакет VRMA — см. `docs/ANIMATIONS.md`.

Предыдущие этапы: **G4 — прод-конфигурация, G3 — скрипт нагрузки,
G2 — предложение установки PWA, G1 — PWA: манифест, иконки и service worker,
F8 — управление отставанием, F7 — микрофон и VAD, F6 — приём аудиофразы, F5 — ASR,
F4 — LLM в конвейере, F3 — сжатие, F2 — запасной режим, F1 — LLM-глоссы,
E5 — панель преподавателя: готовы.**

## Что готово

- Django-проект (`config`) и приложения `accounts`, `rooms`, `dictionary`, `pipeline`.
- Пакет `services` (без Django-моделей): `services.clips` — хранилище клипов,
  `services.asr` — распознавание речи за интерфейсом провайдера.
- Настройки из переменных окружения: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`,
  `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `REDIS_URL`, `MEDIA_ROOT`, `LOG_LEVEL`,
  `DJANGO_VITE_DEV_MODE`, `DJANGO_VITE_DEV_SERVER_HOST`, `DJANGO_VITE_DEV_SERVER_PORT`,
  `ROOM_PING_INTERVAL`, `ROOM_PING_TIMEOUT`, `AVATAR_MODEL_URL`,
  `MEDIAPIPE_HOLISTIC_MODEL_URL`, `CLIP_VERSION`, `CLIP_DEFAULT_FPS`,
  `CLIP_MAX_FRAMES`, `CLIP_MAX_SIZE_BYTES`, `CLIP_MAX_ANIMATION_BYTES`,
  `ANIMATION_DEFAULT_FPS`, `ASR_MAX_CONCURRENCY`, `ROOM_QUEUE_MAX`,
  `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_API_URL`, `LLM_TIMEOUT`,
  `COMPRESS_TIMEOUT`, `WHISPER_MODEL`, `WHISPER_DEVICE`, `ASR_TIMEOUT`.
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
- **Ping/pong (A11):** `{type: ping}` → `{type: pong}`, продлевает TTL presence и
  heartbeat-окно. Любое сообщение клиента тоже продлевает окно.
- **Heartbeat (A11):** у каждого соединения фоновая задача; если клиент молчит
  дольше `ROOM_PING_TIMEOUT` (60 с), сервер закрывает соединение кодом 4408.
  Проверка идёт раз в `ROOM_PING_INTERVAL` (20 с). Параметры — из окружения.
- **ASGI:** `AuthMiddlewareStack` кладёт в scope сессию Django и пользователя —
  без этого `connect()` не видит гостевую сессию.
- **Клиент комнаты (A8–A11):** `frontend/room-live.ts` подключается к WebSocket,
  рисует участников, историю и чат, шлёт `ping` раз в 20 с. Переподключение с
  нарастающей паузой (1, 2, 4, 8 с, потолок 15 с); на 4401/4403 не
  переподключается. После переподключения догружает пропущенное через
  `GET /api/rooms/<code>/history/` и отсекает дубликаты по `id` (и `seq`).
- **Чат (A9):** модель `rooms.Message` (`room`, `participant`, `author_name`,
  `is_teacher`, `body`, `created_at`). Клиент шлёт `{type: chat, body}`, сервер
  сохраняет и рассылает `chat_message` с `{id, user, body, ts, is_teacher}`.
- **История (A9/A11):** при подключении consumer присылает `chat_history`
  (последние 50 сообщений); `GET /api/rooms/<code>/history/` принимает
  `?after_message_id` (чат) и `?after_seq` (фразы) и возвращает
  `{room, utterances, messages}`. `utterances` пока пуст (фразы — блок E),
  поле и параметр уже в контракте.
- **Ограничения чата (A9):** текст нормализуется, максимум 500 символов, rate
  limit `CHAT_RATE_LIMIT_MESSAGES`/`CHAT_RATE_LIMIT_WINDOW` на участника; при
  превышении приходит `chat_error`.
- **Панель преподавателя (A9):** `GET /rooms/<code>/live/` — QR, ID, чат и
  участники в реальном времени; ссылка «Открыть панель» на странице комнаты.
- **Управление комнатой (A10):** `rooms/management.py` — `close_room` (закрыть и
  разослать `room_closed`), `rotate_join_code` (сменить ID с повтором при
  коллизии), `remove_participant` (удалить участника, закрыть его соединения и
  обновить presence). Рассылка идёт в группу `room_<id>` через `async_to_sync`.
- **Действия преподавателя (A10):** `POST /rooms/<code>/close/`,
  `POST /rooms/<code>/rotate-code/`, `POST /rooms/<code>/participants/<id>/remove/`
  (только владелец/админ). Кнопки «Сменить ID» и «Закрыть комнату» на странице
  комнаты и панели; «Удалить» рядом с участником в панели (JS рисует кнопку).
- **События управления (A10):** `room_closed` и `participant_removed` — сервер
  шлёт их и закрывает соединение кодом 4403; клиент на 4403 не переподключается.
  При закрытии presence комнаты очищается, при удалении — только ключ участника.
- **Словарь (B1):** модели `dictionary.Sign` (глосса, язык, описание, статус
  `draft/review/verified/rejected`, `recorded_by`, `verified_by`, `verified_at`,
  `comment`), `dictionary.SignClip` (FK на жест, `file`, `fps`, `duration_ms`,
  `frames`, `version`, `size_bytes`), `dictionary.UnknownWord` (`lemma`, `lang`,
  `count`, `last_seen_at`, статус `new/queued/recorded`),
  `dictionary.DictionaryVersion` (`lang`, `number`, `created_at`).
  Общие `TextChoices`: `Language` (rsl/ksl), `SignStatus`, `UnknownWordStatus`.
  Методы: `Sign.verify(expert, comment)`, `Sign.best_clip`,
  `DictionaryVersion.current/next_number/bump`.
- **Фразы (B1):** модель `pipeline.Utterance` (`room`, `seq`, `text`,
  `glosses` JSONField, `asr_ms`, `gloss_ms`, `display_lag_ms`, `degraded`,
  `started_at`, `created_at`), метод `as_event()`. Порядковый `seq` уникален в
  пределах комнаты.
- **Миграции (B1):** `dictionary/0001_initial`, `pipeline/0001_initial`;
  применяются и откатываются, `makemigrations --check` чист.
- **Хранилище клипов (B2):** `services/clips.py` — интерфейс `ClipStorage`
  (Protocol: `save/exists/read/open/delete/size/etag/url`) и файловая
  реализация `FileClipStorage` поверх `MEDIA_ROOT`/`MEDIA_URL` (корень и URL
  берутся из настроек лениво). `default_storage` — общий экземпляр.
- **Раздача клипов (B2):** `GET /media/clips/<id>.json.gz` →
  `dictionary.views.clip_file`; ETag по содержимому, `Cache-Control:
  public, max-age=604800, immutable`, ответ 304 на `If-None-Match`, 404 для
  неизвестного клипа или отсутствующего файла. В проде запрос перехватывает
  Caddy (`Caddyfile`), в разработке и тестах файл отдаёт Django.
- **Путь клипа (B2):** `SignClip.storage_path` (относительный путь файла) и
  `SignClip.file_url()` (публичный URL по имени маршрута `clip-file`).
- **Формат клипа (B3):** `services.clips` — `pack_clip` (собрать `.json.gz`),
  `parse_clip` (прочитать и проверить), `ClipMeta` (version, gloss, fps, frames,
  layout, data, `duration_ms`) и `ClipFormatError`. Валидация: gzip, JSON-объект,
  версия формата, положительные `fps`/`frames`, лимит кадров, непустые
  `layout`/`data`. Лимиты — из настроек (`CLIP_VERSION`, `CLIP_MAX_SIZE_BYTES`,
  `CLIP_MAX_FRAMES`, `CLIP_DEFAULT_FPS`).
- **Публичный API словаря (B3):** `GET /api/dictionary/?lang=rsl&status=verified`
  → `{lang, version, signs}`; жесты с клипами и `url`; без авторизации отдаёт
  только проверенные. `?status=draft` (черновики) — только редактор/эксперт/админ,
  иначе 403. Неизвестный язык/статус — 400.
- **Загрузка жеста (B3):** `POST /api/signs/` → `dictionary.api.create_sign_api`
  (только редактор/эксперт/админ, иначе 401/403); принимает `multipart/form-data`
  (`gloss`, `lang`, `description`, файл `clip`) или `application/json` (без
  клипа). `dictionary.services.create_sign` валидирует метаданные и клип,
  сохраняет файл в хранилище и создаёт `SignClip` (fps, кадры, длительность,
  размер, версия). Битый/слишком большой клип — 400/413, жест не создаётся.
- **Слаги имени файла (B3):** `dictionary.services` транслитерирует глоссу в
  ASCII и складывает клип в `clips/<год>/<месяц>/<id>-<slug>-v<версия>.json.gz`.
- **Переходы статусов (B4):** `dictionary/statuses.py` — чистая таблица переходов
  (без Django): `draft → review`, `review → verified|rejected|draft`,
  `rejected → draft|review`, `verified → review|rejected`. Функции
  `can_transition`, `required_role`, `allowed_targets`, `validate_transition`,
  исключение `StatusTransitionError`. У каждого перехода своя роль: редактор
  отправляет на проверку, эксперт утверждает/отклоняет.
- **Сервис переходов (B4):** `dictionary.services.transition_sign(sign,
  to_status, actor, comment)` проверяет переход и роль, обновляет
  `status`/`comment`/`verified_by`/`verified_at`; при переходе в `verified`
  создаётся новая `DictionaryVersion` языка (`bump`). Обёртки
  `submit_for_review` (редактор), `verify_sign`/`reject_sign` (эксперт),
  исключения `SignValidationError` (запрещённый переход) и `SignPermissionError`
  (нет роли). `Sign.verify()` остаётся низкоуровневым примитивом модели (админка):
  помечает жест проверенным и тоже растит версию.
- **Полезная нагрузка жеста (B4):** в `sign_payload` добавлены `comment` и
  `allowed_transitions` — куда можно перевести жест дальше (для интерфейса
  редактора и эксперта).
- **Админка словаря (B5):** `dictionary/admin.py` — `SignAdmin` (список с
  клипами, фильтр по статусу и языку, поиск, инлайны клипов, предпросмотр
  лучшего клипа ссылкой на файл), `SignClipAdmin` (сквозной список клипов),
  `UnknownWordAdmin` (очередь по убыванию частоты), `DictionaryVersionAdmin`
  (только чтение; версии создаёт сервис).
- **Действия в админке (B5):** «Отправить на проверку», «Утвердить (эксперт)»,
  «Отклонить (эксперт)» — переиспользуют сервисные переходы B4
  (`submit_for_review`/`verify_sign`/`reject_sign`); запрещённый переход
  пропускается с предупреждением, утверждение растит версию словаря.
- **Решение эксперта (B6):** `POST /api/signs/<id>/review/` →
  `dictionary.api.review_sign_api`; тело `{decision: "approve"|"reject",
  comment}` (JSON или поля формы). Менять статус может только эксперт или
  админ (`can_review_signs`): аноним — 401, редактор/преподаватель — 403,
  неверное решение — 400, запрещённый переход — 409, нет жеста — 404.
  Утверждение растит версию словаря, отклонение — нет.
- **Интерфейс эксперта (B6):** страница очереди `GET /dictionary/review/`
  (жесты в статусе `review`) и карточка `GET/POST /dictionary/review/<id>/` с
  клипом, метаданными, ссылкой на файл и формой «Утвердить/Отклонить» с
  комментарием. Доступ через `dictionary.permissions.review_required` (эксперт
  или админ), решения идут через сервисные переходы B4.
- **Правила очереди слов (B7):** `dictionary/queue.py` — чистая таблица переходов
  `new → queued → recorded` (и `queued → new`, `recorded → queued`), функции
  `can_transition`/`allowed_targets`/`validate_transition`, исключение
  `UnknownWordTransitionError`. Значения `UnknownWordStatus` совпадают с моделью.
- **Сервис очереди (B7):** `record_unknown_word(lemma, lang)` агрегирует повторы
  по `(lemma, lang)` (`count += 1`, `last_seen_at`); `record_unknown_words`,
  `list_unknown_words` (сверху частые, без `recorded` по умолчанию, фильтры по
  языку и статусу), `unknown_word_payload`, `transition_unknown_word`,
  `queue_unknown_word` (`new`/`recorded → queued`), `mark_unknown_word_recorded`
  (`queued → recorded`). Исключение `UnknownWordValidationError`.
- **Интерфейс редактора (B7):** очередь `GET /dictionary/queue/` (таблица со
  словом, счётчиком, языком, статусом, датой и кнопками «Взять в работу» /
  «Записать жест») и действие `POST /dictionary/queue/<id>/action/`. Доступ через
  `dictionary.permissions.dictionary_required` (редактор/эксперт/админ).
- **Админка очереди (B7):** в `UnknownWordAdmin` действия «Взять в работу» и
  «Пометить записанными» через сервис, запрещённый переход пропускается.
- **Модуль аватара (C1):** `frontend/avatar.ts` — класс `Avatar`: сцена Three.js,
  мягкий свет (ambient + key + rim + hemisphere), перспективная камера с кадром
  «по грудь», загрузка VRM через `GLTFLoader` + `VRMLoaderPlugin`
  (`@pixiv/three-vrm`). При загрузке модель оптимизируется
  (`removeUnnecessaryVertices`, `combineSkeletons`, `combineMorphs`,
  `rotateVRM0`) и ставится в нейтральную позу (`normalizedRestPose`).
  Кадр анимации обновляет `vrm.update(delta)` и рисует сцену; `dispose()`
  останавливает цикл, снимает слушатели и освобождает WebGL-ресурсы.
- **Тестовая страница аватара (C1):** `GET /avatar/` → `config.views.avatar_test`,
  шаблон `templates/static_pages/avatar.html`, точка входа
  `frontend/avatar-page.ts`. Страница публичная: контейнер сцены, статус
  загрузки, поле для URL модели и загрузка по кнопке. URL модели берётся из
  поля или из настройки `AVATAR_MODEL_URL` (`.env`); без модели сцена, камера и
  свет работают, а страница показывает подсказку.
- **Декодер клипа (C2):** `frontend/clip.ts` — чистая функция
  `decodeClip(ArrayBuffer|Uint8Array)`: `.json.gz` → `gzip` (`DecompressionStream`)
  → `JSON` → `base64` → `Float16` → `Float32Array`. Также
  `decodeClipPayload(payload)` (готовый объект), хелперы `base64ToBytes`,
  `gunzip`, `readFloat16`, `float16ToFloat32`, `pointAt`, константа
  `CLIP_VERSION` и ошибка `ClipDecodeError`. Разбор проверяет версию, `fps`,
  целые `frames`, непустой `layout` с положительными частями, непустые `data` и
  совпадение размера (`frames × points × 3`). `layout` превращается в `offsets`
  (смещения частей — для ретаргета C3).
- **Тесты клиента (C2):** `frontend/clip.test.ts` (vitest, окружение Node) на
  фикстуре `frontend/clip.fixture.ts` — настоящий файл формата (Float16 → gzip →
  base64 → JSON → `.json.gz`). Проверяются Float16 (эталонные биты, ноль,
  субнормальные, NaN/бесконечность), base64, gunzip, разбор `layout`/смещений,
  значения по кадрам, `pointAt`, все ветки ошибок. `npm test` подключён к
  `make check` (`client-test`).
- **Фильтр One Euro (C3):** `frontend/one-euro.ts` — `OneEuroFilter` (одна
  величина), `OneEuroPoint` (точка `{x,y,z}`), `OneEuroLandmarks` (набор точек
  кадра). Алгоритм Casiez et al. (CHI 2012): оценка скорости, срез растёт со
  скоростью (`minCutoff` + `beta·|dx|`). Параметры по умолчанию под 30 FPS.
- **Ретаргет (C3):** `frontend/retarget.ts` — `splitFrame` разбивает кадр клипа
  на части MediaPipe (`pose`, `hand_l`, `hand_r`, `face`) по `offsets` из C2;
  `retargetParts`/`retargetFrame` вызывают Kalidokit (`Pose.solve`,
  `Hand.solve`, `Face.solve`) и возвращают чистые числа: углы костей туловища и
  рук, позы пальцев, мимику (`RetargetedFrame`). Kalidokit не зависит от
  Three.js здесь — ретаргет тестируется в vitest.
- **Применение к VRM (C3):** `frontend/vrm-rig.ts` — `applyRetargetedFrame`
  раскладывает углы по костям `humanoid` (`rightUpperArm` и т.д.), пальцам
  (`rightIndexProximal`, большой палец `Intermediate → Metacarpal`) и выражениям
  (`blinkLeft/Right`, `aa/ee/ih/oh/ou`); `resetToNeutral` возвращает rest pose и
  нулевую мимику. Углы ограничиваются, поза бёдер переносится в уменьшенном
  масштабе.
- **Проигрыватель клипа (C3):** `frontend/clip-player.ts` — `ClipPlayer` идёт по
  кадрам с частотой `fps × speed`, сглаживает landmarks One Euro по частям
  (сохраняя `visibility` позы), ретаргетит и применяет к VRM; `start`/`stop`,
  `loop`, `onEnd`, `dispose`.
- **Демо-клип (C3):** `frontend/demo-clip.ts` — `encodeDemoClip` собирает в
  браузере синтетический клип «машущие пальцы» (Float16 → gzip → base64) в том же
  формате, что и инструмент записи: на тестовой странице есть что проиграть без
  файлов и словаря.
- **Тестовая страница аватара (C3):** на `/avatar/` добавлены «Демо-клип»,
  «Играть», «Стоп» и выбор файла `.json.gz`; статус клипа показывается рядом.
- **Планировщик очереди (C4):** `frontend/clip-queue.ts` — чистая функция
  `planQueue(clips, options)`: считает отрезки очереди с абсолютным временем
  (`startMs`/`endMs`/`durationMs`), зонами crossfade (`fadeInMs`/`fadeOutMs`) и
  скоростью. Зажимает скорость в 0.6–1.3x (`MIN_SPEED`/`MAX_SPEED`), длину
  перехода — в 150–250 мс (`clampCrossfade`), ужимает переход до половины
  короткого клипа (дактиль), поддерживает паузу между фразами (`gapMs`).
  Хелперы `frameAt`, `segmentAt`, `blendAt`, `tailNeutralAt`, `toQueueClip`,
  константы `DEFAULT_CROSSFADE_MS`, `DACTYL_CROSSFADE_MS`, `NEUTRAL_FADE_MS`.
- **Блендинг (C4):** `frontend/clip-blend.ts` — `lerpFrames`/`crossfade`/
  `fadeToNeutral`/`ease`/`neutralFrame`: смешивают кадры ретаргета (кости,
  пальцы, мимика) линейной интерполяцией с smoothstep. Отсутствующая часть кадра
  считается нейтральной (нули), поэтому `fadeToNeutral` реально уводит позу в
  нейтраль, а не «застывает».
- **Игрок очереди (C4):** `frontend/clip-player.ts` — `loadQueue(clips)` принимает
  очередь и планирует её через `planQueue`; `tick` идёт по кадрам, на стыке
  смешивает кадры двух клипов, между фразами держит нейтральную позу (`gapMs`),
  в конце плавно уходит в нейтраль. Опции `speed`, `crossfadeMs`, `gapMs`,
  `loop`, `onClip`; геттеры `currentClip`, `clipCount`, `crossfadeFrameCount`,
  `queue`. `load(clip)` остаётся обёрткой над `loadQueue([clip])`.
- **Демо-очередь (C4):** `frontend/demo-clip.ts` — `encodeDemoClip(frames, fps,
  variant)` строит варианты жеста, `encodeDemoQueue()` — очередь из трёх разных
  клипов (40/30/50 кадров) для ручной проверки блендинга.
- **Тестовая страница аватара (C4):** на `/avatar/` добавлены кнопка «Очередь
  демо-клипов», поля скорости (0.6–1.3x) и паузы между фразами, а выбор файла
  `.json.gz` стал множественным — файлы играются очередью.
- **Дактиль (C5):** `frontend/dactyl.ts` — русский алфавит дактиля
  (`DACTYL_ALPHABET`, 33 буквы; `DACTYL_DIGITS`, 0–9), нормализация символа
  (`normalizeChar`: верхний регистр + замена похожих латинских), глоссы
  (`letterGloss`: `ДАКТИЛЬ_А`, `ЦИФРА_5`), разбор текста на знаки (`splitWord`:
  буквы, цифры, пробелы как пауза; пунктуация отбрасывается) и тайминги
  (`dactylTimeline`): буквы идут подряд с укороченным перекрытием
  (`DACTYL_LETTER_MS`/`DACTYL_CROSSFADE_MS`), пробел — пауза
  (`DACTYL_WORD_GAP_MS`), скорость сокращает и показ, и переходы.
- **Сборка дактиль-очереди (C5):** `buildDactylQueue(text, resolve, options)` —
  резолвер `DactylClipResolver` (глосса → клип) сопоставляет буквы клипам, план
  строится в режиме `dactyl`; `DactylQueue` отдаёт знаки, клипы и `QueuePlan`.
- **Режим `dactyl` в планировщике (C5):** `QueuePlan.mode` и
  `QueuePlanOptions.mode`, `clampCrossfadeFor` — для дактиля нижняя граница
  перехода 0 (буквы склеиваются на 80 мс), для фразы остаётся 150–250 мс.
- **Игрок (C5):** опция `ClipPlayerOptions.mode` передаётся в планировщик, поэтому
  одна и та же очередь играется и как фраза, и как дактиль.
- **Синтетические буквы (C5):** `frontend/demo-clip.ts` — `encodeDactylClip`
  (форма пальцев зависит от буквы: `dactylFingerPattern`), `encodeDactylWord`,
  `encodeNeutralPauseClip` (клип паузы для пробела). Реальные клипы букв пишет
  блок D.
- **Тестовая страница аватара (C5):** блок «Дактиль» на `/avatar/` — ввод слова
  и кнопка «Показать по буквам»; страница собирает по клипу на знак и играет
  очередь в режиме `dactyl`.
- **Субтитры (C6):** `frontend/subtitles.ts` — типы глосс по ТЗ 7.2
  (`GlossToken`/`UtteranceGlosses`: `sign`/`number`/`fingerspell`), сопоставление
  токена и слова текста (`alignTokens`: поиск от курсора вперёд, ё→е, пунктуация
  не входит в диапазон), глосса единицы (`tokenGloss`), раскладка фразы на
  единицы показа (`utteranceUnits`: жест/число — одна, дактиль — по буквам),
  соответствие отрезков плана токенам (`segmentsToTokens`), активное слово по
  времени очереди (`activeTokenAt`/`activeWordAt` через `segmentAt` из C4),
  разбивка текста на куски (`subtitlePieces`) и отрисовка (`SubtitleView`:
  подсветка текущего слова, `aria-current`). Размер и контраст — `SUBTITLE_SIZES`
  (`small/medium/large`), `SUBTITLE_THEMES` (`dark/light`),
  `subtitleSizeClass`/`subtitleThemeClass`; CSS-классы в `static/css/base.css`.
- **Синтетическая фраза (C6):** `frontend/demo-phrase.ts` — `DEMO_PHRASE`
  (жесты, число, слово по буквам) и `encodePhraseClips` (клип на каждую единицу:
  жест — демо-клип, буква — `encodeDactylClip`).
- **Тестовая страница аватара (C6):** блок «Субтитры» на `/avatar/` — кнопка
  «Фраза с субтитрами» собирает фразу, рисует субтитр и подсвечивает слово по
  текущему клипу очереди (`onClip`).
- **Настройки студента (C7):** `frontend/student-settings.ts` — ограничения
  FR-13 (скорость 0.6–1.2x, размер 0.6–1.6, сдвиг ±40%), нормализация частичных
  и битых данных (`normalizeStudentSettings`/`parseStudentSettings`), хранение в
  `localStorage` (`loadStudentSettings`/`saveStudentSettings`, ключ
  `gluho-nemye:student-settings:v1`), CSS-переменные сцены (`studentSettingsCss`)
  и темы фона (`STUDENT_THEME_BACKGROUNDS`). Настройки переживают перезагрузку.
- **Скорость на ходу (C7):** `ClipPlayer.setSpeed` пересобирает план очереди C4
  под новую скорость, сохраняя текущий клип и кадр; играющая фраза не
  останавливается.
- **Тестовая страница аватара (C7):** блок «Настройки студента» на `/avatar/` —
  ползунки скорости, размера и положения, выбор тёмного/светлого фона и сброс.
  Размер/положение — CSS-переменные `--avatar-size`/`--avatar-offset-*` на сцене,
  фон меняется и в CSS, и в сцене Three.js (`Avatar.setBackground`), тема
  субтитров следует за фоном.
- **Лента расшифровки (C8):** `frontend/transcript.ts` — прокручиваемый список
  фраз под аватаром, чтобы можно было перечитать пропущенное (субтитр C6
  показывает только текущую). Чистая часть: `appendTranscript` (дубли по `seq`,
  безымянная строка `asr_text` заменяется нумерованной фразой, предел
  `TRANSCRIPT_MAX_LINES` = 200), `lastKnownSeq`, `shouldStickToBottom` (не
  дёргать ленту, если студент читает выше). `TranscriptView` — DOM-слой
  (`role="log"`, текущая строка `transcript-line-current`). В `room-live.ts`
  лента наполняется из `asr_text`, `utterance` и догрузки `fetchMissed` после
  переподключения; разметка — в `templates/rooms/student.html`
  (`data-room-transcript`), стили — в `static/css/base.css` (в т.ч. светлая
  тема FR-13).
- **Уведомления студента (C8):** `frontend/notifications.ts` — правило
  `notificationKindFor` (новая фраза — `utterance`, ответ преподавателя —
  `chat_message` с `is_teacher`), узоры вибрации `NOTIFICATION_VIBRATION`,
  `vibrate` с терпимостью к неподдерживаемому API, `ScreenWakeLock` (запрос
  `screen`, повтор после возврата вкладки, освобождение) и `ScreenNotifier`
  (подсветка `body.notification-flash`, текст в `aria-live`).
- **Wake Lock в комнате (C8, FR-25):** на странице студента экран удерживается
  включённым, статус виден рядом с состоянием сокета; при отказе браузера
  показывается причина и делается одна повторная попытка после касания. При
  закрытии комнаты, удалении участника и уходе со страницы блокировка снимается.
- **Подсветка и вибрация (C8, FR-26):** новая фраза и ответ преподавателя в чате
  подсвечивают экран (CSS-анимация `body.notification-flash::after`) и дают
  короткую вибрацию там, где есть `navigator.vibrate`. История чата при
  переподключении не уведомляет; панель преподавателя не мигает.
- **MediaPipe Holistic (D1):** `frontend/holistic.ts` лениво загружает
  `@mediapipe/tasks-vision` (1.1.1), WASM из `static/dist/mediapipe` и модель
  `holistic_landmarker.task`; при недоступности GPU повторяет создание на CPU,
  а метки времени для режима VIDEO делает строго возрастающими.
  `normalizeHolisticResult` приводит ответ к кадрам «поза / лицо / левая и правая
  кисть» и тестируется без DOM.
- **Предпросмотр скелета (D1):** `frontend/skeleton.ts` — чистые функции
  `coverTransform`, `mapLandmark`, `skeletonSegments` и `drawSkeleton`. Учитывает
  `object-fit: cover`, зеркальную камеру, порог видимости точек и рисует позу,
  контур лица, глаза, брови, губы и обе кисти.
- **Инструмент записи (D1):** страница `GET /dictionary/record/` (только роли
  словаря) включает камеру по кнопке, показывает видео и скелет поверх него,
  счётчик кадров и найденные кисти. Видео не уходит на сервер. WASM копируется
  Vite-плагином, модель задаётся `MEDIAPIPE_HOLISTIC_MODEL_URL`.
- **Упаковка клипа (D2):** `frontend/clip-encode.ts` — кодирование
  `Float32 → Float16 little-endian → gzip → base64`, payload версии 1 с layout
  `{pose:33, hand_l:21, hand_r:21, face:468}` и файл `.json.gz`. Размер данных
  проверяется как `frames × points × 3`; упакованный файл читается декодером C2
  (`frontend/clip.ts`) без потери структуры.
- **Запись и обрезка (D2):** `frontend/clip-record.ts` — автоматическая обрезка
  начала и конца по позе/кистям, ручной диапазон, пересэмплирование на 30 FPS
  (ближайший исходный кадр), добор пропавших кистей/лица (предыдущий кадр или
  нейтральная заготовка), One Euro и `encodeRecordedClip`. На странице записи —
  кнопки старт/стоп, таймер, автолимит по `CLIP_MAX_FRAMES`, ползунки обрезки,
  сборка и контрольная распаковка, скачивание `.json.gz`. Лимиты кадров и
  размера передаются из настроек Django.
- **Предпросмотр на аватаре (D3):** после сборки `frontend/record-page.ts`
  лениво создаёт `Avatar` и загружает `AVATAR_MODEL_URL` (если он задан), а
  затем проигрывает клип через `ClipPlayer` с `smoothing: false` — клип уже
  сглажен One Euro на D2, повторное сглаживание только добавило бы лаг. На
  странице есть «Играть» и «Стоп». Модель не скачивается, пока нет записанного
  клипа; ошибка модели или WebGL показывается предупреждением и не мешает
  сохранению черновика.
- **Сохранение черновика (D3):** `frontend/sign-draft.ts` нормализует глоссу и
  описание, проверяет язык по `Language.choices`, собирает
  `multipart/form-data` и отправляет `POST /api/signs/` с CSRF-заголовком.
  `record-page.ts` блокирует повторную отправку, показывает текст ошибки API и
  после успеха открывает персоналу ссылку в Django Admin. Жест создаётся со
  статусом `draft` и виден в `/admin/dictionary/sign/`.
- **Запись из очереди (D4):** у слова в статусе `queued` кнопка «Записать жест»
  ведёт на `/dictionary/record/?word=<id>`. Страница проверяет, что слово ещё
  не записано, подставляет его лемму и язык в форму и показывает, сколько раз
  оно встретилось. `POST /api/signs/` принимает необязательное поле
  `unknown_word`: сервис проверяет статус `queued` и в той же транзакции, что
  создаёт `Sign` и `SignClip`, переводит слово в `recorded`. В ответе приходит
  `unknown_word`, а страница показывает «Слово … отмечено записанным» и ссылку
  назад в очередь. Слова в статусах `new` и `recorded` по прямой ссылке
  возвращают в очередь с сообщением.
- **Упрощённые глоссы (E1):** `pipeline/glosses.py` — чистая часть конвейера:
  разбор текста на слова (`split_words`), нормализация (`normalize_word`:
  регистр, ё→е), русский алфавит дактиля и `word_letters` (латинские похожие
  буквы → кириллица, цифры сохраняются), `sentence_type` и
  `build_simplified_glosses`. Проверенное слово словаря даёт токен `sign`
  (`gloss`, `src`, `markers`), число — `number` (`value`), незнакомое слово —
  `fingerspell` (`letters`) и попадает в `unknown`.
- **Сервис фразы (E1):** `pipeline/services.py` — `create_utterance(room, text)`
  нормализует текст, выбирает язык жестов по комнате (`ru` → `rsl`, `kk` →
  `ksl`), строит глоссы, измеряет `gloss_ms` и сохраняет `Utterance`.
  Проверенный словарь берётся через `verified_sign_glosses` (только
  `SignStatus.VERIFIED`), незнакомые слова — через `record_unknown_words`, каждое
  вхождение увеличивает счётчик B7. `seq` выдаётся под `select_for_update` строки
  комнаты, поэтому две одновременные фразы не получат один номер; запись фразы и
  очереди идёт в одной транзакции. `asr_ms` принимается снаружи для будущего E2,
  пустой текст и текст длиннее 2000 символов отклоняются
  `UtteranceValidationError`.
- **Фоновая очередь фраз (E2):** `pipeline/queue.py` — `PipelineQueue` держит
  `asyncio.Queue` и одну задачу-обработчик на комнату (порядок фраз строго
  сохраняется) и глобальный `asyncio.Semaphore` на `ASR_MAX_CONCURRENCY`.
  Очередь комнаты ограничена `ROOM_QUEUE_MAX`; при переполнении самое старое
  ожидающее задание снимается (`RoomQueueFullError`). Цикл событий очереди живёт
  в отдельном daemon-потоке, поэтому синхронное Django-вью ставит задание и не
  ждёт обработки; сама обработка идёт в `asyncio.to_thread`. `submit` возвращает
  `Future` с `Utterance` (для тестов и диагностики), ошибка одного задания не
  останавливает воркер комнаты. `wait_for_idle`/`close` — для тестов и остановки.
- **Приём текста (E2):** `POST /api/rooms/<code>/text/` →
  `pipeline.api.text_api`. Принимает JSON `{"text": "..."}` или поле формы
  `text`, нормализует его и ставит в очередь с `started_at`; ответ **202**
  `{"status": "accepted"}`. Аноним — 401, не владелец комнаты (даже другой
  преподаватель/гость) — 403, закрытая или неизвестная комната — 404, пустой или
  слишком длинный текст — 400. Администратор может отправлять текст в любую
  открытую комнату. Запрос не создаёт `Utterance` синхронно и не блокирует
  WebSocket-чат.
- **Живые фразы (E3):** `pipeline/events.py` — `asr_text` уходит в группу
  `room_<id>` до обработки глосс, а после сохранения `Utterance` — событие
  `utterance` с объектом глосс и массивом `clips`. Клипы собираются только по
  проверенным жестам (`SignStatus.VERIFIED`) в порядке показа: жест/число —
  один клип, дактиль — по клипу на каждую найденную букву. В ссылке есть
  `token_index` (для подсветки слова), `kind`, `gloss`, `url`, `fps`, `frames`,
  `duration_ms`, версия и id клипа; отсутствующие клипы пропускаются, фраза
  остаётся в субтитрах. `RoomConsumer` получил обработчики `asr_text` и
  `utterance`. Фоновый поток очереди отправляет `group_send` в запомненный цикл
  ASGI через `run_coroutine_threadsafe`, поэтому InMemoryChannelLayer в
  разработке и тестах не используется из чужого цикла.
- **Студент E3:** `frontend/room-clips.ts` — чистый разбор ссылок, параллельная
  загрузка/декодирование клипов и `PhraseQueue` с дедупликацией по `seq`;
  `frontend/room-phrase.ts` (ленивый динамический импорт) создаёт `Avatar`,
  ставит клипы в `ClipPlayer`, подсвечивает слова в `SubtitleView`, а без
  VRM/клипов показывает субтитры по длительности. `frontend/room-live.ts`
  показывает `asr_text` сразу, ставит `utterance` в очередь и готов принять
  историю фраз, когда сервер начнёт её отдавать. Страница студента получила
  сцену аватара, живой текст, субтитры, статус и `AVATAR_MODEL_URL` из настроек.
- **Отставание и обратная связь (E4):** `PipelineQueue` уже измеряет `asr_ms` и
  `gloss_ms`, а `pipeline/services.py` заполняет `display_lag_ms` по событию
  `display_started` от студента. Отставание считается от `started_at` фразы до
  фактического начала показа; первое событие фиксирует метрику, повторное её не
  увеличивает. `lag_level` делит по FR-15: `green` ≤5 с, `yellow` ≤10 с,
  `red` >10 с. `RoomConsumer` принимает `display_started`, проверяет, что фраза
  принадлежит комнате, и рассылает `lag_status`; `unknown_words` уходит вместе
  с `utterance` из `unknown`-глоссов. `lag_status` и `unknown_words` отдаются
  только преподавательским соединениям; F8 добавил студенту отдельное событие
  `playback`. Клиент студента шлёт `display_started` из `RoomPhrasePlayer` в
  момент начала показа, а панель преподавателя показывает цветной индикатор,
  подсказку «замедлитесь» и слова без жеста.
- **Панель преподавателя (E5):** на `/rooms/<code>/live/` появилась форма ввода
  фразы и лента последних `Utterance` с номером, временем, текстом и словами без
  жеста. Форма отправляется через HTMX в `POST /rooms/<code>/live/phrase/`:
  текст нормализуется той же проверкой, что в E2, ставится в очередь, а ответ
  заменяет фрагмент формы и шлёт `HX-Trigger: phrase-saved`. Лента
  (`GET /rooms/<code>/live/feed/`) обновляется по этому событию, по WebSocket
  `utterance` и раз в 3 секунды как запасной вариант. Без HTMX форма работает
  обычным POST с редиректом и сообщением. Начальный список слов без жеста
  берётся из последней фразы, дальше его обновляет E4-событие `unknown_words`.
  Права прежние: владелец комнаты или администратор, остальные — 403.
- **LLM-глоссы (F1):** `services/gloss.py` — чистый модуль без Django.
  `LLMProvider` (Protocol) получает промпт и JSON-схему, возвращает строку;
  `CallableProvider` адаптирует функцию, провайдер по умолчанию задаётся
  `set_default_provider` (F4 строит его из настроек). `gloss_response_schema` описывает
  ответ ТЗ 7.2 (`lang`, `text`, `sentence_type`, `tokens` типов
  `sign`/`number`/`fingerspell`, `unknown`). `build_gloss_prompt` собирает
  правила РЖЯ, проверенные глоссы, few-shot примеры и схему;
  `parse_gloss_response`/`validate_glosses` проверяют JSON (в том числе в
  ```-блоке), нормализуют числа, маркеры и буквы, подставляя исходные
  `text`/`lang`. `GlossDictionary` индексирует глоссы с нормализацией (регистр,
  ё→е), `restrict_to_dictionary` оставляет только глоссы словаря, а всё
  остальное превращает в дактиль и пересобирает `unknown`. `GlossCache` — LRU в
  памяти процесса, ключ `gloss_cache_key` — SHA-256 от нормализованной фразы,
  языка, версии/содержимого словаря и примеров; битые ответы и ошибки
  провайдера не кэшируются. `to_glosses(text, lang, GlossDictionary, *,
  provider, cache, timeout, examples)` — точка входа; ошибки провайдера
  оборачиваются в `LLMUnavailableError`, невалидный ответ — в
  `GlossFormatError`.
- **Запасной режим без LLM (F2):** `services/morphology.py` — ленивая загрузка
  `pymorphy3` (словарь грузится при первом разборе), `word_forms` (все разборы
  с нормальной формой и частью речи, кэш на 8192 слова), `lemmatize_word`,
  `lemmatize_words`, `split_words`, `clean_word`, `is_function_word`,
  `FUNCTION_POS` (`PREP`/`CONJ`/`PRCL`/`INTJ`). `services.gloss.fallback_glosses`
  ищет слово в словаре сначала в исходной форме, затем по нормальным формам
  («учебнике» → «учебник»), числа словами превращает в токены `number`
  (`десять` → 10), служебные части речи без жеста опускает, остальные значимые
  слова отдаёт дактилем и в `unknown`. Для `ksl` русская морфология не
  применяется — только точная форма. Результат проходит ту же
  `validate_glosses`, что и ответ LLM.
- **Сжатие фразы (F3):** `services.gloss.compress(text, target_ratio, *,
  provider, timeout)` — сначала LLM с промптом «убери вводные, сохрани смысл и
  числа» и JSON-схемой `{"text": "..."}` (ответ допускается в ```-блоке). Если
  провайдер не настроен, упал, вернул мусор или текст не короче исходного,
  работает `compress_locally`: удаление вводных оборотов и слов-заполнителей
  («итак», «как вы знаете», «в общем», «пожалуйста», «ребята»…), нормализация
  пробелов и пунктуации, затем обрезка по границе слова до целевой длины.
  `target_ratio` — строго от 0 до 1; `compress_response_schema` и
  `build_compress_prompt` публичные. Для длинной фразы результат всегда короче
  исходной; фразу из одного короткого слова сжимать нечего.
- **Конвейер LLM-глосс (F4):** `services/llm.py` — HTTP-провайдер на stdlib
  (`urlopen`) для OpenAI-compatible API и Ollama; создаётся из
  `LLM_PROVIDER`/`LLM_MODEL`/`LLM_API_KEY`/`LLM_API_URL` только при заданной
  модели (для API ещё и ключе), иначе LLM считается ненастроенной.
  `pipeline/gloss_engine.py` собирает `GlossDictionary` из проверенных жестов и
  `DictionaryVersion.current`, вызывает `to_glosses`; в async-пути словарь
  читается через `database_sync_to_async`, а блокирующий HTTP — через
  `asyncio.to_thread` под `asyncio.wait_for(..., LLM_TIMEOUT)`. Нет провайдера →
  F2-резерв и `degraded=True`; ошибка/битый ответ/таймаут настроенной LLM →
  пустые `tokens` (только субтитры) и `degraded=True`. Очередь по умолчанию
  использует async-обработчик, а сохранение фразы принимает готовые глоссы,
  `gloss_ms` и `degraded`; `create_utterance` без них остаётся путём E1.
- **Распознавание речи (F5):** `services/asr.py` реализует контракт ТЗ 7.1
  `transcribe(audio, lang) -> AsrResult(text, duration_ms)`. Провайдер
  `FasterWhisperProvider` импортирует `faster-whisper` лениво и создаёт
  `WhisperModel` один раз под замком (`WHISPER_MODEL`, `WHISPER_DEVICE`; на CPU
  int8, на CUDA float16). `AsrService` держит отдельный `ThreadPoolExecutor` и
  `BoundedSemaphore(ASR_MAX_CONCURRENCY)`, принимает WAV/Opus байтами в памяти,
  даёт sync `transcribe` и async `transcribe_async`; аудио никуда не
  сохраняется. Модульные `services.asr.transcribe`/`transcribe_async` работают
  через общий сервис, а `set_asr_provider` позволяет подменить распознаватель.
- **Приём аудиофразы (F6):** `POST /api/rooms/<code>/phrase/`
  (`pipeline.api.phrase_api`) принимает multipart-аудио, проверяет, что это
  владелец комнаты/админ, и отвечает 202. Файл читается в память (лимит 2 МиБ),
  загруженный файл сразу закрывается, на диск и в БД аудио не пишется.
  `PipelineQueue.submit_audio` создаёт `AudioJob` в очереди комнаты, а
  `process_audio_job_async` вызывает `services.asr.transcribe_async` с
  `ASR_TIMEOUT=20`, измеряет `asr_ms` и передаёт распознанный текст в общий путь
  `asr_text` → глоссы → `Utterance` → `utterance`. Пустой результат ASR не
  создаёт фразу; ошибка/таймаут завершает `Future` ошибкой и логируется, не
  останавливая воркер комнаты.
- **Микрофон и VAD в браузере (F7):** на панели преподавателя есть карточка
  «Микрофон преподавателя» (`templates/rooms/_microphone.html`). `vad-web@0.7.0`
  загружается динамически только после нажатия кнопки, держит Silero VAD в Web
  Worker и отдаёт готовую фразу по паузе (16 кГц mono). `frontend/audio-phrase.ts`
  кодирует `Float32Array` в PCM16 WAV без внешних библиотек и отправляет
  multipart в F6 endpoint с CSRF; `frontend/microphone.ts` ведёт состояния
  (загрузка, слушаю, речь, отправка, ошибка), отправляет фразы последовательно
  и не блокирует текстовую форму FR-7. При закрытии комнаты или уходе со
  страницы запись останавливается; при ошибке доступа браузер подсказывает
  причину. `vad-web` использует `@huggingface/transformers` и скачивает модель
  Silero VAD при первом запуске (нужен HTTPS/localhost и исходящий доступ).
- `Makefile`: `setup`, `check`, `lint`, `format`, `test`, `up`, `down`, `migrate`,
  `seed-admin`, `client-dev`, `client-build`, `client-typecheck`, `client-test`.
- `pytest-django` + `ruff`, конфигурация в `pyproject.toml`.
- `AGENTS.md`, `.env.example`, `.dockerignore`, `.gitignore`, `README.md`.
- `docs/spec/` — 12 выжимок из ТЗ по разделам.

## Публичные точки входа

| Что | Где |
| --- | --- |
| Стартовая страница | `GET /` → `config.views.home` |
| Health | `GET /health/` → `config.views.health` |
| HTMX-фрагмент | `GET /partials/htmx-demo/` → `config.views.htmx_demo` |
| Тестовая страница аватара | `GET /avatar/` → `config.views.avatar_test` |
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
| Панель преподавателя | `GET /rooms/<code>/live/` → `rooms.views.room_live` |
| Отправка фразы из панели (HTMX) | `POST /rooms/<code>/live/phrase/` → `rooms.views.room_live_phrase` |
| Лента фраз (HTMX-фрагмент) | `GET /rooms/<code>/live/feed/` → `rooms.views.room_live_feed` |
| История для переподключения | `GET /api/rooms/<code>/history/?after_seq=&after_message_id=` → `rooms.api.chat_history_api` |
| Приём текста фразы (преподаватель) | `POST /api/rooms/<code>/text/` → `pipeline.api.text_api` |
| Приём аудиофразы (преподаватель) | `POST /api/rooms/<code>/phrase/` → `pipeline.api.phrase_api` |
| Файл клипа жеста (ETag/304) | `GET /media/clips/<id>.json.gz` → `dictionary.views.clip_file` |
| Список словаря (публичный) | `GET /api/dictionary/?lang=&status=` → `dictionary.api.dictionary_api` |
| Создание жеста (редактор) | `POST /api/signs/` → `dictionary.api.create_sign_api` |
| Решение эксперта (API) | `POST /api/signs/<id>/review/` → `dictionary.api.review_sign_api` |
| Очередь на проверке | `GET /dictionary/review/` → `dictionary.views.review_queue` |
| Карточка жеста (решение) | `GET/POST /dictionary/review/<id>/` → `dictionary.views.review_sign` |
| Очередь нераспознанных слов | `GET /dictionary/queue/` → `dictionary.views.unknown_queue` |
| Запись жеста с камеры (D1–D4) | `GET /dictionary/record/?word=<id>` → `dictionary.views.record_gesture` |
| Действие со словом очереди | `POST /dictionary/queue/<id>/action/` → `dictionary.views.unknown_word_action` |
| Закрыть комнату | `POST /rooms/<code>/close/` → `rooms.views.room_close` |
| Сменить ID комнаты | `POST /rooms/<code>/rotate-code/` → `rooms.views.room_rotate_code` |
| Удалить участника | `POST /rooms/<code>/participants/<id>/remove/` → `rooms.views.room_remove_participant` |
| Управление комнатой (сервис) | `rooms.management` (close_room, rotate_join_code, remove_participant) |
| Админка | `GET /admin/` (в т.ч. `/admin/dictionary/sign/`, `/admin/dictionary/signclip/`, `/admin/dictionary/unknownword/`, `/admin/dictionary/dictionaryversion/`) |
| WebSocket-эхо (только A2, DEBUG) | `WS /ws/echo/<group>/` → `config.consumers.EchoConsumer` |
| ASGI-приложение | `config.asgi:application` |
| WSGI-приложение | `config.wsgi:application` |
| JS-точка входа | `frontend/main.ts` → `{% vite_asset 'frontend/main.ts' %}` |
| JS страницы комнаты | `frontend/rooms.ts` → крупный режим и копирование ссылки |
| JS аватара (C1) | `frontend/avatar.ts` (класс `Avatar`), `frontend/avatar-page.ts` (страница) |
| JS декодера клипа (C2) | `frontend/clip.ts` (`decodeClip`, `decodeClipPayload`) |
| JS ретаргета (C3) | `frontend/retarget.ts`, `frontend/vrm-rig.ts`, `frontend/clip-player.ts`, `frontend/one-euro.ts`, `frontend/demo-clip.ts` |
| JS очереди и блендинга (C4) | `frontend/clip-queue.ts` (`planQueue`), `frontend/clip-blend.ts` |
| JS дактиля (C5) | `frontend/dactyl.ts` (`splitWord`, `dactylTimeline`, `buildDactylQueue`) |
| JS субтитров (C6) | `frontend/subtitles.ts` (`alignTokens`, `utteranceUnits`, `activeWordAt`, `SubtitleView`) |
| JS настроек студента (C7) | `frontend/student-settings.ts` (`loadStudentSettings`, `saveStudentSettings`, `StudentSettingsView`) |
| JS уведомлений и Wake Lock (C8) | `frontend/notifications.ts` (`notificationKindFor`, `vibrate`, `ScreenWakeLock`, `ScreenNotifier`) |
| JS MediaPipe и скелета (D1) | `frontend/holistic.ts` (`HolisticDetector`, `normalizeHolisticResult`), `frontend/skeleton.ts`, `frontend/record-page.ts` |
| JS записи и упаковки клипа (D2) | `frontend/clip-record.ts` (`encodeRecordedClip`, `autoTrimRange`, `resampleCapturedFrames`), `frontend/clip-encode.ts` (`encodeClipPayload`, `packClipFile`) |
| JS сохранения черновика (D3–D4) | `frontend/sign-draft.ts` (`validateSignDraft`, `submitSignDraft`, `unknown_word`), форма в `frontend/record-page.ts` |
| Сервис LLM-глосс (F1) | `services/gloss.py` (`to_glosses`, `build_gloss_prompt`, `gloss_response_schema`, `GlossDictionary`, `GlossCache`, `LLMProvider`) |
| Запасной режим глосс (F2) | `services/gloss.py:fallback_glosses`, `services/morphology.py` (`word_forms`, `lemmatize_word`, `is_function_word`) |
| Сжатие фразы (F3) | `services/gloss.py:compress`, `compress_locally`, `build_compress_prompt`, `compress_response_schema` |
| Конвейер LLM-глосс (F4) | `pipeline/gloss_engine.py` (`compute_glosses`, `compute_glosses_async`, `GlossOutcome`, `verified_gloss_dictionary`), `services/llm.py` (`HttpLLMProvider`, `provider_from_settings`), `pipeline/queue.py:process_text_job_async` |
| Распознавание речи (F5) | `services/asr.py` (`transcribe`, `transcribe_async`, `AsrResult`, `AsrProvider`, `FasterWhisperProvider`, `AsrService`) |
| Аудиофраза в конвейере (F6) | `pipeline/api.py:phrase_api`, `pipeline/queue.py` (`AudioJob`, `submit_audio`, `process_audio_job_async`, `process_phrase_job_async`) |
| Микрофон и VAD (F7) | `frontend/microphone.ts` (`MicrophoneController`, `setupMicrophone`), `frontend/audio-phrase.ts` (`encodeWav`, `uploadPhrase`), `templates/rooms/_microphone.html` |
| Политика догона (F8) | `pipeline/lag_policy.py` (`lag_playback_policy`, `should_compress`), `frontend/lag-policy.ts` (`normalizePlaybackPolicy`, `effectivePlaybackSpeed`) |

## Клиент: режимы

- **Production / образ:** `DJANGO_VITE_DEV_MODE=False`. Django читает
  `static/dist/manifest.json`, отдаёт хэшированные файлы через WhiteNoise.
- **Разработка:** `DJANGO_VITE_DEV_MODE=True`, `make client-dev`. Страница
  подключает `http://localhost:5173/static/dist/frontend/main.ts` и `@vite/client`.
- `base` в `vite.config.ts` (`/static/dist/`) и `static_url_prefix="dist"`
  согласованы: один URL работает в обоих режимах.

## Тесты

- `tests/test_smoke.py` — стартовая страница, health, HTMX-фрагмент.
- `tests/test_frontend.py` — манифест Vite и URL собранного ассета, точки входа
  тестовой страницы аватара (`frontend/avatar-page.ts`) и записи жеста
  (`frontend/record-page.ts`).
- `tests/test_avatar_page.py` — страница `GET /avatar/`: рендер без входа,
  контейнер сцены и атрибуты модуля, передача `AVATAR_MODEL_URL` в шаблон и
  подсказка при пустой модели; поля настроек студента (C7).
- `rooms/tests/test_join.py` — вход студента и страница комнаты; разметка
  уведомлений и Wake Lock (C8).
- `dictionary/tests/test_record_page.py` — страница D1–D4: вход, роли словаря,
  разметка камеры/холста/кнопок, передача моделей Holistic и аватара, пути WASM,
  элементы записи, обрезки, предпросмотра и формы метаданных, лимиты клипа,
  предзаполнение слова очереди, редиректы для `new`/`recorded` и 404.
- `frontend/clip-record.test.ts` (vitest) — конвейер D2: автообрезка, границы
  ручного диапазона, пересэмплирование на 30 FPS, добор частей скелета,
  сглаживание, лимит кадров, упаковка → распаковка C2, ретаргет без NaN.
- `frontend/clip-encode.test.ts` (vitest) — Float16 (известные биты, ноль,
  субнормальное, бесконечность), base64, gzip, payload версии 1, проверка
  размера данных и чтение `.json.gz` декодером C2.
- `frontend/sign-draft.test.ts` (vitest) — D3–D4: нормализация глоссы и
  описания, проверка обязательной глоссы/длины/языка, multipart-поля, CSRF и
  `unknown_word`, текст ошибки API, отказ на ответ без номера созданного жеста.
- `frontend/holistic.test.ts` (vitest) — разбор ответа MediaPipe: вложенные и
  плоские наборы, мусор, пустой кадр, определение кистей.
- `frontend/skeleton.test.ts` (vitest) — геометрия предпросмотра: `object-fit:
  cover`, зеркалирование, рёбра позы и кистей, порог видимости, фильтр групп.
- `frontend/clip.test.ts` (vitest) — декодер формата клипа (C2): Float16 → Float32,
  base64, gzip, разбор `layout` и смещений, значения landmark'ов по кадрам,
  `pointAt`, ошибки (версия, `fps`, `frames`, `layout`, `data`, размер, не-gzip,
  не-JSON). Фикстура `frontend/clip.fixture.ts` собирает настоящий файл клипа.
- `frontend/one-euro.test.ts` (vitest) — фильтр One Euro (C3): первый кадр без
  изменений, сглаживание шума, меньший лаг при большой `beta`, сходимость,
  интервал между кадрами, `reset`, фильтр точки и набора точек.
- `frontend/retarget.test.ts` (vitest) — ретаргет (C3) на синтетическом скелете
  (`frontend/retarget.fixture.ts`, MediaPipe-формат): разбиение кадра по частям,
  `visibility` позы, позы костей и пальцев, реакция на подъём руки и сгиб пальцев,
  мимика, отсутствие позы.
- `frontend/vrm-rig.test.ts` (vitest) — применение поз к VRM (C3) на структурной
  заглушке: раскладка по костям рук и пальцев, большой палец (`Intermediate →
  Metacarpal`), выражения мимики, ограничение углов, перенос позиции бёдер,
  `resetToNeutral`, отсутствие кости не роняет.
- `frontend/clip-player.test.ts` (vitest) — проигрыватель (C3): загрузка и
  нейтральная поза, прогон кадров через `tick`, остановка на конце, цикл,
  сглаживание сохраняет `visibility`, `start`/`stop`/`dispose`.
- `frontend/demo-clip.test.ts` (vitest) — демо-клип (C3): формат v1, декодирование,
  движение пальцев по кадрам, лицо; проверяет путь ручной проверки целиком.
  Варианты жеста, `encodeDemoQueue` (C4): три клипа разной длины, все валидны.
  Синтетические буквы дактиля (C5): `encodeDactylClip` с глоссой `ДАКТИЛЬ_*`,
  разные формы пальцев у разных букв, `encodeNeutralPauseClip`, `encodeDactylWord`.
- `frontend/clip-queue.test.ts` (vitest) — планировщик очереди (C4): зажим
  скорости и crossfade, раскладка отрезков с перекрытием, границы перехода для
  коротких клипов, пауза между фразами, `frameAt`/`segmentAt`/`blendAt`/
  `tailNeutralAt`, `toQueueClip`.
- `frontend/clip-blend.test.ts` (vitest) — блендинг (C4): `ease` (границы,
  зажим), `lerpFrames` (кости, пальцы, мимика, границы, слияние с нейтралью),
  `crossfade`, `fadeToNeutral`, `neutralFrame`.
- `frontend/clip-player-queue.test.ts` (vitest) — очередь в игроке (C4): план при
  загрузке, порядок клипов, пауза в нейтральной позе, crossfade на стыке, цикл,
  зажим скорости, смена скорости на ходу без перезапуска (C7), уход в нейтраль
  в конце, `dispose`; режим `dactyl` (C5) — укороченный переход передаётся в
  план игрока.
- `frontend/dactyl.test.ts` (vitest) — дактиль (C5): алфавит (33 буквы + цифры),
  нормализация и замена латинских, разбор слова на буквы и пробелы, пунктуация,
  глоссы, тайминги букв с укороченным перекрытием, пауза между словами, скорость,
  зажим перехода, `buildDactylQueue` (сопоставление знак→клип, пропуск без
  клипа), режим `dactyl` в планировщике.
- `frontend/subtitles.test.ts` (vitest) — субтитры (C6): нормализация слова и
  разбор текста, сопоставление токенов и слов текста (порядок, повторяющиеся
  слова, лемма, пропуск без источника), глоссы, единицы показа (жест/число/
  дактиль), отображение отрезков на токены, активное слово по времени очереди,
  куски текста (пунктуация сохраняется), размер и контраст.
- `frontend/demo-phrase.test.ts` (vitest) — синтетическая фраза (C6): состав
  токенов, единицы показа, нахождение слова для каждой единицы, клип на каждую
  единицу, глоссы дактиля, декодирование всех клипов.
- `frontend/student-settings.test.ts` (vitest) — настройки студента (C7):
  умолчания и частичные данные, зажим скорости 0.6–1.2x (FR-13), размера и
  положения, мусор и неизвестная тема, круговой обход JSON, сохранение между
  заходами в хранилище, битая запись, отсутствие хранилища, CSS-переменные и
  контрастный фон обеих тем.
- `frontend/notifications.test.ts` (vitest) — уведомления и Wake Lock (C8):
  правило «фраза/ответ преподавателя/тишина», панель преподавателя без
  уведомлений, узоры вибрации и отказ API, запрос экрана, повтор после возврата
  вкладки, освобождение, скрытый документ и отказ браузера.
- `tests/test_websocket.py` — два клиента одной группы получают сообщение,
  изоляция групп, отказ без разрешённого Origin, отключение echo вне DEBUG.
- `accounts/tests/` — модель и роли, регистрация/вход/выход, доступ к админке,
  команда `seed_admin` (создание, обновление, ошибки).
- `rooms/tests/` — формат и алфавит `join_code`, автогенерация кода, уникальность
  среди открытых комнат, повторное использование после закрытия, идемпотентное
  закрытие, повторы сервиса при коллизии, QR и ссылка `/r/<code>/`, страницы
  создания/просмотра/панели комнаты, доступ по ролям, JSON API создания и истории,
  вход студента (гостевая сессия, 404/410/429, name-валидация), rate limit, модель
  участника, модель сообщения и сервисные функции чата, `RoomConsumer` (изоляция
  комнат, 4401/4403, presence, ping/pong, чат, история, rate limit,
  `room_closed`/`participant_removed`, heartbeat: ping продлевает окно,
  молчащий клиент закрывается кодом 4408).
- `dictionary/tests/test_models.py` — значения по умолчанию, уникальность
  `Sign(gloss, lang)` только среди проверенных, дубли черновиков, жест в другом
  языке, `verify`, `best_clip` (версия и кадры), ограничения и порядок
  `UnknownWord`, версии словаря (`next_number`, `bump`, `current`).
- `pipeline/tests/test_models.py` — значения по умолчанию `Utterance`,
  уникальность `(room, seq)`, один `seq` в разных комнатах, порядок, `as_event`.
- `pipeline/tests/test_glosses.py` — чистые упрощённые глоссы E1: слова из
  словаря, дактиль незнакомого слова, порядок токенов, регистр и ё, числа,
  пунктуация и тип предложения, повторы в `unknown`, латиница и цифры в буквах,
  пустой текст.
- `pipeline/tests/test_services.py` — сервис E1: сохранение текста, глосс,
  `asr_ms`/`gloss_ms`/`started_at`, рост `seq` в комнате, очередь незнакомых слов
  (счётчик по каждому вхождению, без дублей в объекте глосс), только проверенные
  жесты, язык комнаты и явный язык, отказ на пустой/длинный текст и неизвестный
  язык.
- `pipeline/tests/test_queue.py` (E2) — порядок фраз одной комнаты, параллельная
  обработка разных комнат, глобальный предел `ASR_MAX_CONCURRENCY`, выброс
  самого старого задания при переполнении `ROOM_QUEUE_MAX`, продолжение работы
  после ошибки задания, `wait_for_idle`.
- `pipeline/tests/test_api.py` (E2) — права на `POST .../text/` (401/403/404),
  владелец и админ получают 202, нормализация текста, JSON и форма, пустой,
  отсутствующий, длинный текст и битый JSON (400), закрытая/неизвестная комната,
  отсутствие синхронного `Utterance`, ответ до завершения фоновой обработки.
- `pipeline/tests/test_processing.py` (E2) — фоновое задание с настоящим
  обработчиком создаёт `Utterance` с глоссами и `started_at`; E3 проверяет
  порядок `asr_text` → `utterance`.
- `pipeline/tests/test_events.py` (E3) — ссылки на клипы в порядке показа,
  лучший клип (версия/кадры), только проверенные жесты, пустой словарь,
  `utterance_event` и рассылка `asr.text`/`utterance` в `room_<id>`.
- `pipeline/tests/test_consumer_events.py` (E3) — `RoomConsumer.asr_text` и
  `RoomConsumer.utterance` отдают клиенту ожидаемый JSON.
- `frontend/room-clips.test.ts` (E3) — разбор ссылок, загрузка с пропуском
  битого клипа, сопоставление клипов словам, последовательная очередь и
  дедупликация по `seq`.
- `frontend/audio-phrase.test.ts` (F7) — PCM16 WAV 16 кГц mono: заголовок,
  little-endian сэмплы, обрезка диапазона, NaN/бесконечность, пустой фрагмент,
  неверная частота; multipart с `audio`, CSRF и same-origin, текст ошибки API,
  не-JSON ответ и обрыв сети.
- `frontend/microphone.test.ts` (F7) — понятные ошибки доступа/HTTPS, включение
  и остановка VAD, статусы «слушаю/речь/отправка», кодирование и отправка
  фразы, строгая последовательность при нескольких фразах, сохранение
  микрофона при ошибке сети, закрытая комната и повторный запуск после
  `disable`.
- `pipeline/tests/test_services.py` (E4) — пороги `lag_level` (5 и 10 с),
  сохранение `display_lag_ms`, идемпотентность `display_started` и отказ для
  фразы из чужой комнаты; `pipeline/tests/test_events.py` — `unknown_words` в
  рассылке; `rooms/tests/test_consumer.py` — `lag_status` и `unknown_words`
  получает только преподаватель, метрика сохраняется в БД.
- `rooms/tests/test_views.py` (E5) — панель показывает форму, ленту и слова без
  жеста; HTMX-фрагмент ленты содержит только фразы комнаты в порядке `seq`;
  отправка формы нормализует текст и ставит его в очередь, возвращает
  `HX-Trigger`, сохраняет ввод при ошибке, блокируется для закрытой комнаты и
  для чужого преподавателя; обычный POST делает редирект с сообщением.
  Панель содержит карточку микрофона с URL F6 endpoint, а в закрытой комнате
  кнопка VAD и подсказка отключены. `pipeline/tests/test_services.py` —
  последние фразы комнаты по возрастанию.
- `services/tests/test_clips.py` — `FileClipStorage`: сохранение/чтение,
  создание каталогов, `exists`, `open`, `size`, `delete`, стабильность и
  чувствительность ETag, сборка URL.
- `dictionary/tests/test_clip_view.py` — раздача клипа: тело ответа,
  `Cache-Control`/`ETag`, **304 на повторный запрос**, разные ETag у разных
  клипов, 404 для неизвестного клипа и отсутствующего файла.
- `services/tests/test_clip_format.py` — `pack_clip`/`parse_clip`: roundtrip,
  gzip/JSON, версия, `fps`/`frames`, лимит кадров, `layout`/`data`,
  `duration_ms`.
- `services/tests/test_gloss.py` (F1) — JSON-схема и промпт (правила, словарь,
  few-shot, пустой словарь), разбор ответа (```-блок, подстановка `text`/`lang`,
  числа, маркеры, буквы, 11 видов битых ответов), ограничение словарём
  (канонизация регистра/ё, выдуманная глосса → дактиль, пересборка `unknown`,
  язык словаря), кэш (хэш без лишних пробелов, версия словаря и язык в ключе,
  независимые копии, отсутствие кэша для ошибок, LRU, таймаут/схема провайдера,
  `CallableProvider`, примеры), 30 реальных фраз с моком LLM — формат корректен.
- `services/tests/test_fallback.py` (F2) — лемматизация (`учебнике` → `учебник`,
  части речи, пустой/незнакомый ввод, `split_words`), пословный перевод без LLM
  (лемма в словаре, служебные слова опускаются, но жест для них показывается,
  дактиль имён и дедупликация `unknown`), числа словами и цифрами, тип
  предложения, точные формы для `ksl`, валидация результата, 12 фраз без доступа
  к LLM, отказ на пустой текст/чужой язык.
- `services/tests/test_compress.py` (F3) — схема и промпт сжатия, разбор
  ```-блока и битых ответов, LLM-сжатие с таймаутом, резерв при длинном/битом
  ответе и ошибке провайдера, работа без провайдера, удаление вводных слов,
  обрезка по границе слова, короткая фраза без изменений, длина результата на
  наборе длинных фраз при 0.4/0.6/0.8, отказ на неверный `target_ratio` и
  пустой текст, отсутствие вызова LLM при неверном коэффициенте.
- `services/tests/test_llm.py` (F4) — провайдер не создаётся без модели/ключа,
  OpenAI-compatible и Ollama конфигурации, тело запроса (промпт, схема,
  `response_format`/`format`, auth, таймаут), разбор ответов, обёртка сетевых и
  битых ответов.
- `pipeline/tests/test_gloss_engine.py` (F4) — словарь только из проверенных
  жестов текущей версии, LLM-глоссы без деградации, F2 без провайдера,
  субтитры при ошибке/битом JSON, ограничение выдуманной глоссы, async-таймаут
  с проверкой, что тикер event loop продолжает работать.
- `pipeline/tests/test_f4_pipeline.py` (F4) — очередь по умолчанию сохраняет
  LLM-глоссы, ставит `fingerspell` в очередь незнакомых слов, без провайдера
  уходит в F2 с `degraded`, а зависший провайдер не задерживает `Future`:
  фраза сохраняется только субтитрами.
- `services/tests/test_asr.py` (F5) — валидный короткий WAV 16 кГц mono,
  текст из сегментов и длительность аудио, однократная загрузка модели (в том
  числе при параллельных первых вызовах), CPU int8/CUDA float16, отказ на
  пустое аудио/неизвестный язык, обёртка ошибок модели, лимит параллелизма
  пула и семафора, async-вызов без блокировки event loop, подмена провайдера.
- `pipeline/tests/test_phrase_api.py` (F6) — аноним 401, чужой 403, владелец и
  админ 202, закрытая/неизвестная комната 404, multipart-поле `audio`/`file`,
  пустой/не-аудио/слишком большой файл, отсутствие записи в БД и медиа,
  передача байтов и `started_at` в очередь, ответ без ожидания обработчика.
- `pipeline/tests/test_audio_processing.py` (F6) — ASR получает байты и язык
  комнаты (`ru`/`kk`), `ASR_TIMEOUT` доходит до сервиса, `asr_ms` сохраняется,
  `asr_text` приходит до `utterance`, казахская комната даёт `ksl`, пустой
  текст не создаёт фразу, ошибка ASR не останавливает воркер, подменённый
  провайдер ASR проходит через общий сервис, аудио не появляется в медиа.
- `dictionary/tests/test_statuses.py` — чистые правила переходов: разрешённые и
  запрещённые пары, требуемые роли, `allowed_targets`, совпадение значений
  `StrEnum` и `TextChoices`.
- `dictionary/tests/test_transitions.py` — сервис: отправка на ревью, утверждение
  и отклонение, рост версии словаря при `verified` (по языку), повторная подача
  отклонённого, переоткрытие проверенного, запрет роли (редактор не утверждает,
  преподаватель не подаёт), запрещённые переходы не меняют статус и не создают
  версию, `Sign.verify()` растит версию.
- `dictionary/tests/test_queue_rules.py` — чистые правила очереди: разрешённые и
  запрещённые переходы, `allowed_targets`, совпадение `StrEnum` и `TextChoices`.
- `dictionary/tests/test_queue.py` — агрегация повторов (критерий B7: одна запись,
  растущий счётчик, `last_seen_at`, отдельные языки, нормализация леммы),
  порядок списка по частоте, фильтры, переходы статусов, интерфейс редактора
  (доступ, список, пустая очередь, действие «взять в работу», ссылка на запись
  для `queued`).
- `dictionary/tests/test_review.py` — интерфейс эксперта: доступ к очереди и
  карточке (вход, роль), список только `review`-жестов, пустая очередь, ссылка
  на клип и предупреждение без клипа, решения через форму (утверждение с ростом
  версии, отклонение, отсутствие решения, запрещённый переход).
- `dictionary/tests/test_admin.py` — регистрация моделей словаря в админке,
  список и фильтр по статусу, поиск, порядок очереди нераспознанных слов,
  ссылка на файл клипа на странице жеста и «клипа пока нет», сквозной список
  клипов, действия переходов (отправка, утверждение с ростом версии, отклонение,
  пропуск запрещённого перехода), доступность админки только персоналу,
  версии словаря только на чтение, действия очереди слов.
- `dictionary/tests/test_api.py` — права доступа (аноним, преподаватель,
  редактор, эксперт, админ) к списку и созданию жеста; фильтр по языку, версия
  словаря, черновики только для ролей словаря; URL клипа в списке; создание
  жеста из формы и JSON, загрузка клипа, отклонение пустой глоссы, неверного
  языка, битого (400) и слишком большого (413) клипа; решение эксперта
  (`/review/`): права (аноним 401, редактор/преподаватель 403), утверждение и
  отклонение, JSON и форма, неверное решение (400), запрещённый переход (409),
  неизвестный жест (404), версия словаря; созданный черновик виден в Django
  Admin; запись из очереди с клипом переводит слово в `recorded`, а слово не в
  `queued` или отсутствующее отклоняется без создания жеста.
- `rooms/tests/test_management.py` — сервисные функции и HTTP-действия A10:
  смена ID (включая повтор при коллизии и недействительность старого кода),
  закрытие (идемпотентность, очистка presence), удаление участника (presence,
  редирект удалённого гостя), права доступа, admin-действие смены ID.
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
- `RoomConsumer` умеет `ping`/`pong`, `chat`, рассылку `presence`/`chat_message`,
  закрытие по `room_closed`/`participant_removed` и heartbeat (закрытие 4408).
  События фраз (`asr_text`, `utterance`) появятся в блоке E.
- Heartbeat реализован фоневой задачей на соединение (не отдельным таймером в
  Redis): `last_seen` обновляется на `connect` и на любом входящем сообщении,
  задача раз в `ROOM_PING_INTERVAL` сравнивает его с `ROOM_PING_TIMEOUT` и
  закрывает соединение кодом 4408. Задача отменяется в `disconnect`. Так работает
  и с in-memory layer, и с Redis.
- Клиент при переподключении сначала получает `chat_history` (последние 50), а
  затем догружает пропущенное через API; дубликаты отсекаются по `lastMessageId`
  (и `lastSeq` для будущих фраз), поэтому двойной источник не даёт повторов.
- Смена ID не меняет `room.id`, поэтому группа Channels остаётся прежней: старый
  код и QR перестают находить комнату (поиск идёт среди открытых), а уже
  подключённые вкладки живут до переподключения. Событие `room_closed` при этом
  не рассылается — комната остаётся открытой.
- Удаление участника закрывает только его соединения: ключ соединения гостя
  `session:<session_key>` передаётся в событии, и совпавший consumer закрывается
  кодом 4403, а остальные получают обновлённый presence. Удалённый гость не может
  переподключиться (`removed_at__isnull=True` в `resolve_connection`) и при заходе
  на страницу перенаправляется на форму входа заново.
- Подтверждение опасных действий (`data-confirm`) обрабатывается глобально в
  `frontend/main.ts`; кнопка «Удалить» у участника рисуется в `room-live.ts` и
  отправляет обычную POST-форму с CSRF-токеном из `data-csrf-token`.
- Чат хранится в `rooms.Message`. Автор фиксируется в `author_name` (имя гостя
  или имя преподавателя) и `is_teacher`, чтобы история читалась без join к User.
- История отдаётся по возрастанию id: при подключении — последние 50, через
  `?after_message_id` — только новые; клиент отсекает дубликаты по id.
- `Utterance` живёт в `pipeline`, остальные модели B1 — в `dictionary`
  (по `docs/spec/project-structure.md`); `pipeline.Utterance` ссылается на
  `rooms.Room` через FK, поэтому миграция зависит от `rooms`.
- Уникальность `Sign(gloss, lang)` — частичная (`UniqueConstraint` с условием
  `status="verified"`): черновики и отклонённые дубликаты допустимы, а проверенный
  жест один на глоссу и язык. Так снимается расхождение при повторном ревью.
- `UnknownWord` уникален по `(lemma, lang)` (`count` и `last_seen_at`
  агрегируются), отсортирован по `-count`; отсюда же индекс `(lang, -count)`.
- `DictionaryVersion.number` уникален в пределах языка; номер растёт через
  `bump(lang)` (`next_number = max + 1`), текущая версия — `current(lang)`
  (наибольший номер). Глоссы для промпта берутся из текущей версии.
- Формат файла клипа и поля `SignClip` подготовлены под `docs/spec/clip-format.md`
  (`.json.gz`, fps 30, число кадров, версия, размер); фактическая загрузка — B3.
- Хранилище клипов вынесено в `services.clips` за Protocol, а не в Django
  `STORAGES`: код словаря не знает, где лежат файлы (файловая система сейчас,
  S3 позже), а `SignClip.file` остаётся обычным `FileField` для админки.
- `FileClipStorage.root` и `base_url` читаются из настроек **лениво** (property):
  так `override_settings(MEDIA_ROOT=...)` в тестах действует и на уже созданный
  `default_storage`.
- ETag считается по содержимому файла (md5), а не по mtime: клип неизменяем,
  поэтому повторный запрос стабильно получает 304. Заголовки Django и Caddy
  совпадают (`Cache-Control: public, max-age=604800, immutable`).
- ETag-функция вью не падает на отсутствующем файле (возвращает `None`), а сам
  вью отдаёт 404 — иначе `@condition` превращал бы 404 в 500.
- Клипы сжимаются на диск (`.json.gz`) и отдаются как `application/gzip`:
  декодирование gzip — на клиенте (этап C2), Django/Caddy содержимое не трогают.
- Публичный `GET /api/dictionary/` отдаёт только **проверенные** жесты: черновики
  запрашиваются со `status=draft` и доступны лишь редактору/эксперту/админу
  (`dictionary.permissions.can_manage_dictionary`). Проверка идёт на сервере, а
  не скрытием в интерфейсе (ТЗ 7.3).
- Создание жеста (`POST /api/signs/`) — для ролей словаря; преподаватель и аноним
  получают 403/401, и ни одного `Sign` при этом не создаётся (проверено тестами).
- Клип проверяется на сервере до записи на диск (`parse_clip`): битый файл не
  создаёт ни `Sign`, ни `SignClip` — валидация и создание идут в одной транзакции.
- Лимит размера файла (`CLIP_MAX_SIZE_BYTES`) проверяется по `upload.size` до
  чтения в память; превышение — 413. Лимит кадров (`CLIP_MAX_FRAMES`) — в
  `parse_clip`, превышение — 400.
- Имя файла клипа — `<id>-<транслит глоссы>-v<версия>.json.gz`: читаемо в
  хранилище и в `pg_dump`-бэкапах, при этом id гарантирует уникальность.
- Валидация метаданных и формата вынесена в `dictionary.services` /
  `services.clips`; вью `dictionary.api` только разбирает ввод и отдаёт
  JSON-ответы (views тонкие, логика — в сервисах).
- Правила переходов статусов живут в `dictionary/statuses.py` без зависимостей
  от Django — это чистые функции, их удобно тестировать и переиспользовать в
  админке (B5), API эксперта (B6) и интерфейсе. Значения `SignStatus` (StrEnum)
  совпадают с `TextChoices` модели, соответствие проверяется тестом.
- Версию словаря растит **только** переход в `verified` (по языку жеста), а не
  создание жеста: глоссы для промпта берутся из текущей версии (ТЗ 9).
- Роли переходов: отправка на проверку — редактор (и эксперт-носитель, и админ),
  утверждение/отклонение — только эксперт и админ. Преподаватель не может менять
  статусы. Проверка роли идёт в сервисе, а не в интерфейсе.
- `Sign.verify()` оставлен низкоуровневым примитивом модели (нужен админке и
  служебным сценариям): он помечает жест проверенным без проверки перехода, но
  тоже растит версию. Поток редактора/эксперта идёт через
  `transition_sign`/`verify_sign`, где переход валидируется.
- Админка словаря не дублирует правила статусов: действия вызывают сервисные
  переходы B4 и на запрещённом переходе показывают предупреждение, а не падают.
  Так админка, API эксперта (B6) и интерфейс редактора работают по одним правилам.
- Предпросмотр клипа в админке — ссылка на файл (`clip-file`) с метаданными
  (кадры, fps, длительность, размер). Полноценное проигрывание анимации — в
  браузере (этап C), в админке достаточно открыть файл для ручной проверки.
- `DictionaryVersion` в админке только для чтения: версии создаёт сервис при
  утверждении жеста, ручное добавление версий запрещено (`has_add_permission`).
- Преподаватель в админку по-прежнему не попадает (`is_staff` только у
  администраторов); редактор и эксперт работают со словарём через API (B3/B6),
  а не через `/admin/`.
- Решение эксперта живёт в двух местах с одной логикой: JSON
  `POST /api/signs/<id>/review/` (для PWA) и серверная страница
  `/dictionary/review/<id>/` (для ручной проверки). Обе вызывают сервисные
  переходы B4, поэтому правила статусов не дублируются.
- Коды ответа решения: 401 без входа, 403 не-эксперт, 400 неверное `decision` или
  битый JSON, 404 нет жеста, 409 запрещённый переход (например, утвердить
  черновик), 200 — успех. Так клиент PWA отличает «нет прав» от «не та фаза».
- Права эксперта — через `can_review_signs` (`dictionary/permissions.py`) и
  декоратор `review_required`; редактор и преподаватель интерфейс эксперта не
  получают (403), хотя редактор и создаёт жесты (B3).
- Интерфейс эксперта показывает клип ссылкой на файл с метаданными: полноценное
  проигрывание анимации (аватар, ретаргет) — этап C, в B6 для решения достаточно
  открыть файл клипа. Оригинальное видео не хранится (аудио и видео не храним).
- Повторы нераспознанных слов агрегируются в одной строке по `(lemma, lang)`
  через `get_or_create` + инкремент `count` (а не по строке на каждое вхождение):
  список для редактора сразу показывает приоритет, а не сотни дублей.
- Записанное слово (`recorded`) при повторе снова не всплывает в очереди
  (`list_unknown_words` исключает `recorded`): счётчик растёт, но редактор уже
  записал жест. Вернуть слово можно переоткрытием (`recorded → queued`).
- Очередь слов — отдельный модуль `dictionary/queue.py` с чистыми правилами, по
  образцу `dictionary/statuses.py` (B4): одна точка правды для статусов, проверки
  и интерфейсов (страница редактора, API, админка).
- Интерфейс очереди для редактора (`/dictionary/queue/`) и действия идут через
  сервис: интерфейс не меняет `status` и `count` напрямую.
- Пополнение очереди (`record_unknown_word`) — публичная функция словаря: её
  вызовет конвейер глосс в блоке E для слов без жеста (FR-9). Модель `UnknownWord`
  при этом живёт в `dictionary`, а `pipeline` зависит от неё только через сервис.
- Модуль аватара (C1) — класс `Avatar` в `frontend/avatar.ts`, а не набор
  функций: у сцены есть жизненный цикл (создание → загрузка → отрисовка →
  `dispose`), и C3/C4 будут обращаться к модели через `avatar.model`. Логика
  отрисовки — в модуле, страница (`frontend/avatar-page.ts`) только связывает DOM
  и `Avatar`.
- VRM-модель не входит в репозиторий: её выбирает и кладёт человек (ТЗ 15.3,
  лицензия проверяется). URL берётся из настройки `AVATAR_MODEL_URL` или поля на
  странице, поэтому на C1 без модели страница всё равно рисует сцену, свет и
  камеру, а не падает.
- При загрузке VRM вызываются оптимизации three-vrm
  (`removeUnnecessaryVertices`, `combineSkeletons`, `combineMorphs`): это снижает
  нагрузку на скелет и морф-цели, что важно для 30 FPS на смартфоне (НФТ) —
  цель блока C. `rotateVRM0` ставит модель VRM 0.x лицом к камере (для 1.0 —
  no-op), ручной поворот не нужен.
- Нейтральная поза — `humanoid.normalizedRestPose` самой модели (ТЗ 5.4:
  нейтральная поза в начале и конце клипа). Поза клипов будет накладываться поверх
  неё на C3/C4.
- Декодер клипа (C2) вынесен в `frontend/clip.ts` отдельно от аватара: это чистая
  функция над байтами без Three.js и DOM, поэтому её легко тестировать (vitest) и
  переиспользовать в инструменте записи (D2, упаковка в тот же формат). Формат —
  единственная точка правды: `CLIP_VERSION` на клиенте совпадает с `CLIP_VERSION`
  на сервере (`services.clips`), соответствие проверяется тестом фикстуры.
- Распаковка gzip — нативный `DecompressionStream('gzip')`, без сторонней
  библиотеки: поддерживается всеми целевыми браузерами (НФТ, последние 2 версии
  Chrome/Edge/Firefox/Safari). Поэтому декодер асинхронный; синхронных путей в
  браузере нет.
- Float16 читается вручную (`readFloat16` по IEEE 754 binary16): в браузерах нет
  `Float16Array`. Тесты покрывают эталонные биты, ноль, субнормальные значения и
  `NaN`/бесконечность, а фикстура пишет half-числа тем же правилом, что `numpy`.
- `decodeClipPayload` превращает `layout` в `offsets` (`{part: {start, count}}`):
  Калидокит на C3 берёт части скелета по именам (`pose`, `hand_l`, `hand_r`,
  `face`), не пересчитывая смещения каждый кадр.
- Тесты клиента гоняются в окружении Node (`environment: "node"` в
  `vite.config.ts`): декодер — чистые функции над байтами, jsdom не нужен.
  Фикстура (`frontend/clip.fixture.ts`) собирает настоящий `.json.gz` через
  `node:zlib`; в сборку клиента фикстура не попадает (только в тесты).
- Ретаргет (C3) разделён на три слоя: `retarget.ts` — чистые числа (Kalidokit
  поверх landmarks, без Three.js), `vrm-rig.ts` — раскладка по костям и мимике
  VRM, `clip-player.ts` — тайминг и сглаживание. Так улучшение ретаргета или
  смена аватара не трогает формат клипа (ТЗ 5.4), а логику легко тестировать:
  `retarget` — на синтетическом скелете, `vrm-rig` — на структурной заглушке.
- Kalidokit вызывается с `runtime: "mediapipe"` и без `video`/`imageSize`: клип
  хранит уже нормализованные landmarks (0..1, y вниз), поэтому ретаргет отдаёт
  их напрямую, без пересчёта в пиксели.
- В клипе нет `visibility` (формат хранит только x/y/z), но Kalidokit по
  `visibility ?? 0` сбрасывает «невидимые» руки в нейтраль. `splitFrame` ставит
  позе `visibility = 1`, а проигрыватель сохраняет её после сглаживания One Euro
  (фильтр возвращает только x/y/z) — иначе руки гасли бы при воспроизведении.
- Kalidokit отдаёт `Vector`/`Euler` (классы с методами), но `retarget.ts`
  приводит выход к простым `{x, y, z}`: дальше по коду идут числа, и модуль не
  тащит зависимости Kalidokit за пределы ретаргета.
- Большой палец: у Kalidokit сегменты `Proximal/Intermediate/Distal`, у VRM —
  `Metacarpal/Proximal/Distal`. Поэтому `Intermediate` ложится на `Metacarpal`,
  а `Proximal` — на `Proximal` (в `vrm-rig.ts`).
- Углы ограничиваются (`clamp`) при записи в кость: на «шумных» кадрах и при
  отсутствии видимости сустав не выворачивается. Позиция бёдер переносится в
  уменьшенном масштабе (`×0.1`), чтобы аватар не «улетал» из кадра.
- Синтетический демо-клип (`demo-clip.ts`) собирается в браузере
  (`CompressionStream` + `btoa`) в том же формате, что пишет инструмент редактора:
  тестовая страница может проиграть клип без файлов и словаря (в репо клипов нет —
  их пишет блок D). Тот же путь декодирования, что у реального файла.
- Очередь клипов (C4) вынесена в три слоя: `clip-queue.ts` — **чистый
  планировщик** (тайминги в миллисекундах: отрезки, crossfade, скорость),
  `clip-blend.ts` — смешивание кадров ретаргета, `clip-player.ts` — тайминг по
  кадрам. Планировщик — единственная точка правды для длины перехода и скорости:
  игрок берёт из него `fadeInMs` и `speed`, а не считает их снова.
- Планировщик считает время в **миллисекундах** (а не в кадрах): так его можно
  переиспользовать в интерфейсе (полоса очереди, отставание FR-15) и в субтитрах
  (C6), где важен реальный тайминг. Игрок переводит миллисекунды в кадры при
  текущей скорости (`framesPerMs = fps × speed / 1000`).
- Модель перекрытия: клипы **накладываются** на `crossfadeMs` (голова `i+1`
  совпадает с хвостом `i`), поэтому общая длительность очереди меньше суммы
  длительностей. Первый клип не имеет зоны входа, последний — зоны выхода.
- Переход не длиннее **половины** самого короткого клипа: у коротких клипов
  (дактиль на букву, C5) зоны входа и выхода иначе наложились бы друг на друга.
  Для дактиля длина перехода берётся из `DACTYL_CROSSFADE_MS` (80 мс) и **не**
  зажимается общей нижней границей: режим `dactyl` (`clampCrossfadeFor`) опускает
  минимум до 0, обычная фраза держит 150–250 мс.
- Дактиль (C5) — отдельный модуль `dactyl.ts` без Three.js: русский алфавит,
  нормализация ввода (верхний регистр + замена похожих латинских `A→А`, `B→В`…),
  разбор на знаки, глоссы (`ДАКТИЛЬ_А`, `ЦИФРА_5`) и тайминги. Планировщик C4
  переиспользуется в режиме `dactyl`, поэтому склейка букв идёт тем же кодом, что
  и очередь фразы, — отдельной «дактильной» очереди нет.
- Раскладка «буква → клип» вынесена в **резолвер** (`DactylClipResolver`): клипы
  букв пишет блок D, а сервис глосс (блок E) возьмёт их из словаря. `buildDactylQueue`
  не знает, откуда клип, и пропускает букву, если клипа нет (`null`) — так страница
  может проверить склейку на синтетике, а прод подставить настоящие клипы.
- `splitWord` **схлопывает** пробелы, убирает пробел в начале/конце и отбрасывает
  пунктуацию: в дактиле озвучиваются только буквы и цифры, а пробел — пауза между
  словами. Пустая строка/одна пунктуация дают пустой список, страница показывает
  подсказку, а не падает.
- Тайминги дактиля: буква показывается `DACTYL_LETTER_MS` (420 мс) и перекрывается
  со следующей на `DACTYL_CROSSFADE_MS` (80 мс), шаг = `letterMs − crossfadeMs` (340
  мс); пробел даёт паузу `DACTYL_WORD_GAP_MS` (320 мс). Скорость делит и показ, и
  переходы. Точные длительности уточнит эксперт вместе с записью букв (блок D).
- Буквы дактиля в демо — **синтетические** (`encodeDactylClip`): форма пальцев
  берётся из индекса буквы в алфавите (`dactylFingerPattern`), поэтому буквы
  выглядят по-разному и склейку видно глазом. Точные артикуляции РЖЯ появятся с
  реальными клипами (блок D); путь декодирования и склейки тот же.
- Пробел в дактиль-очереди играется **клипом нейтральной позы**
  (`encodeNeutralPauseClip`), а не `gapMs`: паузы нужны в конкретных местах (между
  словами), а `gapMs` в планировщике одинаков для всех стыков. Клип паузы встаёт
  в общую очередь и склеивается тем же укороченным переходом.
- Режим очереди (`phrase`/`dactyl`) передаётся в игрок (`ClipPlayerOptions.mode`) и
  дальше в планировщик — так одна и та же очередь играется и как фраза, и как
  слово по буквам, а логика склейки живёт в одном месте.
- Скорость зажимается в 0.6–1.3x (`clampSpeed`), длина перехода — в 150–250 мс
  (`clampCrossfade`). FR-13 говорит про 0.6–1.2x (настройка студента), FR-16 — про
  ускорение до 1.3x (догон отставания); планировщик берёт верхнюю планку 1.3x, а
  конкретное значение задаёт вызывающий (C7 — настройка студента).
- Блендинг смешивает **числа ретаргета** (`RetargetedFrame`), а не кватернионы
  VRM: ретаргет уже посчитан, а `vrm-rig.ts` принимает именно эти числа. Слой
  независим от Three.js и тестируется в vitest вместе с планировщиком.
- Отсутствующая часть кадра при блендинге считается **нейтральной** (нули), а не
  копией соседнего кадра: `fadeToNeutral(frame, 1)` даёт явные нулевые углы,
  поэтому поза действительно уходит в нейтраль, а `applyRetargetedFrame` не
  «замораживает» кости (для пустого `bones = null` он их не трогает).
- Игрок остаётся **покадровым** (один `tick` — один кадр, как в C3): тесты
  детерминированы и не зависят от таймера. Crossfade и пауза считаются в кадрах
  из миллисекунд плана, поэтому изменение `speed`/`crossfadeMs` меняет и тайминг,
  и длину перехода согласованно.
- Пауза между фразами (`gapMs`) — реальная пауза в нейтральной позе (не только
  crossfade): ТЗ 5.4 требует нейтральную позу между фразами. На тестовой странице
  по умолчанию 250 мс, пауза видна глазом как «сброс» аватара между клипами.
- «Демо-очередь» (`encodeDemoQueue`) собирает три клипа разной длины (40/30/50
  кадров) и разного жеста — на них виден и crossfade на стыке, и пауза в
  нейтральной позе. Реальные клипы появятся в блоке D; путь декодирования тот же.
- Субтитры (C6) — отдельный модуль `subtitles.ts` над **объектом глосс** (ТЗ 7.2),
  а не над страницей: сопоставление токена и слова текста, раскладка на единицы
  показа и подсветка по времени очереди тестируются без DOM. Отрисовка
  (`SubtitleView`) — тонкий слой, который страница вызывает по событиям.
- Соответствие «токен ↔ слово» строится **курсором вперёд** (`alignTokens`): каждому
  токену ищется слово в тексте, начиная от предыдущего совпадения. Так повторяющиеся
  слова («дом … дом») не путаются, а лемма («УЧЕБНИК» ← «учебнике») находит слово по
  порядку. Диапазоны подсветки не включают пунктуацию (`subtitlePieces` делит текст
  на слова и промежутки), поэтому подсветка обводит слово, а не запятую.
- Одна фраза → **единицы показа** (`utteranceUnits`): жест и число дают одну единицу
  (один клип), слово по буквам — по единице на букву (дактиль C5). Отрезки плана C4
  сопоставляются единицам индексом (`segmentsToTokens`), а единицы — токену, токен —
  слову. Так подсветка идёт по **единственному источнику таймингов** (план очереди),
  а не по отдельному таймеру.
- Клипы могут не найтись (буква без записи): `segmentsToTokens` отдаёт `-1` для
  «пустых» отрезков, и субтитр просто ничего не подсвечивает — интерфейс не падает.
- Размер и контраст субтитров — отдельные **CSS-классы** (`subtitle-size-*`,
  `subtitle-theme-*`) и функции-хелперы: значения живут в CSS, а модуль отдаёт
  только имена классов. Тёмная тема `dark` — светлый текст на тёмной подложке,
  `light` — наоборот; то и другое контрастно (НФТ: «контраст, размер субтитров»).
- События `asr_text`/`utterance` появятся в блоке E, поэтому C6 подключён к
  **синтетической фразе** (`demo-phrase.ts`) на `/avatar/`: страница собирает клипы
  на единицы, рисует субтитр и подсвечивает слово по текущему клипу игрока. В E тот
  же `SubtitleView` получит фразу из события комнаты — логика не изменится.
- Демо-фраза содержит все три вида токенов (жесты, число, дактиль), чтобы вручную
  проверить и подсветку отдельных слов, и подсветку букв дактиля как одного слова.
- Настройки студента (C7) — отдельный модуль `student-settings.ts`: ограничения,
  нормализация, хранение и CSS-переменные тестируются без DOM. `StudentSettingsView`
  только связывает поля формы со страницей, поэтому те же настройки сможет
  использовать комната студента, когда в ней появится аватар (блок E).
- Пределы настроек — по FR-13: скорость **0.6–1.2x**, хотя планировщик C4 принимает
  до 1.3x. Верхняя планка 1.3x остаётся внутренней для догона отставания (FR-16),
  а студент вручную её не выставляет.
- Настройки лежат в `localStorage` под версионированным ключом
  `gluho-nemye:student-settings:v1`. Чтение терпимо к битому JSON, частичным полям и
  строкам вместо чисел: при любой ошибке возвращаются умолчания, страница не падает.
  Нет хранилища (приватный режим) — настройки работают до перезагрузки.
- Размер и положение — **CSS-переменные** `--avatar-size`/`--avatar-offset-x`/
  `--avatar-offset-y` на сцене, а не параметры камеры: кадр остаётся тем же, меняется
  только показ, а значения живут в CSS и легко проверяются глазами. Тема меняет и
  подложку сцены, и цвет фона Three.js (`Avatar.setBackground`), иначе canvas
  закрывал бы фон.
- Скорость применяется **на ходу**: `ClipPlayer.setSpeed` пересобирает план C4 под
  новую скорость, сохраняя текущий клип и кадр. Если игрока ещё нет, значение
  подхватится при создании. Тема субтитров C6 следует за фоном студента, чтобы
  контраст оставался читаемым в обеих темах.
- Изменения сохраняются сразу при движении ползунка — кнопки «Применить» нет;
  «Сбросить настройки» возвращает умолчания и тоже сохраняет их.
- Лента расшифровки (C8) — отдельный модуль `transcript.ts`: субтитр C6
  показывает только текущую фразу, лента хранит историю, поэтому студент может
  перечитать сказанное. Дубли гасятся по `seq` (`asr_text` и `utterance`
  описывают одну фразу; после переподключения `fetchMissed` может прислать её
  снова), лента ограничена `TRANSCRIPT_MAX_LINES`, а автопрокрутка не мешает
  чтению выше (`shouldStickToBottom`). Предел и допуск прокрутки — константы, а
  не «магические числа» в DOM-слое: оба края поведения покрыты тестами.
- Уведомления (C8) — отдельный модуль `notifications.ts`: правило «событие →
  уведомление», узоры вибрации и Wake Lock тестируются без DOM и мобильного
  браузера. `ScreenNotifier` только переключает класс на `body` и текст в
  `aria-live`, поэтому подсветку можно переиспользовать в блоке E.
- Уведомляет только **страница студента** (`data-student-view`). Панель
  преподавателя не мигает и не вибрирует: там те же события, но не тот адресат.
  Новая фраза — это `utterance`, ответ преподавателя — `chat_message` с
  `is_teacher`; сообщения других студентов и `asr_text` уведомлений не дают.
- `chat_history` при переподключении **не** уведомляет: иначе после обрыва
  прилетела бы пачка подсветок за старые сообщения. Уведомления идут только на
  живые события сокета.
- Wake Lock — необязательная возможность: без `navigator.wakeLock` страница
  показывает, что удержание недоступно, и продолжает работать. Браузер сам
  снимает блокировку при скрытии вкладки, поэтому после возврата запрос
  повторяется; если браузер требует касание, делается одна повторная попытка по
  `pointerdown`. Блокировка снимается при закрытии комнаты, удалении участника и
  уходе со страницы.
- Подсветка — **один** короткий импульс (700 мс) через `body.notification-flash`
  и `::after`, без стробирования; при `prefers-reduced-motion` анимация
  отключается, остаётся спокойная подложка. Вибрация короткая (фраза — двойной
  импульс, чат — один), а без поддержки API просто не вызывается. Звука нет:
  НФТ требуют визуального дубля любой звуковой информации.

## Проверка C8 (на момент этапа)

```bash
make check          # ruff + tsc + vitest (201) + pytest (341) + vite build — зелёный
```

Автотесты покрывают правила уведомлений, вибрацию, запрос/повтор/освобождение
Wake Lock и отказы браузера (`frontend/notifications.test.ts`), а также разметку
уведомлений на странице студента (`rooms/tests/test_join.py`). Ручная проверка:
открыть комнату студента на телефоне — экран не гаснет; отправить сообщение из
панели преподавателя — экран подсвечивается, на Android срабатывает вибрация,
в строке уведомления появляется «Ответ преподавателя в чате».

## Проверка D1

```bash
make check          # ruff + tsc + vitest (216) + pytest (350) + vite build — зелёный
```

Автотесты покрывают разбор кадра Holistic и геометрию скелета
(`frontend/holistic.test.ts`, `frontend/skeleton.test.ts`), доступ и разметку
страницы записи (`dictionary/tests/test_record_page.py`), а также попадание
точки входа и WASM в сборку (`tests/test_frontend.py`). Ручная проверка:
войти редактором, открыть `/dictionary/queue/` и нажать «Записать жест с
камеры», разрешить доступ. Скелет идёт за рукой и пальцами без заметной
задержки, наклон головы повторяет контур лица, при уходе из кадра появляется
«В кадре пока нет человека». В dev-режиме WASM отдаёт Vite; в production —
WhiteNoise из `static/dist/mediapipe`.

## Решения D1

- MediaPipe выбран в варианте **Tasks Vision** (`HolisticLandmarker`), а не
  устаревший пакет `@mediapipe/holistic`: модель и WASM версионируются вместе с
  npm-зависимостью, а API поддерживает видео-режим и делегаты GPU/CPU.
- Видео и landmarks не покидают браузер: на этом этапе сервер отдаёт только
  страницу. Запись и отправка клипа начнутся в D2–D3.
- Модель по умолчанию — официальная float16-модель Google по HTTPS, URL можно
  заменить на свой для офлайн-развёртывания. WASM (SIMD и nosimd) копируется в
  `static/dist/mediapipe` при `npm run build`; путь в dev и production
  вычисляет `_mediapipe_wasm_path`.
- Если GPU-делегат недоступен, детектор автоматически пересоздаётся на CPU.
  Ошибка загрузки модели не выключает камеру: видео продолжает работать, а
  статус объясняет, что скелет недоступен.
- Страница доступна только редактору, эксперту и администратору — как остальные
  инструменты словаря. Роль преподавателя получает 403.

## Проверка D2

```bash
make check          # ruff + tsc + vitest (241) + pytest (351) + vite build — зелёный
```

Автотесты покрывают упаковку и обратную распаковку формата v1
(`frontend/clip-encode.test.ts`), весь конвейер записи — автообрезку,
пересэмплирование, добор кистей/лица, One Euro, лимиты и ретаргет
(`frontend/clip-record.test.ts`), а также разметку и лимиты страницы
(`dictionary/tests/test_record_page.py`). Ручная проверка: войти редактором,
открыть `/dictionary/queue/` и нажать «Записать жест с камеры», разрешить
доступ. Нажать «Начать запись», показать жест, остановить. Края должны
обрезаться, ползунки — менять длительность, а строка сборки — подтвердить
размер, версию формата и совпадение распаковки. Скачанный `.json.gz` можно
проверить командой `gzip -dc zapis-*.json.gz | head -c 200`. Реальная камера и
MediaPipe проверяются в браузере: vitest работает без DOM.

## Решения D2

- Кодировщик вынесен в `frontend/clip-encode.ts`, а конвейер записи — в
  `frontend/clip-record.ts`; страница остаётся тонким слоем. Новых зависимостей
  нет, формат и `CLIP_VERSION` общие с C2.
- Кадры с камеры пишутся не чаще целевого FPS, а на финале пересэмплируются на
  равномерные 30 FPS по ближайшей метке времени. Так клип не зависит от того,
  с какой частотой браузер успевал вызывать MediaPipe.
- Автообрезка ищет первую и последнюю позу/кисть; лицо само по себе не считается
  жестом. Ручные ползунки ограничены минимумом в два кадра.
- Пропавшие кисти и лицо сначала берутся из предыдущего кадра, затем строится
  нейтральная заготовка у запястья/центра позы. Поэтому каждый кадр всегда
  содержит полный layout из 543 точек и ретаргет C3 не получает `NaN`.
- One Euro применяется после пересэмплирования, отдельным фильтром на каждую
  часть скелета, поэтому сглаживание не зависит от неровного потока кадров.
- После сборки страница сразу распаковывает собственный `.json.gz` тем же
  декодером C2 и сверяет число кадров/точек. Это и есть приёмочная проверка
  «упаковка и распаковка дают тот же клип».
- Лимиты (`CLIP_DEFAULT_FPS`, `CLIP_MAX_FRAMES`, `CLIP_MAX_SIZE_BYTES`) приходят
  из настроек в `data-*` страницы. Запись автоматически останавливается на
  `CLIP_MAX_FRAMES`, а превышение размера файла показывается предупреждением —
  окончательно его проверит API D3.
- На D2 клип только скачивается; предпросмотр на аватаре, форма метаданных и
  сохранение черновика через API — следующий этап D3.

## Проверка D3

```bash
make check          # ruff + tsc + vitest (249) + pytest (354) + vite build — зелёный
```

Автотесты покрывают метаданные и multipart-запрос к API
(`frontend/sign-draft.test.ts`), разметку аватара/формы и передачу
`AVATAR_MODEL_URL` (`dictionary/tests/test_record_page.py`), а также появление
созданного черновика в списке Django Admin (`dictionary/tests/test_api.py`).
Ручная проверка: войти редактором, открыть `/dictionary/queue/` и нажать
«Записать жест с камеры», записать короткий жест и дождаться сборки. В блоке
D3 загрузится VRM из `AVATAR_MODEL_URL`; «Играть» повторяет клип на аватаре,
«Стоп» возвращает нейтральную позу. Заполнить глоссу (например, `УЧЕБНИК`),
язык и описание, нажать «Сохранить черновик» — появится номер черновика, а под
администратором он будет виден в `/admin/dictionary/sign/` со статусом
«Черновик». Без `AVATAR_MODEL_URL` предпросмотр показывает предупреждение, но
сохранение работает. Реальная камера, WebGL и VRM проверяются в браузере:
vitest работает без DOM.

## Решения D3

- Новый backend-эндпоинт не понадобился: `POST /api/signs/` уже создаёт
  `Sign` со статусом `draft` и принимает multipart с клипом. D3 добавляет
  клиентскую проверку и форму, а не второй контракт.
- Аватар грузится лениво, только после первой успешной сборки клипа: страница
  записи не должна скачивать VRM и поднимать WebGL, пока редактор только
  настраивает камеру. Ошибка VRM/WebGL не блокирует сохранение — это
  вспомогательный предпросмотр, а не условие черновика.
- `ClipPlayer` запускается с `smoothing: false`: D2 уже применил One Euro к
  кадрам, поэтому повторное сглаживание на предпросмотре только увеличило бы
  задержку и расхождение с сохранённым клипом.
- После успешного сохранения поля и кнопка блокируются, чтобы случайно не
  создать дубликат: API не имеет обновления черновика. Новая запись или
  изменение обрезки сбрасывают это состояние. Языки берутся из
  `Language.choices`, а не дублируются в шаблоне.
- Валидация вынесена в `frontend/sign-draft.ts` без DOM, поэтому правила
  глоссы и формата запроса проверяются vitest; страница остаётся слоем
  взаимодействия.

## Проверка D4

```bash
make check          # ruff + tsc + vitest (250) + pytest (362) + vite build — зелёный
```

Автотесты покрывают ссылку из очереди на запись, предзаполнение и редиректы
(`dictionary/tests/test_record_page.py`, `dictionary/tests/test_queue.py`),
передачу `unknown_word` в multipart (`frontend/sign-draft.test.ts`) и
серверный переход `queued → recorded` в одной транзакции с созданием жеста и
клипа (`dictionary/tests/test_api.py`). Ручная проверка: войти редактором,
открыть `/dictionary/queue/`, у нового слова нажать «Взять в работу», затем
«Записать жест». Откроется страница записи с подставленной леммой и языком.
Записать жест, сохранить черновик — в сообщении появится «Слово … отмечено
записанным», ссылка «Вернуться в очередь» покажет, что слово исчезло из
активной очереди; в Django Admin его статус — «Записано». Повторное открытие
ссылки на записанное слово возвращает в очередь с сообщением. Реальная камера,
WebGL и VRM проверяются в браузере: vitest работает без DOM.

## Решения D4

- Отдельный эндпоинт для очереди не добавлялся: `POST /api/signs/` принимает
  необязательный `unknown_word`, поэтому сохранение клипа и отметка слова
  происходят одним запросом и не расходятся при сбое.
- Переход `queued → recorded` выполняется в `dictionary.services.create_sign`
  внутри той же транзакции, что создание `Sign` и `SignClip`. Если файл битый,
  слово остаётся в работе, а жест не создаётся.
- Слово можно записать только из статуса `queued`: для `new` очередь сначала
  предлагает «Взять в работу», а `recorded` по прямой ссылке возвращает в
  очередь. Это сохраняет правила B7 и не позволяет обойти статусы.
- В интерфейсе очереди кнопка «Записать жест» больше не помечает слово
  записанным сразу: она открывает инструмент записи. Старое POST-действие
  `recorded` оставлено для служебных сценариев и тестов B7, но в таблице не
  используется.
- Лемма и язык подставляются в форму, но остаются редактируемыми: редактор
  может уточнить глоссу. Язык выбирается из `Language.choices`, а API
  возвращает `unknown_word`, чтобы страница показала фактический статус.

## Проверка E1

```bash
make check          # ruff + tsc + vitest (250) + pytest (382) + vite build — зелёный
```

Автотесты покрывают чистый разбор фраз (`pipeline/tests/test_glosses.py`) и
сервис сохранения (`pipeline/tests/test_services.py`): фраза с проверенными
словами даёт токены `sign`, незнакомое слово — `fingerspell` с буквами и запись
в `UnknownWord`, числа — `number`, повторные вхождения увеличивают счётчик
очереди. Ручная проверка в `manage.py shell`:

```python
from rooms.models import Room
from pipeline.services import create_utterance
room = Room.objects.first()
utterance = create_utterance(room, "Учебник Иванов 10")
utterance.as_event()
```

В `glosses` видны `tokens` (жест/дактиль/число), `unknown` и `sentence_type`;
`seq` растёт в пределах комнаты. HTTP-приёма и рассылки событий на E1 ещё нет —
это E2/E3.

## Решения E1

- Поиск слова в словаре — по точной нормализованной форме (регистр и ё не
  важны), без морфологии: лемматизация (F2) и LLM (F1) уже готовы отдельными
  сервисами, но подключаются к конвейеру в F4. Поэтому в E1 «учебник» находит
  `УЧЕБНИК`, а «учебнике» пока уходит в дактиль — это осознанное упрощение E1,
  а не финальное поведение.
- Берутся только `SignStatus.VERIFIED` (FR-19). Черновики и демо-режим комнаты
  к E1 не подключались: публичный словарь и так отдаёт проверенные жесты.
- Разбор вынесен в `pipeline/glosses.py` без Django и базы: критерий этапа
  проверяется на чистых функциях, а `pipeline.services` добавляет транзакцию,
  очередь слов и метрики.
- Каждое вхождение незнакомого слова увеличивает `UnknownWord.count`, но в
  `glosses["unknown"]` слово повторно не дублируется — объект глосс остаётся
  компактным, а счётчик очереди честно отражает частоту.
- `seq` выдаётся под блокировкой строки комнаты (`select_for_update`) и `Max` в
  одной транзакции с созданием фразы и записью неизвестных слов. Это готовит
  последовательную обработку E2 (ТЗ 5.7) и не оставляет разъехавшихся счётчиков
  при сбое.
- Числами считаются только цифровые записи (`10`). Числительные словами
  («десять») до блока F идут через словарь или дактиль: иначе пришлось бы
  разбирать составные числа без лемматизации.
- Объект глосс повторяет ТЗ 7.2, но без `utterance_id`: идентификатор фразы
  уже есть в `Utterance.as_event()` (`id`) и не дублируется в JSONField.

## Проверка E2

```bash
make check          # ruff + tsc + vitest (250) + pytest (400) + vite build — зелёный
```

Автотесты проверяют права и ответ 202 (`pipeline/tests/test_api.py`), очередь
(порядок, параллелизм, предел, переполнение — `pipeline/tests/test_queue.py`) и
реальную фоновую запись `Utterance` (`pipeline/tests/test_processing.py`). Тест
`test_request_does_not_wait_for_background_processing` держит обработчик
заблокированным и подтверждает, что HTTP-ответ уже получен. Ручная проверка:

```bash
curl -i -X POST http://localhost/api/rooms/<код>/text/ \
  -H 'Content-Type: application/json' \
  -H 'X-CSRFToken: <токен>' \
  --cookie 'sessionid=<сессия>' \
  -d '{"text": "Учебник Иванов"}'

# 202 {"status": "accepted"} — фраза сохранится в фоне и появится в Utterance
```

Очередь живёт в памяти процесса: в проде остаётся один процесс uvicorn
(`--workers 1`). Пока нет рассылки `utterance` — это E3.

## Решения E2

- Очередь работает в отдельном daemon-потоке с собственным asyncio-циклом.
  Django-вью синхронное, а цикл запроса (особенно в тестах) живёт только до
  ответа: `asyncio.create_task` в нём был бы отменён, поэтому общий цикл
  принадлежит очереди, а не запросу. HTTP-вью только делает
  `call_soon_threadsafe`.
- Один воркер на комнату берёт задания из `asyncio.Queue` строго по порядку;
  глобальный семафор ограничивает число одновременно работающих обработчиков
  (`ASR_MAX_CONCURRENCY`), как требует ТЗ 5.7. Разные комнаты не ждут друг
  друга, если есть свободный слот.
- Обработка (`create_utterance`) запускается через `asyncio.to_thread`: ORM не
  выполняется в цикле событий, а будущие тяжёлые вызовы ASR/LLM встанут в тот же
  слот семафора. `process_text_job` получает комнату по id уже в фоне, поэтому
  между запросом и обработкой не держится объект модели.
- Очередь комнаты ограничена `ROOM_QUEUE_MAX` (5): при переполнении снимается
  самое старое **ожидающее** задание (текущее не прерывается), его `Future`
  получает `RoomQueueFullError`, в лог идёт предупреждение. Показ предупреждения
  преподавателю — E4/E5.
- Эндпоинт отвечает 202 сразу после постановки в очередь и не ждёт `Future`.
  Поэтому ответ не зависит от скорости глосс и не блокирует WebSocket-consumer,
  который живёт в том же процессе.
- `text` проверяется тем же `normalize_text`, что и сервис E1: пустой и слишком
  длинный текст отклоняются синхронно с 400, а не попадают в очередь.
- Права: только владелец комнаты или администратор. Посторонний преподаватель
  получает 403, гость — тоже 403, аноним — 401. Проверка комнаты идёт после
  аутентификации, чтобы не раскрывать существование закрытых комнат.

## Проверка E3

```bash
make check          # ruff + tsc + vitest (256) + pytest (407) + vite build — зелёный
```

Автотесты проверяют сборку ссылок на клипы и их порядок
(`pipeline/tests/test_events.py`), рассылку в группу комнаты через запомненный
ASGI-цикл, порядок `asr_text` → `utterance` в обработчике очереди
(`pipeline/tests/test_processing.py`) и JSON-ответы consumer'а
(`pipeline/tests/test_consumer_events.py`). Клиентская очередь проверена в
`frontend/room-clips.test.ts`: загрузка клипов, пропуск битого файла,
сопоставление `token_index` слову, строгая последовательность и дедупликация
`seq`. Ручная проверка в браузере:

1. Преподаватель отправляет текст в комнату (`POST .../text/`).
2. Студент видит распознанный текст в блоке `data-room-live-caption` до
   появления глосс.
3. Затем приходит `utterance`, субтитры сменяются словами, а аватар по очереди
   проигрывает клипы; текущее слово подсвечивается.
4. Если VRM или клипы не загрузились, остаются субтитры и статус с причиной.

В Docker задан Redis (`REDIS_URL`); без него используется
`InMemoryChannelLayer`, и рассылка из фонового потока всё равно ставится в
активный цикл ASGI. В проде ожидается Redis и один процесс uvicorn, потому что
очереди фраз хранятся в памяти процесса.

## Решения E3

- `asr_text` отправляется в начале фоновой обработки, до `create_utterance`.
  Это сохраняет порядок «текст раньше глосс» и не даёт более поздней фразе
  обогнать предыдущую: обе проходят через одну очередь комнаты.
- Фоновый поток очереди не вызывает `async_to_sync` на чужом цикле: ASGI-слой
  запоминает активный цикл (`bind_event_loop`), а `pipeline/events.py` делает
  `run_coroutine_threadsafe(...).result()` с таймаутом. Так `group_send`
  выполняется в том же цикле, где живут consumer'ы, и InMemoryChannelLayer не
  ломается при передаче между циклами.
- Ссылки на клипы не сохраняются в `Utterance.glosses`: они собираются при
  рассылке по актуальному словарю и лучшему клипу. Глоссы остаются чистым
  результатом E1, а версия/URL клипа не устаревают в JSONField.
- Порядок клипов задаёт сервер: `clips` — плоский массив в порядке показа с
  `token_index`; клиент не пересортировывает его, а только пропускает битые
  ссылки. Для дактиля каждая найденная буква — отдельный клип, отсутствующие
  буквы просто не попадают в очередь.
- `PhraseQueue` держит фразы строго последовательно и отбрасывает `seq` не
  больше последнего. Это готовит переподключение: клиент уже умеет принять
  историю `utterance`, но `rooms.services.recent_utterances` пока остаётся
  заглушкой, поэтому сервер историю фраз ещё не отдаёт.
- Тяжёлый Three.js/VRM-плеер вынесен в динамический импорт
  `frontend/room-phrase.ts`: панель преподавателя и страница чата не грузят
  аватар, а `asr_text` показывается лёгким текстовым блоком до загрузки плеера.
- Без `AVATAR_MODEL_URL`, WebGL или клипов страница не падает: субтитры
  показываются, слова подсвечиваются по длительности клипов, статус объясняет
  причину.

## Проверка E4

```bash
make check          # ruff + tsc + vitest (256) + pytest (418) + vite build — зелёный
```

Автотесты проверяют пороги FR-15 (5 и 10 с), сохранение `display_lag_ms`,
идемпотентность повторного `display_started` и изоляцию комнаты
(`pipeline/tests/test_services.py`), `unknown_words` в рассылке
(`pipeline/tests/test_events.py`), а также WebSocket-сценарий: студент шлёт
`display_started`, преподаватель получает `lag_status`, метрика попадает в БД,
студент событие не получает; `unknown_words` тоже доходит только до
преподавателя (`rooms/tests/test_consumer.py`). Ручная проверка:

1. Преподаватель открывает `/rooms/<code>/live/`, студент — `/r/<code>/live/`.
2. Преподаватель отправляет несколько фраз подряд; студент проигрывает очередь.
3. Индикатор у преподавателя показывает отставание, цвет и подсказку; при
   задержке больше 10 с появляется «Замедлитесь».
4. Слова, для которых нет проверенного жеста, появляются в списке «Слова без
   жеста».

## Решения E4

- `display_lag_ms` считается от `Utterance.started_at` до фактического начала
  показа: это сквозная задержка, которую требует НФТ (медиана ≤4 с, p95 ≤7 с), а
  не только время в очереди. `asr_ms` и `gloss_ms` уже заполняются на своих
  этапах и остаются в той же строке `Utterance`.
- Сервер не доверяет часам студента: `ts` принимается как epoch мс/с или ISO,
  но если он расходится с серверным больше чем на 60 с или не разбирается,
  используется момент получения `display_started`. Метрика хранится на сервере.
- Повторный `display_started` для той же фразы не перезаписывает метрику: после
  переподключения или дубля события отставание не растёт искусственно.
- `lag_status` и `unknown_words` рассылаются в общую группу `room_<id>` (иначе
  пришлось бы держать отдельный teacher-канал), но consumer отдаёт их в браузер
  только при `is_teacher`. Студенческие соединения события молча игнорируют;
  изоляция комнат по-прежнему проверяется в `connect()`.
- `unknown_words` уходит вместе с каждой `utterance`, даже пустой: панель
  очищает список для фразы, где все слова нашлись. Список берётся из
  `glosses["unknown"]`, то есть это именно слова, показанные дактилем.
- Студент отправляет `display_started` в `RoomPhrasePlayer.play()` после
  `renderSubtitles`, когда его очередь дошла до фразы. Это включает ожидание
  предыдущих фраз (реальное отставание), но не включает последующую загрузку
  клипов; для VRM без клипов и для субтитров событие всё равно отправляется.
- Индикатор FR-15 считает сервер (`lag_level`), клиент только форматирует
  миллисекунды и выбирает подсказку. Пороговые значения включаются в нижний
  уровень: ровно 5 с — зелёный, ровно 10 с — жёлтый, больше 10 с — красный.
  Ускорение клипов и сжатие фраз (FR-16) — следующий этап F8, в E4 их нет.
- История фраз после переподключения всё ещё не отдаётся
  (`rooms.services.recent_utterances` — заглушка); `display_started` уже готов
  работать и для исторических `utterance`, когда сервер начнёт их присылать.

## Проверка E5

```bash
make check          # ruff + tsc + vitest (256) + pytest (426) + vite build — зелёный
```

Автотесты проверяют панель (`rooms/tests/test_views.py`): форму, ленту и
начальный список слов без жеста на странице; HTMX-фрагмент ленты только с
фразами своей комнаты и в порядке `seq`; нормализацию и постановку фразы в
очередь; `HX-Trigger: phrase-saved`; сохранение ввода и текст ошибки; закрытую
комнату; обычный POST с редиректом; 403 для чужого преподавателя. Сервис
`recent_room_utterances` проверен на лимит и порядок. Ручная проверка:

1. Преподаватель открывает `/rooms/<code>/live/` и вводит фразу в форму.
2. Лента обновляется без перезагрузки: появляется фраза с номером, временем,
   текстом и словами без жеста.
3. У студента одновременно появляются субтитры и клипы.
4. При пустом тексте форма показывает ошибку и не очищается; в закрытой комнате
   отправка недоступна.

## Решения E5

- Ввод фразы вынесен в отдельный HTML-эндпоинт `POST .../live/phrase/`, а не в
  JSON API E2: HTMX нужен фрагмент формы с ошибкой/статусом, а JSON-клиенты
  продолжают пользоваться прежним API. Нормализация, проверка длины и постановка
  в очередь общие (`normalize_text` + `submit_text`), поэтому правила не
  расходятся.
- Форма заменяет свой фрагмент целиком (`hx-target` + `outerHTML`), поэтому
  успешная отправка очищает поле, а ошибка сохраняет введённый текст и показывает
  сообщение. Без HTMX тот же POST делает редирект и использует Django messages.
- Лента — серверный фрагмент `GET .../live/feed/`, а не клиентская отрисовка
  событий: после перезагрузки страницы история последних фраз сразу видна, даже
  если WebSocket ещё не подключился. `recent_room_utterances` отдаёт последние
  20 фраз по возрастанию `seq` (снизу — свежие).
- Обновление ленты тройное: `HX-Trigger: phrase-saved` сразу после постановки в
  очередь, событие `phrase-saved` из `room-live.ts` при получении `utterance`
  (когда фраза уже сохранена) и опрос раз в 3 секунды как запасной вариант, если
  WebSocket или заголовок потерялись. Повторная отрисовка идемпотентна.
- Слова без жеста на панели изначально берутся из последней фразы комнаты, а
  затем обновляются E4-событием `unknown_words`. В ленте те же слова показаны
  под каждой фразой, поэтому видно, из какой фразы они пришли.
- Страница и оба фрагмента закрыты теми же правами, что и остальная панель:
  владелец комнаты или администратор; другой преподаватель получает 403.
- История фраз для переподключения по-прежнему не отдаётся:
  `rooms.services.recent_utterances` остаётся заглушкой, хотя лента использует
  отдельный сервис `pipeline.services.recent_room_utterances`. Это не мешает E5,
  но остаётся отдельным решением для клиента после обрыва.

## Проверка F1

```bash
.venv/bin/python -m pytest services/tests/test_gloss.py -q   # 36 passed
```

Автотесты работают без сети и реального ключа: `FakeProvider` подменяет LLM и
проверяет промпт, схему, таймаут и число вызовов. Отдельный тест прогоняет 30
реальных фраз лекции, на каждой проверяет повторную валидацию результата,
допустимые типы токенов, глоссы только из словаря и согласованность `unknown`.
Ручная проверка провайдера (ключ, модель, качество перевода) появится при
настройке F4: F1 сознательно не делает сетевых вызовов.

## Решения F1

- `services.gloss` — чистый Python без Django: провайдер, промпт, схема, словарь
  и кэш тестируются без базы и сети, а F4 вызовет `to_glosses` из
  `asyncio.to_thread`, не завязывая сервис на ORM.
- Провайдер спрятан за `Protocol` с методом `complete(prompt, *, schema,
  timeout)`: он получает и промпт, и JSON-схему, поэтому API-клиент, Ollama или
  мок подставляются без изменения остального кода. `CallableProvider` нужен для
  тестов и ручных экспериментов.
- Глоссы не берутся из ответа LLM на веру: `restrict_to_dictionary` — вторая,
  серверная проверка ТЗ 5.3. Выдуманная глосса или другой регистр не проходят;
  неизвестное слово превращается в `fingerspell` по `src`, а `unknown`
  пересобирается из токенов, поэтому модель не может рассинхронизировать два
  поля.
- JSON-схема исключает `utterance_id`: его выдаёт сервер в `pipeline`, а не
  модель. Поля `lang`/`text` модель обязана повторить, но `parse_gloss_response`
  всё равно подставляет исходные значения — доверять тексту фразы модели нельзя.
- Парсер терпим к ```json-обёртке, строковым/дробным целым числам и забытым
  `letters` (дактиль достраивается по `src`), но строг к типам токенов,
  маркерам, `sentence_type` и структуре: невалидный ответ — `GlossFormatError`,
  который F4 превращает в деградацию (F2 без провайдера или только субтитры).
- Кэш — LRU в памяти процесса, как очереди конвейера (один процесс uvicorn).
  Ключ — SHA-256 от нормализованной фразы, языка, версии и **содержимого**
  словаря и примеров: изменение словаря или few-shot не отдаёт старые глоссы,
  даже если номер версии забыли поднять. Ошибки и невалидные ответы не
  кэшируются, иначе сбой LLM закрепился бы на всё время лекции.
- Кэш отдаёт глубокие копии: вызывающий код (субтитры, очередь клипов) не может
  испортить закэшированные глоссы. Интерфейс `get`/`set` позволит позже положить
  под него `django.core.cache`, не меняя `to_glosses`.
- Провайдер по умолчанию — модульная настройка (`set_default_provider`), а не
  чтение `settings` внутри сервиса: F1 не подключает Django, а F4 собирает
  HTTP-провайдера из `LLM_PROVIDER`/`LLM_MODEL`/`LLM_API_KEY`/`LLM_API_URL` и
  `LLM_TIMEOUT` (или берёт явно заданный провайдер для тестов).

## Проверка F2

```bash
.venv/bin/python -m pytest services/tests/test_fallback.py -q   # 33 passed
```

Тесты не обращаются к сети и не настраивают LLM: запасной режим работает на
локальном словаре и `pymorphy3`. Проверяются лемматизация падежных форм,
служебные части речи, числа словами, дактиль имён, `ksl` без русской
морфологии и 12 реальных фраз с повторной валидацией результата.

## Решения F2

- Морфология вынесена в `services/morphology.py`, а не растворена в
  `gloss.py`: лемматизацию можно переиспользовать в сжатии фраз (F8) и
  тестировать отдельно. Модуль не знает о словаре жестов и Django.
- `pymorphy3` загружается **лениво** и один раз на процесс (`lru_cache`):
  импорт сервиса и тесты без морфологии не платят за словарь, а разбор
  повторяющихся слов кэшируется до 8192 записей.
- Запасной режим ищет сначала точную форму, потом нормальные формы: так жест
  для «дом» находится без лишнего анализа, а «учебнике» и «Откройте» сводятся к
  глоссам «УЧЕБНИК» и «ОТКРЫТЬ». Порядок разборов `pymorphy3` сохраняется —
  первый разбор считается самым вероятным.
- Служебные части речи (`PREP`, `CONJ`, `PRCL`, `INTJ`) без записанного жеста
  **опускаются**, а не уходят в дактиль: иначе предлоги «на», «в» и союзы «и»
  засоряли бы очередь нераспознанных слов и показывались бы по буквам. Если
  редактор записал жест для служебного слова, проверка словаря идёт раньше
  фильтра, и жест показывается.
- Числительные словами (`десять`, `двадцать`, `сто`, `тысяча`, включая родовые
  «одна»/«две») превращаются в `number`, потому что E3 ищет клип `ЦИФРА_<n>`, а
  дактиль цифр — только запасной путь. Диапазон — практичные кардинальные
  числа; составные («двадцать пять») пока дают два токена `number`.
- Для `ksl` русская морфология не применяется: `pymorphy3` — русский
  анализатор, и его леммы могли бы случайно совпасть с казахским словарём.
  Точная форма и дактиль — честное поведение до появления казахской морфологии.
- Запасной режим не кэшируется и не подменяет LLM внутри `to_glosses`:
  `fallback_glosses` — отдельная функция, а решение «LLM упала → упрощённый
  режим → `degraded`» принимает F4, где живут таймауты и события. Так F1-тесты
  и контракт `to_glosses` не меняются.
- `pymorphy3==2.0.6` добавлен в `requirements.txt`: это единственная новая
  зависимость этапа, разрешённая ТЗ 6. Словари `pymorphy3-dicts-ru` ставятся
  транзитивно и в репозиторий не коммитятся.

## Проверка F3

```bash
.venv/bin/python -m pytest services/tests/test_compress.py -q   # 31 passed
```

Тесты не требуют сети: `FakeProvider` возвращает готовый JSON, а резервные
ветки проверяются на таймауте, мусорном ответе и тексте не короче исходного.
Для набора длинных фраз проверяется инвариант «результат короче исходной фразы»
при коэффициентах 0.4, 0.6 и 0.8.

## Решения F3

- `compress` живёт в `services.gloss`, как требует ТЗ 7.1: это часть работы с
  фразой, а не отдельная зависимость. Провайдер тот же `LLMProvider`, что у F1,
  поэтому ключ и API настраиваются в одном месте.
- Ответ LLM — JSON `{"text": "..."}`, а не голая строка: схема позволяет
  отличить нормальный ответ от пояснений модели и переиспользует уже принятый
  контракт провайдера. ```-обёртка принимается, пустое поле — ошибка формата.
- Сжатие **не падает** из-за LLM: при отсутствии провайдера, таймауте, битом
  ответе или тексте не короче исходного включается `compress_locally`. Это
  соответствует предохранителю ТЗ 5.3: отставание важнее идеального качества
  перевода, а преподаватель всё равно видит субтитры.
- Локальный резерв удаляет только явные вводные обороты и слова-заполнители
  («итак», «как вы знаете», «в общем», «пожалуйста», «ребята»), а не смысловые
  слова. «Сегодня» и «теперь» оставлены: в лекции они часто несут смысл.
  После очистки текст при необходимости обрезается по границе слова до
  `target_ratio`; пунктуация на конце не остаётся висящей.
- `target_ratio` проверяется строго (`0 < ratio < 1`), включая отказ на `bool`,
  строки и `None`: коэффициент приходит из настроек F8, и молчаливое приведение
  скрыло бы ошибку конфигурации. Для фразы из одного короткого слова сжатие
  невозможно — она возвращается без изменений, и это документировано.
- Сжатие не кэшируется: результат зависит от `target_ratio` и текущего текста,
  а вызов происходит только при отставании (F8), не на каждой фразе. Если
  понадобится, кэш F1 можно переиспользовать отдельным ключом.
- Интеграция в конвейер и пороги FR-15/FR-16 — задача F8: F3 даёт чистую
  функцию, которую F8 вызовет при жёлтом/красном отставании вместе с
  ускорением клипов.

## Проверка F4

```bash
.venv/bin/python -m pytest services/tests/test_llm.py \
  pipeline/tests/test_gloss_engine.py pipeline/tests/test_f4_pipeline.py -q
```

Тесты не ходят в сеть: HTTP-провайдер проверяется подменой `urlopen`, LLM —
`CallableProvider`, а таймаут — провайдером, который ждёт событие. Проверяется
и то, что за время ожидания LLM цикл событий выполняет тикер, и то, что
`Future` очереди завершается раньше зависшего провайдера. Полный прогон —
552 pytest.

## Решения F4

- Граница «нет провайдера» и «провайдер сломался» разная. Если LLM вообще не
  настроена (пустые модель/ключ), показываем пословные жесты F2 с
  `degraded=True`: это предохранитель ТЗ 5.3 и полезная деградация. Если же
  настроенная LLM упала, вернула мусор или не уложилась в таймаут — жесты не
  показываем вовсе, только субтитры, как прямо требует F4 и ТЗ 5.7: лучше
  молчать жестами, чем показать неверный перевод.
- `pipeline/gloss_engine.py` отделён от `services/gloss.py`: сервис остаётся
  чистым и не знает Django, а движок собирает словарь из БД, выбирает провайдера
  и превращает сбои в `GlossOutcome`. `GlossOutcome` несёт `degraded`,
  `source` и измеренный `elapsed_ms`; в событие уходит только `degraded`, а
  причина остаётся в логах/тестах.
- В async-пути словарь читается через `database_sync_to_async`, а не внутри
  `to_thread`: поток LLM не трогает ORM и не оставляет там соединение. После
  чтения словаря и после задания очередь закрывает соединения фонового потока,
  иначе долгоживущий цикл удерживал бы их между редкими фразами.
- Таймаут двойной: `asyncio.wait_for` жёстко ограничивает ожидание, а тот же
  `LLM_TIMEOUT` передаётся в `urlopen`, чтобы HTTP-запрос тоже завершился.
  `wait_for` отменяет ожидание, но не умеет убить поток; просроченный поток
  доработает в фоне, а его результат будет отброшен. Поэтому event loop и
  consumer не блокируются.
- Провайдер из настроек не создаётся без `LLM_MODEL`, а для OpenAI-compatible
  API — без `LLM_API_KEY`: иначе `.env.example` с пустыми значениями отправлял
  бы каждый тест и каждую фразу в сеть. Для Ollama ключ не нужен, URL по
  умолчанию — локальный `127.0.0.1:11434`.
- `LLM_API_URL` необязателен и позволяет указать прокси/свой endpoint;
  `LLM_TIMEOUT` по умолчанию 8 с (ориентир ТЗ 5.7). Оба значения добавлены в
  `.env.example`.
- `create_utterance` сохраняет обратную совместимость E1: без аргумента
  `glosses` он по-прежнему строит упрощённые глоссы. F4 передаёт готовый объект,
  `gloss_ms` и `degraded`; сервер сам подставляет в него нормализованные
  `text`/`lang`, а `unknown` очереди пересобирает из токенов `fingerspell`.
- Очередь научилась принимать async-обработчик, но старые синхронные функции и
  тестовые процессоры продолжают работать через `asyncio.to_thread`. Это
  сохранило E2-тесты и позволило F4 не запускать вложенный `asyncio.run` на
  каждом задании (он ждал бы executor при таймауте).

## Проверка F5

```bash
.venv/bin/python -m pytest services/tests/test_asr.py -q
```

Тесты не скачивают веса и не требуют GPU: WAV собирается стандартным `wave`,
а `faster_whisper.WhisperModel` подменяется фабрикой. Проверяются ленивая
загрузка модели ровно один раз, лимит параллелизма и то, что event loop
продолжает работать во время `transcribe_async`. Полный прогон — 567 pytest.

Для ручной проверки нужен установленный `faster-whisper` и доступ к весам
(`WHISPER_MODEL=small`, `WHISPER_DEVICE=cpu`); модель скачается при первой
фразе и останется в кэше Hugging Face. Аудио в тестах и в сервисе не
сохраняется на диск.

## Решения F5

- `services/asr.py` следует контракту ТЗ 7.1: вход — байты одной фразы,
  выход — `AsrResult(text, duration_ms)`. `duration_ms` — длительность
  исходного аудио из `TranscriptionInfo`, а не время работы модели: метрику
  `asr_ms` измеряет конвейер F6, как и `gloss_ms` в F4.
- Модель загружается лениво и только один раз, под отдельным `threading.Lock`.
  Импорт `faster_whisper` тоже ленивый: тесты и команды, которым ASR не нужен,
  не платят за `ctranslate2` и не требуют весов. Если пакета нет, ошибка
  `AsrUnavailableError` объясняет, что установить.
- `AsrService` держит собственный `ThreadPoolExecutor` и
  `BoundedSemaphore(ASR_MAX_CONCURRENCY)`: ограничение распознавания не
  смешивается с другими `asyncio.to_thread`, а лишние фразы ждут, а не
  плодят потоки. Sync `transcribe` нужен тестам и скриптам, async
  `transcribe_async` — конвейеру; ни один путь не блокирует event loop.
- Язык комнаты `ru`/`kk` передаётся Whisper как есть; `rsl`/`ksl` сводятся к
  языку речи. Другие коды отклоняются: словарь проекта ограничен русским и
  казахским, а случайный `en` дал бы неожиданные субтитры.
- Вычисления: CPU → `int8`, CUDA → `float16`, `auto` → `default`. Это
  ориентир ТЗ 5.2 для `small` на 4 vCPU; точный выбор остаётся за
  `WHISPER_DEVICE`, а `WHISPER_MODEL` может быть именем или путём к локальной
  модели.
- Ошибки модели не глотаются: провайдер оборачивает их в `AsrError`, пул — в
  `AsrError`, таймаут — в `AsrTimeoutError`. F6 логирует такую ошибку и
  завершает `Future` ошибкой: без распознанного текста субтитров нет, поэтому
  пустая фраза не создаётся.
- `faster-whisper==1.2.1` — новая зависимость этапа (ТЗ 6); в Dockerfile
  добавлен `libgomp1`, нужный CTranslate2. Веса моделей в образ не входят:
  они скачиваются при первом использовании и кэшируются Hugging Face.
- Тест на WAV намеренно использует подменённую модель: реальный `small`
  требует сотни мегабайт и сеть, что сделало бы `make check` невоспроизводимым.
  Контракт провайдера при этом проверяется на настоящих байтах WAV.

## Проверка F6

```bash
.venv/bin/python -m pytest pipeline/tests/test_phrase_api.py -q
.venv/bin/python -m pytest pipeline/tests/test_audio_processing.py -q
```

Тесты эндпоинта подменяют `submit_audio`, поэтому не запускают модель. Тесты
обработки подменяют `pipeline.queue.transcribe_async` и проверяют весь путь до
`Utterance` без скачивания весов. Полный прогон — **584 pytest**, `make check`
зелёный. Для ручной проверки нужен реальный файл WAV/Opus и настроенный
`faster-whisper`; аудио после распознавания нигде не остаётся.

## Решения F6

- `POST /api/rooms/<code>/phrase/` (`phrase_api`) повторяет правила E2: аноним
  401, чужой преподаватель 403, закрытая/неизвестная комната 404. Успех — 202
  `{"status": "accepted"}`; запрос не ждёт ASR, глосс и сохранения.
- Multipart принимает поле `audio` (для совместимости — `file`). Файл читается
  в память, `UploadedFile.close()` вызывается сразу, в `MEDIA_ROOT` ничего не
  пишется. Лимит 2 МиБ: 8 с WAV 16 кГц mono 16 бит занимают около 256 КБ, а
  Django держит такой файл в памяти, не создавая временный на диске.
- `AudioJob` идёт в ту же очередь комнаты, что и текст: порядок фраз не
  нарушается, переполнение `ROOM_QUEUE_MAX` работает одинаково. Обработчик по
  умолчанию — `process_phrase_job_async`, который различает `TextJob` и
  `AudioJob`.
- ASR вызывается через `services.asr.transcribe_async` под
  `asyncio.wait_for(..., ASR_TIMEOUT)` (по умолчанию 20 с). `asr_ms`
  измеряется только вокруг распознавания; `gloss_ms` по-прежнему измеряет LLM.
  Язык распознавания берётся из `room.lang`, язык жестов — из того же правила
  `ru → rsl`, `kk → ksl`.
- После ASR текст сразу уходит событием `asr_text`, затем общий путь F4
  считает глоссы, сохраняет `Utterance` с `asr_ms` и рассылает `utterance`.
  Если ASR вернул пустую строку (тишина), фраза и события не создаются.
- Ошибка или таймаут ASR логируются и завершают `Future` задания ошибкой:
  распознанного текста нет, поэтому «субтитры» показать нечем; воркер комнаты
  продолжает работу. Таймаут/ошибка LLM после успешного ASR, как и в F4, даёт
  `degraded=True` и пустые токены.
- Аудио не попадает ни в модель, ни в медиа, ни в лог: в логах только комната
  и размер задания. После обработки воркер сбрасывает ссылку на последнее
  задание, чтобы байты не удерживались в памяти.

## Проверка F7

```bash
npm test -- frontend/audio-phrase.test.ts frontend/microphone.test.ts
.venv/bin/python -m pytest rooms/tests/test_views.py -q
make check
```

`make check` зелёный: ruff, `tsc`, **271 vitest** в 22 файлах, **585 pytest** и
production-сборка Vite. Сборка выпускает `vad-web-worker-*.js` (~896 КБ) и
`ort-wasm-simd-threaded.jsep-*.wasm` (~21,6 МБ), но они не входят в начальную
загрузку панели: модуль VAD импортируется динамически после нажатия кнопки.

Ручная проверка F7 (нужен реальный микрофон):

1. Запустить `make up` или `make client-dev`, открыть панель преподавателя
   `/rooms/<code>/live/` по HTTPS или на `localhost` (иначе браузер не даёт
   `AudioWorklet` и микрофон).
2. Нажать «Включить микрофон» и разрешить доступ. Первый запуск скачивает
   Silero VAD (модель — Hugging Face, runtime WASM — jsDelivr), поэтому нужен
   исходящий доступ; далее модель кэшируется браузером.
3. Сказать фразу и сделать паузу: статус проходит «Слышу речь…» → «Отправляем
   фраз: 1», счётчик отправленных фраз растёт. Студент должен получить
   `asr_text`, затем `utterance` и жесты (при настроенном ASR).
4. Ввести фразу в текстовую форму при выключенном или сломанном микрофоне —
   запасной режим FR-7 работает независимо.
5. Закрыть комнату или уйти со страницы — запись останавливается; в закрытой
   комнате кнопка микрофона отключена.

## Решения F7

- Взят `vad-web@0.7.0` (ocavue), как указано в ТЗ. Пакет сам держит Silero VAD
  в Web Worker, открывает микрофон и вызывает `onSpeechAvailable` с готовым
  `Float32Array` 16 кГц; своих порогов VAD и второй библиотеки мы не добавляем.
- VAD загружается динамическим `import("vad-web")` только после нажатия кнопки.
  Это сохраняет быстрый первый экран панели и не скачивает worker/WASM тем, кто
  пользуется только текстом.
- `frontend/audio-phrase.ts` кодирует Float32 в PCM16 WAV 16 кГц mono вручную:
  сервер уже принимает WAV, а Opus-энкодер потянул бы лишнюю зависимость. WAV
  получается ~32 КБ на секунду, максимум VAD-фрагмента (~30 с) — меньше 1 МБ,
  то есть в серверный лимит 2 МиБ. Ориентир ТЗ 2–8 с не обрезается: короткие
  команды вроде «Да» тоже полезны, а длинную речь `vad-web` режет по паузам.
- Фразы отправляются строго последовательно через цепочку промисов: иначе
  короткая вторая фраза могла бы обогнать первую и сломать порядок `seq` в
  конвейере. Ошибка одной отправки показывается, но не выключает микрофон и не
  блокирует текстовую форму.
- `MicrophoneController` сначала проверяет secure context, `AudioWorklet` и
  `mediaDevices`, затем загружает VAD. Отказ в доступе, отсутствие микрофона,
  занятое устройство и HTTP переводятся в понятные русские подсказки.
- Состояния карточки: выключен, загрузка, слушаю, слышу речь, отправка, ошибка.
  Они продублированы в `data-state` для CSS и `aria-live`, а счётчик показывает
  число принятых сервером фраз.
- `pagehide` освобождает запись, `room_closed` вызывает `disable()`: VAD
  останавливается, кнопка блокируется, новые фразы после закрытия не
  отправляются. В закрытой комнате кнопка отключена уже в шаблоне.
- `vad-web` тянет `@huggingface/transformers`/`onnxruntime-web`; Vite сам
  собирает worker и wasm-ассет без изменений `vite.config.ts`. Локальный
  wasm-файл в сборке — запасной артефакт библиотеки; по умолчанию transformers
  берёт runtime с jsDelivr, а модель — с Hugging Face.
- Текстовый ввод (FR-7) не спрятан и не зависит от состояния микрофона:
  карточки стоят рядом, ошибка VAD оставляет форму доступной.

## F8: управление отставанием

- **Пороги и политика (FR-15/FR-16):** `pipeline/lag_policy.py` — чистая
  `lag_playback_policy(lag_ms)` поверх существующего `lag_level`. Зелёный
  уровень (`≤5 с`) не трогает ручную скорость студента, оставляет паузу 120 мс
  между клипами и не сжимает текст. Жёлтый (`≤10 с`) включает скорость 1.15x,
  паузу 40 мс и сжатие до 75%. Красный (`>10 с`) — 1.3x, `gap_ms = 0` и сжатие
  до 50%. Политика отдаётся в событии `utterance` (поле `playback`) и
  сохраняется у `Utterance`, чтобы история и переподключение показывали фразу
  теми же параметрами.
- **Сжатие в конвейере:** перед глоссами `_finish_phrase_async` берёт
  `latest_display_lag_ms` комнаты (метрику последней показанной фразы),
  выбирает политику и при жёлтом/красном вызывает `services.gloss.compress` в
  `asyncio.to_thread` под `COMPRESS_TIMEOUT` (по умолчанию 4 с). Если LLM не
  настроена, упала или не уложилась в таймаут, F3 переходит на локальное
  сжатие; при любой ошибке остаётся исходный текст. Сжатие применяется только
  к фразам от 24 символов, чтобы не тратить LLM на короткие команды.
- **Текущая фраза:** после `display_started` consumer по-прежнему отправляет
  преподавателю `lag_status`, а студенту — новое событие `playback` с
  актуальными `speed`/`gap_ms`. `RoomPhrasePlayer.setPlaybackPolicy` меняет
  скорость и паузу уже играющего `ClipPlayer` без перезапуска; сжатие
  применится к следующей фразе. `ClipPlayer.setGapMs` пересобирает план,
  сохраняя текущий клип и кадр.
- **Клиент:** `frontend/lag-policy.ts` нормализует событие, не доверяя числам,
  и совмещает догон с ручной скоростью C7: на зелёном остаётся 0.6–1.2x, на
  жёлтом/красном берётся максимум из ручной и серверной скорости с потолком
  1.3x. `UtteranceEvent` получил необязательное поле `playback`; старые записи
  без него играют как раньше.
- **Хранение:** `Utterance.playback` — `JSONField` (миграция
  `pipeline/0002_utterance_playback.py`), `as_event()` отдаёт его в истории и
  WebSocket. Поле есть и у фраз, созданных путём E1 (пустой объект).
- **Проверка:** `pipeline/tests/test_lag_policy.py` — границы 5/10 с, значения
  скорости, пауз и коэффициентов, короткие фразы;
  `pipeline/tests/test_lag_pipeline.py` — зелёная фраза не сжимается,
  жёлтая/красная сжимаются, чужая комната не влияет;
  `rooms/tests/test_consumer.py` — преподаватель получает `lag_status`, студент
  `playback`; `frontend/lag-policy.test.ts` — нормализация и совмещение
  скоростей. Ручная проверка: отправить несколько длинных фраз, дождаться
  красного индикатора и убедиться, что следующая фраза короче и показывается
  быстрее без пауз.

## G1: PWA — манифест, иконки и service worker

- **Манифест и SW с корня сайта (FR-23):** `config/pwa.py` отдаёт
  `/manifest.webmanifest` и `/sw.js` обычными представлениями, а не статикой:
  service worker получает область видимости `/` (`Service-Worker-Allowed: /`)
  и управляет страницами комнаты (`/r/<code>/`, `/rooms/<code>/`). Манифест —
  `application/manifest+json`, `display: standalone`, `scope: /`, тема
  `#1f2937`; иконки берутся через `static()` и потому переживают
  `collectstatic` с хэшем.
- **Иконки:** `static/img/pwa/icon-192.png`, `icon-512.png`,
  `maskable-512.png`. Генерируются скриптом `scripts/make_pwa_icons.py`
  (чистый Python, PNG через `zlib` — без Pillow): знак «жест» на градиенте,
  maskable с запасом по краям.
- **Версия кэша (FR-24):** `config.pwa.cache_version()` = номера
  `DictionaryVersion` обоих языков + короткий хэш имён файлов из манифеста Vite.
  Строка вшивается в шаблон `templates/pwa/sw.js` при отдаче, поэтому новая
  версия словаря (утверждение жеста) или новая сборка клиента меняют имя кэша.
- **Service worker:** шаблон `templates/pwa/sw.js`. Три кэша (`shell`,
  `runtime`, `clips`) с префиксом `gluho-nemye:` и версией в имени. `install`
  прогревает оболочку (CSS и собранный `main.ts`) и вызывает `skipWaiting`;
  `activate` удаляет все кэши с чужой версией и вызывает `clients.claim`.
  Клипы (`/media/clips/*.json.gz`) и статика (`/static/*`) кэшируются
  `cache-first` (клипы неизменяемы), навигация — `network-first` с офлайн-
  фолбэком на закэшированную оболочку. GET только своего источника; WebSocket
  и `/api/` не перехватываются.
- **Клиент:** `frontend/pwa.ts` — чистая логика (`manifestUrl`,
  `serviceWorkerUrl`, `requiredLinks`, `pwaSupport`,
  `canRegisterServiceWorker`, `isLocalhost`, `isHttps`) и
  `registerServiceWorker`/`setupPwa`. Регистрация откладывается до `load`,
  идёт только на HTTPS или localhost и не ломает страницу при ошибке.
  `frontend/main.ts` вызывает `setupPwa()`; `templates/base.html` подключает
  манифест, `theme-color` и apple-touch-иконки.
- **Проверка:** `tests/test_pwa.py` — манифест, иконки, `Service-Worker-Allowed`,
  версия кэша (растёт вместе с `DictionaryVersion.bump`), мета-теги главной;
  `frontend/pwa.test.ts` — адреса, `<link>`, поддержка, регистрация и её
  ошибки. Ручная проверка (Lighthouse PWA): открыть сайт по HTTPS, установить
  приложение на домашний экран, перезайти — клипы и статика отдаются из
  `Cache Storage`, а после утверждения жеста версия кэша меняется.

## G2: предложение установки PWA

- **Чистая логика (FR-27):** `frontend/install-prompt.ts` — `installEnvironment`
  определяет iOS/iPadOS (по `userAgent`, а для iPadOS 13+ — по
  `Macintosh` + `maxTouchPoints > 1`), standalone-режим и поддержку
  `beforeinstallprompt`; `installOffer` выбирает способ: `native` (Chromium),
  `ios` (Safari на iOS) или ничего (установлено / отказались / настольный
  Safari). Отметка отказа — `gluho-nemye:install-prompt:v1` в `localStorage`
  (`isInstallDismissed`/`markInstallDismissed`/`resetInstallDismissed`).
- **Карточка:** класс `InstallPrompt` слушает `beforeinstallprompt` (гасит
  системный мини-бар, показывает свою карточку), вызывает `event.prompt()` по
  кнопке «Установить» и запоминает выбор. На iOS кнопку «Установить» прячет и
  показывает инструкцию «Поделиться → На экран Домой». Разметка
  `[data-install-prompt]` (заголовок, `[data-install-hint]`,
  `[data-install-accept]`, `[data-install-dismiss]`) добавлена в
  `templates/rooms/student.html` и скрыта до решения клиента.
- **Подключение:** `frontend/room-live.ts` создаёт `InstallPrompt` только для
  студенческой страницы (`isStudentView`), панель преподавателя карточку не
  содержит. Предложение необязательное — страница работает и без установки,
  отказ запоминается и больше не показывается.
- **Стили:** `.install-prompt` в `static/css/base.css` (карточка с кнопками,
  перенос на узких экранах).
- **Проверка:** `frontend/install-prompt.test.ts` (21) — окружение (iOS,
  iPadOS, Android, десктопный Safari), выбор способа, отметка отказа,
  поведение карточки (показ, `accept`, `dismiss`, standalone);
  `rooms/tests/test_join.py::test_live_offers_pwa_install_after_join` — карточка
  в разметке студенческой страницы. Ручная проверка (FR-27): на Android
  (Chrome) карточка появляется после входа и вызывает системный диалог; на
  iPhone (Safari) показывается инструкция; после отказа карточка не появляется.

## G3: скрипт нагрузки

- **Скрипт:** `scripts/load_test.py`. Поднимает N виртуальных студентов
  (по умолчанию 30), подключает их к `WS /ws/rooms/<code>/` и измеряет
  handshake, доставку сообщения чата (медиана/p95), распространение presence и
  рост RSS процесса сервера.
- **Подготовка:** комната и гостевые сессии создаются тем же путём, что у
  студента — `POST /r/<code>/` через Django test client; подписанная
  `sessionid` берётся из куки. Так сервер принимает соединения без обхода
  проверок A8. У каждого клиента свой `X-Forwarded-For`, поэтому лимит на
  перебор ID (10 на IP) не мешает входу. Скрипт и сервер должны иметь один
  `SECRET_KEY`.
- **Пороги:** задержка — из ТЗ (медиана ≤ 4 с, p95 ≤ 7 с), p95 подключения ≤ 3 с,
  необязательный `--max-rss-growth` для памяти. Коды возврата: 0 — ок, 1 —
  превышены пороги, 2 — ошибка запуска. `--json` печатает сводку машинно.
- **Зависимости:** новых нет. `websockets` уже приходит с `uvicorn[standard]`,
  Django — сам проект. Память читается из `/proc` (Linux) или `ps` (macOS).
- **Замер на локальном uvicorn (30 клиентов, compose-Postgres):** подключилось
  30/30, p95 handshake ~10 мс, доставка чата медиана ~11 мс / p95 ~11 мс,
  presence увидели все, рост RSS ≈ 0,3 МиБ. Критерий приёмки №5 выполняется;
  полный стек в Docker меряется на этапе G4.
- **Проверка:** `tests/test_load_script.py` (13) — перцентили, оценка порогов
  (клиенты, задержка, подключение, память), разбор URL, `human_bytes`, RSS
  текущего процесса. Прогон на сервере делается вручную командой из README.

## G4: прод-конфигурация

- **docker-compose:** `restart: unless-stopped` у всех сервисов, логи с
  ротацией (`max-size 10m`, `max-file 3`), порты `db`/`redis` только на
  loopback (наружу смотрят только Caddy :80/:443). У `web` healthcheck через
  `GET /health/`, `caddy` стартует после `condition: service_healthy` у `web`;
  HTTP/3 (`443/udp`). Named volumes: `pgdata`, `media`, `caddy_data`,
  `caddy_config`.
- **Caddy с HTTPS:** `Caddyfile` берёт адрес из `SITE_ADDRESS` (`:80` локально,
  домен — автоматический TLS Let's Encrypt), `ACME_EMAIL` для ACME. Заголовки
  `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy`,
  `X-Frame-Options`. Клипы раздаёт сам Caddy из `/srv/media` с `immutable`-кэшем;
  остальное — `reverse_proxy web:8000`, WebSocket проксируется автоматически.
- **Django при `DEBUG=False`:** `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
  `SECURE_HSTS_SECONDS`/`INCLUDE_SUBDOMAINS`/`PRELOAD`, `SECURE_CONTENT_TYPE_NOSNIFF`,
  `SECURE_REFERRER_POLICY`, `X_FRAME_OPTIONS=DENY`; SSL-редирект делает Caddy
  (`SECURE_SSL_REDIRECT` по умолчанию off).
- **Хранение данных (ТЗ 17):** `settings.RETENTION_DAYS` (ориентир 90) и команда
  `purge_old_data` (`pipeline/retention.py`, `--days`, `--dry-run`): удаляет
  сообщения чата и фразы старше срока, а также закрытые комнаты, закрытые раньше
  срока (каскадом — участники, чат, фразы). Открытые комнаты не трогает.
- **Бэкап:** `scripts/backup.sh` — `pg_dump` в gzip + копия каталога клипов через
  `docker compose cp`, контрольные суммы SHA-256, ротация `BACKUP_KEEP` копий;
  готов к cron и переносу на другой хост.
- **Инструкция:** `docs/DEPLOY.md` — от чистого хоста до работающего сервиса
  (≤ 15 минут), резервные копии и очистка по cron, обновление, логи, вариант «за
  прокси университета», откат из дампа.
- **Проверка:** `make check` зелёный; образ собирается, `docker compose up -d`
  поднимает стек, `web` становится healthy, `caddy` ждёт его и отвечает на
  `GET /health/`, `/manifest.webmanifest`, `/sw.js`, `/static/...` и раздаёт
  заголовки безопасности. `make load` против полного стека: 30/30 подключений,
  доставка чата медиана ~11 мс / p95 ~17 мс, рост RSS в контейнере ≈ 0.2 МиБ.
  Тесты: `tests/test_retention.py` (7), `tests/test_deploy.py` (8),
  `tests/test_load_script.py` (+3, память хоста/контейнера).

## G5: README, схема архитектуры, инструкция редактору словаря

- **README:** добавлен раздел «Архитектура» с ASCII-схемой компонентов (браузеры,
  Caddy, Django/ASGI, PostgreSQL, Redis, том клипов) и коротким путём одной фразы
  от VAD до `lag_status`; добавлен раздел «Словарь жестов» и ссылки на новые
  документы. Быстрый старт, команды и разделы блоков A–G уже были на месте —
  новый человек поднимает проект по инструкции.
- **Инструкция редактору словаря:** `docs/DICTIONARY.md` — роли и матрица прав,
  адреса страниц словаря, пошаговый процесс (запись жеста с камеры D1–D2,
  сохранение черновика D3, отправка на проверку, решение эксперта B4/B6, очередь
  нераспознанных слов B7), работа через API и Django Admin, роль версии словаря в
  кэше PWA. Основа — ТЗ раздел 9.
- **Проверка:** `make check` зелёный (изменения только в документации: код и тесты
  не затронуты).

## H1: анимационные жесты (VRMA/glTF)

- **Модель:** `dictionary.ClipFormat` (`landmarks`/`animation`),
  `SignClip.format` (миграция `0002_signclip_format`) и
  `SignClip.animation_name` (миграция `0003_signclip_animation_name`) — какая
  запись внутри файла. У клипа появились `is_animation`, `file_ext`,
  `file_url()` с расширением; `best_clip` и `pipeline.events.select_best_clip`
  предпочитают анимацию landmarks.
- **Приём и хранение:** `services/clips.py:parse_animation` проверяет GLB
  (сигнатура, версия 2, длина, JSON-чанк, наличие анимаций, лимит
  `CLIP_MAX_ANIMATION_BYTES` = 20 МиБ), возвращает имена и длительности каждой
  записи. `create_sign(animation=…, animation_name=…, animation_clip=…)`
  сохраняет файл `.vrma`/`.glb` и запись `SignClip(format=animation,
  animation_name, frames=0, duration_ms выбранной записи,
  fps=ANIMATION_DEFAULT_FPS)`. Неизвестное имя записи — ошибка; оба файла
  (landmarks + анимация) одновременно — `400`.
- **Один файл — много жестов:** команда
  `dictionary/management/commands/import_animations.py` читает GLB, по умолчанию
  считает имя анимации глоссой (или `--map ГЛОССА=АНИМАЦИЯ`), создаёт жесты и
  клипы, хранит файл один раз (`media/clips/import/<имя>-<хеш>.<ext>`),
  идемпотентна; есть `--only` и `--dry-run`.
- **API и отдача:** `POST /api/signs/` принимает multipart-поля `animation` и
  `animation_clip` (`413` на превышение); `format`/`animation_name` есть в
  `sign_payload` и в ссылках на клипы события `utterance`. Файл отдаётся по
  `/media/clips/<id>.<ext>` с `model/gltf-binary`, ETag и `immutable`-кэшем.
- **Клиент:** `frontend/animation-clip.ts` разбирает GLB, отдаёт
  `AnimationBundle` и выбирает запись по имени (`pickAnimationClip`); VRMA
  распознаётся и даёт `VrmaNotSupportedError` (пакет
  `@pixiv/three-vrm-animation` не подключён — новые зависимости только по
  просьбе). `frontend/animation-player.ts` играет очередь через
  `AnimationMixer` с crossfade 150–250 мс, скоростью 0.6–1.3x и возвратом в
  нейтраль. `frontend/room-phrase.ts` кэширует файлы по URL (несколько жестов
  из одного GLB не качаются повторно) и играет фразу целиком из анимаций;
  смешанная фраза (анимации + дактиль landmarks) пока показывает только
  landmarks с предупреждением в статусе.
- **Документация:** `docs/ANIMATIONS.md` — как готовить анимации в Blender,
  имена файлов/записей, загрузка через API, импорт файла с несколькими жестами,
  что реализовано, чек-лист при готовности модели и точный шаг включения VRMA.
- **Проверка:** `tests/test_animation_clips.py`, vitest
  `animation-clip.test.ts` + `animation-player.test.ts`, полный
  `make check` зелёный.

## Дальше

**Все этапы плана (блоки A–G) готовы.** Дальнейшая работа — наполнение словаря
(редактор и эксперт-носитель, блок D и `docs/DICTIONARY.md`), выбор языка и темы
MVP, проверка на реальных iPhone/Android и с глухими пользователями — это шаги
вне задач агента (ТЗ 15.3).

