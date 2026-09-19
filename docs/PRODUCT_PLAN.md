# Product plan: from the demo to a proxy a team installs

Nothing in this document is in scope for the hackathon build. It exists so the demo's shortcuts are honest about what they stand in for.

## What carries forward unchanged

The models, grounding, the envelope builder and its freeze rule, rule derivation, the ladder, the anomaly catchers, the scoreboard, the `Scenario` format and the Logfire spans. They were written against tool names and argument schemas, not against finance, and they were tested against a scenario module they cannot import.

## What is rebuilt

| Demo | Product |
|---|---|
| Transport: the agent's tools call `staging.Run` in-process | An MCP proxy. The agent points at the proxy; the proxy holds the team's MCP servers behind it. Reads pass through; writes are held. The agent never knows it is there |
| Systems: three in-memory stores with an effects log | The team's real MCP servers. Applying a held write is forwarding the original `tools/call` with placeholders substituted |
| Persistence: one `modal.Dict` blob per team | SQLite beside the proxy: journal, held writes, envelopes, rules, ladder, memory. Exportable, deletable, the team's |
| Auth: a team key header | The proxy's own auth for the review UI; the agent's MCP credentials are the team's, unchanged |
| One run at a time | Sessions: one PR per agent run, many agents |
| Modal as the host | A self-hosted binary. Modal stays as the hosted option |

## The 30 hours

**0–6 — The proxy.** An MCP server that is also an MCP client. It lists the tools of the servers behind it, marks each as read or write (from annotations where the server gives them; otherwise every unknown tool is a write until a person says otherwise), and forwards `tools/call`. Writes go through `staging.Run.write` and return the held text. State in SQLite. `pakka serve --config pakka.toml`.

**6–12 — The review UI, ported.** The demo's page against the proxy's API: sessions instead of Fridays, chains grouped from placeholders exactly as now, edit with validation against the tool's schema (`create_model` from the JSON schema the server published), the cascade preview, rules, promotions.

**12–18 — Native drafts where a system has them.** Holding at the proxy is the same guarantee for every system, which is what keeps the layer agnostic. Where a target has a native draft, a Gmail draft, a GitHub PR, a Stripe payment intent that is not yet confirmed, an adapter can stage there instead and the review page links to it. Adapters are optional and per tool.

**18–24 — Reads with overlays.** A held CRM update should be visible to the agent's later reads in the same session, or the agent will re-issue it. The proxy overlays held writes on later reads of the same record, by id, so the agent sees its own provisional world. Memory already dedupes the re-issue; the overlay stops it happening.

**24–30 — Telemetry and packaging.** OpenTelemetry out of the proxy with Logfire as the default sink and any collector as an option; the dashboard queries shipped as SQL; a second scenario (a deploy pipeline) as the test that no finance assumption leaked out of the scenario module; a Docker image and a one-line install.

## What the layer addresses

Any agent that writes through a tool, MCP first.

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

## Learning stays with the team

Envelopes, rules, workflow shape and memory are the team's: stored beside the proxy, exportable, deletable. No pooling, no shipped priors. The moat is the review habit and the months of "normal" that would have to be re-earned anywhere else.

## The record

The proxy emits OpenTelemetry; Logfire is the default sink. Every decision, both ways, is a span with who and why, nested under the agent's own trace when it is instrumented. SQLite stays the source of truth; the gate never depends on Logfire being reachable.
