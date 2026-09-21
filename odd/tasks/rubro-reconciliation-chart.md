# Rubro Reconciliation Chart

## Objective
Replace the oversized reconciliation hierarchy table with a rubro selector and a category-level bar chart for the selected cost center.

## Product decision
- The user selects one rubro.
- The chart shows one row per category.
- Series are server-owned reconciliation metrics: found in cost center, returned, and difference.
- The frontend renders returned values and performs no reconciliation aggregation.

## Architecture
- Preserve the existing `system-drilldown` contract for the dashboard's current charts and unknown consumers.
- Add a focused authenticated dashboard contract that returns the complete deterministic rubro option set and the complete category chart for one selected rubro.
- The server selects a deterministic default rubro for the initial request; an explicit empty query value represents the unassigned/null rubro.
- Filter by rubro before grouping categories. Do not paginate or truncate category chart data.
- No database migration is required.

## Constraints
- Preserve latest completed system/audit batch selection and server-owned reconciliation semantics.
- Preserve null labels as `Sin rubro asignado` and `Sin categoría asignada`.
- Encode rubro query values safely.
- Keep loading, error, no-system-data, no-audit-data, empty-rubro, and high-cardinality states explicit.
- Remove the reconciliation hierarchy table and its product-level pagination UI from the dashboard detail section.
- Preserve cost-center pagination, other charts, user management, authentication, imports, and mobile accessibility.
- No commit, push, or deployment without explicit user authorization.

## TDD and checks
- Mode: disabled; source: existing ODD baseline.
- Add focused backend contract/query tests and frontend interaction tests.
- Run full backend tests, frontend tests/build, and whitespace checks before delivery.
- Native assessment has been unavailable; use independent verification when required.

## Tasks

- [x] RRC-01 Add the server-owned rubro/category chart contract.
  - Allowed edit candidates: `backend/app/dashboard.py`, `backend/tests/test_dashboard_reads.py`, `README.md` if the API is documented there.
  - Outcome: complete deterministic rubro options and selected-rubro category metrics are returned without leaf pagination or client aggregation.
  - Checks: focused dashboard tests and whitespace check.
  - Evidence: writer and independent verification passed. New authenticated `GET /api/dashboard/rubro-reconciliation-chart` preserves the existing drilldown contract, filters rubro before complete category aggregation, performs a constant number of queries, and handles omitted/null/named/special-character selections plus missing sources, invalid selections, null categories, and high cardinality. Focused tests pass 7/7; full backend suite passes 91 tests; whitespace check passes. Live PostgreSQL execution/plans remain untested.
  - Commit: `554d882` (`feat: expose reconciliation by rubro`).

- [x] RRC-02 Replace the reconciliation table with the rubro chart experience.
  - Allowed edit candidates: `frontend/src/app.tsx`, `frontend/src/styles.css`, `frontend/src/app.test.tsx`.
  - Outcome: accessible rubro selector drives a responsive horizontal category chart with found, returned, and difference series; stale table/product pagination is removed.
  - Checks: frontend tests, production build, and whitespace check.
  - Evidence: writer and final integrated verification passed: 21 frontend tests and production build succeed. Selector/chart behavior, race protection, localized states, direct server-value rendering, table removal, grouped bars, high-cardinality scrolling, and relocated primary-chart pagination were verified.
  - Commit: `3f6b12a` (`feat: chart reconciliation by rubro`).

- [x] RRC-03 Independently verify the integrated contract and experience.
  - Outcome: backend/frontend field compatibility, null semantics, URL encoding, complete data, loading/error/empty states, preserved dashboard behavior, and absence of client-side business calculations are verified.
  - Checks: full backend suite, frontend tests/build, and whitespace check.
  - Evidence: final independent verification passed with no actionable findings: 92 backend tests, 21 frontend tests, production build, and whitespace checks all pass. The PostgreSQL-invalid DISTINCT/ORDER BY shape was replaced by inner DISTINCT plus outer deterministic ordering and covered through PostgreSQL-dialect compilation. Live browser/PostgreSQL execution and the existing 1.22 MB bundle warning remain gaps.

- [x] RRC-04 Approve reviewable delivery slices.
  - Outcome: choose delivery boundaries for the 636-line tracked diff.
  - Recommendation: backend API/tests/docs followed by frontend selector/chart/tests/styles.
  - Evidence: user selected two chained work units. Local commits `554d882` and `3f6b12a` were created; no push or deployment occurred.

## Progress
- 2026-09-20: User requested replacing the giant reconciliation table with a rubro selector and bar chart.
- 2026-09-20: User selected category rows with found-in-cost-center, returned, and difference series.
- 2026-09-20: Read-only mapping confirmed the current leaf pagination can split rubro/category totals; a server-filtered unpaginated category contract is required. A focused new endpoint avoids breaking the existing dashboard drilldown contract.
- 2026-09-20: RRC-01 writer and independent verification passed with no actionable findings. The backend endpoint and README contract are ready for frontend consumption; live PostgreSQL execution and query-plan measurement remain gaps.
- 2026-09-20: RRC-02 writer checks passed. Initial RRC-03 verification found PostgreSQL rejects the DISTINCT rubro option query's ORDER BY expressions; SQLite masks the defect.
- 2026-09-20: The query was corrected with inner DISTINCT and outer deterministic ordering. Final RRC-03 verification passed all automated checks with no actionable findings.
- 2026-09-20: User selected two chained units. Commit `554d882` contains the backend contract/tests/docs; `3f6b12a` contains the frontend selector/chart/tests/styles.
- 2026-09-20: User authorized and pushed both commits to `origin/feat/asset-reconciliation-mvp`.
- 2026-09-20: Production rebuilt backend/Nginx without migration. Containers reported healthy. The first public readiness probe returned a transient 404 immediately after replacement; follow-up Nginx-internal and public probes both returned `200 {"status":"ok"}` with Nginx headers.
- 2026-09-20: User completed browser validation and accepted the deployed rubro selector/category chart experience.

## Deferred follow-ups
- Monitor production PostgreSQL latency and chart readability as category cardinality grows.
- Consider lazy-loading/code-splitting ECharts to reduce the existing ~1.22 MB JavaScript chunk.

## Next step
Feature complete; no active implementation task.
