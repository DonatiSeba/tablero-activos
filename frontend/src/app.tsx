import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";

export type Role = "viewer" | "editor" | "admin";
export type CurrentUser = { id: string; username: string; display_name: string; role: Role };
type ApiError = { status?: number };
type Page = { limit: number; offset: number; has_more: boolean; total_count: number };
type CostCenter = { code: string; name: string };
type Source = { source: "system" | "audit"; available: boolean; batch_id: string | null; report_date: string | null };
type Freshness = { warning: boolean; status: string; message: string | null };
type ExecutiveMetrics = {
  system_count: number | null;
  found_in_cost_center_count: number | null;
  returned_count: number | null;
  accounted_count: number | null;
  difference_count: number | null;
  coverage_percent: number | null;
};
type OperationalIssues = {
  physical_patrimonial_difference_count: number | null;
  system_update_required_return_count: number | null;
  system_data_quality_omission_count: number | null;
  review_required_count: number | null;
  unresolved_audit_case_count: number | null;
};
type DonutChart = { available: boolean; reason?: string | null; segments: { key: string; value: number }[] };
type TimeEvolution = {
  available: boolean;
  reason?: string | null;
  points: { report_date: string; system_count: number; found_in_cost_center_count: number; audit_snapshot_difference_count: number }[];
  return_evolution: { available: boolean; reason?: string | null; points: unknown[] };
};
type Summary = {
  cost_center: CostCenter;
  latest_sources: { system: Source; audit: Source };
  freshness: Freshness;
  executive_metrics: ExecutiveMetrics;
  operational_issues: OperationalIssues;
  charts: { general_status_donut: DonutChart; time_evolution: TimeEvolution };
};
type SummariesResponse = { summaries: Summary[]; page: Page; selection_rule: string; metric_scope: string };
type ReconciliationMetrics = ExecutiveMetrics;
type DrilldownResponse = {
  cost_center: CostCenter | null;
  source: Source;
  audit_source: Source;
  executive_metrics?: ExecutiveMetrics;
  operational_issues?: OperationalIssues;
  page: Page;
  groups: { rubro: string | null; reconciliation_metrics: ReconciliationMetrics; categories: { category: string | null; reconciliation_metrics: ReconciliationMetrics; products: { product: string | null; observation_count: number; distinct_asset_count: number; status_counts: { status: string | null; count: number }[]; reconciliation_metrics: ReconciliationMetrics }[] }[] }[];
  charts: {
    primary_stacked_bar: { available: boolean; reason?: string | null; scope?: string; series: { key: "found_in_cost_center_count" | "returned_count" | "difference_count"; label: string }[]; items: ({ rubro: string | null; category: string | null } & ExecutiveMetrics)[] };
    general_status_donut: DonutChart;
  };
};
type ImportHistory = { items: { batch_id: string; source: string; cost_center: CostCenter; report_date: string; imported_at: string; imported_by_display_name: string | null; row_count: number; status: string; warning_counts: Record<string, number>; processing_counts: Record<string, number> }[]; page: Page };
type ReviewQueue = { items: { id: string; category: string; cost_center: CostCenter; asset: { id: string; code: string | null } | null; source: { report_date: string }; reason: string; inference?: string }[]; queue_counts: Record<string, number>; page: Page };
type CurrentStates = { states: { asset_id: string; asset_code: string; cost_center: CostCenter; state: string; reason: string; marker: { column: number; category: string; raw_value: string | null }; source_report_date: string; projection_version: string }[] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, credentials: "include" });
  if (!response.ok) throw { status: response.status } satisfies ApiError;
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function publicError(error: ApiError) {
  if (error.status === 401) return "La sesión no está disponible. Inicie sesión nuevamente.";
  if (error.status === 403) return "No tiene permiso para realizar esta acción.";
  return "No se pudo completar la solicitud. Intente nuevamente.";
}
function ErrorNotice({ error }: { error: string | null }) { return error ? <p className="notice error" role="alert">{error}</p> : null; }
function Empty({ children }: { children: ReactNode }) { return <p className="empty">{children}</p>; }
function date(value: string | null) { return value || "Sin fecha informada"; }
function number(value: number | null) { return value === null ? "No disponible" : new Intl.NumberFormat("es-AR").format(value); }
function percentage(value: number | null) { return value === null ? "No disponible" : `${new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(value)} %`; }
function hierarchyLabel(value: string | null, level: "rubro" | "categoría" | "producto" | "estado") {
  const emptyLabels = { rubro: "Sin rubro asignado", categoría: "Sin categoría asignada", producto: "Sin producto asignado", estado: "Sin estado informado" };
  return value || emptyLabels[level];
}
function roleLabel(role: Role) { return { viewer: "Consulta", editor: "Editor", admin: "Administrador" }[role]; }

