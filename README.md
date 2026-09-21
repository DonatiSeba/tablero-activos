# Asset Reconciliation

A local foundation for an internal asset-reconciliation application. The current
scope provides a containerized API health check, a PostgreSQL-oriented
persistence schema, local authentication, and a React presentation shell.
CC190-style system-report and physical-audit imports are available to authenticated editors and administrators; authenticated users can view server-calculated dashboard and operational read contracts.

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

## Dashboard and operational read API

All of the following read-only endpoints require an authenticated `VIEWER`,
`EDITOR`, or `ADMIN` session. They are server-calculated presentation contracts:
the browser must not recalculate matching, reconciliation, or KPIs from source
records. Responses never contain workbook bytes, storage paths, SHA-256 values,
source-row JSON, raw notes, session data, or audit-log data.

- `GET /api/dashboard/summaries?cost_center_code=&limit=100&offset=0` returns
  bounded per-cost-center summaries. For each source it selects a completed batch
  by greatest `report_date`, then greatest batch UUID solely as a deterministic
  selection tie-breaker (not as chronology). `latest_sources` reports each
  independently selected batch ID and date. `freshness.warning` is true whenever
  either source is unavailable or dates differ; differing dates explicitly do
  not represent one shared cutoff.
- Summary `metrics.current_system_distinct_asset_count` is the distinct non-null
  asset IDs in the selected system batch. `found_count`, `returned_count`, and
  `review_required_count` are distinct assets in that system scope with an audit
  current-state projection whose provenance is the selected audit batch.
  `unresolved_audit_case_count` is the unresolved reconciliation-case count in
  that selected audit batch. `not_in_management_system_for_cost_center_count`
  combines each distinct matched audit asset absent from the selected system
  snapshot with each unmatched reconciliation case from the selected audit
  batch. It uses only the selected system snapshot as its membership reference
  and remains `null` unless both source snapshots are available.
  `pending_not_accounted_count` is current-system assets not found or returned;
  review-required assets remain pending/not accounted. Metrics needing
  unavailable system or audit evidence are `null`.
- `GET /api/dashboard/system-drilldown?cost_center_code=190&limit=100&offset=0`
  returns the selected system snapshot grouped as `Rubro → Categoría → Producto`,
  with server-owned observation, distinct-asset, and reported-status counts.
  Pagination is over deterministic leaf product groups ordered by rubro, category,
  then product (case-insensitive, with missing labels first); parent groups contain
  only leaves from the requested page. `limit` is 1–100 and `offset` is bounded at
  10,000. `page` gives `has_more` and the total leaf-group count. It returns a
  stable, safe empty `groups` list and zero-count page when no system evidence
  exists.
- `GET /api/dashboard/rubro-reconciliation-chart?cost_center_code=190&rubro=&category=&product_limit=50&product_offset=0`
  returns complete, unpaginated category bars for one rubro and a bounded product
  chart for one selected category from the selected system snapshot.
  `cost_center_code` is required. Omitting `rubro` or `category` selects the
  first option in deterministic null-first, case-insensitive, raw-value
  tie-break order; explicit `rubro=` or `category=` selects the corresponding
  null/unassigned value, and any other value matches exactly after URL decoding.
  `rubro_options`/`selected_rubro` and `category_options`/`selected_category`
  preserve null values while providing `Sin rubro asignado` and
  `Sin categoría asignada` labels. `product_chart` uses the same three
  reconciliation series and preserves null products with `Sin producto asignado`.
  It filters by rubro and category before grouping distinct system assets, then
  paginates product groups with a server-owned `page` (`product_limit` defaults
  to 50, is 1–100, and `product_offset` is bounded at 10,000). Product metrics
  remain null when audit evidence is unavailable. Unmatched audit evidence is
  not assigned to this hierarchy because it has no trustworthy rubro/category/
  product source label. Both charts expose localizable source/rubro reasons such
  as `cost_center_not_found`, `missing_system_evidence`,
  `missing_audit_evidence`, `invalid_rubro_selection`, or `empty_rubro`.
  `invalid_category_selection` applies only to `product_chart`; the already-valid
  complete category chart remains available. Source/audit batch metadata and
  freshness remain server-calculated.
- `GET /api/operations/import-history?source=&cost_center_code=&status=&limit=50&offset=0`
  returns safe batch metadata and sanitized warning/processing counts. Ordering
  is `imported_at` descending then batch UUID descending. `limit` is 1–100 and
  `offset` is bounded at 10,000; `page` gives `has_more` and `total_count`.
- `GET /api/operations/review-queue?cost_center_code=&category=&limit=50&offset=0`
  returns paginated unresolved identifier cases and `review_required_return`
  audit-current projections. `queue_counts` is server-calculated. Return-review
  items state that column-L RETURNED is an authorized post-audit inference, not
  a warehouse receipt. This work unit intentionally exposes no resolution
  command.

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

Open `http://localhost:8080` for the frontend session, dashboard, operations, current-state, and editor-upload views. Stop the stack with:

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
npm --prefix frontend test
npm --prefix frontend run build
```

Validate the resolved Compose configuration before startup:

```sh
docker compose config
```

## Production operations

Production deployment is intentionally separate from local Compose. Use
`docker-compose.production.yml` only with the documented production environment
file and existing Traefik network; it adds no Nginx host port and keeps FastAPI
and PostgreSQL private. The one-shot migration service is run by the release
operator before web startup, while `/health` remains liveness and `/ready`
checks database schema and evidence storage readiness.

- [Hostinger VPS deployment and rollback](docs/production-deployment.md)
- [Matched PostgreSQL/evidence backup, restore, and verification](docs/backup-restore.md)
- [n8n/SharePoint external automation handoff](docs/n8n-sharepoint-handoff.md)

## Container build notes

The Nginx image uses the multi-stage `frontend/Dockerfile`: Node builds the
Vite application, then only the generated static files and Nginx configuration
are included in the runtime image. Nginx routes browser requests to the React
single-page application and forwards `/api/` requests to the internal
`backend` service. No frontend code implements domain logic or accesses
PostgreSQL directly.
