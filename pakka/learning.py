"""What the layer learns from reviews: envelopes, the ladder, rules.

Counts, ranges, set membership and pattern matching. No model calls. Nothing
here knows a field name; the envelope builder dispatches on annotation types
and value shapes, and the ladder keys on what the person did.
"""

from __future__ import annotations

import difflib
import re
import types
import typing
from collections import Counter
from typing import Any

from pydantic import BaseModel

from pakka.models import (
    ApprovedWrite,
    DomainSet,
    EntitySummary,
    Envelope,
    EnvelopeBook,
    HeldWrite,
    LadderState,
    LearnEvent,
    Learned,
    NumericRange,
    Rule,
    Scenario,
    State,
    ValueSet,
    shape_of,
)

PAD = 0.10  # padding on numeric ranges
MIN_SUPPORT = 3  # approved writes before a tool-level set, domain set or range is enforced
MIN_ENTITY_SUPPORT = 2  # approved writes for one entity before its envelope is enforced
COUNT_FACTOR = 1.5  # writes per run allowed = max seen × 1.5
PROMOTE_APPROVED = 15
PROMOTE_RUNS = 5
PROMOTE_BAD_RATIO = 0.10
MEMORY_MIN_SENDS = 8  # sends of a field, all distinct, before a repeat counts as "already sent"

# The three patterns a correction can turn into a rule: label, regex.
RULE_PATTERNS: list[tuple[str, str]] = [
    ("a sort code", r"\b\d{2}-\d{2}-\d{2}\b"),
    ("an account number", r"\b\d{8}\b"),
    ("a currency amount", r"[£$€]\s?\d[\d,]*(?:\.\d{2})?"),
]


# ---------------------------------------------------------------------------
# Envelope builder
# ---------------------------------------------------------------------------


