# Exclude Hand Tools from Audit Evidence

## Objective
Exclude the `Herramientas de mano` manual audit sheet from historical found evidence and physical-audit KPIs because its rows lack unique asset identification and are not represented in the system.

## Product decision
- A mixed physical-audit workbook must still contain exactly five recognized manual sheets.
- `Herramientas de mano` is recognized by its normalized sheet name but is excluded before manual observations, reconciliation cases, and historical-found projections are created.
- The other four recognized manual sheets remain eligible and must provide the complete found-evidence count.
- No model, migration, dashboard-contract, or frontend semantic change is required.

## Evidence
- The parser currently treats every non-BG sheet with the physical-audit layout as a manual source.
- Historical primary Found counts all `historical_found_evidence_projections` for the selected audit batch.
- Existing immutable batches remain unchanged by a parser correction; a corrected workbook with distinct bytes must be imported as a newer selected audit batch before deployed KPIs change.

## Scope
- Exclude only the normalized `Herramientas de mano` sheet from parsed manual evidence.
- Preserve strict validation of five recognized manual sheets, with exactly four contributing manual sources after the exclusion.
- Cover parser/import/dashboard behavior with focused backend regressions.
- Document the exclusion and re-upload requirement.

## Non-goals
- Do not alter existing immutable batches or create a migration/backfill.
- Do not alter BG return/pending semantics.
- Do not redefine the overlapping historical metrics in the doughnut chart.
- Do not push, deploy, or commit without separate authorization.

## Allowed edit surfaces
- `backend/app/audit_imports.py`
- `backend/tests/test_audit_imports.py`
- `backend/tests/test_dashboard_reads.py`
- `README.md`
- `odd/tasks/exclude-hand-tools-audit-evidence.md`

## Tasks
- [x] HTE-01 Exclude the `Herramientas de mano` sheet from mixed-workbook manual evidence while preserving strict source validation.
  - Outcome: title-normalized source exclusion occurs before manual evidence persistence; five recognized layouts and four contributing sources are enforced.
  - Verification: independent review observed exclusion from parsed rows, observations, cases, and historical links; all 19 audit-import tests passed and scoped whitespace validation passed.
- [x] HTE-02 Add parser/import/dashboard regressions proving excluded rows do not affect historical Found or Pending metrics.
  - Outcome: dashboard coverage proves excluded hand-tool data cannot affect Found, Pending, reported units, BG total, or Returned metrics.
  - Verification: independent review observed the historical KPI regression; all 14 dashboard tests passed and scoped whitespace validation passed.
- [x] HTE-03 Document the source-exclusion and corrected re-upload requirement.
  - Outcome: the README documents the five-recognized/four-contributing contract, immutable evidence, and automatic latest-batch selection.
  - Verification: independent documentation review confirmed the source exclusion and that a distinct upload with a later report date is needed for predictable deployed KPI correction.
- [x] HTE-04 Run focused and full backend verification, then record results.
  - Verification: independent final verification observed 33 focused tests, 129 full backend tests, and scoped whitespace validation pass. Existing FastAPI/Starlette deprecation and Git LF-to-CRLF warnings remain non-blocking.
- [x] HTE-04a Add normalized excluded-sheet-title regression, then rerun verification.
  - Outcome: the regression uses full-width compatibility characters plus case/whitespace variation, so it fails if NFKC sheet-title normalization is removed.
- [x] HTE-05 Request explicit commit authorization after verified implementation.
  - Outcome: user authorized commit; implementation committed as `86578b4` (`fix: exclude hand tools from audit evidence`).

## Progress
- 2026-11-16: User confirmed a five-sheet workbook is accepted, but `Herramientas de mano` is ignored and exactly four remaining manual sheets contribute physical found evidence.
- 2026-11-16: HTE-01 completed and independently verified. The exclusion is sheet-title based, not a content heuristic, and retains strict source-layout validation.
- 2026-11-16: HTE-02 completed and independently verified. The dashboard contract retains BG total/returned values and excludes hand-tool rows from historical Found, Pending, and reported-unit metrics.
- 2026-11-16: HTE-03 completed and independently verified. README documentation avoids suggesting manual batch selection; the dashboard automatically selects the newest report-date batch, so corrected uploads need distinct bytes and a later report date.
- 2026-11-16: HTE-04 ran successfully (33 focused and 129 full backend tests), but independent verification identified a missing regression for normalized non-canonical excluded-sheet titles.
- 2026-11-16: HTE-04a added case/whitespace normalization coverage; independent re-verification found it does not isolate NFKC normalization, so a full-width compatibility-character case remains required.
- 2026-11-16: HTE-04a was corrected with full-width compatibility characters. Independent final verification confirms the NFKC contract and five-recognized/four-contributing behavior; all focused and full backend checks pass.
- 2026-11-16: User authorized and created implementation work-unit commit `86578b4` (`fix: exclude hand tools from audit evidence`). Native review inspect reported RDD disabled; delegated writer and independent verifier evidence are recorded above.
