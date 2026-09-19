# Jobs: free text, a chosen agent, connectors, one layer

The demo's Fridays are one job out of many. A person types what they want done, picks the agent it runs through and the connectors it may write to, and the layer holds every write for review, exactly as it does for the recorded run. This is the contract the board (kanban) UI builds on.

## The calls

```
GET  /agents                 -> [AgentChoice]     what a job can be routed through
GET  /connectors             -> [ConnectorView]   what it can write to, beside the scenario's own systems (per team)
POST /connectors/{name}      -> ConnectorView     this team's own settings for one connector (their Slack, not ours)
POST /job                    -> LiveResponse      run it; every write comes back held
```

**Demo mode needs no setup.** Out of the box every connector runs in `mode: "demo"`: `notes` is simulated and `webhook` offers two simulated channels, `ops` and `alerts`. A typed job, its held cards, approve, and the message "delivered" (recorded as `simulated`) all work with nothing configured, for every connector. That is what the video plays. A team that wants the message to really arrive pastes its own webhook URL into the settings form, and the same job now delivers for real.

then the calls that already exist: `POST /decide` to approve, edit or discard the held writes (dependency order, cascade, learning), `GET /state` for everything on the board, `GET /cascade/{run}/{write_id}` for the preview when a card is about to be discarded.

### `GET /agents`

```json
[
  {"id": "replay",  "label": "Recorded run (google:gemini-3.6-flash)", "model": "replay:real", "kind": "replay",  "available": true, "detail": "Plays the transcript … instant. Only the scenario's own prompt."},
  {"id": "live",    "label": "google:gemini-3.6-flash",                "model": "google:gemini-3.6-flash", "kind": "live", "available": true, "detail": "a live model call"},
  {"id": "gateway", "label": "gateway",                                "model": "gateway/openai-chat:gemini-3.6-flash", "kind": "gateway", "available": true, "detail": "through the Pydantic AI Gateway, route pakka"}
]
```

- `replay` is there whenever transcripts are on disk. It is the demo: instant, deterministic, and it only plays the scenario's own prompt (`default_prompt` in `/state`). Any other prompt on it is a 422.
- `live` is `PAKKA_MODEL`. `PAKKA_AGENTS="label=model,label=model"` adds more, for example the gateway route beside the direct call. `available` is false when the provider's key is missing, and `detail` names the key.
- The board shows this list as the agent picker; `available: false` rows are shown disabled with their `detail`.

### `GET /connectors`

```json
[
  {"name": "webhook", "real": true, "configured": false, "mode": "demo", "tools": ["list_channels", "post_message"],
   "targets": ["ops", "alerts"], "settings": {"channels": "name → https URL of an incoming webhook (Slack, Discord, Zapier, n8n); one per line. Leave empty for demo mode."}},
  …
]
```

Six connectors. Each has a **demo mode** (simulated targets, nothing to configure, an approved write is recorded as `simulated`) and, except `notes`, a **live mode** a team switches on with its own credentials. `targets` is what the agent may address (channel, table, repo, endpoint), names only: a URL or a key never comes back out of the API. `settings` is what the settings form asks for, field → hint.

| connector | tools | demo targets | live: settings | live: what an approved write does |
|---|---|---|---|---|
| `notes` | `list_notes`, `write_note` | simulated notes | — (always simulated) | stored in the simulated notes system |
| `webhook` | `list_channels`, `post_message(channel, text)` | `ops`, `alerts` | `channels`: name → https incoming-webhook URL (Slack, Discord, Zapier, n8n) | POSTs `{"text"}` to the channel's URL |
| `email` | `list_senders`, `send_email(to, subject, body)` | `outbox` | `api_key` (Resend), `from` (a verified sender) | sends through Resend's HTTP API |
| `tickets` | `list_tickets`, `open_ticket(repo, title, body)` | `demo/board` | `token` (GitHub, Issues: write), `repo` (owner/name) | opens a GitHub issue; `detail.url` is its link |
| `records` | `list_tables`, `append_record(table, fields)` | `contacts`, `tasks` | `api_key` (Airtable PAT), `base_id`, `tables` | appends a row to the Airtable table |
| `http` | `list_endpoints`, `call_endpoint(endpoint, payload)` | `echo` | `endpoints`: name → `{url, method (POST/PUT/PATCH), headers}` | sends the JSON payload to the endpoint: any API becomes a held write |

- The scenario's own systems (the demo's three) are always on and are not listed here; they are in `/state.systems`.
- A connector's writes are held, flagged, reviewed and learned from like any other: envelopes form per tool, rules apply, the ladder can release the tool after enough approvals.
- Delivery happens **when a person approves the write and at no other moment**; a failed delivery is recorded (`failed`) and never retried; replaying a team's history never delivers again.

### `POST /connectors/{name}`

