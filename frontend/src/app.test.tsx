import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { setOptionMock } = vi.hoisted(() => ({ setOptionMock: vi.fn() }));
vi.mock("echarts", () => ({ init: () => ({ setOption: setOptionMock, resize: vi.fn(), dispose: vi.fn() }) }));

import { App } from "./app";

const viewer = { id: "u1", username: "viewer", display_name: "Usuario visor", role: "viewer", must_change_password: false };
const editor = { ...viewer, role: "editor", display_name: "Usuario editor" };
const admin = { ...viewer, role: "admin", display_name: "Usuario administrador" };
const managedViewer = { ...viewer, id: "u2", email: "viewer@example.test", is_active: true, created_at: "2026-09-20T10:00:00Z", updated_at: "2026-09-20T10:00:00Z" };
const usersResponse = { items: [managedViewer], total: 1, limit: 20, offset: 0 };
const executiveMetrics = { system_count: 4, found_in_cost_center_count: 2, returned_count: 1, accounted_count: 3, difference_count: 1, coverage_percent: 75 };
const operationalIssues = { physical_patrimonial_difference_count: 1, system_update_required_return_count: 1, system_data_quality_omission_count: 0, review_required_count: 0, unresolved_audit_case_count: 1 };
type TemporalFixture = {
  available: boolean;
  reason?: string;
  points: { report_date: string; system_count: number; found_in_cost_center_count: number; audit_snapshot_difference_count: number }[];
  return_evolution: { available: boolean; reason?: string; points: unknown[] };
};
const summary = {
  summaries: [{
    cost_center: { code: "190", name: "Principal" },
    latest_sources: { system: { source: "system", available: true, batch_id: "s", report_date: "2026-09-17" }, audit: { source: "audit", available: true, batch_id: "a", report_date: "2026-09-16" } },
    freshness: { warning: true, status: "report_dates_differ", message: "ignored server text" },
    executive_metrics: executiveMetrics,
    operational_issues: operationalIssues,
    charts: {
      general_status_donut: { available: true, segments: [{ key: "found_in_cost_center", value: 2 }, { key: "returned", value: 1 }, { key: "difference", value: 1 }] },
      time_evolution: { available: false, reason: "fewer_than_two_comparable_snapshots", points: [], return_evolution: { available: false, reason: "return_event_time_evidence_unavailable", points: [] } } as TemporalFixture,
    },
  }], page: { limit: 100, offset: 0, has_more: false, total_count: 1 }, selection_rule: "Server selection", metric_scope: "Status and pending metrics are distinct assets in the selected system batch; audit states are projections whose provenance is the selected audit batch. Executive KPI and chart values are calculated only on the server.",
};
const drilldown = {
  cost_center: { code: "190", name: "Principal" }, source: summary.summaries[0].latest_sources.system, audit_source: summary.summaries[0].latest_sources.audit,
  executive_metrics: executiveMetrics, operational_issues: operationalIssues,
  charts: { primary_stacked_bar: { available: true, series: [{ key: "found_in_cost_center_count", label: "found_in_cost_center" }, { key: "returned_count", label: "returned" }, { key: "difference_count", label: "difference" }], items: [{ rubro: null, category: null, ...executiveMetrics }] }, general_status_donut: summary.summaries[0].charts.general_status_donut },
  page: { limit: 100, offset: 0, has_more: false, total_count: 1 },
};
type RubroChartFixture = {
  cost_center: { code: string; name: string };
  rubro_options: { value: string | null; label: string }[];
  selected_rubro: { value: string | null; label: string } | null;
  category_chart: {
    available: boolean;
    reason: string | null;
    series: { key: string; label: string }[];
    items: { category: string | null; category_label: string; found_in_cost_center_count: number | null; returned_count: number | null; difference_count: number | null }[];
  };
};
const rubroChart: RubroChartFixture = {
  cost_center: { code: "190", name: "Principal" },
  rubro_options: [{ value: "Rubro & Ácento", label: "Rubro & Ácento" }, { value: null, label: "Sin rubro asignado" }],
  selected_rubro: { value: "Rubro & Ácento", label: "Rubro & Ácento" },
  category_chart: {
    available: true, reason: null,
    series: [{ key: "found_in_cost_center_count", label: "found_in_cost_center" }, { key: "returned_count", label: "returned" }, { key: "difference_count", label: "difference" }],
    items: [{ category: null, category_label: "Sin categoría asignada", found_in_cost_center_count: 7, returned_count: 3, difference_count: 2 }, { category: "Muebles", category_label: "Muebles", found_in_cost_center_count: 4, returned_count: 1, difference_count: 5 }],
  },
};
const importHistory = { items: [{ batch_id: "batch-1", source: "system", cost_center: { code: "190", name: "Principal" }, report_date: "2026-09-17", imported_at: "2026-09-17T10:00:00Z", imported_by_display_name: "Usuario editor", row_count: 4, status: "completed", warning_counts: {}, processing_counts: {} }], page: {} };
const reviewQueue = { items: [{ id: "case-1", category: "unresolved_identifier", cost_center: { code: "190", name: "Principal" }, asset: null, source: { report_date: "2026-09-17" }, reason: "missing_identifier" }], queue_counts: { total: 1 }, page: {} };
const currentStates = { states: [{ asset_id: "asset-1", asset_code: "ACT-01", cost_center: { code: "190", name: "Principal" }, state: "returned", reason: "authorized_post_audit_column_l_return_marker", marker: { column: 12, category: "recognized_return", raw_value: "DEVOLVIO" }, source_report_date: "2026-09-17", projection_version: "audit_l_return_v1" }] };

