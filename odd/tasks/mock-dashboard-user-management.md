# Mock Dashboard and User Management

## Objective
Align the production application with `C:/Users/sebaa/Downloads/mock_dashboard_conciliacion_activos.html` while preserving real backend-owned reconciliation data, and add secure ADMIN-only user management based on the established role model.

## Product authority
- Visual reference: `C:/Users/sebaa/Downloads/mock_dashboard_conciliacion_activos.html`.
- Product requirements: `../PROYECTO_CONCILIACION_ACTIVOS.md`.
- Roles remain fixed RBAC: `VIEWER`, `EDITOR`, and `ADMIN`; changing permissions means assigning one of these roles.
- User selected temporary password reset with mandatory password change at next login.

## Scope
- Restyle the application shell and selected-cost-center dashboard to follow the mock's hierarchy, spacing, typography, colors, navigation, cards, charts, grouped table, and responsive behavior.
- Preserve verified server-owned KPIs, freshness, chart, pagination, and reconciliation semantics.
- Add ADMIN-only APIs and UI to list, create, edit, activate/deactivate, and reset users.
- Add self-service password change and force a password change after an administrative temporary reset.
- Audit security-sensitive user-management actions without recording secrets.

## Non-goals
- No granular per-user permission checkboxes or new permission table.
- No Sankey chart; the product authority explicitly discards it as a primary visualization.
- No fabricated export or historical-cutoff behavior without backend contracts.
- No deletion of users with historical activity.
- No client-side business, permission, freshness, or reconciliation calculations.

## Security constraints
- All management endpoints are ADMIN-only; frontend visibility is UX only.
- Passwords never appear in logs, audit details, responses after creation, or browser storage.
- Passwords use existing Argon2id policy and a minimum length consistent with the CLI.
- Reset/deactivation revoke active sessions.
- Prevent self-disable, self-demotion, and operations that leave zero active administrators, including concurrent updates.
- Role changes take effect through database-backed request authorization.
- Temporary reset credentials are shown once and require change before normal application access.

## TDD and checks
- Mode: disabled; source: existing ODD baseline.
- Use focused backend migration/auth/user tests, frontend component tests, production build, and whitespace checks.
- Native assessment has been unavailable in this repository; follow its returned independent-verification fallback when required.

## Delivery strategy
- Forecast: above 400 authored lines across migration, backend API, frontend shell, user-management UI, and tests.
- Strategy: ask-on-risk; plan reviewable backend-security and frontend-experience work units.
- Branch: `feat/asset-reconciliation-mvp`.
- No commit, push, PR, or VPS deployment without explicit user authorization.

## Tasks

- [x] UXU-01 Add secure role-based user-management contracts.
  - Allowed edit candidates: `backend/app/models.py`, `backend/app/auth.py`, `backend/app/users.py`, `backend/app/main.py`, a new Alembic revision under `backend/alembic/versions/`, `backend/tests/test_auth.py`, `backend/tests/test_users.py`, and migration regression coverage where required.
  - Outcome: ADMIN can list/create/edit/activate/deactivate/reset users; users can change their own password; temporary resets force change; last-admin and self-lockout protections hold; secrets never leak.
  - Checks: focused auth/user/migration tests; offline Alembic SQL if migration changes; `git diff --check`.
  - Evidence: final writer and independent security verification passed: 22 focused auth/user/migration tests, PostgreSQL offline Alembic SQL, and whitespace checks. The corrected self-change path locks and refreshes user/session state, revalidates credentials and session validity, and preserves an administrative reset committed first. SQLite proves stale-state behavior and compiled PostgreSQL locks; live PostgreSQL lock scheduling remains untested.
  - Commit: `f15c8b4` (`feat: add secure user management`).

- [x] UXU-02 Rebuild the application shell from the approved mock.
  - Allowed edit candidates: `frontend/src/app.tsx`, `frontend/src/styles.css`, `frontend/src/app.test.tsx`.
  - Outcome: real-data dashboard follows the mock's visual hierarchy with selected-CC focus, grouped navigation, large KPIs, charts, grouped reconciliation table, inconsistencies, accessible mobile navigation, and no unsupported mock-only features.
  - Checks: frontend tests; production build; `git diff --check`.
  - Evidence: final writer and independent verification passed: 11 frontend tests, production build, and whitespace checks. Closed mobile navigation now uses breakpoint-aligned `aria-hidden`, `inert`, and CSS visibility semantics without hiding desktop navigation. Real-browser visual fidelity, tab sequencing, screen readers, ECharts rendering, and live API integration remain untested.
  - Commit: `7fe07da` (`feat: match dashboard mock and manage users`).

