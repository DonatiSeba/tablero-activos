import { FormEvent, useEffect, useState } from "react";

export type Role = "viewer" | "editor" | "admin";
export type CurrentUser = { id: string; username: string; display_name: string; role: Role };
type ApiError = { message: string; status?: number };
type Page = { limit: number; offset: number; has_more: boolean; total_count: number };
type CostCenter = { code: string; name: string };
type Source = { source: "system" | "audit"; available: boolean; batch_id: string | null; report_date: string | null };
type Summary = {
  cost_center: CostCenter;
  latest_sources: { system: Source; audit: Source };
  freshness: { warning: boolean; status: string; message: string | null };
  metrics: Record<string, number | null>;
};
type SummariesResponse = { summaries: Summary[]; page: Page; selection_rule: string; metric_scope: string };
type DrilldownResponse = {
  cost_center: CostCenter | null; source: Source; page: Page;
  groups: { rubro: string | null; categories: { category: string | null; products: { product: string | null; observation_count: number; distinct_asset_count: number; status_counts: { status: string | null; count: number }[] }[] }[] }[];
};
type ImportHistory = { items: { batch_id: string; source: string; cost_center: CostCenter; report_date: string; imported_at: string; imported_by_display_name: string | null; row_count: number; status: string; warning_counts: Record<string, number>; processing_counts: Record<string, number> }[]; page: Page };
type ReviewQueue = { items: { id: string; category: string; cost_center: CostCenter; asset: { id: string; code: string | null } | null; source: { report_date: string }; reason: string; inference?: string }[]; queue_counts: Record<string, number>; page: Page };
type CurrentStates = { states: { asset_id: string; asset_code: string; cost_center: CostCenter; state: string; reason: string; marker: { column: number; category: string; raw_value: string | null }; source_report_date: string; projection_version: string }[] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, credentials: "include" });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw { message: body?.detail || `Request failed (${response.status})`, status: response.status } satisfies ApiError;
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function ErrorNotice({ error }: { error: string | null }) {
  return error ? <p className="notice error" role="alert">{error}</p> : null;
}
function Empty({ children }: { children: React.ReactNode }) { return <p className="empty">{children}</p>; }
function Metric({ label, value }: { label: string; value: number | null }) { return <div className="metric"><dt>{label}</dt><dd>{value ?? "Unavailable"}</dd></div>; }
function date(value: string | null) { return value || "Unavailable"; }
function label(value: string | null) { return value || "Unspecified"; }

function Dashboard() {
  const [data, setData] = useState<SummariesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [drilldown, setDrilldown] = useState<DrilldownResponse | null>(null);
  const [drilldownError, setDrilldownError] = useState<string | null>(null);
  useEffect(() => { request<SummariesResponse>("/dashboard/summaries").then(setData).catch((e: ApiError) => setError(e.message)); }, []);
  function showDrilldown(code: string) {
    setSelectedCode(code); setDrilldown(null); setDrilldownError(null);
    request<DrilldownResponse>(`/dashboard/system-drilldown?cost_center_code=${encodeURIComponent(code)}`).then(setDrilldown).catch((e: ApiError) => setDrilldownError(e.message));
  }
  return <section aria-labelledby="dashboard-heading">
    <h2 id="dashboard-heading">Executive dashboard</h2>
    <p className="muted">All counts and source selection are calculated by the server.</p>
    <ErrorNotice error={error} />
    {!data && !error && <p role="status">Loading dashboard summaries…</p>}
    {data?.summaries.length === 0 && <Empty>No cost centers are available for this session.</Empty>}
    <div className="summary-grid">
      {data?.summaries.map((summary) => <article className="summary-card" key={summary.cost_center.code}>
        <header><h3>{summary.cost_center.code} — {summary.cost_center.name}</h3><button type="button" onClick={() => showDrilldown(summary.cost_center.code)}>View system drill-down</button></header>
        <dl className="sources"><div><dt>System report</dt><dd>{date(summary.latest_sources.system.report_date)}</dd></div><div><dt>Audit report</dt><dd>{date(summary.latest_sources.audit.report_date)}</dd></div></dl>
        {summary.freshness.warning && <p className="notice warning" role="status"><strong>Freshness warning:</strong> {summary.freshness.message}</p>}
        <dl className="metrics">
          <Metric label="Current system assets" value={summary.metrics.current_system_distinct_asset_count} /><Metric label="Found" value={summary.metrics.found_count} />
          <Metric label="Authorized audit L returns" value={summary.metrics.returned_count} /><Metric label="Review required" value={summary.metrics.review_required_count} />
          <Metric label="Unresolved audit cases" value={summary.metrics.unresolved_audit_case_count} /><Metric label="Pending / not accounted" value={summary.metrics.pending_not_accounted_count} />
        </dl>
      </article>)}
    </div>
    {data && <p className="muted small">{data.selection_rule}</p>}
    {selectedCode && <section className="drilldown" aria-labelledby="drilldown-heading"><h3 id="drilldown-heading">System drill-down: {selectedCode}</h3><ErrorNotice error={drilldownError} />
      {!drilldown && !drilldownError && <p role="status">Loading grouped system data…</p>}
      {drilldown?.groups.length === 0 && <Empty>No selected system evidence is available for this cost center.</Empty>}
      {drilldown?.groups.map((rubro) => <section className="group" key={String(rubro.rubro)}><h4>Rubro: {label(rubro.rubro)}</h4>{rubro.categories.map((category) => <div key={String(category.category)}><h5>Category: {label(category.category)}</h5><ul>{category.products.map((product) => <li key={String(product.product)}><strong>{label(product.product)}</strong>: {product.observation_count} observations, {product.distinct_asset_count} distinct assets. Statuses: {product.status_counts.map((item) => `${label(item.status)} (${item.count})`).join(", ") || "None"}.</li>)}</ul></div>)}</section>)}
    </section>}
  </section>;
}

