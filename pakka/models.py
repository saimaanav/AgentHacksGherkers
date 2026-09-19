"""Every type that crosses a boundary in pakka.

Nothing in this file knows what industry it is serving. Tools are names with
argument schemas; writes are argument dicts; the layer keys on the *shape* of
values (numbers, identifiers, names, addresses, free text) and on what the
person did with them.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

# ---------------------------------------------------------------------------
# Shapes: how the layer sees a value without knowing what it is called
# ---------------------------------------------------------------------------

Shape = Literal["number", "bool", "email", "account", "ref", "id", "placeholder", "name", "text", "empty"]

PLACEHOLDER_PREFIX = "ph_"
PLACEHOLDER_RE = re.compile(r"ph_[0-9a-f]{12}")
ACCOUNT_RE = re.compile(r"^\d{2}-\d{2}-\d{2}\s?\d{6,8}$")
REF_RE = re.compile(r"^[A-Z]{2,6}-\d{3,}$")
ID_RE = re.compile(r"^[a-z]{2,4}_[A-Za-z0-9]{4,}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def shape_of(value: Any) -> Shape:
    """Classify a scalar by its shape. Names of fields are never consulted."""
    if value is None or value == "":
        return "empty"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if not isinstance(value, str):
        return "text"
    s = value.strip()
    if PLACEHOLDER_RE.fullmatch(s):
        return "placeholder"
    if EMAIL_RE.match(s):
        return "email"
    if ACCOUNT_RE.match(s):
        return "account"
    if REF_RE.match(s):
        return "ref"
    if ID_RE.match(s):
        return "id"
    if len(s) <= 40 and len(s.split()) <= 5 and "\n" not in s:
        return "name"
    return "text"


def is_identifier_shape(shape: Shape) -> bool:
    return shape in ("account", "ref", "id")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

ToolKind = Literal["read", "write"]

_JSON_TYPES: dict[str, Any] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def model_from_schema(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Build a Pydantic model from a JSON schema of an object.

    This is the same path an MCP tool takes in the product: the tool registers
    JSON Schema, the layer builds the model, validation and the envelope
    builder work off the model.
    """
    fields: dict[str, Any] = {}
    required = set(schema.get("required", []))
    for fname, fschema in (schema.get("properties") or {}).items():
        jtype = fschema.get("type")
        if isinstance(jtype, list):
            jtype = next((t for t in jtype if t != "null"), "string")
        if jtype is None and "anyOf" in fschema:
            options = [o.get("type") for o in fschema["anyOf"] if o.get("type") != "null"]
            jtype = options[0] if options else "string"
        py = _JSON_TYPES.get(jtype, Any)
        if fschema.get("enum"):  # a closed set of values (a connector's targets) is validated at the call, not after
            py = Literal[tuple(fschema["enum"])]  # type: ignore[valid-type]
        if fname in required:
            fields[fname] = (py, Field(description=fschema.get("description")))
        else:
            fields[fname] = (py | None, Field(default=fschema.get("default"), description=fschema.get("description")))
    return create_model(name, **fields)


class ToolSpec(BaseModel):
    """A tool the agent may call. The layer sees a name, a kind and a schema."""

    name: str
    kind: ToolKind
    description: str = ""
    args_schema: dict[str, Any] = Field(default_factory=dict)

    def args_model(self) -> type[BaseModel]:
        return _ARGS_MODELS.setdefault(
            (self.name, _schema_key(self.args_schema)),
            model_from_schema(f"{self.name}_args", self.args_schema),
        )


_ARGS_MODELS: dict[tuple[str, str], type[BaseModel]] = {}


def _schema_key(schema: dict[str, Any]) -> str:
    import json

    return json.dumps(schema, sort_keys=True)


class ToolCall(BaseModel):
    """One call the agent made, in order."""

    seq: int
    tool: str
    args: dict[str, Any]


class ReadResult(BaseModel):
    """What a read returned, kept for grounding within the same run."""

    seq: int
    tool: str
    args: dict[str, Any]
    result: Any


