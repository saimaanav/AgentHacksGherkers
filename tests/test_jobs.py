"""Free-text jobs through a chosen agent and connectors, into the same layer: the demo's Fridays are one such job."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo

from pakka import agent as agent_mod
from pakka import connectors, staging
from pakka.app import MemoryStore, build_world, create_app, full_scenario
from pakka.models import DecideRequest, Decision
from tests.conftest import SCENARIO, fresh_state


def _step(messages: list[ModelMessage]) -> int:
    return sum(1 for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart))


def note_and_message_policy(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """A scripted agent for a typed job: list the channels, write a note, post a message that cites the note."""
    step = _step(messages)
    if step == 0:
        return ModelResponse(parts=[ToolCallPart("list_channels", {})])
    if step == 1:
        return ModelResponse(parts=[ToolCallPart("write_note", {"title": "Friday summary", "body": "Three things landed."})])
    if step == 2:
        returns = [p for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart)]
        note_ph = str(returns[-1].content).split("`")[1]
        return ModelResponse(parts=[ToolCallPart("post_message", {"channel": "ops", "text": f"Summary written as {note_ph}"})])
    return ModelResponse(parts=[TextPart("DONE completed=0 held=2")])


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(MemoryStore()))


def test_agents_and_connectors_are_listed(client: TestClient):
    agents = client.get("/agents").json()
    assert any(a["id"] == "replay" and a["kind"] == "replay" for a in agents)
    conns = {c["name"]: c for c in client.get("/connectors").json()}
    assert conns["notes"]["real"] is False and conns["notes"]["configured"] is True
    assert conns["webhook"]["real"] is True and "post_message" in conns["webhook"]["tools"]
    view = client.post("/reset").json()
    assert view["default_prompt"] and view["agents"] and view["connectors"]
    assert [s["name"] for s in view["systems"]] and "notes" not in [s["name"] for s in view["systems"]]
    first = view["runs"][str(SCENARIO.review_runs[0])]
    assert first["prompt"] == view["default_prompt"] and first["agent"] == "replay"


def test_the_demo_is_a_job_with_the_default_prompt_and_the_recorded_agent(client: TestClient):
    client.post("/reset")
    nxt = SCENARIO.montage_runs[0]
    r = client.post("/job", json={"agent": "replay", "prompt": "", "run": nxt})
    assert r.status_code == 200, r.text
    assert r.json()["run"]["agent"] == "replay" and r.json()["run"]["writes"]
    # a new prompt cannot be played from a recording
    r = client.post("/job", json={"agent": "replay", "prompt": "Pay everyone twice", "run": nxt + 1})
    assert r.status_code == 422
    assert client.post("/job", json={"agent": "no-such-agent"}).status_code == 422
    assert client.post("/job", json={"agent": "replay", "connectors": ["nope"], "run": nxt + 1}).status_code == 422


def test_a_typed_job_through_connectors_is_held_then_delivered_once_on_approval(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAKKA_WEBHOOKS", "ops=https://hooks.example.test/ops")
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(connectors, "post_json", lambda url, payload, timeout=10.0: (sent.append((url, payload)) or {"status": "delivered", "http_status": 200}))
    state = fresh_state()
    scn = full_scenario()
    world = build_world(1, state)
    tools = list(SCENARIO.tools) + connectors.tools_for(["notes", "webhook"])
    rr, _ = agent_mod.run_agent(scn, world, state, 1, policy=note_and_message_policy, prompt="Write up Friday and tell ops", tools=tools)
    assert rr.prompt == "Write up Friday and tell ops"
    assert [w.tool for w in rr.writes] == ["write_note", "post_message"]
    assert all(w.status == "held" for w in rr.writes) and sent == []  # nothing left the building
    note, msg = rr.writes
    assert note.placeholder in msg.args["text"] and msg.blocked_by == [note.id]
    rr, errors, _ = staging.decide(scn, world, state, rr, DecideRequest(run=1, approve_rest=True))
    assert not errors
    assert note.sent and msg.sent and len(sent) == 1
    url, payload = sent[0]
    assert url == "https://hooks.example.test/ops" and note.result_id in payload["text"] and "ph_" not in payload["text"]
    # replaying the persisted effects rebuilds the records and never posts again
    again = build_world(2, state)
    assert len(again.systems["webhook"].records) == 1 and len(sent) == 1


def test_a_discarded_message_never_posts(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAKKA_WEBHOOKS", "ops=https://hooks.example.test/ops")
    sent: list[Any] = []
    monkeypatch.setattr(connectors, "post_json", lambda url, payload, timeout=10.0: sent.append(url))
    state = fresh_state()
    world = build_world(1, state)
    rr, _ = agent_mod.run_agent(full_scenario(), world, state, 1, policy=note_and_message_policy, tools=connectors.tools_for(["notes", "webhook"]))
    note = rr.writes[0]
    rr, _, _ = staging.decide(full_scenario(), world, state, rr, DecideRequest(run=1, decisions=[Decision(write_id=note.id, action="discard")], approve_rest=True))
    assert [w.status for w in rr.writes] == ["discarded", "skipped"] and sent == []


def test_a_failed_delivery_is_recorded_not_retried(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAKKA_WEBHOOKS", "ops=https://hooks.example.test/ops")

    def boom(url: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        raise OSError("connection refused")

    monkeypatch.setattr(connectors, "post_json", boom)
    state = fresh_state()
    world = build_world(1, state)
    rr, _ = agent_mod.run_agent(full_scenario(), world, state, 1, policy=note_and_message_policy, tools=connectors.tools_for(["notes", "webhook"]))
    rr, errors, _ = staging.decide(full_scenario(), world, state, rr, DecideRequest(run=1, approve_rest=True))
    assert not errors and rr.writes[1].sent
    record = world.systems["webhook"].records[rr.writes[1].result_id]
    assert record["status"] == "failed" and "refused" in record["error"]


def test_available_agents_reflect_keys(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAKKA_MODEL", "google:gemini-3.6-flash")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("PAKKA_AGENTS", "gateway=gateway/openai-chat:gemini-3.6-flash")
    monkeypatch.setenv("PYDANTIC_AI_GATEWAY_API_KEY", "k")
    by_id = {a.id: a for a in agent_mod.available_agents()}
    assert by_id["live"].available is False and "GOOGLE_API_KEY" in by_id["live"].detail
    assert by_id["gateway"].available is True and by_id["gateway"].kind == "gateway"
    assert agent_mod.resolve_agent("").id == "gateway"  # the first available live agent
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    assert agent_mod.resolve_agent("").id == "live"
