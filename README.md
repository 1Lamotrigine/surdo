# ИИ-аватар сурдопереводчик для лекций

Прототип веб-сервиса: преподаватель говорит в микрофон, аватар в браузере показывает
фразу жестами, студенты видят субтитры и пишут вопросы в чат. Язык первой версии —
русский (русская речь и РЖЯ).

> Это прототип помощника, а не замена живому сурдопереводчику.

## Требования

- Python 3.12 и [uv](https://docs.astral.sh/uv/) для локальной разработки;
- Docker и Docker Compose для полного стека и тестов;
- Node.js 22 понадобится на этапе A3.

## Быстрый старт

```bash
cp .env.example .env     # при необходимости поменяйте пароль и SECRET_KEY
make setup               # venv + зависимости Python
make check               # ruff + pytest (поднимает контейнер db)
docker compose up --build -d
docker compose exec web python manage.py migrate
```

Стартовая страница: <http://localhost/> (через Caddy), health: <http://localhost/health/>.

## Структура

| Путь | Назначение |
| --- | --- |
| `config/` | настройки, маршруты, ASGI/WSGI |
| `accounts/` | пользователи и роли |
| `rooms/` | комнаты, участники, чат, WebSocket |
| `dictionary/` | словарь жестов и клипы |
| `pipeline/` | обработка фраз |
| `services/` | ASR, глоссы, сжатие (pure Python) |
| `templates/`, `static/` | шаблоны и статика |
| `docs/spec/` | выжимки из ТЗ |
| `docs/STATE.md` | текущее состояние проекта |

## Команды

```bash
make check       # ruff check + pytest
make lint        # только ruff
make test        # только pytest
make up          # docker compose up --build
make down        # остановить стек
make migrate     # применить миграции
make logs        # логи web
```

## Документация

- Полное ТЗ: `../TZ_django.md`
- Правила для агента: `AGENTS.md`
- Состояние и план этапов: `docs/STATE.md`
