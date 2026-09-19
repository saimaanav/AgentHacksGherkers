# Architecture

One Python package on Modal, one static page in front of it.

```
browser  web/app.js
   │  GET /state · POST /reset · POST /run/{friday} · POST /decide · GET /learned
   │  POST /autopilot/{friday} · GET /cascade/{friday}/{id} · POST /live · POST /rules · GET /scenario
   ▼
Modal app  pakka/app.py  (FastAPI, @modal.asgi_app, min_containers=1)
   ├─ pakka/models.py     Pydantic: ToolSpec, ToolCall, ReadResult, HeldWrite, Flag = Grounding|Envelope|Rule|Memory,
   │                      Decision, Envelope, Rule, LadderState, Scenario, Transcript, RunResult, Scoreboard, State
   ├─ pakka/staging.py    intercept → placeholder → depends_on → held text; apply in topo order, substitute, cascade;
   │                      one logfire span per write and per decision
   ├─ pakka/checks.py     grounding · envelope · memory · rules   (each returns Flag | None)
   ├─ pakka/learning.py   envelope builder (walks model_fields) · ladder · rule derivation from a diff
   ├─ pakka/agent.py      Pydantic AI agent: tools = the scenario's ToolSpecs; model = PAKKA_MODEL
   │                      --generate writes transcripts · --live runs it now · FunctionModel replays / scripts
   ├─ pakka/record.py     logfire.configure + instrument_pydantic_ai, .env loading
   ├─ pakka/sim/          systems.py (in-memory, effects log) · transcripts/<tag>/friday_NN.json (generated)
   │                      scenarios/finance.py   ← the only file allowed to say "invoice"
   ├─ state               modal.Dict("pakka-state"): one State JSON per team key (envelopes, rules, ladder,
   │                      memory, scoreboard, effects, runs); a plain dict when run locally
   └─ record              Logfire: agent spans via instrument_pydantic_ai(); pakka.write / pakka.decision nested
```

## A module each

**`models.py`** is every type that crosses a boundary, and the only file the others all import. Tools are `ToolSpec(name, kind, args_schema)`; the argument model is built from the JSON schema with `pydantic.create_model`, which is the same path an MCP tool takes in the product. Flags are a discriminated union on `kind`. `Rule` compiles its pattern in a validator. `Scenario` is data, so a second industry is a second instance and its JSON schema is exported to `docs/scenario.schema.json`. At the bottom, `shape_of(value)` classifies a scalar as a number, an email address, an account-like identifier, a reference, an id, a placeholder, a short name or free text: this is how the checks key on values without ever reading a field name.

**`staging.py`** is the substrate. `Run` is one pass of the agent through the layer: `read` records what the agent saw, `write` intercepts, assigns the deterministic placeholder, finds dependencies, runs the checks, and either holds the write or, on a released tool with no flags, applies it. `decide` applies a person's approve / edit / discard decisions, cascades discards, sends in topological order with real ids substituted, then hands the judged writes to `learning`. `cascade_preview` is what the review page shows before you confirm a discard.

**`checks.py`** is the four checks. Grounding is history-free and compares the write with the run's reads. Envelope compares it with what has been approved, per tool and per entity. Memory compares it with what was sent and what is held. Rules apply what the person wrote. Each returns at most one flag, and each reason is a template the scenario owns with slots the layer fills.

**`learning.py`** is the product. `build_envelope` walks `model_fields` and dispatches on annotation types; `build_book` runs it per tool and per entity; `propose_promotions` and `accept_promotion` are the ladder; `derive_rules` turns a removed sort code, account number or amount into a proposed rule; `learn_from_run` is the only place the envelope changes, and it only ever sees writes a person judged.

**`agent.py`** is Tom's agent: a Pydantic AI `Agent` whose tools are built from the scenario's `ToolSpec`s and call straight into `staging.Run`. The model is whatever `PAKKA_MODEL` says. The same class runs three models: a real provider for `--generate` and `--live`, a `FunctionModel` that replays a saved transcript for the demo, and a `FunctionModel` that scripts a naive run for tests and for transcripts when no key is present. The transcript is built from `result.all_messages()` and never hand-edited.

**`app.py`** is the FastAPI app inside the `modal.App`. Every request rebuilds the world for that Friday from the scenario and the persisted effects log, runs or decides, and writes the state back. Locally it runs under uvicorn with an in-memory store; on Modal the store is a `modal.Dict`, keyed by team.

**`sim/systems.py`** is the three in-memory systems with an effects log; ids are deterministic from `(seed, run, sequence)` so a replayed run lands the same ids every time. **`sim/scenarios/finance.py`** is the first customer: vendors, invoices, templates and anomalies from one seed, the naive policy, and the reason templates in finance words. It is the only file allowed to use them; a test greps for them everywhere else.

**`web/`** is one page, vanilla JavaScript and hand-written CSS, three buttons and Reset. **`video/record.py`** drives the deployed URL with Playwright at exact timestamps and records the demo. **`tests/`** is §9 of the build plan.

## A request

`POST /run/1` loads the team's `State`, builds Friday 1's world, replays Friday 1's transcript through a Pydantic AI agent whose tools call `Run.read` and `Run.write`, and returns a `RunResult`: every write with its placeholder, dependencies, flags and status, the reads, the proposed rules and promotions, and the counts. `POST /decide` takes `DecideRequest` (decisions, rules to accept, promotions to accept, `approve_rest`), applies it, sends in order, learns, and returns the run again with the effects, inline validation errors keyed by write id, and what was learned. `POST /autopilot/8` is the same as `/run/8` with `supervisor=False`: nothing is decided and nothing is learned. `POST /rules` takes a typed rule ("always hold payments over £10k" is `{tool, field, op: "gt", value: 10000}`), validates it through the `Rule` model (a bad pattern is a 422), and makes it live from the next action. `POST /live` runs the real agent on a fresh state and returns the run like any other; the page shows a *Run live* button only when a model is configured.

## Determinism

One seed drives every invoice, amount and anomaly. Transcripts are generated once and replayed; placeholders and ids derive from `(seed, run, sequence)`; the layer decides live on every replayed call. Reset rewrites the state from the scenario, and the run is identical every time.