function Operations() {
  const [history, setHistory] = useState<ImportHistory | null>(null); const [queue, setQueue] = useState<ReviewQueue | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { Promise.all([request<ImportHistory>("/operations/import-history"), request<ReviewQueue>("/operations/review-queue")]).then(([h, q]) => { setHistory(h); setQueue(q); }).catch((e: ApiError) => setError(e.message)); }, []);
  return <section aria-labelledby="operations-heading"><h2 id="operations-heading">Operations</h2><ErrorNotice error={error} />{!history && !error && <p role="status">Loading operational records…</p>}
    <section aria-labelledby="history-heading"><h3 id="history-heading">Import history</h3>{history?.items.length === 0 && <Empty>No imports match this view.</Empty>}<div className="table-scroll"><table><thead><tr><th>Source</th><th>Cost center</th><th>Report date</th><th>Rows</th><th>Status</th><th>Imported by</th></tr></thead><tbody>{history?.items.map((item) => <tr key={item.batch_id}><td>{item.source}</td><td>{item.cost_center.code}</td><td>{item.report_date}</td><td>{item.row_count}</td><td><span className="status">{item.status}</span></td><td>{item.imported_by_display_name || "Unknown"}</td></tr>)}</tbody></table></div></section>
    <section aria-labelledby="queue-heading"><h3 id="queue-heading">Review queue</h3>{queue && <p className="muted">Server queue: {queue.queue_counts.total} total; no resolution command is available in this application.</p>}{queue?.items.length === 0 && <Empty>No items require review.</Empty>}<ul className="queue">{queue?.items.map((item) => <li key={item.id}><strong>{item.category.replaceAll("_", " ")}</strong> — {item.cost_center.code}{item.asset ? `, asset ${item.asset.code || "unspecified"}` : ""}; {item.reason}. {item.inference}</li>)}</ul></section>
  </section>;
}

function CurrentStateList() {
  const [data, setData] = useState<CurrentStates | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { request<CurrentStates>("/current-states").then(setData).catch((e: ApiError) => setError(e.message)); }, []);
  return <section aria-labelledby="states-heading"><h2 id="states-heading">Current states</h2><p className="muted">Audit column-L returns are authorized post-audit inferences, not warehouse receipts.</p><ErrorNotice error={error} />{!data && !error && <p role="status">Loading current states…</p>}{data?.states.length === 0 && <Empty>No current-state projections are available.</Empty>}<div className="table-scroll"><table><thead><tr><th>Asset</th><th>Cost center</th><th>State</th><th>Audit date</th><th>Reason</th></tr></thead><tbody>{data?.states.map((item) => <tr key={item.asset_id}><td>{item.asset_code}</td><td>{item.cost_center.code}</td><td><span className="status">{item.state}</span></td><td>{item.source_report_date}</td><td>{item.reason}</td></tr>)}</tbody></table></div></section>;
}

