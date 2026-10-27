# Технологический стек, окружение и развёртывание

Источник: `TZ_django.md`, раздел(ы) 6, 18. Копия для этапов генерации.


## 6. Технологический стек

| Слой | Технологии |
| --- | --- |
| Веб-приложение | Django (актуальная LTS), Django Channels (WebSocket), uvicorn (ASGI), шаблоны Django и HTMX, Django Admin для словаря и ревью |
| База | PostgreSQL 16 в Docker (named volume), `pg_dump` в cron |
| Redis | Channel layer для Channels, ограничение перебора ID, счётчики presence |
| ИИ-модули (внутри проекта) | `faster-whisper`, клиент LLM API (`httpx`) или Ollama за интерфейсом, `pymorphy3` |
| Клиентские модули | Vite и TypeScript: Three.js, `@pixiv/three-vrm`, Kalidokit, MediaPipe Holistic, `vad-web`; интеграция через `django-vite`; PWA: manifest и service worker, отдаваемые с корня сайта |
| Хранилище клипов | Docker volume на сервере университета, раздаётся Caddy или Nginx; позже S3-совместимое |
| QR | `segno` (SVG на сервере) |
| Инфраструктура | Docker Compose: `web` (Django и uvicorn), `db` (postgres), `redis`, `caddy`; HTTPS через Caddy (либо reverse proxy университета) |
| Тесты | `pytest-django`, `vitest` |
| CI | GitHub Actions: тесты, линтер `ruff`, сборка образов |
| Мониторинг | Логи в stdout, метрики задержек в таблице `Utterance`, `GET /health/`, Django Admin |

Redis нужен для Channels (рассылка по комнатам между процессами) и для ограничения перебора ID, это один лишний контейнер. В разработке допускается in-memory channel layer. База везде PostgreSQL, SQLite не используется, чтобы не получить расхождений между разработкой и сервером. Версии Python, Django, Channels, Node и остальных зависимостей фиксируются в `AGENTS.md` и lock-файлах.

## 18. Окружение и развёртывание

### 18.1. docker-compose (каркас)

```yaml
name: gluho-nemye
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: [CMD-SHELL, pg_isready -U app]
      interval: 5s
      retries: 10
  redis:
    image: redis:7
  web:
    build: .
    container_name: gluho-nemye
    command: uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 1
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - media:/app/media
  caddy:
    image: caddy:2
    ports:
      - 80:80
      - 443:443
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - media:/srv/media:ro
      - caddy_data:/data
    depends_on:
      - web
volumes:
  pgdata:
  media:
  caddy_data:
```

Caddyfile (клипы раздаёт Caddy, остальное идёт в Django, WebSocket проксируется автоматически):

```
<ваш-поддомен> {
    handle /media/* {
        root * /srv
        file_server
    }
    handle {
        reverse_proxy web:8000
    }
}
```

Статику Django (админка) раздаёт WhiteNoise. Если HTTPS и домен обслуживает прокси университета, сервис `caddy` убирается, а клипы раздаёт тот прокси.

### 18.2. Переменные окружения

| Переменная | Назначение |
| --- | --- |
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | Базовые настройки Django |
| `DATABASE_URL`, `REDIS_URL` | Подключения к Postgres и Redis |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` | Провайдер LLM (API или локальная Ollama) |
| `WHISPER_MODEL`, `WHISPER_DEVICE` | Модель распознавания (`small`) и устройство (`cpu` или `cuda`) |
| `ASR_MAX_CONCURRENCY`, `ROOM_QUEUE_MAX` | Параллелизм распознавания и размер очереди комнаты |
| `MEDIA_ROOT`, `RETENTION_DAYS` | Каталог клипов и срок хранения чата и фраз |

### 18.3. Развёртывание

1. Клонировать репозиторий на сервер, создать `.env` по `.env.example`.
2. `docker compose up -d --build`.
3. `docker compose exec web python manage.py migrate` и `createsuperuser`.
4. Проверить `GET /health/`: база, Redis и модель распознавания загружены.
5. Бэкап по cron: `docker compose exec -T db pg_dump -U app app` в файл и копия на другой хост университета, плюс копия каталога клипов.
6. Обновление: `git pull`, `docker compose up -d --build`, миграции.
