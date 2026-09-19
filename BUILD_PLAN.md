# BUILD_PLAN.md — pakka, hackathon build

Working name: `pakka` (one constant, renameable).

## Read this first

You are building a hackathon submission in about six hours: 4½ to build, 1 for the video, ½ for the README. The demo is sixty seconds and three clicks (§1). The submission is a 2-minute video and a public repo (§8). **Modal, Pydantic, Pydantic AI and Logfire are required partner tech** and each is load-bearing (§2). Work the hour plan in §3 in order; every block has a gate and a named cut. When two sections disagree, §1 wins. Domain words — invoice, vendor, payout, remittance, ledger — are allowed in exactly one file, `pakka/sim/scenarios/finance.py`; a test greps for them everywhere else.

**What this is.** A staging layer between an agent and the real systems it writes to. Every write is held; the agent gets a provisional result and finishes its task; a person reviews everything once, as one diff; the layer learns from those reviews — what's normal, what gets corrected — until most writes go through without anyone looking and only the strange ones stop. Staging is the substrate; learning is the product. Finance operations is the first customer; the layer knows nothing about finance.

**The one-liner.** Pull requests for agent actions — with checks that learn from your reviews until most of them merge on their own.

**The pitch in one axis.** Permissions stop an agent before every action and wait for you. Observability lets it act and shows you afterwards. Neither lets the agent finish and shows you what it wanted to do. This does — and it sends every decision to Logfire, so you keep the record.

**Borrowed framing, one sentence each.** DeepMind's AI Safety Gridworlds separates the reward an agent optimises from a hidden function that measures what you actually wanted; the agent's screen says "paid four vendors", the world says zero, and everything after that is the second function — which Tom writes by reviewing. The Agentic Trust Framework says agents earn autonomy, they don't get it by default; the ladder here is that, per tool. Both are for Q&A, not the sixty seconds.

The 30-hour product plan and the MCP research are at `docs/PRODUCT_PLAN.md` and `docs/PROTOCOL_NOTES.md`. Nothing in them is in scope today.

---

## 0. Rules

1. §1 is the spec. When §1 and anything else disagree, §1 wins.
2. Follow §3. Miss a gate, take the named cut, keep moving.
3. **One Python package on Modal, one static page in front of it.** `pakka/` with FastAPI on Modal, Pydantic v2 for every model that crosses a boundary, Pydantic AI for the agent, Logfire for the record. Front end: `web/index.html` + `web/app.js`, vanilla, Tailwind from a CDN, served by the same Modal app. No other framework, no bundler.
4. **Deterministic by construction.** One `random.Random(SEED)` in the scenario drives every invoice, amount and anomaly. The agent's runs are generated once with a real model and replayed from transcripts, so the demo and the Playwright recording play identically every time.
5. **Domain words live in one file.** `pakka/sim/scenarios/finance.py` is the only place "invoice", "vendor", "payout", "remittance" or "ledger" may appear. `pakka/models.py`, `checks.py`, `learning.py`, `staging.py` key on types and on what the person did — never on names.
6. **No model calls in the layer.** `staging.py`, `checks.py` and `learning.py` are counts, ranges, set membership and pattern matching. The only model in the repo is Tom's agent, and it can be any model.
7. **Logfire is written to, never read from.** No check consults it. It records every decision, both ways.
8. If it isn't on screen in §1 or required by §8, don't build it.

---

## 1. The demo

**Sixty seconds. Three clicks. One sentence per screen.** Friday 1 has already run when the page opens; the montage runs at 8×; autopilot runs ten Fridays in 25 seconds. Nothing waits on an animation. Everything not in the sixty seconds is built for Q&A (§1.1).

One browser window, full screen, dark. Three buttons — **Review · Play 5 Fridays · Autopilot** — and Reset.

| Time | On screen | Click | Say |
|---|---|---|---|
| 0:00 | End of Friday 1, frozen: the agent's last line *"Paid 4 vendors, £9,415.50"*; the world at **0** | — | *"Tom's agent just ran his Friday payment run. It says it paid four vendors. It paid nobody — every write is held."* |
| 0:06 | Review: four vendor cards, one flagged — *the pay-to account on Halden's invoice isn't the account on file, and the agent read both*; the rule card already open on Ashcombe's email | **Discard**, **Yes always**, **Approve** | *"This one's an approved invoice with a new bank account on it — the layer saw the account on file in the same run. He discards it, and the entry and email that depended on it go with it. He pulls bank details out of an email, and that becomes a rule. Approve."* |
| 0:20 | Montage, 8×: five Fridays flick past; **What it has learned** fills — vendors, usual amounts, the rule, promotions firing | **Play 5 Fridays** | *"Five more Fridays. It learned his vendors, his amounts, his order, and what he corrects — from him, not from a model."* |
| 0:32 | Autopilot: feed streaming green; counters climbing; four amber holds land while you talk | **Autopilot** | *"Now it runs alone. That one's a vendor he's never paid. That one's three times what Farrow usually bills. That one's a changed bank account — that's what invoice fraud looks like. That one has a sort code in it because someone changed the template — his rule caught it. Caught four, wrongly held none."* |
| 0:55 | Counters: 10 Fridays · ~100 actions · 96 through · 4 held · £80k moved · **caught 4/4, wrongly held 0**. Footer: *ledgers · payment rails · CRMs · email · databases · deploys · tickets* | — | *"Four held out of a hundred, and they're the right four. Nothing in here knows what an invoice is — it's the same layer for any agent that writes to a ledger, a payment rail, a CRM, an inbox, a database or a deploy pipeline. Finance is just where we start."* |

