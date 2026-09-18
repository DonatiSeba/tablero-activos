# Asset Reconciliation

A local foundation for an internal asset-reconciliation application. The current
scope provides a containerized API health check, a PostgreSQL-oriented
persistence schema, local authentication, and a React presentation shell.
CC190-style system-report and physical-audit imports are available to authenticated editors and administrators; dashboard behavior remains deferred.

## Architecture

- **PostgreSQL** is the system of record and is isolated on the Compose network.
- **FastAPI** provides the backend boundary. Its current `GET /health` endpoint
  confirms that the API process is ready.
- **React + Vite** build the presentation-only frontend as static files.
- **Nginx** serves the built frontend and proxies `/api/*` to FastAPI without
  rewriting its path. For example, `POST /api/auth/login` reaches FastAPI as
  `POST /api/auth/login`, and `GET /api/health` reaches the public health alias.
  Its exact `/api/imports/system` and `/api/imports/audit` routes stream request
  bodies without an Nginx size cap so the application can enforce its configured
  limit and record the sanitized oversized-upload audit before multipart parsing.

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

`IMPORT_STORAGE_PATH` is the backend container path for immutable uploaded
system-report and physical-audit originals. Compose mounts the named `import_data` volume at the
configured path (default `/data/imports`); retain that volume in backups alongside PostgreSQL. For a
non-Compose local backend, set `IMPORT_STORAGE_PATH` to a private writable
directory outside the repository. Files are written once as
`<sha-prefix>/<sha256>.xlsx`, never from the submitted filename, and should not
be edited or removed while their import-batch evidence is retained. Publication
uses a private fsynced temporary file and an atomic no-replace link; an existing
digest path is hash-verified before it is reused.

`IMPORT_MAX_UPLOAD_BYTES` limits each workbook upload to 25 MiB by default and
`IMPORT_MAX_XLSX_UNCOMPRESSED_BYTES` limits the XLSX archive's declared expanded
content to 100 MiB by default. Both values are positive byte counts. Uploads are
read in bounded chunks and are not saved to evidence storage until they pass
validation; rejected uploads leave no retained evidence file. The import route
also rejects an oversized declared or streamed multipart body with HTTP 413
before FastAPI's multipart parser runs.

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

## System-report import API

`POST /api/imports/system` is an editor/admin-only multipart endpoint. Submit a
`.xlsx` `file` and a `report_date` formatted as `YYYY-MM-DD`. It requires the
named columns `Rubro`, `Categoría`, `Producto`, `Cód. Ident.`, `Identificación`,
`Nro. CC`, `Centro de Costo`, and `Estado`; it rejects unreadable reports,
blank or mixed cost-center codes, empty reports, and a duplicate SHA-256 file.

Accepted reports retain the original file and every nonblank source row as
immutable evidence. Each row stores ordered cells with their one-based column,
raw header, and raw value, so blank or duplicate headers cannot overwrite
source evidence. Assets are associated only by an exact original `Cód.
Ident.` value; normalized codes, descriptions, and `Identificación` are never
used as import matching keys. If a report observes more than one cost-center
name for its code, or differs from an already stored name, the response returns
an explicit warning while the historical cost-center name is left unchanged.
Rejected and accepted authorized attempts are audit logged without file bytes
or row values.

Example after authenticating with the session cookie:

```sh
curl -X POST http://localhost:8080/api/imports/system \
  -b cookies.txt \
  -F file=@report.xlsx \
  -F report_date=2026-09-17
```

## Physical-audit import API

`POST /api/imports/audit` is an editor/admin-only multipart endpoint. Submit a
`.xlsx` `file`, an explicit `report_date` (`YYYY-MM-DD`), and an explicit
existing `cost_center_code`; neither value is inferred from the workbook.

Only physical-audit sheets are imported. Row 3 must contain each exact A:K
header once: `CANTIDAD`, `IDENTIFICACION`, `MAQUINA/EQUIPO`, `MARCA`, `MODELO `,
`FUNCIONAMIENTO`, `ESTADO EXTERNO`, `OBSERVACIONES`, `EXISTENCIA EN BRIDGE`,
`CC FISICO`, and `CC  BG`. Other embedded Bridge/system sheets are reference
only. Every nonblank row retains its sheet name, source row, ordered cells, and
positive integer quantity exactly as evidence. Notes and source values are not
included in errors, audit logs, or the response.

Each imported row creates exactly one derived reconciliation case, regardless of
quantity. A nonblank `IDENTIFICACION` matches an existing asset by exact
`original_code` first; only if that has no candidate does NFKC-uppercase,
whitespace-free `normalized_code` matching apply, and only if it has exactly
one candidate. ASCII hyphens remain significant. Blank, absent-normalized, and
ambiguous identifiers retain an unresolved case; imports never create assets or
aliases from audit inputs. Cases are separate from `ReconciliationResult`, so
unresolved evidence never fabricates an asset identity. The response exposes
only aggregate match counts and warnings.

The workbook's blank-header column L is retained as positional raw evidence (`column: 12`). Exact raw `VOLVI�`, `DEVOLVIO`, and `DEVOLVI�` markers have the user-authorized interpretation of a return **after** that audit snapshot (the supplied workbook stores the accented variants as `VOLVIÓ` and `DEVOLVIÓ`; both spellings are recognized without changing raw evidence). After every accepted audit import, a transactionally rebuilt `audit_l_return_v1` projection creates one current state per resolved asset and cost center: recognized markers produce `returned`; unmarked/unknown L values produce `found`; and `VOLVI� 4` (and workbook raw `VOLVIÓ 4`) produces `review_required` with its raw marker and source observation provenance. Review-required projections are not found, returned, or accounted buckets, and no immutable evidence is changed. Unresolved identifiers never project a state. Across report dates the later date wins. On the same report date, recognized return dominates ambiguous marker, which dominates ordinary unmarked presence; this is the authorized marker interpretation, not measured event time. A stable observation identifier only chooses provenance among otherwise equal rows, never event time. No return import, return observation, destination, or receipt timestamp is fabricated.

Authenticated viewers (and therefore editors/administrators) can read `GET /api/current-states` with an optional `cost_center_code`. It returns the derived state, reason, projection version, raw L marker copy, and source audit observation ID, but not the full source row.

Example after authenticating with the session cookie:

```sh
curl -X POST http://localhost:8080/api/imports/audit \
  -b cookies.txt \
  -F file=@physical-audit.xlsx \
  -F report_date=2026-06-27 \
  -F cost_center_code=190
```

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

The migrations create the users, cost centers, assets and aliases, immutable
import-batch evidence, observations, derived audit reconciliation cases, derived audit current-state projections,
reconciliation results, and audit-log tables. It uses PostgreSQL UUID, JSONB, INET, and enum types while
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
