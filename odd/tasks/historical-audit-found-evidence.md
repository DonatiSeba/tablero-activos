# Historical Audit Found Evidence

## Objective
Count all assets listed in the manual physical-audit sheets as historically found at the cost center, while independently reporting BG blue-fill rows as returned.

## Product decisions
- Total is the complete BG list for the selected cost center.
- Found is historical physical-audit evidence; it can overlap with returned evidence.
- Returned is determined only by the confirmed BG blue direct fill.
- A manual row without a machine identifier is still found evidence, but must retain its limited identity confidence rather than being silently attached to a BG asset.
- Rows with formatting/fill but no source values are blank and must be ignored; the five manual physical sheets are the only historical-found sources.
- Physical-row quantities are not automatically treated as distinct BG assets.
- The primary `Found` KPI counts nonblank manual physical rows. Distinct BG-linked manual rows are shown separately as a confidence/reconciliation metric.

## Scope
- Parse the manual physical-audit sheets alongside the BG sheets in one uploaded workbook.
- Preserve each manual source row and derive conservative BG relationships: exact identifier, whitespace-normalized identifier, uniquely embedded serial/code, review candidate, or unlinked found evidence.
- Expose total/found/returned metrics without making historical-found and returned mutually exclusive.
- Add a derived reconciliation workbook/report only if it is necessary to review uncertain relationships; never alter the uploaded original workbook.

## Evidence
- The supplied workbook has 831 BG rows: 331 blue/returned and 500 non-blue/pending.
- Manual physical sheets have 763 nonblank rows and 1,833 reported units; 215 rows lack `IDENTIFICACION`, so reported quantities cannot be assumed to identify distinct BG assets.
- 228 manual rows have high-confidence unique BG matches: 52 exact, 2 whitespace-normalized, and 174 uniquely embedded serial/code matches.
- Of those high-confidence relationships, 187 point to blue/returned BG rows and 41 to non-blue rows; found and returned necessarily overlap as historical evidence.
- 2026-10-29: Contract mapping confirmed parser and dashboard assumptions must be separated: parse all seven sheets together, preserve the five nonblank manual sources as historical evidence, and keep BG return state independent. The user selected manual nonblank rows as the primary Found KPI and authorized a two-work-unit implementation: backend/migration first, then dashboard presentation.
- 2026-10-30: HFE-02 initial implementation passed writer tests but independent verification blocked it: manual rows were incorrectly admitted to the exclusive current-state projection and embedded matching accepted weak tokens. The bounded correction filters current states to BG observations and requires six alphanumeric characters for automatic embedded links. Independent re-verification passed 63 targeted and 127 full backend tests.
- 2026-10-30: HFE-03 independent frontend verification approved the dedicated historical-evidence panel. It keeps additive historical metrics outside existing current-state charts; 41 tests and production build passed.
- 2026-10-30: User authorized local commits. Native review preflight reported `rdd_disabled`; no review transaction was started. Push and deployment remain separate decisions.

## Tasks
- [x] HFE-01 Map the current persistence, import, and dashboard contracts for historical found evidence.
  - Outcome: BG/manual rows are currently mutually exclusive parser paths and the dashboard treats found/returned as exclusive current states. The change needs typed mixed-source observations, a parallel historical-found projection, and additive metrics.
- [x] HFE-02 Implement mixed-source backend evidence and summary contract.
  - Allowed edit candidates: `backend/app/audit_imports.py`, `backend/app/imports.py`, `backend/app/models.py`, `backend/app/dashboard.py`, a directly related new backend projection module, one migration under `backend/alembic/versions/`, and focused backend tests.
  - Outcome: parse BG and five manual sheets together, ignore blank formatted rows, preserve manual found evidence, derive conservative links, and expose additive historical metrics without changing current return states.
  - Verification: independent re-verification passed 63 targeted and 127 full backend tests; `git diff --check` passed. Corrections exclude manual rows from exclusive current-state projections and require six alphanumeric characters for automatic embedded serial/code links.
  - Work-unit forecast: 450–650 changed lines across parser, persistence, migration, summary contract, and tests.
- [x] HFE-03 Implement dashboard presentation and regression coverage.
  - Allowed edit candidates: `frontend/src/app.tsx`, `frontend/src/app.test.tsx`, `frontend/src/styles.css` only if required, and directly related dashboard contract tests.
  - Outcome: a dedicated historical-evidence panel shows Total BG, Found manual rows, returned BG rows, linked/ambiguous/unlinked evidence, supplemental units, and the overlap warning; existing current-state charts remain exclusive-state views.
  - Verification: independent frontend review approved; 41 frontend tests and production build passed. The existing Vite large-chunk warning remains non-blocking.
  - Work-unit forecast: 180–300 changed lines.
- [x] HFE-04 Verify cross-source matching, overlapping metric semantics, migration safety, and regressions.
  - Verification: 63 targeted backend tests, 127 full backend tests, 41 frontend tests, production frontend build, SQLite migration coverage, offline PostgreSQL migration SQL generation, and `git diff --check` passed. A live PostgreSQL migration and browser E2E remain release validation steps.
- [x] HFE-05 Obtain explicit commit authorization.
  - Outcome: the user authorized work-unit commits; HFE-02 is `45a94a3` (`feat: add historical audit evidence`) and HFE-03 is `84dc033` (`feat: present historical audit metrics`).
