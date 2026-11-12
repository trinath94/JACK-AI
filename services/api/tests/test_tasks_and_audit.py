"""Milestone 1 acceptance items 5–6 plus health/system routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from conftest import WS_URL
from jack_api.db import AuditEvent
from jack_api.tasks import ACTIVE, HOLD, TERMINAL, TaskStatus, allowed_targets


def _create(client: TestClient, text: str = "Jack, build a corporate website") -> dict:
    r = client.post("/v1/tasks", json={"command_text": text, "source": "voice"})
    assert r.status_code == 201, r.text
    return r.json()


def test_health_report(client: TestClient) -> None:
    body = client.get("/v1/health").json()
    assert body["status"] in {"healthy", "degraded"}
    assert body["version"] == "0.1.0"
    db = next(c for c in body["components"] if c["name"] == "database")
    assert db["status"] == "healthy"


def test_system_info(client: TestClient) -> None:
    info = client.get("/v1/system/info").json()
    assert info["database_backend"] in {"sqlite", "postgresql"}


def test_create_and_get_task(client: TestClient) -> None:
    t = _create(client)
    assert t["status"] == "RECEIVED"
    assert t["title"] == "Jack, build a corporate website"
    detail = client.get(f"/v1/tasks/{t['id']}").json()
    assert [e["to_status"] for e in detail["events"]] == ["RECEIVED"]


def test_create_task_validation(client: TestClient) -> None:
    assert client.post("/v1/tasks", json={"command_text": ""}).status_code == 422
    assert client.post("/v1/tasks", json={"command_text": "x" * 4001}).status_code == 422
    r = client.post("/v1/tasks", json={"command_text": "hi", "admin": True})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_unknown_task_404(client: TestClient) -> None:
    r = client.get("/v1/tasks/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_full_happy_path(client: TestClient) -> None:
    t = _create(client)
    path = ["UNDERSTANDING", "REQUIREMENTS", "PLANNING", "APPROVAL", "EXECUTION", "TESTING",
            "REPAIR", "TESTING", "RELEASE_PREPARATION", "DEPLOYMENT_APPROVAL", "DEPLOYMENT",
            "VERIFICATION", "COMPLETED"]
    for status in path:
        r = client.post(f"/v1/tasks/{t['id']}/transition", json={"to_status": status})
        assert r.status_code == 200, (status, r.text)
    final = client.get(f"/v1/tasks/{t['id']}").json()
    assert final["status"] == "COMPLETED"
    assert final["completed_at"] is not None
    assert [e["seq"] for e in final["events"]] == list(range(1, len(path) + 2))


def test_invalid_transition_409_and_audited(client: TestClient) -> None:
    t = _create(client)
    r = client.post(f"/v1/tasks/{t['id']}/transition", json={"to_status": "DEPLOYMENT"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_transition"
    audit = client.get("/v1/audit").json()["items"]
    assert any(a["action"] == "task.transition" and a["outcome"] == "denied" for a in audit)


def test_cannot_skip_deployment_approval(client: TestClient) -> None:
    t = _create(client)
    for s in ["UNDERSTANDING", "PLANNING", "EXECUTION", "TESTING", "RELEASE_PREPARATION"]:
        client.post(f"/v1/tasks/{t['id']}/transition", json={"to_status": s})
    r = client.post(f"/v1/tasks/{t['id']}/transition", json={"to_status": "DEPLOYMENT"})
    assert r.status_code == 409


def test_pause_resume_returns_to_previous_stage(client: TestClient) -> None:
    t = _create(client)
    for s in ["UNDERSTANDING", "PLANNING", "EXECUTION"]:
        client.post(f"/v1/tasks/{t['id']}/transition", json={"to_status": s})
    assert client.post(f"/v1/tasks/{t['id']}/pause", json={}).json()["status"] == "PAUSED"
    # Paused task cannot jump forward.
    r = client.post(f"/v1/tasks/{t['id']}/transition", json={"to_status": "TESTING"})
    assert r.status_code == 409
    resumed = client.post(f"/v1/tasks/{t['id']}/resume", json={"reason": "user"}).json()
    assert resumed["status"] == "EXECUTION"


def test_resume_when_not_paused_409(client: TestClient) -> None:
    t = _create(client)
    assert client.post(f"/v1/tasks/{t['id']}/resume", json={}).status_code == 409


def test_cancel_is_terminal(client: TestClient) -> None:
    t = _create(client)
    assert client.post(f"/v1/tasks/{t['id']}/cancel", json={}).json()["status"] == "CANCELLED"
    r = client.post(f"/v1/tasks/{t['id']}/transition", json={"to_status": "UNDERSTANDING"})
    assert r.status_code == 409


def test_failed_can_retry(client: TestClient) -> None:
    t = _create(client)
    client.post(f"/v1/tasks/{t['id']}/transition", json={"to_status": "FAILED"})
    r = client.post(f"/v1/tasks/{t['id']}/transition", json={"to_status": "RECEIVED"})
    assert r.status_code == 200
    assert r.json()["completed_at"] is None


def test_list_filter_and_pagination(client: TestClient) -> None:
    ids = [_create(client, f"task {i}")["id"] for i in range(3)]
    client.post(f"/v1/tasks/{ids[0]}/cancel", json={})
    assert client.get("/v1/tasks").json()["total"] == 3
    cancelled = client.get("/v1/tasks", params={"status": "CANCELLED"}).json()
    assert [t["id"] for t in cancelled["items"]] == [ids[0]]
    page = client.get("/v1/tasks", params={"limit": 1, "offset": 1}).json()
    assert len(page["items"]) == 1 and page["total"] == 3


def test_tasks_persist_across_restart(settings, token) -> None:  # type: ignore[no-untyped-def]
    from jack_api.app import create_app

    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765",
                    headers=headers) as c1:
        tid = c1.post("/v1/tasks", json={"command_text": "survive restart"}).json()["id"]
        c1.post(f"/v1/tasks/{tid}/transition", json={"to_status": "UNDERSTANDING"})
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765",
                    headers=headers) as c2:
        t = c2.get(f"/v1/tasks/{tid}").json()
        assert t["status"] == "UNDERSTANDING"
        assert c2.get("/v1/audit/verify").json()["valid"] is True


def test_task_events_broadcast_over_ws(client: TestClient, token: str) -> None:
    with client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive_json()  # hello
        ws.receive_json()  # health
        tid = _create(client)["id"]
        for _ in range(5):
            msg = ws.receive_json()
            if msg["topic"] == "task.created":
                assert msg["data"]["id"] == tid
                break
        else:
            pytest.fail("task.created not received")


def test_audit_chain_verifies_and_detects_tampering(client: TestClient) -> None:
    for i in range(5):
        _create(client, f"audit {i}")
    v = client.get("/v1/audit/verify").json()
    assert v["valid"] is True and v["checked"] >= 6

    db = client.app.state.svc.db  # type: ignore[attr-defined]
    with db.session() as s:
        s.execute(update(AuditEvent).where(AuditEvent.seq == 3).values(outcome="allowed2"))
    v = client.get("/v1/audit/verify").json()
    assert v == {"valid": False, "checked": 3, "first_invalid_seq": 3}


def test_state_machine_invariants() -> None:
    for s in TaskStatus:
        targets = allowed_targets(s, TaskStatus.EXECUTION if s in HOLD else None)
        if s in TERMINAL:
            assert targets <= {TaskStatus.RECEIVED}
        else:
            assert TaskStatus.CANCELLED in targets and TaskStatus.FAILED in targets
        if s in ACTIVE:
            assert HOLD <= targets
    # Production deployment is only reachable through DEPLOYMENT_APPROVAL.
    sources = [s for s in TaskStatus
               if TaskStatus.DEPLOYMENT in allowed_targets(s, None)]
    assert sources == [TaskStatus.DEPLOYMENT_APPROVAL]