def _unwrap(annotation: Any) -> Any:
    """`int | None` -> int; `Optional[str]` -> str."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return args[0] if len(args) == 1 else annotation
    return annotation


def _is_numeric(annotation: Any) -> bool:
    return _unwrap(annotation) in (int, float)


def _is_str(annotation: Any) -> bool:
    return _unwrap(annotation) is str


def build_envelope(approved: list[dict[str, Any]], model: type[BaseModel]) -> Envelope:
    """What is normal, from human-approved writes only. Dispatches on annotation types, never on a field name."""
    env = Envelope(tool=model.__name__.removesuffix("_args"), n=len(approved))
    for name, field in model.model_fields.items():
        values = [w[name] for w in approved if w.get(name) not in (None, "")]
        if not values:
            continue
        if _is_numeric(field.annotation):
            lo, hi = float(min(values)), float(max(values))
            env.ranges[name] = NumericRange(lo=lo * (1 - PAD), hi=hi * (1 + PAD), observed_min=lo, observed_max=hi, n=len(values))
        elif _is_str(field.annotation) and all(shape_of(v) == "email" for v in values):
            env.domains[name] = DomainSet(domains=sorted({str(v).rsplit("@", 1)[1].lower() for v in values}), n=len(values))
        elif _is_str(field.annotation) and all(shape_of(v) in ("name", "account", "ref", "id") for v in values):
            distinct = sorted({str(v) for v in values})
            stable = len(values) >= MIN_SUPPORT and len(distinct) * 2 <= len(values)
            if len(values) < MIN_SUPPORT or stable:
                env.sets[name] = ValueSet(values=distinct, n=len(values), stable=stable)
    return env


def build_book(approved: dict[str, list[ApprovedWrite]], scenario: Scenario) -> EnvelopeBook:
    """Tool-level envelopes plus one envelope per (tool, entity field, entity value)."""
    book = EnvelopeBook()
    for spec in scenario.write_tools():
        writes = approved.get(spec.name, [])
        if not writes:
            continue
        model = spec.args_model()
        env = build_envelope([w.args for w in writes], model)
        env.tool = spec.name
        per_run = Counter(w.run for w in writes)
        env.per_run_max = max(per_run.values()) if per_run else 0
        book.by_tool[spec.name] = env
        for field in entity_fields([w.args for w in writes], model):
            for value in sorted({str(w.args[field]) for w in writes if w.args.get(field) not in (None, "")}):
                sub = [w.args for w in writes if str(w.args.get(field)) == value]
                ent = build_envelope(sub, model)
                ent.tool, ent.scope = spec.name, f"{field}={value}"
                book.by_entity[f"{spec.name}|{field}={value}"] = ent
    return book


def entity_fields(approved: list[dict[str, Any]], model: type[BaseModel]) -> list[str]:
    """String fields whose values are names and repeat across approved writes: the things the writes are about."""
    out: list[str] = []
    for name, field in model.model_fields.items():
        if not _is_str(field.annotation):
            continue
        values = [str(w[name]) for w in approved if w.get(name) not in (None, "")]
        if len(values) >= 2 and len(set(values)) < len(values) and all(shape_of(v) == "name" for v in values):
            out.append(name)
    return out


def entity_summaries(book: EnvelopeBook) -> list[EntitySummary]:
    out: list[EntitySummary] = []
    for key, env in book.by_entity.items():
        tool, scope = key.split("|", 1)
        field, value = scope.split("=", 1)
        out.append(EntitySummary(tool=tool, field=field, value=value, n=env.n, ranges=env.ranges, sets=env.sets))
    return out


# ---------------------------------------------------------------------------
# Ladder: per tool, from what the person did
# ---------------------------------------------------------------------------


def record_outcome(state: State, write: HeldWrite) -> None:
    """Count one judged write on its tool's ladder. Cascade skips are nobody's judgement and are not counted."""
    ladder = state.ladder_for(write.tool)
    if write.status == "approved":
        ladder.approved += 1
    elif write.status == "edited":
        ladder.edited += 1
    elif write.status == "discarded":
        ladder.discarded += 1


def propose_promotions(state: State, run: int) -> list[str]:
    """Tools that have earned a proposal to be sent without review."""
    proposed: list[str] = []
    for tool, ladder in state.ladder.items():
        if ladder.level != "checked" or ladder.proposal is not None:
            continue
        judged = ladder.approved + ladder.edited + ladder.discarded
        bad = (ladder.edited + ladder.discarded) / judged if judged else 1.0
        if ladder.approved >= PROMOTE_APPROVED and ladder.runs >= PROMOTE_RUNS and bad <= PROMOTE_BAD_RATIO:
            ladder.proposal, ladder.proposed_run = "release", run
            proposed.append(tool)
    return proposed


def accept_promotion(state: State, tool: str, run: int) -> LearnEvent:
    ladder = state.ladder_for(tool)
    ladder.level, ladder.proposal, ladder.released_run = "released", None, run
    ev = LearnEvent(run=run, kind="promotion", text=f"{tool}: now sent without review ({ladder.approved} approved across {ladder.runs} runs)")
    state.events.append(ev)
    return ev


def demote(state: State, tool: str, run: int) -> LearnEvent:
    ladder = state.ladder_for(tool)
    ladder.level, ladder.proposal, ladder.released_run = "checked", None, None
    ev = LearnEvent(run=run, kind="demotion", text=f"{tool}: back to checked after a discard")
    state.events.append(ev)
    return ev


# ---------------------------------------------------------------------------
# Rules from a correction
# ---------------------------------------------------------------------------


def removed_text(before: str, after: str) -> str:
    """The parts of `before` that the edit took out."""
    sm = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return " ".join(before[i1:i2] for op, i1, i2, _, _ in sm.get_opcodes() if op in ("delete", "replace"))


def derive_rules(write: HeldWrite, run: int, created_by: str = "person") -> list[Rule]:
    """One correction -> at most one proposed rule: hold <tool> when <field> matches <pattern>."""
    if write.edited_args is None:
        return []
    for field, before in write.args.items():
        after = write.edited_args.get(field)
        if not isinstance(before, str) or not isinstance(after, str) or before == after:
            continue
        gone = removed_text(before, after)
        for label, pattern in RULE_PATTERNS:
            if re.search(pattern, gone):
                slug = re.sub(r"[^a-z0-9]+", "_", label.split(" ", 1)[1].lower())
                return [
                    Rule(
                        id=f"rule_{write.tool}_{field}_{slug}",
                        tool=write.tool,
                        field=field,
                        op="matches",
                        value=pattern,
                        label=label,
                        status="proposed",
                        created_by=created_by,
                        created_run=run,
                        derived_from=write.id,
                    )
                ]
    return []


# ---------------------------------------------------------------------------
# Learning from a reviewed run
# ---------------------------------------------------------------------------


def learn_from_run(state: State, scenario: Scenario, writes: list[HeldWrite], run: int) -> list[LearnEvent]:
    """Update the ladder and the envelopes from what a person decided. Autopilot passes never reach here."""
    events: list[LearnEvent] = []
    before_entities = set(state.envelopes.by_entity)
    before_support = {k: e.n for k, e in state.envelopes.by_entity.items()}
    judged_tools: set[str] = set()
    for w in writes:
        if w.decided_by not in ("person", "simulated"):
            continue
        record_outcome(state, w)
        judged_tools.add(w.tool)
        if w.status in ("approved", "edited") and w.sent and w.final_args is not None:
            state.approved_writes.setdefault(w.tool, []).append(ApprovedWrite(run=run, args=w.final_args))
    for tool in judged_tools:
        state.ladder_for(tool).runs += 1
    state.envelopes = build_book(state.approved_writes, scenario)
    said: set[str] = set()
    for key, ent in state.envelopes.by_entity.items():
        value = key.split("=", 1)[1]
        if key not in before_entities and value not in said:
            said.add(value)
            events.append(LearnEvent(run=run, kind="envelope", text=f"{value}: learned"))
        if ent.n >= MIN_ENTITY_SUPPORT and before_support.get(key, 0) < MIN_ENTITY_SUPPORT:
            for field, r in ent.ranges.items():
                text = f"{value}: {field} usually {r.observed_min:,.0f}–{r.observed_max:,.0f}"
                if text not in said:
                    said.add(text)
                    events.append(LearnEvent(run=run, kind="envelope", text=text))
    state.events.extend(events)
    return events


def learned(state: State) -> Learned:
    return Learned(
        envelopes=list(state.envelopes.by_tool.values()),
        entities=entity_summaries(state.envelopes),
        rules=state.rules,
        ladder=list(state.ladder.values()),
        memory_size=sum(len(v) for v in state.memory.sent_values.values()),
        events=state.events,
    )
