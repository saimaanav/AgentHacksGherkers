"""§9 Golden run: Friday 1, twelve held writes, zero effects, the redirect flagged, nine effects after review."""

from __future__ import annotations

from pakka import staging
from pakka.models import DecideRequest, Decision, GroundingFlag
from tests.conftest import SCENARIO, finance, fresh_state, replay


def test_friday_one_end_state():
    state = fresh_state()
    rr = replay(state, 1)
    assert len(rr.writes) == 12
    assert all(w.status == "held" for w in rr.writes)
    assert rr.effects == [] and state.effects == []
    assert rr.agent_text.startswith("Paid 4") and "9,415.50" in rr.agent_text
    flagged = [w for w in rr.writes if w.flags]
    assert len(flagged) == 1
    (halden,) = flagged
    assert halden.tool == SCENARIO.write_tools()[0].name
    assert isinstance(halden.flags[0], GroundingFlag)
    assert halden.flags[0].detail == "conflict"
    assert halden.anomaly is not None
    assert "the agent read both" in halden.flags[0].reason
    # four chain roots, eight dependents
    assert sum(1 for w in rr.writes if not w.depends_on) == 4
    assert rr.counts.held == 4 and rr.counts.blocked == 8 and rr.counts.caught == 1 and rr.counts.wrongly_held == 0
    # nothing is proposed until a person edits something
    assert rr.proposed_rules == []


def test_discard_then_approve_lands_nine_in_order():
    state = fresh_state()
    rr = replay(state, 1)
    halden = next(w for w in rr.writes if w.flags)
    preview = staging.cascade_preview(rr, halden.id)
    assert len(preview) == 2
    # the person takes the bank details out of one email; the layer proposes the rule from that edit and it is accepted in the same request
    target, edited = next((w, a) for w in rr.writes for a in [staging.prepared_edit_args(SCENARIO, 1, w)] if a is not None)
    world = finance.build_world(1, state.effects)
    rr, errors, _ = staging.decide(
        SCENARIO,
        world,
        state,
        rr,
        DecideRequest(
            run=1,
            decisions=[Decision(write_id=halden.id, action="discard"), Decision(write_id=target.id, action="edit", args=edited)],
            accept_rules=["*"],
            approve_rest=True,
        ),
    )
    assert errors == {}
    assert len(rr.effects) == 9
    assert halden.status == "discarded"
    skipped = [w for w in rr.writes if w.status == "skipped"]
    assert {w.id for w in skipped} == set(preview)
    # dependency order: every effect's dependencies landed before it
    by_ph = {w.placeholder: w for w in rr.writes}
    landed: list[str] = []
    for e in rr.effects:
        w = next(x for x in rr.writes if x.result_id == e.result_id)
        for ph in w.depends_on:
            assert by_ph[ph].result_id in landed
        landed.append(e.result_id)
    # real ids where the placeholders were
    for e in rr.effects:
        assert "ph_" not in str(e.args)
    dependents = [w for w in rr.writes if w.sent and w.depends_on]
    assert dependents and all(any(by_ph[ph].result_id in str(w.final_args) for ph in w.depends_on) for w in dependents)
    # the edited email went out without the sort code, and the rule is live
    edited = [w for w in rr.writes if w.status == "edited"]
    assert len(edited) == 1 and edited[0].sent
    assert "sort code" not in edited[0].final_args["body"].lower() or not __import__("re").search(r"\b\d{2}-\d{2}-\d{2}\b", edited[0].final_args["body"])
    assert [r for r in state.rules if r.status == "active"]
