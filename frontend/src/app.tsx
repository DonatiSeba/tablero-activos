import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import type { BarSeriesOption, EChartsOption } from "echarts";

export type Role = "viewer" | "editor" | "admin";
export type CurrentUser = { id: string; username: string; display_name: string; role: Role; must_change_password: boolean };
type ApiError = { status?: number };
type Page = { limit: number; offset: number; has_more: boolean; total_count: number };
type ManagedUser = CurrentUser & { email: string; is_active: boolean; created_at: string; updated_at: string };
type UserListResponse = { items: ManagedUser[]; total: number; limit: number; offset: number };
type TemporaryPasswordResponse = ManagedUser & { temporary_password: string };
type CostCenter = { code: string; name: string };
type ManagedCostCenter = CostCenter & { id: string; status: "active" | "inactive"; start_date: string | null; end_date: string | null; created_at: string; updated_at: string };
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
  not_in_management_system_for_cost_center_count: number | null;
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
type DrilldownResponse = {
  cost_center: CostCenter | null;
  source: Source;
  audit_source: Source;
  executive_metrics?: ExecutiveMetrics;
  operational_issues?: OperationalIssues;
  page: Page;
  charts: {
    primary_stacked_bar: { available: boolean; reason?: string | null; scope?: string; series: { key: "found_in_cost_center_count" | "returned_count" | "difference_count"; label: string }[]; items: ({ rubro: string | null; category: string | null } & ExecutiveMetrics)[] };
    general_status_donut: DonutChart;
  };
};
type RubroOption = { value: string | null; label: string };
type ReconciliationChart = {
  available: boolean;
  reason: string | null;
  series: { key: "found_in_cost_center_count" | "returned_count" | "difference_count"; label: string }[];
  items: { product: string | null; product_label: string; found_in_cost_center_count: number | null; returned_count: number | null; difference_count: number | null }[];
  page: Page;
};
type RubroReconciliationResponse = {
  cost_center: CostCenter | null;
  rubro_options: RubroOption[];
  selected_rubro: RubroOption | null;
  category_options: RubroOption[];
  selected_category: RubroOption | null;
  product_chart: ReconciliationChart;
};
type ProductPageRequest = { offset: number; limit: number };
type RubroChartRequestIdentity = {
  costCenterCode: string;
  rubro: string | null | undefined;
  category: string | null | undefined;
  productPage: ProductPageRequest | null;
};
function sameRubroChartRequest(left: RubroChartRequestIdentity, right: RubroChartRequestIdentity) {
  return left.costCenterCode === right.costCenterCode
    && left.rubro === right.rubro
    && left.category === right.category
    && (left.productPage === right.productPage || (left.productPage !== null && right.productPage !== null && left.productPage.offset === right.productPage.offset && left.productPage.limit === right.productPage.limit));
}
type ImportHistory = { items: { batch_id: string; source: string; cost_center: CostCenter; report_date: string; imported_at: string; imported_by_display_name: string | null; row_count: number; status: string; warning_counts: Record<string, number>; processing_counts: Record<string, number> }[]; page: Page };
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
  if (error.status === 409) return "La acción entra en conflicto con otro usuario o con las protecciones de administradores activos.";
  if (error.status === 400 || error.status === 422) return "Revise los datos ingresados e intente nuevamente.";
  return "No se pudo completar la solicitud. Intente nuevamente.";
}
function passwordError(error: ApiError) {
  if (error.status === 400) return "La contraseña actual no es correcta o la nueva contraseña no cumple los requisitos.";
  if (error.status === 422) return "La nueva contraseña debe tener al menos 12 caracteres y ser diferente de la actual.";
  return publicError(error);
}
function ErrorNotice({ error }: { error: string | null }) { return error ? <p className="notice error" role="alert">{error}</p> : null; }
function Empty({ children }: { children: ReactNode }) { return <p className="empty">{children}</p>; }
function date(value: string | null) { return value || "Sin fecha informada"; }
function number(value: number | null) { return value === null ? "No disponible" : new Intl.NumberFormat("es-AR").format(value); }
function percentage(value: number | null) { return value === null ? "No disponible" : `${new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(value)} %`; }
function hierarchyLabel(value: string | null, level: "rubro" | "categoría") {
  const emptyLabels = { rubro: "Sin rubro asignado", categoría: "Sin categoría asignada" };
  return value || emptyLabels[level];
}
function roleLabel(role: Role) { return { viewer: "Consulta", editor: "Editor", admin: "Administrador" }[role]; }

const metricScopeLabels: Record<string, string> = {
  "Status and pending metrics are distinct assets in the selected system batch; audit states are projections whose provenance is the selected audit batch. Executive KPI and chart values are calculated only on the server.": "Los estados y las diferencias se calculan sobre activos distintos del lote de sistema seleccionado. Los estados de auditoría son proyecciones del lote de auditoría seleccionado. Los KPI y gráficos se calculan únicamente en el servidor.",
};
const sourceLabels: Record<string, string> = { system: "Sistema", audit: "Auditoría", return: "Retorno" };
const importStatusLabels: Record<string, string> = { completed: "Completada", rejected: "Rechazada", failed: "Con errores" };
const stateLabels: Record<string, string> = {
  Active: "Activo", active: "Activo", Inactive: "Inactivo", inactive: "Inactivo", Retired: "Retirado", retired: "Retirado", in_service: "En servicio",
  found: "Encontrado en el centro de costo", returned: "Retornado", review_required: "Requiere revisión", pending: "Pendiente", matched: "Conciliado", mismatched: "No conciliado",
};
const reasonLabels: Record<string, string> = {
  authorized_post_audit_column_l_return_marker: "La marca de retorno de la columna L fue reconocida después de la auditoría; no constituye una recepción de almacén.",
  ambiguous_column_l_return_marker_requires_review: "La marca de retorno de la columna L es ambigua y requiere revisión.",
  resolved_audit_presence_without_recognized_return_marker: "El activo fue encontrado en la auditoría sin una marca de retorno reconocida.",
};
const chartLabels: Record<string, string> = { found_in_cost_center: "Encontrados en CC", returned: "Retornados", difference: "Diferencia pendiente" };

