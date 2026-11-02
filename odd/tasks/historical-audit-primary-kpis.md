# Historical Audit Primary KPIs

## Objective
Make the dashboard’s primary KPI cards reflect the physical audit when mixed BG/manual evidence is available.

## Product decisions
- Total is the number of BG rows.
- Found in CC is the number of nonblank rows across the five manual physical sheets.
- Returned is the number of blue BG rows.
- Pending to survey is `total BG - found manual rows`; returned is not subtracted because it can overlap historical found evidence.
- Existing current-state charts remain separate and retain their exclusive-state semantics.

## Scope
- Add server-owned derived primary metrics to the historical audit summary contract.
- Replace the dashboard primary-card values and supporting coverage/counter copy when historical audit data is available.
- Preserve a truthful unavailable state and existing non-historical dashboard behavior.

## Evidence
- Current deployed panel correctly shows `Total BG=831`, `Found manual rows=763`, and `Returned BG=331`.
- The primary cards still show legacy system/current-state values (`637`, `0`, `182`, `455`), which conflicts with the selected physical-audit definition.
- 2026-10-30: Implementation completed and independently verified: historical primary metrics are server-owned, pending is BG total minus manual found rows, and returns are never subtracted. The fallback remains unchanged when historical evidence is unavailable. Native review preflight reported `rdd_disabled`; push/deployment follow ordinary user authorization.

## Tasks
- [x] HAP-01 Add server-owned physical-audit primary metrics and backend coverage.
  - Outcome: the historical summary returns validated primary metrics for BG total, manual found rows, blue returns, and pending-to-survey; inconsistent values remain unavailable.
- [x] HAP-02 Bind primary dashboard cards to the physical-audit metrics and cover fallback behavior.
  - Outcome: primary cards render server-owned historical metrics when available and retain legacy cards only when historical evidence is unavailable.
- [x] HAP-03 Verify backend/frontend contracts and regressions.
  - Verification: dashboard backend tests (13), full backend suite (128), frontend tests (42), frontend production build, and `git diff --check` passed. The existing Vite chunk-size and deprecation warnings remain non-blocking.
- [x] HAP-04 Obtain explicit commit authorization.
  - Outcome: user authorized the correction commit `8ffdbbb` (`fix: prioritize physical audit KPIs`).
