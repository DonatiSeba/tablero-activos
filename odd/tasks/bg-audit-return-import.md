# BG Audit Return Import

## Objective
Import audit evidence from the two embedded `Activos en sistema BG Pag.*` sheets in the supplied CC 190 workbook. Rows with the confirmed light-blue direct fill represent returned assets; all other data rows represent pending assets.

## Product decision
- Parse exactly the two BG source pages, not the existing physical-audit sheets.
- The direct row fill `theme=7`, `tint=0.5999938962981048`, `solid` means **returned**.
- Every other BG data row means **pending / not surveyed**.
- Preserve source rows and fill evidence immutably. Do not infer dates or cost centers from the workbook name.

## Scope
- Add a strict BG audit workbook parser and preserve raw source/fill evidence.
- Interpret the confirmed blue fill as a returned audit marker; represent uncolored rows as pending rather than found.
- Extend focused parser/import/current-state tests.

## Constraints
- Existing physical-audit parser behavior must remain compatible.
- Rows are matched by the existing exact-or-unique-normalized asset-code contract.
- API-supplied report date and active cost center remain required.
- No commit, push, pull request, deployment, or uploaded-data mutation without explicit user authorization.

## Tasks

- [x] BAR-01 Implement strict BG-page audit parsing and returned/pending evidence mapping.
  - Allowed edit surfaces: `backend/app/audit_imports.py`, `backend/app/audit_current_states.py`, `backend/app/models.py`, `backend/alembic/versions/20261029_0007_bg_audit_return_markers.py`, `backend/tests/test_audit_imports.py`, `backend/tests/test_audit_current_states.py`.
  - Outcome: the importer recognizes only the two BG pages, maps column D identifier/source fields faithfully, records the blue-fill return marker plus pending state evidence, and safely migrates existing PostgreSQL data.

- [x] BAR-02 Verify parser, import integration, and projection precedence.
  - Checks: focused audit tests, full backend suite, `git diff --check`.

- [ ] BAR-03 Obtain explicit commit authorization.
  - Outcome: no commit until the user explicitly requests it.

## Evidence
- 2026-10-29: Workbook inspection found 831 BG data rows: 331 rows with direct `solid` theme-7/tint-0.5999938962981048 fill and 500 non-blue rows. The user confirmed blue = returned and the rest = pending.
- 2026-10-29: Independent verification blocked the initial implementation: PostgreSQL enum values cannot be consumed by new constraints in the same migration transaction. The bounded correction added an autocommit boundary and fill/tie-break coverage, but follow-up verification found the SQLite downgrade rebuild retained a check constraint over removed `marker_source`. That correction now drops the dependent enum check with the column, restoring the 0006 SQLite schema on downgrade.
- 2026-10-29: Final independent verification approved BAR-01/BAR-02: full backend suite passed 123 tests, `git diff --check` passed, and the supplied workbook parsed as exactly 831 BG rows (331 returned, 500 pending). PostgreSQL upgrade logic was source-reviewed but not exercised against a live PostgreSQL server; PostgreSQL downgrade intentionally remains unsupported once BG-specific values exist.
