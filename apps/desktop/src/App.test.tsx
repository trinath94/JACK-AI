import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { BackendProvider } from "./lib/backend";
import { NAV } from "./lib/nav";
import { CONN, FakeWebSocket, fakeBridge } from "./test/fakes";

const TASK = {
  id: "11111111-1111-1111-1111-111111111111",
  title: "Build a corporate website",
  command_text: "Build a corporate website",
  source: "text",
  status: "RECEIVED",
  status_reason: null,
  mode: "assisted",
  created_at: "2026-11-12T10:00:00Z",
  updated_at: "2026-11-12T10:00:00Z",
  completed_at: null,
};

function renderApp(bridge = fakeBridge()) {
  return render(
    <BackendProvider bridge={bridge} WebSocketImpl={FakeWebSocket as unknown as typeof WebSocket}>
      <App />
    </BackendProvider>,
  );
}

async function connect() {
  await waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThan(0));
  const ws = FakeWebSocket.instances.at(-1)!;
  act(() => {
    ws.open();
    ws.emit("hello", { version: "0.1.0" });
    ws.emit("health.changed", {
      status: "healthy",
      components: [
        { name: "api", status: "healthy", detail: null, latency_ms: 0.1, checked_at: "" },
        { name: "database", status: "healthy", detail: "sqlite", latency_ms: 1, checked_at: "" },
      ],
    });
  });
  return ws;
}

describe("App", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith("/v1/tasks") && init?.method === "POST") {
          return new Response(JSON.stringify(TASK), { status: 201 });
        }
        if (url.includes("/v1/tasks?")) {
          return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 });
        }
        return new Response("{}", { status: 404 });
      }),
    );
  });

  it("renders all 16 Section 21 navigation entries", () => {
    renderApp();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    const labels = within(nav).getAllByRole("button").map((b) => b.textContent?.replace(/M\d+$/, ""));
    expect(labels).toEqual(NAV.map((n) => n.label));
    expect(NAV).toHaveLength(16);
  });

  it("shows live health once the service connects", async () => {
    renderApp();
    await connect();
    expect(await screen.findByText("live open")).toBeInTheDocument();
    const comps = screen.getByRole("list", { name: "Component health" });
    expect(within(comps).getByText("database")).toBeInTheDocument();
    expect(within(comps).getByText("sqlite")).toBeInTheDocument();
  });

  it("does not claim the microphone or wake word works yet", async () => {
    renderApp();
    expect(screen.getByText(/Microphone: not available until Milestone 3/)).toBeInTheDocument();
    expect(screen.getByTestId("voice-orb")).toHaveAttribute("data-state", "offline");
  });

  it("creates a task from a typed command and shows it from the live feed", async () => {
    renderApp();
    const ws = await connect();
    const input = await screen.findByLabelText("Command");
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { value: "Build a corporate website" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(`${CONN.baseUrl}/v1/tasks`, expect.objectContaining({ method: "POST" })),
    );
    act(() => ws.emit("task.created", TASK));
    const list = await screen.findByRole("list", { name: "Recent tasks" });
    expect(within(list).getByText("Build a corporate website")).toBeInTheDocument();
    expect(within(list).getByText("RECEIVED")).toBeInTheDocument();
  });

  it("marks unimplemented sections honestly", () => {
    renderApp();
    fireEvent.click(screen.getByRole("button", { name: /Deployments/ }));
    expect(screen.getByText("Deployments is not implemented yet")).toBeInTheDocument();
    expect(screen.getByText(/Milestone 13/)).toBeInTheDocument();
  });

  it("reflects supervisor failures", async () => {
    const bridge = fakeBridge("running");
    renderApp(bridge);
    await connect();
    act(() => bridge.push({ state: "failed", restarts: 5, lastError: "service process exited", pid: null }));
    expect(await screen.findByText("service failed")).toBeInTheDocument();
    expect(screen.getByText("service process exited")).toBeInTheDocument();
  });

  it("supports keyboard navigation shortcuts", () => {
    renderApp();
    fireEvent.keyDown(window, { key: "3", ctrlKey: true });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Security");
  });
});
