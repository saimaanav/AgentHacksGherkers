"""The service over HTTP, in process: reset, a typed rule (good and bad), and the one-decision-per-run guard."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pakka.app import MemoryStore, create_app
from tests.conftest import SCENARIO


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(MemoryStore()))


def _write_tool_and_numeric_field() -> tuple[str, str]:
    spec = SCENARIO.write_tools()[0]
    field = next(n for n, f in spec.args_schema["properties"].items() if f.get("type") == "number")
    return spec.name, field


def test_reset_plays_the_first_run_with_twelve_held_writes(client: TestClient):
    r = client.post("/reset")
    assert r.status_code == 200
    view = r.json()
    first = str(SCENARIO.review_runs[0])
    assert len(view["runs"][first]["writes"]) == 12
    assert all(w["status"] == "held" for w in view["runs"][first]["writes"])
    assert all(s["count"] == 0 for s in view["systems"])


def test_a_rule_with_a_bad_pattern_is_a_422_with_the_message(client: TestClient):
    tool = SCENARIO.write_tools()[-1].name
    field = next(iter(SCENARIO.tool(tool).args_schema["properties"]))
    r = client.post("/rules", json={"tool": tool, "field": field, "op": "matches", "value": "["})
    assert r.status_code == 422
    assert "valid pattern" in r.json()["detail"]
    tool, field = _write_tool_and_numeric_field()
    r = client.post("/rules", json={"tool": tool, "field": field, "op": "gt", "value": "ten thousand"})
    assert r.status_code == 422
    assert "needs a number" in r.json()["detail"]
    assert client.post("/rules", json={"tool": "no_such_tool", "field": field, "op": "gt", "value": 1}).status_code == 422
    assert client.post("/rules", json={"tool": tool, "field": field, "op": "bogus", "value": 1}).status_code == 422


def test_a_typed_gt_rule_is_active_in_learned(client: TestClient):
    tool, field = _write_tool_and_numeric_field()
    r = client.post("/rules", json={"tool": tool, "field": field, "op": "gt", "value": 10000})
    assert r.status_code == 200
    learned = client.get("/learned").json()
    typed = [x for x in learned["rules"] if x["tool"] == tool and x["field"] == field and x["op"] == "gt"]
    assert len(typed) == 1
    assert typed[0]["status"] == "active" and typed[0]["value"] == 10000
    assert typed[0]["created_by"] == "person" and typed[0]["created_run"] == SCENARIO.review_runs[0]
    assert typed[0]["derived_from"] is None
    assert any(e["kind"] == "rule" and typed[0]["label"] in e["text"] for e in learned["events"])


def test_a_second_decision_on_the_same_run_is_a_409(client: TestClient):
    run = SCENARIO.review_runs[0]
    first = client.post("/decide", json={"run": run, "approve_rest": True, "accept_rules": ["*"], "decided_by": "person"})
    assert first.status_code == 200
    again = client.post("/decide", json={"run": run, "approve_rest": True})
    assert again.status_code == 409


def test_reading_a_rule_in_the_persons_words_names_the_proposed_rule_it_matches(client: TestClient):
    view = client.post("/reset").json()
    proposed = view["runs"][str(SCENARIO.review_runs[0])]["proposed_rules"]
    assert len(proposed) == 1
    rule = proposed[0]
    words = lambda s: s.replace("_", " ")  # noqa: E731
    prefill = f"Always hold {words(rule['tool']).capitalize()} when {words(rule['field'])} contains {rule['label']}"
    r = client.post("/rules/read", json={"text": prefill, "tool": rule["tool"], "field": rule["field"]})
    assert r.status_code == 200
    reading = r.json()
    assert reading["intent"] == "hold"
    assert reading["rule"] == {"tool": rule["tool"], "field": rule["field"], "op": "matches", "value": rule["value"], "label": rule["label"]}
    assert (reading["same_as"], reading["same_as_status"]) == (rule["id"], "proposed")
    assert reading["pattern"] == rule["value"]
    # the opposite, said about the write in front of the person, is an exception to that same proposal
    r = client.post("/rules/read", json={"text": f"from now on it's fine if it contains {rule['label']}", "tool": rule["tool"], "field": rule["field"]})
    reading = r.json()
    assert reading["intent"] == "allow" and reading["same_as"] == rule["id"]
    # a different rule is nobody's twin, and nothing was saved by reading
    r = client.post("/rules/read", json={"text": f"hold {words(rule['tool'])} when {words(rule['field'])} contains an account number"})
    assert r.json()["intent"] == "hold" and r.json()["same_as"] is None
    assert [x["id"] for x in client.get("/learned").json()["rules"]] == [rule["id"]]
    # what cannot be read is a 200 with the reason, not an error
    r = client.post("/rules/read", json={"text": "make it faster"})
    assert r.status_code == 200 and r.json()["intent"] == "unclear" and "Start with what to do" in r.json()["problem"]

