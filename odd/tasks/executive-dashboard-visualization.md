# Executive Dashboard Visualization

## Objective
Deliver the executive and operational dashboard defined in `../PROYECTO_CONCILIACION_ACTIVOS.md`: Spanish-language, visually coherent, corporate UI that lets leadership understand reconciliation status, differences, and priorities at a glance.

## Product source of truth
`../PROYECTO_CONCILIACION_ACTIVOS.md` requires:
- Executive KPIs for System, Found in Cost Center, Returned, Accounted, Difference, and coverage.
- Grouped navigation Rubro → Category → Product → Asset.
- Primary visualizations: stacked bars by rubro/category, a general-status donut, and time evolution when snapshots support it; heatmap/treemap are progressive enhancements.
- Clear separation between physical/patrimonial differences and system-data quality/update problems.
- A dark sidebar, light main area, KPI cards, corporate state colors, responsive layout, and discreet motion.
- Backend-owned calculations; React only renders server-owned results.
- Spanish user-facing UI.

## Problem and evidence
The deployed frontend is functional but has English local copy, text-width-dependent buttons, and no charts. `frontend/src/app.tsx` centralizes current UI copy and buttons; `frontend/src/styles.css` has only a base button rule. Existing audit source-row totals are correct across valid worksheets and are not part of this feature.

## Scope
- Reconcile existing dashboard read contracts with the documented executive metrics and chart data.
- Add only backend-owned aggregate/read data necessary for the documented dashboard.
- Rebuild the React dashboard visual system, Spanish UI copy, responsive layout, chart rendering, and clear empty/loading/error states.
- Add focused backend and frontend coverage.

## Non-goals
- No client-side reconciliation calculations.
- No change to import parsers, audit row-count semantics, matching, or migrations unless a proven dashboard contract requires one.
- No fabricated time series when fewer than two comparable snapshots exist.
- No Sankey chart.

## Constraints
- TDD mode: disabled; source: existing ODD feature baseline. Use focused functional checks.
- Technical artifacts remain English; user-facing UI must be Spanish.
- The source spec is the product authority; do not ask the user to redefine documented dashboard semantics.
- No commit, push, PR, or VPS deployment without explicit user authorization.

## Delivery strategy
- Forecast: above 400 authored changed lines across contract, UI, charts, and tests.
- Strategy: ask-on-risk; split into independent backend and frontend work units before any delivery decision.
- Branch: `feat/asset-reconciliation-mvp`.

## Tasks

- [x] DASH-01 Establish chart-ready executive dashboard read contracts.
  - Allowed edit surfaces (provisional; confirm from mapper): `backend/app/dashboard.py`, `backend/app/main.py`, `backend/tests/test_dashboard_reads.py`.
  - Outcome: viewer-authorized server responses expose documented executive KPIs and chart-ready grouped/time data without moving business calculations into React.
  - Checks: focused dashboard backend tests; offline Alembic/contract checks only if affected; `git diff --check`.
  - Evidence: writer and final independent verifier observed `python -m pytest backend/tests/test_dashboard_reads.py` pass (5 tests; 55 dependency deprecation warnings) and `git diff --check` pass. The contract now keeps undated returns out of evolution, separates audit-only system-quality omissions, provides server-owned freshness, bounds reads, and distinguishes explicit NULL labels from omitted dimensions.
  - Commit: `69204c7` (`feat: expose executive dashboard metrics`).

- [x] DASH-02 Deliver Spanish visual dashboard and consistent interaction system.
  - Allowed edit surfaces (provisional; confirm from mapper): `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/app.tsx`, `frontend/src/styles.css`, `frontend/src/app.test.tsx`.
  - Outcome: Spanish corporate dashboard renders server-owned KPI, bar, donut, and truthful temporal/empty-state views; buttons share explicit semantic variants and the layout remains responsive.
  - Checks: frontend component tests; production build; `git diff --check`.
  - Evidence: final independent verifier observed `npm --prefix frontend test` pass (8 tests), `npm --prefix frontend run build` pass, and `git diff --check` pass. Spanish rendering, operational unresolved-case visibility, unavailable return-evolution notice, ECharts charts, responsive button variants, and backend-owned calculations were verified. ECharts bundle size and dashboard query fan-out remain production risks to assess separately.
  - Commit: `ff3e0c1` (`feat: deliver executive dashboard visualizations`).