# ---------------------------------------------------------------------------
# Flags: a discriminated union on `kind`
# ---------------------------------------------------------------------------


class GroundingFlag(BaseModel):
    kind: Literal["grounding"] = "grounding"
    field: str
    value: str
    detail: Literal["conflict", "unmatched"]
    entity: str | None = None
    conflicts: list[str] = Field(default_factory=list)
    reason: str


class EnvelopeFlag(BaseModel):
    kind: Literal["envelope"] = "envelope"
    field: str | None = None
    scope: Literal["tool", "entity"]
    entity: str | None = None
    detail: Literal["unknown_value", "above_range", "below_range", "changed_value", "new_domain", "too_many"]
    value: str | None = None
    bound: str | None = None
    ratio: float | None = None
    reason: str


class RuleFlag(BaseModel):
    kind: Literal["rule"] = "rule"
    rule_id: str
    field: str
    label: str
    created_run: int
    reason: str


class MemoryFlag(BaseModel):
    kind: Literal["memory"] = "memory"
    field: str | None = None
    value: str
    detail: Literal["already_sent", "already_held"]
    first_run: int | None = None
    reason: str


Flag = Annotated[Union[GroundingFlag, EnvelopeFlag, RuleFlag, MemoryFlag], Field(discriminator="kind")]

FlagKind = Literal["grounding", "envelope", "rule", "memory"]


# ---------------------------------------------------------------------------
# Held writes and decisions
# ---------------------------------------------------------------------------

WriteStatus = Literal[
    "held",  # waiting for a person (or blocked behind a held dependency)
    "passed",  # released tool, no flags: sent without review
    "approved",  # a person approved it as proposed
    "edited",  # a person changed it, then approved
    "discarded",  # a person rejected it; never sent
    "skipped",  # its dependency was discarded; never sent
]

DecidedBy = Literal["person", "layer", "cascade", "simulated"]


class HeldWrite(BaseModel):
    id: str
    run: int
    seq: int
    tool: str
    args: dict[str, Any]
    placeholder: str
    depends_on: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    status: WriteStatus = "held"
    decided_by: DecidedBy | None = None
    edited_args: dict[str, Any] | None = None
    final_args: dict[str, Any] | None = None
    result_id: str | None = None
    sent: bool = False
    blocked_by: list[str] = Field(default_factory=list)
    anomaly: str | None = None
    fingerprint: str = ""
    learned: bool = False  # the ladder and the envelope have already counted this decision
    delivery_error: str | None = None  # approved, but the connector could not deliver; `sent` stays False until a retry lands

    @property
    def is_root(self) -> bool:
        return not self.blocked_by

    def effective_args(self) -> dict[str, Any]:
        return self.edited_args if self.edited_args is not None else self.args


class Decision(BaseModel):
    write_id: str
    action: Literal["approve", "discard", "edit"]
    args: dict[str, Any] | None = None


class DecideRequest(BaseModel):
    run: int
    decisions: list[Decision] = Field(default_factory=list)
    accept_rules: list[str] = Field(default_factory=list)
    reject_rules: list[str] = Field(default_factory=list)
    accept_promotions: list[str] = Field(default_factory=list)
    approve_rest: bool = False
    decided_by: DecidedBy = "person"


class RunRequest(BaseModel):
    auto_approve: bool = False
    supervisor: bool = True


# ---------------------------------------------------------------------------
# Envelopes, rules, memory, ladder
# ---------------------------------------------------------------------------


class NumericRange(BaseModel):
    lo: float
    hi: float
    observed_min: float
    observed_max: float
    n: int


class ValueSet(BaseModel):
    values: list[str]
    n: int
    stable: bool


class DomainSet(BaseModel):
    domains: list[str]
    n: int


