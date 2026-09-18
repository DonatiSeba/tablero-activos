# Asset Reconciliation MVP

## Objective
Deliver a maintainable, containerized internal web application that imports asset evidence, preserves immutable historical snapshots, reconciles assets by cost center, and exposes an executive dashboard with operational drill-down.

## Problem
System, physical-audit, and warehouse-return reports are independent and may disagree. The application must turn their evidence into traceable, reviewable reconciliation results without treating Excel files as the system of record.

## Scope
- FastAPI + PostgreSQL backend, React + Vite frontend, Nginx, and Docker Compose.
- Immutable import batches and normalized asset observations.
- System, audit, and return parsers behind a shared internal contract.
- Deterministic matching before manual review; originals preserved alongside normalized values.
- Role-protected local authentication and auditable manual actions.
- Grouped dashboard and per-asset drill-down.

## Constraints
- The backend and PostgreSQL own every business rule; the frontend is presentation only.
- Imports are snapshots and must never overwrite historical data.
- Exact codes and normalized codes are distinct; ambiguous matches require human confirmation.
- The initial system report for CC 190 has 637 unique `Cód. Ident.` values and two observed cost-center names for code `190`.
- User-facing product UI and all technical artifacts default to English unless the product language is explicitly revised.
- No external SharePoint, Hermes, n8n, or Microsoft Entra dependency is required for the MVP.

## Delivery strategy
- Forecast: above 400 authored lines across the feature.
- Strategy: ask-on-risk; no PR, push, merge, or commit without explicit user authorization.
- Branch: `feat/asset-reconciliation-mvp`.

## TDD and checks
- Mode: disabled (no existing project test configuration).
- Source: new repository baseline.
- Runner: to be established by the backend and frontend foundation task.
- Every implementation task runs its focused functional checks and records observed evidence.

## Tasks

- [x] AR-00 Resolve the Pi worktree association.
  - Outcome: the Pi session is opened at this repository's Git root so bounded workers can operate in `tablero-activos/`.
  - Checks: `git status` and branch inspection ran at the nested repository root; the bounded worker capability is available.
  - Evidence: completed 2026-09-17 — current working directory resolves to the `feat/asset-reconciliation-mvp` worktree.

- [x] AR-01 Establish the containerized application foundation.
  - Outcome: Docker Compose defines PostgreSQL, FastAPI, and Nginx serving a React/Vite shell; FastAPI exposes `GET /health`, and Nginx proxies `/api/*`.
  - Scope: root infrastructure, backend bootstrap, frontend bootstrap, and deployment documentation only.
  - Checks: `python -m pytest backend/tests` passed (1 test; 3 Python 3.14 dependency deprecation warnings); `npm --prefix frontend run build` passed; `git diff --check` passed. Independent verification passed after a `.dockerignore` and dependency-separation correction. Docker Compose configuration/startup/image-build checks could not run because the Docker CLI is absent.
  - Evidence: completed 2026-09-17. Added configuration, Compose, FastAPI health test, React shell, Nginx proxy, production/test dependency separation, Docker context exclusions, and local documentation. No work-unit commit was created because the user has not authorized commits.

- [x] AR-02 Define the core persistence model and migrations.
  - Outcome: SQLAlchemy models and initial Alembic migration create users, cost centers, assets, aliases, import batches, observations, reconciliation results, and audit logs with PostgreSQL/SQLite-compatible integrity constraints.
  - Checks: `python -m pytest backend/tests` passed (6 tests; 3 Python 3.14 dependency deprecation warnings); clean SQLite Alembic upgrade/downgrade passed; PostgreSQL offline Alembic SQL generation passed; `npm --prefix frontend run build` passed. Independent verification passed. Docker Compose and live PostgreSQL validation could not run because Docker is absent.
  - Evidence: completed 2026-09-17. Models preserve original/normalized evidence, enforce SHA-256 uniqueness and reconciliation coverage, and database triggers reject direct updates/deletes of import batches and observations. Enum serialization is tested against migration values. No work-unit commit was created because the user has not authorized commits.

