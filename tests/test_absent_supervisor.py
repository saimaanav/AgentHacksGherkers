"""§9 Absent supervisor: Friday 8 with supervisor=True and False → identical held sets."""

from __future__ import annotations

import copy

from pakka.models import State
from tests.conftest import after_montage, replay  # noqa: F401


def _held_set(rr):
    return {(w.tool, w.seq, w.status, tuple(f.kind for f in w.flags), tuple(w.blocked_by)) for w in rr.writes}


def test_friday_eight_same_holds_with_and_without_tom(after_montage: State):
    present = replay(copy.deepcopy(after_montage), 8, supervisor=True, mode="review")
    absent = replay(copy.deepcopy(after_montage), 8, supervisor=False, mode="autopilot")
    assert _held_set(present) == _held_set(absent)
    assert present.counts.held == absent.counts.held == 1
    assert absent.counts.caught == 1 and absent.counts.wrongly_held == 0


def test_autopilot_never_learns(after_montage: State):
    state = copy.deepcopy(after_montage)
    before = (state.envelopes.model_dump_json(), [l.model_dump() for l in state.ladder.values()], [r.model_dump() for r in state.rules])
    replay(state, 8, supervisor=False, mode="autopilot")
    after = (state.envelopes.model_dump_json(), [l.model_dump() for l in state.ladder.values()], [r.model_dump() for r in state.rules])
    assert before == after
