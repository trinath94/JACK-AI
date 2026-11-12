import { describe, expect, it, vi } from "vitest";
import { CONN } from "../test/fakes";
import { ApiRequestError, JackApi } from "./api";

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("JackApi", () => {
  it("sends the bearer token and JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, { id: "1", status: "RECEIVED" }));
    const api = new JackApi(CONN, fetchMock);
    await api.createTask("build a website", "voice");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://127.0.0.1:5555/v1/tasks");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe(`Bearer ${CONN.token}`);
    expect(JSON.parse(init.body)).toEqual({ command_text: "build a website", source: "voice" });
  });

  it("parses the error envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(409, { error: { code: "invalid_transition", message: "nope", request_id: null } }),
    );
    const api = new JackApi(CONN, fetchMock);
    const err = await api.taskAction("x", "resume").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err).toMatchObject({ status: 409, code: "invalid_transition", message: "nope" });
  });

  it("encodes task ids and list params", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, { items: [], total: 0 }));
    const api = new JackApi(CONN, fetchMock as unknown as typeof fetch);
    await api.listTasks({ status: "PAUSED", limit: 5 });
    expect((fetchMock.mock.calls[0] as unknown[])[0]).toBe("http://127.0.0.1:5555/v1/tasks?status=PAUSED&limit=5&offset=0");
    await api.getTask("a/b");
    expect((fetchMock.mock.calls[1] as unknown[])[0]).toBe("http://127.0.0.1:5555/v1/tasks/a%2Fb");
  });
});
