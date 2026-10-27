# Состояние проекта

Обновлено: 2026-10-27

## Текущий этап

**D1 — камера и MediaPipe Holistic: готов.**

## Что готово

- Django-проект (`config`) и приложения `accounts`, `rooms`, `dictionary`, `pipeline`.
- Пакет `services` (без Django-моделей): `services.clips` — хранилище клипов.
- Настройки из переменных окружения: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`,
  `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `REDIS_URL`, `MEDIA_ROOT`, `LOG_LEVEL`,
  `DJANGO_VITE_DEV_MODE`, `DJANGO_VITE_DEV_SERVER_HOST`, `DJANGO_VITE_DEV_SERVER_PORT`,
  `ROOM_PING_INTERVAL`, `ROOM_PING_TIMEOUT`, `AVATAR_MODEL_URL`,
  `MEDIAPIPE_HOLISTIC_MODEL_URL`.
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
  Vite-плагином, модель задаётся `MEDIAPIPE_HOLISTIC_MODEL_URL`; запись клипа —
  этап D2.
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
| История для переподключения | `GET /api/rooms/<code>/history/?after_seq=&after_message_id=` → `rooms.api.chat_history_api` |
| Файл клипа жеста (ETag/304) | `GET /media/clips/<id>.json.gz` → `dictionary.views.clip_file` |
| Список словаря (публичный) | `GET /api/dictionary/?lang=&status=` → `dictionary.api.dictionary_api` |
| Создание жеста (редактор) | `POST /api/signs/` → `dictionary.api.create_sign_api` |
| Решение эксперта (API) | `POST /api/signs/<id>/review/` → `dictionary.api.review_sign_api` |
| Очередь на проверке | `GET /dictionary/review/` → `dictionary.views.review_queue` |
| Карточка жеста (решение) | `GET/POST /dictionary/review/<id>/` → `dictionary.views.review_sign` |
| Очередь нераспознанных слов | `GET /dictionary/queue/` → `dictionary.views.unknown_queue` |
| Запись жеста с камеры (D1) | `GET /dictionary/record/` → `dictionary.views.record_gesture` |
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
- `dictionary/tests/test_record_page.py` — страница D1: вход, роли словаря,
  разметка камеры/холста/кнопок, передача модели и пути WASM, ссылка из очереди
  нераспознанных слов.
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
- `services/tests/test_clips.py` — `FileClipStorage`: сохранение/чтение,
  создание каталогов, `exists`, `open`, `size`, `delete`, стабильность и
  чувствительность ETag, сборка URL.
- `dictionary/tests/test_clip_view.py` — раздача клипа: тело ответа,
  `Cache-Control`/`ETag`, **304 на повторный запрос**, разные ETag у разных
  клипов, 404 для неизвестного клипа и отсутствующего файла.
- `services/tests/test_clip_format.py` — `pack_clip`/`parse_clip`: roundtrip,
  gzip/JSON, версия, `fps`/`frames`, лимит кадров, `layout`/`data`,
  `duration_ms`.
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
  (доступ, список, пустая очередь, действие «взять в работу»/«записать»).
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
  неизвестный жест (404), версия словаря.
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

## Дальше

**D1 готов.** Следующий — D2: запись клипа (старт/стоп, обрезка начала и конца,
One Euro, упаковка в формат клипа) и проверка обратимости упаковки. Читать:
`docs/spec/clip-format.md`, `docs/spec/requirements.md` (3.5), текущие
`frontend/clip.ts`, `frontend/one-euro.ts`.


Пополнение очереди из реальных занятий подключается в блоке **E**
(`record_unknown_word` вызывается для слов без жеста), а запись жеста из очереди —
в блоке **D** (`D4`: слово получает статус `recorded`).
