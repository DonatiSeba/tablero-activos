#!/usr/bin/env bash
# Restore a matched backup generation only after explicit operator confirmation.
# Default mode validates inputs and prints the destructive plan without changing services or data.
set -euo pipefail
umask 077

ENV_FILE=${ENV_FILE:-/etc/asset-reconciliation/production.env}
GENERATION=${1:?usage: ENV_FILE=/etc/asset-reconciliation/production.env ops/restore-release.sh /secure/backup-root/generation [--apply]}
MODE=${2:---dry-run}
PROJECT=${COMPOSE_PROJECT_NAME:-activos}
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.production.yml)
if [[ ${RESTORE_REHEARSAL:-0} == "1" ]]; then
  PROJECT=${COMPOSE_PROJECT_NAME:-activos-restore-rehearsal}
  COMPOSE_FILES+=(-f docker-compose.restore-rehearsal.yml)
fi
COMPOSE=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}")

[[ -r "$ENV_FILE" && -d "$GENERATION" ]] || { echo "environment file or backup generation is unavailable" >&2; exit 2; }
[[ -f "$GENERATION/database.dump" && -f "$GENERATION/evidence.tar.gz" && -f "$GENERATION/SHA256SUMS" ]] || { echo "backup generation is incomplete" >&2; exit 2; }
(
  cd "$GENERATION"
  sha256sum -c SHA256SUMS
)

if [[ "$MODE" != "--apply" ]]; then
  echo "Dry run passed. --apply would replace only the selected project's database and evidence volume, then verify every completed import hash before starting application services."
  exit 0
fi
[[ ${CONFIRM_RESTORE:-} == "RESTORE" ]] || { echo "set CONFIRM_RESTORE=RESTORE for an applied restore" >&2; exit 2; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
exec 9>"$(dirname "$GENERATION")/.backup.lock"
flock -n 9 || { echo "another backup or restore owns the backup lock" >&2; exit 2; }

# This is the deliberate destructive boundary. Keep web/API writers stopped until
# both data halves and the verification below have succeeded.
"${COMPOSE[@]}" stop nginx backend
"${COMPOSE[@]}" up -d --wait postgres
"${COMPOSE[@]}" exec -T postgres pg_restore -U "${POSTGRES_USER:?POSTGRES_USER must be set}" --clean --if-exists -d "${POSTGRES_DB:?POSTGRES_DB must be set}" <"$GENERATION/database.dump"
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint sh backend -c 'find "$IMPORT_STORAGE_PATH" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar -xzf - -C "$IMPORT_STORAGE_PATH"' <"$GENERATION/evidence.tar.gz"

VERIFY_CODE='
import hashlib
from pathlib import Path
from sqlalchemy import select
from app.db import _session_factory
from app.models import ImportBatch, ImportBatchStatus
from app.system_imports import import_storage_path
root = import_storage_path().resolve()
bad = []
with _session_factory()() as session:
    batches = session.execute(select(ImportBatch.sha256, ImportBatch.storage_path).where(ImportBatch.status == ImportBatchStatus.COMPLETED)).all()
for digest, stored_path in batches:
    candidate = (root / (stored_path or "")).resolve()
    if root not in candidate.parents or not candidate.is_file():
        bad.append(digest)
        continue
    hasher = hashlib.sha256()
    with candidate.open("rb") as evidence:
        for chunk in iter(lambda: evidence.read(1024 * 1024), b""):
            hasher.update(chunk)
    if hasher.hexdigest() != digest:
        bad.append(digest)
raise SystemExit("evidence verification failed for %d completed imports" % len(bad) if bad else 0)
'
"${COMPOSE[@]}" run --rm --no-deps --entrypoint python backend -c "$VERIFY_CODE"
"${COMPOSE[@]}" up -d --wait backend nginx
echo "restore and completed-import evidence verification succeeded"
