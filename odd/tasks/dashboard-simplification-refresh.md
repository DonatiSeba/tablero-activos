# Dashboard Simplification and Refresh

## Objective
Simplify the dashboard by removing the historical-evidence and operational-issues panels, and make dashboard summaries and charts explicitly refresh after new data becomes available.

## Product decisions
- Remove the visible "Evidencia histórica de relevamiento" panel.
- Remove the visible "Inconsistencias operativas" panel.
- Keep the primary physical-audit KPI cards when historical evidence is available.
- Preserve backend response fields for compatibility; this change is presentation and client-refresh behavior only.
- Provide an accessible user-initiated dashboard refresh. Do not add background polling.

## Evidence
- VPS database is at Alembic revision `20261030_0008`.
- The active audit batch has historical evidence available with 831 BG rows and 331 returned BG rows.
- `historical_found_evidence_projections` contains 763 rows.
- The client loads dashboard summaries only on mount; imports do not invalidate summary, drilldown, or rubro-chart requests.

## Scope
- Remove the two specified frontend panels and their dead styling.
- Refresh summary, drilldown, and rubro-chart state through a shared refresh identity without changing the selected cost center.
- Add regression coverage for the simplified dashboard and refreshed chart data.

## Non-goals
- Do not remove or migrate backend historical-evidence data.
- Do not change import semantics, audit projections, or physical KPI definitions.
- Do not introduce automatic polling.
- Do not deploy, push, or commit without separate authorization.

## Allowed edit surfaces
- `frontend/src/app.tsx`
- `frontend/src/app.test.tsx`
- `frontend/src/styles.css`
- `odd/tasks/dashboard-simplification-refresh.md`

## Tasks
- [x] DSR-01 Remove the historical-evidence and operational-issues dashboard panels, including dead styles, and cover their absence.
  - Outcome: removed both dedicated sections while preserving historical primary KPI cards and the backend response contract.
  - Verification: independent review observed populated-payload absence coverage; `npm test -- src/app.test.tsx` passed (41 tests) and scoped `git diff --check` passed.
- [x] DSR-02 Add an explicit dashboard refresh that invalidates summary, drilldown, and rubro-chart data while preserving the selected cost center; add regression coverage.
  - Outcome: an accessible refresh reloads the active summary page plus same-center drilldown and rubro-chart data; request versions reject stale results.
  - Verification: independent re-verification confirmed active page-two selection is retained; focused frontend tests passed (44 tests) and scoped `git diff --check` passed.
- [x] DSR-03 Run frontend regression and production-build verification, then record results.
  - Verification: independent final verification observed full frontend tests pass (44), the TypeScript/Vite production build pass, and scoped `git diff --check` pass. Vite reports its existing non-blocking 500 kB chunk-size advisory.
- [x] DSR-03a Correct the newly added frontend test fixture types and rerun complete verification.
  - Outcome: widened the test-only mock fixture's `rubro` field to `string | null`, allowing refreshed and stale test values without changing runtime behavior.
- [x] DSR-04 Request explicit commit authorization after verified implementation.
  - Outcome: user authorized commit; implementation committed as `532a39c` (`fix: simplify dashboard refresh`).

## Progress
- 2026-11-16: User authorized simplification and refresh correction. Read-only exploration confirmed stored historical evidence is present; the stale display is a client lifecycle issue rather than missing audit data.
- 2026-11-16: DSR-01 completed and independently verified. Only the two requested panels and their panel-specific styles were removed; historical primary KPI rendering remains intact.
- 2026-11-16: DSR-02 completed and independently verified. A first implementation reset paginated summaries on refresh; it was corrected and covered so the active page and selected center remain visible.
- 2026-11-16: DSR-03 verification found a build-blocking TypeScript error in three newly added test fixture fields. Full frontend tests passed (44); whitespace checks passed; no build artifact was produced.
- 2026-11-16: DSR-03a corrected the test-only fixture type. Independent final verification passed all frontend tests (44), TypeScript/Vite production build, and scoped whitespace validation.
- 2026-11-16: User authorized and created the implementation work-unit commit `532a39c` (`fix: simplify dashboard refresh`). Native review inspect reported RDD disabled; delegated writer and independent verifier evidence are recorded above.