class Envelope(BaseModel):
    """What is normal for one tool, or for one tool within one entity."""

    tool: str
    scope: str = "*"  # "*" or "field=value"
    n: int = 0
    ranges: dict[str, NumericRange] = Field(default_factory=dict)
    sets: dict[str, ValueSet] = Field(default_factory=dict)
    domains: dict[str, DomainSet] = Field(default_factory=dict)
    per_run_max: int = 0


class EnvelopeBook(BaseModel):
    by_tool: dict[str, Envelope] = Field(default_factory=dict)
    by_entity: dict[str, Envelope] = Field(default_factory=dict)  # "tool|field=value"

    def entity(self, tool: str, field: str, value: str) -> Envelope | None:
        return self.by_entity.get(f"{tool}|{field}={value}")


RuleOp = Literal["matches", "in", "not_in", "gt", "lt"]


class Rule(BaseModel):
    id: str
    tool: str  # a tool name or "*"
    field: str
    op: RuleOp
    value: Any
    label: str = ""
    status: Literal["proposed", "active", "rejected"] = "proposed"
    created_by: str = "person"
    created_run: int = 0
    derived_from: str | None = None  # held write id the edit came from

    @field_validator("value")
    @classmethod
    def _compile_pattern(cls, v: Any, info: Any) -> Any:
        if info.data.get("op") == "matches":
            if not isinstance(v, str):
                raise ValueError("a `matches` rule needs a string pattern")
            try:
                re.compile(v)
            except re.error as e:  # re.error is not a ValueError, so Pydantic would let it escape
                raise ValueError(f"a `matches` rule needs a valid pattern: {e}") from e
        if info.data.get("op") in ("in", "not_in") and not isinstance(v, list):
            raise ValueError("an `in` / `not_in` rule needs a list")
        if info.data.get("op") in ("gt", "lt") and not isinstance(v, (int, float)):
            raise ValueError("a `gt` / `lt` rule needs a number")
        return v


class RuleRequest(BaseModel):
    """A rule a person types: `hold <tool> when <field> <op> <value>`. Validated by building a `Rule` from it."""

    tool: str
    field: str
    op: RuleOp
    value: Any
    label: str | None = None


class Memory(BaseModel):
    sent_values: dict[str, dict[str, int]] = Field(default_factory=dict)  # "tool|field" -> value -> first run
    sent_counts: dict[str, int] = Field(default_factory=dict)  # "tool|field" -> sends
    held_fingerprints: dict[str, str] = Field(default_factory=dict)  # fingerprint -> write id


class ApprovedWrite(BaseModel):
    run: int
    args: dict[str, Any]


LadderLevel = Literal["checked", "released"]


class LadderState(BaseModel):
    tool: str
    approved: int = 0
    edited: int = 0
    discarded: int = 0
    runs: int = 0
    level: LadderLevel = "checked"
    proposal: Literal["release"] | None = None
    proposed_run: int | None = None
    released_run: int | None = None


class LearnEvent(BaseModel):
    run: int
    kind: Literal["envelope", "rule", "promotion", "demotion", "memory"]
    text: str


class EntitySummary(BaseModel):
    tool: str
    field: str
    value: str
    n: int
    ranges: dict[str, NumericRange] = Field(default_factory=dict)
    sets: dict[str, ValueSet] = Field(default_factory=dict)


class Learned(BaseModel):
    envelopes: list[Envelope]
    entities: list[EntitySummary]
    rules: list[Rule]
    ladder: list[LadderState]
    memory_size: int
    events: list[LearnEvent]


# ---------------------------------------------------------------------------
# Effects, runs, scoreboard
# ---------------------------------------------------------------------------


class Effect(BaseModel):
    seq: int
    run: int
    tool: str
    system: str
    args: dict[str, Any]
    result_id: str
    detail: dict[str, Any] = Field(default_factory=dict)  # a real connector's delivery: status delivered | simulated | failed


class RunCounts(BaseModel):
    checked: int = 0
    through: int = 0
    held: int = 0  # held for its own flags or an unreleased tool, not blocked behind another
    blocked: int = 0  # held only because a dependency is held
    caught: int = 0
    wrongly_held: int = 0
    volume: float = 0.0


