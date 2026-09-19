# Jobs: free text, a chosen agent, connectors, one layer

The demo's Fridays are one job out of many. A person types what they want done, picks the agent it runs through and the connectors it may write to, and the layer holds every write for review, exactly as it does for the recorded run. This is the contract the board (kanban) UI builds on.

## The three calls

```
GET  /agents         -> [AgentChoice]      what a job can be routed through
GET  /connectors     -> [ConnectorView]    what it can write to, beside the scenario's own systems
POST /job            -> LiveResponse       run it; every write comes back held
```

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
  {"name": "notes",   "description": "A simulated notes system …",                     "real": false, "configured": true,  "tools": ["list_notes", "write_note"]},
  {"name": "webhook", "description": "A real one: post a message to a named incoming webhook …", "real": true, "configured": false, "tools": ["list_channels", "post_message"]}
]
```

- The scenario's own systems (the demo's three) are always on and are not listed here; they are in `/state.systems`.
- `notes` is simulated: the shape of a CRM, a wiki or a ticket write, with no credentials.
- `webhook` is real. `PAKKA_WEBHOOKS="ops=https://hooks.slack.com/services/…,alerts=https://…"` names the channels; `post_message(channel, text)` POSTs `{"text": …}` to the channel's URL **when a person approves the write**, and at no other moment. The agent never sees or chooses a URL. `configured` is false until at least one channel is set. Slack, Discord, Zapier and n8n incoming webhooks accept that body.
- A connector's writes are held, flagged, reviewed and learned from like any other: envelopes form per tool, rules apply, the ladder can release the tool after enough approvals.

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

Returns `LiveResponse`: `run` (a `RunResult`, with `prompt`, `agent`, `connectors`, `writes[]` each with `status`, `flags[]`, `depends_on`, `blocked_by`, `placeholder`), `learned`, `scoreboard`, `transcript`. A live Gemini job takes 30–60 s; the recorded one is instant.

`POST /live` remains for the page's *Run live* button and takes the same fields; it is `POST /job` with the first available live agent.

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
- The demo's three systems are simulated. "Hypothetically working with the payment connectors" is exactly that: the layer's behaviour on those writes is real, the rail behind them is not. The webhook is the one real connector, so a judge can watch an approved message arrive in a channel.