The body is the connector's `settings` fields, for example:

```json
{"channels": {"ops": "https://hooks.slack.com/services/T…/B…/…"}}                 // webhook
{"api_key": "re_…", "from": "Tom <tom@yourdomain.com>"}                            // email
{"token": "github_pat_…", "repo": "acme/ops"}                                      // tickets
{"api_key": "pat…", "base_id": "app…", "tables": "contacts, tasks"}                // records
{"endpoints": {"crm": {"url": "https://crm.example/api", "method": "POST", "headers": {"Authorization": "Bearer …"}}}}  // http
```

Per team (`X-Pakka-Team`), stored in that team's state, kept across Reset. Each connector validates its own settings (https only, `owner/name` for a repo, an address for `from`, at least one table) and a bad one is a 422 with the reason. All fields empty puts the connector back in demo mode. The response is the updated `ConnectorView`, with `mode: "live"` and the new `targets`; the secrets are not in it. `PAKKA_WEBHOOKS` in the server environment is only a default for the webhook on a self-hosted, single-team install; a team's own settings win.

A settings panel on the board is: `GET /connectors` → for each connector with `settings`, one field per key with its hint (a dict-valued field such as `channels` or `endpoints` is a name → value list) → `POST /connectors/{name}` on save → show `mode` and `targets`.

### `POST /job`

```json
{"prompt": "Write up what landed this week and tell ops", "agent": "live", "connectors": ["notes", "webhook"], "run": null}
```

| field | |
|---|---|
| `prompt` | The job. Empty means the scenario's own prompt (`/state.default_prompt`). |
| `agent` | An `AgentChoice.id`. Empty picks the first available live agent, else `replay`. |
| `connectors` | Connector names the agent may write through for this job. The scenario's tools are always included. Unknown name: 422. |
| `run` | The slot to play; default the next one. A slot already decided or played by autopilot: 409. |

Returns `LiveResponse`: `run` (a `RunResult`, with `prompt`, `agent`, `connectors`, `usage`, `writes[]` each with `status`, `flags[]`, `depends_on`, `blocked_by`, `placeholder`), `learned`, `scoreboard`, `transcript`. After approval, `run.effects[]` carries one entry per landed write with `result_id` and, for a connector, `detail` (`status`: `simulated`, `delivered` or `failed`, plus `channel`), which is what a card's "sent" footer shows. A live Gemini job takes 30–60 s; the recorded one is instant.

`POST /live` remains for the page's *Run live* button and takes the same fields; it is `POST /job` with the first available live agent.

## What a job cost

Every run carries `usage`, what the board shows in a card's header or a stats strip:

| field | |
|---|---|
| `requests` | model requests (turns) |
| `input_tokens`, `output_tokens`, `total_tokens` | as Pydantic AI reports them from the provider; **0 on a replay**, which spends nothing now |
| `tool_calls`, `reads`, `writes` | what the agent did; `writes` is what the layer held or passed |
| `latency_s` | wall clock of the agent's run through the layer |
| `replay` | true for the recorded run |

`/state.scoreboard` sums them over the decided runs: `model_requests`, `input_tokens`, `output_tokens`, `tool_calls`, `latency_s`, and `live_runs` (runs that spent tokens now). The same numbers are attributes on the `pakka.run` span in Logfire (`usage.input_tokens`, …), so tokens per run is one query (`docs/LOGFIRE_DASHBOARD.md`).

## What a board column is

Every card is one `HeldWrite` from a run's `writes[]`, and its column is its `status`:

| column | `status` | how a card gets there |
|---|---|---|
| Held | `held` | every write a job makes lands here; `blocked_by` non-empty means it waits on another card (show it under that card, or greyed) |
| Passed | `passed` | a released tool: the layer sent it without asking (autopilot's green stream) |
| Approved / Edited | `approved`, `edited` | the person's decision; `sent: true` once it has landed, `result_id` is the real id |
| Discarded | `discarded` | the person's decision; `skipped` for the cards that fell with it (cascade) |

The `flags[]` on a card are the checks that fired, each with `kind` (`grounding`, `envelope`, `memory`, `rule`) and `reason` in the scenario's words. A card with `edited_args` shows old → new. `POST /decide` takes every decision for one run in one request.

## What stays honest

- Nothing lands until `POST /decide`. A real connector's send happens inside the approve, once; a failed delivery is recorded on the effect (`status: failed`) and never retried by the layer.
- The recorded agent cannot play a new prompt; free text needs a live agent and its key.
- The demo's three systems are simulated. "Hypothetically working with the payment connectors" is exactly that: the layer's behaviour on those writes is real, the rail behind them is not. The webhook in live mode is the one real connector, so a judge who pastes their own URL can watch an approved message arrive in their channel; in demo mode the same card says *simulated*, never *delivered*.
