# The board: what to build on the API as it works now

This is the build spec for the kanban UI. Everything it needs exists on the server today and is verified on the live URL; nothing here needs a backend change. The contract for each call is in [`JOBS_API.md`](JOBS_API.md); this file says what to put on screen, in what order to build it, and what the demo path is.

The rule that shapes every screen: **a card is a write the agent wanted to make, and its column is what happened to it.** The person's job is to move cards out of *Held*. Everything else is context for that decision.

## The screen

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ pakka          [ prompt text box …………………………………………… ] [agent ▾] [connectors ▾] [ Run ] │ header
│                Friday 3 · 10 checked · 7 through · 3 held · 2 caught · 4.1k tokens · 9.8 s│ stats strip
├──────────────┬──────────────┬──────────────┬──────────────┬──────────────────────────────┤
│ Held (3)     │ Passed (7)   │ Approved (0) │ Discarded (0)│ What it has learned          │
│ ┌──────────┐ │ ┌──────────┐ │              │              │ • Halden Ltd: amount usually │
│ │create_…  │ │ │post_…    │ │              │              │   £1,800–£2,400              │
│ │Halden Ltd│ │ │ …        │ │              │              │ • rule: hold send_… when     │
│ │£2,140.00 │ │ └──────────┘ │              │              │   body contains a sort code  │
│ │⚠ envelope│ │              │              │              │ • send_… released Friday 5   │
│ │ 2.7× …   │ │              │              │              │                              │
│ │[Approve] │ │              │              │              │ Settings ▸ connectors, team  │
│ │[Edit]    │ │              │              │              │                              │
│ │[Discard] │ │              │              │              │                              │
│ └──────────┘ │              │              │              │                              │
│  ↳ 2 waiting │              │              │              │                              │
└──────────────┴──────────────┴──────────────┴──────────────┴──────────────────────────────┘
```

### Header: the job

- **Prompt box**, prefilled with `/state.default_prompt` ("It's Friday. Run the payment run."). The user can type anything.
- **Agent picker** from `GET /agents` (also in `/state.agents`): show `label`, disable rows with `available: false` and show their `detail` as the tooltip. Default: the first available row that is not `replay`, else `replay`.
- **Connectors picker** (multi-select) from `GET /connectors`: show `name`, `mode` as a small tag (`demo` / `live`), `targets` in the tooltip. The scenario's own tools are always on and are not in this list.
- **Run** → `POST /job {prompt, agent, connectors}`. While it runs (a live agent takes 5–60 s): disable the header, show a progress line "agent running · 4 reads · 2 writes so far" is *not* available (the call returns when done), so show an indeterminate spinner with the prompt text. On 200, render the run. On 422 show the `detail` inline under the box (a new prompt on the recorded agent, an unknown connector). On 409 the slot was already played: Reset, or show the run that exists.
- **Reset** (`POST /reset`) in the header's far right; it keeps the team's connector settings.

The Friday demo is exactly this header with the default prompt and the `replay` agent. The video presses Run with those defaults; nothing else is special-cased.

### Stats strip

From the run just played (`run.counts`, `run.usage`) and the scoreboard (`/state.scoreboard`):

| shown | from |
|---|---|
| `Friday 3` | `run.run` with `/state.run_label` |
| `10 checked · 7 through · 3 held · 2 caught · 0 wrongly held` | `run.counts` |
| `4.1k tokens · 6 requests · 9.8 s` | `run.usage.total_tokens`, `.requests`, `.latency_s`; for a replay show `recorded · 0 tokens` |
| totals on hover or a second line | `scoreboard.checked`, `.through`, `.held`, `.caught`, `.input_tokens + .output_tokens`, `.latency_s`, `.live_runs` |

### The columns

Cards are `run.writes[]`. Column = `status`:

| column | statuses | notes |
|---|---|---|
| **Held** | `held` | the only column with buttons. A card with `blocked_by` non-empty is shown nested under (or dimmed below) the card it waits on, with "waits on ↑". Count in the column title. |
| **Passed** | `passed` | the layer sent it without asking (a released tool). Green tick, `result_id`. |
| **Approved** | `approved`, `edited` | after a decision. `sent: true` → tick and `result_id`; `sent: false` with `delivery_error` → red "not delivered: …" and a **Retry** button (`POST /retry/{run}`). An edited card shows old → new (`args` vs `edited_args`). |
| **Discarded** | `discarded`, `skipped` | `skipped` cards say "fell with ↑" and name the discarded card. |

Order within a column: `seq`.

### A card

```
┌────────────────────────────────────────────┐
│ create_payout                 hw_3_5       │  tool name · id (small)
│ Halden Ltd · £2,140.00 · 20-45-17 31447702 │  the args, the scenario's summary fields first, the rest on expand
│ ⚠ envelope · 2.7× the most you've approved │  each flag: kind chip + reason (flags[].kind, flags[].reason)
│   for Halden Ltd                           │
│ depends on ph_3f2a… (post_ledger_entry)    │  depends_on, resolved to the card's tool name
│ [ Approve ]  [ Edit ]  [ Discard ]         │  Held only
└────────────────────────────────────────────┘
```

- **Flags** are the whole point of a card. `flags[].kind` ∈ grounding, envelope, memory, rule; colour by kind; `reason` verbatim. A card with no flags is held only because its tool is not yet released: say so in grey ("held: tool not yet trusted").
- **Discard** first calls `GET /cascade/{run}/{write_id}` and shows "this also skips N cards" before confirming.
- **Edit** opens the args as a form (string, number, object fields from the tool's `args_schema` in `/scenario` or the connector's tools). Validation errors come back per write in `DecideResponse.errors[write_id]`: show them inline on the card and keep it in Held.
- **Sent footer** (Approved/Passed): `result_id`, and for a connector card the effect's `detail` from `run.effects[]` matched on `result_id`: `simulated` (grey), `delivered` (green, with `url` as a link when present), `failed` (red).

### Decisions are one request per run

Buttons on cards do not call the server one by one. Collect decisions locally (a card moves to a "pending" style), then one **Approve all / Send decisions** button posts `POST /decide {run, decisions[], approve_rest: true, accept_rules: ["*"], accept_promotions: ["*"]}`. A second decide on the same run is a 409, so the button disables after success and the columns re-render from the response's `run`. `approve_rest: true` is what "everything I didn't touch is fine" means.

Proposed rules (`run.proposed_rules[]`) are a card of their own in *Needs your approval* ("Make this a rule?"), and promotions (`run.proposed_promotions[]`) are accepted with the decisions. The rule card's popup is built so the person sees in a second what needs their eye and why, then says the rule in their own words:

1. **What you took out, first.** An amber block: *You took **a sort code** out of the **body** of this **send remittance email***; under it the exact text the edit removed, with the match highlighted; then why a rule is on offer (the layer's checks did not catch this, the person did by editing; a rule makes the layer check for it from now on). The whole field, before and after, is one click away, collapsed.
2. **The rule, in your words.** A text box prefilled by the layer with its proposal (*Always hold Send remittance email when body contains a sort code*): the derivation in `learning.derive_rules`, no model. The person can leave it, edit it (*always hold payments over £10k*), or turn it into an exception (*from now on it's fine if it contains a sort code*). As they type, `POST /rules/read` reads the words back under the box (*→ Hold Create payout when amount is over 10,000*, or *Not read as a rule yet* with the forms it does read), and chips offer the other patterns the layer knows and the "it's fine" version.
3. **One button, three outcomes.** The prefilled proposal → **Yes, always** puts the id into `accept_rules`. A different `hold` reading → the person's own rule goes to `POST /rules` when the decisions are sent, and the proposal's id goes into `reject_rules`. An `allow` reading of the proposal → **Yes, it's fine**: `reject_rules`, no rule, and the layer never proposes that one again. **Not now** is `reject_rules` too. Nothing reaches the server until **Send decisions**.

### What it has learned (right rail)

From `/state.learned` (also on every `RunResponse` and `DecideResponse`):

- `entities` and `envelopes`: one line per entity, "usually £a–£b", "accounts: …".
- `rules[]`: chips with `label`, `tool`, `field`, `status`; an **Add a rule** form → `POST /rules {tool, field, op, value}`; a 422 shows its `detail`.
- `ladder`: per tool, level and counts; a released tool says "released Friday N".
- `events[]`: the feed, newest first.

### Settings (a drawer from the rail)

- **Team key**: on first load generate `crypto.randomUUID()`, store in `localStorage`, send as `X-Pakka-Team` on every call. Show it here with a copy button and a paste field ("use this board on another device"). Without it the visitor is on the shared `demo` team, which is fine for the demo and refuses live settings.
- **Connectors**: one section per entry of `GET /connectors`. Show `mode` and `targets`. If `settings` is non-empty, one input per key with its hint as placeholder; a dict-valued key (`channels`, `endpoints`) is a name → value list with an add row. Save → `POST /connectors/{name}` with exactly those fields; 422 shows `detail` under the form; 403 means the user is on the shared team and needs a key. A "back to demo" button posts empty fields. Secrets are never returned, so after a save show "configured" and the targets, not the values.

## Build order

1. **Header + columns from `/state`** (one afternoon): render `runs[current_run]` into the four columns with cards and flags. Reset button. This already shows the Friday demo.
2. **Decide**: local decision collection, the one `POST /decide`, cascade preview on Discard, inline `errors`.
3. **Run**: prompt box, agent and connector pickers, `POST /job`, spinner, 422/409 handling. Free text now works end to end.
4. **Stats strip and learned rail** from what the responses already carry.
5. **Settings drawer**: team key, connectors. Retry button on failed deliveries.
6. Polish: montage and autopilot as "Play 5" and "Autopilot" buttons that loop `POST /run/{f}` (`auto_approve: true`) and `POST /autopilot/{f}` over `/state.montage_runs` and `/state.autopilot_runs`, exactly as the current page does.

## The demo path, on this board

1. Page opens on the shared team: Friday 1 is in the columns, 12 cards in Held, one with a grounding flag.
2. Discard the flagged one (cascade shows 2 more will fall), Yes-always on the proposed rule, Send decisions. Cards move; the rail fills.
3. Type a job in the box ("Do not pay anything. Open one ticket on the board listing what is due, then tell ops."), pick `live` and `tickets` + `webhook`. Run. Two cards land in Held with the agent's text. Approve. Footers say *simulated*.
4. Open Settings, paste a real Slack webhook URL, save: the connector tag flips to `live`. Run the same job again; approve; the footer says *delivered* and the message is in Slack.
5. Play 5, Autopilot: the same counters climb, four amber cards land in Held with their reasons.

## What not to build

- Anything that reads Logfire; the layer never does, and the board has everything on `/state`.
- A per-card decide call; decisions are one request per run.
- A "bring your own model key" form; agents are the deployment's.
- Polling for progress during a live run; the call is synchronous and returns the whole run.