type FetchResponses = { summaries?: unknown; drilldown?: unknown; rubroChart?: unknown; importHistory?: unknown; reviewQueue?: unknown; currentStates?: unknown; users?: unknown };
function json(data: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } })); }
function installViewport(matchesMobile: boolean) {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: matchesMobile,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}
function installFetch(user: object | null = viewer, responses: FetchResponses = {}) {
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
    if (url === "/api/auth/me") return user ? json(user) : json({ detail: "Authentication required" }, 401);
    if (url === "/api/auth/login") return json(viewer);
    if (url === "/api/dashboard/summaries") return json(responses.summaries ?? summary);
    if (url.startsWith("/api/dashboard/system-drilldown")) return json(responses.drilldown ?? drilldown);
    if (url.startsWith("/api/dashboard/rubro-reconciliation-chart")) return json(responses.rubroChart ?? rubroChart);
    if (url === "/api/operations/import-history") return json(responses.importHistory ?? importHistory);
    if (url === "/api/operations/review-queue") return json(responses.reviewQueue ?? reviewQueue);
    if (url === "/api/current-states") return json(responses.currentStates ?? currentStates);
    if (url.startsWith("/api/imports/")) return json({ source: url.endsWith("system") ? "system" : "audit", row_count: 3 }, 201);
    if (url.startsWith("/api/users?")) return json(responses.users ?? usersResponse);
    if (url === "/api/users" && _init?.method === "POST") return json({ ...managedViewer, id: "u2", display_name: "Nueva Persona", temporary_password: "Temporal-very-secret" }, 201);
    if (url.endsWith("/reset-password")) return json({ ...managedViewer, temporary_password: "Reset-very-secret" });
    if (/\/api\/users\/[^/]+\/(enable|disable)$/.test(url)) return json({ ...managedViewer, is_active: url.endsWith("enable") });
    if (/\/api\/users\/[^/]+$/.test(url) && _init?.method === "PATCH") return json(managedViewer);
    if (url === "/api/auth/change-password") return json({ ...viewer, must_change_password: false });
    if (url === "/api/auth/logout") return Promise.resolve(new Response(null, { status: 204 }));
    return json({ detail: "not found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock); return fetchMock;
}

describe("sesión y vistas de presentación", () => {
  beforeEach(() => { vi.unstubAllGlobals(); setOptionMock.mockClear(); });
  afterEach(() => cleanup());

  it("muestra el inicio de sesión en español y accede sin almacenamiento local", async () => {
    const fetchMock = installFetch(null); render(<App />);
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Usuario"), { target: { value: "alex" } }); fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Ingresar" }));
    expect(await screen.findByText("Usuario visor")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/login", expect.objectContaining({ credentials: "include", method: "POST" }));
    expect(localStorage.length).toBe(0);
  });

  it("mantiene las importaciones autorizadas para editor y administrador", async () => {
    installFetch(viewer); const viewerView = render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    expect(screen.queryByRole("button", { name: "Importaciones" })).not.toBeInTheDocument(); viewerView.unmount();
    installFetch(editor); const editorView = render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    expect(screen.getByRole("button", { name: "Importaciones" })).toBeInTheDocument(); editorView.unmount();
    installFetch(admin); render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    expect(screen.getByRole("button", { name: "Importaciones" })).toBeInTheDocument();
  });

  it("solicita el rubro predeterminado sin parámetro y lo reinicia al cambiar de centro", async () => {
    const multipleSummaries = structuredClone(summary);
    multipleSummaries.summaries.push({ ...structuredClone(summary.summaries[0]), cost_center: { code: "191", name: "Centro secundario" } });
    const fetchMock = installFetch(viewer, { summaries: multipleSummaries }); render(<App />);
    const selector = await screen.findByLabelText("Centro de costo");
    expect(selector).toHaveValue("190");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/rubro-reconciliation-chart?cost_center_code=190", expect.objectContaining({ credentials: "include" })));
    expect(await screen.findByLabelText("Rubro")).toHaveValue("Rubro & Ácento");
    fireEvent.change(selector, { target: { value: "191" } });
    expect(screen.queryByRole("img", { name: "Barras agrupadas de conciliación por categoría" })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/rubro-reconciliation-chart?cost_center_code=191", expect.objectContaining({ credentials: "include" })));
  });

  it("avanza y regresa entre páginas del servidor de centros de costo", async () => {
    const firstPage = structuredClone(summary);
    firstPage.page = { limit: 1, offset: 0, has_more: true, total_count: 2 };
    const secondPage = structuredClone(summary);
    secondPage.summaries[0].cost_center = { code: "191", name: "Centro secundario" };
    secondPage.page = { limit: 1, offset: 1, has_more: false, total_count: 2 };
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/auth/me") return json(viewer);
      if (url === "/api/dashboard/summaries") return json(firstPage);
      if (url === "/api/dashboard/summaries?limit=1&offset=1") return json(secondPage);
      if (url === "/api/dashboard/summaries?limit=1&offset=0") return json(firstPage);
      if (url.startsWith("/api/dashboard/rubro-reconciliation-chart")) return json(rubroChart);
      if (url.startsWith("/api/dashboard/system-drilldown")) {
        const response = structuredClone(drilldown);
        const code = new URL(url, "https://example.test").searchParams.get("cost_center_code") || "190";
        response.cost_center = code === "191" ? { code, name: "Centro secundario" } : { code, name: "Principal" };
        return json(response);
      }
      return json({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock); render(<App />);

    const firstNavigation = await screen.findByRole("navigation", { name: "Paginación de centros de costo" });
    expect(within(firstNavigation).getByRole("button", { name: "Anterior" })).toBeDisabled();
    fireEvent.click(within(firstNavigation).getByRole("button", { name: "Siguiente" }));

    expect(await screen.findByLabelText("Centro de costo")).toHaveValue("191");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/summaries?limit=1&offset=1", expect.objectContaining({ credentials: "include" })));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/system-drilldown?cost_center_code=191", expect.objectContaining({ credentials: "include" })));
    const secondNavigation = screen.getByRole("navigation", { name: "Paginación de centros de costo" });
    expect(within(secondNavigation).getByRole("button", { name: "Siguiente" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "CC 191 · Centro secundario" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "CC 190 · Principal" })).not.toBeInTheDocument();

    fireEvent.click(within(secondNavigation).getByRole("button", { name: "Anterior" }));
    expect(await screen.findByLabelText("Centro de costo")).toHaveValue("190");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/summaries?limit=1&offset=0", expect.objectContaining({ credentials: "include" })));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/system-drilldown?cost_center_code=190", expect.objectContaining({ credentials: "include" })));
  });

  it("mantiene la paginación del servidor junto al gráfico principal", async () => {
    const firstPage = { ...structuredClone(drilldown), page: { limit: 1, offset: 0, has_more: true, total_count: 2 } };
    const secondPage = { ...structuredClone(drilldown), page: { limit: 1, offset: 1, has_more: false, total_count: 2 } };
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/auth/me") return json(viewer);
      if (url === "/api/dashboard/summaries") return json(summary);
      if (url === "/api/dashboard/rubro-reconciliation-chart?cost_center_code=190") return json(rubroChart);
      if (url === "/api/dashboard/system-drilldown?cost_center_code=190") return json(firstPage);
      if (url === "/api/dashboard/system-drilldown?cost_center_code=190&limit=1&offset=1") return json(secondPage);
      if (url === "/api/dashboard/system-drilldown?cost_center_code=190&limit=1&offset=0") return json(firstPage);
      return json({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock); render(<App />);

    const navigation = await screen.findByRole("navigation", { name: "Paginación del gráfico principal de conciliación" });
    expect(screen.queryByRole("navigation", { name: "Paginación del detalle de conciliación" })).not.toBeInTheDocument();
    expect(within(navigation).getByRole("button", { name: "Anterior" })).toBeDisabled();
    fireEvent.click(within(navigation).getByRole("button", { name: "Siguiente" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/system-drilldown?cost_center_code=190&limit=1&offset=1", expect.objectContaining({ credentials: "include" })));
  });

  it("oculta semánticamente la navegación móvil cerrada y la restaura al abrirla", async () => {
    installViewport(true); installFetch(); render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    const sidebar = document.getElementById("application-sidebar")!;
    const toggle = screen.getByRole("button", { name: "Abrir navegación" });
    expect(toggle).toHaveAttribute("type", "button");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(sidebar).toHaveAttribute("aria-hidden", "true");
    expect(sidebar).toHaveAttribute("inert");
    expect(screen.queryByRole("navigation", { name: "Aplicación" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Salir" })).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Cerrar navegación" })).toHaveAttribute("aria-expanded", "true");
    expect(sidebar).not.toHaveAttribute("aria-hidden");
    expect(sidebar).not.toHaveAttribute("inert");
    expect(screen.getByRole("navigation", { name: "Aplicación" })).toBeInTheDocument();
    const backdrop = screen.getByRole("button", { name: "Cerrar navegación al seleccionar fuera del menú" });
    fireEvent.click(backdrop);
    expect(screen.getByRole("button", { name: "Abrir navegación" })).toHaveAttribute("aria-expanded", "false");
    expect(sidebar).toHaveAttribute("aria-hidden", "true");
    expect(sidebar).toHaveAttribute("inert");
    expect(backdrop).not.toBeInTheDocument();
  });

  it("mantiene la navegación de escritorio en el árbol accesible sin abrir el menú móvil", async () => {
    installViewport(false); installFetch(); render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    const sidebar = document.getElementById("application-sidebar")!;
    expect(sidebar).not.toHaveAttribute("aria-hidden");
    expect(sidebar).not.toHaveAttribute("inert");
    expect(screen.getByRole("navigation", { name: "Aplicación" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salir" })).toBeInTheDocument();
  });

  it("muestra KPI y advertencia de vigencia del servidor sin exponer su texto crudo", async () => {
    installFetch(); render(<App />);
    expect(await screen.findByText("Las fechas de sistema y auditoría no coinciden; no representan un corte común.")).toBeInTheDocument();
    expect(screen.queryByText("ignored server text")).not.toBeInTheDocument();
    expect(screen.getAllByText("4").length).toBeGreaterThan(0);
    expect(screen.getByRole("img", { name: "Distribución general de conciliación" })).toBeInTheDocument();
    expect(screen.getByText("2026-09-17")).toBeInTheDocument(); expect(screen.getByText("2026-09-16")).toBeInTheDocument();
  });

  it("localiza los valores de presentación del servidor sin exponer sus enums", async () => {
    installFetch(); render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    expect(screen.getByText("Los estados y las diferencias se calculan sobre activos distintos del lote de sistema seleccionado. Los estados de auditoría son proyecciones del lote de auditoría seleccionado. Los KPI y gráficos se calculan únicamente en el servidor.")).toBeInTheDocument();
    expect(screen.queryByText(summary.metric_scope)).not.toBeInTheDocument();

    expect(await screen.findByRole("img", { name: "Barras agrupadas de conciliación por categoría" })).toBeInTheDocument();
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
    expect(screen.getByText("Casos pendientes de revisión")).toBeInTheDocument();
    expect(screen.getByText("Casos de auditoría sin resolver")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Operaciones" }));
    expect(await screen.findByText("Sistema")).toBeInTheDocument();
    expect(screen.getByText("Completada")).toBeInTheDocument();
    const reviewCase = screen.getByText("Identificador sin resolver").closest("li");
    expect(reviewCase).toHaveTextContent("Falta el identificador del activo.");
    expect(screen.queryByText("missing_identifier")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Estados actuales" }));
    expect(await screen.findByText("Retornado")).toBeInTheDocument();
    expect(screen.getByText("La marca de retorno de la columna L fue reconocida después de la auditoría; no constituye una recepción de almacén.")).toBeInTheDocument();
  });

  it("renderiza el gráfico temporal y avisa cuando la evolución de retornos no está disponible", async () => {
    const temporalSummary = structuredClone(summary);
    temporalSummary.summaries[0].charts.time_evolution = {
      available: true,
      points: [
        { report_date: "2026-09-16", system_count: 3, found_in_cost_center_count: 2, audit_snapshot_difference_count: 1 },
        { report_date: "2026-09-17", system_count: 4, found_in_cost_center_count: 3, audit_snapshot_difference_count: 1 },
      ],
      return_evolution: { available: false, reason: "return_event_time_evidence_unavailable", points: [] },
    };
    installFetch(viewer, { summaries: temporalSummary }); render(<App />);
    expect(await screen.findByRole("img", { name: "Evolución temporal de las instantáneas comparables" })).toBeInTheDocument();
    expect(screen.getByText("La evolución de retornos no está disponible porque no existe evidencia temporal de esos eventos.")).toBeInTheDocument();
    expect(screen.queryByText("return_event_time_evidence_unavailable")).not.toBeInTheDocument();
  });

  it("renderiza las barras agrupadas con las etiquetas y valores que entrega el servidor", async () => {
    installFetch(); render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    expect(await screen.findByRole("img", { name: "Barras agrupadas de conciliación por categoría" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Sin rubro asignado" })).toBeInTheDocument();
    await waitFor(() => expect(setOptionMock).toHaveBeenCalledWith(expect.objectContaining({
      yAxis: expect.objectContaining({ data: ["Sin categoría asignada", "Muebles"] }),
      series: [expect.objectContaining({ data: [7, 4] }), expect.objectContaining({ data: [3, 1] }), expect.objectContaining({ data: [2, 5] })],
    })));
    expect(screen.queryByRole("table", { name: /detalle/i })).not.toBeInTheDocument();
  });

  it("codifica rubros nombrados y representa la selección nula explícita", async () => {
    const fetchMock = installFetch(); render(<App />);
    const rubroSelector = await screen.findByLabelText("Rubro");
    fireEvent.change(rubroSelector, { target: { value: "" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/rubro-reconciliation-chart?cost_center_code=190&rubro=", expect.objectContaining({ credentials: "include" })));
    fireEvent.change(await screen.findByLabelText("Rubro"), { target: { value: "Rubro & Ácento" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/rubro-reconciliation-chart?cost_center_code=190&rubro=Rubro%20%26%20%C3%81cento", expect.objectContaining({ credentials: "include" })));
  });

  it("muestra los estados localizados del contrato de rubro y no expone motivos crudos", async () => {
    const unavailable = structuredClone(rubroChart);
    unavailable.rubro_options = [];
    unavailable.selected_rubro = null;
    unavailable.category_chart = { ...unavailable.category_chart, available: false, reason: "missing_system_evidence", items: [] };
    installFetch(viewer, { rubroChart: unavailable }); const systemView = render(<App />);
    expect(await screen.findByText("No hay evidencia vigente de sistema para mostrar rubros y categorías.")).toBeInTheDocument();
    expect(screen.queryByText("missing_system_evidence")).not.toBeInTheDocument();
    systemView.unmount();

    const auditUnavailable = structuredClone(rubroChart);
    auditUnavailable.category_chart = { ...auditUnavailable.category_chart, available: false, reason: "missing_audit_evidence", items: [] };
    installFetch(viewer, { rubroChart: auditUnavailable }); const auditView = render(<App />);
    expect(await screen.findByText("No hay evidencia vigente de auditoría para conciliar las categorías seleccionadas.")).toBeInTheDocument();
    auditView.unmount();

    const invalid = structuredClone(rubroChart);
    invalid.category_chart = { ...invalid.category_chart, available: false, reason: "invalid_rubro_selection", items: [] };
    installFetch(viewer, { rubroChart: invalid }); const invalidView = render(<App />);
    expect(await screen.findByText("El rubro seleccionado ya no está disponible para este centro de costo.")).toBeInTheDocument();
    expect(screen.queryByText("invalid_rubro_selection")).not.toBeInTheDocument();
    invalidView.unmount();

    const empty = structuredClone(rubroChart);
    empty.category_chart = { ...empty.category_chart, available: false, reason: "empty_rubro", items: [] };
    installFetch(viewer, { rubroChart: empty }); render(<App />);
    expect(await screen.findByText("El rubro seleccionado no tiene categorías para mostrar.")).toBeInTheDocument();
  });

  it("muestra un error seguro al cargar el gráfico de rubro", async () => {
    const fetchMock = installFetch();
    fetchMock.mockImplementation((url: string) => url === "/api/auth/me" ? json(viewer) : url === "/api/dashboard/summaries" ? json(summary) : url.startsWith("/api/dashboard/rubro-reconciliation-chart") ? json({ detail: "raw chart outage" }, 503) : url.startsWith("/api/dashboard/system-drilldown") ? json(drilldown) : json({}, 404));
    render(<App />);
    expect(await screen.findByText("No se pudo completar la solicitud. Intente nuevamente.")).toBeInTheDocument();
    expect(screen.queryByText("raw chart outage")).not.toBeInTheDocument();
  });

  it("muestra carga, protege contra respuestas obsoletas y no conserva el gráfico anterior", async () => {
    const multipleSummaries = structuredClone(summary);
    multipleSummaries.summaries.push({ ...structuredClone(summary.summaries[0]), cost_center: { code: "191", name: "Centro secundario" } });
    let resolveFirstChart: (response: Response) => void = () => undefined;
    const firstChart = new Promise<Response>((resolve) => { resolveFirstChart = resolve; });
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/auth/me") return json(viewer);
      if (url === "/api/dashboard/summaries") return json(multipleSummaries);
      if (url.startsWith("/api/dashboard/system-drilldown")) return json(drilldown);
      if (url === "/api/dashboard/rubro-reconciliation-chart?cost_center_code=190") return firstChart;
      if (url === "/api/dashboard/rubro-reconciliation-chart?cost_center_code=191") return json(rubroChart);
      return json({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock); render(<App />);
    const centerSelector = await screen.findByLabelText("Centro de costo");
    expect(await screen.findByText("Cargando categorías del rubro…")).toBeInTheDocument();
    fireEvent.change(centerSelector, { target: { value: "191" } });
    expect(screen.queryByRole("img", { name: "Barras agrupadas de conciliación por categoría" })).not.toBeInTheDocument();
    expect(await screen.findByRole("img", { name: "Barras agrupadas de conciliación por categoría" })).toBeInTheDocument();
    const stale = structuredClone(rubroChart);
    stale.rubro_options = [{ value: "Obsoleto", label: "Obsoleto" }];
    stale.selected_rubro = stale.rubro_options[0];
    resolveFirstChart(await json(stale));
    await waitFor(() => expect(screen.queryByRole("option", { name: "Obsoleto" })).not.toBeInTheDocument());
  });

  it("muestra un error localizado sin exponer el detalle crudo del servidor", async () => {
    const fetchMock = installFetch(); fetchMock.mockImplementation((url: string) => url === "/api/auth/me" ? json(viewer) : url === "/api/dashboard/summaries" ? json({ detail: "Unavailable now" }, 503) : json({}));
    render(<App />); expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo completar la solicitud. Intente nuevamente.");
    expect(screen.queryByText("Unavailable now")).not.toBeInTheDocument();
  });

  it("envía la importación de sistema como multipart y anuncia el resultado localizado", async () => {
    const fetchMock = installFetch(editor); render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    fireEvent.click(screen.getByRole("button", { name: "Importaciones" }));
    const form = screen.getByRole("heading", { name: "Reporte de sistema" }).closest("form")!;
    fireEvent.change(within(form).getByLabelText("Libro de trabajo"), { target: { files: [new File(["workbook"], "report.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" })] } });
    fireEvent.change(within(form).getByLabelText("Fecha del reporte"), { target: { value: "2026-09-17" } }); fireEvent.submit(form);
    expect(await screen.findByText("La importación de Sistema fue aceptada con 3 filas.")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/imports/system", expect.objectContaining({ method: "POST", credentials: "include" })));
    const uploadCall = fetchMock.mock.calls.find(([url]) => url === "/api/imports/system"); expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData);
  });

  it("reserva Usuarios para ADMIN y ofrece el cambio de contraseña a toda cuenta", async () => {
    installFetch(viewer); const viewerView = render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    expect(screen.queryByRole("button", { name: "Usuarios" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mi contraseña" }));
    expect(screen.getByRole("heading", { name: "Cambiar mi contraseña" })).toBeInTheDocument(); viewerView.unmount();

    installFetch(admin); render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    fireEvent.click(screen.getByRole("button", { name: "Usuarios" }));
    expect(await screen.findByRole("heading", { name: "Usuarios" })).toBeInTheDocument();
    expect(await screen.findByText("viewer@example.test")).toBeInTheDocument();
    expect(screen.getByText("Consulta")).toBeInTheDocument();
    expect(screen.getByText("Activo")).toBeInTheDocument();
  });

  it("crea usuarios y oculta la contraseña temporal al cerrar sin persistirla", async () => {
    const fetchMock = installFetch(admin); render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" });
    fireEvent.click(screen.getByRole("button", { name: "Usuarios" }));
    const form = (await screen.findByRole("heading", { name: "Crear usuario" })).closest("form")!;
    fireEvent.change(within(form).getByLabelText("Nombre para mostrar"), { target: { value: "Nueva Persona" } });
    fireEvent.change(within(form).getByLabelText("Usuario"), { target: { value: "nueva" } });
    fireEvent.change(within(form).getByLabelText("Correo electrónico"), { target: { value: "nueva@example.test" } });
    fireEvent.change(within(form).getByLabelText("Rol"), { target: { value: "editor" } }); fireEvent.submit(form);
    expect(await screen.findByLabelText("Contraseña temporal")).toHaveTextContent("Temporal-very-secret");
    const createCall = fetchMock.mock.calls.find(([url, init]) => url === "/api/users" && init?.method === "POST");
    expect(createCall?.[1]).toEqual(expect.objectContaining({ credentials: "include", method: "POST" }));
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({ username: "nueva", email: "nueva@example.test", display_name: "Nueva Persona", role: "editor" });
    expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Cerrar y ocultar" }));
    expect(screen.queryByText("Temporal-very-secret")).not.toBeInTheDocument();
  });

  it("edita, desactiva y restablece usuarios mediante los contratos reales", async () => {
    const fetchMock = installFetch(admin); render(<App />); await screen.findByRole("heading", { name: "Conciliación de activos" }); fireEvent.click(screen.getByRole("button", { name: "Usuarios" }));
    const edit = await screen.findByRole("button", { name: "Editar" }); fireEvent.click(edit);
    const form = screen.getByRole("heading", { name: "Editar usuario" }).closest("form")!;
    fireEvent.change(within(form).getByLabelText("Nombre para mostrar"), { target: { value: "Visor actualizado" } }); fireEvent.change(within(form).getByLabelText("Rol"), { target: { value: "editor" } }); fireEvent.submit(form);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/users/u2", expect.objectContaining({ credentials: "include", method: "PATCH" })));
    fireEvent.click(await screen.findByRole("button", { name: "Desactivar" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/users/u2/disable", expect.objectContaining({ credentials: "include", method: "POST" })));
    fireEvent.click(await screen.findByRole("button", { name: "Restablecer contraseña" }));
    expect(await screen.findByLabelText("Contraseña temporal")).toHaveTextContent("Reset-very-secret");
  });

  it("bloquea la navegación hasta cambiar una contraseña temporal y refresca la sesión", async () => {
    let passwordChanged = false;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/auth/me") return json({ ...viewer, must_change_password: !passwordChanged });
      if (url === "/api/auth/change-password") { passwordChanged = true; return json({ ...viewer, must_change_password: false }); }
      if (url === "/api/dashboard/summaries") return json(summary);
      if (url.startsWith("/api/dashboard/system-drilldown")) return json(drilldown);
      return json({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock); render(<App />);
    expect(await screen.findByRole("heading", { name: "Cambie su contraseña para continuar" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Aplicación" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Contraseña actual"), { target: { value: "Temporal-very-secret" } });
    fireEvent.change(screen.getByLabelText("Nueva contraseña"), { target: { value: "Nueva-clave-segura-123" } }); fireEvent.click(screen.getByRole("button", { name: "Cambiar contraseña" }));
    expect(await screen.findByRole("heading", { name: "Conciliación de activos" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/change-password", expect.objectContaining({ credentials: "include", method: "POST" }));
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/auth/me")).toHaveLength(2);
  });
});