const metricScopeLabels: Record<string, string> = {
  "Status and pending metrics are distinct assets in the selected system batch; audit states are projections whose provenance is the selected audit batch. Executive KPI and chart values are calculated only on the server.": "Los estados y las diferencias se calculan sobre activos distintos del lote de sistema seleccionado. Los estados de auditoría son proyecciones del lote de auditoría seleccionado. Los KPI y gráficos se calculan únicamente en el servidor.",
};
const sourceLabels: Record<string, string> = { system: "Sistema", audit: "Auditoría", return: "Retorno" };
const importStatusLabels: Record<string, string> = { completed: "Completada", rejected: "Rechazada", failed: "Con errores" };
const reviewCategoryLabels: Record<string, string> = { unresolved_identifier: "Identificador sin resolver", review_required_return: "Retorno que requiere revisión" };
const stateLabels: Record<string, string> = {
  Active: "Activo", active: "Activo", Inactive: "Inactivo", inactive: "Inactivo", Retired: "Retirado", retired: "Retirado", in_service: "En servicio",
  found: "Encontrado en el centro de costo", returned: "Retornado", review_required: "Requiere revisión", pending: "Pendiente", matched: "Conciliado", mismatched: "No conciliado",
};
const reasonLabels: Record<string, string> = {
  missing_identifier: "Falta el identificador del activo.",
  no_normalized_candidate: "No se encontró un activo candidato con el identificador normalizado.",
  ambiguous_normalized_candidate: "El identificador normalizado coincide con más de un activo.",
  authorized_post_audit_column_l_return_marker: "La marca de retorno de la columna L fue reconocida después de la auditoría; no constituye una recepción de almacén.",
  ambiguous_column_l_return_marker_requires_review: "La marca de retorno de la columna L es ambigua y requiere revisión.",
  resolved_audit_presence_without_recognized_return_marker: "El activo fue encontrado en la auditoría sin una marca de retorno reconocida.",
};
const chartLabels: Record<string, string> = { found_in_cost_center: "Encontrados en CC", returned: "Retornados", difference: "Diferencia pendiente" };