- [x] AR-03 Import and validate system-report snapshots.
  - Outcome: authenticated editors and administrators can import CC 190-style system reports. The service preserves lossless positional raw evidence, stores original files at SHA-256-derived immutable paths, rejects duplicates, validates columns and resource limits before multipart parsing, associates assets only by exact original code, and reports divergent CC names without changing historical evidence.
  - Checks: 29 backend tests passed in a fresh Python 3.14 environment; PostgreSQL offline Alembic SQL reached `20260919_0003`; frontend production build passed; `git diff --check` passed. Final independent verification passed. Docker Compose, live Nginx proxy behavior, and live PostgreSQL migration/import remain blocked because Docker is unavailable.
  - Evidence: completed and committed 2026-09-18 as `c9128b7` (`feat: import immutable system snapshots`).

- [x] AR-04 Add audit evidence and deterministic matching.
  - Outcome: authenticated editors and administrators can import validated physical-audit sheets as immutable observations and one derived reconciliation case per source row. Matching is exact `Asset.original_code`, then unique NFKC-uppercase-whitespace-free `Asset.normalized_code`; unmatched evidence retains a reason and never creates identities.
  - Checks: 43 backend tests passed in a fresh Python 3.14 environment; parser/layout (including blank-tail skipping and nonblank invalid-quantity rejection), matching, authorization, duplicate, body-limit, migration, and immutability coverage passed. PostgreSQL offline Alembic SQL reached `20260920_0004`; frontend production build and `git diff --check` passed. Final independent verification passed. Docker Compose, live Nginx proxy behavior, and live PostgreSQL migration/import remain blocked because Docker is unavailable.
  - Evidence: completed and committed 2026-09-20 as `e2ec7c7` (`feat: import audit evidence and reconcile deterministically`).

- [x] AR-05 Add return events and temporal reconciliation.
  - Outcome: immutable audit column-L evidence is interpreted in a separate, reproducible current-state projection without creating return observations; resolved assets have one found, returned, or review-required classification per cost center.
  - Checks: 61 backend tests passed in a fresh Python 3.14 environment; marker interpretation, raw preservation, date/rank dominance (recognized return > ambiguous > unmarked on the same report date), repeated-row idempotence, unresolved exclusion, projection constraints, audit-import integration, migrations, and API authorization coverage passed. PostgreSQL offline Alembic SQL reached `20260921_0005`; frontend build and `git diff --check` passed. Docker Compose, live Nginx, and live PostgreSQL verification remain unavailable because Docker is absent.
  - Evidence: the user accepted the documented Docker verification gap; completed and committed 2026-09-21 as `95ecde0` (`feat: derive audit return states`).

- [x] AR-06 Implement local authentication, authorization, and audit logging.
  - Outcome: Argon2id-backed local users and database-validated signed cookie sessions enforce VIEWER, EDITOR, and ADMIN permissions in the API. `POST /api/auth/login`, `POST /api/auth/logout`, and `GET /api/auth/me` are available through Nginx; an explicit interactive CLI creates the first administrator.
  - Checks: fresh isolated Python 3.14 dependency installation and backend tests passed (17 tests; 27 FastAPI/Starlette dependency deprecation warnings); PostgreSQL offline Alembic SQL passed; frontend production build passed; independent security verification passed. Docker Compose and live PostgreSQL/Nginx checks could not run because Docker is absent.
  - Evidence: completed 2026-09-17. The service fails fast on invalid session configuration; Secure/HttpOnly/SameSite=Lax cookie behavior, dummy Argon2 verification, server-side role checks, isolated denial audit records, logout revocation, and active-user revalidation are covered. No work-unit commit was created because the user has not authorized commits.

- [x] AR-07 Deliver the executive and operational frontend.
  - Delivery split: AR-07A backend read contracts, then AR-07B presentation-only React views. Each is independently verified and committed only with explicit user authorization.
  - [x] AR-07A Add dashboard and operational read contracts.
    - Outcome: viewer-authorized server APIs provide latest-per-source CC summaries, explicit source freshness, a bounded category/product drill-down, import history, and review queues without exposing raw evidence or assigning business logic to the browser.
    - Checks: 64 backend tests passed in a fresh Python 3.14 environment; high-cardinality leaf-page and pagination-boundary coverage passed. PostgreSQL offline SQL, frontend build, and whitespace check passed. Docker Compose configuration could not run because Docker is unavailable.
    - Evidence: completed and committed 2026-09-21 as `0fec962` (`feat: add dashboard read contracts`).
  - [x] AR-07B Deliver React executive and operational views.
    - Outcome: directors view server-calculated KPIs, freshness, grouped drill-down, import history, and queues; editors use authorized import controls. The browser presents server data and never calculates reconciliation/matching/business states.
    - Checks: frontend component tests; production build; API-contract checks; responsive smoke test.
    - Evidence: completed 2026-09-21. Vitest/RTL covers session, role affordances, freshness, error state, and multipart upload behavior; frontend build and 64 backend regression tests passed.

