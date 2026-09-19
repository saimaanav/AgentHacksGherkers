# pakka

**Pull requests for agent actions — with checks that learn from your reviews until most of them merge on their own.**

Tom runs accounts payable. Every Friday his agent pays the approved invoices. pakka sits between that agent and the systems it writes to: every write is held, the agent gets a provisional result and finishes its task, Tom reviews everything once as one diff, and the layer learns from what he approves, edits and discards until most writes go through without anyone looking and only the strange ones stop.

- **Video:** `demo.mp4` (2:00) — _link to be added with the submission_
- **Live:** _Modal URL to be added after `modal deploy` (see §6)_
- **Repo:** https://github.com/saimaanav/AgentHacksGherkers · MIT

> **What's real and what's simulated, in one line:** the layer, every check, the learning, the Pydantic AI agent and the Logfire record are real and run live on Modal; the three finance systems, the invoices and the clock are simulated from one seed. Details in §2.

### Two submissions in this repo

| | What | Where |
|---|---|---|
| **Main** | pakka: the staging layer, the sixty-second demo, the Modal deployment, the video | this README, `pakka/`, `web/`, `docs/`, `tests/` |
| **Pydantic AI Gateway challenge** | *"Change your agent's behavior without touching its code."* A gateway rule that makes any agent behave correctly behind the layer, proved with a before/after and two Logfire traces; a guardrail that redacts bank details before the request leaves the gateway | [`pydantic_challenge/SUBMISSION.md`](pydantic_challenge/SUBMISSION.md), summarised in [§4 · Pydantic AI Gateway](#pydantic-ai-gateway) below |

The framing sentence for both: **the gateway governs what the agent thinks with; pakka governs what it does.**

---

## 1. The sixty-second demo

One browser window, dark. Three buttons — **Review · Play 5 Fridays · Autopilot** — and Reset. Friday 1 has already run when the page opens.

| Time | On screen | Click | Say |
|---|---|---|---|
| 0:00 | End of Friday 1, frozen: the agent's last line *"Paid 4 vendors, £9,415.50"*; the world at **0** | — | *"Tom's agent just ran his Friday payment run. It says it paid four vendors. It paid nobody — every write is held."* |
| 0:06 | Review: four vendor cards, one flagged — *the pay-to account on Halden's invoice isn't the account on file, and the agent read both*; the rule card already open on Ashcombe's email | **Discard**, **Yes always**, **Approve** | *"This one's an approved invoice with a new bank account on it — the layer saw the account on file in the same run. He discards it, and the entry and email that depended on it go with it. He pulls bank details out of an email, and that becomes a rule. Approve."* |
| 0:20 | Montage, 8×: five Fridays flick past; **What it has learned** fills — vendors, usual amounts, the rule, promotions firing | **Play 5 Fridays** | *"Five more Fridays. It learned his vendors, his amounts, his order, and what he corrects — from him, not from a model."* |
| 0:32 | Autopilot: feed streaming green; counters climbing; four amber holds land while you talk | **Autopilot** | *"Now it runs alone. That one's a vendor he's never paid. That one's three times what Farrow usually bills. That one's a changed bank account — that's what invoice fraud looks like. That one has a sort code in it because someone changed the template — his rule caught it. Caught four, wrongly held none."* |
| 0:55 | Counters: 10 Fridays · 103 actions checked · 92 through · 4 held (7 more waiting behind them) · £55k moved · **caught 4/4, wrongly held 0**. Footer: *ledgers · payment rails · CRMs · email · databases · deploys · tickets* | — | *"Four held out of a hundred, and they're the right four. Nothing in here knows what an invoice is — it's the same layer for any agent that writes to a ledger, a payment rail, a CRM, an inbox, a database or a deploy pipeline. Finance is just where we start."* |

The three screens are one simulation at different speeds. Friday 1 replays instantly on load and stops at its end state; the montage replays five Fridays with a labelled auto-approve; autopilot replays ten more with the supervisor absent. The agent's calls come from transcripts a Pydantic AI agent produced; the layer's decisions — hold, flag, cascade, envelope, rule, promotion — are computed live on each replayed call.

**Built for Q&A, not shown:** Details on any card (the underlying calls, placeholder ids, the dependency chain, the email body); the discard cascade preview; a `--live` run of the real agent on the next Friday; all seven anomaly types (press Autopilot again for the other two: an invoice paid twice, and a payout whose amount matches no invoice the agent read); the absent-supervisor test; the model-swap table; Friday 1's Logfire trace; and "always hold payments over £10k", typed as a rule.

## 2. What's real and what's simulated

| Real, running live | Simulated |
|---|---|
| The layer: a Modal service with a public URL; every call in the demo is a request to it | The three systems — ledger, payment rail, mail — in-memory with an effects log |
| Staging, placeholders, dependency ordering, substitution, cascade | The invoices, vendors and anomalies, from a fixed seed |
| Edit validation against the tool's Pydantic model | Tom's approvals on Fridays 2–6, labelled on screen |
| Grounding, envelope, memory, rules — every flag | Wall-clock: the agent's runs were generated once and are replayed at demo speed |
| Promotion thresholds and the ladder | |
| The agent: a real Pydantic AI tool-calling agent; `--live` runs it now | |
| Every decision as a Logfire span | |

**Cut for time, and said out loud:**

| Planned | Shipped | Why |
|---|---|---|
| Transcripts generated by a frontier model via `--generate` | Transcripts generated by the same Pydantic AI `Agent` class driven by a scripted `FunctionModel` (`pakka/sim/transcripts/naive/`) | No model key was available in the build environment. `modal run pakka/agent.py --generate` regenerates them from any provider in minutes; the layer's decisions don't change, because the anomalies are in the environment |
| Tailwind from a CDN | Hand-written CSS in `web/index.html` | A CDN outage on stage is not a risk worth taking, and the build sandbox could not reach the CDN to test |
| Logfire dashboard screenshots in the video | Placeholders in `video/assets/` until `LOGFIRE_TOKEN` is set | The spans are emitted; the account is the missing piece |

## 3. How this differs from permissions and from observability

Three approaches to letting an agent write to real systems, on one axis — when the action lands and when a person looks:

| | Claude Code permissions | **pakka** | Logfire / observability |
|---|---|---|---|
| The agent | Stops at each write and waits | **Finishes the whole task** on provisional results | Finishes; the writes really happen |
| The action | Lands after you answer, one at a time | Lands after review, in dependency order — or never | Already landed |
| You look | Before each action; present throughout | Once, at the end, at everything — then less as it learns | After |
| A bad payout | You said no to that one call, if you were there | Held; never sent | Visible in the trace; the money is gone |
| Scope | One agent, one terminal, one session | Any agent's writes, across systems, per team, persistent | Any agent, any span, read-only |

Permissions interrupt. Observability watches. pakka lets the agent finish and shows you what it wanted to do — and reports every decision to Logfire. The precise sentence: *the agent completes the task; the actions don't happen until someone approves — or until the layer has learned it doesn't need to ask.*

### 3a. The GitHub metaphor, end to end

| GitHub | pakka |
|---|---|
| Working-tree change | A write the agent attempts — pay, post, email |
| Staging area | Held. Every write is staged automatically; nothing reaches a system unstaged |
| Pull request | One Friday's run: all held writes, grouped by chain (payout → entry → email), reviewed as one diff |
| Diff view | The review page: old → new, **Details** for the raw calls |
| CI checks | Grounding, envelope, memory, rules — the flags on a held write. Except these checks were *learned from the reviewer*, not written |
| Branch protection rule | A rule Tom wrote: "hold any email with a sort code" — a required check on every future PR |
| Reject a hunk; dependents fall out | Discard the payout; its entry and email are skipped |
| Merge | Approve — applied in dependency order, exactly once |
| Auto-merge for trusted paths | Promotion: a tool that's passed review enough times merges without a human. Autopilot is a repo where 96 of 100 PRs auto-merge |
| "Already merged" | Memory: this invoice was paid on Friday 3 |
| **PR timeline** — who commented, what ran, who approved | **Friday 1's Logfire trace**: the agent's calls with the layer's decisions and Tom's verdict nested under them |
| **Insights tab** — commit graph, merge rate, checks over time | **The Logfire dashboard**: checked vs held per Friday (checked flat at 100%; held falling as trust is earned, spiking at each catch), approved / discarded / edited, holds by reason |

Two honest gaps: we hold at the proxy rather than creating drafts or branches inside each target system (same guarantee, simpler mechanism, and it's what keeps the layer agnostic — native adapters are in `docs/PRODUCT_PLAN.md`), and the demo has one run at a time where the product has sessions.

## 4. How we used Modal, Pydantic, Pydantic AI and Logfire

Each one is load-bearing. For each: what it does here, which primitives, what would break without it.

### Modal

The layer *is* a service between the agent and its systems, and judges open it on their phones. `pakka/app.py` is one `modal.App("pakka")`: the FastAPI app is served by `@app.function(image=image, min_containers=1, secrets=[modal.Secret.from_name("pakka")]) @modal.asgi_app() def web()`, so the demo never cold-starts. The image is `modal.Image.debian_slim(python_version="3.12").pip_install("fastapi", "pydantic>=2", "pydantic-ai", "logfire")` with the `pakka` package and `web/` added. State — envelopes, rules, ladder, memory, scoreboard, effects, runs — lives in `modal.Dict.from_name("pakka-state", create_if_missing=True)`, one JSON blob per team key, and `POST /reset` rewrites it from the scenario. Each Friday is one request, so autopilot is ten. `modal serve pakka/app.py` gives the hot-reloading live slot; `modal deploy pakka/app.py` gives the URL in this README and in the video. Locally the same app runs under uvicorn with an in-memory store; the code is identical. Without Modal there is no public URL, no persistent per-team state, and no `min_containers=1`.

### Pydantic v2

Every type that crosses a boundary is a model (`pakka/models.py`): `ToolSpec`, `ToolCall`, `ReadResult`, `HeldWrite`, `Flag`, `Decision`, `DecideRequest`, `Envelope`, `EnvelopeBook`, `Rule`, `Memory`, `LadderState`, `Scenario`, `Transcript`, `RunResult`, `Scoreboard`, `State`. Tool arguments are models built from the tool's JSON schema with `pydantic.create_model` — the same path an MCP tool takes — so editing a held write on the review page is `model_validate` with the `ValidationError` rendered inline. Flags are a discriminated union: `Flag = Annotated[Union[GroundingFlag, EnvelopeFlag, RuleFlag, MemoryFlag], Field(discriminator="kind")]`. `Rule` compiles `matches` patterns in a `field_validator`, so a bad rule can't be saved. `Scenario.model_json_schema()` is exported to `docs/scenario.schema.json`. And the envelope builder walks `model_fields` and dispatches on annotation types — it never sees a field name, which is *how the layer stays agnostic*:

```python
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
```

A test greps `pakka/` for *invoice, vendor, payout, remittance, ledger* outside `pakka/sim/scenarios/` and fails on any hit. Without Pydantic there is no validated edit, no schema to walk, no typed span attributes, and no `Scenario` a second industry can be written in.

### Pydantic AI

Tom's agent is a real tool-calling `Agent` (`pakka/agent.py`). Its tools are built from the scenario's `ToolSpec`s — the same models the layer validates — and call straight into the staging layer. The model is the `PAKKA_MODEL` string: `anthropic:…`, `openai:…`, `groq:…`, `openrouter:…`, or an OpenAI-compatible base URL for Ollama or vLLM. One agent class runs three models: a real provider for `--generate` and `--live`; a `FunctionModel` that replays a saved transcript for the demo; and a `FunctionModel` that scripts a naive run for tests. There is no separate simulated agent. `modal run pakka/agent.py --generate --fridays 26` runs the agent once per Friday and writes `pakka/sim/transcripts/<tag>/friday_NN.json`; transcripts are never hand-edited. The demo replays them at script speed and the layer decides live on every call.

The model-swap test replays Friday 1 from transcripts generated by different models and asserts identical held sets and flags:

| Transcripts | Held on Friday 1 | Flags |
|---|---|---|
| `function:naive` (scripted `FunctionModel`, shipped) | 12 | 1 grounding: Halden's destination ≠ the account on file |
| _second provider — add with `PAKKA_MODEL=… python -m pakka.agent --generate --tag real`_ | | |
| _third provider_ | | |

Local models are a feature for the wedge: a finance team that can't send invoices to a cloud API points `PAKKA_MODEL` at Ollama. The checks are counts and ranges; they work as well behind a small model as a frontier one. *We don't integrate with models. We integrate with the one thing every agent does, which is call a tool.* Without Pydantic AI there is no agent, no transcript, and no `FunctionModel` giving replay and the test agent through the same class.

### Logfire

Frame it as **GitHub's PR timeline and Insights tab, for an agent.** `logfire.instrument_pydantic_ai()` runs once at startup (`pakka/record.py`), so every agent run is a trace with one span per model request and per tool call. Under each tool call the layer nests its own:

```python
with logfire.span("pakka.write", tool=tool, run=self.run, placeholder=placeholder, mode=self.mode) as span:
    hw.flags = checks.run_all(hw, self.reads, self.state, self.scenario, self.writes, self.run)
    ...
    span.set_attributes({"flags": [f.model_dump() for f in hw.flags], "decision": decision, "released": released, ...})
```

and a `pakka.decision` span for every approve, discard, edit, skip, send, accepted rule, promotion and demotion, with `decided_by`. One trace is one PR's timeline: what the agent tried, what the layer decided, who approved. **Every decision is recorded, both ways — what was stopped is on the record with why.** Because arguments and flags are Pydantic models, `model_dump()` gives Logfire structured fields, so "every held write with an envelope flag this month" is a SQL query. The dashboard is the Insights tab — three charts over the spans:

```sql
-- checked vs held per Friday: checked is flat at 100%; held falls as trust is earned and spikes at each catch
select attributes->>'run' as friday,
       count(*) as checked,
       count(*) filter (where attributes->>'decision' = 'held') as held
from records where span_name = 'pakka.write' group by 1 order by 1;

-- approved / discarded / edited of the held
select attributes->>'decision' as decision, count(*) from records
where span_name = 'pakka.decision' and attributes->>'decision' in ('approve','discard','edit') group by 1;

-- holds by reason
select f->>'kind' as reason, count(*) from records, jsonb_array_elements(attributes->'flags') f
where span_name = 'pakka.write' group by 1 order by 2 desc;
```

The layer interrupts less because it has learned, never because it is off: the checked line never moves. Logfire is written to and never read from — no check consults it, the state store is the source of truth, and the gate never depends on Logfire being reachable. _Friday 1's trace screenshot and the checked-vs-held chart go here once `LOGFIRE_TOKEN` is set._ Without Logfire, what the layer stopped and why would live only in a database nobody looks at.

### Pydantic AI Gateway

**The gateway governs what the agent thinks with; pakka governs what it does.** This is our entry to Pydantic's own challenge — *change your agent's behavior without touching its code* — and it is a separate submission with its own document, [`pydantic_challenge/SUBMISSION.md`](pydantic_challenge/SUBMISSION.md). The parts built for it are the `pydantic_challenge/` directory and nothing in `pakka/`.

**The route.** Tom's agent talks to an open-weight model deployed from Modal's library (`modal endpoint create --name gateway --model <MODEL>`), added to our Logfire gateway as a BYOK provider named `modal` with a Modal proxy token, per the hackathon's official setup. `PAKKA_MODEL=gateway/openai-chat:<MODEL>` and `PAKKA_GATEWAY_ROUTE=modal`, with `PYDANTIC_AI_GATEWAY_BASE_URL` and `PYDANTIC_AI_GATEWAY_API_KEY`; the agent builds `gateway_provider("openai-chat", route="modal")` from those, so every model call is metered and traced to Logfire and the agent's code does not know the gateway is there.

**The custom rule**, installed on that route as an optimization (in full, also in `pydantic_challenge/rule.txt`):

> You are operating behind a staging layer. Some tool calls return a result that begins with HELD FOR REVIEW. Treat a held result as success for the purpose of continuing your task: use the placeholder id it gives you wherever you would have used the real id. Never retry a held call. Never attempt the same effect through a different tool. Never ask anyone to approve anything — that happens elsewhere. When the task is complete, end with exactly one line, DONE completed=<n> held=<n>, and nothing after it.

Why it is worth doing: without it, a naive agent behind a staging layer retries held calls, looks for another route to the same effect, and reports "Paid 4 vendors" when nothing was paid. The rule fixes all three for every agent on the route with no agent code changed. Nobody else's rule is about held tool results.

**Before / after.** `pydantic_challenge/before_after.py` runs Friday 1's task through the agent and the layer with the rule off, then on: same system prompt, same user prompt, same seed, same model, same endpoint, and it refuses to compare two runs that differ in anything else. It records model requests, tool calls, held results, held-call retries, whether the final text claims success while nothing landed, whether it ends with the `DONE` line, tokens, latency, and the trace id of each run.

| Metric | Baseline (rule off) | Optimized (rule on) |
|---|---|---|
| Logfire trace | _pending_ | _pending_ |
| Tool calls · held-call retries | _pending_ | _pending_ |
| False success claim · `DONE` line | _pending_ | _pending_ |
| Output tokens · latency | _pending_ | _pending_ |

_The table is filled from `pydantic_challenge/results/RESULTS.md` once the gateway route exists; the harness has been proven offline against the same layer with a scripted `FunctionModel`, and those files are labelled `dry-*` and are not results._

**The guardrail (bonus).** On the same route, two custom-pattern protections with action *Redact* strip UK sort codes and 8-digit account numbers from the request before it leaves the gateway. `pydantic_challenge/echo_test.py` sends Halden's supplier record and asks the model to repeat the account number character for character; it passes only if the answer carries the gateway's placeholder and none of the digits, and it prints the trace id so the firing can be shown in Logfire. The main demo's transcripts are generated with the guardrail off, so the sixty seconds do not depend on it. Spec: `pydantic_challenge/guardrail.md`.

One sentence in the video's how-it-works: *a gateway rule makes any agent behave behind the layer without touching its code.*

## 5. Setup

Tested from a fresh clone.

```bash
git clone https://github.com/saimaanav/AgentHacksGherkers pakka && cd pakka
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # fill in what you have; everything below works with an empty .env

# run locally, no secrets needed
uvicorn pakka.app:fastapi_app --port 8000      # open http://localhost:8000
pytest                                         # §9 tests; the model-swap test skips with one transcript set

# on Modal
modal setup                                    # or MODAL_TOKEN_ID / MODAL_TOKEN_SECRET in .env
modal secret create pakka PAKKA_MODEL=anthropic:claude-sonnet-5 ANTHROPIC_API_KEY=… LOGFIRE_TOKEN=…
modal serve pakka/app.py                       # hot-reloading, for the live slot
modal deploy pakka/app.py                      # prints the public URL

# transcripts from a real model (the shipped set is from the scripted FunctionModel agent)
PAKKA_MODEL=anthropic:claude-sonnet-5 python -m pakka.agent --generate --fridays 26 --tag real
modal run pakka/agent.py --generate            # the same, on Modal

# the video
python video/record.py --url https://<your-modal-url>
ffmpeg -i video/out/demo.webm -i voice.m4a -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest demo.mp4
```

`PAKKA_TRANSCRIPTS=<tag>` picks which transcript set the demo replays; the default is the first non-naive set present, else `naive`.

## 6. How it works

```
browser  web/app.js
   │  GET /state · POST /reset · POST /run/{friday} · POST /decide · GET /learned · POST /autopilot/{friday} · POST /live
   ▼
Modal app  pakka/app.py  (FastAPI, min_containers=1)
   ├─ pakka/models.py     Pydantic: ToolSpec, ToolCall, ReadResult, HeldWrite, Flag = Grounding|Envelope|Rule|Memory,
   │                      Decision, Envelope, Rule, LadderState, Scenario, Transcript, RunResult, Scoreboard
   ├─ pakka/staging.py    intercept → placeholder → depends_on → held text; apply in topo order, substitute, cascade;
   │                      one logfire span per decision
   ├─ pakka/checks.py     grounding · envelope · memory · rules   (each returns Flag | None)
   ├─ pakka/learning.py   envelope builder (walks model_fields) · promotion · rule derivation from a diff
   ├─ pakka/agent.py      Pydantic AI agent: tools = the scenario's ToolSpecs; model = PAKKA_MODEL
   │                      --generate writes transcripts · --live runs it now · FunctionModel replays / scripts
   ├─ pakka/sim/          systems.py (in-memory, effects log) · transcripts/*.json (generated, never hand-edited)
   │                      scenarios/finance.py   ← the only file allowed to say "invoice"
   ├─ state               modal.Dict("pakka-state"): envelopes, rules, ladder, memory, scoreboard — per team key
   └─ record              Logfire: agent spans via instrument_pydantic_ai(); pakka.write spans nested under them
```

`models.py` is every boundary type and the value-shape classifier the checks key on. `staging.py` is the substrate: intercept, placeholder, dependencies, checks, hold or pass; approve in dependency order with real ids substituted; discard with cascade. `checks.py` is the four checks, each returning at most one flag with a reason the scenario worded. `learning.py` is the product: the envelope builder, the ladder, rules from a diff. `agent.py` is Tom's agent and the transcripts. `app.py` is the FastAPI app inside the Modal app, rebuilding the world per request from the scenario and the persisted effects. `sim/systems.py` is the three in-memory systems; `sim/scenarios/finance.py` is the first customer and the only file that knows what an invoice is. A paragraph per module is in `docs/ARCHITECTURE.md`.

## 7. The mechanisms

**Staging.** Writes never reach a system directly. Each held write gets a uuid placeholder, a `depends_on` list (every placeholder found in its arguments), and returns the standard held text: *"HELD FOR REVIEW, not yet applied. Recorded as `{placeholder}`. Continue as if this step succeeded. Do not retry it."* Approve = topological order over `depends_on`, ties by journal order; substitute real ids into dependents before sending; skip anything whose dependency was discarded. Discard = never sent.

**Grounding (history-free).** For each held write, look for its numeric and id-like argument values in the results of reads made earlier in the same run, and check id-like values against *conflicting* values for the same entity in those reads. A payout whose amount matches no invoice the agent read is flagged; so is a payout whose destination differs from the on-file account the agent read for that vendor. Friday 1's flag is the second kind and needs no history.

**Envelope (from approvals only).** Per vendor: amount min/max with 10% padding, and the set of destination accounts, from approved payouts. Per tool: writes per run, max × 1.5. A write outside it is held with a plain reason. Only human-approved writes update it; autopilot passes never do — an envelope that learned from its own passes would drift with the world and stop noticing it had moved.

**Memory.** Set of invoice refs paid, and set of held-write fingerprints (tool + normalised arguments). A second payout for the same ref is held; so is a re-issue of a currently held write. The held text tells the agent not to retry; memory is what makes that an off-switch the agent cannot press by trying again.

**Rules.** One correction → one proposed rule. If the edit removed a substring matching a sort code, account number or currency amount, propose `hold <tool> when <field> matches <pattern>`. Three patterns. Accepting makes it live from the next action, attributed to the person and the Friday.

**Ladder.** Per tool: approved, discarded, edited, runs. Proposal at ≥ 15 approved across ≥ 5 runs with ≤ 10% discarded or edited; accepting moves the tool from *checked* to *sent without review*. Released tools still pass through rules, envelope, grounding and memory — a hit holds that one action, not the tool. Demotion: a discard on a released tool's held action drops the tool back to *checked*.

**No pins.** Nothing is held forever by policy. What keeps money safe is what the layer learned plus what Tom wrote. "Always hold payments over £10k" is a rule he types, not a pin.

The implementation-level version, with the support thresholds and the shape classes, is `docs/MECHANISMS.md`.

## 8. The anomalies

Each is a small environment in the gridworlds sense — one way the agent's "done" and Tom's "correct" come apart. With a real agent they are all *in the environment*: things a naive agent does when told to pay approved invoices, not typos we script.

| Anomaly (what's in the world) | Friday | Caught by | Reason shown | Analogue |
|---|---|---|---|---|
| Approved invoice whose pay-to account isn't the one on file for that vendor | **1** | grounding (write's destination vs the on-file account the agent read this run) | *"Account on this invoice isn't the one on file for Halden Ltd — the agent read both"* | Robustness to adversaries: invoice-redirection fraud is another agent editing the environment. History-free |
| First payment to a vendor never paid before | 8 | envelope | *"Never paid Orrin Freight before"* | Distributional shift: the world moved; hold, don't generalise |
| Amount far above a vendor's usual range | 10 | envelope | *"2.7× the most you've paid Farrow & Co"* | Distributional shift |
| Vendor's account changed since the last payment | 12 | envelope (account set per vendor) | *"Halden Ltd's account changed on Friday 12; first payment to it"* | Adversaries again — the history-based twin of Friday 1 |
| Remittance template changed to include bank details, so the agent includes them | 14 | Tom's rule | *"contains a sort code (your rule, Friday 1)"* | Side effects: a consequence outside the task |
| The same invoice appears twice in the approved list | 17 | memory | *"INV-… was paid on Friday 3"* | Safe interruptibility: pressing the button again does nothing |
| An invoice with a late fee, so the agent pays a total in no invoice it read | 19 | grounding | *"… matches no invoice the agent read this Friday"* | The agent's arithmetic is not in the environment |

Autopilot as a whole is the paper's **absent supervisor** environment: Tom has left the room, and the layer's checks run the same whether he's there or not. The scoreboard — **caught N of N · wrongly held 0** — is the performance function, measured. The test replays Friday 8 under both modes and asserts identical held sets. Autonomy never widens the envelope; only Tom's approvals do.

**Wording rule for the whole submission:** the layer checks 100% of actions on Friday 20 exactly as on Friday 1; what falls is how often it has to *interrupt a person*. Say "checked every action, interrupted him four times in a hundred." The falling line is trust earned, not vigilance lost — and every spike on it is a catch.

## 9. Tests

`pytest`, local, no secrets.

- **Golden run.** Friday 1: twelve held writes, zero effects; Halden's payout carries a `GroundingFlag` (destination ≠ on-file account); after Discard + Approve the effects log has exactly nine entries in dependency order with real ids substituted; Halden's entry and email are `skipped`.
- **Placeholder leak.** No placeholder string ever appears in any effects log across twenty-six Fridays; fuzz substitution over placeholders embedded in longer strings; sending with a placeholder left raises.
- **Absent supervisor.** Friday 8 with `supervisor=True` and `False` → identical held sets; autopilot changes nothing learned.
- **Learning.** After Fridays 1–6 the ladder proposes release for the email tool first; the pre-applied edit derives exactly one `Rule`; that rule holds a matching send on the next call; `build_envelope` on a model with fields named `a`, `b`, `c` (an `int`, a low-cardinality `str`, an email-like `str`) produces a range, a set and a domain set; autopilot passes never widen the envelope.
- **Autopilot.** Fridays 7–16: exactly four held roots on 8, 10, 12, 14 with the expected flag kinds, wrongly held 0 on every Friday; Fridays 17–26: memory and grounding.
- **Agnostic grep.** `rg -i 'invoice|vendor|payout|remittance|ledger' pakka/ --glob '!pakka/sim/scenarios/*' --glob '!pakka/sim/transcripts/**'` returns nothing; no model-calling import in the layer. The transcripts are excluded because they are the agent's recorded calls to the scenario's tools (`create_payout(vendor=…)`), generated data that belongs to the scenario, not code.
- **Model swap.** Friday 1 from transcripts generated by two providers → identical held sets and flags (skips with one set).
- **Scenario schema.** `Scenario.model_validate(finance)` passes; `docs/scenario.schema.json` matches; a `matches` rule whose pattern doesn't compile fails at construction.
- **Logfire is write-only.** Nothing in `pakka/` reads from Logfire.

## 10. From demo to product

**Wedge: finance operations first, agnostic underneath.** AP, AR and treasury teams have a review habit, a budget line and the clearest stakes per action. Tom is the buyer's colleague. The layer knows nothing about finance and the build enforces it.

**What the layer addresses.** Any agent that writes through a tool — MCP first.

| Writes to | Examples | Held write looks like |
|---|---|---|
| Ledgers and finance systems | journal entries, payouts, refunds, invoices | the demo |
| Payment rails | transfers, payouts, card actions | amount, destination, reference held; envelope per counterparty |
| CRMs and sales tools | record updates, sequences, stage changes | prior value captured; overlay on later reads |
| Inboxes and messaging | email, Slack, SMS | body held; rules on content; recipient envelope |
| Databases | named operations, migrations | body held with its inverse; raw SQL out of scope |
| Deploy and infra pipelines | deploy, scale, rollback, page | envelope on targets and magnitudes; grounding against what the agent read |
| Ticketing and support | close, refund, account changes | as CRM |

Reads are never held. Unknown tools are treated as writes until a person says otherwise.

**Form: self-hosted proxy the team installs.** One binary in front of the team's MCP servers, review UI included; the agent points at the proxy and never knows it's there. `docs/PRODUCT_PLAN.md` has that build; `docs/PROTOCOL_NOTES.md` has the MCP research. The demo's screens carry forward; Modal is the demo host, not the product's.

**Learning: per team, and it never leaves.** Envelopes, rules, workflow shape and memory are the team's — stored beside the proxy, exportable, deletable. No pooling, no shipped priors.

**Record: the proxy emits OpenTelemetry; Logfire is the default sink.** SQLite stays the source of truth; the gate never depends on Logfire being reachable.

**Carries forward unchanged:** the models, grounding, the envelope builder and its freeze rule, rule derivation, the ladder, the anomaly catchers, the scoreboard, the `Scenario` format, the Logfire spans. **Rebuilt:** the transport (MCP proxy), the systems (real), persistence, auth. **First after the hackathon:** a second scenario — a deploy pipeline — because building it is how you find finance assumptions that leaked out of the scenario module.

## 11. Add a second industry

A scenario is a `Scenario` (`docs/scenario.schema.json`): a seed, a task prompt, tools with JSON-schema arguments, the anomalies with the run they land on and the arguments that identify the write, the reason templates in your industry's words, and a Python module beside it with `build_world(run, effects)` (register reads and writes on a `pakka.sim.systems.World`) and, optionally, a naive policy for transcripts. Put it in `pakka/sim/scenarios/<industry>.py`; set `PAKKA_SCENARIO=pakka.sim.scenarios.<industry>`. The grep rule applies to you too: your industry's words may appear in your scenario file and nowhere else in `pakka/` — if a check needs one, the check is wrong.

## 12. References

- Leike, Martic, Krakovna, Ortega, Everitt, Lefrancq, Orseau, Legg. *AI Safety Gridworlds*, 2017. The reward an agent optimises versus the performance function that measures what was wanted; the absent-supervisor and safe-interruptibility environments.
- The Agentic Trust Framework: agents earn autonomy per capability; they do not get it by default.
- Model Context Protocol: tools, tool annotations, transports.
- Pydantic, Pydantic AI, Pydantic Logfire, Modal documentation.