- [x] DASH-03 Independently verify the integrated executive dashboard.
  - Outcome: contracts, visual state mappings, Spanish copy, and build behavior are independently checked before any delivery request.
  - Checks: exact focused backend/frontend commands selected from DASH-01 and DASH-02 evidence.
  - Evidence: final independent verification passed: 5 focused backend tests, 8 frontend tests, production build, and whitespace check. No live-browser or production-volume performance test ran.
  - Commit: no code commit; verification evidence only.

- [x] DASH-04 Approve reviewable delivery slices.
  - Outcome: user selected two chained work units: DASH-01 backend contract, then DASH-02 frontend.
  - Evidence: commits `69204c7` and `ff3e0c1` created locally; no push or VPS deployment occurred.

## Progress
- 2026-09-20: User reported English UI copy, inconsistent button sizing, and absence of executive charts in the deployed frontend.
- 2026-09-20: Read-only mapping confirmed the audit 763-row display is the total of non-empty rows across all valid audit worksheets, not quantity expansion. User chose to leave that behavior unchanged.
- 2026-09-20: The project specification was re-read after the user correctly noted that dashboard priorities were already defined there. It establishes the KPI and visualization requirements for this feature.
- 2026-09-20: DASH-01 writer implemented an initial contract and its focused tests passed. Independent verification found temporal truthfulness, audit-only omission, server freshness, and read-bounding defects; DASH-02 is blocked pending the bounded DASH-01 correction.
- 2026-09-20: DASH-01 correction resolved those four defects, but independent verification found one remaining NULL-label drill-down scope defect. DASH-02 remained blocked until explicit NULL labels were distinguished from omitted filters.
- 2026-09-20: DASH-01 final correction and independent verification passed. DASH-01 awaits an explicit work-unit commit authorization; DASH-02 may consume the verified uncommitted server contract.
- 2026-09-20: DASH-02 writer added ECharts, Spanish local UI, button variants, and responsive chart layout; all writer checks passed. DASH-03 found three user-visible defects that block acceptance: untranslated API metadata/enums, omitted unresolved audit-match cases, and hidden unavailable-return-evolution state.
- 2026-09-20: DASH-02 correction implemented those defects, but the new localized queue assertion fails because its text is split by child markup. Frontend verification remains incomplete.
- 2026-09-20: The localization matcher correction passed all 8 frontend tests, but the production TypeScript build exposed a `never[]` inference in the temporal fixture. Frontend verification remained incomplete.
- 2026-09-20: Explicit temporal fixture typing resolved the build blocker. Final DASH-03 verification passed all focused backend/frontend checks and found no acceptance blockers. It reported non-blocking query-fan-out and 1.2 MB ECharts bundle risks, plus no live-browser or production-volume test.
- 2026-09-20: The verified dashboard diff totals 1,464 authored lines across seven source/package/test files. The configured `ask-on-risk` delivery strategy requires a user-selected review slicing strategy before any commit.
- 2026-09-20: User selected two chained work units. Commit `69204c7` carries the backend dashboard contract (880 authored lines) and `ff3e0c1` carries frontend visualization work (584 authored lines). This is the smallest coherent backend/frontend split; both still exceed the 400-line review heuristic, so do not mechanically split them further.
- 2026-09-20: User authorized and pushed `69204c7` and `ff3e0c1` to `origin/feat/asset-reconciliation-mvp`.
- 2026-09-20: VPS redeployment rebuilt backend and Nginx without migrations. PostgreSQL, backend, and Nginx reported healthy. Browser-based visual/responsive validation remains pending.

## Next step
Open the dashboard in a browser and validate Spanish copy, charts, button consistency, desktop/mobile layout, chart tooltips, and freshness/unavailable-return notices. Bundle/query-fan-out risks remain to monitor.
