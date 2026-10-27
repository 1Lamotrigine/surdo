# Развёртывание (G4)

Инструкция для сервера университета: от чистого хоста до работающего сервиса
за ≤ 15 минут. Весь стек — Docker Compose: `web` (Django + uvicorn), `db`
(Postgres 16), `redis` (Redis 7), `caddy` (HTTPS и раздача клипов).

> Прототип помощника-сурдопереводчика. Персональные данные (имя гостя, чат,
> фразы) хранятся ограниченное время, аудио не сохраняется вовсе (ТЗ 17).

## Что нужно заранее

- Сервер с Docker и плагином Docker Compose (`docker compose version`).
- Домен, указывающий на IP сервера (для HTTPS от Caddy), например
  `lecture.example.org`. Если HTTPS обеспечивает прокси университета — домен
  не нужен, см. раздел «За прокси».
- ~5 ГБ свободного места (образы, база, клипы).

## Шаги

### 1. Код на сервере

```bash
git clone <репозиторий> gluho-nemye && cd gluho-nemye
```

### 2. Настройки `.env`

```bash
cp .env.example .env
```

Заполните прод-значения:

| Переменная | Значение |
| --- | --- |
| `SECRET_KEY` | длинная случайная строка (`openssl rand -hex 32`) |
| `DEBUG` | `False` |
| `SITE_ADDRESS` | ваш домен, например `lecture.example.org` (для HTTPS) |
| `ACME_EMAIL` | почта для Let's Encrypt |
| `ALLOWED_HOSTS` | домен: `lecture.example.org` |
| `CSRF_TRUSTED_ORIGINS` | `https://lecture.example.org` |
| `DB_PASSWORD` | пароль базы (и тот же в `DATABASE_URL`) |
| `ADMIN_EMAIL`/`ADMIN_PASSWORD`/`ADMIN_NAME` | начальный администратор |
| `RETENTION_DAYS` | срок хранения данных, ориентир `90` |

LLM и распознавание речи необязательны: без `LLM_MODEL`/`LLM_API_KEY` работает
упрощённый режим, а ASR подключается моделью `WHISPER_MODEL`.

### 3. Запуск

```bash
docker compose up -d --build     # соберёт образ (клиент Vite + Python) и поднимет стек
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_admin
```

Проверьте `GET /health/` — он отвечает `{"status": "ok"}` и проверяет базу:

```bash
curl -s https://lecture.example.org/health/
```

Caddy сам получит TLS-сертификат при первом запросе к домену (нужен доступ в
интернет на 80 и 443).

### 4. Проверка

Откройте `https://lecture.example.org/`, войдите администратором в `/admin/`,
создайте комнату и войдите студентом с телефона. WebSocket-ы Caddy проксирует.

Нагрузку (комната на 30 клиентов, критерий приёмки №5) можно проверить с
машины, где лежит репозиторий:

```bash
make load LOAD_URL=https://lecture.example.org LOAD_CLIENTS=30
```

## Обслуживание

### Резервные копии по cron

`scripts/backup.sh` делает `pg_dump` базы и копию каталога клипов, сжимает и
хранит последние `BACKUP_KEEP` копий:

```bash
BACKUP_DIR=/mnt/backup ./scripts/backup.sh
```

Пример cron (ежедневно в 3:17):

```
17 3 * * * cd /srv/gluho-nemye && BACKUP_DIR=/mnt/backup ./scripts/backup.sh >> /var/log/gluho-backup.log 2>&1
```

Скопируйте каталог `BACKUP_DIR` на другой хост университета: копия на том же
сервере не защищает от отказа диска (ТЗ 18.3).

### Очистка старых данных

Хранение ограничено `RETENTION_DAYS`. Проверьте, что попадёт под удаление:

```bash
docker compose exec web python manage.py purge_old_data --dry-run
```

И добавьте в cron (раз в неделю):

```
23 4 * * 0 cd /srv/gluho-nemye && docker compose exec -T web python manage.py purge_old_data >> /var/log/gluho-purge.log 2>&1
```

Команда удаляет чат и фразы старше срока, а также закрытые комнаты, закрытые
раньше срока (вместе с их участниками). Аудио не хранится, чистить нечего.

### Обновление

```bash
git pull
docker compose up -d --build
docker compose exec web python manage.py migrate
```

### Логи и состояние

```bash
docker compose ps                 # статус и healthcheck сервисов
docker compose logs -f web        # логи приложения (stdout)
docker compose logs -f caddy      # логи TLS и прокси
```

Память и задержки видны в `GET /health/`, Django Admin (таблица `Utterance`) и
`docs/STATE.md`.

## За прокси университета

Если HTTPS и домен обслуживает внешний reverse proxy:

1. Уберите сервис `caddy` из `docker-compose.yml` (или не запускайте его).
2. Прокси должен передавать заголовок `X-Forwarded-Proto: https`
   (настройка `SECURE_PROXY_SSL_HEADER` уже это учитывает) и проксировать
   WebSocket по пути `/ws/`.
3. Клипы (`/media/...`) раздаёт тот же прокси из каталога с клипами (docker
   volume `media`) либо оставьте их отдавать через Django в разработке.

## Откат

Данные восстанавливаются из дампа:

```bash
gunzip -c backups/<дата>/db.sql.gz | docker compose exec -T db psql -U app app
```

Каталог клипов — из `backups/<дата>/media` в volume `media` (через
`docker compose cp`). Перед откатом остановите `web`, чтобы не писать в базу.
