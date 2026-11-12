import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { BackendProvider } from "./lib/backend";
import { NAV } from "./lib/nav";
import { CONN, FakeWebSocket, METRICS, TASK, fakeBridge, mockService, type FakeBridge } from "./test/fakes";

let service: ReturnType<typeof mockService>;

function renderApp(bridge: FakeBridge = fakeBridge()) {
  render(
    <BackendProvider bridge={bridge} WebSocketImpl={FakeWebSocket as unknown as typeof WebSocket}>
      <App />
    </BackendProvider>,
  );
  return bridge;
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
  await screen.findByText("live open");
  return ws;
}

describe("App", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    localStorage.clear();
    service = mockService();
    vi.stubGlobal("fetch", vi.fn(service.fetchImpl));
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
    const comps = screen.getByRole("list", { name: "Component health" });
    expect(within(comps).getByText("sqlite")).toBeInTheDocument();
  });

  it("does not claim wake word or speech recognition exist yet", async () => {
    renderApp();
    await connect();
    expect(await screen.findByText(/Wake word "Jack": arrives in Milestone 3/)).toBeInTheDocument();
    expect(screen.getByText(/Speech recognition: Milestone 3/)).toBeInTheDocument();
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
  });

  it("marks unimplemented sections honestly", () => {
    renderApp();
    fireEvent.click(screen.getByRole("button", { name: /Deployments/ }));
    expect(screen.getByText("Deployments is not implemented yet")).toBeInTheDocument();
    expect(screen.getByText(/Milestone 13/)).toBeInTheDocument();
  });

  it("reflects supervisor failures and turns the orb offline", async () => {
    const bridge = renderApp();
    await connect();
    act(() => bridge.push({ state: "failed", restarts: 5, lastError: "service process exited", pid: null }));
    expect(await screen.findByText("service failed")).toBeInTheDocument();
    expect(screen.getByText("service process exited")).toBeInTheDocument();
    expect(screen.getByTestId("voice-orb")).toHaveAttribute("data-state", "offline");
  });

  it("supports keyboard shortcuts, including Ctrl+K and the ? dialog", async () => {
    renderApp();
    await connect();
    fireEvent.keyDown(window, { key: "3", ctrlKey: true });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Security");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Home");
    await waitFor(() => expect(screen.getByLabelText("Command")).toHaveFocus());
    fireEvent.keyDown(document.body, { key: "?" });
    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(within(dialog).getByText("Ctrl+Shift+Space")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument();
  });
});

describe("Voice", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    localStorage.clear();
    service = mockService();
    vi.stubGlobal("fetch", vi.fn(service.fetchImpl));
  });

  it("push-to-talk opens on press, closes on release, and the orb follows the level", async () => {
    renderApp();
    const ws = await connect();
    const btn = await screen.findByRole("button", { name: /hold to talk/i });
    await waitFor(() => expect(btn).toBeEnabled());
    fireEvent.pointerDown(btn);
    await waitFor(() => expect(service.state.calls.some((c) => c.path === "/v1/voice/ptt/start")).toBe(true));
    act(() => {
      ws.emit("voice.state", { state: "listening" });
      ws.emit("voice.level", { level: 0.8 });
    });
    expect(screen.getByTestId("voice-orb")).toHaveAttribute("data-state", "listening");
    expect(screen.getByTestId("voice-status")).toHaveTextContent("voice listening");
    fireEvent.pointerUp(btn);
    await waitFor(() => expect(service.state.calls.some((c) => c.path === "/v1/voice/ptt/stop")).toBe(true));
    act(() => {
      ws.emit("voice.state", { state: "idle" });
      ws.emit("voice.utterance", { captured_ms: 1500, transcribed: false, transcript: null, detail: "Speech recognition arrives in Milestone 3; the captured audio was discarded.", stopped_by: "released" });
    });
    expect(await screen.findByTestId("last-utterance")).toHaveTextContent("Heard 1.5 s of audio");
    expect(screen.getByTestId("last-utterance")).toHaveTextContent("Milestone 3");
  });

  it("disables push-to-talk while muted and explains why", async () => {
    service = mockService({ voice: { ...mockService().state.voice, state: "disabled", settings: { ...mockService().state.voice.settings, muted: true } } });
    vi.stubGlobal("fetch", vi.fn(service.fetchImpl));
    renderApp();
    await connect();
    const btn = await screen.findByRole("button", { name: /hold to talk/i });
    expect(btn).toBeDisabled();
    expect(screen.getByText("Microphone is muted")).toBeInTheDocument();
    expect(screen.getByTestId("voice-status")).toHaveTextContent("mic muted");
  });

  it("shows service errors from push-to-talk", async () => {
    service.state.pttError = { code: "audio_unavailable", message: "could not open microphone: device busy" };
    renderApp();
    await connect();
    const btn = await screen.findByRole("button", { name: /hold to talk/i });
    await waitFor(() => expect(btn).toBeEnabled());
    fireEvent.pointerDown(btn);
    expect(await screen.findByRole("alert")).toHaveTextContent("device busy");
  });

  it("shows errors raised by the native hotkey", async () => {
    const bridge = renderApp();
    await connect();
    act(() => bridge.voiceError("The microphone is muted"));
    expect(await screen.findByRole("alert")).toHaveTextContent("The microphone is muted");
  });

  it("surfaces a microphone that delivers no audio", async () => {
    renderApp();
    const ws = await connect();
    act(() => ws.emit("voice.error", { code: "no_audio", message: "No audio is arriving from the microphone (Headset)." }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No audio is arriving");
  });

  it("syncs mute state to the tray", async () => {
    const bridge = renderApp();
    const ws = await connect();
    await waitFor(() => expect(bridge.trayCalls.at(-1)).toEqual([false, "idle"]));
    act(() => {
      ws.emit("voice.settings", { ...service.state.voice.settings, muted: true });
      ws.emit("voice.state", { state: "disabled" });
    });
    await waitFor(() => expect(bridge.trayCalls.at(-1)).toEqual([true, "disabled"]));
  });

  it("voice page saves microphone, mute and privacy settings", async () => {
    renderApp();
    await connect();
    fireEvent.keyDown(window, { key: "4", ctrlKey: true });
    const select = await screen.findByLabelText("Microphone");
    await within(select).findByText(/Headset \(WASAPI\)/);
    fireEvent.change(select, { target: { value: "WASAPI:Headset" } });
    fireEvent.click(screen.getByRole("switch", { name: "Privacy mode" }));
    await waitFor(() => {
      const patches = service.state.calls.filter((c) => c.method === "PATCH").map((c) => c.body);
      expect(patches).toEqual([{ input_device_id: "WASAPI:Headset" }, { privacy_mode: true }]);
    });
    expect(screen.getByRole("switch", { name: /Listen for "Jack"/ })).toBeDisabled();
  });
});