function metricScopeLabel(scope: string) { return metricScopeLabels[scope] || "Los KPI y gráficos se calculan únicamente en el servidor a partir de la evidencia seleccionada."; }
function sourceLabel(source: string) { return sourceLabels[source] || "Fuente no reconocida"; }
function importStatusLabel(status: string) { return importStatusLabels[status] || "Estado de importación no reconocido"; }
function reviewCategoryLabel(category: string) { return reviewCategoryLabels[category] || "Categoría de revisión no reconocida"; }
function stateLabel(state: string | null) { return state === null ? hierarchyLabel(state, "estado") : stateLabels[state] || "Estado no reconocido"; }
function reasonLabel(reason: string | null | undefined) { return reason ? reasonLabels[reason] || "El motivo informado no está reconocido." : "Sin motivo informado."; }
function chartLabel(key: string) { return chartLabels[key] || "Serie no reconocida"; }
function chartReason(reason?: string | null) {
  if (reason === "system_and_audit_evidence_required") return "Se requieren evidencias vigentes de sistema y auditoría para este gráfico.";
  if (reason === "fewer_than_two_comparable_snapshots") return "Aún no hay dos instantáneas comparables para mostrar una evolución.";
  if (reason === "return_event_time_evidence_unavailable") return "La evolución de retornos no está disponible porque no existe evidencia temporal de esos eventos.";
  return "La información para este gráfico no está disponible.";
}
function freshnessText(freshness: Freshness) {
  if (freshness.status === "report_dates_differ") return "Las fechas de sistema y auditoría no coinciden; no representan un corte común.";
  if (freshness.status === "missing_system") return "No hay evidencia vigente de sistema para comparar el corte.";
  if (freshness.status === "missing_audit") return "No hay evidencia vigente de auditoría para comparar el corte.";
  if (freshness.status === "missing_both") return "No hay evidencia vigente de sistema ni de auditoría para comparar el corte.";
  return "Las fuentes requieren atención antes de comparar el corte.";
}
function statusLabel(status: string | null) { return stateLabel(status); }

function EChart({ option, ariaLabel }: { option: EChartsOption; ariaLabel: string }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current, undefined, { renderer: "svg" });
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [option]);
  return <div className="chart" role="img" aria-label={ariaLabel} ref={element} />;
}

function Metric({ label, value, tone = "blue" }: { label: string; value: number | null; tone?: "blue" | "green" | "cyan" | "red" | "yellow" }) {
  return <div className={`metric metric-${tone}`}><dt>{label}</dt><dd>{number(value)}</dd></div>;
}
function Kpis({ metrics }: { metrics: ExecutiveMetrics }) {
  return <dl className="metrics">
    <Metric label="En sistema" value={metrics.system_count} />
    <Metric label="Encontrados en CC" value={metrics.found_in_cost_center_count} tone="green" />
    <Metric label="Retornados" value={metrics.returned_count} tone="cyan" />
    <Metric label="Contabilizados" value={metrics.accounted_count} tone="green" />
    <Metric label="Diferencia pendiente" value={metrics.difference_count} tone="red" />
    <div className="metric metric-yellow"><dt>Cobertura</dt><dd>{percentage(metrics.coverage_percent)}</dd></div>
  </dl>;
}
function Donut({ chart }: { chart: DonutChart }) {
  if (!chart.available) return <Empty>{chartReason(chart.reason)}</Empty>;
  const colors: Record<string, string> = { found_in_cost_center: "#17855f", returned: "#168aad", difference: "#c74545" };
  return <EChart ariaLabel="Distribución general de conciliación" option={{
    tooltip: { trigger: "item", valueFormatter: (value) => number(Number(value)) },
    color: chart.segments.map((segment) => colors[segment.key] || "#627587"),
    series: [{ type: "pie", radius: ["56%", "78%"], avoidLabelOverlap: true, label: { formatter: "{b}\n{d}%" }, data: chart.segments.map((segment) => ({ name: chartLabel(segment.key), value: segment.value })) }],
  }} />;
}
function StackedBars({ chart }: { chart: DrilldownResponse["charts"]["primary_stacked_bar"] }) {
  if (!chart.available) return <Empty>{chartReason(chart.reason)}</Empty>;
  const colors: Record<string, string> = { found_in_cost_center_count: "#17855f", returned_count: "#168aad", difference_count: "#c74545" };
  return <EChart ariaLabel="Barras apiladas de conciliación por categoría" option={{
    color: chart.series.map((series) => colors[series.key] || "#627587"),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { bottom: 0, data: chart.series.map((series) => chartLabel(series.label)) },
    grid: { left: 16, right: 16, top: 24, bottom: 52, containLabel: true },
    xAxis: { type: "value", minInterval: 1 },
    yAxis: { type: "category", data: chart.items.map((item) => `${hierarchyLabel(item.rubro, "rubro")} · ${hierarchyLabel(item.category, "categoría")}`) },
    series: chart.series.map((series) => ({ name: chartLabel(series.label), type: "bar", stack: "conciliación", emphasis: { focus: "series" }, data: chart.items.map((item) => item[series.key]) })),
  }} />;
}
function Evolution({ chart }: { chart: TimeEvolution }) {
  if (!chart.available) return <Empty>{chartReason(chart.reason)}</Empty>;
  return <>
    <EChart ariaLabel="Evolución temporal de las instantáneas comparables" option={{
      color: ["#245da6", "#c74545"],
      tooltip: { trigger: "axis" },
      legend: { bottom: 0, data: ["En sistema", "Diferencia de instantánea"] },
      grid: { left: 16, right: 16, top: 24, bottom: 50, containLabel: true },
      xAxis: { type: "category", boundaryGap: false, data: chart.points.map((point) => point.report_date) },
      yAxis: { type: "value", minInterval: 1 },
      series: [
        { name: "En sistema", type: "line", smooth: true, data: chart.points.map((point) => point.system_count) },
        { name: "Diferencia de instantánea", type: "line", smooth: true, data: chart.points.map((point) => point.audit_snapshot_difference_count) },
      ],
    }} />
    {!chart.return_evolution.available && <p className="notice return-evolution-notice" role="status"><strong>Evolución de retornos no disponible:</strong> {chartReason(chart.return_evolution.reason)}</p>}
  </>;
}

