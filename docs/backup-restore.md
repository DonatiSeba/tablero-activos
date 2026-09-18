# Backup and restore operations

Run backup and restore from the repository root with the production environment file. Backup generations contain a PostgreSQL custom dump, immutable evidence archive, and checksums.

```sh
ENV_FILE=/etc/asset-reconciliation/production.env ops/backup-release.sh /secure/asset-backups
```

`restore-release.sh` defaults to dry-run. An applied restore requires both `--apply` and `CONFIRM_RESTORE=RESTORE`. It verifies every completed import's stored SHA-256 evidence before starting backend or Nginx.

## Isolated restore rehearsal

Use a disposable Compose project and volumes; it never joins `n8n_default`, exposes Traefik labels, or changes production volumes:

```sh
RESTORE_REHEARSAL=1 \
COMPOSE_PROJECT_NAME=activos-restore-rehearsal \
CONFIRM_RESTORE=RESTORE \
ENV_FILE=/etc/asset-reconciliation/production.env \
ops/restore-release.sh /secure/asset-backups/<generation> --apply
```

After verification, inspect the rehearsal only on its private network and remove its isolated containers/volumes deliberately when the rehearsal is complete. Never use `down -v` against the production `activos` project.