The three screens are one simulation at different speeds: Friday 1 replays instantly on load and stops at its end state; the montage replays five Fridays with a labelled auto-approve; autopilot replays ten more with the supervisor absent. The agent's calls come from transcripts a real Pydantic AI agent produced; the layer's decisions — hold, flag, cascade, envelope, rule, promotion — are computed live on each replayed call.

### 1.1 Built for Q&A, not shown

- **Details** on any vendor card: the underlying calls, placeholder ids, the dependency chain, the email body.
- **Discard cascade preview** — the entry and email that go with a discarded payout, shown before confirming.
- **Live agent** — a `--live` button runs the real agent on the next Friday, for anyone who asks whether the transcripts are real.
- **All six anomaly types** in the scenario; the sixty seconds show four. Press Play again for the other two: an invoice paid twice, and a payout whose amount matches no invoice the agent read.
- **The absent-supervisor test** (§4): same Friday, Tom present vs absent, identical held set.
- **The model-swap table** (§2.2): same Friday under two providers, identical holds.
- **Friday 1's Logfire trace**: the agent's tool-call spans with Pakka's hold decisions nested under them.
- **"Always hold payments over £10k"** — typed as a rule in ten seconds, if a finance judge asks for a hard floor.

### 1.2 The anomalies

Each is a small environment in the gridworlds sense — one way the agent's "done" and Tom's "correct" come apart. With a real agent they are all *in the environment*: things a naive agent does when told to pay approved invoices, not typos we script.

| Anomaly (what's in the world) | Caught by | Reason shown | Analogue |
|---|---|---|---|
| Approved invoice whose pay-to account isn't the one on file for that vendor — **Friday 1** | grounding (write's destination vs the on-file account the agent read this run) | *"Account on this invoice isn't the one on file for Halden — the agent read both"* | Robustness to adversaries: invoice-redirection fraud is another agent editing the environment. History-free |
| First payment to a vendor never paid before | envelope | *"Never paid Orrin Freight before"* | Distributional shift: the world moved; hold, don't generalise |
| Amount far above a vendor's usual range | envelope | *"2.7× the most you've paid Farrow"* | Distributional shift |
| Vendor's account changed since the last payment | envelope (account set per vendor) | *"Halden's account changed on Friday 10; first payment to it"* | Adversaries again — the history-based twin of Friday 1 |
| Remittance template changed to include bank details, so the agent includes them | Tom's rule | *"contains a sort code (your rule, Friday 1)"* | Side effects: a consequence outside the task |
| The same invoice appears twice in the approved list | memory | *"INV-20433 was paid on Friday 3"* | Safe interruptibility: pressing the button again does nothing |

Autopilot as a whole is the paper's **absent supervisor** environment: Tom has left the room, and the layer's checks run the same whether he's there or not. The scoreboard — **caught N of N · wrongly held 0** — is the performance function, measured. Autonomy never widens the envelope; only Tom's approvals do.

**Wording rule for the whole submission:** never say holds went "to nothing" or the layer "got out of the way". The layer checks 100% of actions on Friday 20 exactly as on Friday 1; what falls is how often it has to *interrupt a person*. Say "checked every action, interrupted him four times in a hundred." The falling line is trust earned, not vigilance lost — and every spike on it is a catch.

### What must be true at H+4:30

- [ ] Page opens on the end of Friday 1 with no visible loading; Review shows the flag and the rule card without extra clicks
- [ ] Discard → Yes always → Approve is three clicks; the world fills in dependency order with real ids where placeholders were
- [ ] Play 5 Fridays runs in ≤ 12s and the learning panel fills live; promotions fire on the thresholds
- [ ] Autopilot runs ten Fridays in ≤ 25s unattended; exactly four anomalies land, of four different types, at roughly 0:36, 0:41, 0:46, 0:51; counters agree with the feed; scoreboard reads 4 of 4 and 0
- [ ] The whole thing, spoken, comes in under 60s in three consecutive dry runs
- [ ] Reset returns to the opening state and the run is identical every time
- [ ] The deployed Modal URL works from a phone
- [ ] The agnostic grep test passes
- [ ] The honesty line — what's real, what's simulated — is on the first slide and the last

