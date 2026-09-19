"""The staging layer: every write is held, the agent gets provisional text, a person reviews once.

intercept -> placeholder -> depends_on -> held text; apply in topological order,
substitute real ids into dependents, cascade discards. One Logfire span per
decision, written to and never read from.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from typing import Any, Protocol

import logfire
from pydantic import ValidationError

from pakka import checks, learning
from pakka.sim.systems import DeliveryError
from pakka.models import (
    DecideRequest,
    EditPreview,
    EditRequest,
    Effect,
    HeldWrite,
    LearnEvent,
    PLACEHOLDER_RE,
    ReadResult,
    Rule,
    RunCounts,
    RunMode,
    RunResult,
    Scenario,
    State,
)

HELD_TEXT = (
    "HELD FOR REVIEW, not yet applied. Recorded as `{placeholder}`. "
    "Continue as if this step succeeded. Do not retry it."
)
PASSED_TEXT = "Applied. Reference {placeholder} = {result_id}."

_NAMESPACE = uuid.UUID("6f5c2a7e-9a4b-4f3e-8f6a-2b7d1e9c0a11")


def placeholder_for(seed: int, run: int, seq: int) -> str:
    """Deterministic, uuid-shaped: the same call in the same run gets the same placeholder on every replay."""
    return "ph_" + uuid.uuid5(_NAMESPACE, f"{seed}:{run}:{seq}").hex[:12]


class PlaceholderLeak(RuntimeError):
    """A write was about to be sent while it still contained a placeholder."""


class World(Protocol):
    """The systems a run writes to. `pakka.sim.systems` implements it; the product's MCP proxy would too."""

    def read(self, tool: str, args: dict[str, Any]) -> Any: ...

    def apply(self, tool: str, args: dict[str, Any], run: int) -> Effect: ...


def substitute(value: Any, mapping: dict[str, str]) -> Any:
    """Replace placeholders with real ids everywhere, including inside longer strings."""
    if isinstance(value, str):
        return PLACEHOLDER_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), value)
    if isinstance(value, dict):
        return {k: substitute(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, mapping) for v in value]
    return value


def find_placeholders(args: dict[str, Any]) -> list[str]:
    return sorted(set(PLACEHOLDER_RE.findall(json.dumps(args, default=str))))


def topological(writes: list[HeldWrite]) -> list[HeldWrite]:
    """Dependency order, ties by journal order."""
    by_ph = {w.placeholder: w for w in writes}
    indeg: dict[str, int] = {w.id: 0 for w in writes}
    dependents: dict[str, list[HeldWrite]] = defaultdict(list)
    for w in writes:
        for ph in w.depends_on:
            dep = by_ph.get(ph)
            if dep is not None:
                indeg[w.id] += 1
                dependents[dep.id].append(w)
    ready = sorted([w for w in writes if indeg[w.id] == 0], key=lambda w: w.seq)
    out: list[HeldWrite] = []
    while ready:
        w = ready.pop(0)
        out.append(w)
        for d in sorted(dependents[w.id], key=lambda x: x.seq):
            indeg[d.id] -= 1
            if indeg[d.id] == 0:
                ready.append(d)
                ready.sort(key=lambda x: x.seq)
    return out


