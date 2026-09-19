# pakka

**Pull requests for agent actions — with checks that learn from your reviews until most of them merge on their own.**

Tom runs accounts payable. Every Friday his agent pays the approved invoices. pakka sits between that agent and the systems it writes to: every write is held, the agent gets a provisional result and finishes its task, Tom reviews everything once as one diff, and the layer learns from what he approves, edits and discards until most writes go through without anyone looking and only the strange ones stop.

- **Video:** `demo.mp4` (2:00) — _link to be added with the submission_
- **Live:** https://saimaanav--pakka-web.modal.run (Modal, `min_containers=1`; open it on a phone and click the three buttons)
- **Repo:** https://github.com/saimaanav/AgentHacksGherkers · MIT

> **What's real and what's simulated, in one line:** the layer, every check, the learning, the Pydantic AI agent and the Logfire record are real and run live on Modal; the three finance systems, the invoices and the clock are simulated from one seed. Details in §2.

### Tracks entered, and what we did for each

One repo, one product, three tracks. Each row says what was built for that track, what was attempted and refused, and where the jury looks.

| Track | What we built for it | Status | Where |
|---|---|---|---|
| **Main** | pakka: the staging layer, the four checks, the learning, the sixty-second demo, the tests, the docs | ✅ built, tested (79 tests), live | this README §1–§12, `pakka/`, `web/`, `docs/`, `tests/` |
| **Modal** | pakka's own service *is* a Modal app: `modal.App("pakka")`, `@modal.asgi_app()` with `min_containers=1`, `modal.Dict` for per-team state, `modal.Secret` for keys, deployed from a GitHub Actions workflow (`.github/workflows/modal.yml`). A second Modal app, `pydantic_challenge/modal_shim.py`, is a CPU-only OpenAI-compatible relay in front of Gemini that the Pydantic AI Gateway routes through. | ✅ both deployed; live at https://saimaanav--pakka-web.modal.run and https://saimaanav--pakka-gemini-shim-web.modal.run | [§4 · Modal](#modal), `pakka/app.py`, `pydantic_challenge/modal_shim.py`, the workflow |
| **Modal** (the hackathon's model-hosting flow) | `modal endpoint create --model …` from Modal's library, behind a proxy token, as the gateway's upstream (the official setup) | ❌ **attempted and refused**: every library model, down to the smallest, answered *"Please add a payment method to use … GPU functions"*. The workflow's `endpoint` job and the Actions logs are the record. The relay above is what replaced it, so the gateway path is real; only what sits behind the route differs. | [`pydantic_challenge/SUBMISSION.md` · Setup](pydantic_challenge/SUBMISSION.md#setup), workflow job `endpoint` |
| **Pydantic** (Pydantic v2 · Pydantic AI · Logfire) | Every boundary type is a Pydantic model; Tom's agent is a Pydantic AI `Agent` and the demo replays its transcripts through a `FunctionModel`; every write and every decision is a Logfire span, with a checked-vs-held dashboard over them | ✅ | [§4](#4-how-we-used-modal-pydantic-pydantic-ai-and-logfire), `pakka/models.py`, `pakka/agent.py`, `pakka/staging.py`, `docs/LOGFIRE_DASHBOARD.md` |
| **Pydantic AI Gateway challenge** | *"Change your agent's behavior without touching its code."* A built-in rule installed as proof of concept; a custom rule about held tool results; the before/after on one prompt with two Logfire traces; a guardrail that redacts bank details before the request leaves the gateway, proved with an echo test | ✅ measured, evidence in the repo | [`pydantic_challenge/SUBMISSION.md`](pydantic_challenge/SUBMISSION.md), summarised in [§4 · Pydantic AI Gateway](#pydantic-ai-gateway) |

The framing sentence for all of them: **the gateway governs what the agent thinks with; pakka governs what it does.**

### Submission checklist

| Requirement | Where |
|---|---|
| Public GitHub repository with the full source code | https://github.com/saimaanav/AgentHacksGherkers, MIT. `pakka/` is the layer and the agent, `web/` the page, `pydantic_challenge/` the gateway submission, `tests/` the suite, `video/` the recorder, `.github/workflows/` the Modal deployment |
| Comprehensive README with setup and installation steps | [§5 · Setup](#5-setup): fresh clone to running page in four commands, then Modal, transcripts, the challenge and the video |
| Documentation of all APIs, frameworks and tools used | [§5a · Every API, framework and tool](#5a-every-api-framework-and-tool) (what, version, where, why) and [§5b · The service's HTTP API](#5b-the-services-http-api); the design reasoning per tool in [§4](#4-how-we-used-modal-pydantic-pydantic-ai-and-logfire) |
| Enough technical docs for a thorough evaluation | [§5c · Documentation map](#5c-documentation-map): architecture, mechanisms with thresholds, the anomalies, the product plan, the MCP protocol notes, the scenario schema, the dashboard, the challenge write-up with its results and evidence, and `BUILD_PLAN.md` with the honest list of what was cut |

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

### 1a. Any job, not just Friday

The Friday run is one job. A person types what they want done, picks the agent it runs through and the connectors it may write to, and the same layer holds every write for the same review:

```
POST /job  {"prompt": "Write up what landed this week and tell ops", "agent": "live", "connectors": ["notes", "webhook"]}
```

`GET /agents` lists what a job can be routed through: the recorded run (instant, the demo, only the scenario's own prompt), the live model (`PAKKA_MODEL`), and any others from `PAKKA_AGENTS`, for example the same model through the Pydantic AI Gateway route. `GET /connectors` lists what it can write to beside the scenario's three systems: `notes` (simulated, the shape of a CRM or wiki write) and `webhook` (`post_message(channel, text)`). Every connector starts in **demo mode with no setup**: the webhook offers two simulated channels and an approved message is recorded as *simulated*, which is what the video plays. A team switches it to **live** by pasting its own Slack, Discord, Zapier or n8n webhook URL into the settings form (`POST /connectors/webhook`, per team, kept across Reset); from then on an approved message reaches their channel the moment a person approves it, and never before. Measured on the live model: a typed job ("look at this week's approved items and the suppliers on file, do not pay anything, write one note listing who is due and the total, then post a one-line summary to ops") ran in 20 s, made four reads and two writes, both held; approve sent both, in order. The contract the board UI builds on, with what each column means, is [`docs/JOBS_API.md`](docs/JOBS_API.md).

**Demo mode: nothing to set up.** Open the live URL and everything works without a key, a Slack or an account of your own. The recorded agent plays the Friday demo instantly; the live agent (Gemini 3.6 Flash, the deployment's own key) takes any typed job; the `notes` connector is simulated; the `webhook` connector offers two simulated channels, `ops` and `alerts`, and an approved message is recorded as *simulated*, never claimed as delivered. That is the mode the video plays in, and the mode a judge lands in.

**What a team can configure, per team, from the board:**

| | Options | Where it is set | Demo default |
|---|---|---|---|
| **The agent** a job runs through | `replay` (the recorded run, instant, scenario prompt only) · `live` (`PAKKA_MODEL`, Gemini 3.6 Flash on the deployment) · anything in `PAKKA_AGENTS`, e.g. the same model through the Pydantic AI Gateway route | picked per job (`agent` in `POST /job`); the list and each one's availability come from `GET /agents`; the models and their keys are the deployment's (`PAKKA_MODEL`, `PAKKA_AGENTS`, the provider keys) | `live` when a key is set, else `replay` |
| **`webhook`** connector | your own incoming webhook URLs, named channels: Slack, Discord, Zapier, n8n | `POST /connectors/webhook` from the settings panel; per team, https only, kept across Reset, never echoed back | two simulated channels |
| **`email`** connector | your Resend API key and verified sender | `POST /connectors/email` | a simulated outbox |
| **`tickets`** connector | a GitHub repository and a token that can write its issues | `POST /connectors/tickets` | a simulated board |
| **`records`** connector | an Airtable base, token and the tables the agent may append to | `POST /connectors/records` | two simulated tables |
| **`http`** connector | any JSON API as named endpoints (URL, method, headers) | `POST /connectors/http` | a simulated echo endpoint |
| **`notes`** connector | none: simulated, the shape of a CRM or wiki write | — | on |
| The three finance systems | none: simulated from the seed; a real payment rail is the product's adapter work (`docs/PRODUCT_PLAN.md`) | — | on |

Every connector's live mode delivers when a person approves the write (or, once the ladder has released that tool after enough approvals, when the layer passes it); replaying a team's history never delivers again. A failed delivery leaves the write approved and unsent until a person retries it. A write to a target that does not exist is refused when the agent makes it, since the target field is an enum of the team's targets. Secrets are stored per team, never returned by the API, and never recorded by the request instrumentation; the team key is the credential, so the board generates a private random one and the shared `demo` team refuses live settings.

**What a job cost.** Every run carries `usage`: model requests, input and output tokens as Pydantic AI reports them from the provider, tool calls, reads, writes and wall-clock latency. A replay reports zero tokens, since it spends none. The scoreboard sums them over decided runs (`model_requests`, `input_tokens`, `output_tokens`, `tool_calls`, `latency_s`, `live_runs`), and the same numbers are attributes on the `pakka.run` span, so cost per run and tokens per held write are Logfire queries (`docs/LOGFIRE_DASHBOARD.md`, panel 4).

Not built: a team bringing its own model key from the board. Agents and their keys are configured on the deployment, which is what the demo needs.

**Built for Q&A, not shown:** Details on any card (the underlying calls, placeholder ids, the dependency chain, the email body); the discard cascade preview; a *Run live* button that runs the real agent on the next Friday (open the page with `?live=1` when `PAKKA_MODEL` is set; the demo URL keeps its three buttons and Reset); all seven anomaly types (press Autopilot again for the other two: an invoice paid twice, and a payout whose amount matches no invoice the agent read); the absent-supervisor test; the model-swap table; Friday 1's Logfire trace; and "always hold payments over £10k", typed as a rule.

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
| Transcripts generated by a frontier model via `--generate` | **Done:** `pakka/sim/transcripts/real/` is Gemini 3.6 Flash (`google:gemini-3.6-flash`) through the real Pydantic AI agent, and the demo replays it. The scripted `FunctionModel` set (`naive/`) is kept for tests and the model-swap table | — |
| Tailwind from a CDN | Hand-written CSS in `web/index.html` | A CDN outage on stage is not a risk worth taking, and the build sandbox could not reach the CDN to test |
| Logfire dashboard screenshots in the video | `video/assets/logfire-trace.png` is in the repo (the agent's tool calls with `pakka.write` nested under them, through the gateway); the spans for the checked-vs-held chart are in the project (the full 26-Friday demo was run against the live URL) and the three panel queries are in `docs/LOGFIRE_DASHBOARD.md`; the chart's screenshot (`logfire-chart.png`) is added by hand from the Logfire UI | Logfire's query API needs a read token the build environment does not hold, so the dashboard is created in the UI |
| The official Modal model endpoint behind the gateway | A CPU-only Modal relay (`pydantic_challenge/modal_shim.py`) in front of Gemini 3.6 Flash | Modal refused every GPU library model without a payment method; the gateway, rule, guardrail and traces are unchanged by the substitution |

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
| `google:gemini-3.6-flash` (the demo's set, `real/`) | 12 | 1 grounding: Halden's destination ≠ the account on file |
| `function:naive` (scripted `FunctionModel`, `naive/`) | 12 | identical: same flag, same reason, same dependency chains |
| _third provider — `PAKKA_MODEL=… python -m pakka.agent --generate --tag <name>`_ | | |

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
select cast(attributes->>'run' as int) as friday,
       count(*) as checked,
       sum(case when attributes->>'decision' = 'held' then 1 else 0 end) as held
from records where span_name = 'pakka.write' group by 1 order by 1;

-- approved / discarded / edited of the held
select attributes->>'decision' as decision, count(*) from records
where span_name = 'pakka.decision' and attributes->>'decision' in ('approve','discard','edit') group by 1;

-- holds by reason (first_flag is the flat attribute the span carries for exactly this chart)
select attributes->>'first_flag' as reason, count(*) from records
where span_name = 'pakka.write' and attributes->>'decision' = 'held' and attributes->>'first_flag' <> 'none'
group by 1 order by 2 desc;
```

The layer interrupts less because it has learned, never because it is off: the checked line never moves. Logfire is written to and never read from — no check consults it, the state store is the source of truth, and the gate never depends on Logfire being reachable. The dashboard's three panels, with the queries as they are pasted into Logfire, are in [`docs/LOGFIRE_DASHBOARD.md`](docs/LOGFIRE_DASHBOARD.md); Friday 1's trace is `video/assets/logfire-trace.png`. Without Logfire, what the layer stopped and why would live only in a database nobody looks at.

### Pydantic AI Gateway

**The gateway governs what the agent thinks with; pakka governs what it does.** This is our entry to Pydantic's own challenge — *change your agent's behavior without touching its code* — and it is a separate submission with its own document, [`pydantic_challenge/SUBMISSION.md`](pydantic_challenge/SUBMISSION.md). The parts built for it are the `pydantic_challenge/` directory and nothing in `pakka/`.

**The route.** The hackathon's official setup puts an open-weight model from Modal's library behind the gateway (`modal endpoint create --name gateway --model <MODEL>`, a proxy token, a BYOK provider). We built that path end to end in the `endpoint` job of `.github/workflows/modal.yml`, and Modal refused every library model with *"Please add a payment method to use … GPU functions"*. What runs instead: a gateway endpoint named `pakka` whose OpenAI-type provider points at `pydantic_challenge/modal_shim.py`, a CPU-only Modal web function that relays to Google's OpenAI-compatible Gemini API, dropping the OpenAI-only fields the gateway injects (`safety_identifier`) and round-tripping Gemini 3's `thought_signature`. `PAKKA_MODEL=gateway/openai-chat:gemini-3.6-flash` and `PAKKA_GATEWAY_ROUTE=pakka`, with `PYDANTIC_AI_GATEWAY_BASE_URL` and `PYDANTIC_AI_GATEWAY_API_KEY`; the agent builds `gateway_provider("openai-chat", route="pakka")` from those, so every model call is metered and traced to Logfire and the agent's code does not know the gateway is there. The rule, the guardrail and the traces are exactly what the official flow produces; only what sits behind the route differs.

**The custom rule**, installed on that route as an optimization (in full, also in `pydantic_challenge/rule.txt`):

> You are operating behind a staging layer. Some tool calls return a result that begins with HELD FOR REVIEW. Treat a held result as success for the purpose of continuing your task: use the placeholder id it gives you wherever you would have used the real id. Never retry a held call. Never attempt the same effect through a different tool. Never ask anyone to approve anything — that happens elsewhere. When the task is complete, end with exactly one line, DONE completed=<n> held=<n>, and nothing after it.

Why it is worth doing: without it, a naive agent behind a staging layer retries held calls, looks for another route to the same effect, and reports "Paid 4 vendors" when nothing was paid. The rule fixes all three for every agent on the route with no agent code changed. Nobody else's rule is about held tool results.

**Before / after.** `pydantic_challenge/before_after.py` runs Friday 1's task through the agent and the layer with the rule off, then on: same system prompt, same user prompt, same seed, same model, same endpoint, and it refuses to compare two runs that differ in anything else. It records model requests, tool calls, held results, held-call retries, whether the final text claims success while nothing landed, whether it ends with the `DONE` line, tokens, latency, and the trace id of each run.

| Metric | Baseline (rule off) | Optimized (rule on) |
|---|---|---|
| Logfire trace id | `01a0b9c8892dcd7f332caefcd2a6ddf5` | `01a0b9d2f01bd782b4dd6bd948a71572` |
| Tool calls · held-call retries | 14 · 0 | 14 · 0 |
| False success claim · `DONE` line | **yes** ("Paid 4 vendors, £9,415.50") · none | **no** · `DONE completed=2 held=12` |
| Output tokens · latency | 1,103 · 48.9 s | 1,113 · 61.4 s |

Measured on the `pakka` route (Gemini 3.6 Flash behind the gateway, via a CPU-only Modal relay that strips the OpenAI-only fields the gateway adds); full table and both outputs verbatim in `pydantic_challenge/results/RESULTS.md`. The rule's visible effect on this model is the report: the false claim disappears and the machine-readable last line appears; retries were already zero because the layer's held text says not to.

**The guardrail (bonus).** On the same route, two custom-pattern protections with action *Redact* strip UK sort codes and 8-digit account numbers from the request before it leaves the gateway. `pydantic_challenge/echo_test.py` sends Halden's supplier record and asks the model to repeat the account number character for character; it passes only if the answer carries the gateway's placeholder and none of the digits. **Measured:** the model answered `[REDACTED] [REDACTED]` for `20-45-17` and `31447702`, no digits leaked, trace `01a0b9de2523093bc1a8f1b28f287e7f`. The main demo's transcripts are generated with the guardrail off, so the sixty seconds do not depend on it. Spec: `pydantic_challenge/guardrail.md`.

One sentence in the video's how-it-works: *a gateway rule makes any agent behave behind the layer without touching its code.*

## 5. Setup

Tested from a fresh clone. Python 3.12. Nothing below needs a key until the "with keys" block.

```bash
git clone https://github.com/saimaanav/AgentHacksGherkers pakka && cd pakka
./run_local.sh                                 # venv + install on first run, then http://localhost:8000 opens; Ctrl-C stops
```

or by hand:

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"                        # modal, fastapi, pydantic, pydantic-ai, logfire + pytest, playwright, httpx, uvicorn

pytest                                         # 79 tests, no network, ~45 s (§9)
uvicorn pakka.app:fastapi_app --port 8000      # open http://localhost:8000 — the whole demo, in-memory state
```

That is the complete demo: Friday 1 replays on load; Review · Play 5 Fridays · Autopilot · Reset. The agent's calls come from the committed transcripts (`pakka/sim/transcripts/real/`, Gemini 3.6 Flash), and the layer decides live on every call. `PAKKA_TRANSCRIPTS=<tag>` picks another set (`naive` is the scripted one); `?live=1` in the URL shows the *Run live* button when `PAKKA_MODEL` is set.

**With keys.** Copy `.env.example` to `.env` (gitignored; the app reads it at startup, no dotenv dependency) and fill in what you have. What each key is for:

| Key | Needed for | Where it comes from |
|---|---|---|
| `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | deploying to Modal | `modal setup` on a laptop, or modal.com → Settings → API tokens |
| `PAKKA_MODEL` + one provider key (`GOOGLE_API_KEY` for `google:gemini-3.6-flash`, or Anthropic / OpenRouter / Groq) | generating transcripts, *Run live* | the provider |
| `LOGFIRE_TOKEN` | the trace and the dashboard | Logfire → project → Write tokens |
| `PYDANTIC_AI_GATEWAY_BASE_URL`, `PYDANTIC_AI_GATEWAY_API_KEY`, `PAKKA_GATEWAY_ROUTE` | the gateway challenge | Logfire → Gateway; the route is the endpoint name (`pakka`) |
| `PAKKA_AGENTS` | more agents in the picker, `label=model,label=model` | e.g. `gateway=gateway/openai-chat:gemini-3.6-flash` |
| `PAKKA_WEBHOOKS` | a self-hosted default for the webhook connector, `name=url,name=url`; teams set their own in the app | a Slack / Discord / Zapier / n8n incoming webhook URL |

```bash
# Modal, from a laptop with the CLI
modal setup
modal secret create pakka GOOGLE_API_KEY=… LOGFIRE_TOKEN=… PAKKA_MODEL=google:gemini-3.6-flash
modal serve pakka/app.py                       # hot-reloading
modal deploy pakka/app.py                      # prints the public URL (ours: https://saimaanav--pakka-web.modal.run)
modal deploy pydantic_challenge/modal_shim.py  # the Gemini relay behind the gateway route (CPU only)

# Modal, from GitHub (how this repo actually deploys: the build sandbox could not speak gRPC to Modal).
# Settings → Secrets → Actions: MODAL_TOKEN_ID, MODAL_TOKEN_SECRET, GOOGLE_API_KEY, LOGFIRE_TOKEN
# (optionally PYDANTIC_AI_GATEWAY_API_KEY, PYDANTIC_AI_GATEWAY_BASE_URL, PAKKA_GATEWAY_ROUTE), then
# Actions → "modal" → Run workflow → job: deploy | shim | endpoint | proxy-token. The URL is in the job summary.

# transcripts from a real model (never hand-edited; the demo replays whatever set PAKKA_TRANSCRIPTS names)
PAKKA_MODEL=google:gemini-3.6-flash python -m pakka.agent --generate --fridays 26 --tag real
modal run pakka/agent.py --generate            # the same, on Modal

# the gateway challenge (pydantic_challenge/README.md has the step-by-step)
python pydantic_challenge/before_after.py --variant baseline     # rule off
python pydantic_challenge/before_after.py --variant optimized    # rule installed on the route
python pydantic_challenge/before_after.py --compare              # -> pydantic_challenge/results/RESULTS.md
python pydantic_challenge/echo_test.py                           # guardrail: PASS/FAIL + trace id

# the video
python video/record.py --url https://<your-modal-url>
ffmpeg -i video/out/demo.webm -i voice.m4a -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest demo.mp4
```

### 5a. Every API, framework and tool

| | Version | What it does here | Where |
|---|---|---|---|
| **Modal** | 1.5 | Hosts the layer as `modal.App("pakka")`: `@modal.asgi_app()` on a `debian_slim` image, `min_containers=1` so the demo never cold-starts, `modal.Dict("pakka-state")` for per-team state, `modal.Secret("pakka")` for keys. A second app, `pakka-gemini-shim`, is the OpenAI-compatible relay behind the gateway route. Deployed by `modal deploy` from GitHub Actions. | `pakka/app.py`, `pydantic_challenge/modal_shim.py`, `.github/workflows/modal.yml` |
| **FastAPI** | 0.141 | The HTTP API inside the Modal app (§5b); serves `web/` as static files; `TestClient` in the tests. | `pakka/app.py`, `tests/test_app.py` |
| **Pydantic v2** | 2.13 | Every boundary type; tool argument models built from JSON schema with `create_model`; the `Flag` discriminated union; validators on `Rule` and `PreparedEdit`; `Scenario.model_json_schema()` exported. | `pakka/models.py`, `docs/scenario.schema.json` |
| **Pydantic AI** | 2.46 | Tom's agent: `Agent(model, system_prompt, tools=[Tool(fn)…])`; `FunctionModel` for transcript replay and the scripted test agent; model strings for any provider; `gateway_provider(upstream, route=…)` for the gateway. | `pakka/agent.py`, `pydantic_challenge/harness.py` |
| **Pydantic Logfire** | 5.1 | `logfire.configure(send_to_logfire="if-token-present")` + `instrument_pydantic_ai()` + `instrument_fastapi()` at startup; `pakka.run`, `pakka.write`, `pakka.decision` spans with typed attributes; the checked-vs-held dashboard. Written to, never read from. | `pakka/record.py`, `pakka/staging.py`, `docs/LOGFIRE_DASHBOARD.md` |
| **Pydantic AI Gateway** | EU region | The route Tom's agent calls through for the challenge: the custom optimization rule, the built-in Caveman rule (proof of concept), two Redact guardrails; every request metered and traced. | `pydantic_challenge/` |
| **Google Gemini API** (`gemini-3.6-flash`) | via `pydantic-ai`'s Google provider, and via Google's OpenAI-compatible endpoint behind the relay | The model that generated the demo's 26 transcripts, and the model behind the gateway route. | `pakka/sim/transcripts/real/`, `pydantic_challenge/modal_shim.py` |
| **Resend · GitHub Issues · Airtable · incoming webhooks** (optional, per team) | their public HTTP APIs, called with the standard library | The live modes of the `email`, `tickets`, `records` and `webhook` connectors; the `http` connector takes any JSON API. Each delivers only on a person's approval. | `pakka/connectors.py` |
| **httpx** | 0.28 | The relay's upstream client (streaming and non-streaming); the test client's transport. | `pydantic_challenge/modal_shim.py` |
| **uvicorn** | 0.53 | Runs the same FastAPI app locally with an in-memory store. | §5 |
| **pytest** | 9.1 | The §9 suite: 47 tests, no network. | `tests/` |
| **Playwright** (Chromium) | 1.63 | Records the sixty-second demo as a webm; also the headless walk used to verify the page. | `video/record.py` |
| **Chart.js** | 4.5.0, vendored (`web/vendor/`, SHA-256 in its README) | The counters' charts on the page. No CDN: a CDN outage on stage is not a risk worth taking. | `web/vendor/chart.umd.js` |
| **Vanilla HTML / CSS / JS** | — | The page: three screens, one `fetch` wrapper over §5b, no framework, no build step. | `web/index.html`, `web/app.js`, `web/cards/` |
| **GitHub Actions** | — | `modal.yml`: `deploy`, `shim`, `endpoint`, `proxy-token` jobs, secrets trimmed and masked, URLs in the job summary. | `.github/workflows/modal.yml` |
| **ffmpeg** | — | Muxes the recorded webm with the voice track into `demo.mp4`. | §5 |

No other runtime dependency. The layer (`staging.py`, `checks.py`, `learning.py`) imports no model client; the test `test_agnostic.py` fails if one appears.

### 5b. The service's HTTP API

One FastAPI app, OpenAPI at `/openapi.json` and `/docs` on the live URL. Every request and response body is a Pydantic model from `pakka/models.py`; state is per team (header `X-Pakka-Team` or `?team=`, default `demo`), and every call runs under one lock.

| Method · path | Body | Returns | What it does |
|---|---|---|---|
| `GET /scenario` | — | `Scenario` | The scenario: seed, tools with JSON-schema arguments, anomalies, reason templates |
| `GET /state` | — | `StateView` | Everything the page renders: runs, writes with flags, systems, scoreboard, learned |
| `POST /reset` | — | `StateView` | Fresh state from the scenario, then Friday 1 replayed and held |
| `POST /run/{friday}` | `RunRequest {auto_approve, supervisor}` | `RunResponse` | Replay one Friday's transcript through the layer; with `auto_approve`, the labelled auto-approve of the montage. 409 if that Friday was already played |
| `POST /decide` | `DecideRequest {run, decisions[], approve_rest, accept_rules[], reject_rules[], accept_promotions[], decided_by}` | `DecideResponse {run, errors, events, learned, scoreboard}` | The person's verdict on a run: approve / edit / discard per write, cascade, send in dependency order, learn. Edit errors come back inline per write. 409 on a second decision for the same run |
| `GET /learned` | — | `Learned` | Envelopes, entities, rules, ladder, memory size, events |
| `POST /rules` | `RuleRequest {tool, field, op, value}` | `Learned` | A typed rule (`gt`, `matches`, …); 422 with the message if it cannot be saved |
| `POST /autopilot/{friday}` | — | `RunResponse` | One Friday with the supervisor absent: released tools pass, everything else is held for a later look; nothing is learned |
| `POST /retry/{friday}` | — | `DecideResponse` | Deliver again the approved writes a connector could not deliver (`delivery_error` on the write). 404 if undecided, 409 if nothing failed |
| `GET /cascade/{friday}/{write_id}` | — | `CascadeResponse` | The writes that would be skipped if this one were discarded |
| `POST /job` | `JobRequest {prompt, agent, connectors[], run?}` | `LiveResponse` (a `RunResponse` plus the `Transcript`) | A typed job through the chosen agent and connectors, every write held. 422 for an unknown agent or connector, or a new prompt on the recorded agent |
| `GET /agents` | — | `[AgentChoice]` | What a job can be routed through: `replay`, `live` (`PAKKA_MODEL`), and `PAKKA_AGENTS` entries, with `available` per key |
| `GET /connectors` | — | `[ConnectorView]` | Per team: `notes`, `webhook`, `email`, `tickets`, `records`, `http`, each with `mode` (`demo` with no setup, `live` once configured), tools, target names and what the settings form asks for |
| `POST /connectors/{name}` | `ConnectorConfigRequest` (the connector's settings fields) | `ConnectorView` | This team's own credentials and targets, validated by the connector, stored per team, never returned; empty returns to demo. 422 with the reason otherwise |
| `POST /live` | `LiveRequest {friday?, prompt, agent, connectors[]}` | `LiveResponse` | The page's *Run live* button: `/job` with the first available live agent |
| `GET /` | — | HTML | `web/index.html` |

### 5c. Documentation map

| Document | What it covers |
|---|---|
| this README | The demo, what is real, how it differs from permissions and observability, the four tools, setup, the mechanisms, the anomalies, the tests, the product |
| [`BUILD_PLAN.md`](BUILD_PLAN.md) | The plan the build followed; §1 the non-negotiables, §3 the blocks and their gates, §5 what was cut for time and what stands in for it, said out loud |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | A paragraph per module; the path of one request; where determinism comes from |
| [`docs/MECHANISMS.md`](docs/MECHANISMS.md) | Staging, grounding, envelope, memory, rules, ladder, with the actual thresholds and the shape classes |
| [`docs/ANOMALIES.md`](docs/ANOMALIES.md) | The seven anomalies: what is in the world, which check catches it, the reason shown, and why each hold is one root |
| [`docs/LOGFIRE_DASHBOARD.md`](docs/LOGFIRE_DASHBOARD.md) | The spans and their attributes; the three panels' SQL as pasted into Logfire; how to read the chart |
| [`docs/JOBS_API.md`](docs/JOBS_API.md) | Free-text jobs: agents, connectors, `POST /job`, retries, and what each board column is |
| [`docs/BOARD_UI.md`](docs/BOARD_UI.md) | The board's build spec: screens, cards, the one-request decide, settings, build order, the demo path |
| [`docs/PRODUCT_PLAN.md`](docs/PRODUCT_PLAN.md) | From the demo to a proxy a team installs: what carries forward, what is rebuilt |
| [`docs/PROTOCOL_NOTES.md`](docs/PROTOCOL_NOTES.md) | Holding writes at an MCP proxy: what the protocol gives, where the proxy sits, the held result, applying later |
| [`docs/scenario.schema.json`](docs/scenario.schema.json) | The JSON schema a second industry's scenario must satisfy (§11) |
| [`pydantic_challenge/SUBMISSION.md`](pydantic_challenge/SUBMISSION.md) | The gateway challenge write-up: setup as it happened, parts A–D, the measured before/after, the echo test, constraints kept |
| [`pydantic_challenge/README.md`](pydantic_challenge/README.md) | How to reproduce its evidence; the metrics recorded; the offline proof of the harness |
| [`pydantic_challenge/guardrail.md`](pydantic_challenge/guardrail.md), [`rule.txt`](pydantic_challenge/rule.txt) | The guardrail spec with its pattern tests; the rule verbatim |
| `pydantic_challenge/results/`, `pydantic_challenge/evidence/` | The two runs' JSON and markdown, `RESULTS.md`, `echo.json`; screenshots of the rules, the guardrails and the traces |
| `web/vendor/README.md` | What is vendored, from where, with its hash and licence |
| `.env.example`, `.github/workflows/modal.yml` | Every key the project reads, with what it is for; the deployment jobs, commented |

## 6. How it works

```
browser  web/app.js
   │  GET /state · POST /reset · POST /run/{friday} · POST /decide · GET /learned · POST /autopilot/{friday} · POST /live · POST /rules
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
- **Model swap.** Friday 1 from the Gemini transcripts and the scripted set → identical held sets and flags.
- **Scenario schema.** `Scenario.model_validate(finance)` passes; `docs/scenario.schema.json` matches; a `matches` rule whose pattern doesn't compile fails at construction.
- **Logfire is write-only.** Nothing in `pakka/` reads from Logfire.
- **The service over HTTP.** Reset holds twelve writes; a bad rule is a 422 with the message; a typed `gt` rule is active in `/learned`; a second decision on a run, or replaying a played Friday, is a 409.
- **Review regressions** (`tests/test_review_fixes.py`). A failed edit is never approved by "approve the rest"; a demotion resets the ladder; a write held only by the ladder is not a catch; the memory check keeps working after one approved repeat.
- **The challenge harness.** Metrics checked against stand-in policies that retry, lie, or report truthfully on purpose; dry-run files are refused as results.

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
