# Import History Navigation

## Objective
Remove the currently unused Operations page and place import history alongside authorized import forms.

## Product decisions
- Remove Operations from application navigation.
- Do not render or request the review queue for now.
- Render import history below the system/audit upload forms in Importaciones.
- Keep Importaciones restricted to EDITOR and ADMIN.
- Refresh history after a successful import.

## Constraints
- Preserve backend endpoints, authentication, RBAC, upload semantics, error localization, mobile navigation, and existing dashboard behavior.
- History-loading failures must not disable authorized upload forms.
- No backend changes or database migration.
- No commit, push, or deployment without explicit user authorization.

## Tasks

- [x] IHN-01 Consolidate import history into Importaciones.
  - Allowed edit candidates: `frontend/src/app.tsx`, `frontend/src/app.test.tsx`, `frontend/src/styles.css` only if required.
  - Outcome: Operations is absent; authorized users see upload forms and import history together; history reloads after accepted uploads.
  - Checks: focused/full frontend tests, production build, whitespace check.
  - Evidence: writer and independent verification passed with 30 frontend tests, production build, and whitespace checks. Operations navigation/component and review-queue requests were removed. Importaciones now contains both authorized upload forms and the localized history table; accepted uploads refresh history while preserving success messages, and history failures remain isolated from form availability.
  - Commit: frontend work unit `feat: move import history into imports`.

- [x] IHN-02 Independently verify navigation, RBAC, and import behavior.
  - Outcome: viewers cannot access Importaciones; editors/admins retain uploads and history; no Operations/review-queue request remains.
  - Evidence: independent PASS. Viewer exclusion and editor/admin access remain correct; no backend files or contracts changed. History responses are protected by active-instance and monotonic request-version guards against stale/unmounted updates. Real-browser file-picker, screen-reader, and responsive layout checks remain gaps; Vite retains the 1,220.54 kB chunk warning.

## Progress
- 2026-09-21: User said Operations is not useful for now and requested moving import history into Importaciones.
- 2026-09-21: Read-only inspection confirmed Operations currently combines import history and review queue, while Importaciones contains only the two authorized upload forms.
- 2026-09-21: IHN-01 implemented and IHN-02 independently passed. Operations/review queue are absent, and import history now lives below the upload forms with safe refresh/error isolation.

## Next step
Await explicit commit authorization, then push/deploy separately if requested.