- [x] UXU-03 Add ADMIN-only user-management UI.
  - Allowed edit candidates: `frontend/src/app.tsx`, `frontend/src/styles.css`, `frontend/src/app.test.tsx`.
  - Outcome: admins can manage users and roles through the real API; viewer/editor cannot see the section; password fields are transient; forced-password-change state blocks normal navigation until resolved.
  - Checks: frontend tests; production build; `git diff --check`.
  - Evidence: final writer and integrated verification passed. ADMIN gating, API compatibility, transient one-time-disclosure credentials, forced/self password change, safe localized errors, and server-driven pagination were verified. Frontend suite passes 17 tests and production build succeeds.
  - Commit: `7fe07da` (`feat: match dashboard mock and manage users`).

- [x] UXU-04 Independently verify integrated security and experience.
  - Outcome: verify authorization, last-admin/self-lockout safeguards, secret handling, migration behavior, Spanish UI, mock fidelity, responsive behavior, and regressions before delivery.
  - Checks: exact backend/frontend commands established by UXU-01 through UXU-03.
  - Evidence: final independent verification passed with no actionable findings: full backend suite (89 tests), PostgreSQL offline Alembic SQL, frontend suite (17 tests), production build, and whitespace checks all passed. Live PostgreSQL concurrency/migration execution, real-browser visual/accessibility/API behavior, and the 1.22 MB frontend bundle warning remain explicit gaps.

- [x] UXU-05 Approve reviewable delivery slices.
  - Outcome: choose how to deliver approximately 1,753 authored implementation lines across backend security and frontend experience without obscuring review boundaries.
  - Recommended slices: UXU-01 backend/migration/security tests, then UXU-02/03 frontend dashboard and user management.
  - Evidence: user selected two chained work units. Local commits `f15c8b4` and `7fe07da` were created; no push or deployment occurred.

## Progress
- 2026-09-20: User supplied `mock_dashboard_conciliacion_activos.html` as the desired visual reference and requested user creation and editable permissions.
- 2026-09-20: Read-only mapping confirmed the existing product model uses fixed hierarchical roles, not granular permissions, and currently has no HTTP user-management API.
- 2026-09-20: User selected temporary password reset with mandatory change at next login, authorizing the corresponding small user-schema migration and forced-change flow.
- 2026-09-20: UXU-01 initial implementation passed focused checks. Independent security review found a reset-vs-self-change concurrency race and required row-lock/refresh/revalidation on self-service password change. Frontend work remained blocked.
- 2026-09-20: UXU-01 race correction and final independent security verification passed with no actionable findings. Live PostgreSQL concurrency remains a deployment verification gap; the secure API contract is ready for frontend consumption.
- 2026-09-20: UXU-02 implemented the mock-aligned shell and selected-CC dashboard. One mobile-navigation accessibility test failed because the close toggle and backdrop shared the same accessible name.
- 2026-09-20: Unique mobile control names and automated checks passed. Independent verification found the closed off-canvas sidebar remained keyboard/screen-reader reachable at the mobile breakpoint.
- 2026-09-20: UXU-02 closed-mobile-sidebar correction and final independent verification passed with no actionable findings. Real-browser responsive/accessibility/visual checks remain an integration gap.
- 2026-09-20: UXU-03 user-management UI passed writer checks. UXU-04 full automated verification passed all commands and cross-layer contracts, but found dashboard pagination lacked controls for subsequent cost-center and grouped pages.
- 2026-09-20: Server-driven pagination and 17 passing frontend tests were added. The production build exposed a narrow test-fixture type inference (`rubro: null`).
- 2026-09-20: Explicit fixture typing resolved the build blocker. Final UXU-04 independent verification passed all checks with no actionable findings. Live PostgreSQL/browser validation and bundle size remain residual gaps.
- 2026-09-20: The verified implementation totals approximately 1,753 authored lines excluding trackers. The configured `ask-on-risk` strategy requires a user delivery-slice decision before any commit.
- 2026-09-20: User selected two chained work units. Commit `f15c8b4` contains backend user security/API/migration work (970 authored lines); `7fe07da` contains the mock-aligned dashboard and user-management UI (783 authored lines). These are the smallest coherent security/frontend boundaries despite exceeding the 400-line heuristic.
- 2026-09-20: User authorized and pushed `f15c8b4` and `7fe07da` to `origin/feat/asset-reconciliation-mvp`.
- 2026-09-20: Production rebuilt migrate/backend/Nginx, applied Alembic `20260922_0006` transactionally, and restarted PostgreSQL, backend, and Nginx healthy. Public readiness, backup-generation verification, and real-browser functional validation remain pending.

## Next step
Confirm the matched backup generation, public `/api/ready`, and browser behavior for the mock-aligned dashboard, ADMIN Users view, and password flows.
