import type { BackendConnection, BackendStatus } from "@jack/shared-types";
import type { DesktopBridge } from "../lib/backend";

export const CONN: BackendConnection = {
  baseUrl: "http://127.0.0.1:5555",
  wsUrl: "ws://127.0.0.1:5555/v1/ws",
  token: "t".repeat(64),
};

export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  // test helpers
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  emit(topic: string, data: unknown) {
    this.onmessage?.({ data: JSON.stringify({ type: "event", topic, ts: new Date().toISOString(), data }) });
  }
  drop() {
    this.readyState = 3;
    this.onclose?.();
  }
}

export function fakeBridge(status: BackendStatus["state"] = "running"): DesktopBridge & {
  push: (s: BackendStatus) => void;
} {
  let listener: ((s: BackendStatus) => void) | null = null;
  const current: BackendStatus = { state: status, restarts: 0, lastError: null, pid: 42 };
  return {
    isNative: true,
    getConnection: async () => CONN,
    getStatus: async () => current,
    restart: async () => {},
    onStatus: async (cb) => {
      listener = cb;
      return () => (listener = null);
    },
    push: (s) => listener?.(s),
  };
}