function Uploads() {
  const [message, setMessage] = useState<string | null>(null); const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>, endpoint: "/imports/system" | "/imports/audit") {
    event.preventDefault(); setError(null); setMessage(null); setBusy(true);
    try { const result = await request<{ source: string; row_count: number }>(endpoint, { method: "POST", body: new FormData(event.currentTarget) }); setMessage(`${result.source} import accepted with ${result.row_count} rows.`); event.currentTarget.reset(); }
    catch (e) { setError((e as ApiError).message); } finally { setBusy(false); }
  }
  return <section aria-labelledby="uploads-heading"><h2 id="uploads-heading">Evidence uploads</h2><p className="muted">Editors and administrators can submit source workbooks. Server validation determines acceptance and matching.</p><p className="notice" role="status" aria-live="polite">{message}</p><ErrorNotice error={error} /><div className="upload-grid">
    <form onSubmit={(event) => submit(event, "/imports/system")}><h3>System report</h3><label>Workbook <input name="file" type="file" accept=".xlsx" required /></label><label>Report date <input name="report_date" type="date" required /></label><button disabled={busy}>{busy ? "Uploading…" : "Upload system report"}</button></form>
    <form onSubmit={(event) => submit(event, "/imports/audit")}><h3>Physical audit</h3><label>Workbook <input name="file" type="file" accept=".xlsx" required /></label><label>Report date <input name="report_date" type="date" required /></label><label>Cost center code <input name="cost_center_code" required /></label><button disabled={busy}>{busy ? "Uploading…" : "Upload audit"}</button></form>
  </div></section>;
}

export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null); const [sessionLoading, setSessionLoading] = useState(true); const [sessionError, setSessionError] = useState<string | null>(null); const [view, setView] = useState("dashboard");
  useEffect(() => { request<CurrentUser>("/auth/me").then(setUser).catch((e: ApiError) => { if (e.status !== 401) setSessionError(e.message); }).finally(() => setSessionLoading(false)); }, []);
  async function login(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setSessionError(null); const form = new FormData(event.currentTarget); try { const loggedIn = await request<CurrentUser>("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) }); setUser(loggedIn); event.currentTarget.reset(); } catch (e) { setSessionError((e as ApiError).message); } }
  async function logout() { try { await request<void>("/auth/logout", { method: "POST" }); } catch (e) { setSessionError((e as ApiError).message); } finally { setUser(null); setView("dashboard"); } }
  if (sessionLoading) return <main className="application-shell"><p role="status">Checking session…</p></main>;
  if (!user) return <main className="login-shell"><section className="login-card" aria-labelledby="login-heading"><p className="eyebrow">Asset reconciliation</p><h1 id="login-heading">Sign in</h1><p>Use your local account. Credentials are sent only to the same-origin session API.</p><form onSubmit={login}><label>Username <input name="username" autoComplete="username" required /></label><label>Password <input name="password" type="password" autoComplete="current-password" required /></label><button>Sign in</button></form><ErrorNotice error={sessionError} /></section></main>;
  const canUpload = user.role === "editor" || user.role === "admin";
  return <div className="app"><header className="topbar"><div><p className="eyebrow">Asset reconciliation</p><strong>{user.display_name}</strong> <span className="status">{user.role}</span></div><button type="button" onClick={logout}>Sign out</button></header><nav aria-label="Application"><button className={view === "dashboard" ? "active" : ""} onClick={() => setView("dashboard")}>Dashboard</button><button className={view === "operations" ? "active" : ""} onClick={() => setView("operations")}>Operations</button><button className={view === "states" ? "active" : ""} onClick={() => setView("states")}>Current states</button>{canUpload && <button className={view === "uploads" ? "active" : ""} onClick={() => setView("uploads")}>Uploads</button>}</nav><main className="content">{view === "dashboard" && <Dashboard />}{view === "operations" && <Operations />}{view === "states" && <CurrentStateList />}{view === "uploads" && canUpload && <Uploads />}</main></div>;
}