class RunUsage(BaseModel):
    """What one run cost: the model's usage as Pydantic AI reports it, plus the layer's own counts."""

    requests: int = 0  # model requests (turns)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    reads: int = 0
    writes: int = 0
    latency_s: float = 0.0  # wall clock of the agent's run through the layer
    replay: bool = False  # a recorded run: requests count, tokens are the recording's, not spent now


RunMode = Literal["review", "auto", "autopilot", "live"]


class RunResult(BaseModel):
    run: int
    mode: RunMode
    supervisor: bool
    model: str
    agent_text: str
    writes: list[HeldWrite]
    reads: list[ReadResult] = Field(default_factory=list)
    proposed_rules: list[Rule] = Field(default_factory=list)
    proposed_promotions: list[str] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    counts: RunCounts = Field(default_factory=RunCounts)
    events: list[LearnEvent] = Field(default_factory=list)
    decided: bool = False
    prompt: str = ""  # the job as the person typed it (the demo's Fridays carry the scenario's prompt)
    agent: str = ""  # the agent choice it ran through (see AgentChoice.id)
    connectors: list[str] = Field(default_factory=list)  # the connectors the job could write through
    usage: RunUsage = Field(default_factory=RunUsage)


class AgentChoice(BaseModel):
    """One agent a job can be routed through: a recorded transcript (instant) or a live model."""

    id: str
    label: str
    model: str  # the Pydantic AI model string, or replay:<tag>
    kind: Literal["replay", "live", "gateway"]
    available: bool = True
    detail: str = ""


class ConnectorView(BaseModel):
    name: str
    description: str
    real: bool  # can reach a real system once configured
    configured: bool  # this team has set it up
    mode: Literal["demo", "live"]  # demo: simulated targets, no setup; live: the team's own targets
    tools: list[str]
    targets: list[str] = Field(default_factory=list)  # what the agent may address (channels, tables, a repo…); names only, never a URL or a key
    settings: dict[str, str] = Field(default_factory=dict)  # what the settings form asks for, field -> hint


class ConnectorConfigRequest(BaseModel):
    """A team's settings for one connector: the fields its `ConnectorView.settings` names (e.g. `channels` for webhook,
    `api_key` + `from` for email). Values are validated by the connector; a key is stored per team and never returned.
    All fields empty clears the settings (back to demo)."""

    model_config = ConfigDict(extra="allow")


class JobRequest(BaseModel):
    """A job typed by a person: free text, through a chosen agent and connectors, into the staging layer."""

    prompt: str = ""
    agent: str = ""  # an AgentChoice.id; empty picks the first available
    connectors: list[str] = Field(default_factory=list)
    run: int | None = None  # the slot to play; default: the next one


class Scoreboard(BaseModel):
    runs: int = 0
    checked: int = 0
    through: int = 0
    held: int = 0
    blocked: int = 0
    caught: int = 0
    wrongly_held: int = 0
    anomalies_seen: int = 0
    volume: float = 0.0
    # what it cost, summed over the runs above
    model_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    latency_s: float = 0.0
    live_runs: int = 0  # runs that spent tokens now (not replays)


class Transcript(BaseModel):
    """What the agent did, in order. Generated by the agent, never hand-edited."""

    run: int
    model: str
    scenario: str
    seed: int
    calls: list[ToolCall]
    final_text: str
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


class Anomaly(BaseModel):
    """Something in the world on one run that the layer should hold.

    A write matches when it is on `run`, calls `tool`, and every item of
    `marker` equals the same-named argument (compared as text).
    """

    id: str
    run: int
    tool: str
    marker: dict[str, Any]
    expected: FlagKind
    label: str


class PreparedEdit(BaseModel):
    """A correction the (simulated) reviewer has already typed when the run opens."""

    run: int
    tool: str
    match: dict[str, Any]
    field: str
    remove: str  # regex; what it matches is removed from the field

    @field_validator("remove")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"`remove` must be a valid pattern: {e}") from e
        return v