function metricScopeLabel(scope: string) { return metricScopeLabels[scope] || "Los KPI y gráficos se calculan únicamente en el servidor a partir de la evidencia seleccionada."; }
function sourceLabel(source: string) { return sourceLabels[source] || "Fuente no reconocida"; }
function importStatusLabel(status: string) { return importStatusLabels[status] || "Estado de importación no reconocido"; }
function stateLabel(state: string | null) { return state === null ? "Sin estado informado" : stateLabels[state] || "Estado no reconocido"; }
function reasonLabel(reason: string | null | undefined) { return reason ? reasonLabels[reason] || "El motivo informado no está reconocido." : "Sin motivo informado."; }
function chartLabel(key: string) { return chartLabels[key] || "Serie no reconocida"; }
function chartReason(reason?: string | null) {
  if (reason === "system_and_audit_evidence_required") return "Se requieren evidencias vigentes de sistema y auditoría para este gráfico.";
  if (reason === "fewer_than_two_comparable_snapshots") return "Aún no hay dos instantáneas comparables para mostrar una evolución.";
  if (reason === "return_event_time_evidence_unavailable") return "La evolución de retornos no está disponible porque no existe evidencia temporal de esos eventos.";
  return "La información para este gráfico no está disponible.";
}
function rubroChartReason(reason?: string | null) {
  if (reason === "missing_system_evidence") return "No hay evidencia vigente de sistema para mostrar rubros y categorías.";
  if (reason === "missing_audit_evidence") return "No hay evidencia vigente de auditoría para conciliar los productos seleccionados.";
  if (reason === "empty_rubro") return "El rubro seleccionado no tiene categorías para mostrar.";
  if (reason === "invalid_rubro_selection") return "El rubro seleccionado ya no está disponible para este centro de costo.";
  if (reason === "invalid_category_selection") return "La categoría seleccionada ya no está disponible para este rubro.";
  if (reason === "cost_center_not_found") return "El centro de costo seleccionado no está disponible.";
  return "La información para este gráfico no está disponible.";
}
function freshnessText(freshness: Freshness) {
  if (freshness.status === "report_dates_differ") return "Las fechas de sistema y auditoría no coinciden; no representan un corte común.";
  if (freshness.status === "missing_system") return "No hay evidencia vigente de sistema para comparar el corte.";
  if (freshness.status === "missing_audit") return "No hay evidencia vigente de auditoría para comparar el corte.";
  if (freshness.status === "missing_both") return "No hay evidencia vigente de sistema ni de auditoría para comparar el corte.";
  return "Las fuentes requieren atención antes de comparar el corte.";
}

function EChart({ option, ariaLabel, height }: { option: EChartsOption; ariaLabel: string; height?: number }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current, undefined, { renderer: "svg" });
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [option]);
  return <div className="chart" style={height ? { height } : undefined} role="img" aria-label={ariaLabel} ref={element} />;
}

const metricIcons = { blue: "▤", green: "✓", cyan: "↩", red: "!", yellow: "◎" } as const;
function Metric({ label, value, tone = "blue", description }: { label: string; value: number | null; tone?: keyof typeof metricIcons; description?: string }) {
  return <div className={`metric metric-${tone}`}><div className="metric-top"><dt>{label}</dt><span className="metric-icon" aria-hidden="true">{metricIcons[tone]}</span></div><dd>{number(value)}</dd>{description && <span className="metric-description">{description}</span>}<span className="metric-accent" aria-hidden="true" /></div>;
}
function Kpis({ metrics }: { metrics: ExecutiveMetrics }) {
  return <><dl className="metrics executive-metrics">
    <Metric label="En sistema" value={metrics.system_count} />
    <Metric label="Encontrados en CC" value={metrics.found_in_cost_center_count} tone="green" />
    <Metric label="Retornados" value={metrics.returned_count} tone="cyan" />
    <Metric label="Diferencia pendiente" value={metrics.difference_count} tone="red" />
  </dl><dl className="supporting-metrics" aria-label="Indicadores complementarios"><div><dt>Contabilizados</dt><dd>{number(metrics.accounted_count)}</dd></div><div><dt>Cobertura</dt><dd>{percentage(metrics.coverage_percent)}</dd></div></dl></>;
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
  const rubroMap = new Map<string | null, { rubro: string | null; found_in_cost_center_count: number; returned_count: number; difference_count: number }>();
  for (const item of chart.items) {
    const existing = rubroMap.get(item.rubro);
    if (existing) {
      existing.found_in_cost_center_count += item.found_in_cost_center_count ?? 0;
      existing.returned_count += item.returned_count ?? 0;
      existing.difference_count += item.difference_count ?? 0;
    } else {
      rubroMap.set(item.rubro, {
        rubro: item.rubro,
        found_in_cost_center_count: item.found_in_cost_center_count ?? 0,
        returned_count: item.returned_count ?? 0,
        difference_count: item.difference_count ?? 0,
      });
    }
  }
  const aggregatedItems = Array.from(rubroMap.values());
  return <EChart ariaLabel="Barras apiladas de conciliación por rubro" option={{
    color: chart.series.map((series) => colors[series.key] || "#627587"),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { bottom: 0, data: chart.series.map((series) => chartLabel(series.label)) },
    grid: { left: 16, right: 16, top: 24, bottom: 52, containLabel: true },
    xAxis: { type: "value", minInterval: 1 },
    yAxis: { type: "category", data: aggregatedItems.map((item) => hierarchyLabel(item.rubro, "rubro")) },
    series: chart.series.map((series) => ({ name: chartLabel(series.label), type: "bar", stack: "conciliación", emphasis: { focus: "series" }, data: aggregatedItems.map((item) => item[series.key]) })),
  }} />;
}
type ProductBarDataItem = {
  value: number | null;
  emphasis: { focus: readonly number[] };
};
function productBarDataItem(value: number | null, productIndex: number): ProductBarDataItem {
  return { value, emphasis: { focus: [productIndex] } };
}
function ProductBars({ chart }: { chart: ReconciliationChart }) {
  if (!chart.available) return <Empty>{rubroChartReason(chart.reason)}</Empty>;
  if (chart.items.length === 0) return <Empty>No hay productos para la categoría seleccionada.</Empty>;
  const colors: Record<string, string> = { found_in_cost_center_count: "#17855f", returned_count: "#168aad", difference_count: "#c74545" };
  const height = Math.max(310, chart.items.length * 48 + 82);
  return <div className="product-chart-scroll"><EChart height={height} ariaLabel="Barras agrupadas de conciliación por producto" option={{
    color: chart.series.map((series) => colors[series.key] || "#627587"),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { bottom: 0, data: chart.series.map((series) => chartLabel(series.label)) },
    grid: { left: 16, right: 24, top: 24, bottom: 52, containLabel: true },
    xAxis: { type: "value", minInterval: 1 },
    yAxis: { type: "category", data: chart.items.map((item) => item.product_label) },
    series: chart.series.map((series) => ({
      name: chartLabel(series.label),
      type: "bar",
      // ECharts supports per-item data-index focus, but its bar helper narrows focus to series values.
      data: chart.items.map((item, productIndex) => productBarDataItem(item[series.key], productIndex)) as unknown as BarSeriesOption["data"],
    })),
  }} /></div>;
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
  return <section className="panel issues" aria-labelledby="issues-heading"><div className="panel-heading"><div><h2 id="issues-heading">Inconsistencias operativas</h2></div><span className="chip chip-warning">Revisión</span></div><div className="issue-grid">
    <Metric label="Diferencia física o patrimonial" value={issues.physical_patrimonial_difference_count} tone="red" />
    <Metric label="Retornos pendientes de actualización" value={issues.system_update_required_return_count} tone="cyan" />
    <Metric label="Casos pendientes de revisión" value={issues.review_required_count} tone="yellow" />
    <Metric label="No figuran en el sistema de gestión para este CC" value={issues.not_in_management_system_for_cost_center_count} tone="yellow" />
  </div></section>;
}

