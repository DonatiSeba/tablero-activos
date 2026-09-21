# Readiness Session Factory Fix

## Objective
Restore production backend readiness by correcting the SQLAlchemy session-factory usage that makes `GET /ready` return HTTP 503 after otherwise successful startup and migrations.

## Problem and evidence
On VPS `srv1309451`, `activos-backend-1` starts successfully but remains unhealthy because its `/ready` probe returns 503. An in-container diagnostic raised `AttributeError: 'sessionmaker' object has no attribute 'get_bind'` at `backend/app/readiness.py:29`. The backend image and database both target the Alembic head `20260921_0005`; this defect is independent of VPS directory selection, Compose interpolation, and migration application.

## Scope
- Correct only the database-readiness session acquisition.
- Add focused regression coverage for real session-factory use.
- Do not change secrets, migrations, Compose configuration, healthcheck semantics, or public readiness response detail.

## Constraints
- TDD mode: disabled; source: existing ODD feature baseline. Run focused regression checks.
- Technical artifacts remain English.
- No commit, push, or VPS mutation is authorized by this task. Request separate authorization before each.

## Acceptance criteria and checks
- The database readiness check obtains a real SQLAlchemy `Session`, runs its bounded read-only database probe, and closes the session.
- The existing fail-closed public `/ready` contract remains unchanged.
- Focused readiness tests pass locally.
- `git diff --check` passes.

## Delivery strategy
- Forecast: below 400 authored changed lines.
- Strategy: ask-on-risk.
- Branch: `feat/asset-reconciliation-mvp`.

## Tasks

- [x] RDY-01 Correct database readiness session acquisition and cover the regression.
  - Allowed edit surfaces: `backend/app/readiness.py`, `backend/tests/test_readiness.py`.
  - Outcome: readiness uses a real configured SQLAlchemy session without an `AttributeError`, preserving bounded checks, detail-free failures, and cleanup on every probe path.
  - Checks: writer and independent verifier each observed `python -m pytest backend/tests/test_readiness.py` pass (6 tests; 52 dependency deprecation warnings); `git diff --check` passed (only LF→CRLF working-tree warnings).
  - Evidence: the native risk assessment was unavailable, so independent verification was required and passed with no actionable findings. No VPS deployment occurred.
  - Commit: `ff1ae6e` (`fix: repair backend readiness session handling`).

## Progress
- 2026-09-20: User authorized the local correction and focused tests after VPS evidence proved the sessionmaker `get_bind` defect. Commit, push, and VPS redeployment remain unapproved.
- 2026-09-20: The first bounded writer applied the code fix and regression test, then reported partial verification: `python -m pytest backend/tests/test_readiness.py` has two setup failures because `sessionmaker(class_=make_session)` requires a Session class rather than a factory callable. No VPS deployment occurred.
- 2026-09-20: A follow-up worker replaced that invalid fixture with a real tracking `Session` subclass. Focused tests and whitespace checks passed; independent verification found no actionable issues. The native risk assessment returned unavailable, so the independent verification is the recorded fallback evidence.
- 2026-09-20: User authorized and created work-unit commit `ff1ae6e` (`fix: repair backend readiness session handling`).
- 2026-09-20: User authorized and pushed `ff1ae6e` to `origin/feat/asset-reconciliation-mvp`.
- 2026-09-20: VPS redeployment rebuilt `activos-backend` without rerunning migrations. PostgreSQL, backend, and Nginx all reported healthy; Docker's backend healthcheck validates `/ready`.
- 2026-09-20: Public HTTPS smoke checks succeeded for `https://activos.tisico-sa.com/api/health` and `/api/ready`; both returned successful curl exit status and the repeated liveness/readiness response was `{"status":"ok"}`.

## Next step
Operational readiness repair is complete. Retain normal monitoring and backup/restore procedures; no further deployment action is pending for this fix.