class Run:
    """One pass of the agent through the layer. The agent's tools call `read` and `write`."""

    def __init__(
        self,
        scenario: Scenario,
        world: World,
        state: State,
        run: int,
        *,
        supervisor: bool = True,
        mode: RunMode = "review",
        model: str = "",
    ) -> None:
        self.scenario, self.world, self.state, self.run = scenario, world, state, run
        self.supervisor, self.mode, self.model = supervisor, mode, model
        self.writes: list[HeldWrite] = []
        self.reads: list[ReadResult] = []
        self.effects: list[Effect] = []
        self.seq = 0

    # -- the agent's side -------------------------------------------------

    def read(self, tool: str, args: dict[str, Any]) -> Any:
        self.seq += 1
        result = self.world.read(tool, args)
        self.reads.append(ReadResult(seq=self.seq, tool=tool, args=args, result=result))
        return result

    def write(self, tool: str, args: dict[str, Any]) -> str:
        """Intercept a write. Returns the provisional text the agent sees; text only, never invented values."""
        self.seq += 1
        placeholder = placeholder_for(self.scenario.seed, self.run, self.seq)
        depends_on = find_placeholders(args)
        by_ph = {w.placeholder: w for w in self.writes}
        anomaly = self.scenario.match_anomaly(self.run, tool, args)
        hw = HeldWrite(
            id=f"hw_{self.run}_{self.seq}",
            run=self.run,
            seq=self.seq,
            tool=tool,
            args=args,
            placeholder=placeholder,
            depends_on=depends_on,
            anomaly=anomaly.id if anomaly else None,
            fingerprint=checks.fingerprint(tool, args),
            blocked_by=[by_ph[ph].id for ph in depends_on if ph in by_ph and not by_ph[ph].sent],
        )
        with logfire.span("pakka.write", tool=tool, run=self.run, placeholder=placeholder, mode=self.mode) as span:
            hw.flags = checks.run_all(hw, self.reads, self.state, self.scenario, self.writes, self.run)
            released = self.state.released(tool)
            if hw.flags or not released or hw.blocked_by:
                hw.status = "held"
                self.state.memory.held_fingerprints[hw.fingerprint] = hw.id
                decision = "held"
            else:
                hw.status, hw.decided_by = "passed", "layer"
                self._send(hw)
                decision = "passed"
            span.set_attributes(
                {
                    "flags": [f.model_dump() for f in hw.flags],
                    "flag_kinds": [f.kind for f in hw.flags],
                    "first_flag": hw.flags[0].kind if hw.flags else "none",
                    "decision": decision,
                    "held": decision == "held",
                    "blocked": bool(hw.blocked_by),
                    "released": released,
                    "blocked_by": hw.blocked_by,
                    "anomaly": hw.anomaly,
                    "supervisor": self.supervisor,
                }
            )
        self.writes.append(hw)
        if hw.status == "passed":
            return PASSED_TEXT.format(placeholder=placeholder, result_id=hw.result_id)
        return HELD_TEXT.format(placeholder=placeholder)

    # -- sending ------------------------------------------------------------

    def _send(self, hw: HeldWrite) -> None:
        mapping = {w.placeholder: w.result_id for w in self.writes if w.sent and w.result_id}
        final = substitute(hw.effective_args(), mapping)
        if PLACEHOLDER_RE.search(json.dumps(final, default=str)):
            raise PlaceholderLeak(f"{hw.id} still references a placeholder: {find_placeholders(final)}")
        spec = self.scenario.tool(hw.tool)
        final = spec.args_model().model_validate(final).model_dump()
        try:
            effect = self.world.apply(hw.tool, final, self.run)
        except DeliveryError as e:
            # Approved, not landed: no effect, no id, nothing learned, dependents wait. A person can retry it.
            hw.final_args, hw.delivery_error = final, str(e)
            logfire.warn("pakka.delivery_failed", write=hw.id, tool=hw.tool, run=self.run, error=str(e))
            return
        hw.final_args, hw.result_id, hw.sent, hw.delivery_error = final, effect.result_id, True, None
        self.effects.append(effect)
        self.state.effects.append(effect)
        checks.remember_sent(self.state, hw, self.run)
        self.state.memory.held_fingerprints.pop(hw.fingerprint, None)

    # -- the end of the agent's run ------------------------------------------

    def result(self, agent_text: str) -> RunResult:
        # nothing is edited for the person: a rule is proposed when they edit (preview_edit / decide), and any proposal still open surfaces here
        proposed_rules = [r for r in self.state.rules if r.status == "proposed"]
        rr = RunResult(
            run=self.run,
            mode=self.mode,
            supervisor=self.supervisor,
            model=self.model,
            agent_text=agent_text,
            writes=self.writes,
            reads=self.reads,
            proposed_rules=proposed_rules,
            proposed_promotions=[t for t, l in self.state.ladder.items() if l.proposal == "release"],
            effects=self.effects,
        )
        rr.counts = count(rr)
        return rr


def count(rr: RunResult) -> RunCounts:
    """Counts as they stood at the end of the agent's run, before anyone decided. `through` is refreshed after decisions."""
    c = RunCounts(checked=len(rr.writes))
    for w in rr.writes:
        if w.sent:
            c.through += 1
        if w.status == "passed":
            continue
        if w.blocked_by:
            c.blocked += 1
        else:
            c.held += 1
            if not w.flags:
                continue  # held only because the tool is not released yet: neither caught nor wrongly held
            if w.anomaly:
                c.caught += 1
            else:
                c.wrongly_held += 1
    return c


# ---------------------------------------------------------------------------
# Decisions: approve, edit, discard; cascade; apply in order
# ---------------------------------------------------------------------------