function ServerPagination({ page, busy, label, onNavigate }: { page: Page; busy: boolean; label: string; onNavigate: (offset: number, limit: number) => void }) {
  const pageNumber = Math.floor(page.offset / page.limit) + 1;
  const pageCount = Math.max(1, Math.ceil(page.total_count / page.limit));
  if (pageCount <= 1) return null;
  return <nav className="pagination dashboard-pagination" aria-label={label}>
    <button type="button" className="button-secondary" disabled={busy || page.offset === 0} onClick={() => onNavigate(Math.max(0, page.offset - page.limit), page.limit)}>Anterior</button>
    <span aria-live="polite">Página {pageNumber} de {pageCount}</span>
    <button type="button" className="button-secondary" disabled={busy || !page.has_more} onClick={() => onNavigate(page.offset + page.limit, page.limit)}>Siguiente</button>
  </nav>;
}

function Dashboard() {
  const [data, setData] = useState<SummariesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const summaryRequestInFlight = useRef(false);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const selectedCodeRef = useRef<string | null>(null);
  const [drilldown, setDrilldown] = useState<DrilldownResponse | null>(null);
  const [drilldownError, setDrilldownError] = useState<string | null>(null);
  const [drilldownLoading, setDrilldownLoading] = useState(false);
  const [drilldownRequest, setDrilldownRequest] = useState<{ offset: number; limit: number } | null>(null);
  const [rubroChart, setRubroChart] = useState<RubroReconciliationResponse | null>(null);
  const [rubroChartError, setRubroChartError] = useState<string | null>(null);
  const [rubroChartLoading, setRubroChartLoading] = useState(false);
  const [requestedRubro, setRequestedRubro] = useState<string | null | undefined>(undefined);
  const [requestedCategory, setRequestedCategory] = useState<string | null | undefined>(undefined);
  const [productPageRequest, setProductPageRequest] = useState<ProductPageRequest | null>(null);
  const lastSuccessfulRubroRequest = useRef<RubroChartRequestIdentity | null>(null);
  const rollbackRubroChartRequest = useRef<RubroChartRequestIdentity | null>(null);

  function selectCenter(code: string | null) {
    selectedCodeRef.current = code;
    setSelectedCode(code);
    setDrilldownRequest(null);
    setDrilldown(null);
    setDrilldownError(null);
    setRequestedRubro(undefined);
    setRequestedCategory(undefined);
    setProductPageRequest(null);
    lastSuccessfulRubroRequest.current = null;
    rollbackRubroChartRequest.current = null;
    setRubroChart(null);
    setRubroChartError(null);
  }

  function selectRubro(value: string) {
    setRequestedRubro(value || null);
    setRequestedCategory(undefined);
    setProductPageRequest(null);
    setRubroChartError(null);
  }

  function selectCategory(value: string) {
    setRequestedCategory(value || null);
    setProductPageRequest(null);
    setRubroChartError(null);
  }

  async function loadSummaryPage(page?: { offset: number; limit: number }) {
    if (summaryRequestInFlight.current) return;
    summaryRequestInFlight.current = true;
    setSummaryLoading(true);
    setError(null);
    const path = page ? `/dashboard/summaries?limit=${page.limit}&offset=${page.offset}` : "/dashboard/summaries";
    try {
      const response = await request<SummariesResponse>(path);
      const current = selectedCodeRef.current;
      const next = response.summaries.some((summary) => summary.cost_center.code === current)
        ? current
        : response.summaries[0]?.cost_center.code || null;
      setData(response);
      if (next !== current) selectCenter(next);
    } catch (e) {
      setError(publicError(e as ApiError));
    } finally {
      summaryRequestInFlight.current = false;
      setSummaryLoading(false);
    }
  }

  useEffect(() => { void loadSummaryPage(); }, []);
  useEffect(() => {
    if (!selectedCode) return;
    let active = true;
    setDrilldownLoading(true);
    setDrilldown(null);
    setDrilldownError(null);
    const pagination = drilldownRequest ? `&limit=${drilldownRequest.limit}&offset=${drilldownRequest.offset}` : "";
    request<DrilldownResponse>(`/dashboard/system-drilldown?cost_center_code=${encodeURIComponent(selectedCode)}${pagination}`).then((response) => {
      if (active) setDrilldown(response);
    }).catch((e: ApiError) => {
      if (active) setDrilldownError(publicError(e));
    }).finally(() => {
      if (active) setDrilldownLoading(false);
    });
    return () => { active = false; };
  }, [selectedCode, drilldownRequest]);

  useEffect(() => {
    if (!selectedCode) return;
    const currentRequest = { costCenterCode: selectedCode, rubro: requestedRubro, category: requestedCategory, productPage: productPageRequest };
    const rollbackRequest = rollbackRubroChartRequest.current;
    if (rollbackRequest) {
      rollbackRubroChartRequest.current = null;
      if (sameRubroChartRequest(currentRequest, rollbackRequest)) return;
    }
    let active = true;
    setRubroChartLoading(true);
    setRubroChartError(null);
    const rubro = requestedRubro === undefined ? "" : `&rubro=${encodeURIComponent(requestedRubro ?? "")}`;
    const category = requestedCategory === undefined ? "" : `&category=${encodeURIComponent(requestedCategory ?? "")}`;
    const productPage = productPageRequest ? `&product_limit=${productPageRequest.limit}&product_offset=${productPageRequest.offset}` : "";
    request<RubroReconciliationResponse>(`/dashboard/rubro-reconciliation-chart?cost_center_code=${encodeURIComponent(selectedCode)}${rubro}${category}${productPage}`).then((response) => {
      if (active) {
        lastSuccessfulRubroRequest.current = currentRequest;
        setRubroChart(response);
      }
    }).catch((e: ApiError) => {
      if (!active) return;
      setRubroChartLoading(false);
      setRubroChartError(publicError(e));
      const previousRequest = lastSuccessfulRubroRequest.current;
      if (previousRequest) {
        rollbackRubroChartRequest.current = previousRequest;
        setRequestedRubro(previousRequest.rubro);
        setRequestedCategory(previousRequest.category);
        setProductPageRequest(previousRequest.productPage);
      }
    }).finally(() => {
      if (active) setRubroChartLoading(false);
    });
    return () => { active = false; };
  }, [selectedCode, requestedRubro, requestedCategory, productPageRequest]);

  function navigateDrilldown(offset: number, limit: number) {
    if (drilldownLoading) return;
    setDrilldownLoading(true);
    setDrilldown(null);
    setDrilldownError(null);
    setDrilldownRequest({ offset, limit });
  }

  const selected = data?.summaries.find((summary) => summary.cost_center.code === selectedCode) || null;
  return <section aria-labelledby="dashboard-heading">
    <div className="dashboard-topbar"><div className="title-wrap"><h1 id="dashboard-heading">Conciliación de activos</h1></div>{data && data.summaries.length > 0 && <label className="cost-center-select">Centro de costo<select value={selectedCode || ""} disabled={summaryLoading} onChange={(event) => selectCenter(event.target.value)}>{data.summaries.map((summary) => <option value={summary.cost_center.code} key={summary.cost_center.code}>CC {summary.cost_center.code} · {summary.cost_center.name}</option>)}</select></label>}</div>
    <ErrorNotice error={error} />
    {!data && !error && <div className="loading-card" role="status">Cargando resumen ejecutivo…</div>}
    {data?.summaries.length === 0 && <Empty>No hay centros de costo disponibles para esta sesión.</Empty>}
    {data && <ServerPagination page={data.page} busy={summaryLoading} label="Paginación de centros de costo" onNavigate={(offset, limit) => void loadSummaryPage({ offset, limit })} />}
    {selected && <>
      <section className="context-card" aria-label="Contexto del centro de costo"><div><span>Centro seleccionado</span><strong>CC {selected.cost_center.code} · {selected.cost_center.name}</strong></div><SourceDates system={selected.latest_sources.system} audit={selected.latest_sources.audit} freshness={selected.freshness} /></section>
      <Kpis metrics={selected.executive_metrics} />
      <ErrorNotice error={drilldownError} />
      {!drilldown && !drilldownError && <div className="loading-card" role="status">Cargando conciliación agrupada…</div>}
      <div className="dashboard-grid dashboard-grid-primary"><section className="panel chart-panel"><div className="panel-heading"><div><h2>Conciliación por rubro</h2></div><span className="chip">Último corte</span></div>{drilldown ? <><StackedBars chart={drilldown.charts.primary_stacked_bar} /><ServerPagination page={drilldown.page} busy={drilldownLoading} label="Paginación del gráfico principal de conciliación" onNavigate={navigateDrilldown} /></> : <div className="chart-placeholder" />}</section><section className="panel chart-panel"><div className="panel-heading"><div><h2>Estado general</h2></div><span className="chip">{percentage(selected.executive_metrics.coverage_percent)} cobertura</span></div><Donut chart={drilldown?.charts.general_status_donut || selected.charts.general_status_donut} /></section></div>
      <div className="dashboard-grid">{selected.charts.time_evolution.available && <section className="panel chart-panel"><div className="panel-heading"><div><h2>Evolución temporal</h2></div><span className="chip">Histórico</span></div><Evolution chart={selected.charts.time_evolution} /></section>}<OperationalIssues issues={drilldown?.operational_issues || selected.operational_issues} /></div>
      <section className="panel rubro-chart-panel" aria-labelledby="rubro-chart-heading" aria-busy={rubroChartLoading}><div className="panel-heading"><div><h2 id="rubro-chart-heading">Detalle de conciliación</h2></div><span className="chip" role="status" aria-live="polite">{rubroChartLoading && rubroChart ? "Actualizando…" : "Por producto"}</span></div>{!rubroChart && rubroChartLoading && <div className="loading-card" role="status">Cargando productos de la categoría…</div>}<ErrorNotice error={rubroChartError} />{rubroChart && <>{rubroChart.rubro_options.length === 0 ? <Empty>No hay rubros disponibles para este centro de costo.</Empty> : <div className="hierarchy-selectors"><label>Rubro<select value={rubroChart.selected_rubro?.value ?? ""} disabled={rubroChartLoading} onChange={(event) => selectRubro(event.target.value)}>{rubroChart.rubro_options.map((option) => <option key={option.value ?? "unassigned"} value={option.value ?? ""}>{option.label}</option>)}</select></label><label>Categoría<select value={rubroChart.selected_category?.value ?? ""} disabled={rubroChartLoading || rubroChart.category_options.length === 0} onChange={(event) => selectCategory(event.target.value)}>{rubroChart.category_options.map((option) => <option key={option.value ?? "unassigned"} value={option.value ?? ""}>{option.label}</option>)}</select></label></div>}<ProductBars chart={rubroChart.product_chart} />{rubroChart.product_chart.available && <ServerPagination page={rubroChart.product_chart.page} busy={rubroChartLoading} label="Paginación de productos de conciliación" onNavigate={(offset, limit) => setProductPageRequest({ offset, limit })} />}</>}</section>
    </>}
  </section>;
}