function SourceDates({ system, audit, freshness }: { system: Source; audit: Source; freshness: Freshness }) {
  return <>
    <dl className="sources"><div><dt>Reporte de sistema</dt><dd>{date(system.report_date)}</dd></div><div><dt>Reporte de auditoría</dt><dd>{date(audit.report_date)}</dd></div></dl>
    {freshness.warning && <p className="notice warning" role="status"><strong>Advertencia de vigencia:</strong> {freshnessText(freshness)}</p>}
  </>;
}
function OperationalIssues({ issues }: { issues: OperationalIssues }) {
  return <section className="issues" aria-labelledby="issues-heading"><h3 id="issues-heading">Inconsistencias operativas</h3><div className="issue-grid">
    <Metric label="Diferencia física o patrimonial" value={issues.physical_patrimonial_difference_count} tone="red" />
    <Metric label="Retornos pendientes de actualización" value={issues.system_update_required_return_count} tone="cyan" />
    <Metric label="Casos pendientes de revisión" value={issues.review_required_count} tone="yellow" />
    <Metric label="Casos de auditoría sin resolver" value={issues.unresolved_audit_case_count} tone="yellow" />
    <Metric label="Omisiones de calidad del sistema" value={issues.system_data_quality_omission_count} tone="yellow" />
  </div></section>;
}