def prepared_edit_args(scenario: Scenario, run: int, write: HeldWrite) -> dict[str, Any] | None:
    """The demo's prepared correction applied to this write's arguments, or None if it is not about this write.

    The layer never applies it on the person's behalf; the test fixture and the video's recorder use it to make
    the same edit a person makes at the page."""
    for pe in scenario.prepared_edits:
        if pe.run != run or pe.tool != write.tool or not all(str(write.args.get(k)) == str(v) for k, v in pe.match.items()):
            continue
        before = str(write.args.get(pe.field, ""))
        after = re.sub(r"[ \t]{2,}", " ", re.sub(pe.remove, "", before)).strip()
        if after == before:
            return None
        return {**write.args, pe.field: after}
    return None


def propose_from_edit(state: State, write: HeldWrite, run: int, created_by: str) -> list[Rule]:
    """The rules an edit would propose that the layer has not already proposed, accepted or been told to drop."""
    return [r for r in learning.derive_rules(write, run, created_by=created_by) if not any(x.id == r.id for x in state.rules)]


def preview_edit(scenario: Scenario, state: State, rr: RunResult, req: EditRequest) -> EditPreview:
    """What an edit would do before the decisions are sent. Raises `ValidationError` if the tool's model refuses the arguments."""
    w = next(x for x in rr.writes if x.id == req.write_id)
    edited = scenario.tool(w.tool).args_model().model_validate(req.args).model_dump()
    trial = w.model_copy(update={"edited_args": edited})
    return EditPreview(run=rr.run, write_id=w.id, edited_args=edited, proposed_rules=propose_from_edit(state, trial, rr.run, "person"))


def decide(scenario: Scenario, world: World, state: State, rr: RunResult, req: DecideRequest) -> tuple[RunResult, dict[str, list[str]], list[LearnEvent]]:
    """Apply a person's decisions to a run. Returns the run, inline validation errors, and what was learned."""
    writes = {w.id: w for w in rr.writes}
    errors: dict[str, list[str]] = {}
    events: list[LearnEvent] = []
    by = req.decided_by

    def decision_span(name: str, **attrs: Any) -> None:
        with logfire.span("pakka.decision", decision=name, run=rr.run, decided_by=by, **attrs):
            pass

    for d in req.decisions:
        w = writes.get(d.write_id)
        if w is None or w.status != "held":
            continue
        if d.action == "discard":
            w.status, w.decided_by = "discarded", by
            decision_span("discard", write=w.id, tool=w.tool)
        elif d.action == "edit":
            try:
                w.edited_args = scenario.tool(w.tool).args_model().model_validate(d.args or {}).model_dump()
                w.edited_by = by
                w.status, w.decided_by = "edited", by
                decision_span("edit", write=w.id, tool=w.tool)
                state.rules.extend(propose_from_edit(state, w, rr.run, by))  # one correction -> one proposed rule; accepted or declined below, in this same request
            except ValidationError as e:
                errors[w.id] = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        elif d.action == "approve":
            w.status = "edited" if w.edited_args is not None else "approved"
            w.decided_by = by
            decision_span("approve", write=w.id, tool=w.tool, edited=w.edited_args is not None)
    if req.approve_rest:
        # A write whose edit failed validation stays held: "approve the rest" must not send its original args.
        for w in rr.writes:
            if w.status == "held" and w.id not in errors:
                w.status = "edited" if w.edited_args is not None else "approved"
                w.decided_by = by
                decision_span("approve", write=w.id, tool=w.tool, edited=w.edited_args is not None)

    # rules
    for r in state.rules:
        if r.status != "proposed":
            continue
        if "*" in req.accept_rules or r.id in req.accept_rules:
            r.status = "active"
            r.created_run = r.created_run or rr.run
            ev = LearnEvent(run=rr.run, kind="rule", text=f"Rule: hold {r.tool} when {r.field} contains {r.label} — {r.created_by}, {scenario.run_label} {r.created_run}")
            state.events.append(ev)
            events.append(ev)
            decision_span("rule_accepted", rule=r.id, tool=r.tool, field=r.field)
        elif "*" in req.reject_rules or r.id in req.reject_rules:
            r.status = "rejected"
            decision_span("rule_rejected", rule=r.id)

    # cascade: a discarded write takes its dependents with it
    changed = True
    while changed:
        changed = False
        dead = {w.placeholder for w in rr.writes if w.status in ("discarded", "skipped")}
        for w in rr.writes:
            if w.status in ("held", "approved", "edited") and any(ph in dead for ph in w.depends_on):
                w.status, w.decided_by = "skipped", "cascade"
                decision_span("skip", write=w.id, tool=w.tool)
                changed = True

    # apply in dependency order, substituting real ids
    run = Run(scenario, world, state, rr.run, supervisor=rr.supervisor, mode=rr.mode, model=rr.model)
    run.writes = rr.writes
    for w in topological(rr.writes):
        if w.status not in ("approved", "edited") or w.sent:
            continue
        by_ph = {x.placeholder: x for x in rr.writes}
        deps = [by_ph[ph] for ph in w.depends_on if ph in by_ph]
        if all(d.sent for d in deps):
            run._send(w)
            decision_span("sent", write=w.id, tool=w.tool, result_id=w.result_id)
    rr.effects = rr.effects + run.effects
    for w in rr.writes:
        if w.status != "held":
            state.memory.held_fingerprints.pop(w.fingerprint, None)

    # learning: only from a person's decisions
    if rr.supervisor:
        events.extend(learning.learn_from_run(state, scenario, rr.writes, rr.run))
        for w in rr.writes:
            if w.status == "discarded" and state.released(w.tool):
                events.append(learning.demote(state, w.tool, rr.run))
                decision_span("demotion", tool=w.tool)
        for tool in learning.propose_promotions(state, rr.run):
            ev = LearnEvent(run=rr.run, kind="promotion", text=f"{tool}: proposed for release")
            state.events.append(ev)
            events.append(ev)
        for tool, ladder in state.ladder.items():
            if ladder.proposal == "release" and ("*" in req.accept_promotions or tool in req.accept_promotions):
                events.append(learning.accept_promotion(state, tool, rr.run))
                decision_span("promotion", tool=tool)
    rr.proposed_promotions = [t for t, l in state.ladder.items() if l.proposal == "release"]
    rr.proposed_rules = [r for r in state.rules if r.status == "proposed"]
    rr.decided = True
    rr.events = rr.events + events
    rr.counts.through = sum(1 for w in rr.writes if w.sent)
    return rr, errors, events