- [ ] AR-08 Prepare operational deployment and automation handoff.
  - Outcome: production configuration, backups, health checks, import endpoint documentation, and SharePoint/n8n integration contract are ready without coupling the MVP to automation.
  - Checks: Compose production configuration review; documented restore rehearsal; endpoint contract review.
  - Evidence: pending.

## Progress
- 2026-09-17: Repository branch created and existing system report profiled. No application code exists yet.
- 2026-09-17: AR-01 delegation was blocked before launch because this Pi session is not associated with the nested Git worktree. No worker ran and no application files were created.
- 2026-09-17: The session resumed at the nested Git worktree. AR-00 is complete and AR-01 is delegated to the bounded foundation worker.
- 2026-09-17: AR-01 completed and independently verified. Docker runtime validation remains pending on a Docker-enabled host; no implementation defect was found by static review.
- 2026-09-17: AR-02 completed and independently verified after correcting missing domain fields, database-level evidence immutability, enum/migration parity, and migration round-trip coverage. Docker and live PostgreSQL checks remain pending on a Docker-enabled host.
- 2026-09-17: For AR-06, the user selected an explicit initialization command for the first administrator rather than environment bootstrap or a web first-install route.
- 2026-09-17: AR-06 completed and independently verified after correcting Nginx API forwarding, startup secret validation, isolated authorization-denial auditing, account-enumeration timing defense, and Python 3.14 test dependency compatibility.
- 2026-09-17: Four verified tasks remain uncommitted. Before AR-03 adds another application area, delivery strategy requires explicit user direction to limit reviewer workload.
- 2026-09-17: The user authorized one foundation commit instead of risky historical reconstruction. Commit `2978cd1` (`feat: establish asset reconciliation foundation`) contains AR-01, AR-02, and AR-06 plus ODD tracking.
- 2026-09-17: AR-03 implementation and correction checks reached 28 backend tests, PostgreSQL offline SQL generation, and frontend build. The final independent re-verification is still pending after the pre-parser oversized-import audit correction. Work paused at the user's request; no AR-03 commit was created.
- 2026-09-17: AR-03 final independent verification passed with 29 backend tests, PostgreSQL offline SQL through `20260919_0003`, frontend build, and whitespace check. A dedicated Nginx import route now delegates request-size enforcement and rejection auditing to the ASGI layer. Docker/live PostgreSQL/Nginx validation remains pending because Docker is unavailable.
- 2026-09-18: The user authorized the AR-03 work-unit commit. Commit `c9128b7` (`feat: import immutable system snapshots`) contains the verified importer, its migration, proxy configuration, docs, tests, and ODD tracking.
- 2026-09-18: AR-04 mapping found no audit workbook or concrete audit column contract in the repository. The parser cannot be safely invented. The existing normalization also removes whitespace but preserves hyphens, while the project examples imply hyphen-insensitive matching; resolve this when approving the audit contract. Existing `ReconciliationResult` cannot represent unresolved observations because `asset_id` is non-null, so unmatched/ambiguous reasons need a derived storage design rather than mutation of immutable source evidence.
- 2026-09-18: A representative audit workbook was supplied and profiled read-only. Its five physical-audit sheets share an exact row-3, 11-column layout; its embedded Bridge sheets are not audit evidence and must be skipped. The workbook has no reliable date or row-level CC, so `report_date` and `cost_center_code` must be explicit API fields. `IDENTIFICACION` is optional, frequently unmatched, and must use exact-then-unique-whitespace-normalized matching only; hyphens stay significant.
- 2026-09-20: AR-04 implemented a separate per-audit-observation `ReconciliationCase` with nullable candidate asset and mutually exclusive matched strategy or unresolved reason. Source batches and observations remain trigger-immutable; audit rows keep their positional cells, sheet, row, and quantity without derived reasons. Full API verification remains pending because the current Python environment lacks `argon2-cffi` and a temporary dependency environment cannot be removed under this worker's deletion restriction.
- 2026-09-20: AR-04 final independent verification passed after correcting the invalid-quantity fixture to distinguish a nonblank missing-quantity row from a fully blank tail row. A fresh environment passed all 43 backend tests; PostgreSQL offline SQL reached `20260920_0004`; frontend build and whitespace checks passed. Docker/live PostgreSQL/Nginx checks remain unavailable because Docker is absent.
- 2026-09-20: The user authorized the AR-04 work-unit commit. Commit `e2ec7c7` (`feat: import audit evidence and reconcile deterministically`) contains the verified audit importer, derived reconciliation cases, migration, proxy configuration, docs, tests, and ODD tracking.
- 2026-09-20: AR-05 mapping found no return/warehouse workbook or source-column contract. The current application has `RETURN`/`RETURNED` enum placeholders but no chronology projection. A same-day audit and return with date-only evidence cannot establish causal order and must remain review-required; upload order, UUIDs, and worksheet rows are not temporal evidence. A real report is required before defining identifiers, receipt time, origin/destination, quantity, and return-state semantics.
- 2026-09-20: The user clarified that the audit workbook's blank-header L column records returns. Read-only profiling found 135 unambiguous return-like values (`VOLVI�`, `DEVOLVIO`, `DEVOLVI�`) and one ambiguous `VOLVI� 4` row. L has no header, date, destination, or receipt time; blank means unmarked/unknown, not a negative return. Raw L remains immutable positional evidence and must map to a separate derived state.
- 2026-09-20: The user chose to interpret recognized L return markers as post-audit return events. AR-05 may project a matched asset as returned and remove it from current found/pending counts without modifying its audit observation. `VOLVI� 4`, blank markers, and unresolved identifiers remain review/unmarked evidence; no fabricated `RETURNED` source observation or destination will be created.
- 2026-09-21: The user accepted the documented Docker validation gap and authorized the AR-05 work-unit commit. Commit `95ecde0` (`feat: derive audit return states`) contains the projection, migration, API, documentation, tests, and ODD tracking.
- 2026-09-21: AR-07 mapping found a static React shell and only one suitable presentation read API (`GET /api/current-states`). Executive KPIs, import history, review queues, category drill-down, and manual decisions have no backend read contracts and must not be calculated by the browser. A first frontend slice can truthfully deliver auth/session UI, existing upload forms, and current-state list; dashboard work needs an as-of/KPI contract first.
- 2026-09-21: The user selected latest available System and Audit evidence per CC as the dashboard rule. Server responses must include both source report dates and a visible freshness warning whenever they differ; the browser must not imply a common cutoff.
- 2026-09-21: The user chose a reviewable AR-07 split: AR-07A provides backend dashboard and operational read contracts; AR-07B then delivers the presentation-only React views.
- 2026-09-21: AR-07A added viewer-only, bounded server read contracts for independently selected source batches, freshness, grouped system snapshot status counts, sanitized import history, and review queues. Backend tests, offline PostgreSQL SQL, frontend build, and whitespace checks passed; Docker Compose remains unavailable because Docker is absent.
- 2026-09-21: AR-07A correction paginates the deterministic server-owned Rubro/Categoría/Producto leaf order before constructing the returned hierarchy; every response, including an empty one, now includes bounded page metadata and high-cardinality boundary coverage.
- 2026-09-21: AR-07B added cookie-session React views for dashboard summaries and drill-down, operations, current states, and editor uploads. The UI renders server contracts directly, displays source freshness and the column-L inference limitation, and exposes no match-resolution command or credential storage. Vitest/RTL, production build, backend regression tests, and whitespace checks passed.

## Next step
Prepare the AR-08 operational deployment and automation handoff.

## Key Learnings
Recognized column-L markers are post-audit return annotations by explicit user authorization, not independently timestamped events. The audit workbook provides no destination, receipt record, or event time, so the projection records only the authorized inference and source-observation provenance. Same-date marker rank (recognized return > ambiguous > unmarked) is an approved deterministic interpretation rather than measured chronology. A later ambiguous marker is a review-required current projection and is not counted as found or returned. The supplied workbook stores accented marker variants with U+00D3, while the legacy U+FFFD renderings are retained as exact compatibility spellings without normalization. Dashboard source selection uses report date and a UUID only as a deterministic tie-breaker, never as evidence of event chronology.
