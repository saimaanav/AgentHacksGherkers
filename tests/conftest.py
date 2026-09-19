"""Shared fixtures: the layer played the way the app plays it, locally, with no secrets."""

from __future__ import annotations

import copy
import importlib
import os

import pytest

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pakka import record  # noqa: E402

record.setup(send=False)

from pakka import agent as agent_mod  # noqa: E402
from pakka import staging  # noqa: E402
from pakka.models import DecideRequest, RunResult, State  # noqa: E402

finance = importlib.import_module("pakka.sim.scenarios.finance")
SCENARIO = finance.SCENARIO


def fresh_state() -> State:
    return State(scenario=SCENARIO.name, seed=SCENARIO.seed)


def replay(state: State, friday: int, *, supervisor: bool = True, mode: str = "review", tag: str | None = None) -> RunResult:
    """Replay one Friday's transcript through the layer against `state` (mutates state)."""
    transcript = agent_mod.load_transcript(friday, tag)
    world = finance.build_world(friday, state.effects)
    rr, _ = agent_mod.run_agent(
        SCENARIO,
        world,
        state,
        friday,
        model=agent_mod.replay_model(transcript),
        model_name=f"replay:{transcript.model}",
        supervisor=supervisor,
        mode=mode,
    )
    state.runs[friday] = rr
    return rr


def auto_approve(state: State, rr: RunResult) -> RunResult:
    world = finance.build_world(rr.run, state.effects)
    # the world must know what already landed, but not this run's effects twice
    rr, errors, _ = staging.decide(
        SCENARIO,
        world,
        state,
        rr,
        DecideRequest(run=rr.run, approve_rest=True, accept_rules=["*"], accept_promotions=["*"], decided_by="simulated"),
    )
    assert not errors, errors
    staging.update_scoreboard(state, rr, SCENARIO)
    return rr


def play_montage(state: State, fridays: list[int]) -> None:
    for f in fridays:
        rr = replay(state, f, supervisor=True, mode="auto")
        auto_approve(state, rr)


@pytest.fixture(scope="session")
def after_friday_one() -> State:
    """Friday 1 reviewed the way the demo does it: discard the flagged chain root, accept the rule, approve the rest."""
    from pakka.models import Decision

    state = fresh_state()
    rr = replay(state, 1)
    flagged = [w for w in rr.writes if w.flags and not w.blocked_by]
    assert len(flagged) == 1
    edits = [(w, staging.prepared_edit_args(SCENARIO, 1, w)) for w in rr.writes]
    edits = [(w, a) for w, a in edits if a is not None]
    assert len(edits) == 1  # the demo's correction: the person takes the bank details out of one email
    world = finance.build_world(1, state.effects)
    rr, errors, _ = staging.decide(
        SCENARIO,
        world,
        state,
        rr,
        DecideRequest(
            run=1,
            decisions=[Decision(write_id=flagged[0].id, action="discard"), Decision(write_id=edits[0][0].id, action="edit", args=edits[0][1])],
            accept_rules=["*"],
            approve_rest=True,
        ),
    )
    assert not errors
    staging.update_scoreboard(state, rr, SCENARIO)
    return state


@pytest.fixture(scope="session")
def after_montage(after_friday_one: State) -> State:
    state = copy.deepcopy(after_friday_one)
    play_montage(state, SCENARIO.montage_runs)
    return state


@pytest.fixture(scope="session")
def after_autopilot(after_montage: State) -> State:
    state = copy.deepcopy(after_montage)
    for f in SCENARIO.autopilot_runs:
        rr = replay(state, f, supervisor=False, mode="autopilot")
        staging.update_scoreboard(state, rr, SCENARIO)
    return state
