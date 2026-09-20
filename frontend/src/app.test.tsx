import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("echarts", () => ({ init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }) }));

import { App } from "./app";

const viewer = { id: "u1", username: "viewer", display_name: "Usuario visor", role: "viewer" };
const editor = { ...viewer, role: "editor", display_name: "Usuario editor" };
const admin = { ...viewer, role: "admin", display_name: "Usuario administrador" };
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
  executive_metrics: executiveMetrics, operational_issues: operationalIssues, groups: [{ rubro: null, reconciliation_metrics: executiveMetrics, categories: [{ category: null, reconciliation_metrics: executiveMetrics, products: [{ product: null, observation_count: 4, distinct_asset_count: 4, status_counts: [{ status: null, count: 3 }, { status: "Active", count: 1 }], reconciliation_metrics: executiveMetrics }] }] }],
  charts: { primary_stacked_bar: { available: true, series: [{ key: "found_in_cost_center_count", label: "found_in_cost_center" }, { key: "returned_count", label: "returned" }, { key: "difference_count", label: "difference" }], items: [{ rubro: null, category: null, ...executiveMetrics }] }, general_status_donut: summary.summaries[0].charts.general_status_donut },
  page: { limit: 100, offset: 0, has_more: false, total_count: 1 },
};
const importHistory = { items: [{ batch_id: "batch-1", source: "system", cost_center: { code: "190", name: "Principal" }, report_date: "2026-09-17", imported_at: "2026-09-17T10:00:00Z", imported_by_display_name: "Usuario editor", row_count: 4, status: "completed", warning_counts: {}, processing_counts: {} }], page: {} };
const reviewQueue = { items: [{ id: "case-1", category: "unresolved_identifier", cost_center: { code: "190", name: "Principal" }, asset: null, source: { report_date: "2026-09-17" }, reason: "missing_identifier" }], queue_counts: { total: 1 }, page: {} };
const currentStates = { states: [{ asset_id: "asset-1", asset_code: "ACT-01", cost_center: { code: "190", name: "Principal" }, state: "returned", reason: "authorized_post_audit_column_l_return_marker", marker: { column: 12, category: "recognized_return", raw_value: "DEVOLVIO" }, source_report_date: "2026-09-17", projection_version: "audit_l_return_v1" }] };

type FetchResponses = { summaries?: unknown; drilldown?: unknown; importHistory?: unknown; reviewQueue?: unknown; currentStates?: unknown };
function json(data: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } })); }
function installFetch(user: object | null = viewer, responses: FetchResponses = {}) {
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
    if (url === "/api/auth/me") return user ? json(user) : json({ detail: "Authentication required" }, 401);
    if (url === "/api/auth/login") return json(viewer);
    if (url === "/api/dashboard/summaries") return json(responses.summaries ?? summary);
    if (url.startsWith("/api/dashboard/system-drilldown")) return json(responses.drilldown ?? drilldown);
    if (url === "/api/operations/import-history") return json(responses.importHistory ?? importHistory);
    if (url === "/api/operations/review-queue") return json(responses.reviewQueue ?? reviewQueue);
    if (url === "/api/current-states") return json(responses.currentStates ?? currentStates);
    if (url.startsWith("/api/imports/")) return json({ source: url.endsWith("system") ? "system" : "audit", row_count: 3 }, 201);
    if (url === "/api/auth/logout") return Promise.resolve(new Response(null, { status: 204 }));
    return json({ detail: "not found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock); return fetchMock;
}

describe("sesión y vistas de presentación", () => {
  beforeEach(() => vi.unstubAllGlobals());
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
    installFetch(viewer); const viewerView = render(<App />); await screen.findByRole("heading", { name: "Control de activos" });
    expect(screen.queryByRole("button", { name: "Importaciones" })).not.toBeInTheDocument(); viewerView.unmount();
    installFetch(editor); const editorView = render(<App />); await screen.findByRole("heading", { name: "Control de activos" });
    expect(screen.getByRole("button", { name: "Importaciones" })).toBeInTheDocument(); editorView.unmount();
    installFetch(admin); render(<App />); await screen.findByRole("heading", { name: "Control de activos" });
    expect(screen.getByRole("button", { name: "Importaciones" })).toBeInTheDocument();
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
    installFetch(); render(<App />); await screen.findByRole("heading", { name: "Control de activos" });
    expect(screen.getByText("Los estados y las diferencias se calculan sobre activos distintos del lote de sistema seleccionado. Los estados de auditoría son proyecciones del lote de auditoría seleccionado. Los KPI y gráficos se calculan únicamente en el servidor.")).toBeInTheDocument();
    expect(screen.queryByText(summary.metric_scope)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ver análisis" }));
    expect(await screen.findByText(/Activo \(1\)/)).toBeInTheDocument();
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

  it("renderiza el gráfico agrupado y las etiquetas nulas como sin asignar", async () => {
    installFetch(); render(<App />); await screen.findByRole("heading", { name: "Control de activos" });
    fireEvent.click(screen.getByRole("button", { name: "Ver análisis" }));
    expect(await screen.findByRole("img", { name: "Barras apiladas de conciliación por categoría" })).toBeInTheDocument();
    expect(screen.getByText("Rubro: Sin rubro asignado")).toBeInTheDocument();
    expect(screen.getByText("Categoría: Sin categoría asignada")).toBeInTheDocument();
    expect(screen.getByText("Sin producto asignado")).toBeInTheDocument();
  });

  it("muestra un error localizado sin exponer el detalle crudo del servidor", async () => {
    const fetchMock = installFetch(); fetchMock.mockImplementation((url: string) => url === "/api/auth/me" ? json(viewer) : url === "/api/dashboard/summaries" ? json({ detail: "Unavailable now" }, 503) : json({}));
    render(<App />); expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo completar la solicitud. Intente nuevamente.");
    expect(screen.queryByText("Unavailable now")).not.toBeInTheDocument();
  });

  it("envía la importación de sistema como multipart y anuncia el resultado localizado", async () => {
    const fetchMock = installFetch(editor); render(<App />); await screen.findByRole("heading", { name: "Control de activos" });
    fireEvent.click(screen.getByRole("button", { name: "Importaciones" }));
    const form = screen.getByRole("heading", { name: "Reporte de sistema" }).closest("form")!;
    fireEvent.change(within(form).getByLabelText("Libro de trabajo"), { target: { files: [new File(["workbook"], "report.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" })] } });
    fireEvent.change(within(form).getByLabelText("Fecha del reporte"), { target: { value: "2026-09-17" } }); fireEvent.submit(form);
    expect(await screen.findByText("La importación de Sistema fue aceptada con 3 filas.")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/imports/system", expect.objectContaining({ method: "POST", credentials: "include" })));
    const uploadCall = fetchMock.mock.calls.find(([url]) => url === "/api/imports/system"); expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData);
  });
});
