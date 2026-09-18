# Production deployment: isolated Hostinger VPS

This application is the `activos` Compose project. It does not alter `n8n`,
`hermes`, or `tisico-prod`. Traefik remains the VPS's public TLS listener;
only this application's Nginx container joins its existing `n8n_default`
network. PostgreSQL and FastAPI are attached only to the private
`activos_app_internal` network and publish no host ports.

## One-time VPS preparation

1. Create a DNS `A` record for `activos.tisico-sa.com` pointing to the VPS
   public IP. Wait for authoritative DNS to resolve before requesting a
   certificate.
2. Confirm the existing Traefik configuration before touching this project:

   ```sh
   docker network inspect n8n_default >/dev/null
   docker ps --format '{{.Names}} {{.Image}}' | grep -i traefik
   ```

   Its Docker provider must have `exposedbydefault=false`; its web entrypoint
   must redirect to `websecure`; and `mytlschallenge` must be its configured
   ACME resolver. Do **not** create another proxy or bind ports 80/443.
3. Check out this application in its own directory. Create an operator-owned
   directory such as `/etc/asset-reconciliation/secrets` (mode `0700`) and
   three separate root-readable files (each mode `0600`):

   - `postgres_password`: a unique PostgreSQL password;
   - `database_url`: `postgresql://asset_app:<URL-encoded-password>@postgres:5432/asset_reconciliation`;
   - `session_secret`: a unique random value of at least 32 characters.

   Do not put those values in Git, shell history, a Compose file, n8n, or the
   environment file. Generate the session secret with
   `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
4. Create `/etc/asset-reconciliation/production.env`, mode `0600`, with
   non-secret settings and secret *paths* only:

   ```dotenv
   POSTGRES_DB=asset_reconciliation
   POSTGRES_USER=asset_app
   POSTGRES_PASSWORD_FILE=/etc/asset-reconciliation/secrets/postgres_password
   DATABASE_URL_FILE=/etc/asset-reconciliation/secrets/database_url
   SESSION_SECRET_FILE=/etc/asset-reconciliation/secrets/session_secret
   ```

   Keep the database URL password URL-encoded. The production override mounts
   these as Compose secrets, so FastAPI uses `DATABASE_URL_FILE` and
   `SESSION_SECRET_FILE` rather than direct secret environment values.

## Release sequence

Run all commands from the repository root. Set the command once so every
operation uses the same isolated project and production configuration:

```sh
export ENV_FILE=/etc/asset-reconciliation/production.env
export COMPOSE='docker compose --project-name activos --env-file /etc/asset-reconciliation/production.env -f docker-compose.yml -f docker-compose.production.yml'
$COMPOSE config --quiet
```

1. Build/pull the release and start only PostgreSQL:

   ```sh
   $COMPOSE build
   $COMPOSE up -d --wait postgres
   ```

2. Assign one release operator as migration owner. With no other release,
   backup, restore, or application writer running, execute the one-shot
   migration and wait for it to exit successfully:

   ```sh
   $COMPOSE --profile operations run --rm migrate
   ```

   The `backend` command never runs Alembic. A migration failure belongs to the
   release operator: leave the old web service stopped, inspect the failure,
   restore a known matched backup if necessary, and use the documented rollback
   below. Never retry concurrent migration containers. If this is a new
   database, create the initial administrator from a trusted interactive
   terminal before public use:

   ```sh
   $COMPOSE run --rm backend python -m app.cli create-initial-admin \
     --username admin --email admin@example.test --display-name "Initial Administrator"
   ```

   The command prompts for the password and refuses a second administrator; do
   not put it in an environment variable or automation.
3. Start the application and wait for private readiness:

   ```sh
   $COMPOSE up -d --wait backend nginx
   docker ps --filter label=com.docker.compose.project=activos
   ```

4. Smoke test through the public TLS route after DNS/ACME propagation:

   ```sh
   curl --fail --silent --show-error --proto '=https' https://activos.tisico-sa.com/api/health
   curl --fail --silent --show-error --proto '=https' https://activos.tisico-sa.com/api/ready
   ```

   `/api/health` is process liveness only. `/api/ready` returns `200`
   `{"status":"ok"}` only after bounded database connectivity, the bundled
   Alembic head revision, and a write/fsync/remove probe of evidence storage
   succeed. It returns only `503 {"status":"unavailable"}` on failure and
   intentionally reveals no dependency details.

## Rollback and incident ownership

A failed image/startup release is owned by the release operator: stop only this
project's application containers, select the previous image/configuration, and
start it after confirming its schema compatibility. Schema/data rollback is
owned by the database operator and must use a tested matched backup generation;
never infer it from an image rollback. Traefik/DNS/certificate failures are
owned by the VPS/network operator and must be corrected outside this Compose
project.

Do not use `docker compose down -v` in deployment, rollback, backup, or normal
maintenance. It destroys persistent state. `docker compose down` is also not a
normal release operation; use targeted `up`, `stop`, logs, and the restore
runbook.