def resend(scenario: Scenario, world: World, state: State, rr: RunResult) -> RunResult:
    """Try again to deliver the approved writes a connector could not deliver, in dependency order. A person's
    action; the decisions themselves are not reopened."""
    run = Run(scenario, world, state, rr.run, supervisor=rr.supervisor, mode=rr.mode, model=rr.model)
    run.writes = rr.writes
    by_ph = {x.placeholder: x for x in rr.writes}
    for w in topological(rr.writes):
        if w.status not in ("approved", "edited") or w.sent:
            continue
        deps = [by_ph[ph] for ph in w.depends_on if ph in by_ph]
        if all(d.sent for d in deps):
            run._send(w)
            with logfire.span("pakka.decision", decision="resent" if w.sent else "resend_failed", run=rr.run, decided_by="person", write=w.id, tool=w.tool):
                pass
    rr.effects = rr.effects + run.effects
    rr.counts.through = sum(1 for w in rr.writes if w.sent)
    return rr


def update_scoreboard_through(state: State) -> None:
    """After a retry landed something: `through` is what has actually been sent, over all runs."""
    state.scoreboard.through = sum(1 for rr in state.runs.values() for w in rr.writes if w.sent)


def cascade_preview(rr: RunResult, write_id: str) -> list[str]:
    """Ids of the writes that would be skipped if this one were discarded."""
    by_id = {w.id: w for w in rr.writes}
    root = by_id[write_id]
    dead = {root.placeholder}
    out: list[str] = []
    changed = True
    while changed:
        changed = False
        for w in rr.writes:
            if w.id not in out and w.id != write_id and any(ph in dead for ph in w.depends_on):
                out.append(w.id)
                dead.add(w.placeholder)
                changed = True
    return out


def update_scoreboard(state: State, rr: RunResult, scenario: Scenario) -> None:
    sb = state.scoreboard
    sb.runs += 1
    sb.checked += rr.counts.checked
    sb.through += rr.counts.through
    sb.held += rr.counts.held
    sb.blocked += rr.counts.blocked
    sb.caught += rr.counts.caught
    sb.wrongly_held += rr.counts.wrongly_held
    sb.anomalies_seen += sum(1 for a in scenario.anomalies if a.run == rr.run)
    sb.model_requests += rr.usage.requests
    sb.input_tokens += rr.usage.input_tokens
    sb.output_tokens += rr.usage.output_tokens
    sb.tool_calls += rr.usage.tool_calls
    sb.latency_s = round(sb.latency_s + rr.usage.latency_s, 3)
    sb.live_runs += 0 if rr.usage.replay else 1
    if scenario.volume:
        vol = sum(float(w.final_args.get(scenario.volume.field, 0) or 0) for w in rr.writes if w.sent and w.tool == scenario.volume.tool and w.final_args)
        rr.counts.volume = vol
        sb.volume += vol
