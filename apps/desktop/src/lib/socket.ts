import type { BackendConnection, WsEvent } from "@jack/shared-types";

export type SocketState = "connecting" | "open" | "closed";

export interface JackSocketOptions {
  onEvent: (e: WsEvent) => void;
  onState: (s: SocketState) => void;
  /** Injected for tests. */
  WebSocketImpl?: typeof WebSocket;
  pingIntervalMs?: number;
}

/**
 * Authenticated WebSocket with first-frame auth (browsers cannot set headers on upgrade)
 * and exponential reconnect (0.5 s → 10 s).
 */
export class JackSocket {
  private ws: WebSocket | null = null;
  private attempts = 0;
  private stopped = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;

  constructor(
    private readonly conn: BackendConnection,
    private readonly opts: JackSocketOptions,
  ) {}

  start() {
    this.stopped = false;
    this.open();
  }

  stop() {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.ws?.close(1000);
    this.ws = null;
  }

  private open() {
    const Impl = this.opts.WebSocketImpl ?? WebSocket;
    this.opts.onState("connecting");
    const ws = new Impl(this.conn.wsUrl);
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token: this.conn.token }));
    };
    ws.onmessage = (msg: MessageEvent) => {
      let event: WsEvent;
      try {
        event = JSON.parse(String(msg.data)) as WsEvent;
      } catch {
        return;
      }
      if (event.topic === "hello") {
        this.attempts = 0;
        this.opts.onState("open");
        if (this.pingTimer) clearInterval(this.pingTimer);
        this.pingTimer = setInterval(
          () => ws.readyState === 1 && ws.send(JSON.stringify({ type: "ping" })),
          this.opts.pingIntervalMs ?? 25_000,
        );
      }
      this.opts.onEvent(event);
    };
    ws.onclose = () => {
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.opts.onState("closed");
      if (this.stopped) return;
      const delay = Math.min(10_000, 500 * 2 ** this.attempts++);
      this.reconnectTimer = setTimeout(() => this.open(), delay);
    };
  }
}