function Dashboard() {
  const [data, setData] = useState<SummariesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [drilldown, setDrilldown] = useState<DrilldownResponse | null>(null);
  const [drilldownError, setDrilldownError] = useState<string | null>(null);
  useEffect(() => { request<SummariesResponse>("/dashboard/summaries").then(setData).catch((e: ApiError) => setError(publicError(e))); }, []);
  function showDrilldown(code: string) {
    setSelectedCode(code); setDrilldown(null); setDrilldownError(null);
    request<DrilldownResponse>(`/dashboard/system-drilldown?cost_center_code=${encodeURIComponent(code)}`).then(setDrilldown).catch((e: ApiError) => setDrilldownError(publicError(e)));
  }
  return <section aria-labelledby="dashboard-heading">
    <div className="page-heading"><div><p className="eyebrow">Dirección ejecutiva</p><h1 id="dashboard-heading">Control de activos</h1><p className="muted">Resumen de conciliación calculado y seleccionado por el servidor.</p></div></div>
    <ErrorNotice error={error} />
    {!data && !error && <p role="status" className="loading">Cargando resumen ejecutivo…</p>}
    {data?.summaries.length === 0 && <Empty>No hay centros de costo disponibles para esta sesión.</Empty>}
    <div className="summary-grid">
      {data?.summaries.map((summary) => <article className="summary-card" key={summary.cost_center.code}>
        <header><div><p className="card-overline">Centro de costo {summary.cost_center.code}</p><h2>{summary.cost_center.name}</h2></div><button className="button-secondary" type="button" onClick={() => showDrilldown(summary.cost_center.code)}>Ver análisis</button></header>
        <SourceDates system={summary.latest_sources.system} audit={summary.latest_sources.audit} freshness={summary.freshness} />
        <Kpis metrics={summary.executive_metrics} />
        <div className="summary-chart"><h3>Estado general</h3><Donut chart={summary.charts.general_status_donut} /></div>
        <div className="summary-chart"><h3>Evolución temporal</h3><Evolution chart={summary.charts.time_evolution} /></div>
      </article>)}
    </div>
    {data?.page.has_more && <p className="notice" role="status">Hay más centros de costo disponibles en el servidor. Esta vista muestra la página actual.</p>}
    {data && <p className="muted small">{metricScopeLabel(data.metric_scope)}</p>}
    {selectedCode && <section className="drilldown panel" aria-labelledby="drilldown-heading"><div className="panel-heading"><div><p className="eyebrow">Detalle agrupado</p><h2 id="drilldown-heading">Conciliación por rubro y categoría: CC {selectedCode}</h2></div></div><ErrorNotice error={drilldownError} />
      {!drilldown && !drilldownError && <p role="status" className="loading">Cargando datos agrupados…</p>}
      {drilldown && !drilldown.cost_center && <Empty>No se encontró el centro de costo seleccionado.</Empty>}
      {drilldown?.executive_metrics && <Kpis metrics={drilldown.executive_metrics} />}
      {drilldown?.operational_issues && <OperationalIssues issues={drilldown.operational_issues} />}
      {drilldown && <div className="chart-grid"><section className="chart-panel"><h3>Conciliación por categoría</h3><StackedBars chart={drilldown.charts.primary_stacked_bar} /></section><section className="chart-panel"><h3>Composición del estado</h3><Donut chart={drilldown.charts.general_status_donut} /></section></div>}
      {drilldown?.groups.length === 0 && <Empty>No hay evidencia de sistema agrupada para este centro de costo.</Empty>}
      {drilldown?.groups.map((rubro) => <section className="group" key={String(rubro.rubro)}><h3>Rubro: {hierarchyLabel(rubro.rubro, "rubro")}</h3><dl className="group-metrics"><Metric label="En sistema" value={rubro.reconciliation_metrics.system_count} /><Metric label="Diferencia" value={rubro.reconciliation_metrics.difference_count} tone="red" /></dl>{rubro.categories.map((category) => <div className="category" key={String(category.category)}><h4>Categoría: {hierarchyLabel(category.category, "categoría")}</h4><ul>{category.products.map((product) => <li key={String(product.product)}><strong>{hierarchyLabel(product.product, "producto")}</strong><span>{number(product.distinct_asset_count)} activos distintos · {number(product.observation_count)} observaciones</span><span className="muted">Estados: {product.status_counts.map((item) => `${statusLabel(item.status)} (${number(item.count)})`).join(", ") || "Sin estados informados"}</span></li>)}</ul></div>)}</section>)}
      {drilldown?.page.has_more && <p className="notice" role="status">Hay más grupos disponibles en el servidor. Los gráficos reflejan únicamente la página agrupada actual.</p>}
    </section>}
  </section>;
}

