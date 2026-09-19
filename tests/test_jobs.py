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
    c = TestClient(create_app(MemoryStore()))
    c.headers["X-Pakka-Team"] = "team-a"  # a private team key; the shared default team refuses live settings
    return c


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
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(connectors, "request_json", lambda method, url, payload=None, headers=None, timeout=15.0: (sent.append((url, payload)) or {"status": "delivered", "http_status": 200}))
    state = fresh_state()
    connectors.configure(state.connector_config, "webhook", {"channels": {"ops": "https://hooks.example.test/ops"}})
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
    assert state.effects[-1].detail["status"] == "delivered" and state.effects[-1].detail["channel"] == "ops"
    # replaying the persisted effects rebuilds the records and never posts again
    again = build_world(2, state)
    assert len(again.systems["webhook"].records) == 1 and len(sent) == 1


def test_a_discarded_message_never_posts(monkeypatch: pytest.MonkeyPatch):
    sent: list[Any] = []
    monkeypatch.setattr(connectors, "request_json", lambda method, url, payload=None, headers=None, timeout=15.0: sent.append(url))
    state = fresh_state()
    connectors.configure(state.connector_config, "webhook", {"channels": {"ops": "https://hooks.example.test/ops"}})
    world = build_world(1, state)
    rr, _ = agent_mod.run_agent(full_scenario(), world, state, 1, policy=note_and_message_policy, tools=connectors.tools_for(["notes", "webhook"]))
    note = rr.writes[0]
    rr, _, _ = staging.decide(full_scenario(), world, state, rr, DecideRequest(run=1, decisions=[Decision(write_id=note.id, action="discard")], approve_rest=True))
    assert [w.status for w in rr.writes] == ["discarded", "skipped"] and sent == []


