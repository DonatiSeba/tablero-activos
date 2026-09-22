# Multi-Cost-Center Report Linking

## Objective
Allow administrators to configure any number of cost centers and let authorized importers explicitly associate each BSG/system and audit report with the correct cost center.

## Problem
The persistence model already supports multiple cost centers and multiple report batches per center, but cost centers can only be created implicitly by a system import. The audit form requires a manually typed code, and the system form does not expose or confirm the selected center. This makes the multi-center workflow difficult to discover and easy to mis-associate.

## Product decisions
- Asset codes are globally unique across the company.
- Cost centers are managed explicitly rather than existing only as a side effect of a BSG/system import.
- Every upload is associated with one selected cost center.
- A BSG/system workbook must contain exactly one center and its code must match the selected center.
- The dashboard continues to use the latest completed system batch and latest completed audit batch independently for each center; all prior batches remain in history.
- Administrators manage cost centers; editors and administrators may select active centers and upload reports.

## Scope
- Add protected cost-center list/create/update capabilities over the existing `CostCenter` model.
- Require and validate explicit cost-center association for system and audit imports.
- Replace free-text center entry in the import UI with active-center selectors and add an administrator management surface.
- Preserve immutable import evidence, report history, existing dashboard aggregation, authentication, and role boundaries.

## Constraints
- Backend and PostgreSQL remain the owners of validation and business rules.
- A selected system-import center must match the workbook `Nro. CC`; mismatches are rejected before evidence is persisted.
- Inactive centers cannot receive new imports but remain visible in historical reads.
- Asset identity and audit matching remain global because asset codes are globally unique.
- No explicit pairing table is introduced; latest-per-source selection remains the approved dashboard rule.
- UI copy remains Spanish; technical artifacts remain English.
- No push, pull request, deployment, or commit without explicit user authorization.

## Delivery strategy
- Forecast: approximately 450–700 authored changed lines across backend routes, import validation, frontend UI, tests, and documentation.
- Strategy: feature-branch-chain (selected by the user after the above-budget forecast).
- Slices: MCC-01 backend center lifecycle, MCC-02 explicit import binding, then MCC-03 frontend management/upload workflow.
- Slice boundary: MCC-01 is commit `9b626e2`; MCC-02 starts after it.
- Running authored lines: 890 committed after MCC-01; MCC-02 currently adds 553 uncommitted authored lines (tests, docs, and tracking included; no generated files).
- Branch: `feat/asset-reconciliation-mvp`.

## TDD and checks
- Mode: disabled.
- Source: inherited ODD project baseline; tests exist, but no project/session setting enables strict TDD.
- Backend runner: `python -m pytest backend/tests` with focused files first.
- Frontend runner: `npm --prefix frontend test -- --run` and `npm --prefix frontend run build`.
- Repository check: `git diff --check`.

## Tasks

- [x] MCC-01 Add protected cost-center management contracts.
  - Status: completed.
  - Allowed edit candidates: `backend/app/cost_centers.py`, `backend/app/main.py`, `backend/app/models.py` only if required, `backend/tests/test_cost_centers.py`, and directly related backend test helpers.
  - Outcome: administrators can create and update centers; authorized importers can list active centers; duplicate/blank codes, invalid date ranges, unauthorized mutations, and inactive-state behavior are validated server-side.
  - Checks: focused backend tests, full backend regression suite, and whitespace check.
  - Commit: `9b626e2` (`feat: add cost center management contracts`).

- [ ] MCC-02 Bind both import sources to an explicit active cost center.
  - Status: verified; work-unit commit authorized and pending.
  - Allowed edit candidates: `backend/app/imports.py`, `backend/app/system_imports.py` only if required, `backend/tests/test_system_imports.py`, `backend/tests/test_audit_imports.py`, and import API documentation under `docs/` or `README.md` when directly affected.
  - Outcome: system and audit uploads require an active selected center; system workbook codes must match it; imports remain immutable and historical; existing automation contracts are documented.
  - Checks: focused import tests, full backend regression suite, offline migration SQL if persistence changes, and whitespace check.
  - Commit: authorized; identity pending.