describe("Notifications, metrics, settings", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    localStorage.clear();
  });

  it("notification centre shows unread count, live arrivals, and marks read", async () => {
    service = mockService({
      notifications: [
        { id: "n1", level: "error", kind: "task.failed", title: "Task failed", body: "Build site", task_id: null, created_at: "2026-11-12T10:00:00Z", read_at: null },
      ],
    });
    vi.stubGlobal("fetch", vi.fn(service.fetchImpl));
    renderApp();
    const ws = await connect();
    const bell = await screen.findByRole("button", { name: "Notifications (1 unread)" });
    act(() =>
      ws.emit("notification.created", { id: "n2", level: "success", kind: "task.completed", title: "Task completed", body: null, task_id: null, created_at: "2026-11-12T11:00:00Z", read_at: null }),
    );
    expect(await screen.findByRole("button", { name: "Notifications (2 unread)" })).toBe(bell);
    fireEvent.click(bell);
    const panel = screen.getByRole("dialog", { name: "Notification centre" });
    expect(within(panel).getByText("Task completed")).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(service.state.calls.some((c) => c.path === "/v1/notifications/read-all")).toBe(true));
    act(() => ws.emit("notification.read", { ids: ["n1", "n2"] }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument());
  });

  it("renders live system metrics", async () => {
    service = mockService();
    vi.stubGlobal("fetch", vi.fn(service.fetchImpl));
    renderApp();
    const ws = await connect();
    const cpu = await screen.findByRole("meter", { name: "CPU (8 cores)" });
    expect(cpu).toHaveAttribute("aria-valuenow", "13");
    act(() => ws.emit("system.metrics", { ...METRICS, cpu_percent: 91 }));
    await waitFor(() => expect(screen.getByRole("meter", { name: "CPU (8 cores)" })).toHaveAttribute("aria-valuenow", "91"));
  });

  it("toggles start with Windows", async () => {
    service = mockService();
    vi.stubGlobal("fetch", vi.fn(service.fetchImpl));
    const bridge = renderApp();
    fireEvent.keyDown(window, { key: ",", ctrlKey: true });
    const sw = await screen.findByRole("switch", { name: /Start JACK when I sign in/ });
    await waitFor(() => expect(sw).toBeEnabled());
    fireEvent.click(sw);
    await waitFor(() => expect(bridge.autostartOn).toBe(true));
    await waitFor(() => expect(sw).toBeChecked());
  });

  it("switches to light theme", async () => {
    service = mockService();
    vi.stubGlobal("fetch", vi.fn(service.fetchImpl));
    renderApp();
    expect(document.documentElement).toHaveClass("dark");
    fireEvent.keyDown(window, { key: ",", ctrlKey: true });
    fireEvent.click(screen.getByRole("radio", { name: "light" }));
    expect(document.documentElement).not.toHaveClass("dark");
  });
});
