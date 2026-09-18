#!/usr/bin/env bash
# Create one matched PostgreSQL + immutable-evidence backup generation.
# This script never deletes a volume, database, or prior backup.
set -euo pipefail
umask 077

ENV_FILE=${ENV_FILE:-/etc/asset-reconciliation/production.env}
BACKUP_ROOT=${1:?usage: ENV_FILE=/etc/asset-reconciliation/production.env ops/backup-release.sh /secure/backup-root}
PROJECT=${COMPOSE_PROJECT_NAME:-activos}
COMPOSE=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.production.yml)

[[ -r "$ENV_FILE" ]] || { echo "production environment file is not readable" >&2; exit 2; }
# The file contains deployment parameters and secret-file paths, never secret values.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
mkdir -p "$BACKUP_ROOT"
exec 9>"$BACKUP_ROOT/.backup.lock"
flock -n 9 || { echo "another backup or restore owns the backup lock" >&2; exit 2; }

generation="$BACKUP_ROOT/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir "$generation"

# Stop the only API writer before either half is captured. A failed backup leaves
# it stopped deliberately, so an operator must inspect the failure before resume.
"${COMPOSE[@]}" stop backend
"${COMPOSE[@]}" exec -T postgres pg_dump -U "${POSTGRES_USER:?POSTGRES_USER must be exported or present in ENV_FILE}" -Fc "${POSTGRES_DB:?POSTGRES_DB must be exported or present in ENV_FILE}" >"$generation/database.dump"
"${COMPOSE[@]}" run --rm --no-deps --entrypoint tar backend -C /data/imports -czf - . >"$generation/evidence.tar.gz"
(
  cd "$generation"
  sha256sum database.dump evidence.tar.gz > SHA256SUMS
  printf 'created_utc=%s\ncompose_project=%s\n' "$(date -u +%FT%TZ)" "$PROJECT" > manifest.env
)

"${COMPOSE[@]}" up -d backend
echo "backup generation complete: $generation"