function Operations() {
  const [history, setHistory] = useState<ImportHistory | null>(null); const [queue, setQueue] = useState<ReviewQueue | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { Promise.all([request<ImportHistory>("/operations/import-history"), request<ReviewQueue>("/operations/review-queue")]).then(([h, q]) => { setHistory(h); setQueue(q); }).catch((e: ApiError) => setError(publicError(e))); }, []);
  return <section aria-labelledby="operations-heading"><div className="page-heading"><div><p className="eyebrow">Seguimiento</p><h1 id="operations-heading">Operaciones</h1></div></div><ErrorNotice error={error} />{!history && !error && <p role="status" className="loading">Cargando registros operativos…</p>}
    <section className="panel" aria-labelledby="history-heading"><h2 id="history-heading">Historial de importaciones</h2>{history?.items.length === 0 && <Empty>No hay importaciones para esta vista.</Empty>}<div className="table-scroll"><table><thead><tr><th>Fuente</th><th>Centro de costo</th><th>Fecha del reporte</th><th>Filas</th><th>Estado</th><th>Importado por</th></tr></thead><tbody>{history?.items.map((item) => <tr key={item.batch_id}><td>{sourceLabel(item.source)}</td><td>{item.cost_center.code}</td><td>{item.report_date}</td><td>{number(item.row_count)}</td><td><span className="status">{importStatusLabel(item.status)}</span></td><td>{item.imported_by_display_name || "No informado"}</td></tr>)}</tbody></table></div></section>
    <section className="panel" aria-labelledby="queue-heading"><h2 id="queue-heading">Cola de revisión</h2>{queue && <p className="muted">Casos informados por el servidor: {number(queue.queue_counts.total ?? null)}. Esta pantalla no resuelve casos.</p>}{queue?.items.length === 0 && <Empty>No hay elementos que requieran revisión.</Empty>}<ul className="queue">{queue?.items.map((item) => <li key={item.id}><strong>{reviewCategoryLabel(item.category)}</strong> — CC {item.cost_center.code}{item.asset ? `, activo ${item.asset.code || "sin código"}` : ""}. {reasonLabel(item.reason)}</li>)}</ul></section>
  </section>;
}

function CurrentStateList() {
  const [data, setData] = useState<CurrentStates | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { request<CurrentStates>("/current-states").then(setData).catch((e: ApiError) => setError(publicError(e))); }, []);
  return <section aria-labelledby="states-heading"><div className="page-heading"><div><p className="eyebrow">Trazabilidad</p><h1 id="states-heading">Estados actuales</h1><p className="muted">Los retornos de la columna L de auditoría son inferencias autorizadas posteriores a la auditoría, no recepciones de almacén.</p></div></div><ErrorNotice error={error} />{!data && !error && <p role="status" className="loading">Cargando estados actuales…</p>}{data?.states.length === 0 && <Empty>No hay proyecciones de estado actual disponibles.</Empty>}<div className="table-scroll"><table><thead><tr><th>Activo</th><th>Centro de costo</th><th>Estado</th><th>Fecha de auditoría</th><th>Motivo</th></tr></thead><tbody>{data?.states.map((item) => <tr key={item.asset_id}><td>{item.asset_code}</td><td>{item.cost_center.code}</td><td><span className="status">{stateLabel(item.state)}</span></td><td>{item.source_report_date}</td><td>{reasonLabel(item.reason)}</td></tr>)}</tbody></table></div></section>;
}

