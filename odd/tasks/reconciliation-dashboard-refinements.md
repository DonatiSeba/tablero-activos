# Reconciliation Dashboard Refinements

## Objective
Make the dashboard suppress unavailable temporal comparisons, surface every audited item absent from the selected cost center's system list, and support server-driven drill-down from rubro to category and product.

## Product decisions
- Render temporal evolution only when the backend marks it available.
- The selected cost center's system snapshot is the sole membership reference.
- Every audited item absent from that selected system list is classified as `not_in_management_system_for_cost_center`, regardless of whether it matches an asset assigned elsewhere or remains unmatched globally.
- Do not infer or expose another cost center for those items.
- The review outcome is administrative: correct the assignment or create the asset if it truly does not exist.
- Reuse the actual source hierarchy `Rubro → Categoría → Producto`; counts remain distinct identified assets and server-owned metrics.

## Constraints
- Preserve authentication, RBAC, imports, existing reconciliation evidence, and current dashboard contracts unless explicitly extended.
- Do not fabricate asset identities or expand source quantity into synthetic assets.
- Keep aggregation, filtering, null semantics, and reconciliation calculations on the server.
- Preserve explicit Spanish loading, error, unavailable, empty, and high-cardinality states.
- No database migration unless implementation evidence proves the existing JSON-backed hierarchy is insufficient.
- No commit, push, or deployment without explicit user authorization.

## Checks
- Focused backend and frontend tests for each work unit.
- Full `python -m pytest backend/tests`.
- Full `npm --prefix frontend test`.
- `npm --prefix frontend run build`.
- `git diff --check`.
- Independent verification before delivery.

## Tasks

- [x] RDR-01 Hide unavailable temporal evolution.
  - Outcome: the complete temporal panel is absent when `time_evolution.available` is false and remains visible with comparable points.
  - Allowed edit candidates: `frontend/src/app.tsx`, `frontend/src/app.test.tsx`, `frontend/src/styles.css` only if required.
  - Evidence: frontend writer passed focused and full suites (22 tests) plus whitespace checks. The complete panel is now gated solely by the backend-owned `time_evolution.available` flag; no client inference or stylesheet change was introduced.
  - Commit: frontend work unit `feat: improve reconciliation dashboard detail`.

- [x] RDR-02 Classify audited items absent from the selected CC system list.
  - Outcome: matched-elsewhere and unmatched audit evidence absent from the selected system snapshot is counted under one server-owned review category without disclosing another CC.
  - Allowed edit candidates: `backend/app/dashboard.py`, reconciliation/read-model helpers if required, `backend/tests/test_dashboard_reads.py`, `frontend/src/app.tsx`, `frontend/src/app.test.tsx`, `README.md`.
  - Evidence: backend/frontend writer passed 10 focused dashboard tests, 94 full backend tests, 22 frontend tests, and whitespace checks. The new server-owned `not_in_management_system_for_cost_center_count` composes distinct matched assets absent from the selected system snapshot plus unmatched audit cases, adds no query, remains null when either source is missing, preserves legacy fields, and replaces the two overlapping frontend cards with one Spanish review card.
  - Commits: `f5c07c1` (`feat: refine reconciliation drilldown data`) and frontend work unit `feat: improve reconciliation dashboard detail`.

- [x] RDR-03 Extend the backend category/product drill-down contract.
  - Outcome: the rubro chart endpoint returns deterministic category options and server-owned product metrics for one selected category, with explicit null/omitted semantics and bounded high-cardinality behavior.
  - Note: unmatched audit items cannot be assigned to the system hierarchy without fabrication, so the absent-from-system review count remains a separate operational metric rather than being grouped by product.
  - Allowed edit candidates: `backend/app/dashboard.py`, `backend/tests/test_dashboard_reads.py`, `README.md`.
  - Evidence: backend writer passed 11 focused dashboard tests, 95 full backend tests, and whitespace checks. The endpoint remains backward-compatible and now supports deterministic omitted/null/exact category selection plus bounded product pagination after complete SQL grouping. Product metrics count distinct assets, fixed query count remains 11 statements including authentication for both 2 and 102 products, and PostgreSQL shape is compile-covered. Live PostgreSQL execution remains unverified.
  - Commit: `f5c07c1` (`feat: refine reconciliation drilldown data`).