- [ ] MCC-03 Deliver the multi-center management and upload UI.
  - Status: pending.
  - Allowed edit candidates: `frontend/src/app.tsx`, `frontend/src/app.test.tsx`, `frontend/src/styles.css` only if required.
  - Outcome: administrators can manage centers; editors/admins select an active center for both report types; loading/error states remain isolated; import history refreshes after successful uploads.
  - Checks: focused/full frontend tests, production build, full backend regression suite, and whitespace check.
  - Commit: pending explicit user authorization.

## Acceptance criteria
- More than one active cost center can be created without importing a report first.
- Every accepted system or audit batch references the center explicitly selected by the importer.
- A system file whose embedded center differs from the selection is rejected without persisting evidence.
- Inactive centers cannot receive new reports.
- Editors and administrators can select any active center; only administrators can create or modify centers.
- Dashboard and history remain isolated by center and retain prior report batches.
- Existing authorization, immutable-evidence, duplicate-file, and global-asset-identity behavior remains covered.

## Progress
- 2026-09-22: Read-only exploration confirmed the database and dashboard already support multiple centers and multiple batches per center. The missing capabilities are explicit center management and safe upload association.
- 2026-09-22: The user confirmed asset codes are globally unique across the company, so asset identity remains global.
- 2026-09-22: The user accepted the proposed explicit management and upload-linking direction. No source files have been changed yet.
- 2026-09-22: MCC-01 started through one bounded backend writer.
- 2026-09-22: MCC-01 writer checks passed (8 focused, 103 full), but independent verification found semantic same-value PATCH requests were accepted as mutations and several denial paths lacked direct regression tests. MCC-01 remained in progress for a bounded correction.
- 2026-09-22: MCC-01 correction now rejects and audits semantic no-op PATCH requests and adds direct denial-path coverage. Final independent verification passed with 17 focused tests and 112 full backend tests; the parent spot-check reran 17 focused tests successfully.
- 2026-09-22: The user authorized the MCC-01 work-unit commit and selected the feature-branch-chain delivery strategy. Push and deployment remain unauthorized.
- 2026-09-22: MCC-01 completed in commit `9b626e2` with 890 authored lines. MCC-02 started as the next isolated work unit.
- 2026-09-22: MCC-02 writer reached 26 focused and 113 full passing tests, but independent verification failed on validation precedence and insufficient multi-center relationship assertions. A pre-existing post-storage/database-failure orphan-file risk was also identified; it is outside this task's explicit-center scope and must be documented truthfully rather than silently expanded into storage transaction redesign.
- 2026-09-22: MCC-02 correction validates the selected center before workbook processing, proves every multi-center persistence relationship, and fixes external duplicate-response documentation. Final independent verification passed with 28 focused and 115 full backend tests; the parent spot-check reran 28 focused tests successfully. The coherent work unit is 553 authored lines.
- 2026-09-22: The user authorized the MCC-02 work-unit commit and continuation into MCC-03. Push and deployment remain unauthorized.

## Verification evidence
- MCC-01 initial writer: `python -m pytest backend/tests/test_cost_centers.py` passed (8 tests); `python -m pytest backend/tests` passed (103 tests); `git diff --check` passed with an LF-to-CRLF working-copy warning.
- MCC-01 initial independent verification: FAIL because same-value PATCH requests created update audit records instead of being rejected; empty/null/missing-center update paths needed direct tests.
- MCC-01 final independent verification: PASS; prior findings closed, 17 focused tests passed, 112 full backend tests passed, `git diff --check` passed with the existing line-ending warning, and `git diff --cached --exit-code` confirmed no staged changes.
- MCC-01 parent spot-check: 17 focused tests passed; cached diff and whitespace checks passed.
- MCC-02 initial writer: final rerun passed 26 focused import tests and 113 full backend tests; `git diff --check` passed, but the writer reported partial because an earlier assertion relied on nondeterministic audit-log ordering.
- MCC-02 initial independent verification: FAIL because center lifecycle validation followed workbook parsing/digest checks and tests did not fully assert batch/observation/case center relationships. It also surfaced the pre-existing possibility of a digest file remaining after database persistence failure.
- MCC-02 final independent verification: PASS; all prior implementation and documentation findings closed, 28 focused tests passed, 115 full backend tests passed, and the staged index was clean.
- MCC-02 parent spot-check: 28 focused import tests passed; cached diff and whitespace checks passed.

## Next step
Create the authorized MCC-02 work-unit commit, record its identity, then start MCC-03.