function Uploads() {
  const [message, setMessage] = useState<string | null>(null); const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>, endpoint: "/imports/system" | "/imports/audit") {
    event.preventDefault(); setError(null); setMessage(null); setBusy(true);
    try { const result = await request<{ source: string; row_count: number }>(endpoint, { method: "POST", body: new FormData(event.currentTarget) }); setMessage(`La importación de ${sourceLabel(result.source as Source["source"])} fue aceptada con ${number(result.row_count)} filas.`); event.currentTarget.reset(); }
    catch (e) { setError(publicError(e as ApiError)); } finally { setBusy(false); }
  }
  return <section aria-labelledby="uploads-heading"><div className="page-heading"><div><p className="eyebrow">Carga autorizada</p><h1 id="uploads-heading">Importar evidencia</h1><p className="muted">Los editores y administradores pueden enviar libros de origen. El servidor valida la aceptación y las coincidencias.</p></div></div><p className="notice" role="status" aria-live="polite">{message}</p><ErrorNotice error={error} /><div className="upload-grid">
    <form className="panel" onSubmit={(event) => submit(event, "/imports/system")}><h2>Reporte de sistema</h2><label>Libro de trabajo <input name="file" type="file" accept=".xlsx" required /></label><label>Fecha del reporte <input name="report_date" type="date" required /></label><button className="button-primary" disabled={busy}>{busy ? "Cargando…" : "Cargar reporte de sistema"}</button></form>
    <form className="panel" onSubmit={(event) => submit(event, "/imports/audit")}><h2>Auditoría física</h2><label>Libro de trabajo <input name="file" type="file" accept=".xlsx" required /></label><label>Fecha del reporte <input name="report_date" type="date" required /></label><label>Código de centro de costo <input name="cost_center_code" required /></label><button className="button-primary" disabled={busy}>{busy ? "Cargando…" : "Cargar auditoría"}</button></form>
  </div></section>;
}

export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null); const [sessionLoading, setSessionLoading] = useState(true); const [sessionError, setSessionError] = useState<string | null>(null); const [view, setView] = useState("dashboard");
  useEffect(() => { request<CurrentUser>("/auth/me").then(setUser).catch((e: ApiError) => { if (e.status !== 401) setSessionError(publicError(e)); }).finally(() => setSessionLoading(false)); }, []);
  async function login(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setSessionError(null); const form = new FormData(event.currentTarget); try { const loggedIn = await request<CurrentUser>("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) }); setUser(loggedIn); event.currentTarget.reset(); } catch (e) { setSessionError(publicError(e as ApiError)); } }
  async function logout() { try { await request<void>("/auth/logout", { method: "POST" }); } catch (e) { setSessionError(publicError(e as ApiError)); } finally { setUser(null); setView("dashboard"); } }
  if (sessionLoading) return <main className="application-shell"><p role="status">Verificando sesión…</p></main>;
  if (!user) return <main className="login-shell"><section className="login-card" aria-labelledby="login-heading"><p className="eyebrow">Conciliación de activos</p><h1 id="login-heading">Iniciar sesión</h1><p>Use su cuenta local. Las credenciales solo se envían a la API de sesión del mismo origen.</p><form onSubmit={login}><label>Usuario <input name="username" autoComplete="username" required /></label><label>Contraseña <input name="password" type="password" autoComplete="current-password" required /></label><button className="button-primary">Ingresar</button></form><ErrorNotice error={sessionError} /></section></main>;
  const canUpload = user.role === "editor" || user.role === "admin";
  return <div className="app"><aside className="sidebar"><div className="brand"><p className="eyebrow">TISICO</p><strong>Control de activos</strong></div><nav aria-label="Aplicación"><button className={view === "dashboard" ? "active" : ""} onClick={() => setView("dashboard")}>Panel ejecutivo</button><button className={view === "operations" ? "active" : ""} onClick={() => setView("operations")}>Operaciones</button><button className={view === "states" ? "active" : ""} onClick={() => setView("states")}>Estados actuales</button>{canUpload && <button className={view === "uploads" ? "active" : ""} onClick={() => setView("uploads")}>Importaciones</button>}</nav><div className="sidebar-user"><strong>{user.display_name}</strong><span className="status">{roleLabel(user.role)}</span><button className="button-ghost" type="button" onClick={logout}>Cerrar sesión</button></div></aside><main className="content">{view === "dashboard" && <Dashboard />}{view === "operations" && <Operations />}{view === "states" && <CurrentStateList />}{view === "uploads" && canUpload && <Uploads />}</main></div>;
}
