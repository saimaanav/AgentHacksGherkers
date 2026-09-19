"""The service: FastAPI inside a Modal app. One state per team key; a world per request.

Runs locally with `uvicorn pakka.app:fastapi_app --port 8000` and no secrets;
on Modal the same app is served by `web()` with state in a `modal.Dict`.
"""

from __future__ import annotations

import importlib
import os
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import logfire
import modal
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from pakka import learning, record, staging
from pakka.models import (
    DecideRequest,
    Learned,
    LearnEvent,
    Rule,
    RuleRequest,
    RunMode,
    RunRequest,
    RunResult,
    Scenario,
    Scoreboard,
    State,
    Transcript,
)

record.setup()

NAME = "pakka"
VERSION = "0.1.0"
DEFAULT_TEAM = "demo"
SCENARIO_MODULE = os.environ.get("PAKKA_SCENARIO", "pakka.sim.scenarios.finance")
AGENT_MODULE = os.environ.get("PAKKA_AGENT", "pakka.agent")

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SystemView(BaseModel):
    name: str
    id_prefix: str
    count: int = 0


class StateView(BaseModel):
    name: str = NAME
    scenario: str
    run_label: str
    current_run: int
    scoreboard: Scoreboard
    learned: Learned
    runs: dict[int, RunResult]
    transcripts_tag: str
    live_available: bool
    review_runs: list[int]
    montage_runs: list[int]
    autopilot_runs: list[int]
    total_runs: int
    systems: list[SystemView]
    volume_unit: str = ""
    anomaly_runs: list[int] = Field(default_factory=list)


class RunResponse(BaseModel):
    run: RunResult
    learned: Learned
    scoreboard: Scoreboard


class DecideResponse(BaseModel):
    run: RunResult
    errors: dict[str, list[str]]
    events: list[LearnEvent]
    learned: Learned
    scoreboard: Scoreboard


class CascadeResponse(BaseModel):
    skipped: list[str]


class LiveRequest(BaseModel):
    friday: int | None = None


class LiveResponse(RunResponse):
    transcript: Transcript


# ---------------------------------------------------------------------------
# State stores
# ---------------------------------------------------------------------------


class MemoryStore:
    """Local: one dict, in process."""

    def __init__(self) -> None:
        self._states: dict[str, State] = {}

    def get(self, team: str) -> State | None:
        return self._states.get(team)

    def put(self, team: str, state: State) -> None:
        self._states[team] = state


class ModalDictStore:
    """On Modal: JSON strings in a `modal.Dict`, one entry per team."""

    def __init__(self, name: str = "pakka-state") -> None:
        self._dict = modal.Dict.from_name(name, create_if_missing=True)

    def get(self, team: str) -> State | None:
        raw = self._dict.get(team)
        if not raw:
            return None
        return State.model_validate_json(raw)

    def put(self, team: str, state: State) -> None:
        self._dict[team] = state.model_dump_json()


def make_store() -> MemoryStore | ModalDictStore:
    if modal.is_local():
        return MemoryStore()
    return ModalDictStore()


# ---------------------------------------------------------------------------
# Scenario and agent modules (lazy: they may be swapped by env)
# ---------------------------------------------------------------------------


def scenario_module() -> ModuleType:
    return importlib.import_module(SCENARIO_MODULE)


def agent_module() -> ModuleType:
    return importlib.import_module(AGENT_MODULE)


def scenario() -> Scenario:
    return scenario_module().SCENARIO


def transcripts_tag() -> str:
    try:
        return str(agent_module().default_tag())
    except Exception:  # the agent module may not be importable yet
        return "naive"


def live_available() -> bool:
    return bool(os.environ.get("PAKKA_MODEL"))


def rule_label(op: str, value: Any) -> str:
    """The words a rule chip and a flag reason use when the person typed no label."""
    if op == "gt":
        return f"over {value}"
    if op == "lt":
        return f"under {value}"
    if op == "in":
        return "one of " + ", ".join(str(v) for v in value) if isinstance(value, list) else f"one of {value}"
    if op == "not_in":
        return "not one of " + ", ".join(str(v) for v in value) if isinstance(value, list) else f"not one of {value}"
    return f"a match for /{value}/"