function ImportHistoryPanel({ refreshVersion }: { refreshVersion: number }) {
  const [history, setHistory] = useState<ImportHistory | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(false); const requestVersion = useRef(0);
  useEffect(() => {
    let active = true;
    const version = ++requestVersion.current;
    setLoading(true);
    setError(null);
    request<ImportHistory>("/operations/import-history").then((response) => {
      if (active && version === requestVersion.current) setHistory(response);
    }).catch((e: ApiError) => {
      if (active && version === requestVersion.current) setError(publicError(e));
    }).finally(() => {
      if (active && version === requestVersion.current) setLoading(false);
    });
    return () => { active = false; };
  }, [refreshVersion]);
  return <section className="panel" aria-labelledby="history-heading" aria-busy={loading}><h2 id="history-heading">Historial de importaciones</h2><ErrorNotice error={error} />{loading && !history && <p role="status" className="loading">Cargando historial de importaciones…</p>}{history?.items.length === 0 && <Empty>No hay importaciones para esta vista.</Empty>}{history && <div className="table-scroll"><table><thead><tr><th>Fuente</th><th>Centro de costo</th><th>Fecha del reporte</th><th>Filas</th><th>Estado</th><th>Importado por</th></tr></thead><tbody>{history.items.map((item) => <tr key={item.batch_id}><td>{sourceLabel(item.source)}</td><td>{item.cost_center.code}</td><td>{item.report_date}</td><td>{number(item.row_count)}</td><td><span className="status">{importStatusLabel(item.status)}</span></td><td>{item.imported_by_display_name || "No informado"}</td></tr>)}</tbody></table></div>}</section>;
}

