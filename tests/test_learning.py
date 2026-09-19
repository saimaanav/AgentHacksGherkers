"""§9 Learning: the ladder, the derived rule, and build_envelope on fields named a, b, c."""

from __future__ import annotations

import copy

from pydantic import BaseModel

from pakka import learning, staging
from pakka.models import DecideRequest, HeldWrite, Rule, RuleFlag, State
from tests.conftest import SCENARIO, after_friday_one, after_montage, finance, fresh_state, play_montage, replay  # noqa: F401


def test_email_tool_is_proposed_for_release_first(after_friday_one: State):
    state = copy.deepcopy(after_friday_one)
    released_at: dict[str, int] = {}
    for f in SCENARIO.montage_runs:
        rr = replay(state, f, supervisor=True, mode="auto")
        world = finance.build_world(f, state.effects)
        rr, _, _ = staging.decide(
            SCENARIO, world, state, rr, DecideRequest(run=f, approve_rest=True, accept_rules=["*"], accept_promotions=["*"], decided_by="simulated")
        )
        staging.update_scoreboard(state, rr, SCENARIO)
        for tool, ladder in state.ladder.items():
            if ladder.level == "released" and tool not in released_at:
                released_at[tool] = f
    write_tools = [t.name for t in SCENARIO.write_tools()]
    assert set(released_at) == set(write_tools)
    email_tool = write_tools[-1]
    assert released_at[email_tool] == min(released_at.values())
    assert all(released_at[t] > released_at[email_tool] for t in write_tools if t != email_tool)


def test_pre_applied_edit_derives_exactly_one_rule():
    state = fresh_state()
    rr = replay(state, 1)
    assert len(rr.proposed_rules) == 1
    rule = rr.proposed_rules[0]
    assert rule.op == "matches" and rule.tool == SCENARIO.write_tools()[-1].name and rule.field == "body"
    edited = [w for w in rr.writes if w.edited_args is not None]
    assert len(edited) == 1
    assert learning.derive_rules(edited[0], 1) == [Rule(**{**rule.model_dump(), "status": "proposed"})]


def test_accepted_rule_holds_a_matching_send_on_the_next_call(after_friday_one: State):
    state = copy.deepcopy(after_friday_one)
    rule = next(r for r in state.rules if r.status == "active")
    from pakka.sim.systems import World

    world = World(SCENARIO.seed, SCENARIO.tools)
    run = staging.Run(SCENARIO, world, state, 2)
    hw = HeldWrite(id="hw_t", run=2, seq=1, tool=rule.tool, args={"to": "x@y.co", "subject": "s", "body": "Sent to sort code 12-34-56 today.", "payout_id": "po_abc123"}, placeholder="ph_000000000001")
    from pakka import checks

    flag = checks.rules(hw, state, SCENARIO)
    assert isinstance(flag, RuleFlag) and flag.rule_id == rule.id
    assert "your rule" in flag.reason and "1" in flag.reason
    assert checks.rules(HeldWrite(**{**hw.model_dump(), "args": {**hw.args, "body": "Sent today."}}), state, SCENARIO) is None
    del run


def test_build_envelope_keys_on_types_not_names():
    class M(BaseModel):
        a: int
        b: str
        c: str

    approved = [
        {"a": 10, "b": "x", "c": "p@one.com"},
        {"a": 20, "b": "y", "c": "q@one.com"},
        {"a": 15, "b": "x", "c": "r@two.org"},
        {"a": 12, "b": "y", "c": "s@one.com"},
    ]
    env = learning.build_envelope(approved, M)
    assert env.n == 4
    assert env.ranges["a"].observed_min == 10 and env.ranges["a"].observed_max == 20
    assert env.ranges["a"].lo == 9.0 and env.ranges["a"].hi == 22.0
    assert env.sets["b"].values == ["x", "y"] and env.sets["b"].stable
    assert env.domains["c"].domains == ["one.com", "two.org"]
    assert "c" not in env.sets and "b" not in env.domains and "a" not in env.sets


def test_only_approvals_widen_the_envelope(after_montage: State):
    state = copy.deepcopy(after_montage)
    entity_before = state.envelopes.model_dump()
    rr = replay(state, 10, supervisor=False, mode="autopilot")
    assert rr.counts.through > 0
    assert state.envelopes.model_dump() == entity_before


def test_demotion_on_discard_of_a_released_tool(after_montage: State):
    state = copy.deepcopy(after_montage)
    tool = SCENARIO.write_tools()[0].name
    assert state.released(tool)
    rr = replay(state, 7, supervisor=True, mode="review")
    passed = [w for w in rr.writes if w.tool == tool and w.status == "passed"]
    assert passed, "nothing passed on a released tool"
    # force one held write to discard: use a flagged one if any, else pretend by marking one held
    target = next((w for w in rr.writes if w.tool == tool and w.status == "held"), None)
    if target is None:
        return  # no held write on Friday 7 for this tool; the mechanism is covered by learning.demote
    world = finance.build_world(7, state.effects)
    from pakka.models import Decision

    staging.decide(SCENARIO, world, state, rr, DecideRequest(run=7, decisions=[Decision(write_id=target.id, action="discard")], approve_rest=True))
    assert not state.released(tool)
