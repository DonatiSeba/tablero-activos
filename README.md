# Asset Reconciliation

A local foundation for an internal asset-reconciliation application. The current
scope provides a containerized API health check, a PostgreSQL-oriented
persistence schema, local authentication, and a React presentation shell.
Imports, matching, and dashboard behavior are intentionally deferred to later tasks.

## Architecture

- **PostgreSQL** is the system of record and is isolated on the Compose network.
- **FastAPI** provides the backend boundary. Its current `GET /health` endpoint
  confirms that the API process is ready.
- **React + Vite** build the presentation-only frontend as static files.
- **Nginx** serves the built frontend and proxies `/api/*` to FastAPI without
  rewriting its path. For example, `POST /api/auth/login` reaches FastAPI as
  `POST /api/auth/login`, and `GET /api/health` reaches the public health alias.

Only Nginx is published to the host at `http://localhost:8080` by default.
The database and backend remain internal to Docker Compose.

## Local configuration

1. Copy the sample configuration:

   ```sh
   cp .env.example .env
   ```

   On PowerShell, use `Copy-Item .env.example .env`.
2. Edit `.env` only if the local port or development database values conflict
   with your environment. The supplied values are non-secret local examples.
3. Never commit `.env` or use its sample password in a shared environment.

`APP_PORT` controls the host port. `POSTGRES_DB`, `POSTGRES_USER`, and
`POSTGRES_PASSWORD` configure the development database and are also used to
construct the backend's internal `DATABASE_URL`. `SESSION_SECRET` must be a
unique value of at least 32 characters in every deployment; generate one with
the command in `.env.example` and never reuse the sample value. Session cookies
are HttpOnly and SameSite=Lax. `APP_ENV=development` is only for local HTTP
workflows and deliberately makes the cookie non-Secure; every non-development
configuration sets the Secure flag, so production must be served over HTTPS.

## Initial administrator and local authentication

Run migrations before creating the first administrator. There is intentionally
no setup route and the service never creates an administrator on startup. From
a trusted interactive terminal, run:

```sh
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli create-initial-admin \
  --username admin --email admin@example.test --display-name "Initial Administrator"
```

The command requests and confirms the password through `getpass`; passwords are
never accepted as command-line arguments or environment variables. It refuses
to run if an ADMIN already exists and records the creation in the audit log.

`POST /api/auth/login` accepts a username and password, then issues a signed
server-side session cookie. `GET /api/auth/me` returns the active database user,
and `POST /api/auth/logout` revokes that session. Each authenticated request
checks both the unrevoked, unexpired database session and the active database
user. API code can apply the server-side `require_viewer`, `require_editor`, or
`require_admin` dependencies; denied role checks are audit logged. Passwords
are stored only as Argon2id hashes.

## Start and stop

Build and start the complete stack:

```sh
docker compose up --build --wait
```

Check the API through its public Nginx route:

```sh
curl http://localhost:8080/api/health
```

Expected response:

```json
{"status":"ok"}
```

Open `http://localhost:8080` for the frontend shell. Stop the stack with:

```sh
docker compose down
```

Use `docker compose down -v` only when you intentionally want to delete local
PostgreSQL data.

## Development checks

Install backend test dependencies in an isolated Python environment, then run:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements-test.txt
python -m pytest backend/tests
```

On PowerShell, activate with `.venv\\Scripts\\Activate.ps1`. Remove `.venv`
afterward if it was created only for verification. `backend/requirements.txt`
contains only production dependencies installed by the backend runtime image.
Its Python-version markers retain the pinned PostgreSQL runtime dependency for
the Python 3.13 Docker image while selecting a compatible binary `psycopg`
wheel for newer host Python test environments. `backend/requirements-test.txt`
includes those requirements plus test-only packages.

Apply the persistence schema with Alembic after setting `DATABASE_URL`:

```sh
python -m alembic -c backend/alembic.ini upgrade head
```

The initial migration creates the users, cost centers, assets and aliases,
immutable import-batch evidence, observations, reconciliation results, and
audit-log tables. It uses PostgreSQL UUID, JSONB, INET, and enum types while
retaining SQLite compatibility for isolated migration tests.

Import batches record a required cost center, report date, and final
`completed` or `rejected` status at insertion time. Observations retain their
source-provided `reported_status` and positive decimal quantity in addition to
`original_data`; those raw values are not normalized by this persistence layer.
Database triggers reject direct `UPDATE` and `DELETE` statements against both
import batches and observations (PostgreSQL and SQLite), preserving import
evidence independently of application policy.

Install frontend dependencies and produce the static production build:

```sh
npm --prefix frontend ci
npm --prefix frontend run build
```

Validate the resolved Compose configuration before startup:

```sh
docker compose config
```

## Container build notes

The Nginx image uses the multi-stage `frontend/Dockerfile`: Node builds the
Vite application, then only the generated static files and Nginx configuration
are included in the runtime image. Nginx routes browser requests to the React
single-page application and forwards `/api/` requests to the internal
`backend` service. No frontend code implements domain logic or accesses
PostgreSQL directly.