function CurrentStateList() {
  const [data, setData] = useState<CurrentStates | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { request<CurrentStates>("/current-states").then(setData).catch((e: ApiError) => setError(publicError(e))); }, []);
  return <section aria-labelledby="states-heading"><div className="page-heading"><div><p className="eyebrow">Trazabilidad</p><h1 id="states-heading">Estados actuales</h1><p className="muted">Los retornos de la columna L de auditoría son inferencias autorizadas posteriores a la auditoría, no recepciones de almacén.</p></div></div><ErrorNotice error={error} />{!data && !error && <p role="status" className="loading">Cargando estados actuales…</p>}{data?.states.length === 0 && <Empty>No hay proyecciones de estado actual disponibles.</Empty>}<div className="table-scroll"><table><thead><tr><th>Activo</th><th>Centro de costo</th><th>Estado</th><th>Fecha de auditoría</th><th>Motivo</th></tr></thead><tbody>{data?.states.map((item) => <tr key={item.asset_id}><td>{item.asset_code}</td><td>{item.cost_center.code}</td><td><span className="status">{stateLabel(item.state)}</span></td><td>{item.source_report_date}</td><td>{reasonLabel(item.reason)}</td></tr>)}</tbody></table></div></section>;
}

function CostCenterManagement({ onCentersChanged }: { onCentersChanged: () => void }) {
  const [centers, setCenters] = useState<ManagedCostCenter[] | null>(null); const [error, setError] = useState<string | null>(null); const [message, setMessage] = useState<string | null>(null); const [busy, setBusy] = useState(false); const [listLoading, setListLoading] = useState(false); const [editing, setEditing] = useState<ManagedCostCenter | null>(null); const mounted = useRef(true); const listRequestVersion = useRef(0);
  async function load() {
    if (!mounted.current) return;
    const version = ++listRequestVersion.current;
    setListLoading(true); setError(null);
    try {
      const response = await request<ManagedCostCenter[]>("/cost-centers");
      if (mounted.current && version === listRequestVersion.current) setCenters(response);
    } catch (e) {
      if (mounted.current && version === listRequestVersion.current) setError(publicError(e as ApiError));
    } finally {
      if (mounted.current && version === listRequestVersion.current) setListLoading(false);
    }
  }
  useEffect(() => {
    mounted.current = true; void load();
    return () => { mounted.current = false; listRequestVersion.current += 1; };
  }, []);
  async function createCenter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); setBusy(true); setError(null); setMessage(null);
    try {
      const created = await request<ManagedCostCenter>("/cost-centers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: values.get("code"), name: values.get("name") }) });
      if (!mounted.current) return;
      form.reset(); setMessage(`El centro CC ${created.code} fue creado.`); await load();
      if (mounted.current) onCentersChanged();
    } catch (e) { if (mounted.current) setError(publicError(e as ApiError)); } finally { if (mounted.current) setBusy(false); }
  }
  async function saveCenter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!editing) return; const values = new FormData(event.currentTarget); setBusy(true); setError(null); setMessage(null);
    try {
      const updated = await request<ManagedCostCenter>(`/cost-centers/${editing.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: values.get("name"), status: values.get("status") }) });
      if (!mounted.current) return;
      setEditing(null); setMessage(`El centro CC ${updated.code} fue actualizado.`); await load();
      if (mounted.current) onCentersChanged();
    } catch (e) { if (mounted.current) setError(publicError(e as ApiError)); } finally { if (mounted.current) setBusy(false); }
  }
  async function toggleStatus(center: ManagedCostCenter) {
    setBusy(true); setError(null); setMessage(null);
    const status = center.status === "active" ? "inactive" : "active";
    try {
      const updated = await request<ManagedCostCenter>(`/cost-centers/${center.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
      if (!mounted.current) return;
      setMessage(`El centro CC ${updated.code} quedó ${updated.status === "active" ? "activo" : "inactivo"}.`); await load();
      if (mounted.current) onCentersChanged();
    } catch (e) { if (mounted.current) setError(publicError(e as ApiError)); } finally { if (mounted.current) setBusy(false); }
  }
  return <section className="panel cost-centers-panel" aria-labelledby="cost-centers-heading" aria-busy={listLoading}><div className="panel-heading"><div><h2 id="cost-centers-heading">Administrar centros de costo</h2><p>Los centros inactivos conservan su historial y no reciben nuevas importaciones.</p></div></div><div className="cost-center-management-grid"><form className="cost-center-form" onSubmit={createCenter}><h3>Crear centro</h3><label>Código <input name="code" required maxLength={64} /></label><label>Nombre <input name="name" required maxLength={255} /></label><button className="button-primary" disabled={busy}>Crear centro</button></form>{editing && <form className="cost-center-form" onSubmit={saveCenter}><div className="form-heading"><h3>Editar CC {editing.code}</h3><button className="text-button" type="button" onClick={() => setEditing(null)}>Cancelar</button></div><label>Nombre <input name="name" required maxLength={255} defaultValue={editing.name} /></label><label>Estado<select name="status" defaultValue={editing.status}><option value="active">Activo</option><option value="inactive">Inactivo</option></select></label><button className="button-primary" disabled={busy}>Guardar centro</button></form>}</div><p className="notice" role="status" aria-live="polite">{message}</p><ErrorNotice error={error} />{listLoading && !centers && !error && <p className="loading" role="status">Cargando centros de costo…</p>}{centers?.length === 0 && <Empty>No hay centros de costo registrados.</Empty>}{centers && centers.length > 0 && <div className="table-scroll"><table className="cost-centers-table"><thead><tr><th>Código</th><th>Nombre</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>{centers.map((center) => <tr key={center.id}><td><strong>{center.code}</strong></td><td>{center.name}</td><td><span className={`status ${center.status === "active" ? "status-active" : "status-inactive"}`}>{center.status === "active" ? "Activo" : "Inactivo"}</span></td><td><div className="row-actions"><button type="button" aria-label={`Editar CC ${center.code} · ${center.name}`} disabled={busy} onClick={() => setEditing(center)}>Editar</button><button type="button" aria-label={`${center.status === "active" ? "Desactivar" : "Activar"} CC ${center.code} · ${center.name}`} disabled={busy} onClick={() => void toggleStatus(center)}>{center.status === "active" ? "Desactivar" : "Activar"}</button></div></td></tr>)}</tbody></table></div>}</section>;
}