def web_dir() -> Path | None:
    for candidate in (Path(__file__).resolve().parent.parent / "web", Path("/root/web")):
        if candidate.is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class Service:
    """Everything an endpoint does, behind one lock, against one store."""

    def __init__(self, store: MemoryStore | ModalDictStore) -> None:
        self.store = store
        self.lock = threading.Lock()

    # -- state -------------------------------------------------------------

    def fresh_state(self) -> State:
        scn = scenario()
        return State(scenario=scn.name, seed=scn.seed)

    def load(self, team: str) -> State:
        state = self.store.get(team)
        if state is None:
            state = self.fresh_state()
            self.store.put(team, state)
        return state

    def save(self, team: str, state: State) -> None:
        self.store.put(team, state)

    def view(self, state: State) -> StateView:
        scn = scenario()
        world = scenario_module().build_world(1, [])
        counts: dict[str, int] = {}
        for e in state.effects:
            counts[e.system] = counts.get(e.system, 0) + 1
        systems = [SystemView(name=s.name, id_prefix=s.id_prefix, count=counts.get(s.name, 0)) for s in world.systems.values()]
        return StateView(
            scenario=scn.name,
            run_label=scn.run_label,
            current_run=state.current_run,
            scoreboard=state.scoreboard,
            learned=learning.learned(state),
            runs=state.runs,
            transcripts_tag=transcripts_tag(),
            live_available=live_available(),
            review_runs=scn.review_runs,
            montage_runs=scn.montage_runs,
            autopilot_runs=scn.autopilot_runs,
            total_runs=scn.runs,
            systems=systems,
            volume_unit=scn.volume.unit if scn.volume else "",
            anomaly_runs=[a.run for a in scn.anomalies],
        )

    # -- running the agent ---------------------------------------------------

    def model_for(self, friday: int) -> tuple[Any, str]:
        """A replay of the recorded transcript for this run, else the scenario's naive policy."""
        ag = agent_module()
        try:
            transcript = ag.load_transcript(friday, ag.default_tag())
        except Exception:
            transcript = None
        if transcript is not None:
            return ag.replay_model(transcript), f"replay:{transcript.model}"
        policy = getattr(scenario_module(), "naive_policy", None)
        if policy is None:
            raise HTTPException(500, f"no transcript for run {friday} and the scenario has no naive policy")
        return ag.naive_model(policy), "function:naive"

    def run(self, state: State, friday: int, *, supervisor: bool, mode: RunMode, model: Any = None, model_name: str = "") -> tuple[RunResult, Transcript]:
        scn = scenario()
        if friday < 1 or friday > scn.runs:
            raise HTTPException(400, f"{scn.run_label} {friday} is outside 1..{scn.runs}")
        previous = state.runs.get(friday)
        if previous is not None:
            if previous.decided or previous.mode == "autopilot":
                raise HTTPException(409, f"{scn.run_label} {friday} has already been played; reset to play it again")
            for w in previous.writes:  # a re-run replaces an undecided run; forget what it held
                if state.memory.held_fingerprints.get(w.fingerprint) == w.id:
                    state.memory.held_fingerprints.pop(w.fingerprint, None)
        if model is None:
            model, model_name = self.model_for(friday)
        world = scenario_module().build_world(friday, state.effects)
        with logfire.span("pakka.run", run=friday, mode=mode, supervisor=supervisor, model=model_name):
            rr, transcript = agent_module().run_agent(
                scn, world, state, friday, model=model, model_name=model_name, supervisor=supervisor, mode=mode,
                prompt=getattr(scenario_module(), "AGENT_PROMPT", None),
            )
        state.runs[friday] = rr
        state.current_run = friday
        return rr, transcript

    def decide(self, state: State, req: DecideRequest) -> tuple[RunResult, dict[str, list[str]], list[LearnEvent]]:
        rr = state.runs.get(req.run)
        if rr is None:
            raise HTTPException(404, f"run {req.run} has not been played")
        if rr.decided:
            raise HTTPException(409, f"run {req.run} has already been decided; send every decision for a run in one request, or reset")
        world = scenario_module().build_world(req.run, state.effects)
        rr, errors, events = staging.decide(scenario(), world, state, rr, req)
        state.runs[req.run] = rr
        staging.update_scoreboard(state, rr, scenario())
        return rr, errors, events

    # -- endpoints' bodies ---------------------------------------------------

    def reset(self, team: str) -> StateView:
        state = self.fresh_state()
        scn = scenario()
        first = scn.review_runs[0] if scn.review_runs else 1
        self.run(state, first, supervisor=True, mode="review")
        self.save(team, state)
        return self.view(state)

    def play(self, team: str, friday: int, req: RunRequest) -> RunResponse:
        state = self.load(team)
        mode: RunMode = "auto" if req.auto_approve else "review"
        rr, _ = self.run(state, friday, supervisor=req.supervisor, mode=mode)
        if req.auto_approve:
            rr, _, _ = self.decide(
                state,
                DecideRequest(run=friday, approve_rest=True, accept_rules=["*"], accept_promotions=["*"], decided_by="simulated"),
            )
        self.save(team, state)
        return RunResponse(run=rr, learned=learning.learned(state), scoreboard=state.scoreboard)

    def autopilot(self, team: str, friday: int) -> RunResponse:
        state = self.load(team)
        rr, _ = self.run(state, friday, supervisor=False, mode="autopilot")
        staging.update_scoreboard(state, rr, scenario())
        self.save(team, state)
        return RunResponse(run=rr, learned=learning.learned(state), scoreboard=state.scoreboard)

    def decision(self, team: str, req: DecideRequest) -> DecideResponse:
        state = self.load(team)
        rr, errors, events = self.decide(state, req)
        self.save(team, state)
        return DecideResponse(run=rr, errors=errors, events=events, learned=learning.learned(state), scoreboard=state.scoreboard)

    def cascade(self, team: str, friday: int, write_id: str) -> CascadeResponse:
        state = self.load(team)
        rr = state.runs.get(friday)
        if rr is None or not any(w.id == write_id for w in rr.writes):
            raise HTTPException(404, f"no write {write_id} on run {friday}")
        return CascadeResponse(skipped=staging.cascade_preview(rr, write_id))

    def add_rule(self, team: str, req: RuleRequest) -> Learned:
        """A rule a person typed. `Rule`'s validators decide whether it can be saved; a bad one is a 422 with the message."""
        state = self.load(team)
        scn = scenario()
        if req.tool != "*" and req.tool not in {t.name for t in scn.write_tools()}:
            raise HTTPException(422, f"{req.tool} is not a write tool of this scenario")
        n = sum(1 for r in state.rules if r.created_by == "person" and r.derived_from is None) + 1
        try:
            rule = Rule(
                id=f"rule_{req.tool}_{req.field}_{req.op}_{n}",
                tool=req.tool,
                field=req.field,
                op=req.op,
                value=req.value,
                label=req.label or rule_label(req.op, req.value),
                status="active",
                created_by="person",
                created_run=state.current_run,
            )
        except ValidationError as e:
            raise HTTPException(422, "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg'].removeprefix('Value error, ')}" for err in e.errors())) from e
        state.rules.append(rule)
        ev = LearnEvent(run=state.current_run, kind="rule", text=f"Rule: hold {rule.tool} when {rule.field} is {rule.label} — {rule.created_by}, {scn.run_label} {rule.created_run}")
        state.events.append(ev)
        with logfire.span("pakka.decision", decision="rule_accepted", run=state.current_run, decided_by="person", rule=rule.id, tool=rule.tool, field=rule.field, op=rule.op):
            pass
        self.save(team, state)
        return learning.learned(state)

    def live(self, team: str, req: LiveRequest) -> LiveResponse:
        if not live_available():
            raise HTTPException(400, "Live runs need PAKKA_MODEL and the matching API key in the environment (or the `pakka` Modal secret).")
        ag = agent_module()
        try:
            model = ag.real_model()
        except Exception as e:
            raise HTTPException(400, f"Could not build the live model: {e}") from e
        state = self.load(team)
        friday = req.friday or (state.current_run + 1)
        rr, transcript = self.run(state, friday, supervisor=True, mode="live", model=model, model_name=str(os.environ.get("PAKKA_MODEL", "")))
        self.save(team, state)
        return LiveResponse(run=rr, learned=learning.learned(state), scoreboard=state.scoreboard, transcript=transcript)


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------


