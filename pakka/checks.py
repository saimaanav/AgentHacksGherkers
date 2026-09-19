"""The four checks: grounding, envelope, memory, rules. Each returns Flag | None.

Counts, ranges, set membership and pattern matching over value shapes. No
model calls, no field names, nothing read back from Logfire.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from pakka.models import (
    EnvelopeFlag,
    Flag,
    GroundingFlag,
    HeldWrite,
    MemoryFlag,
    ReadResult,
    RuleFlag,
    Scenario,
    State,
    is_identifier_shape,
    shape_of,
)
from pakka.learning import COUNT_FACTOR, MEMORY_MIN_SENDS, MIN_ENTITY_SUPPORT, MIN_SUPPORT


class _Slots(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def reason(scenario: Scenario, key: str, **slots: Any) -> str:
    template = getattr(scenario.reasons, key)
    slots.setdefault("run_label", scenario.run_label)
    return template.format_map(_Slots(slots))


def fingerprint(tool: str, args: dict[str, Any]) -> str:
    from pakka.models import PLACEHOLDER_RE

    return tool + ":" + PLACEHOLDER_RE.sub("<ph>", json.dumps(args, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# Grounding (history-free): the write against what the agent read this run
# ---------------------------------------------------------------------------


def _records(reads: list[ReadResult]) -> list[dict[str, Any]]:
    """Flatten read results into records of scalar values."""
    out: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            scalars = {k: v for k, v in node.items() if not isinstance(v, (dict, list))}
            if scalars:
                out.append(scalars)
            for v in node.values():
                if isinstance(v, (dict, list)):
                    visit(v)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    for r in reads:
        visit(r.result)
    return out


def _scalar_args(write: HeldWrite) -> dict[str, Any]:
    return {k: v for k, v in write.args.items() if shape_of(v) not in ("placeholder", "empty", "bool", "text")}


def grounding(write: HeldWrite, reads: list[ReadResult], scenario: Scenario) -> Flag | None:
    records = _records(reads)
    if not records:
        return None
    args = _scalar_args(write)
    read_numbers = {round(float(v), 2) for rec in records for v in rec.values() if shape_of(v) == "number"}
    for field, value in args.items():
        if shape_of(value) == "number" and read_numbers and round(float(value), 2) not in read_numbers:
            return GroundingFlag(
                field=field, value=str(value), detail="unmatched", reason=reason(scenario, "grounding_unmatched", field=field, value=value)
            )
    names = [str(v) for v in args.values() if shape_of(v) == "name"]
    entity_recs = [rec for rec in records if any(str(x) in names for x in rec.values())]
    if not entity_recs:
        return None
    entity = next(str(x) for rec in entity_recs for x in rec.values() if str(x) in names)
    # A shape whose values are all unique per record is a record key (a reference), not an attribute of the entity.
    key_shapes: set[str] = set()
    for shape in ("account", "ref", "id"):
        seen: list[str] = [str(x) for rec in records for x in rec.values() if shape_of(x) == shape]
        if seen and len(seen) == len(set(seen)):
            key_shapes.add(shape)
    for field, value in args.items():
        shape = shape_of(value)
        if not is_identifier_shape(shape) or shape in key_shapes:
            continue
        same = {str(x) for rec in entity_recs for x in rec.values() if shape_of(x) == shape}
        if not same:
            continue
        if str(value) not in same:
            return GroundingFlag(
                field=field,
                value=str(value),
                detail="unmatched",
                entity=entity,
                conflicts=sorted(same),
                reason=reason(scenario, "grounding_unmatched", field=field, value=value, entity=entity),
            )
        others = sorted(same - {str(value)})
        if others:
            return GroundingFlag(
                field=field,
                value=str(value),
                detail="conflict",
                entity=entity,
                conflicts=others,
                reason=reason(scenario, "grounding_conflict", field=field, value=value, entity=entity, expected=", ".join(others)),
            )
    return None


# ---------------------------------------------------------------------------
# Envelope: from approvals only
# ---------------------------------------------------------------------------


def envelope(write: HeldWrite, state: State, scenario: Scenario, run_writes: list[HeldWrite], run: int) -> Flag | None:
    book = state.envelopes
    args = write.args
    for field, value in args.items():
        if shape_of(value) != "name":
            continue
        ent = book.entity(write.tool, field, str(value))
        if ent is None or ent.n < MIN_ENTITY_SUPPORT:
            continue
        for g, x in args.items():
            if g == field:
                continue
            shape = shape_of(x)
            if shape == "number" and g in ent.ranges:
                r = ent.ranges[g]
                if float(x) > r.hi:
                    ratio = round(float(x) / r.observed_max, 1) if r.observed_max else None
                    return EnvelopeFlag(
                        field=g, scope="entity", entity=str(value), detail="above_range", value=str(x), bound=str(r.observed_max), ratio=ratio,
                        reason=reason(scenario, "envelope_above", field=g, value=x, entity=value, ratio=ratio, bound=r.observed_max),
                    )
                if float(x) < r.lo:
                    return EnvelopeFlag(
                        field=g, scope="entity", entity=str(value), detail="below_range", value=str(x), bound=str(r.observed_min),
                        reason=reason(scenario, "envelope_below", field=g, value=x, entity=value, bound=r.observed_min),
                    )
            elif is_identifier_shape(shape) and g in ent.sets and ent.sets[g].stable and str(x) not in ent.sets[g].values:
                return EnvelopeFlag(
                    field=g, scope="entity", entity=str(value), detail="changed_value", value=str(x), bound=", ".join(ent.sets[g].values),
                    reason=reason(scenario, "envelope_changed", field=g, value=x, entity=value, run=run, expected=", ".join(ent.sets[g].values)),
                )
    env = book.by_tool.get(write.tool)
    if env is None or env.n < MIN_SUPPORT:
        return None
    for field, value in args.items():
        shape = shape_of(value)
        if shape == "name" and field in env.sets and env.sets[field].stable and str(value) not in env.sets[field].values:
            return EnvelopeFlag(
                field=field, scope="tool", entity=str(value), detail="unknown_value", value=str(value),
                reason=reason(scenario, "envelope_unknown", field=field, value=value, entity=value),
            )
        if shape == "email" and field in env.domains and env.domains[field].n >= MIN_SUPPORT:
            domain = str(value).rsplit("@", 1)[1].lower()
            if domain not in env.domains[field].domains:
                return EnvelopeFlag(
                    field=field, scope="tool", detail="new_domain", value=domain, bound=", ".join(env.domains[field].domains),
                    reason=reason(scenario, "envelope_domain", field=field, value=domain),
                )
        if shape == "number" and field in env.ranges:
            r = env.ranges[field]
            if float(value) > r.hi:
                ratio = round(float(value) / r.observed_max, 1) if r.observed_max else None
                return EnvelopeFlag(
                    field=field, scope="tool", detail="above_range", value=str(value), bound=str(r.observed_max), ratio=ratio,
                    reason=reason(scenario, "envelope_above", field=field, value=value, entity="anyone", ratio=ratio, bound=r.observed_max),
                )
    count = sum(1 for w in run_writes if w.tool == write.tool) + 1
    if env.per_run_max and count > math.ceil(env.per_run_max * COUNT_FACTOR):
        return EnvelopeFlag(
            field=None, scope="tool", detail="too_many", value=str(count), bound=str(env.per_run_max),
            reason=reason(scenario, "envelope_count", tool=write.tool, count=count, bound=env.per_run_max),
        )
    return None


# ---------------------------------------------------------------------------
# Memory: what was sent, what is already held
# ---------------------------------------------------------------------------


def memory(write: HeldWrite, state: State, scenario: Scenario) -> Flag | None:
    for field, value in write.args.items():
        shape = shape_of(value)
        if not is_identifier_shape(shape):
            continue
        key = f"{write.tool}|{field}"
        seen = state.memory.sent_values.get(key, {})
        sends = state.memory.sent_counts.get(key, 0)
        unique_valued = sends >= MEMORY_MIN_SENDS and len(seen) == sends  # a field that never repeats is a reference
        if unique_valued and str(value) in seen:
            first = seen[str(value)]
            return MemoryFlag(
                field=field, value=str(value), detail="already_sent", first_run=first,
                reason=reason(scenario, "memory_sent", field=field, value=value, run=first),
            )
    held_as = state.memory.held_fingerprints.get(write.fingerprint)
    if held_as and held_as != write.id:
        return MemoryFlag(field=None, value=held_as, detail="already_held", reason=reason(scenario, "memory_held", value=held_as))
    return None


def remember_sent(state: State, write: HeldWrite, run: int) -> None:
    args = write.final_args if write.final_args is not None else write.args
    for field, value in args.items():
        if is_identifier_shape(shape_of(value)):
            key = f"{write.tool}|{field}"
            state.memory.sent_values.setdefault(key, {}).setdefault(str(value), run)
            state.memory.sent_counts[key] = state.memory.sent_counts.get(key, 0) + 1


# ---------------------------------------------------------------------------
# Rules: what the person wrote
# ---------------------------------------------------------------------------


def _rule_hit(op: str, value: Any, target: Any) -> bool:
    if op == "matches":
        return isinstance(value, str) and re.search(target, value) is not None
    if op == "in":
        return str(value) in [str(t) for t in target]
    if op == "not_in":
        return str(value) not in [str(t) for t in target]
    if op == "gt":
        return isinstance(value, (int, float)) and value > target
    if op == "lt":
        return isinstance(value, (int, float)) and value < target
    return False


def rules(write: HeldWrite, state: State, scenario: Scenario) -> Flag | None:
    for r in state.active_rules():
        if r.tool not in ("*", write.tool):
            continue
        value = write.args.get(r.field)
        if value is None:
            continue
        if _rule_hit(r.op, value, r.value):
            return RuleFlag(
                rule_id=r.id, field=r.field, label=r.label or f"{r.op} {r.value}", created_run=r.created_run,
                reason=reason(scenario, "rule", field=r.field, label=r.label or f"{r.op} {r.value}", run=r.created_run),
            )
    return None


def run_all(write: HeldWrite, reads: list[ReadResult], state: State, scenario: Scenario, run_writes: list[HeldWrite], run: int) -> list[Flag]:
    flags: list[Flag] = []
    for f in (
        grounding(write, reads, scenario),
        envelope(write, state, scenario, run_writes, run),
        memory(write, state, scenario),
        rules(write, state, scenario),
    ):
        if f is not None:
            flags.append(f)
    return flags
