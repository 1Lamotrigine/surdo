# ИИ-аватар сурдопереводчик для лекций

Прототип веб-сервиса: преподаватель говорит в микрофон, аватар в браузере показывает
фразу жестами, студенты видят субтитры и пишут вопросы в чат. Язык первой версии —
русский (русская речь и РЖЯ).

> Это прототип помощника, а не замена живому сурдопереводчику.

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
| `templates/`, `static/` | шаблоны, статика и HTMX |
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

## Документация

- Полное ТЗ: `../TZ_django.md`
- Правила для агента: `AGENTS.md`
- Состояние и план этапов: `docs/STATE.md`