- [x] RDR-04 Add the cascading category/product frontend experience.
  - Outcome: users select rubro and category, then inspect product-level found, returned, and difference values rendered directly from the server.
  - Allowed edit candidates: `frontend/src/app.tsx`, `frontend/src/styles.css`, `frontend/src/app.test.tsx`.
  - Evidence: frontend writer passed 24 focused/full tests, production build, and whitespace checks. Category omission/null/encoding semantics, rubro/category/page resets, stale-response protection, direct server-value rendering, product-specific pagination, responsive scrolling, and unavailable/empty/error states are covered. The existing Vite warning is now 1,221.12 kB minified (401.02 kB gzip).
  - Commit: frontend work unit `feat: improve reconciliation dashboard detail`.

- [x] RDR-05 Independently verify the integrated behavior.
  - Outcome: backend/frontend contracts, nulls, encoding, stale responses, permissions, complete server-side aggregation, and preserved dashboard behavior pass review.
  - Evidence: independent verification passed after correcting one README precision issue. Full checks passed: 95 backend tests, 24 frontend tests, production build, and whitespace checks. No actionable RDR defect remains. Live PostgreSQL and real-browser execution remain environmental gaps; Vite retains the 1,221.12 kB chunk warning. Unrelated user-owned `frontend/index.html` and `frontend/public/favicon.svg` changes were preserved and excluded from RDR review scope.

- [x] RDR-06 Focus product-chart hover by item.
  - Outcome: hovering one product keeps its Encontrados, Retornados, and Diferencia bars emphasized together instead of emphasizing one metric series across every product.
  - Allowed edit candidates: `frontend/src/app.tsx`, `frontend/src/app.test.tsx`.
  - Checks: focused/full frontend tests, production build, whitespace check.
  - Evidence: writer and independent verification passed with 25 frontend tests, production build, and whitespace checks. `ProductBars` emits item-level `emphasis.focus: [productIndex]` across all three metric series, retains the axis tooltip, and removes series-wide focus only from the product chart. Type safety uses a narrow local datum plus an isolated `unknown` boundary; no broad `any` or client arithmetic was introduced. Real-browser hover remains unverified.
  - Commit: frontend work unit `fix: focus reconciliation hover by product`.

## Progress
- 2026-09-21: User requested three refinements: hide unavailable temporal evolution, count audited items absent from the selected CC system list, and add category/product filtering.
- 2026-09-21: Read-only mapping confirmed temporal availability is already server-owned; cross-CC matches currently collapse into a generic quality metric; the real hierarchy is Rubro → Categoría → Producto.
- 2026-09-21: User clarified that no alternate CC should be inferred or shown. Any audited item outside the selected CC system list should enter one review category for assignment correction or asset creation.
- 2026-09-21: RDR-01 implemented and verified with 22 frontend tests. Temporal evolution is absent unless the backend marks it available.
- 2026-09-21: RDR-02 implemented and verified. One operational metric now counts selected-CC system omissions without alternate-CC inference or disclosure.
- 2026-09-21: Split the hierarchy work into backend and frontend units. Unmatched audit evidence remains outside hierarchy grouping because assigning rubro/category/product would fabricate source data.
- 2026-09-21: RDR-03 implemented and verified. The existing endpoint now exposes deterministic category options and a bounded product chart grouped before pagination.
- 2026-09-21: RDR-04 implemented and writer-verified. The UI now supports Rubro → Categoría → Producto with server pagination and no client reconciliation arithmetic.
- 2026-09-21: RDR-05 independent verification passed after one documentation correction. No actionable implementation defect remains.
- 2026-09-21: User authorized two local work units: backend contract/tests/docs in `f5c07c1`, followed by the frontend experience/tests/styles and this tracker in `feat: improve reconciliation dashboard detail`. Unrelated favicon/index changes remain outside both commits.
- 2026-09-21: User accepted the production rollout, then requested product-oriented hover: one product row should retain all three metric bars together.
- 2026-09-21: RDR-06 implemented and independently verified. Product hover now focuses the same data index across all three metric series; no actionable finding remains.

## Next step
Await explicit commit authorization, then push/deploy separately if requested. Keep unrelated user-owned favicon/index changes outside this work unit.
