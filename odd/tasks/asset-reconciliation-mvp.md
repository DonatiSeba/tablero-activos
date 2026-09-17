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

- [ ] AR-03 Import and validate system-report snapshots.
  - Outcome: authenticated editors can import the CC 190 system report; the service preserves raw evidence, rejects duplicate hashes, validates columns, normalizes codes, and reports warnings such as divergent CC names.
  - Checks: parser unit tests using minimal fixtures; duplicate import and validation tests; endpoint integration test.
  - Evidence: pending.

- [ ] AR-04 Add audit evidence and deterministic matching.
  - Outcome: audit reports become observations and match system assets by exact code then normalized code, surfacing unresolved evidence without silent merges.
  - Checks: matching unit tests; audit parser tests; reconciliation integration tests.
  - Evidence: pending.

- [ ] AR-05 Add return events and temporal reconciliation.
  - Outcome: return observations update inferred state chronologically without double counting assets found and later returned.
  - Checks: temporal reconciliation unit tests including post-audit returns and system-pending outcomes.
  - Evidence: pending.

- [x] AR-06 Implement local authentication, authorization, and audit logging.
  - Outcome: Argon2id-backed local users and database-validated signed cookie sessions enforce VIEWER, EDITOR, and ADMIN permissions in the API. `POST /api/auth/login`, `POST /api/auth/logout`, and `GET /api/auth/me` are available through Nginx; an explicit interactive CLI creates the first administrator.
  - Checks: fresh isolated Python 3.14 dependency installation and backend tests passed (17 tests; 27 FastAPI/Starlette dependency deprecation warnings); PostgreSQL offline Alembic SQL passed; frontend production build passed; independent security verification passed. Docker Compose and live PostgreSQL/Nginx checks could not run because Docker is absent.
  - Evidence: completed 2026-09-17. The service fails fast on invalid session configuration; Secure/HttpOnly/SameSite=Lax cookie behavior, dummy Argon2 verification, server-side role checks, isolated denial audit records, logout revocation, and active-user revalidation are covered. No work-unit commit was created because the user has not authorized commits.

- [ ] AR-07 Deliver the executive and operational frontend.
  - Outcome: directors can view grouped KPIs, category drill-down, import history, and review queues; editors can perform authorized imports and manual match decisions.
  - Checks: frontend component tests; production build; API-contract checks; responsive smoke test.
  - Evidence: pending.

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

## Next step
Choose whether to create a reviewed work-unit commit now, continue with AR-03 uncommitted, or pause for a change summary.
