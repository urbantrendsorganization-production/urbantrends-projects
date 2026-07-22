#!/usr/bin/env bash
# OnboardKit backup (CLAUDE.md §14).
# Dumps Postgres AND the self-hosted MinIO object store (KYC documents) into the
# shared UrbanTrends backup dir, then prunes old files. Install as a daily cron
# on the Hetzner box, e.g.:
#   0 3 * * *  /opt/onboardkit/ops/backup.sh >> /var/log/onboardkit-backup.log 2>&1
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/backups}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/onboardkit}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
DB_SERVICE="${DB_SERVICE:-postgres}"
# Docker volume holding MinIO's data. Compose project is `onboardkit`, so the
# volume `minio-data` is created as `onboardkit_minio-data`.
MINIO_VOLUME="${MINIO_VOLUME:-onboardkit_minio-data}"

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

# Object storage: tar the MinIO data volume (KYC documents). Objects are
# immutable files, so a hot tar is crash-consistent enough for this stack; a
# throwaway alpine container mounts the volume read-only and streams the archive.
# Restore into a fresh volume with:
#   docker run --rm -v onboardkit_minio-data:/data -v /opt/backups:/backup alpine \
#     sh -c 'cd /data && tar xzf /backup/onboardkit-minio-<STAMP>.tar.gz'
MINIO_OUT="${BACKUP_DIR}/onboardkit-minio-${STAMP}.tar.gz"
if docker volume inspect "${MINIO_VOLUME}" >/dev/null 2>&1; then
	echo "[$(date -Is)] archiving MinIO volume ${MINIO_VOLUME} -> ${MINIO_OUT}"
	docker run --rm \
		-v "${MINIO_VOLUME}:/data:ro" \
		-v "${BACKUP_DIR}:/backup" \
		alpine tar czf "/backup/onboardkit-minio-${STAMP}.tar.gz" -C /data .
	echo "[$(date -Is)] MinIO archive complete ($(du -h "${MINIO_OUT}" | cut -f1))"
else
	echo "[$(date -Is)] WARNING: MinIO volume ${MINIO_VOLUME} not found — skipping object backup"
fi

# Prune backups older than the retention window (both Postgres dumps and MinIO
# archives).
find "${BACKUP_DIR}" -name 'onboardkit-*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete
find "${BACKUP_DIR}" -name 'onboardkit-minio-*.tar.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "[$(date -Is)] backup complete (db $(du -h "${OUT}" | cut -f1))"
