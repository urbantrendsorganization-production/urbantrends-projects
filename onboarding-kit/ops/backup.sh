#!/usr/bin/env bash
# OnboardKit Postgres backup (CLAUDE.md §14).
# Dumps the database into the shared UrbanTrends backup dir and prunes old files.
# Install as a daily cron on the Hetzner box, e.g.:
#   0 3 * * *  /opt/onboardkit/ops/backup.sh >> /var/log/onboardkit-backup.log 2>&1
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/backups}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/onboardkit}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
DB_SERVICE="${DB_SERVICE:-postgres}"

# shellcheck disable=SC1091
[ -f "${COMPOSE_DIR}/.env" ] && set -a && . "${COMPOSE_DIR}/.env" && set +a

POSTGRES_USER="${POSTGRES_USER:-onboardkit}"
POSTGRES_DB="${POSTGRES_DB:-onboardkit}"

mkdir -p "${BACKUP_DIR}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/onboardkit-${STAMP}.sql.gz"

echo "[$(date -Is)] dumping ${POSTGRES_DB} -> ${OUT}"
docker compose -f "${COMPOSE_DIR}/docker-compose.prod.yml" exec -T "${DB_SERVICE}" \
	pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" | gzip > "${OUT}"

# Prune backups older than the retention window.
find "${BACKUP_DIR}" -name 'onboardkit-*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "[$(date -Is)] backup complete ($(du -h "${OUT}" | cut -f1))"
