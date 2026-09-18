import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./app";

const viewer = { id: "u1", username: "viewer", display_name: "Viewer User", role: "viewer" };
const editor = { ...viewer, role: "editor", display_name: "Editor User" };
const admin = { ...viewer, role: "admin", display_name: "Admin User" };
const summary = {
  summaries: [{ cost_center: { code: "190", name: "Main" }, latest_sources: { system: { source: "system", available: true, batch_id: "s", report_date: "2026-09-17" }, audit: { source: "audit", available: true, batch_id: "a", report_date: "2026-09-16" } }, freshness: { warning: true, status: "report_dates_differ", message: "System and audit report dates differ; they are not a shared cutoff." }, metrics: { current_system_distinct_asset_count: 4, found_count: 2, returned_count: 1, review_required_count: 0, unresolved_audit_case_count: 1, pending_not_accounted_count: 1 } }], page: { limit: 100, offset: 0, has_more: false, total_count: 1 }, selection_rule: "Server selection", metric_scope: "Server metrics",
};
function json(data: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } })); }
function installFetch(user: object | null = viewer) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === "/api/auth/me") return user ? json(user) : json({ detail: "Authentication required" }, 401);
    if (url === "/api/auth/login") return json(viewer);
    if (url === "/api/dashboard/summaries") return json(summary);
    if (url.startsWith("/api/dashboard/system-drilldown")) return json({ cost_center: { code: "190", name: "Main" }, source: summary.summaries[0].latest_sources.system, groups: [], page: { limit: 100, offset: 0, has_more: false, total_count: 0 } });
    if (url === "/api/operations/import-history") return json({ items: [], page: {} });
    if (url === "/api/operations/review-queue") return json({ items: [], queue_counts: { total: 0 }, page: {} });
    if (url === "/api/current-states") return json({ states: [] });
    if (url.startsWith("/api/imports/")) return json({ source: url.endsWith("system") ? "system" : "audit", row_count: 3 }, 201);
    if (url === "/api/auth/logout") return Promise.resolve(new Response(null, { status: 204 }));
    return json({ detail: "not found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock); return fetchMock;
}

describe("session and presentation views", () => {
  beforeEach(() => vi.unstubAllGlobals());
  afterEach(() => cleanup());
  it("shows a login form after an anonymous session check and signs in without storage", async () => {
    const fetchMock = installFetch(null); render(<App />);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "alex" } }); fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Viewer User")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/login", expect.objectContaining({ credentials: "include", method: "POST" }));
    expect(localStorage.length).toBe(0);
  });
  it("renders upload affordances for lowercase editor and admin roles, but not viewers", async () => {
    installFetch(viewer); const { unmount } = render(<App />); await screen.findByRole("heading", { name: "Executive dashboard" });
    expect(screen.queryByRole("button", { name: "Uploads" })).not.toBeInTheDocument(); unmount();

    installFetch(editor); const editorView = render(<App />); await screen.findByRole("heading", { name: "Executive dashboard" });
    expect(screen.getByRole("button", { name: "Uploads" })).toBeInTheDocument(); editorView.unmount();

    installFetch(admin); render(<App />); await screen.findByRole("heading", { name: "Executive dashboard" });
    expect(screen.getByRole("button", { name: "Uploads" })).toBeInTheDocument();
  });
  it("renders server freshness warning and does not conceal different report dates", async () => {
    installFetch(); render(<App />); expect(await screen.findByText(/not a shared cutoff/)).toBeInTheDocument();
    expect(screen.getByText("2026-09-17")).toBeInTheDocument(); expect(screen.getByText("2026-09-16")).toBeInTheDocument();
  });
  it("renders a dashboard request error", async () => {
    const fetchMock = installFetch(); fetchMock.mockImplementation((url: string) => url === "/api/auth/me" ? json(viewer) : url === "/api/dashboard/summaries" ? json({ detail: "Unavailable now" }, 503) : json({}));
    render(<App />); expect(await screen.findByRole("alert")).toHaveTextContent("Unavailable now");
  });
  it("renders operational empty states supplied by the server", async () => {
    installFetch(); render(<App />); await screen.findByRole("heading", { name: "Executive dashboard" }); fireEvent.click(screen.getByRole("button", { name: "Operations" }));
    expect(await screen.findByText("No imports match this view.")).toBeInTheDocument(); expect(screen.getByText("No items require review.")).toBeInTheDocument();
  });
  it("submits editor system upload as multipart and announces the server result", async () => {
    const fetchMock = installFetch(editor); render(<App />); await screen.findByRole("heading", { name: "Executive dashboard" });
    fireEvent.click(screen.getByRole("button", { name: "Uploads" }));
    const form = screen.getByRole("heading", { name: "System report" }).closest("form")!;
    fireEvent.change(within(form).getByLabelText("Workbook"), { target: { files: [new File(["workbook"], "report.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" })] } });
    fireEvent.change(within(form).getByLabelText("Report date"), { target: { value: "2026-09-17" } });
    fireEvent.submit(form);
    expect(await screen.findByText("system import accepted with 3 rows.")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/imports/system", expect.objectContaining({ method: "POST", credentials: "include" })));
    const uploadCall = fetchMock.mock.calls.find(([url]) => url === "/api/imports/system");
    expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData);
  });
});