---

## 2. Stack

| Layer | Choice | Why it's load-bearing |
|---|---|---|
| Runtime | **Modal** — one `modal.App`, FastAPI via `@modal.asgi_app()`, state in a `modal.Dict`, secrets for the model key and the Logfire token | The layer *is* a service between the agent and its systems, with a public URL judges can open. Each Friday is a function call; autopilot is fourteen. `min_containers=1` on the web function so the demo never cold-starts |
| Types | **Pydantic v2** — every model that crosses a boundary | Tool arguments are models, so edit-with-validation on the review page is `model_validate` with the `ValidationError` rendered inline. The envelope builder walks `model_fields` and keys on annotation types — numeric → range, low-cardinality `str` → allowed set, email-like `str` → domain set — which is *how the layer stays agnostic*. Flags are a discriminated union on `kind`. The scenario is a model, so a second industry is a second instance |
| The agent | **Pydantic AI** — Tom's AP agent; the model is the `PAKKA_MODEL` string | A real tool-calling agent satisfies "build an agent". Its tools are the same models the layer validates. Any provider by changing one string; `FunctionModel` gives transcript replay and the deterministic test agent through the same class, so there is no separate simulated agent |
| Record | **Pydantic Logfire** — `instrument_pydantic_ai()` on the agent; one span per decision in `staging.py` | Every decision the layer makes — held, passed, flagged, approved, discarded, edited, promoted, demoted, rule accepted — is a span nested under the agent's own tool-call trace. What was *stopped* is on the record with why. Written to, never read from |
| API | FastAPI inside the Modal app | Pydantic models are the request and response types; `/openapi.json` is part of the jury docs |
| Front end | `web/index.html` + `web/app.js`, vanilla, Tailwind CDN, served as static files by the same app | One URL. Dark, big type — it's projected |
| Video | **Playwright** (Python) drives the three clicks against the deployed URL with exact waits and records `.webm`; voiceover mixed with ffmpeg | The demo timings become code, so the recording is reproducible and matches the live run to the frame |
| Tests | pytest | §9 |

Python 3.12. Dependencies: `modal`, `fastapi`, `pydantic>=2`, `pydantic-ai`, `logfire`; dev: `playwright`, `pytest`. Nothing else. Check Pydantic AI's current docs for the model-string format and `FunctionModel` before writing the loop — the shape in §2.2 is right, the spelling may have moved.

### 2.1 Where everything sits

```
browser  web/app.js
   │  GET /scenario · POST /run/{friday} · POST /decide · GET /learned · POST /autopilot/{friday} · POST /reset · POST /live
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

Pydantic, concretely:

- `ToolSpec(name, args_model: type[BaseModel], kind: Literal["read","write"])` — the simulated systems register tools with argument models; MCP tools in the product register JSON Schema and we build the model with `pydantic.create_model`, same code path.
- `HeldWrite(id, tool, args: dict, placeholder, depends_on: list[str], flags: list[Flag], status)` with `Flag = Annotated[Union[GroundingFlag, EnvelopeFlag, RuleFlag, MemoryFlag], Field(discriminator="kind")]`.
- `Rule(tool, field, op: Literal["matches","in","not_in","gt","lt"], value)` with a `field_validator` that compiles `matches` patterns at construction — a bad rule can't be saved.
- `Envelope` is built by `learning.build_envelope(approved: list[HeldWrite], model: type[BaseModel])`, which iterates `model.model_fields.items()` and dispatches on `field.annotation`. It never sees a field name. Twelve lines; quoted in full in the README.
- `Scenario(seed, tools, generator, anomalies, task)` — `Scenario.model_json_schema()` is exported to `docs/scenario.schema.json`.
- `Transcript(friday, model, calls: list[ToolCall])` — what the agent did, in order, never hand-edited.

Modal, concretely:

- `app = modal.App("pakka")`; `image = modal.Image.debian_slim(python_version="3.12").pip_install("fastapi", "pydantic>=2", "pydantic-ai", "logfire")`.
- `@app.function(image=image, min_containers=1, secrets=[modal.Secret.from_name("pakka")]) @modal.asgi_app() def web(): return fastapi_app`.
- `state = modal.Dict.from_name("pakka-state", create_if_missing=True)`; `POST /reset` rewrites it from the scenario.
- `generate_transcripts = app.function(...)` — runs the real agent once per Friday; `modal run pakka/agent.py --generate`.
- `modal serve pakka/app.py` for the live slot (local terminal, hot reload); `modal deploy` for the URL in the README and the video.

Logfire, concretely:

```python
with logfire.span("pakka.write", tool=call.tool, run=run.id, placeholder=hw.placeholder) as span:
    flags = checks.run_all(call, run, state)
    decision = "held" if flags or not state.released(call.tool) else "passed"
    span.set_attributes(flags=[f.model_dump() for f in flags], decision=decision)