def team_key(
    x_pakka_team: str | None = Header(default=None, alias="X-Pakka-Team"),
    team: str | None = Query(default=None),
) -> str:
    key = (x_pakka_team or team or DEFAULT_TEAM).strip()
    return key[:64] or DEFAULT_TEAM


def create_app(store: MemoryStore | ModalDictStore | None = None) -> FastAPI:
    app = FastAPI(title=NAME, version=VERSION, description="Pull requests for agent actions: every write is held, reviewed once, and the layer learns from the review.")
    service = Service(store or make_store())
    app.state.service = service

    def locked(fn, *args):
        with service.lock:
            return fn(*args)

    @app.get("/scenario", response_model=Scenario)
    def get_scenario() -> Scenario:
        return scenario()

    @app.get("/state", response_model=StateView)
    def get_state(team: str = Depends(team_key)) -> StateView:
        return locked(lambda: service.view(service.load(team)))

    @app.post("/reset", response_model=StateView)
    def post_reset(team: str = Depends(team_key)) -> StateView:
        return locked(service.reset, team)

    @app.post("/run/{friday}", response_model=RunResponse)
    def post_run(friday: int, req: RunRequest | None = None, team: str = Depends(team_key)) -> RunResponse:
        return locked(service.play, team, friday, req or RunRequest())

    @app.post("/decide", response_model=DecideResponse)
    def post_decide(req: DecideRequest, team: str = Depends(team_key)) -> DecideResponse:
        return locked(service.decision, team, req)

    @app.get("/learned", response_model=Learned)
    def get_learned(team: str = Depends(team_key)) -> Learned:
        return locked(lambda: learning.learned(service.load(team)))

    @app.post("/rules", response_model=Learned, responses={422: {"description": "The rule could not be saved: the message says why"}})
    def post_rule(req: RuleRequest, team: str = Depends(team_key)) -> Learned:
        return locked(service.add_rule, team, req)

    @app.post("/autopilot/{friday}", response_model=RunResponse)
    def post_autopilot(friday: int, team: str = Depends(team_key)) -> RunResponse:
        return locked(service.autopilot, team, friday)

    @app.get("/cascade/{friday}/{write_id}", response_model=CascadeResponse)
    def get_cascade(friday: int, write_id: str, team: str = Depends(team_key)) -> CascadeResponse:
        return locked(service.cascade, team, friday, write_id)

    @app.post("/live", response_model=LiveResponse)
    def post_live(req: LiveRequest | None = None, team: str = Depends(team_key)) -> LiveResponse:
        return locked(service.live, team, req or LiveRequest())

    static = web_dir()
    if static is not None:
        app.mount("/web", StaticFiles(directory=str(static)), name="web")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(str(static / "index.html"), media_type="text/html")

    else:

        @app.get("/", include_in_schema=False)
        def index_missing() -> dict[str, str]:
            return {"name": NAME, "detail": "web/ not found; the API is at /openapi.json"}

    try:
        logfire.instrument_fastapi(app)
    except Exception as e:  # the FastAPI instrumentation extra is optional locally
        logfire.info("fastapi instrumentation skipped", reason=str(e))
    return app


fastapi_app = create_app()

# ---------------------------------------------------------------------------
# Modal
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parent.parent

app = modal.App(NAME)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi", "pydantic>=2", "pydantic-ai", "logfire[fastapi]")
    .add_local_python_source("pakka", ignore=lambda p: "__pycache__" in p.parts or p.suffix == ".pyc")
)
if (_REPO / "web").is_dir():
    image = image.add_local_dir(_REPO / "web", remote_path="/root/web")


@app.function(image=image, min_containers=1, secrets=[modal.Secret.from_name("pakka")])
@modal.asgi_app()
def web() -> FastAPI:
    return fastapi_app
