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

  it("shows real wake word and speech recognition status", async () => {
    renderApp();
    await connect();
    expect(await screen.findByText(/Wake word "Jack": off/)).toBeInTheDocument();
    expect(screen.getByText("Speech recognition: small.en")).toBeInTheDocument();
  });

  it("sends a typed command to requirement discovery and shows the task from the live feed", async () => {
    renderApp();
    const ws = await connect();
    const input = await screen.findByLabelText("Command");
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { value: "Build a corporate website" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(`${CONN.baseUrl}/v1/discovery/messages`, expect.objectContaining({ method: "POST" })),
    );
    const exchange = await screen.findByTestId("discovery-exchange");
    expect(exchange).toHaveTextContent("What is the website for?");
    // The next message answers the same conversation, and option chips answer in one click.
    expect(screen.getByLabelText("Command")).toHaveAttribute("placeholder", "Answer JACK…");
    fireEvent.click(within(exchange).getByRole("button", { name: "My company or business" }));
    expect(await screen.findByText(/Would you like a corporate website/)).toBeInTheDocument();
    const posted = service.state.calls.filter((c) => c.path === "/v1/discovery/messages").map((c) => c.body as { session_id: string | null });
    expect(posted[0]!.session_id).toBeNull();
    expect(posted[1]!.session_id).toBe("sess-1");
    // Navigating away and back keeps the conversation: the next message still answers it.
    fireEvent.keyDown(window, { key: "2", ctrlKey: true });
    fireEvent.keyDown(window, { key: "1", ctrlKey: true });
    expect(await screen.findByTestId("discovery-exchange")).toHaveTextContent(/Would you like a corporate website/);
    await waitFor(() => expect(screen.getByLabelText("Command")).toHaveAttribute("placeholder", "Answer JACK…"));
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
    expect(screen.getByTestId("voice-status")).toHaveTextContent("listening");
    fireEvent.pointerUp(btn);
    await waitFor(() => expect(service.state.calls.some((c) => c.path === "/v1/voice/ptt/stop")).toBe(true));
    act(() => {
      ws.emit("voice.state", { state: "processing" });
      ws.emit("voice.utterance", { trigger: "ptt", captured_ms: 1500, transcribed: true, transcript: "build a corporate website", reply: "Got it.", stopped_by: "released", task_id: "t1" });
      ws.emit("voice.reply", { text: "Got it. I've added it to your tasks." });
      ws.emit("voice.state", { state: "idle" });
    });
    const ex = await screen.findByTestId("last-exchange");
    expect(ex).toHaveTextContent("You: build a corporate website");
    expect(ex).toHaveTextContent("JACK: Got it. I've added it to your tasks.");
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
  });

  it("voice page manages models, wake word, replies and history", async () => {
    renderApp();
    const ws = await connect();
    fireEvent.keyDown(window, { key: "4", ctrlKey: true });
    const models = await screen.findByRole("list", { name: "Speech models" });
    await within(models).findByText("base.en");
    fireEvent.click(within(models).getByRole("button", { name: /Download/ }));
    await waitFor(() => expect(service.state.calls.some((c) => c.path === "/v1/voice/models/base.en/download")).toBe(true));
    act(() => ws.emit("voice.models", service.state.models.map((m) => (m.name === "base.en" ? { ...m, status: "downloading", downloaded_mb: 72.5 } : m))));
    expect(await screen.findByRole("meter", { name: "Downloading base.en" })).toHaveAttribute("aria-valuenow", "50");

    fireEvent.click(screen.getByRole("switch", { name: /Listen for "Jack"/ }));
    await waitFor(() => expect(service.state.calls.some((c) => c.method === "PATCH" && (c.body as { wake_word_enabled?: boolean }).wake_word_enabled === true)).toBe(true));

    await within(screen.getByLabelText("Voice")).findByText("Microsoft Zira");
    fireEvent.click(screen.getByRole("button", { name: /Test voice/ }));
    await waitFor(() => expect(service.state.calls.some((c) => c.path === "/v1/voice/speak")).toBe(true));

    const hist = await screen.findByRole("list", { name: "Conversation history" });
    expect(within(hist).getByText("build a website")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Clear/ }));
    await waitFor(() => expect(service.state.calls.some((c) => c.method === "DELETE" && c.path === "/v1/voice/history")).toBe(true));
  });

  it("shows the standby state when the wake word is listening", async () => {
    renderApp();
    const ws = await connect();
    act(() => {
      ws.emit("voice.settings", { ...service.state.voice.settings, wake_word_enabled: true });
      ws.emit("voice.state", { state: "standby" });
    });
    expect(await screen.findByText(/Wake word "Jack": listening/)).toBeInTheDocument();
    // After "Jack", JACK listens without the button being held: don't tell the user to release it.
    act(() => ws.emit("voice.state", { state: "listening" }));
    expect(await screen.findByRole("button", { name: /Listening for your command/ })).toBeInTheDocument();
    expect(screen.queryByText(/release to stop/)).not.toBeInTheDocument();
    act(() => ws.emit("voice.state", { state: "standby" }));
    expect(screen.getByTestId("voice-status")).toHaveTextContent("wake word on");
    expect(screen.getByTestId("voice-orb")).toHaveAttribute("data-state", "standby");
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


describe("Usage and Billing (M4)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    localStorage.clear();
    service = mockService();
    vi.stubGlobal("fetch", vi.fn(service.fetchImpl));
  });

  it("stores an API key without ever showing it back, then tests the connection", async () => {
    renderApp();
    const ws = await connect();
    fireEvent.keyDown(window, { key: "5", ctrlKey: true });
    expect(await screen.findByText("Windows Credential Manager")).toBeInTheDocument();
    const input = screen.getByLabelText("Anthropic API key");
    expect(input).toHaveAttribute("type", "password");
    fireEvent.change(input, { target: { value: "sk-ant-api03-SECRETSECRETSECRET9z9z" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(service.state.calls.some((c) => c.method === "PUT" && c.path === "/v1/ai/anthropic/key")).toBe(true));
    act(() => ws.emit("ai.status", { changed: "anthropic.key" }));
    expect(await screen.findByTestId("key-hint")).toHaveTextContent("sk-ant-…9z9z");
    await waitFor(() => expect(screen.getByRole("button", { name: /Test connection/ })).toHaveFocus());
    expect(document.body.textContent).not.toContain("SECRETSECRETSECRET");
    expect(await screen.findByRole("option", { name: "Claude Future 9 (no price data)" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Test connection/ }));
    expect(await screen.findByTestId("test-ok")).toHaveTextContent("claude-opus-5-5");
  });

  it("separates API spend from Claude Code usage and saves limits", async () => {
    service.state.ai.month.api = { ...service.state.ai.month.api, requests: 3, cost_usd: "1.2345" };
    service.state.ai.month.claude_code = { ...service.state.ai.month.claude_code, requests: 2, cost_usd: "0.5" };
    service.state.ai.month.monthly_limit_usd = "10";
    service.state.ai.month.limit_used_pct = 12.3;
    renderApp();
    await connect();
    fireEvent.keyDown(window, { key: "5", ctrlKey: true });
    expect(await screen.findByTestId("api-spend")).toHaveTextContent("$1.2345");
    expect(screen.getByTestId("cc-usage")).toHaveTextContent("$0.50");
    expect(screen.getByText(/never counted toward API spend/)).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Monthly limit $10.00" })).toHaveAttribute("aria-valuenow", "12");
    fireEvent.change(screen.getByLabelText("Monthly ($)"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("Per task ($)"), { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save limits" }));
    await waitFor(() => {
      const patch = service.state.calls.find((c) => c.path === "/v1/ai/settings");
      expect(patch?.body).toEqual({ limits: { monthly_usd: "25", per_task_usd: "2.5", per_project_usd: null, alert_pct: [50, 80, 100] } });
    });
  });

  it("detects Claude Code and keeps provider fallback opt-in", async () => {
    renderApp();
    await connect();
    fireEvent.keyDown(window, { key: "5", ctrlKey: true });
    fireEvent.click(await screen.findByRole("button", { name: /Detect/ }));
    const det = await screen.findByLabelText("Claude Code detection");
    expect(det).toHaveTextContent("2.1.322");
    expect(det).toHaveTextContent("yes (claude.ai)");
    const fb = screen.getByRole("switch", { name: /Fall back to the other provider/ });
    expect(fb).not.toBeChecked();
    fireEvent.click(fb);
    await waitFor(() => expect(service.state.calls.some((c) => c.path === "/v1/ai/settings" && JSON.stringify(c.body) === '{"fallback":{"enabled":true}}')).toBe(true));
  });

  it("test console shows the answer with model, tokens and cost", async () => {
    renderApp();
    await connect();
    fireEvent.keyDown(window, { key: "5", ctrlKey: true });
    fireEvent.change(await screen.findByLabelText("Prompt"), { target: { value: "Say hello" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
    const out = await screen.findByTestId("console-result");
    expect(out).toHaveTextContent("Hello from Claude");
    expect(out).toHaveTextContent("20 in / 6 out");
    expect(out).toHaveTextContent("$0.0002");
  });

  it("home shows Claude as not configured instead of a fake status", async () => {
    renderApp();
    await connect();
    const list = await screen.findByRole("list", { name: "Integrations" });
    expect(await within(list).findByText("not configured")).toBeInTheDocument();
    expect(within(list).getByTestId("home-api-spend")).toHaveTextContent("$0.00");
  });
});

describe("Command Centre (M5)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    localStorage.clear();
    service = mockService();
    vi.stubGlobal("fetch", vi.fn(service.fetchImpl));
  });

  async function openCommandCentre() {
    renderApp();
    const ws = await connect();
    fireEvent.keyDown(window, { key: "6", ctrlKey: true });
    return ws;
  }

  it("runs a requirements conversation and approves the specification", async () => {
    await openCommandCentre();
    const input = await screen.findByLabelText("New request");
    fireEvent.change(input, { target: { value: "Build a professional website" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    const convo = await screen.findByRole("list", { name: "Conversation" });
    expect(within(convo).getByText(/What is the website for\?/)).toBeInTheDocument();
    const chips = screen.getByLabelText("Suggested answers");
    fireEvent.click(within(chips).getByRole("button", { name: "My company or business" }));
    expect(await screen.findByText(/Would you like a corporate website/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "A corporate website" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(await screen.findByTestId("spec-title")).toHaveTextContent("Corporate website");
    expect(screen.getByText("needs approval")).toBeInTheDocument();
    // Answers show where they came from; assumptions are marked as such.
    expect(screen.getAllByText("you said").length).toBeGreaterThan(0);
    expect(screen.getAllByText("assumed").length).toBeGreaterThan(0);
    expect(screen.getByText("Milestone 11")).toBeInTheDocument(); // honest: not built yet
    fireEvent.click(screen.getByRole("button", { name: /Approve specification/ }));
    expect(await screen.findByText(/Specification complete/)).toBeInTheDocument();
    expect(service.state.calls.some((c) => c.path === "/v1/discovery/sessions/sess-1/approve")).toBe(true);
  });

  it("edits an assumption from the specification", async () => {
    service.state.discovery.message("Build a website");
    service.state.discovery.message("My company", "sess-1");
    service.state.discovery.message("Corporate", "sess-1");
    await openCommandCentre();
    await screen.findByTestId("spec-title");
    fireEvent.click(screen.getAllByRole("button", { name: "Change Visual style" })[0]!);
    fireEvent.change(screen.getByRole("combobox", { name: "Visual style" }), { target: { value: "bold" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const put = service.state.calls.find((c) => c.method === "PUT" && c.path === "/v1/discovery/sessions/sess-1/answers/style");
      expect(put?.body).toEqual({ value: "bold" });
    });
    expect((await screen.findAllByText("Bold and colourful")).length).toBeGreaterThan(0);
  });

  it("changes how JACK asks", async () => {
    await openCommandCentre();
    const engine = await screen.findByRole("combobox", { name: "Understanding engine" });
    fireEvent.change(engine, { target: { value: "local" } });
    await waitFor(() => expect(service.state.discovery.settings.engine).toBe("local"));
    fireEvent.click(screen.getByRole("switch", { name: /Listen for my answer/ }));
    await waitFor(() => expect(service.state.discovery.settings.followup_listen).toBe(false));
  });

  it("shows when JACK is listening for the answer", async () => {
    service.state.discovery.message("Build a website");
    const ws = await openCommandCentre();
    await screen.findByRole("list", { name: "Conversation" });
    act(() => ws.emit("voice.state", { state: "listening" }));
    act(() => ws.emit("voice.followup", { wait_s: 8 }));
    expect(await screen.findByText(/Listening for your answer/)).toBeInTheDocument();
  });
});