function Uploads({ role }: { role: Role }) {
  const [activeCenters, setActiveCenters] = useState<ManagedCostCenter[] | null>(null); const [activeCentersError, setActiveCentersError] = useState<string | null>(null); const [activeCentersRefresh, setActiveCentersRefresh] = useState(0); const [systemCode, setSystemCode] = useState(""); const [auditCode, setAuditCode] = useState(""); const [systemMessage, setSystemMessage] = useState<string | null>(null); const [auditMessage, setAuditMessage] = useState<string | null>(null); const [systemError, setSystemError] = useState<string | null>(null); const [auditError, setAuditError] = useState<string | null>(null); const [busyEndpoint, setBusyEndpoint] = useState<"/imports/system" | "/imports/audit" | null>(null); const [historyRefreshVersion, setHistoryRefreshVersion] = useState(0); const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let active = true; setActiveCentersError(null);
    request<ManagedCostCenter[]>("/cost-centers?active_only=true").then((centers) => {
      if (!active) return; setActiveCenters(centers); const fallback = centers[0]?.code || "";
      setSystemCode((current) => centers.some((center) => center.code === current) ? current : fallback);
      setAuditCode((current) => centers.some((center) => center.code === current) ? current : fallback);
    }).catch((e: ApiError) => { if (active) { setActiveCenters([]); setSystemCode(""); setAuditCode(""); setActiveCentersError(publicError(e)); } });
    return () => { active = false; };
  }, [activeCentersRefresh]);
  async function submit(event: FormEvent<HTMLFormElement>, endpoint: "/imports/system" | "/imports/audit") {
    event.preventDefault(); const form = event.currentTarget; const system = endpoint === "/imports/system"; const selectedCode = system ? systemCode : auditCode;
    if (!activeCenters?.some((center) => center.code === selectedCode)) { const unavailable = "Seleccione un centro de costo activo antes de importar."; if (system) setSystemError(unavailable); else setAuditError(unavailable); return; }
    if (system) { setSystemError(null); setSystemMessage(null); } else { setAuditError(null); setAuditMessage(null); } setBusyEndpoint(endpoint);
    try {
      const result = await request<{ source: string; row_count: number }>(endpoint, { method: "POST", body: new FormData(form) });
      if (!mounted.current) return;
      const message = `La importación de ${sourceLabel(result.source as Source["source"])} fue aceptada con ${number(result.row_count)} filas.`;
      if (system) setSystemMessage(message); else setAuditMessage(message);
      form.reset();
      setHistoryRefreshVersion((version) => version + 1);
    } catch (e) { if (mounted.current) { if (system) setSystemError(publicError(e as ApiError)); else setAuditError(publicError(e as ApiError)); } } finally { if (mounted.current) setBusyEndpoint(null); }
  }
  const centersUnavailable = activeCenters === null || activeCenters.length === 0;
  const centerOptions = activeCenters?.map((center) => <option value={center.code} key={center.id}>CC {center.code} · {center.name}</option>);
  return <section aria-labelledby="uploads-heading"><div className="page-heading"><div><p className="eyebrow">Carga autorizada</p><h1 id="uploads-heading">Importar evidencia</h1><p className="muted">Los editores y administradores pueden enviar libros de origen. El servidor valida la aceptación y las coincidencias.</p></div></div>{activeCenters === null && <p className="loading" role="status">Cargando centros de costo activos…</p>}<ErrorNotice error={activeCentersError} />{activeCenters !== null && activeCenters.length === 0 && <Empty>{activeCentersError ? "No se pudo confirmar ningún centro de costo activo. Las importaciones están temporalmente deshabilitadas." : "No hay centros de costo activos. Active o cree un centro antes de importar."}</Empty>}<div className="upload-grid">
    <form className="panel" onSubmit={(event) => submit(event, "/imports/system")}><h2>Reporte de sistema</h2><label>Libro de trabajo <input name="file" type="file" accept=".xlsx" required /></label><label>Fecha del reporte <input name="report_date" type="date" required /></label><label>Centro de costo<select name="cost_center_code" required value={systemCode} onChange={(event) => setSystemCode(event.target.value)} disabled={centersUnavailable}><option value="" disabled>Seleccione un centro activo</option>{centerOptions}</select></label><p className="notice" role="status" aria-live="polite">{systemMessage}</p><ErrorNotice error={systemError} /><button className="button-primary" disabled={centersUnavailable || busyEndpoint !== null}>{busyEndpoint === "/imports/system" ? "Cargando…" : "Cargar reporte de sistema"}</button></form>
    <form className="panel" onSubmit={(event) => submit(event, "/imports/audit")}><h2>Auditoría física</h2><label>Libro de trabajo <input name="file" type="file" accept=".xlsx" required /></label><label>Fecha del reporte <input name="report_date" type="date" required /></label><label>Centro de costo<select name="cost_center_code" required value={auditCode} onChange={(event) => setAuditCode(event.target.value)} disabled={centersUnavailable}><option value="" disabled>Seleccione un centro activo</option>{centerOptions}</select></label><p className="notice" role="status" aria-live="polite">{auditMessage}</p><ErrorNotice error={auditError} /><button className="button-primary" disabled={centersUnavailable || busyEndpoint !== null}>{busyEndpoint === "/imports/audit" ? "Cargando…" : "Cargar auditoría"}</button></form>
  </div>{role === "admin" && <CostCenterManagement onCentersChanged={() => setActiveCentersRefresh((version) => version + 1)} />}<ImportHistoryPanel refreshVersion={historyRefreshVersion} /></section>;
}

