#!/usr/bin/env bash
# Резервная копия (G4, ТЗ 18.3): дамп PostgreSQL и копия каталога клипов.
#
# Запуск на сервере, где работает `docker compose`:
#
#     ./scripts/backup.sh                 # в ./backups по умолчанию
#     BACKUP_DIR=/mnt/backup ./scripts/backup.sh
#     BACKUP_KEEP=14 ./scripts/backup.sh  # сколько последних копий хранить
#
# Скрипт делает:
#   1. `pg_dump` базы из контейнера `db` (пользователь и база — app);
#   2. копию docker-volume с клипами (`/app/media`) через `docker compose cp`;
#   3. сжатие (gzip) и удаление копий старше BACKUP_KEEP штук.
#
# Для cron (пример, ежедневно в 3:17):
#   17 3 * * * cd /srv/gluho-nemye && ./scripts/backup.sh >> /var/log/gluho-backup.log 2>&1
#
# Скопируйте каталог backup на другой хост университета: локальная копия не
# защищает от выхода из строя сервера (ТЗ 18.3).

set -euo pipefail

COMPOSE="${COMPOSE:-docker compose}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
DB_USER="${DB_USER:-app}"
DB_NAME="${DB_NAME:-app}"
MEDIA_SERVICE="${MEDIA_SERVICE:-web}"

timestamp="$(date +%Y%m%d-%H%M%S)"
target="${BACKUP_DIR}/${timestamp}"
mkdir -p "${target}"

echo "[backup] ${timestamp}: дамп базы ${DB_NAME}"
# -T: без TTY (нужно для cron). Дамп пишется на хост через stdout.
${COMPOSE} exec -T db pg_dump -U "${DB_USER}" "${DB_NAME}" \
	| gzip -9 > "${target}/db.sql.gz"

echo "[backup] копия каталога клипов"
# Клипы живут в volume /app/media; compose cp забирает их на хост.
${COMPOSE} cp "${MEDIA_SERVICE}:/app/media/." "${target}/media" || {
	echo "[backup] предупреждение: каталог media не скопирован" >&2
	mkdir -p "${target}/media"
}

# Контрольная сумма — чтобы можно было проверить целостность после переноса.
( cd "${target}" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS )

echo "[backup] чистка: оставляем последние ${BACKUP_KEEP} копий"
# shellcheck disable=SC2012 — каталоги называются по timestamp, сортировка по имени = по времени.
ls -1dt "${BACKUP_DIR}"/*/ 2>/dev/null | tail -n "+$((BACKUP_KEEP + 1))" | while read -r old; do
	echo "[backup] удаляю ${old}"
	rm -rf "${old}"
done

echo "[backup] готово: ${target}"
