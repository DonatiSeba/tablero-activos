# n8n / SharePoint automation handoff contract

This is an integration contract only. This repository does not run, configure,
or depend on n8n, SharePoint, Microsoft Entra, Hermes, or a browser session.
Automation must not join the private application network; it calls the public
HTTPS hostname.

## Identity and transport

- The workflow must use a dedicated external least-privilege identity, scoped
  only to the SharePoint source/library and this import action. It must not use
  a browser cookie, a local administrator password, an administrator account,
  or any shared human account.
- Use `https://activos.tisico-sa.com` with normal certificate validation. Do
  not call container addresses, HTTP, or bypass TLS verification.
- The current application has cookie-session authentication intended for people;
  it does **not** provide an automation credential. Before any workflow is
  enabled, a future approved machine-auth design is required (for example,
  separately issued and revocable service credentials with narrowly scoped
  import permissions, rotation, audit attribution, rate limiting, and explicit
  CSRF/session separation). Do not work around that gap by reusing admin
  browser credentials.

## Multipart requests after machine authentication exists

For a system report, send:

```text
POST /api/imports/system
Content-Type: multipart/form-data
file=@<SharePoint-downloaded-workbook>.xlsx
report_date=YYYY-MM-DD
```

For a physical audit report, send:

```text
POST /api/imports/audit
Content-Type: multipart/form-data
file=@<SharePoint-downloaded-workbook>.xlsx
report_date=YYYY-MM-DD
cost_center_code=<existing explicit cost-center code>
```

The workflow must stream/download only the intended `.xlsx` item, preserve the
report date and audit cost-center from an approved workflow field (never infer
them silently), and keep workbook bytes out of workflow logs. Application size
limits and validation remain authoritative.

## Retry and duplicate treatment

Use bounded retries only for transport failures, TLS/transient gateway failures,
and explicitly retryable 5xx responses. Use capped exponential backoff with
jitter, a finite attempt count, and an alert/dead-letter outcome after
exhaustion; operations must choose the actual limits. Do not retry 4xx
validation/authorization errors.

A `409` response with `duplicate_sha256` means that identical immutable
workbook content was already accepted or is present as an existing import. It
is a terminal idempotency outcome, not a reason to upload indefinitely. Record
it as duplicate/no-new-import and notify the designated operator if the
workflow expected a new report. The workflow should treat a successful `201`
or this duplicate result according to its approved source-processing policy;
it must never delete or overwrite SharePoint evidence based solely on an HTTP
attempt.
