"""Regressions from the code review: each test pins one bug that the review found and the fix closed."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from pakka import checks, learning, staging
from pakka.app import MemoryStore, create_app
from pakka.models import DecideRequest, Decision, HeldWrite
from tests.conftest import SCENARIO, auto_approve, finance, fresh_state, replay


def _write(tool: str, args: dict, **kw) -> HeldWrite:
    return HeldWrite(id="hw_1_1", run=1, seq=1, tool=tool, args=args, placeholder="ph_000000000001", **kw)


def test_a_failed_edit_is_not_approved_by_approve_rest():
    """An edit that fails validation leaves the write held; "approve the rest" must not send its original args."""
    state = fresh_state()
    rr = replay(state, 1)
    target = next(w for w in rr.writes if w.status == "held" and not w.blocked_by)
    world = finance.build_world(1, state.effects)
    rr, errors, _ = staging.decide(
        SCENARIO, world, state, rr,
        DecideRequest(run=1, decisions=[Decision(write_id=target.id, action="edit", args={"nonsense": 1})], approve_rest=True),
    )
    assert target.id in errors
    w = next(w for w in rr.writes if w.id == target.id)
    assert w.status == "held" and not w.sent
    assert all(not x.sent for x in rr.writes if target.placeholder in x.depends_on)


def test_a_played_run_cannot_be_replayed_over_http():
    client = TestClient(create_app(MemoryStore()))
    client.post("/reset")
    first = SCENARIO.review_runs[0]
    assert client.post("/decide", json={"run": first, "approve_rest": True, "accept_rules": ["*"]}).status_code == 200
    assert client.post(f"/run/{first}", json={}).status_code == 409
    nxt = SCENARIO.montage_runs[0]
    assert client.post(f"/run/{nxt}", json={"auto_approve": True}).status_code == 200
    before = client.get("/state").json()["scoreboard"]
    assert client.post(f"/run/{nxt}", json={"auto_approve": True}).status_code == 409
    assert client.get("/state").json()["scoreboard"] == before
    auto = SCENARIO.autopilot_runs[0]
    assert client.post(f"/autopilot/{auto}").status_code == 200
    assert client.post(f"/autopilot/{auto}").status_code == 409


def test_a_demotion_sticks_until_the_tool_earns_its_way_back():
    state = fresh_state()
    tool = SCENARIO.write_tools()[0].name
    ladder = state.ladder_for(tool)
    ladder.level, ladder.approved, ladder.runs = "released", 40, 10
    state.judged_runs[tool] = list(range(1, 11))
    learning.demote(state, tool, 11)
    assert not state.released(tool)
    assert learning.propose_promotions(state, 11) == []
    assert ladder.approved == ladder.edited == ladder.discarded == ladder.runs == 0
    assert tool not in state.judged_runs


def test_a_write_held_only_by_the_ladder_is_not_a_catch():
    """`caught` credits the checks, so it needs a flag; a held-because-unreleased write with an anomaly label is just held."""
    tool = SCENARIO.write_tools()[0].name
    from pakka.models import RunResult

    rr = RunResult(run=1, mode="review", supervisor=True, model="test", agent_text="", writes=[_write(tool, {}, anomaly="something")])
    c = staging.count(rr)
    assert c.held == 1 and c.caught == 0 and c.wrongly_held == 0


def test_memory_keeps_checking_after_one_approved_repeat():
    """Seven distinct values in eight sends is still a reference field; the repeat must flag, not switch the check off."""
    state = fresh_state()
    tool = SCENARIO.write_tools()[0].name
    field = next(n for n, f in SCENARIO.tool(tool).args_schema["properties"].items() if "ref" in n.lower() or "reference" in n.lower())
    key = f"{tool}|{field}"
    values = [f"INV-2010{i}" for i in range(7)]
    state.memory.sent_values[key] = {v: 1 for v in values}
    state.memory.sent_counts[key] = 8  # one of the seven went twice
    flag = checks.memory(_write(tool, {field: values[0]}), state, SCENARIO)
    assert flag is not None and flag.kind == "memory" and flag.detail == "already_sent"
    state.memory.sent_counts[key] = 20  # seven distinct in twenty sends: the field repeats freely, not a reference
    assert checks.memory(_write(tool, {field: values[0]}), state, SCENARIO) is None


@pytest.mark.parametrize("friday", [1])
def test_the_demo_path_is_unchanged_by_the_fixes(friday: int):
    state = fresh_state()
    rr = replay(state, friday)
    assert staging.count(rr).checked == 12
    auto_approve(copy.deepcopy(state), copy.deepcopy(rr))
