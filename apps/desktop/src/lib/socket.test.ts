import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CONN, FakeWebSocket } from "../test/fakes";
import { JackSocket, type SocketState } from "./socket";

describe("JackSocket", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("authenticates with the first frame and reports open on hello", () => {
    const states: SocketState[] = [];
    const s = new JackSocket(CONN, {
      onEvent: () => {},
      onState: (st) => states.push(st),
      WebSocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    s.start();
    const ws = FakeWebSocket.instances[0]!;
    ws.open();
    expect(JSON.parse(ws.sent[0]!)).toEqual({ type: "auth", token: CONN.token });
    expect(states).toEqual(["connecting"]);
    ws.emit("hello", { version: "0.1.0" });
    expect(states).toEqual(["connecting", "open"]);
    s.stop();
  });

  it("reconnects with backoff after the connection drops", () => {
    const s = new JackSocket(CONN, {
      onEvent: () => {},
      onState: () => {},
      WebSocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    s.start();
    FakeWebSocket.instances[0]!.drop();
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.instances).toHaveLength(2);
    FakeWebSocket.instances[1]!.drop();
    vi.advanceTimersByTime(999);
    expect(FakeWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(3);
    s.stop();
  });

  it("does not reconnect after stop", () => {
    const s = new JackSocket(CONN, {
      onEvent: () => {},
      onState: () => {},
      WebSocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    s.start();
    s.stop();
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("ignores malformed frames", () => {
    const onEvent = vi.fn();
    const s = new JackSocket(CONN, { onEvent, onState: () => {}, WebSocketImpl: FakeWebSocket as unknown as typeof WebSocket });
    s.start();
    FakeWebSocket.instances[0]!.onmessage?.({ data: "not json" });
    expect(onEvent).not.toHaveBeenCalled();
    s.stop();
  });
});