class ReasonTemplates(BaseModel):
    """Plain-language reasons. The scenario owns the words; the layer fills the slots.

    Slots: {entity} {field} {value} {expected} {ratio} {run} {label} {tool} {bound} {count}
    """

    grounding_conflict: str = "{field} on this write isn't the one on record for {entity} — the agent read both"
    grounding_unmatched: str = "{field} {value} matches nothing the agent read this run"
    envelope_unknown: str = "Never seen {value} before"
    envelope_above: str = "{ratio}× the most you've approved for {entity}"
    envelope_below: str = "Below anything you've approved for {entity}"
    envelope_changed: str = "{entity}'s {field} changed on {run_label} {run}; first time to this one"
    envelope_domain: str = "{value} is a domain you've never approved"
    envelope_count: str = "{count} {tool} calls in one run; the most you've approved is {bound}"
    rule: str = "contains {label} (your rule, {run_label} {run})"
    memory_sent: str = "{value} was already sent on {run_label} {run}"
    memory_held: str = "the same write is already held as {value}"


class VolumeSpec(BaseModel):
    tool: str
    field: str
    unit: str = ""


class Scenario(BaseModel):
    """A world for the agent to act in. A second industry is a second instance."""

    model_config = ConfigDict(json_schema_extra={"title": "pakka scenario"})

    name: str
    seed: int
    run_label: str = "Run"
    task: str
    tools: list[ToolSpec]
    anomalies: list[Anomaly] = Field(default_factory=list)
    prepared_edits: list[PreparedEdit] = Field(default_factory=list)
    reasons: ReasonTemplates = Field(default_factory=ReasonTemplates)
    volume: VolumeSpec | None = None
    runs: int = 26
    review_runs: list[int] = Field(default_factory=lambda: [1])
    montage_runs: list[int] = Field(default_factory=lambda: [2, 3, 4, 5, 6])
    autopilot_runs: list[int] = Field(default_factory=lambda: list(range(7, 17)))
    agent_summary_field: str | None = None

    def tool(self, name: str) -> ToolSpec:
        for t in self.tools:
            if t.name == name:
                return t
        raise KeyError(name)

    def write_tools(self) -> list[ToolSpec]:
        return [t for t in self.tools if t.kind == "write"]

    def match_anomaly(self, run: int, tool: str, args: dict[str, Any]) -> Anomaly | None:
        for a in self.anomalies:
            if a.run == run and a.tool == tool and all(str(args.get(k)) == str(v) for k, v in a.marker.items()):
                return a
        return None


# ---------------------------------------------------------------------------
# Whole persisted state (one per team key)
# ---------------------------------------------------------------------------


class State(BaseModel):
    scenario: str
    seed: int
    current_run: int = 0
    runs: dict[int, RunResult] = Field(default_factory=dict)
    envelopes: EnvelopeBook = Field(default_factory=EnvelopeBook)
    approved_writes: dict[str, list[ApprovedWrite]] = Field(default_factory=dict)  # tool -> human-approved
    judged_runs: dict[str, list[int]] = Field(default_factory=dict)  # tool -> runs in which a person judged it
    connector_config: dict[str, dict[str, Any]] = Field(default_factory=dict)  # connector -> its settings, per team
    rules: list[Rule] = Field(default_factory=list)
    ladder: dict[str, LadderState] = Field(default_factory=dict)
    memory: Memory = Field(default_factory=Memory)
    scoreboard: Scoreboard = Field(default_factory=Scoreboard)
    effects: list[Effect] = Field(default_factory=list)
    events: list[LearnEvent] = Field(default_factory=list)

    def ladder_for(self, tool: str) -> LadderState:
        return self.ladder.setdefault(tool, LadderState(tool=tool))

    def released(self, tool: str) -> bool:
        return self.ladder.get(tool, LadderState(tool=tool)).level == "released"

    def active_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.status == "active"]
