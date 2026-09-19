"""The sixty seconds, measured: four holds of four kinds on autopilot, wrongly held zero."""

from __future__ import annotations

import copy

from pakka import staging
from pakka.models import State
from tests.conftest import SCENARIO, after_montage, replay  # noqa: F401


def test_autopilot_holds_exactly_the_four_anomalies(after_montage: State):
    state = copy.deepcopy(after_montage)
    held_by_friday: dict[int, list] = {}
    checked = through = 0
    for f in SCENARIO.autopilot_runs:
        rr = replay(state, f, supervisor=False, mode="autopilot")
        staging.update_scoreboard(state, rr, SCENARIO)
        roots = [w for w in rr.writes if w.status == "held" and not w.blocked_by]
        held_by_friday[f] = roots
        checked += rr.counts.checked
        through += rr.counts.through
        assert rr.counts.wrongly_held == 0, (f, [(w.tool, [x.reason for x in w.flags]) for w in roots])
    holds = [(f, w) for f, ws in held_by_friday.items() for w in ws]
    assert len(holds) == 4, [(f, w.tool, [x.reason for x in w.flags]) for f, w in holds]
    fridays = [f for f, _ in holds]
    assert fridays == sorted(a.run for a in SCENARIO.anomalies if a.run in SCENARIO.autopilot_runs)
    kinds = [w.flags[0].kind for _, w in holds]
    assert len(set(kinds)) >= 2 and all(w.anomaly for _, w in holds)
    expected = {a.run: a.expected for a in SCENARIO.anomalies}
    assert all(w.flags[0].kind == expected[f] for f, w in holds)
    assert 80 <= checked <= 120, checked
    assert through >= checked - 4 - 12  # everything except the four holds and their blocked dependents
    caught = sum(rr.counts.caught for rr in state.runs.values() if rr.mode == "autopilot")
    assert caught == 4


def test_second_press_catches_memory_and_arithmetic(after_montage: State):
    state = copy.deepcopy(after_montage)
    for f in SCENARIO.autopilot_runs:
        replay(state, f, supervisor=False, mode="autopilot")
    seen: dict[int, list[str]] = {}
    for f in range(max(SCENARIO.autopilot_runs) + 1, SCENARIO.runs + 1):
        rr = replay(state, f, supervisor=False, mode="autopilot")
        assert rr.counts.wrongly_held == 0, f
        seen[f] = [w.flags[0].kind for w in rr.writes if w.status == "held" and not w.blocked_by]
    kinds = {k for ks in seen.values() for k in ks}
    assert "memory" in kinds and "grounding" in kinds
    assert sum(len(v) for v in seen.values()) == 2
