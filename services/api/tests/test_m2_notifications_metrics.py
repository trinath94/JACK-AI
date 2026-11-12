"""Milestone 2: notification centre and system metrics."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from conftest import WS_URL
from jack_api.health import ProbeResult


def _task(client: TestClient) -> str:
    return str(client.post("/v1/tasks", json={"command_text": "notify me"}).json()["id"])


def test_terminal_task_states_create_notifications(client: TestClient) -> None:
    tid = _task(client)
    client.post(f"/v1/tasks/{tid}/cancel", json={})
    body = client.get("/v1/notifications").json()
    assert body["unread"] == 1
    n = body["items"][0]
    assert n["kind"] == "task.cancelled" and n["task_id"] == tid and n["body"] == "notify me"


def test_routine_transitions_do_not_notify(client: TestClient) -> None:
    tid = _task(client)
    client.post(f"/v1/tasks/{tid}/transition", json={"to_status": "UNDERSTANDING"})
    assert client.get("/v1/notifications").json()["total"] == 0


def test_notification_pushed_over_ws(client: TestClient, token: str) -> None:
    with client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive_json()
        ws.receive_json()
        tid = _task(client)
        client.post(f"/v1/tasks/{tid}/transition", json={"to_status": "FAILED"})
        for _ in range(30):
            msg = ws.receive_json()
            if msg["topic"] == "notification.created":
                assert msg["data"]["level"] == "error"
                assert msg["data"]["title"] == "Task failed"
                break
        else:
            raise AssertionError("notification.created not received")


def test_mark_read_and_read_all(client: TestClient) -> None:
    for _ in range(3):
        client.post(f"/v1/tasks/{_task(client)}/cancel", json={})
    items = client.get("/v1/notifications").json()["items"]
    assert client.post(f"/v1/notifications/{items[0]['id']}/read").status_code == 204
    body = client.get("/v1/notifications").json()
    assert body["unread"] == 2
    assert len(client.get("/v1/notifications", params={"unread_only": True}).json()["items"]) == 2
    assert client.post("/v1/notifications/read-all").json() == {"marked": 2}
    assert client.get("/v1/notifications").json()["unread"] == 0
    assert client.post("/v1/notifications/nope/read").status_code == 404


def test_health_degradation_and_recovery_notify(client: TestClient) -> None:
    state = {"status": "healthy"}

    async def flaky() -> ProbeResult:
        return ProbeResult(state["status"], "simulated")  # type: ignore[arg-type]

    client.app.state.svc.health.register("flaky", flaky)  # type: ignore[attr-defined]
    time.sleep(0.5)  # first observation is not news
    state["status"] = "unhealthy"
    _wait_for_title(client, "Flaky is unhealthy")
    state["status"] = "healthy"
    _wait_for_title(client, "Flaky recovered")


def _wait_for_title(client: TestClient, title: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any(n["title"] == title for n in client.get("/v1/notifications").json()["items"]):
            return
        time.sleep(0.1)
    raise AssertionError(f"notification {title!r} not created")


def test_system_metrics(client: TestClient) -> None:
    m = client.get("/v1/system/metrics").json()
    assert 0 <= m["cpu_percent"] <= 100 * m["cpu_count"]
    assert 0 < m["memory_used_bytes"] <= m["memory_total_bytes"]
    assert 0 <= m["disk_percent"] <= 100
    assert m["service_rss_bytes"] > 10_000_000  # a real Python process
    assert m["uptime_s"] > 0


def test_metrics_streamed_to_connected_clients(client: TestClient, token: str) -> None:
    with client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "auth", "token": token})
        for _ in range(30):
            msg = ws.receive_json()
            if msg["topic"] == "system.metrics":
                assert "memory_percent" in msg["data"]
                return
    raise AssertionError("system.metrics not received")


def test_new_routes_require_auth(anon: TestClient) -> None:
    for method, path in [("get", "/v1/voice/status"), ("post", "/v1/voice/ptt/start"),
                         ("patch", "/v1/voice/settings"), ("get", "/v1/notifications"),
                         ("get", "/v1/system/metrics")]:
        assert getattr(anon, method)(path).status_code == 401, path
