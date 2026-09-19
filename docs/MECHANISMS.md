# Mechanisms

What the layer does, mechanically. Everything here is counts, ranges, set membership and pattern matching. There is no model call in `staging.py`, `checks.py` or `learning.py`, and nothing in them knows what industry it is serving: the checks key on the *shape* of a value (a number, an email address, an account-like identifier, a reference, a short name, free text) and on what the person did with it.

## Staging

Writes never reach a system directly. When the agent calls a write tool, `staging.Run.write` does four things:

1. **Placeholder.** The write gets a uuid-shaped placeholder, `ph_<12 hex>`, derived deterministically from `(scenario seed, run, sequence)`. The same call in the same run gets the same placeholder on every replay, which is what lets a transcript recorded once be replayed with the layer deciding live.
2. **Dependencies.** Every placeholder found anywhere in the arguments, including inside longer strings, becomes an entry in `depends_on`. A ledger entry that carries a payout's placeholder depends on that payout; the email that quotes it depends on it too.
3. **Checks.** Grounding, envelope, memory and rules run, in that order, each returning at most one flag. The four flags are a discriminated union on `kind`.
4. **The decision.** The write is *held* if it has any flag, if its tool has not been released, or if it depends on a placeholder that has not been sent. Otherwise, on a released tool, it *passes* and is applied immediately. Either way the agent gets text only:

   > HELD FOR REVIEW, not yet applied. Recorded as `ph_…`. Continue as if this step succeeded. Do not retry it.

   Provisional results are text; the layer never invents a field value.

**Approve** applies held writes in topological order over `depends_on`, ties broken by journal order. Before each send the layer substitutes the real ids of already-sent dependencies into the arguments (again including inside longer strings), validates the result against the tool's own Pydantic model, and refuses to send anything that still contains a placeholder (`PlaceholderLeak`). **Discard** means never sent, and it cascades: every write that depends on a discarded placeholder, transitively, is *skipped*. The review page shows the cascade before you confirm.

Every write and every decision is a Logfire span: `pakka.write` with the flags and the decision, `pakka.decision` with `decided_by`. Logfire is written to and never read from.

## Grounding (history-free)

Grounding compares a write with what the agent read in the same run, so it works on day one with no history.

- The read results are flattened into records of scalar values.
- **Numbers.** Every numeric argument on a write must appear, to two decimal places, somewhere in those records. An amount that matches nothing the agent read is flagged (`unmatched`).
- **Identifiers.** The write's short-name arguments (the entity it is about) select the read records that mention the same name. For each identifier-shaped argument on the write, the layer collects every value of the same shape from those records. If the write's value is not among them, it is flagged (`unmatched`). If it is among them but the records disagree with each other, it is flagged (`conflict`): the destination on the write is one of two accounts the agent read for the same entity, and the layer cannot know which is right, only that the agent read both.
- Reference-like shapes, those whose values are unique per record, are exempt from the conflict check: two invoice references for one vendor are not a conflict.

Friday 1's flag is the second kind. It needs no history.

## Envelope (from approvals only)

`learning.build_envelope(approved, model)` walks `model.model_fields` and dispatches on each field's annotation and the shape of its values. It never sees a field name:

- numeric → a range, observed min and max padded by 10 %;
- string, all values email-like → the set of domains;
- string, all values name- or identifier-shaped → an allowed set, marked *stable* once there are at least three values and the distinct count is at most half of them.

`build_book` applies the builder twice: once per tool over every approved write, and once per *entity*, where an entity field is any name-shaped string field whose values repeat across approved writes. The per-entity envelope is what knows that Farrow is usually £1,776–£1,924 and always the same account.

The envelope check enforces, with support thresholds so a single approval never becomes a rule:

| Scope | What | Flag | Support |
|---|---|---|---|
| entity | numeric argument above the padded max | `above_range`, with the ratio to the observed max | ≥ 2 approved writes for that entity |
| entity | numeric argument below the padded min | `below_range` | same |
| entity | identifier argument not in the entity's stable set | `changed_value` | stable set |
| tool | name argument not in the tool's stable set | `unknown_value` | ≥ 3 approved, stable |
| tool | email argument in a domain never approved | `new_domain` | ≥ 3 approved |
| tool | numeric argument above the tool's padded max | `above_range` | ≥ 3 approved |
| tool | more calls in one run than the most ever approved × 1.5 | `too_many` | any |

Only human-approved writes update the envelope. Autopilot passes never do: an envelope that learned from its own passes would drift with the world and stop noticing it had moved. Autonomy never widens the envelope; only approvals do.

## Memory

Two sets, both keyed on shape rather than name:

- **What was sent.** For every identifier-shaped argument of every sent write, the layer remembers `(tool, field, value) → run`. Once a field has been sent at least eight times with every value distinct, it is treated as a reference field, and a repeat is flagged: *"INV-20433 was paid on Friday 3."* Fields whose values repeat (an account, a name) never qualify.
- **What is held.** A fingerprint, tool plus normalised arguments with placeholders blanked, of every write currently held. A re-issue of a held write is flagged as already held.

The held text tells the agent not to retry; memory is what makes that an off-switch the agent cannot press by trying again.

## Rules

One correction → one proposed rule. When a person edits a held write and the removed text matches one of three patterns, a sort code, an eight-digit account number, or a currency amount, the layer proposes:

> hold `<tool>` when `<field>` matches `<pattern>`

The `Rule` model compiles `matches` patterns in a validator, so a rule that does not compile cannot be saved. Accepting a rule makes it live from the next action, attributed to the person and the run. A rule can also be typed directly ("always hold payments over £10k" is `Rule(tool, field, op="gt", value=10000)`).

## Ladder

Per tool: approved, edited, discarded, and the number of runs in which the tool was judged. Cascade skips are nobody's judgement and are not counted. When a tool has at least 15 approved writes across at least 5 runs with at most 10 % edited or discarded, the layer proposes release. Accepting moves the tool from *checked* to *sent without review*.

Released tools still pass through every check. A flag holds that one action, not the tool. A discard on a released tool's held action demotes the tool back to *checked*.

## No pins

Nothing is held forever by policy. What keeps money safe is what the layer learned plus what the person wrote.

## Absent supervisor

The checks run identically whether a person is reviewing (the montage) or absent (autopilot). The only differences in autopilot are that nobody decides, so held writes stay held, and nothing is learned, so the envelope is frozen. The test replays Friday 8 under both modes from identical state and asserts the held sets are equal.
