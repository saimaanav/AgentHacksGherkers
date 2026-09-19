"""§9 Placeholder leak: no placeholder ever reaches an effects log; substitution inside longer strings."""

from __future__ import annotations

import json
import random

import pytest

from pakka.models import PLACEHOLDER_RE, State
from pakka.staging import PlaceholderLeak, placeholder_for, substitute
from tests.conftest import SCENARIO, after_autopilot, after_montage  # noqa: F401


def test_no_placeholder_in_any_effect_over_twenty_six_fridays(after_autopilot: State):
    import copy

    from pakka import staging
    from tests.conftest import replay

    state = copy.deepcopy(after_autopilot)
    for f in range(max(SCENARIO.autopilot_runs) + 1, SCENARIO.runs + 1):
        rr = replay(state, f, supervisor=False, mode="autopilot")
        staging.update_scoreboard(state, rr, SCENARIO)
    assert state.scoreboard.runs == SCENARIO.runs
    assert state.effects, "nothing landed"
    for e in state.effects:
        assert not PLACEHOLDER_RE.search(json.dumps(e.args)), e


def test_substitution_inside_longer_strings_fuzz():
    rng = random.Random(1)
    for _ in range(200):
        phs = [placeholder_for(rng.randint(1, 10**6), rng.randint(1, 30), rng.randint(1, 40)) for _ in range(rng.randint(1, 4))]
        mapping = {ph: f"id_{i:04d}" for i, ph in enumerate(phs)}
        words = ["see", "ref", ",", "and", "(", ")", "\n", "total:"]
        text = " ".join(rng.choice(words + phs) for _ in range(rng.randint(3, 20)))
        args = {"body": text, "ids": phs[:], "nested": {"note": f"x{phs[0]}y", "n": 3}}
        out = substitute(args, mapping)
        dumped = json.dumps(out)
        assert not PLACEHOLDER_RE.search(dumped), dumped
        for ph, real in mapping.items():
            assert (real in dumped) == (ph in json.dumps(args))
    assert substitute({"n": 1, "b": True}, {}) == {"n": 1, "b": True}


def test_placeholders_are_deterministic_and_uuid_shaped():
    a = placeholder_for(SCENARIO.seed, 3, 7)
    assert a == placeholder_for(SCENARIO.seed, 3, 7)
    assert a != placeholder_for(SCENARIO.seed, 3, 8)
    assert PLACEHOLDER_RE.fullmatch(a)


def test_sending_with_a_placeholder_left_is_refused():
    from pakka import staging
    from pakka.models import HeldWrite
    from pakka.sim.systems import World

    state = State(scenario=SCENARIO.name, seed=SCENARIO.seed)
    world = World(SCENARIO.seed, SCENARIO.tools)
    run = staging.Run(SCENARIO, world, state, 99)
    spec = SCENARIO.write_tools()[0]
    field = next(iter(spec.args_schema["properties"]))
    hw = HeldWrite(id="hw_x", run=99, seq=1, tool=spec.name, args={field: placeholder_for(1, 1, 1)}, placeholder="ph_000000000000", depends_on=[placeholder_for(1, 1, 1)])
    with pytest.raises(PlaceholderLeak):
        run._send(hw)