```

Plus `logfire.instrument_pydantic_ai()` once at startup, and a `pakka.decision` span for every approve, discard, edit, promotion, demotion and accepted rule with `decided_by`. Because arguments and flags are Pydantic models, `model_dump()` gives Logfire structured fields — "every held write with an envelope flag this month" is a SQL query.

### 2.1a Next to the things judges already know

Three approaches to letting an agent write to real systems, on one axis — when the action lands and when a person looks:

| | Claude Code permissions | **Pakka** | Logfire / observability |
|---|---|---|---|
| The agent | Stops at each write and waits | **Finishes the whole task** on provisional results | Finishes; the writes really happen |
| The action | Lands after you answer, one at a time | Lands after review, in dependency order — or never | Already landed |
| You look | Before each action; present throughout | Once, at the end, at everything — then less as it learns | After |
| A bad payout | You said no to that one call, if you were there | Held; never sent | Visible in the trace; the money is gone |
| Scope | One agent, one terminal, one session | Any agent's writes, across systems, per team, persistent | Any agent, any span, read-only |

Permissions interrupt. Observability watches. Pakka lets the agent finish and shows you what it wanted to do — and reports every decision to Logfire. The precise sentence: *the agent completes the task; the actions don't happen until someone approves — or until the layer has learned it doesn't need to ask.*

### 2.1b The GitHub metaphor, end to end

The one-liner is "pull requests for agent actions". Every part of the build has a GitHub counterpart, and Logfire is the last one — so the metaphor holds from the first write to the graphs.

| GitHub | Pakka |
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
| **Insights tab** — commit graph, merge rate, checks over time | **The Logfire dashboard**: checked vs held per Friday (checked flat at 100%; held falling as trust is earned, spiking at each catch), approved / discarded / edited, holds by reason. The commit graph for an agent earning its autonomy — the checks never stop, the interruptions do |

Two honest gaps: we hold at the proxy rather than creating drafts or branches inside each target system (same guarantee, simpler mechanism, and it's what keeps the layer agnostic — native adapters are in the product plan), and the demo has one run at a time where the product has sessions.

### 2.2 Any model a team wants

The layer never sees the model. Its input is `create_payout(vendor, amount, destination)`, not a prompt or a provider; anything that calls tools through it is covered. *"We don't integrate with models. We integrate with the one thing every agent does, which is call a tool."*

Tom's agent is made agnostic on purpose:

```python
agent = Agent(
    model=os.environ["PAKKA_MODEL"],       # "anthropic:…", "openai:…", "groq:…", or an OpenAI-compatible base URL (Ollama, vLLM, OpenRouter)
    system_prompt=scenario.task,
    tools=[t.as_tool() for t in scenario.tools],
)
```

- **One agent class, three models.** A real provider for `--generate` and `--live`; a `FunctionModel` that replays a saved transcript for the demo; a `FunctionModel` that scripts a naive run for tests.
- **Local models are a feature for the wedge.** A finance team that can't send invoices to a cloud API points `PAKKA_MODEL` at Ollama. The layer's checks are counts and ranges; they work as well behind a small local model as a frontier one.
- **The model-swap test.** Friday 1 replayed from transcripts generated by two providers → identical held sets. Three-row table in the README.

**Transcripts.** `modal run pakka/agent.py --generate --fridays 20` runs the real agent once per Friday and writes `pakka/sim/transcripts/*.json`. The demo replays them at script speed; the layer decides live on each call. Transcripts are never hand-edited; if a generation doesn't tell the story, regenerate and say in the README that the set was selected. The anomalies are environmental (§1.2), so a naive agent produces the story on almost any generation.

---

## 3. Hour plan

**0:00–0:30 — Models, scenario, skeleton on Modal.** `models.py`; `scenarios/finance.py` as a validated `Scenario`; `app.py` with `/scenario` and static serving; `modal serve` running.
**GATE:** the front end loads from the Modal URL and `/scenario` validates. *Miss → uvicorn locally, deploy at 3:45; code is identical.*

**0:30–1:15 — Agent, systems, staging.** `agent.py` with the Pydantic AI agent and a `FunctionModel` naive agent (read → pay ×N → post ×N → email ×N); in-memory systems with an effects log; staging intercept, placeholders, `depends_on`, held text; `POST /run/1` returns a `RunResult`. Front end renders Friday 1's **end state on load**. **Then kick off `--generate` for 20 Fridays on Modal in the background** — it takes minutes and the naive agent stands in until it lands.
**GATE:** opening screen shows "Paid 4 vendors" beside a world at 0. *Miss → drop the agent narration pane.*

**1:15–2:15 — Review and apply.** `POST /decide`; grounding (destination vs on-file account, amount vs invoices read); vendor cards, attention/normal split; discard with cascade preview; rule derivation from the pre-applied email edit, card **already open** on arrival; edit validation via `model_validate`, errors inline; approve → topo order, substitution, effects.
**GATE:** Review → Discard → Yes always → Approve in three clicks against the Modal URL. *Miss → rule ships pre-seeded, introduced verbally.*

**2:15–3:00 — Learning and montage.** `build_envelope` walking `model_fields`; per-tool ladder; promotion at ≥ 15 approved across ≥ 5 runs, ≤ 10% discarded or edited; `/learned`; montage = five replayed Fridays with a labelled auto-approve. Swap in the real transcripts when `--generate` finishes.
**GATE:** Play 5 Fridays in ≤ 12s. *Miss → lower thresholds so promotion fires by Friday 4; never fake the counts.*

**3:00–3:45 — Autopilot.** `POST /autopilot/{friday}` with the supervisor flag off; anomaly schedule from the scenario (**four in the first ten Fridays**: new vendor, amount above range, account changed, template with bank details); scoreboard; feed, counters, held list. Envelope frozen.
**GATE:** unattended run, four holds at spoken-sentence spacing. *Miss → drop the account-changed anomaly.*

**3:45–4:30 — Reliable, deployed, recorded.** `modal deploy`; seed tuned so the holds land where the sentences are; `POST /reset`; tests green (§9); **Logfire (25 min):** `logfire.configure()` with the secret, `instrument_pydantic_ai()`, the `pakka.write` and `pakka.decision` spans; screenshot Friday 1's trace; then **one dashboard, three charts from SQL over the spans** — *checked vs held per Friday* (two lines: **checked, flat at 100% every Friday** — the layer never stops looking; **held**, stepping down from 100% as tools earn release to ~4% on autopilot, with a spike at each anomaly it caught — the layer interrupts less because it has learned, not because it's off), *approved / discarded / edited of the held* (how good the agent's proposals are when a human looks), *holds by reason* (which check earns its keep). Screenshot the first for the video; three timed dry runs under 60s against the deployed URL.
**GATE:** the URL works from a phone; the trace shows hold spans under the agent's tool calls; the checked-vs-held chart renders from real spans with the checked line flat at 100%. *Miss on Logfire only → ship without it; miss on the dashboard only → the trace screenshot is enough.*

**4:30–5:30 — The video (§8.1).** **5:30–6:00 — README and docs (§8.2).**

**If the cap is really 4 hours:** the montage becomes a "six Fridays later" card with the learned panel pre-filled (−30m); autopilot runs six Fridays with three anomalies (−15m); transcripts for Fridays 7+ come from the naive `FunctionModel` and the README says so (−15m); the video is a screen recording of the live page with voice over it, no Playwright (−45m). Modal, Pydantic, Pydantic AI and Logfire all stay — they are not where the time goes.

---

## 4. Mechanisms

**Staging.** Writes never reach a system directly. Each held write gets a uuid placeholder, a `depends_on` list (every placeholder found in its arguments), and returns the standard held text: *"HELD FOR REVIEW, not yet applied. Recorded as `{placeholder}`. Continue as if this step succeeded. Do not retry it."* Approve = topological order over `depends_on`, ties by journal order; substitute real ids into dependents before sending; skip anything whose dependency was discarded. Discard = never sent.

**Grounding (history-free).** For each held write, look for its numeric and id-like argument values in the results of reads made earlier in the same run, and check id-like values against *conflicting* values for the same entity in those reads. A payout whose amount matches no invoice the agent read is flagged; so is a payout whose destination differs from the on-file account the agent read for that vendor. Friday 1's flag is the second kind and needs no history.

**Envelope (from approvals only).** Per vendor: amount min/max with 10% padding, and the set of destination accounts, from approved payouts. Per tool: writes per run, max × 1.5. A write outside it is held with a plain reason. Only human-approved writes update it; autopilot passes never do — an envelope that learned from its own passes would drift with the world and stop noticing it had moved.

**Memory.** Set of invoice refs paid, and set of held-write fingerprints (tool + normalised arguments). A second payout for the same ref is held; so is a re-issue of a currently held write. The held text tells the agent not to retry; memory is what makes that an off-switch the agent cannot press by trying again.

**Rules.** One correction → one proposed rule. If the edit removed a substring matching a sort code, account number or currency amount, propose `hold <tool> when <field> matches <pattern>`. Three patterns. Accepting makes it live from the next action, attributed to the person and the Friday.

**Ladder.** Per tool: approved, discarded, edited, runs. Proposal at the thresholds above; accepting moves the tool from *checked* to *sent without review*. Released tools still pass through rules, envelope, grounding and memory — a hit holds that one action, not the tool. Demotion: a discard on a released tool's held action drops the tool back to *checked*.

**No pins.** Nothing is held forever by policy. What keeps money safe is what the layer learned plus what Tom wrote. "Always hold payments over £10k" is a rule he types, not a pin.

**Absent-supervisor assertion.** The same checks run in the montage (Tom reviewing) and autopilot (nobody). Test: replay Friday 8 under both modes; the held sets are identical.

---

## 5. What's real and what's simulated

Say this on the first slide.

| Real, running live | Simulated |
|---|---|
| The layer: a Modal service with a public URL; every call in the demo is a request to it | The three systems — ledger, payment rail, mail — in-memory with an effects log |
| Staging, placeholders, dependency ordering, substitution, cascade | The invoices, vendors and anomalies, from a fixed seed |
| Edit validation against the tool's Pydantic model | Tom's approvals on Fridays 2–6, labelled on screen |
| Grounding, envelope, memory, rules — every flag | Wall-clock: the agent's runs were generated once by the real agent and are replayed at demo speed |
| Promotion thresholds and the ladder | |
| The agent: a real Pydantic AI tool-calling agent; `--live` runs it now | |
| Every decision as a Logfire span | |

**Cut for time in the build (recorded here, never silently):**

| Planned | Shipped instead | Reason |
|---|---|---|
| Transcripts generated by a frontier model via `--generate` | Done later in the build: `pakka/sim/transcripts/real/` from Gemini 3.6 Flash; the scripted set stays for tests | — |
| Tailwind from a CDN | Hand-written CSS in `web/index.html` | No CDN dependency on stage; the build sandbox could not reach the CDN to test |
| Logfire trace screenshot and the checked-vs-held dashboard in the video | `video/record.py` shows a captioned placeholder frame until `video/assets/logfire-trace.png` and `logfire-chart.png` exist (no `video/assets/` in the repo yet) | No `LOGFIRE_TOKEN` in the build environment; the spans are emitted |
| `modal deploy` and the public URL | Local uvicorn, identical code; Modal constructs import-clean | No Modal token in the build environment |
| The literal §9 grep over all of `pakka/` | The same grep excluding `pakka/sim/transcripts/**` | Generated transcripts record the agent's calls to the scenario's tools (`create_payout(vendor=…)`); every `.py` file is clean |

### 5.1 From demo to product

**Wedge: finance operations first, agnostic underneath.** AP, AR and treasury teams have a review habit, a budget line and the clearest stakes per action. Tom is the buyer's colleague. The layer knows nothing about finance and the build enforces it (§0 rule 5).

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

**Form: self-hosted proxy the team installs.** One binary in front of the team's MCP servers, review UI included; the agent points at the proxy and never knows it's there. `docs/PRODUCT_PLAN.md` has that build. The demo's screens carry forward; Modal is the demo host, not the product's.

**Learning: per team, and it never leaves.** Envelopes, rules, workflow shape and memory are the team's — stored beside the proxy, exportable, deletable. No pooling, no shipped priors. The moat is the review habit and the months of "normal" that would have to be re-earned anywhere else.

**Record: the proxy emits OpenTelemetry; Logfire is the default sink.** Every decision — both ways — is a span with who and why, nested under the agent's own trace when it's instrumented. A team that keeps telemetry on-premises points the same exporter at their own collector. SQLite stays the source of truth; the gate never depends on Logfire being reachable.

**Carries forward unchanged:** the models, grounding, the envelope builder and its freeze rule, rule derivation, the ladder, the anomaly catchers, the scoreboard, the `Scenario` format, the Logfire spans. **Rebuilt:** the transport (MCP proxy), the systems (real), persistence, auth. **First after the hackathon:** a second scenario — a deploy pipeline — because building it is how you find finance assumptions that leaked out of the scenario module.

---

## 6. Optional, only if the 3:45 gate was met early

- **Discard from the autopilot queue** demotes the tool on screen. Ten minutes; the answer to "what if it gets one wrong?"
- **Checks strip** under the review header, like a PR's checks: `Grounding ✓ 11 of 12 · Envelope — no history yet · Rules ✓ · Memory ✓`. Twenty minutes; makes the pre-read legible as a system.
- Not borrowed from the gridworlds paper, on purpose: the RL algorithms and rendering; *self-modification*; *safe exploration*. Keep the analogy to the table and the absent-supervisor line.

---

## 7. What to say

One sentence per screen. Everything else is the screen.

0. *(over the comparison card, video and live only)* "Permissions stop an agent before every action and wait for you. Observability lets it act and shows you afterwards. Neither lets the agent finish and shows you what it wanted to do. This does."
1. "Tom's agent just ran his Friday payment run. It says it paid four vendors. It paid nobody — every write is held."
2. "This one's an approved invoice with a new bank account on it — the layer saw the account on file in the same run. He discards it, and the entry and email that depended on it go with it. He pulls bank details out of an email, and that becomes a rule."
3. "Five more Fridays. It learned his vendors, his amounts, his order, and what he corrects — from him, not from a model."
4. "Now it runs alone. That one's a vendor he's never paid. That one's three times what Farrow usually bills. That one's a changed bank account — that's what invoice fraud looks like. That one has a sort code in it because someone changed the template — his rule caught it. Caught four, wrongly held none."
5. "Four held out of a hundred, and they're the right four. Nothing in here knows what an invoice is — it's the same layer for any agent that writes to a ledger, a payment rail, a CRM, an inbox, a database or a deploy pipeline. Finance is just where we start."

Held back for Q&A: the gridworlds line; the ATF line; *"Logfire tells you what the agent did. We decide whether it gets to. We tell Logfire — so you get the PR timeline and the Insights tab for an agent."*; *"We don't integrate with models. We integrate with the one thing every agent does, which is call a tool."*

---

## 8. The submission

A 2-minute video and a public repo. Judged on creativity and technical complexity, bonus for partner tech; five teams go to a 5-minute live slot.

### 8.1 The video — 2:00, Playwright-recorded, your voice over it

**The recording is code.** `video/record.py` drives the deployed URL, navigates the three static cards in `web/cards/`, clicks the three buttons at exact timestamps, and writes `demo.webm`. Every take is identical, so a separately recorded voiceover lines up.

| Time | On screen | Voice |
|---|---|---|
| 0:00–0:14 | Comparison card (three timelines), then the opening screen | Sentence 0, then sentence 1 |
| 0:14–0:30 | Review → Discard → Yes always → Approve → world fills | Sentence 2, plus *"Approve — and it lands, in order, with real ids where the placeholders were."* |
| 0:30–0:45 | Montage, learned panel fills | Sentence 3, plus *"There's no model in this loop — counts, ranges and a pattern he wrote."* |
| 0:45–1:12 | Autopilot, four holds | Sentence 4, plus *"Ninety-six actions went through without anyone looking, and the four that stopped are the four that should have."* |
| 1:12–1:37 | Architecture card → **Friday 1's Logfire trace** → **the checked-vs-held chart across twenty Fridays** | *"Tom's agent is Pydantic AI — swap the model with one string. The layer is a Modal service. Every tool's arguments are a Pydantic model, so editing a held write is validated against the tool's own schema, and the envelope builder walks the model's fields and keys on types — it never reads a field name. That's why nothing in the checks knows what an invoice is. Every decision is a span in Logfire, under the agent's own trace — and this is those spans as a chart. The flat line is every action checked, every Friday. The falling line is how often it had to interrupt Tom: all of them on day one, four in a hundred by Friday twenty — and each spike is something it caught."* |
| 1:37–1:50 | Real vs simulated table | *"What's real: the agent, the layer, the checks, the learning, the record — live on Modal. What's simulated: the three systems and the invoices, from a fixed seed, and the clock — the agent's runs were recorded once and replayed. The product wires the same code behind a real MCP proxy; the plan's in the repo."* |
| 1:50–2:00 | Closing card: the seven tool classes, repo URL | Sentence 5 |

Production: `page.set_viewport_size(1440, 900)`, `record_video_dir`, `wait_for_selector` on the opening screen, clicks at 14.0s / 30.0s / 45.0s, hold the last frame 3s. Voice in one take against the finished video with a timer visible. `ffmpeg -i video/out/demo.webm -i voice.m4a -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest demo.mp4`. Two takes of voice, pick the calmer one; speak slower than feels natural.

### 8.2 The repo

Public GitHub, MIT.

```
README.md
docs/ARCHITECTURE.md        §2.1 + a paragraph per module
docs/MECHANISMS.md          §4
docs/ANOMALIES.md           §1.2
docs/scenario.schema.json   generated
docs/PRODUCT_PLAN.md · docs/PROTOCOL_NOTES.md
pakka/  app.py models.py staging.py checks.py learning.py agent.py sim/{systems.py, transcripts/, scenarios/finance.py}
web/    index.html app.js cards/
video/  record.py
tests/
pyproject.toml
```

**README.md** — the jury reads this first; it is judged on "comprehensive", so it is long and it is honest.

1. **One paragraph and the video.** The one-liner, Tom in two sentences, the video embed, the deployed URL.
2. **The 60-second demo as a table** — §1's table.
3. **What's real and what's simulated** — §5, unedited.
4. **How this differs from permissions and from observability** — §2.1a, unedited.
4a. **The GitHub metaphor, end to end** — §2.1b's table, unedited, including the two honest gaps.
5. **How we used Modal, Pydantic, Pydantic AI and Logfire** — its own top-level heading, near the top, one subsection each, each answering *what it does here, which primitives, what would break without it*:
   - **Modal** — the `modal.App`, `@modal.asgi_app()`, `modal.Dict`, one function call per Friday, `min_containers=1`, secrets, `modal serve` vs `modal deploy`, the URL.
   - **Pydantic v2** — the boundary models (listed), `model_validate` on edit, the discriminated `Flag` union, `build_envelope` quoted in full, `scenario.schema.json`, the agnostic grep test.
   - **Pydantic AI** — the agent, tools as the same models, `PAKKA_MODEL`, `FunctionModel` for replay and tests, `--generate` / `--live`, the model-swap table, pointing it at Ollama.
   - **Logfire** — frame it as *GitHub's PR timeline and Insights tab, for an agent*. `instrument_pydantic_ai()`; the `pakka.write` and `pakka.decision` spans and what they carry, nested under the agent's trace so one trace is one PR's timeline — what the agent tried, what the layer decided, who approved; **every decision recorded, both ways — what was stopped is on the record with why**; the Friday 1 trace screenshot; the dashboard as the Insights tab — checked vs held per Friday (checked flat at 100%, held falling as trust is earned and spiking at each catch: the layer interrupts less because it learned, never because it's off), approved / discarded / edited, holds by reason — with its SQL; SQLite as source of truth, Logfire written to and never read from.
6. **Setup.** `pip install -e .`, `modal setup`, `modal secret create pakka PAKKA_MODEL=… ANTHROPIC_API_KEY=… LOGFIRE_TOKEN=…`, `modal serve pakka/app.py`, `modal deploy pakka/app.py`, `modal run pakka/agent.py --generate`, `pytest`, `python video/record.py --url …`. Every command tested from a fresh clone.
7. **How it works** — the diagram and a paragraph per module.
8. **The mechanisms** — §4.
9. **The anomalies** — §1.2 and the absent-supervisor test.
10. **Tests** — §9.
11. **From demo to product** — §5.1.
12. **Add a second industry** — writing a `Scenario`; the schema; the grep rule.
13. **References** — the gridworlds paper, the Agentic Trust Framework, MCP.

### 8.3 The live 5 minutes, if selected

0:00–0:30 the comparison card and Tom. 0:30–1:30 the sixty seconds, live, against `modal serve` on your laptop. 1:30–2:30 how it works, ending on Friday 1's Logfire trace and `build_envelope` on screen. 2:30–3:00 real vs simulated and the product. 3:00–5:00 questions — §1.1. Deployed URL on the closing card so judges open it on their phones.

---

## 9. Tests

- **Golden run.** Friday 1: twelve held writes, zero effects; Halden's payout carries a `GroundingFlag` (destination ≠ on-file account); after Discard + Approve the effects log has exactly nine entries in dependency order with real ids substituted; Halden's entry and email are `skipped`.
- **Placeholder leak.** No placeholder string ever appears in any effects log across twenty Fridays; fuzz substitution over placeholders embedded in longer strings.
- **Absent supervisor.** Friday 8 with `supervisor=True` and `False` → identical held sets.
- **Learning.** After Fridays 1–6 the ladder proposes release for the email tool first; the pre-applied edit derives exactly one `Rule`; that rule holds a matching send on the next call; `build_envelope` on a model with fields named `a`, `b`, `c` (an `int`, a low-cardinality `str`, an email-like `str`) produces a range, a set and a domain set.
- **Agnostic grep.** `rg -i 'invoice|vendor|payout|remittance|ledger' pakka/ --glob '!pakka/sim/scenarios/*'` returns nothing.
- **Model swap.** Friday 1 from transcripts generated by two providers → identical held sets and flags.
- **Scenario schema.** `Scenario.model_validate(finance)` passes; a `matches` rule whose pattern doesn't compile fails at construction.
- **Logfire is write-only.** Nothing in `pakka/` imports from Logfire except to emit; a grep for `logfire.query` or reads returns nothing.

---

## 10. CLAUDE.md starter

```
# pakka — project rules
- Read BUILD_PLAN.md "Read this first", §1 and §3 before any task. §1 wins conflicts. Work §3 in order; take the named cut at a missed gate.
- Stack is fixed: Modal + FastAPI, Pydantic v2, Pydantic AI, Logfire, vanilla web/. No other dependency.
- Domain words (invoice, vendor, payout, remittance, ledger) only in pakka/sim/scenarios/finance.py. The grep test enforces it.
- No model calls in staging.py, checks.py, learning.py. Logfire is written to, never read from.
- Every type that crosses a boundary is a Pydantic model. Flags are a discriminated union on `kind`.
- Only human-approved writes update an envelope. Never send a write that still contains a placeholder. Discard cascades to dependents.
- Transcripts are generated by the agent and never hand-edited. Determinism comes from the scenario seed and replay.
- Check Pydantic AI and Logfire current docs before writing the agent loop or instrumentation; don't rely on memory.
- Provisional results are text only. Never invent field values.
- Anything cut for time goes in BUILD_PLAN.md §5 "simulated" column. Never silently.
```