const managedRoles: { value: Role; label: string }[] = [
  { value: "viewer", label: "Viewer" },
  { value: "editor", label: "Editor" },
  { value: "admin", label: "Admin" },
];
function TemporaryPasswordPanel({ result, onClose }: { result: { displayName: string; password: string }; onClose: () => void }) {
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  async function copyPassword() {
    try { await navigator.clipboard.writeText(result.password); setCopyStatus("Contraseña copiada."); }
    catch { setCopyStatus("No se pudo copiar. Seleccione la contraseña y cópiela manualmente."); }
  }
  return <section className="temporary-password" aria-labelledby="temporary-password-heading" role="status"><div><p className="eyebrow">Credencial temporal</p><h2 id="temporary-password-heading">Contraseña para {result.displayName}</h2><p>Se muestra una sola vez. Entréguela por un canal seguro; la persona deberá cambiarla al ingresar.</p><output aria-label="Contraseña temporal">{result.password}</output>{copyStatus && <p aria-live="polite">{copyStatus}</p>}</div><div className="temporary-password-actions"><button className="button-secondary" type="button" onClick={() => void copyPassword()}>Copiar contraseña</button><button className="button-secondary" type="button" onClick={onClose}>Cerrar y ocultar</button></div></section>;
}
function Users({ currentUser, onCurrentUserUpdated }: { currentUser: CurrentUser; onCurrentUserUpdated: (user: CurrentUser) => void }) {
  const pageSize = 20;
  const [data, setData] = useState<UserListResponse | null>(null); const [offset, setOffset] = useState(0); const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false); const [editing, setEditing] = useState<ManagedUser | null>(null); const [temporary, setTemporary] = useState<{ displayName: string; password: string } | null>(null);
  async function load(pageOffset = offset) {
    setData(null); setError(null);
    try { setData(await request<UserListResponse>(`/users?limit=${pageSize}&offset=${pageOffset}`)); }
    catch (e) { setError(publicError(e as ApiError)); }
  }
  useEffect(() => { void load(offset); }, [offset]);
  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); setBusy(true); setError(null); setTemporary(null);
    try {
      const created = await request<TemporaryPasswordResponse>("/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: values.get("username"), email: values.get("email"), display_name: values.get("display_name"), role: values.get("role") }) });
      form.reset(); setTemporary({ displayName: created.display_name, password: created.temporary_password }); await load(offset);
    } catch (e) { setError(publicError(e as ApiError)); } finally { setBusy(false); }
  }
  async function saveUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!editing) return; const values = new FormData(event.currentTarget); setBusy(true); setError(null);
    try {
      const updated = await request<ManagedUser>(`/users/${editing.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: values.get("username"), email: values.get("email"), display_name: values.get("display_name"), role: values.get("role") }) });
      setEditing(null); if (updated.id === currentUser.id) onCurrentUserUpdated({ id: updated.id, username: updated.username, display_name: updated.display_name, role: updated.role, must_change_password: updated.must_change_password }); await load(offset);
    } catch (e) { setError(publicError(e as ApiError)); } finally { setBusy(false); }
  }
  async function setActive(user: ManagedUser) {
    setBusy(true); setError(null);
    try { await request<ManagedUser>(`/users/${user.id}/${user.is_active ? "disable" : "enable"}`, { method: "POST" }); await load(offset); }
    catch (e) { setError(publicError(e as ApiError)); } finally { setBusy(false); }
  }
  async function resetPassword(user: ManagedUser) {
    setBusy(true); setError(null); setTemporary(null);
    try { const result = await request<TemporaryPasswordResponse>(`/users/${user.id}/reset-password`, { method: "POST" }); setTemporary({ displayName: result.display_name, password: result.temporary_password }); await load(offset); }
    catch (e) { setError(publicError(e as ApiError)); } finally { setBusy(false); }
  }
  const first = data && data.total > 0 ? data.offset + 1 : 0; const last = data ? Math.min(data.offset + data.items.length, data.total) : 0;
  return <section aria-labelledby="users-heading"><div className="page-heading"><div><p className="eyebrow">Administración</p><h1 id="users-heading">Usuarios</h1><p className="muted">Gestione perfiles y asigne uno de los roles fijos. La autorización siempre se valida en el servidor.</p></div></div><ErrorNotice error={error} />
    {temporary && <TemporaryPasswordPanel result={temporary} onClose={() => setTemporary(null)} />}
    <div className="user-management-grid"><form className="panel user-form" onSubmit={createUser}><h2>Crear usuario</h2><label>Nombre para mostrar <input name="display_name" required maxLength={255} /></label><label>Usuario <input name="username" required maxLength={128} autoComplete="off" /></label><label>Correo electrónico <input name="email" type="email" required maxLength={320} autoComplete="off" /></label><label>Rol<select name="role" defaultValue="viewer">{managedRoles.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}</select></label><button className="button-primary" disabled={busy}>Crear usuario</button></form>
      {editing && <form className="panel user-form" onSubmit={saveUser}><div className="form-heading"><h2>Editar usuario</h2><button className="text-button" type="button" onClick={() => setEditing(null)}>Cancelar</button></div><label>Nombre para mostrar <input name="display_name" defaultValue={editing.display_name} required maxLength={255} /></label><label>Usuario <input name="username" defaultValue={editing.username} required maxLength={128} /></label><label>Correo electrónico <input name="email" type="email" defaultValue={editing.email} required maxLength={320} /></label><label>Rol<select name="role" defaultValue={editing.role}>{managedRoles.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}</select></label><button className="button-primary" disabled={busy}>Guardar cambios</button></form>}
    </div>
    <section className="panel users-panel" aria-labelledby="users-list-heading"><div className="panel-heading"><div><h2 id="users-list-heading">Usuarios registrados</h2>{data && <p>Mostrando {first}–{last} de {data.total}</p>}</div></div>{!data && !error && <p className="loading" role="status">Cargando usuarios…</p>}{data?.items.length === 0 && <Empty>No hay usuarios registrados.</Empty>}{data && data.items.length > 0 && <div className="table-scroll"><table className="users-table"><thead><tr><th>Nombre</th><th>Usuario</th><th>Correo</th><th>Rol</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>{data.items.map((managedUser) => <tr key={managedUser.id}><td><strong>{managedUser.display_name}</strong></td><td>{managedUser.username}</td><td>{managedUser.email}</td><td>{roleLabel(managedUser.role)}</td><td><span className={`status ${managedUser.is_active ? "status-active" : "status-inactive"}`}>{managedUser.is_active ? "Activo" : "Inactivo"}</span></td><td><div className="row-actions"><button type="button" onClick={() => setEditing(managedUser)} disabled={busy}>Editar</button><button type="button" onClick={() => void setActive(managedUser)} disabled={busy}>{managedUser.is_active ? "Desactivar" : "Activar"}</button><button type="button" onClick={() => void resetPassword(managedUser)} disabled={busy}>Restablecer contraseña</button></div></td></tr>)}</tbody></table></div>}
      {data && data.total > pageSize && <nav className="pagination" aria-label="Paginación de usuarios"><button type="button" className="button-secondary" disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Anterior</button><span>Página {Math.floor(offset / pageSize) + 1}</span><button type="button" className="button-secondary" disabled={busy || offset + data.items.length >= data.total} onClick={() => setOffset(offset + pageSize)}>Siguiente</button></nav>}
    </section>
  </section>;
}
function PasswordChange({ forced = false, onChanged, onLogout }: { forced?: boolean; onChanged: (user: CurrentUser) => void; onLogout?: () => void }) {
  const [error, setError] = useState<string | null>(null); const [message, setMessage] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); const currentPassword = String(values.get("current_password") || ""); const newPassword = String(values.get("new_password") || ""); form.reset(); setError(null); setMessage(null); setBusy(true);
    try { await request<CurrentUser>("/auth/change-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }); const refreshed = await request<CurrentUser>("/auth/me"); setMessage("La contraseña se actualizó correctamente."); onChanged(refreshed); }
    catch (e) { setError(passwordError(e as ApiError)); } finally { setBusy(false); }
  }
  return <section className={forced ? "password-gate" : "password-page"} aria-labelledby="password-heading"><div className={forced ? "password-card" : "panel password-card"}><p className="eyebrow">Seguridad de la cuenta</p><h1 id="password-heading">{forced ? "Cambie su contraseña para continuar" : "Cambiar mi contraseña"}</h1><p>{forced ? "Está usando una contraseña temporal. Debe reemplazarla antes de acceder a la aplicación." : "Use su contraseña actual y elija una nueva de al menos 12 caracteres."}</p><form onSubmit={submit}><label>Contraseña actual <input name="current_password" type="password" autoComplete="current-password" required /></label><label>Nueva contraseña <input name="new_password" type="password" autoComplete="new-password" minLength={12} required /></label><button className="button-primary" disabled={busy}>{busy ? "Actualizando…" : "Cambiar contraseña"}</button></form><p className="notice" role="status" aria-live="polite">{message}</p><ErrorNotice error={error} />{forced && onLogout && <button className="text-button" type="button" onClick={onLogout}>Cerrar sesión</button>}</div></section>;
}

const navigationIcons = { dashboard: "◫", states: "▣", uploads: "⇩", users: "♙", password: "◆" } as const;
const mobileNavigationQuery = "(max-width: 52rem)";
function useMobileNavigation() {
  const [mobile, setMobile] = useState(() => window.matchMedia?.(mobileNavigationQuery).matches ?? false);
  useEffect(() => {
    if (!window.matchMedia) return;
    const mediaQuery = window.matchMedia(mobileNavigationQuery);
    const update = () => setMobile(mediaQuery.matches);
    update();
    mediaQuery.addEventListener("change", update);
    return () => mediaQuery.removeEventListener("change", update);
  }, []);
  return mobile;
}
export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null); const [sessionLoading, setSessionLoading] = useState(true); const [sessionError, setSessionError] = useState<string | null>(null); const [view, setView] = useState("dashboard"); const [navigationOpen, setNavigationOpen] = useState(false); const mobileNavigation = useMobileNavigation();
  useEffect(() => { request<CurrentUser>("/auth/me").then(setUser).catch((e: ApiError) => { if (e.status !== 401) setSessionError(publicError(e)); }).finally(() => setSessionLoading(false)); }, []);
  async function login(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setSessionError(null); const element = event.currentTarget; const form = new FormData(element); const username = form.get("username"); const password = form.get("password"); element.reset(); try { const loggedIn = await request<CurrentUser>("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) }); setUser(loggedIn); } catch (e) { setSessionError(publicError(e as ApiError)); } }
  async function logout() { try { await request<void>("/auth/logout", { method: "POST" }); } catch (e) { setSessionError(publicError(e as ApiError)); } finally { setUser(null); setView("dashboard"); setNavigationOpen(false); } }
  function navigate(destination: string) { setView(destination); setNavigationOpen(false); }
  if (sessionLoading) return <main className="application-shell"><p role="status">Verificando sesión…</p></main>;
  if (!user) return <main className="login-shell"><section className="login-card"><img className="login-logo" src="/logo-dark.svg" alt="TISICO" width="3340" height="1063" /><form aria-label="Iniciar sesión" onSubmit={login}><label>Usuario <input name="username" autoComplete="username" required /></label><label>Contraseña <input name="password" type="password" autoComplete="current-password" required /></label><button className="button-primary">Ingresar</button></form><ErrorNotice error={sessionError} /></section></main>;
  if (user.must_change_password) return <PasswordChange forced onChanged={setUser} onLogout={() => void logout()} />;
  const canUpload = user.role === "editor" || user.role === "admin"; const canManageUsers = user.role === "admin";
  const initials = user.display_name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  const navigationUnavailable = mobileNavigation && !navigationOpen;
  return <div className="app"><header className="mobile-header"><div className="mobile-brand"><img className="mobile-logo" src="/logo.svg" alt="TISICO" width="3340" height="1063" /></div><button className="menu-toggle" type="button" aria-label={navigationOpen ? "Cerrar navegación" : "Abrir navegación"} aria-expanded={navigationOpen} aria-controls="application-sidebar" onClick={() => setNavigationOpen((open) => !open)}><span aria-hidden="true">{navigationOpen ? "×" : "☰"}</span></button></header>{navigationOpen && <button className="nav-scrim" type="button" aria-label="Cerrar navegación al seleccionar fuera del menú" onClick={() => setNavigationOpen(false)} />}<aside id="application-sidebar" className={`sidebar${navigationOpen ? " sidebar-open" : ""}`} aria-hidden={navigationUnavailable || undefined} ref={(element) => element?.toggleAttribute("inert", navigationUnavailable)}><div className="brand"><img className="brand-logo" src="/logo.svg" alt="TISICO" width="3340" height="1063" /></div><nav aria-label="Aplicación"><p className="nav-label">Principal</p><button className={view === "dashboard" ? "active" : ""} onClick={() => navigate("dashboard")}><span className="nav-icon" aria-hidden="true">{navigationIcons.dashboard}</span>Dashboard</button><button className={view === "states" ? "active" : ""} onClick={() => navigate("states")}><span className="nav-icon" aria-hidden="true">{navigationIcons.states}</span>Estados actuales</button><p className="nav-label">Gestión</p>{canUpload && <button className={view === "uploads" ? "active" : ""} onClick={() => navigate("uploads")}><span className="nav-icon" aria-hidden="true">{navigationIcons.uploads}</span>Importaciones</button>}{canManageUsers && <button className={view === "users" ? "active" : ""} onClick={() => navigate("users")}><span className="nav-icon" aria-hidden="true">{navigationIcons.users}</span>Usuarios</button>}<p className="nav-label">Cuenta</p><button className={view === "password" ? "active" : ""} onClick={() => navigate("password")}><span className="nav-icon" aria-hidden="true">{navigationIcons.password}</span>Mi contraseña</button></nav><div className="sidebar-user"><div className="avatar" aria-hidden="true">{initials}</div><div className="user-copy"><strong>{user.display_name}</strong><span>{roleLabel(user.role)}</span></div><button className="logout-button" type="button" onClick={logout}>Salir</button></div></aside><main className="content">{view === "dashboard" && <Dashboard />}{view === "states" && <CurrentStateList />}{view === "uploads" && canUpload && <Uploads role={user.role} />}{view === "users" && canManageUsers && <Users currentUser={user} onCurrentUserUpdated={setUser} />}{view === "password" && <PasswordChange onChanged={setUser} />}</main></div>;
}
