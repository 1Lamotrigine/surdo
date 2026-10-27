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
make check               # ruff + tsc + vite build + pytest (поднимает контейнер db)
docker compose up --build -d
docker compose exec web python manage.py migrate
```

Стартовая страница: <http://localhost/> (через Caddy), health: <http://localhost/health/>.

На этапе A2 доступен тестовый WebSocket-эхо `ws://localhost/ws/echo/<group>/`
(только при `DEBUG=True`). Два клиента одной группы получают общие сообщения.

## Клиент в разработке

По умолчанию `DJANGO_VITE_DEV_MODE=False`: Django отдаёт собранные файлы из
`static/dist` (они попадают в Docker-образ). Для HMR:

```bash
# в .env: DJANGO_VITE_DEV_MODE=True
make client-dev          # Vite на http://localhost:5173
make up                  # страница подключает модуль с dev-сервера
```

`make client-build` пересобирает `static/dist`, `make client-typecheck` проверяет
TypeScript.

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
make check            # ruff + tsc + vite build + pytest
make lint             # только ruff
make test             # vite build + только pytest
make client-dev       # Vite dev-сервер с HMR
make client-build     # production-сборка клиента
make client-typecheck # проверка TypeScript
make up               # docker compose up --build
make down             # остановить стек
make migrate          # применить миграции
make logs             # логи web
```

## Документация

- Полное ТЗ: `../TZ_django.md`
- Правила для агента: `AGENTS.md`
- Состояние и план этапов: `docs/STATE.md`