def test_a_failed_delivery_leaves_the_write_approved_and_unsent_until_a_retry_lands(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def boom(*a: Any, **k: Any) -> dict[str, Any]:
        calls.append(a[1])
        raise OSError("connection refused")

    monkeypatch.setattr(connectors, "request_json", boom)
    state = fresh_state()
    connectors.configure(state.connector_config, "webhook", {"channels": {"ops": "https://hooks.example.test/ops"}})
    world = build_world(1, state)
    rr, _ = agent_mod.run_agent(full_scenario(), world, state, 1, policy=note_and_message_policy, tools=connectors.tools_for(["notes", "webhook"]))
    rr, errors, _ = staging.decide(full_scenario(), world, state, rr, DecideRequest(run=1, approve_rest=True))
    note, msg = rr.writes
    assert not errors and note.sent
    assert msg.status == "approved" and not msg.sent and msg.result_id is None and "refused" in msg.delivery_error
    assert [e.tool for e in state.effects] == ["write_note"] and rr.counts.through == 1  # nothing landed for the message
    assert "post_message|channel" not in state.memory.sent_values  # and nothing was learned from it
    # the endpoint comes back: a person retries, and only then is it delivered, once
    monkeypatch.setattr(connectors, "request_json", lambda m, u, payload=None, headers=None, timeout=15.0: {"status": "delivered", "http_status": 200})
    rr = staging.resend(full_scenario(), build_world(1, state), state, rr)
    assert msg.sent and msg.delivery_error is None and state.effects[-1].detail["status"] == "delivered" and rr.counts.through == 2
    assert len(calls) == 1


def test_retry_over_http(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    client.post("/reset")
    assert client.post("/retry/1").status_code == 404  # not decided
    client.post("/decide", json={"run": 1, "approve_rest": True, "accept_rules": ["*"]})
    assert client.post("/retry/1").status_code == 409  # nothing failed


def test_a_write_to_an_unknown_target_is_refused_at_the_call_not_after_approval():
    """The target field is an enum of this team's targets, so the agent hears about it and picks again."""
    from pydantic_ai.messages import RetryPromptPart

    def policy(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        retried = any(isinstance(p, RetryPromptPart) for m in messages if isinstance(m, ModelRequest) for p in m.parts)
        if _step(messages) == 0 and not retried:
            return ModelResponse(parts=[ToolCallPart("post_message", {"channel": "random", "text": "hi"})])
        if _step(messages) == 0:
            return ModelResponse(parts=[ToolCallPart("post_message", {"channel": "ops", "text": "hi"})])
        return ModelResponse(parts=[TextPart("DONE completed=0 held=1")])

    state = fresh_state()
    world = build_world(1, state)
    rr, _ = agent_mod.run_agent(full_scenario(), world, state, 1, policy=policy, tools=connectors.tools_for(["webhook"], state.connector_config))
    assert [(w.tool, w.args["channel"], w.status) for w in rr.writes] == [("post_message", "ops", "held")]
    spec = next(t for t in connectors.tools_for(["webhook"], state.connector_config) if t.name == "post_message")
    assert spec.args_schema["properties"]["channel"]["enum"] == ["ops", "alerts"]


def test_live_settings_are_refused_on_the_shared_default_team():
    shared = TestClient(create_app(MemoryStore()))
    r = shared.post("/connectors/webhook", json={"channels": {"ops": "https://hooks.example/ops"}})
    assert r.status_code == 403 and "private team key" in r.json()["detail"]
    assert shared.post("/connectors/webhook", json={"channels": {}}).status_code == 200  # clearing is fine


def test_connector_settings_never_reach_logfire():
    from types import SimpleNamespace

    from pakka.app import _request_attributes

    req = SimpleNamespace(url=SimpleNamespace(path="/connectors/tickets"))
    assert _request_attributes(req, {"values": {"token": "ghp_x"}}) is None
    assert _request_attributes(SimpleNamespace(url=SimpleNamespace(path="/job")), {"a": 1}) == {"a": 1}


def test_agent_ids_never_collide(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAKKA_MODEL", "google:gemini-3.6-flash")
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("PAKKA_AGENTS", "Live=anthropic:claude-x,replay=google:gemini-3.6-pro")
    ids = [a.id for a in agent_mod.available_agents()]
    assert len(ids) == len(set(ids)) and ids[:2] == ["replay", "live"]
    assert agent_mod.resolve_agent("live").model == "google:gemini-3.6-flash"
    assert agent_mod.resolve_agent("live-2").model == "anthropic:claude-x"


def test_an_openai_compatible_endpoint_needs_no_openai_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAKKA_MODEL", "openai:llama3")
    monkeypatch.setenv("PAKKA_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert agent_mod.resolve_agent("live").available is True


def test_demo_mode_needs_no_setup_and_simulates_delivery(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PAKKA_WEBHOOKS", raising=False)
    monkeypatch.setattr(connectors, "request_json", lambda *a, **k: pytest.fail("demo mode must never post"))
    state = fresh_state()
    assert {c.mode for c in connectors.views(state.connector_config)} == {"demo"}
    world = build_world(1, state)
    assert world.read("list_channels", {}) == ["ops", "alerts"]
    rr, _ = agent_mod.run_agent(full_scenario(), world, state, 1, policy=note_and_message_policy, tools=connectors.tools_for(["notes", "webhook"]))
    rr, errors, _ = staging.decide(full_scenario(), world, state, rr, DecideRequest(run=1, approve_rest=True))
    assert not errors and rr.writes[1].sent
    assert state.effects[-1].detail == {"status": "simulated", "channel": "ops"}


def test_a_team_configures_its_own_channels_over_http(client: TestClient):
    client.post("/reset")
    demo = {c["name"]: c for c in client.get("/connectors").json()}
    assert demo["webhook"]["mode"] == "demo" and demo["webhook"]["targets"] == ["ops", "alerts"] and "channels" in demo["webhook"]["settings"]
    r = client.post("/connectors/webhook", json={"channels": {"ops": "http://not-https.example/x"}})
    assert r.status_code == 422 and "https" in r.json()["detail"]
    assert client.post("/connectors/nope", json={"channels": {}}).status_code == 422
    r = client.post("/connectors/webhook", json={"channels": {"ops": "https://hooks.slack.com/services/T0/B0/x"}})
    assert r.status_code == 200 and r.json()["mode"] == "live" and r.json()["targets"] == ["ops"]
    assert "hooks.slack.com" not in r.text  # the URL never comes back
    other = client.get("/connectors", headers={"X-Pakka-Team": "someone-else"}).json()
    assert {c["name"]: c["mode"] for c in other}["webhook"] == "demo"  # per team, not per server
    assert {c["name"]: c["mode"] for c in client.post("/reset").json()["connectors"]}["webhook"] == "live"  # reset keeps the settings
    r = client.post("/connectors/webhook", json={"channels": {}})
    assert r.status_code == 200 and r.json()["mode"] == "demo"


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


# ---------------------------------------------------------------------------
# the other connectors: demo mode for each, live mode against a captured HTTP call
# ---------------------------------------------------------------------------

LIVE_CASES = {
    # connector: (settings, write tool, args, expected method, expected url fragment, expected header fragment, expected payload check)
    "email": ({"api_key": "re_k", "from": "Tom <tom@example.com>"}, "send_email", {"to": "a@b.co", "subject": "Hi", "body": "Text"},
              "POST", "api.resend.com/emails", "Bearer re_k", lambda p: p["to"] == ["a@b.co"] and p["from"] == "Tom <tom@example.com>"),
    "tickets": ({"token": "ghp_x", "repo": "acme/ops"}, "open_ticket", {"repo": "acme/ops", "title": "T", "body": "B"},
                "POST", "api.github.com/repos/acme/ops/issues", "Bearer ghp_x", lambda p: p == {"title": "T", "body": "B"}),
    "records": ({"api_key": "pat_x", "base_id": "appX", "tables": "contacts, tasks"}, "append_record", {"table": "tasks", "fields": {"name": "n"}},
                "POST", "api.airtable.com/v0/appX/tasks", "Bearer pat_x", lambda p: p == {"fields": {"name": "n"}}),
    "http": ({"endpoints": {"crm": {"url": "https://crm.example/api", "method": "put", "headers": {"X-Key": "k"}}}}, "call_endpoint", {"endpoint": "crm", "payload": {"a": 1}},
             "PUT", "crm.example/api", "k", lambda p: p == {"a": 1}),
    "webhook": ({"channels": {"ops": "https://hooks.example/ops"}}, "post_message", {"channel": "ops", "text": "hi"},
                "POST", "hooks.example/ops", "", lambda p: p == {"text": "hi"}),
}


def _one_write_policy(tool: str, args: dict[str, Any]):
    def policy(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if _step(messages) == 0:
            return ModelResponse(parts=[ToolCallPart(tool, args)])
        return ModelResponse(parts=[TextPart("DONE completed=0 held=1")])
    return policy


@pytest.mark.parametrize("name", sorted(LIVE_CASES))
def test_every_connector_has_a_demo_mode_that_never_calls_out(name: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PAKKA_WEBHOOKS", raising=False)
    monkeypatch.setattr(connectors, "request_json", lambda *a, **k: pytest.fail("demo mode must never call out"))
    settings, tool, args, *_ = LIVE_CASES[name]
    state = fresh_state()
    view = {c.name: c for c in connectors.views(state.connector_config)}[name]
    assert view.mode == "demo" and view.targets and view.settings
    world = build_world(1, state)
    demo_args = dict(args)
    target_word = connectors.registry()[name].target_word
    if target_word in demo_args:
        demo_args[target_word] = view.targets[0]
    rr, _ = agent_mod.run_agent(full_scenario(), world, state, 1, policy=_one_write_policy(tool, demo_args), tools=connectors.tools_for([name]))
    assert [w.status for w in rr.writes] == ["held"]
    rr, errors, _ = staging.decide(full_scenario(), world, state, rr, DecideRequest(run=1, approve_rest=True))
    assert not errors and rr.writes[0].sent and state.effects[-1].detail["status"] == "simulated"


@pytest.mark.parametrize("name", sorted(LIVE_CASES))
def test_every_connector_delivers_once_on_approval_in_live_mode(name: str, monkeypatch: pytest.MonkeyPatch):
    settings, tool, args, method, url_part, header_part, check = LIVE_CASES[name]
    calls: list[tuple[str, str, Any, dict[str, str]]] = []
    monkeypatch.setattr(connectors, "request_json", lambda m, u, payload=None, headers=None, timeout=15.0: (calls.append((m, u, payload, headers or {})) or {"status": "delivered", "http_status": 200, "body": {"html_url": "https://x/1"}}))
    state = fresh_state()
    view = connectors.configure(state.connector_config, name, settings)
    assert view.mode == "live" and view.targets
    assert not any(v in json_dumps(view) for v in ("re_k", "ghp_x", "pat_x", "hooks.example", "crm.example"))  # nothing secret comes back
    world = build_world(1, state)
    rr, _ = agent_mod.run_agent(full_scenario(), world, state, 1, policy=_one_write_policy(tool, args), tools=connectors.tools_for([name], state.connector_config))
    assert [w.status for w in rr.writes] == ["held"] and calls == []
    rr, errors, _ = staging.decide(full_scenario(), world, state, rr, DecideRequest(run=1, approve_rest=True))
    assert not errors and len(calls) == 1
    m, u, payload, headers = calls[0]
    assert m == method and url_part in u and header_part in " ".join(headers.values()) and check(payload)
    assert state.effects[-1].detail["status"] == "delivered"
    build_world(2, state)  # replay never delivers again
    assert len(calls) == 1


def json_dumps(view: Any) -> str:
    return view.model_dump_json()


@pytest.mark.parametrize("name,bad,message", [
    ("email", {"api_key": "re_k", "from": "not-an-address"}, "email address"),
    ("email", {"from": "t@e.co"}, "api_key"),
    ("tickets", {"token": "t", "repo": "no-slash"}, "owner/name"),
    ("records", {"api_key": "k", "base_id": "appX", "tables": ""}, "at least one"),
    ("records", {"api_key": "k", "base_id": "appX", "tables": [1, {"a": 2}]}, "must be a string"),
    ("http", {"endpoints": {"a": {"url": "https://x", "headers": "X-Key: k"}}}, "headers must be a mapping"),
    ("http", {"endpoints": {"a": {"url": "https://x", "method": "GET"}}}, "POST, PUT or PATCH"),
    ("http", {"endpoints": {"a": "http://x"}}, "https"),
])
def test_bad_settings_are_refused_with_the_reason(name: str, bad: dict[str, Any], message: str):
    with pytest.raises(ValueError, match=message):
        connectors.configure({}, name, bad)


def test_settings_of_any_connector_go_through_the_one_endpoint(client: TestClient):
    r = client.post("/connectors/tickets", json={"token": "ghp_x", "repo": "acme/ops"})
    assert r.status_code == 200 and r.json()["mode"] == "live" and r.json()["targets"] == ["acme/ops"] and "ghp_x" not in r.text
    r = client.post("/connectors/email", json={"api_key": "re_k", "from": "nope"})
    assert r.status_code == 422 and "email address" in r.json()["detail"]
    names = [c["name"] for c in client.get("/connectors").json()]
    assert names == ["notes", "webhook", "email", "tickets", "records", "http"]


def test_every_run_reports_what_it_cost(client: TestClient):
    view = client.post("/reset").json()
    first = view["runs"][str(SCENARIO.review_runs[0])]
    usage = first["usage"]
    assert usage["replay"] is True and usage["requests"] >= 1 and usage["input_tokens"] == 0
    assert usage["reads"] == len(first["reads"]) and usage["writes"] == len(first["writes"]) == 12
    assert usage["tool_calls"] == usage["reads"] + usage["writes"] and usage["latency_s"] >= 0
    before = view["scoreboard"]
    assert before["model_requests"] == 0  # nothing counted until a run is decided
    out = client.post("/decide", json={"run": first["run"], "approve_rest": True, "accept_rules": ["*"]}).json()
    sb = out["scoreboard"]
    assert sb["model_requests"] == usage["requests"] and sb["tool_calls"] == usage["tool_calls"] and sb["live_runs"] == 0
    assert sb["latency_s"] >= usage["latency_s"] and sb["input_tokens"] == 0
