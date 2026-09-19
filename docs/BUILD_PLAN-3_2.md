# BUILD_PLAN.md — MVP build plan for Claude Code

Working name: `pakka` (placeholder; keep it in one constant so it can be renamed).
Last fact-check: 19 Sep 2026 (fourth review round: native staging added; the new facts in section 2 were read from the vendors' own pages on 19 Sep, and the 18 Sep facts are unchanged). Sources are linked where a fact shapes the design. A source marked *(secondary)* is not a primary page: confirm it against the pinned SDK or the spec during M0.

### What changed in this revision (19 Sep 2026)

1. **Native staging is in, and it is the preferred hold.** The 18 Sep revision listed native staging adapters (drafts, branches, auth-holds) as a non-goal. That contradicted `docs/PRODUCT_PLAN.md` (hours 12–18) and the README of the hackathon repo, which promise native adapters, and it gave up the best hold there is for the systems agents write to most. Where a target has its own not-yet-live form, the hold now goes there: a Gmail draft instead of a sent mail, a branch and draft pull request instead of a push, an uncaptured Stripe PaymentIntent instead of a charge, a draft invoice instead of an open one. The journal stays the hold for everything else. New: section 5.4a, the `stage_via` block in section 6, milestone M2e, draft tools on the fakes (section 8), CLAUDE.md lines, M0 question 15, questions 9–12 in section 11.
2. **Facts checked on the vendors' pages (section 2):** Gmail `drafts.send`, `drafts.delete` and the Gmail scopes; Microsoft Graph `message: send`; Stripe manual capture and its authorization windows; Stripe invoice status transitions; GitHub draft pull requests, the REST API's inability to mark one ready, and workflow triggers; Slack scheduled messages and their 60-second deletion cut-off; Twilio's 15-minute-to-35-day scheduling window; Google Calendar `sendUpdates=none` and Google's warning against it; Shopify `draftOrderComplete`; the 2026-07-28 changelog's silence on staging. Two MCP servers were inspected directly for the tool pairs they expose.
3. **Mechanisms are classed by what they do in the world:** `inert`, `visible`, `consequential`, `fused`. The first two stage by default, the third needs a person's opt-in per tool, the fourth (anything that goes live on its own at a deadline) is never a hold.
4. **Native staging goes through the upstream's own MCP tools.** The proxy never calls a vendor API of its own: it holds no credential for one, and the dependency list stays at four.
5. **Discard is no longer free.** Withdrawing a native stage is an upstream call that can fail. A failed withdrawal is `unknown`, listed on the session page, never silent.
6. **Read back before promoting.** A person may have edited the draft in the target's own UI. The proxy promotes what is there, shows the difference, and counts it as an edit.
7. **Data model:** `tool_policy.stage` and `tool_policy.expose`; `held_write` gains `stage_kind`, `native_ref_json`, `native_state`, `stage_expires_at`, `read_back_json`, `read_back_hash`, `edited_natively`; verdicts gain `leave`.

Items 3 and 4, the `stage_via` block and the three cases in 5.4a are design proposals, not sourced facts. Confirm them in review.

### What changed on 18 Sep 2026

1. **Tasks are de-risked.** The Go SDK had no typed Tasks API as of v1.7.0, and the v1.8.0 notes list no tasks work. Tasks moved out of M1 and M2b into their own gated milestone (M2d). Until then the proxy never declares the extension.
2. **Both protocol generations on the upstream side too.** The spec is seven weeks old, so expect upstreams that still speak 2025-11-25. Added a 2×2 matrix (5.1), legacy elicitation at commit (5.8) and legacy-mode fakes (8).
3. **Section 2 corrected:** `server/discover` was missing; cacheable results include `resources/read` and `server/discover`, not only lists; the SDK's size caps have defaults (this file said unbounded); `CommandTransport` has no line cap (open question answered); a stateful-handler discovery trap was reported on 15 Sep.
4. **Stack:** Go 1.27.x and its new standard-library `uuid` (drops `google/uuid`); `gopkg.in/yaml.v3` is archived, use `go.yaml.in/yaml/v3`; htmx major pinned (4.0.0 shipped 28 Aug); `x/crypto` ≥ v0.56.0; `govulncheck` in `make check`; SQLite `synchronous=FULL`.
5. **Correctness gaps closed:** discard cascades to dependents; no call is ever sent with a placeholder still in it; late calls to a closed session; compare-and-swap on commit; the tool hash covers descriptions; last-known tool list when an upstream is down.
6. **`unknown` gets smaller:** idempotency keys where the upstream supports them, a "check now" read for the rest.
7. M2b is split into M2b / M2c / M2d. M0 gains questions 10–14. Section 11 gains questions 5–8.

Items 5 and 6 and the matrix in 5.1 are design proposals, not sourced facts. Confirm them in review.

---

## 0. How to use this file

You are building this with a human reviewing. Rules for the whole project:

1. Work one milestone at a time (section 7). Do not start the next until the acceptance tests pass.
2. **Do not trust memory for MCP or go-sdk APIs.** The protocol and SDK were largely rewritten in July 2026. Read the pinned SDK source and `docs/` in the module cache, and the spec pages linked below, before writing protocol code.
3. No new dependency without asking. The dependency list in section 3 is the whole list.
4. Every mechanism in section 5 ships with tests. Run `make check` before saying a task is done.
5. When a decision is not covered here, write a short ADR in `docs/adr/` and ask.
6. Keep `CLAUDE.md` (starter in section 10) current as conventions emerge.
7. Never set `MCPGODEBUG`, in code, CI or Docker. Every v1.7 and v1.8 escape hatch is removed in v1.9.0, so nothing may depend on one.
8. If the pinned SDK source disagrees with section 2, the source wins. Record it in ADR-0001 and fix this file in the same change.

---

## 1. What we are building

A self-hosted layer between a team's own AI agent and the tools it calls over MCP.

- Harmless calls pass straight through.
- Risky writes are **held**: the agent gets a provisional result and keeps working, so the whole task finishes.
- **The hold goes where the target can hold it.** Where a system has its own not-yet-live form (an email draft, a branch and draft pull request, an uncaptured payment, a draft invoice), the proxy stages the write there, through that system's own MCP tools, and the reviewer sees the real thing in the real tool. Everywhere else the proxy's journal holds the call. Same guarantee either way: nothing the agent asked for goes live until a person decides (5.4a).
- A person reviews every held write in one screen, across all systems, and commits or discards the session.
- Over time the product learns from those decisions: actions that keep getting approved are proposed for release; anything unusual is pulled back into review.

Non-goals for the MVP: databases and raw SQL tools, code/file tools, vendor-built agents, non-MCP traffic, hosted multi-tenant SaaS, native staging beyond the catalog's shipped mechanisms (section 6) or through anything but the upstream's own MCP tools, holds on mechanisms that go live by themselves at a deadline (`fused`, 5.4a), the 2025-11-25 experimental tasks (not wire-compatible with the tasks extension), relaying upstream prompts to legacy agents.

---

## 2. Ground truths that shape the design

| Fact | Consequence |
|---|---|
| MCP spec **2026-07-28** made the protocol core stateless: the `initialize` handshake and `Mcp-Session-Id` are retired; each request describes itself through `_meta` (protocol version, client info, client capabilities). A new `server/discover` RPC lets a client learn versions and capabilities up front; the Go client tries it first and falls back to `initialize`. On this revision `ping`, `logging/setLevel`, `resources/subscribe` and `resources/unsubscribe` are rejected with `MethodNotFound`, and resumability (`Last-Event-ID`, standalone GET) is gone. ([spec blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/), [changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog), [go-sdk v1.7.0 notes](https://github.com/modelcontextprotocol/go-sdk/releases/tag/v1.7.0)) | We cannot use the transport session as our session. Sessions are our own concept (5.2). We answer `server/discover` ourselves, with capabilities merged from the agent's upstreams, and advertise only what we really forward (5.1). |
| Same release: `Mcp-Method` / `Mcp-Name` headers are required on Streamable HTTP; tool arguments marked `x-mcp-header` in the input schema are mirrored into `Mcp-Param-*` headers, and a header/body mismatch is rejected with `-32020`. `ttlMs` / `cacheScope` (`public` or `private`, analogous to HTTP `Cache-Control`) are carried by the four list results **and** by `resources/read` and `server/discover`; lists have a deterministic order. Server-initiated requests are replaced by Multi Round-Trip Requests (`resultType: "input_required"`). Change notifications moved to a single `subscriptions/listen` stream; with resumability removed, a dropped stream is not replayed. HTTP+SSE, roots, sampling, logging and Dynamic Client Registration are deprecated. ([SEP-2549](https://modelcontextprotocol.io/seps/2549-TTL-for-list-results), [go-sdk v1.7.0 notes](https://github.com/modelcontextprotocol/go-sdk/releases/tag/v1.7.0)) | Pass MRTR results through untouched. Treat `tools/list` as something clients cache. Mark **every** cacheable result `private`, not only lists (5.1, 5.13). Listen for upstream tool changes so demotion fires promptly, and re-list after every listen (re)connect because missed events never arrive. Schemas pass through untouched, so `x-mcp-header` arguments must round-trip (M0). Do not build on deprecated features. |
| An MRTR `input_required` result carries `inputRequests` and an opaque `requestState`. The client answers the requests and retries the original call with `inputResponses`, echoing `requestState` verbatim without inspecting it. ([Python SDK guide](https://py.sdk.modelcontextprotocol.io/v2/advanced/multi-round-trip/), [C# SDK reference](https://csharp.sdk.modelcontextprotocol.io/api/ModelContextProtocol.Protocol.InputRequiredResult.html)) The retry is a new JSON-RPC request with a new id and the tool handler runs again, so a server's first round is expected to be free of side effects *(secondary: [AppleBOY walkthrough](https://blog.wu-boy.com/2026/09/mcp-2026-07-28-spec-update-en/))*. The Go SDK ships client- and server-side MRTR middleware, including a server-side shim that lets MRTR handlers work against legacy clients ([v1.7.0 notes](https://github.com/modelcontextprotocol/go-sdk/releases/tag/v1.7.0)). | Forwarded retries keep `requestState` intact. At commit, persist it with the write and echo it on the retry (5.8). Key the "one logical call" log on our own call id, never on the JSON-RPC id. What a legacy agent sees when an upstream asks for input is an M0 question (matrix in 5.1). |
| Tasks moved into the `io.modelcontextprotocol/tasks` extension. The server alone decides, per request, whether to answer with a task (`resultType: "task"`) or a standard result; the client only declares the extension, and a server must never return a task to a client that did not declare it. A server that cannot answer without a task returns `-32021` (missing required client capability). The method set is `tasks/get`, `tasks/update` and `tasks/cancel`, plus `notifications/tasks` on the listen stream. Clients poll `tasks/get` at the server's `pollIntervalMs`; a task can pause in `input_required`, answered through `tasks/update`; clients should persist task ids so polling survives a restart. The extension is not defined under 2025-11-25, and that revision's experimental tasks are not wire-compatible with it. ([tasks extension](https://modelcontextprotocol.io/extensions/tasks), [SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)) **The Go SDK had no typed Tasks API as of v1.7.0**: no `Task` or `CreateTaskResult` types, no `tasks/*` methods, no task-aware `CallToolResult`, only generic extension declaration and custom methods *(secondary: [AppleBOY walkthrough](https://blog.wu-boy.com/2026/09/mcp-2026-07-28-spec-update-en/); a [third-party Go runtime](https://pkg.go.dev/github.com/hurtener/dockyard@v1.1.0/runtime/tasks) reports the same and routes `tasks/*` itself)*. The v1.8.0 notes list no tasks work. | Tasks are hand-built on generic extensions and custom methods, or deferred. They are their own gated milestone (M2d). Until then we never declare the extension, in `server/discover` or upstream, so a compliant upstream never sends a task; `-32021` passes through on forwarded calls and fails the write at commit with a plain message. When built: declare tasks upstream only when the agent declared it on that request. Task calls carry only a task id, so we map ids back to their upstream. Held calls return standard results. Commit persists task ids and resumes polling after a restart (5.1, 5.8). |
| The official Go SDK **v1.7.0** fully supports 2026-07-28 and keeps backward compatibility with 2025-11-25 and earlier on every endpoint. 2026-07-28 over HTTP requires `StreamableHTTPOptions.Stateless = true`, and a stateless server ignores `Mcp-Session-Id` entirely; the flag that restores it is removed in v1.9.0. ([release notes](https://github.com/modelcontextprotocol/go-sdk/releases/tag/v1.7.0), [protocol docs](https://github.com/modelcontextprotocol/go-sdk/blob/main/docs/protocol.md)) | Run the agent-facing endpoint stateless and key sessions ourselves. There is no legacy session-id fallback (5.2). Test with both a legacy client and a 2026-07-28 client. |
| **v1.8.0** is out and is equivalent to v1.8.0-pre.2 (released 4 Sep 2026). It hardens v1.7.0: `MaxEventSize` on `SSEClientTransport` and `StreamableClientTransport`, `StdioTransport.MaxLineLength`, a JSON nesting cap (1000 levels), fixes for session leaks, deadlocks and teardown hangs, and `ServerOptions.SupportedProtocolVersions`. The notes say every decoding path that buffers input is now bounded, and GitHub's gateway refers to an SDK constant `DefaultMaxEventSize`, so the caps have defaults (the 17 Sep revision of this file said "unbounded unless set"; read the pinned source). `ServerOptions.SetCacheable` decides `ttlMs` / `cacheScope` for `server/discover`, the four list methods and `resources/read`; anything left unset falls back to the protocol default `public`. Behaviour changes: a stateful streamable handler now answers a 2026-07-28 request with JSON-RPC error `-32022` so the client can renegotiate down; a cancelled call now returns immediately and sends its cancel notification asynchronously. Both changes have escape hatches (`plaintextstatefulrejection`, `blockingcancelnotify`) that go away in v1.9.0. The legacy `MCPGODEBUG` options `seterroroverwrite`, `enableoriginverification`, `disablecontenttypecheck` and `disablelocalhostprotection` are removed. ([v1.8.0-pre.2 notes](https://github.com/modelcontextprotocol/go-sdk/releases/tag/v1.8.0-pre.2), [gateway PR #13145](https://github.com/github/gh-aw-mcpg/pull/13145)) | Pin v1.8.0 (GitHub's gateway pins pre.2, the same code). Set every cap to our own number instead of aliasing the SDK default, so an SDK bump cannot move it. Set `cacheScope: private` on every cacheable result (5.1). A cancelled or timed-out write may still land upstream, so it becomes `unknown` (5.8). Never set `MCPGODEBUG`. |
| The SDK supports the two newest Go releases. Go 1.27.0 shipped on 19 Aug 2026; 1.27.1 and 1.26.8 followed on 1 Sep 2026, so the supported pair is 1.27 and 1.26. Go 1.27 adds a standard-library `uuid` package (`NewV4`, `NewV7`, `Parse`; RFC 9562; `NewV7` values sort in increasing order unless the clock moves back). Cross-origin protection has been off by default since v1.6.0, while DNS-rebinding protection for localhost is on by default. ([golang-announce](https://groups.google.com/g/golang-announce), [`uuid`](https://pkg.go.dev/uuid), [SDK releases](https://github.com/modelcontextprotocol/go-sdk/releases)) | Build with Go 1.27.x and pin it with a `toolchain` line. Use the standard-library `uuid`; drop `google/uuid`. Configure `CrossOriginProtection` explicitly on the agent endpoint. |
| GitHub runs its MCP server on this SDK, and GitHub's own MCP gateway is built on it: `CommandTransport` and `StreamableClientTransport` to backends, `NewStreamableHTTPHandler` in front, tools registered via `Server.AddTool` to let backend schemas through, guarded by canary tests. It deliberately runs `Stateless: false`, because it ties backend connections and timeouts to sessions. ([review issue](https://github.com/github/gh-aw-mcpg/issues/13130)) Two follow-ups from that repo. `CommandTransport` has no `MaxLineLength` equivalent in v1.8.0-pre.2; only `StdioTransport` does ([PR #13145](https://github.com/github/gh-aw-mcpg/pull/13145)). And on 15 Sep 2026 its stateful handlers were reported to answer a modern client's `server/discover` successfully, which left the client on the sessionless path, so its next `tools/list` failed with `-32022`; the tested fix sets `SupportedProtocolVersions` to the legacy versions so discovery is refused and the client falls back to `initialize` ([issue #13196](https://github.com/github/gh-aw-mcpg/issues/13196)). | Reference for the plumbing, not for the session model. ADR-0001 must say why we diverge: our upstream connections belong to the agent, not to a session. Copy the canary-test habit. Bound a stdio child's stdout ourselves (5.1). The discovery trap is one more reason to run stateless; if ADR-0001 ever chooses stateful, set `SupportedProtocolVersions` and keep that failure as a canary. |
| The 2026-07-28 spec forbids **token passthrough**: a server must only accept tokens issued for itself; when it calls upstream it uses a separate token and must not pass through the one it received. ([security considerations](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations)) | The proxy issues its own keys to agents and holds its own upstream credentials. Never forward an agent's Authorization header. |
| Client registration priority in the spec: pre-registered credentials first, then Client ID Metadata Documents, then Dynamic Client Registration as a deprecated fallback. A CIMD `client_id` must be an https URL with a path. Clients should support static pre-registered credentials, bound to the issuer that granted them. The SDK supports pre-registered clients. ([client registration](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration)) | A self-hosted proxy has no public https URL by default, so M7 starts with pre-registration. |
| Tool annotations (`readOnlyHint`, `destructiveHint`, …) are optional, self-reported hints. Since v1.7.0 the Go SDK always serializes `readOnlyHint` and `idempotentHint` because they are bare `bool`, so from a Go-built upstream `false` and "unset" look the same; `destructiveHint` and `openWorldHint` are `*bool`. ([v1.7.0 notes](https://github.com/modelcontextprotocol/go-sdk/releases/tag/v1.7.0)) | Use them to seed classification only. `readOnlyHint: false` proves nothing. Unknown means write. |
| `modernc.org/sqlite` is a CGo-free `database/sql` driver. Its README warns to pin `modernc.org/libc` to the exact version in its `go.mod`. ([pkg.go.dev](https://pkg.go.dev/modernc.org/sqlite)) | Static binaries with `CGO_ENABLED=0`. Pin libc. |
| In WAL mode SQLite defaults to `synchronous=NORMAL`: the database stays consistent, but a committed transaction can roll back after power loss or an OS crash. It is durable across application crashes either way. ([pragma docs](https://sqlite.org/pragma.html#pragma_synchronous)) | "Persist `executing` before sending" (5.8) only prevents a double send after power loss if that write is durable. Run `synchronous=FULL`. Our volume is tiny, so the cost does not matter. |
| Tool schemas may now use full JSON Schema 2020-12, and `structuredContent` may be any JSON value, not only an object (SEP-2106) *(secondary: [AppleBOY walkthrough](https://blog.wu-boy.com/2026/09/mcp-2026-07-28-spec-update-en/); confirm in the changelog)*. | Id extraction cannot assume an object (5.4). Consuming-argument checks must resolve `$ref` and combinators under depth and node limits, and treat anything they cannot resolve as unknown → `pause`. Validating edited arguments needs a 2020-12 validator: the SDK already pulls one in (its notes mention `jsonschema-go`), so reuse it rather than add a dependency (M0). |
| `gopkg.in/yaml.v3` is archived and unmaintained (April 2025). The YAML organization maintains a drop-in fork at `go.yaml.in/yaml/v3`. ([go-yaml/yaml](https://github.com/go-yaml/yaml), [yaml/go-yaml](https://github.com/yaml/go-yaml)) | Use `go.yaml.in/yaml/v3`. |
| htmx **4.0.0** shipped on 28 Aug 2026. 2.x stays npm `latest` until early 2027 and 4.x is tagged `next`, but the htmx website now documents 4.0. Differences that bite: attribute inheritance is explicit, event names changed, 4xx/5xx responses are swapped into the page by default, requests use `fetch()`. ([announcement](https://four.htmx.org/announcements/2026-08-28-htmx-4.0.0-is-released)) | Pin one major here and in `CLAUDE.md`, vendor that exact file and record its SHA-256. Default: 2.0.x, the line npm still marks `latest` (question 5 in section 11). Whichever is chosen, write attributes from the vendored version's own docs: the website and model memory now describe different majors. |
| `golang.org/x/crypto` v0.56.0 (2 Sep 2026) fixes vulnerabilities in its `ssh` package. ([golang-announce](https://groups.google.com/g/golang-announce)) | We import only `bcrypt`, but pin ≥ v0.56.0 and run `govulncheck` in `make check` so the next one is caught. |
| Gmail's API is a complete draft cycle. `drafts.create`; `drafts.update` ("Because messages cannot be updated, the message contained in the draft is destroyed and replaced by the new MIME message supplied in the update request"); `drafts.get`; `drafts.delete` ("Immediately and permanently deletes the specified draft. Does not simply trash it."); `drafts.send` ("Sends the specified, existing draft to the recipients in the `To`, `Cc`, and `Bcc` headers"), which returns a `Message`. Sending is not id-stable: "When the draft is sent, the draft is automatically deleted and a new message with an updated ID is created with the `SENT` system label." Scopes: `gmail.compose` ("Manage drafts and send emails") is the narrowest that can both draft and send; `gmail.send` ("Send email on your behalf") cannot draft; the three scopes `drafts.send` accepts are the three `drafts.delete` accepts. The API has no scheduled send: the guide never mentions one *(secondary: a Google community thread says the same)*. Anthropic's Gmail connector exposes the cycle over MCP, observed in a Claude Code session on 19 Sep 2026: `create_draft` and `update_draft` return the draft `id`; `get_draft`, `list_drafts`, `delete_draft`; and `send_message` with a `draftId` ("the specified draft is sent as is"). ([drafts guide](https://developers.google.com/workspace/gmail/api/guides/drafts), [drafts.send](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/send), [drafts.delete](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/delete), [scopes](https://developers.google.com/workspace/gmail/api/auth/scopes), [community thread](https://support.google.com/mail/thread/5594544/is-possible-to-send-a-schedule-email-using-the-gmail-api?hl=en)) | Email is the first native stage: a held send becomes a draft in the sending account's Drafts folder, inert until promoted (5.4a). `id_stable: false`, so a dependent that quotes the message id keeps its placeholder until the send result arrives. The draft lives in whichever mailbox the upstream credential belongs to; a reviewer who is not that account can open it only on the proxy's page (question 10). The upstream credential needs a scope that drafts, not a send-only one (5.13). |
| Microsoft Graph sends an existing draft with `POST /me/messages/{id}/send`: "Send an existing draft message", "This method saves the message in the **Sent Items** folder", least-privileged permission `Mail.Send`, and "If successful, this method returns `202 Accepted` response code. It doesn't return anything in the response body." ([message: send](https://learn.microsoft.com/en-us/graph/api/message-send)) | The same shape as Gmail, so one email pattern with two catalog entries. Promotion returns no body, so the promoted id comes from read-back, not from the result (5.4a). |
| Stripe separates authorization from capture with `capture_method=manual`. After authorization the PaymentIntent is `requires_capture`; `POST /v1/payment_intents/:id/capture` captures it (the full amount by default; "you can only perform one capture on an authorized payment for most payments"); cancelling the PaymentIntent releases the hold; the charge's `payment_method_details.card.capture_before` "indicates when the authorization expires". Windows: online card holds are valid for 7 days (Visa merchant-initiated: "4 days and 18 hours"), in-person 2 days on most networks, Klarna to midnight of the 28th day, PayPal 10 days extended once; "If the authorization expires before you capture the funds, the funds are released and the payment status changes to `canceled`." The hold is not invisible: "Card statements from some issuers and interfaces from payment methods don't always distinguish between authorizations and captured (settled) payments, which can sometimes confuse customers." A private-preview `automatic_delayed` capture captures by itself before expiry. ([place a hold](https://docs.stripe.com/payments/place-a-hold-on-a-payment-method)) | An uncaptured PaymentIntent is a native stage with an expiry and a customer-visible effect: class `consequential`, off by default, per-tool opt-in (5.4a). `stage_expires_at` comes from `capture_before` and the review page counts down to it. The PaymentIntent keeps its id through capture, so `id_stable: true`. `automatic_delayed` is `fused`: never a hold. |
| Stripe invoices are born as drafts: "Invoices are initially created with `status=draft`, and you can only edit them while they're in this state." A draft is deleted with `DELETE /v1/invoices/:id` or finalized with `POST /v1/invoices/:id/finalize` (→ `open`); afterwards "you can't change most of its details", and it is voided rather than deleted. Finalizing can email the customer by itself: "By default, Stripe automatically sends invoices when you set `collection_method` to `send_invoice`", unless the account's "Email finalized invoices to customers" setting is off. ([status transitions](https://docs.stripe.com/invoicing/integration/workflow-transitions)) | A draft invoice is an `inert` stage with a stable id. Promote = finalize; the catalog entry records whether finalizing also sends, because that is the moment the customer sees it. |
| GitHub draft pull requests: "Draft pull requests cannot be merged", "code owners are not automatically requested to review them", and "Marking a pull request as ready for review will request reviews from any code owners." The REST API creates one (`draft` on create) but its update endpoint has no `draft` field, so REST cannot mark a draft ready; GitHub's MCP server can (`update_pull_request` takes `draft`, "Mark pull request as draft (true) or ready for review (false)", and `merge_pull_request` takes `expectedHeadSha`; observed 19 Sep 2026). Drafts are available "in public repositories with GitHub Free and GitHub Free for organizations, GitHub Pro, and legacy per-repository billing plans, and in public and private repositories with GitHub Team and GitHub Enterprise Cloud". A `pull_request` workflow runs by default on `opened`, `synchronize` and `reopened`; the docs do not exempt drafts, and `ready_for_review` is a separate activity type. ([about pull requests](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests), [REST pulls](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28), [workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)) | A branch plus draft pull request is a `visible` stage: collaborators see it and CI may run on it. Promote = mark ready for review, or merge when the team says so; withdraw = close the pull request and delete the branch. Which tools can promote is a fact about each MCP server, not about the REST API: check it per upstream in M0 (question 15). |
| Slack `chat.scheduleMessage` schedules "up to 120 days into the future", returns a `scheduled_message_id`, and lists through `chat.scheduledMessages.list`; `chat.deleteScheduledMessage` "cannot delete scheduled messages that have already been posted to Slack or that will be posted to Slack within 60 seconds of the delete request". Twilio: "Messages must be scheduled between 15 minutes and 35 days" ahead, and a scheduled message is cancelled by setting its `Status` to `canceled`. ([scheduleMessage](https://docs.slack.dev/reference/methods/chat.scheduleMessage), [deleteScheduledMessage](https://docs.slack.dev/reference/methods/chat.deleteScheduledMessage), [Twilio scheduling](https://www.twilio.com/docs/messaging/features/message-scheduling)) | Scheduled sends go live on their own if nobody acts. That is a `fused` mechanism: never a hold. It may back LOG's undo window (5.9), with the cut-off (60 s on Slack) subtracted. |
| Google Calendar `events.insert` takes `sendUpdates`; `none` means "No notifications are sent", and Google warns: "Using the value `none` can have significant adverse effects, including events not syncing to external calendars or events being lost altogether for some users." ([events.insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)) | A quiet create is not a stage: the event is on the calendar and the vendor warns against the flag. Calendar writes stay in the journal. |
| Shopify `draftOrderComplete` "Completes a draft order and converts it into a regular order. The order appears in the merchant's orders list, and the customer can be notified about their order." Its payload's `draftOrder.order` is a separate `Order` with its own id. ([draftOrderComplete](https://shopify.dev/docs/api/admin-graphql/latest/mutations/draftOrderComplete)) | A draft order is a stage whose promoted object has a new id: `id_stable: false`, the real id comes from the completion result. A catalog example, not shipped in the MVP. |
| The 2026-07-28 changelog adds nothing for staging, dry runs or approval: no new tool annotation, no preview call. It does say that servers "that need cross-call state use explicit, server-minted handles passed as ordinary tool arguments". ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)) | Native staging is a catalog fact about a pair of tools, never a protocol feature, and a staged object's id is exactly such a handle: it travels as an ordinary argument on the promote call. Nothing depends on an upstream cooperating beyond exposing its draft tools. |

---

## 3. Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Go 1.27.x, pinned with a `toolchain` line in `go.mod` (the SDK supports 1.27 and 1.26) | One static binary, strong stdlib HTTP, easy concurrency, proven for exactly this kind of gateway. |
| MCP | `github.com/modelcontextprotocol/go-sdk` pinned at v1.8.0 (see section 2) | Tier 1 SDK, both client and server roles, both protocol generations. |
| HTTP | `net/http` stdlib | No framework needed. |
| Storage | SQLite in WAL mode via `modernc.org/sqlite`, plain `database/sql`, embedded SQL migrations. Pragmas: `synchronous=FULL`, `busy_timeout`, `foreign_keys=ON` | Single file, no service to run, fits self-hosted. One writer goroutine on its own connection (`SetMaxOpenConns(1)`), plus a read-only pool for the UI. `FULL` because the commit engine's crash safety depends on durable writes (section 2). |
| UI | `html/template` + htmx **2.0.x**, vendored with its SHA-256 recorded, embedded with `go:embed` | No JS build step; htmx is a small dependency-free script. Whole product stays one binary. The major is pinned on purpose (section 2). |
| Config | YAML (`go.yaml.in/yaml/v3`, the maintained fork) for bootstrap, DB for everything editable in the UI | |
| IDs | UUIDv7 from the standard-library `uuid` package (`uuid.NewV7`) | Sortable by time, and one dependency fewer. Placeholders for uuid-typed ids use `uuid.NewV4`. |
| Logging | `log/slog` JSON | |
| Crypto | stdlib AES-GCM for secrets at rest, `golang.org/x/crypto/bcrypt` (module ≥ v0.56.0) for the admin password. Agent keys are 32 random bytes, stored as SHA-256 and compared in constant time | bcrypt on every MCP request would blow the latency target; a high-entropy key does not need a slow hash. |
| Packaging | Static binary + distroless Docker image | |
| Tooling (not linked into the binary) | `staticcheck`, `govulncheck` | Both run in `make check`. |

The whole module list is now four: the go-sdk, `modernc.org/sqlite` (with its pinned `libc`), `go.yaml.in/yaml/v3` and `golang.org/x/crypto`.

SDK bumps happen only with the canary suite green and the release notes read. v1.9.0 removes every v1.7 and v1.8 escape hatch, so that bump gets its own PR.

Performance note: tool-call volume is tiny and model latency dominates. "Fast" here means low added latency on pass-through (target: under 5 ms p95 excluding upstream) and fast startup. Measure it: `make bench` runs a pass-through benchmark against a fake upstream, and M1 records the number.

---

## 4. Architecture

```
agent ──HTTP──▶ [ agent endpoint ]──▶ [ router ]──▶ [ policy ]──┬─▶ forward ─▶ [ upstream clients ] ─▶ MCP servers
   (or stdio bridge)                                            │
                                                                └─▶ hold ─▶ [ journal | native stage in the upstream ] ─▶ provisional result
                        [ review UI ] ─▶ [ commit engine ] ─▶ [ upstream clients ]
                        [ learner: scorecard, envelope ]   [ notifier ]   [ SQLite ]
```

One daemon owns the database. Everything else talks to it.

- `pakka serve` — the daemon: agent endpoint, UI, commit engine.
- `pakka stdio --agent <key>` — a thin stdio MCP server that forwards to the local daemon over HTTP, for clients that only launch local commands. One code path for policy.
- `pakka report` — prints the observe-mode census.
- `pakka health` — exits 0 when the daemon answers. Used as the Docker `HEALTHCHECK`, because a distroless image has no shell or curl.

Two listeners. The agent endpoint and the review UI listen on separate addresses, so the UI can stay on loopback while the agent endpoint is reachable from wherever the agent runs. They are never the same origin.

### Data model (SQLite)

- `agent(id, name, key_hash, version_label, mode[observe|hold], created_at)`
- `upstream(id, agent_id, name, transport[stdio|http], command_json, url, auth_kind, secret_ref, tools_hash, protocol_version, last_seen_at)`
- `tool(id, upstream_id, name, input_schema_json, output_schema_json, annotations_json, schema_hash, class[read|write|unknown], holdable)`
- `tool_policy(tool_id, posture[pass|log|stage|hold], stage[journal|native], expose[live|draft_only], source[hard|team|learned|catalog|heuristic], rules_json, updated_by, updated_at)`
- `session(id, agent_id, key, key_source[url|header|stdio|idle], rule_version, status[open|awaiting_review|committing|committed|discarded|partial|closed], opened_at, last_activity_at, closed_at, close_reason[explicit|stdio_exit|idle], review_started_at, review_seconds)`
- `call(id, session_id, seq, tool_id, args_json, class, decided_posture, would_posture, reason, result_json, result_hash, is_error, started_at, duration_ms)`
- `held_write(id, call_id, placeholder, placeholder_kind[string|uuid|int|none], depends_on_json, duplicate_of, placeholder_in_text, prior_json, edited_args_json, status[pending|executing|needs_input|executed|failed|skipped|unknown], upstream_task_id, input_requests_json, request_state, real_id, verdict[commit|discard|edit|leave], reason_tag, note, skip_reason[discarded|cascade|failed_dependency], idempotency_key, attempts, executed_at, error, stage_kind[journal|native], native_ref_json, native_state[staging|staged|promoting|promoted|withdrawing|withdrawn|expired|left|orphan], stage_expires_at, read_back_json, read_back_hash, edited_natively)`
- `task_route(proxy_task_id, session_id, upstream_id, upstream_task_id, created_at, expires_at)` — created in M2d.
- `read_dep(id, session_id, call_id, entity_keys_json, result_hash)`
- `tool_stats(agent_id, tool_id, reviewed, committed, discarded, edited, attentive_reviews, sessions, last_promoted_at, last_demoted_at)`
- `envelope(agent_id, tool_id, version, stats_json, built_from_n, created_at)`
- `rule(id, agent_id, tool_id, version, text, status[proposed|active|retired], created_from_json, created_at)`
- `audit(id, at, actor, action, subject, detail_json)` — append-only, enforced by triggers that abort `UPDATE` and `DELETE`.

Hash the full result first, then truncate. `result_hash` always covers the complete payload; the stored `result_json` is capped (default 256 KB) with a marker. Conflict checks compare hashes, never truncated bodies.

`schema_hash` covers the tool's name, description, input schema, output schema and annotations. A description-only change is how a tool gets quietly repurposed, so it must count as a change (5.10).

`session` is unique on `(agent_id, key)`: a run id means nothing outside its agent. `upstream.protocol_version` is the negotiated revision, which decides how that upstream asks for input (matrix in 5.1).

`native_ref_json` is `{upstream, kind, id, url}`, with `url` only where the catalog can build one. `read_back_hash` is hashed like `result_hash`, full payload first. `tool_policy.stage` is `native` only when the catalog has a `stage_via` block for the tool and the team has not switched it off; `expose: draft_only` leaves the live tool out of that agent's list (5.4a).

---

## 5. Mechanisms

### 5.1 Upstreams and the aggregated endpoint

- Each agent gets **one** MCP endpoint: `POST /mcp/{agentId}`. Behind it sit all of that agent's upstreams. This is what makes a cross-system session possible without any agent cooperation.
- Tool names are exposed as `{upstream}__{tool}`. If an agent has exactly one upstream, the prefix can be switched off.
- `server/discover`: answer it ourselves. Capabilities are the union of what the agent's upstreams offer, cut down to what we really forward. Do not advertise the tasks extension before M2d, or resource subscriptions in the MVP. The result is cacheable, so it is `private` too.
- `tools/list`: merge upstream lists in a deterministic order (upstream name, then tool name). Store each tool's schema hash. Set `ttlMs` and `cacheScope: private` through `SetCacheable`: the SDK falls back to `public` when unset, and our lists differ per agent and per rule version. Clients cache this list and build prompt caches on it, so it must only change when we publish a rules batch (5.11) or an upstream really changes. A session's list is built at that session's `rule_version`, so a `tools/list` request carries the session key like any other request (5.2); one without a key gets the latest published version.
- When an upstream is down, keep serving its last-known tools from the database and fail its calls with a clear error. Dropping them would flap the list and burn every client's prompt cache. Drain upstream pagination fully when listing; return our merged list as one page unless it passes a size cap.
- **Holdable** is decided by class, not by current posture: every tool classed `write` or `unknown` is holdable, because learning and envelope breaches (5.10) move tools between postures at any time and the list must not flap. The only exception is a tool a person pins to PASS; that change ships with the next rules publish. Holdable tools do **not** advertise `outputSchema`. That keeps text-only provisional results valid (5.4). Pass upstream `structuredContent` through unchanged when such a tool is forwarded.
- **Stage tools**, the tools a `stage_via` block names for creating, updating, reading back, listing and withdrawing a staged form (section 6), are forwarded with their real schemas and keep their `outputSchema`. They are never held themselves: holding a draft would hold a hold. Their calls are journaled as native stages (5.4a). Under `expose: draft_only` the live tool is left out of that agent's list; like a PASS pin, an exposure change ships with the next rules publish, so the list does not flap.
- Register forwarded tools in a way that does not re-validate or rewrite upstream schemas. Find how the pinned SDK allows this, add a canary test.
- Upstream connections: stdio via `CommandTransport`, remote via `StreamableClientTransport`. Set `MaxEventSize` on HTTP transports to our own constant and a timeout on every call. Reconnect with backoff. `CommandTransport` has no line-length cap in v1.8.0 (section 2), so bound the child's stdout ourselves; re-check on every SDK bump. Record each upstream's negotiated `protocol_version`.
- Upstream tool changes: set the list-changed handler on each upstream client so the SDK opens `subscriptions/listen`. On a change, **and on every (re)connect of that stream, because missed events are never replayed**, re-list, recompute hashes and run demotion (5.10). Fall back to TTL polling for upstreams that do not advertise the capability, which includes every legacy upstream that lacks list-changed.
- Non-tool methods (prompts, resources) are passed through with the same namespacing. MRTR `input_required` results and their retries must reach the agent untouched, including the opaque `requestState`, and be logged as one logical call. A retry repeats the namespaced tool name, so it routes to the same upstream. The SDK ships client-side middleware that answers MRTR automatically, so confirm in M0 how to bypass it on upstream clients. `resources/subscribe` no longer exists on 2026-07-28 (section 2); the MVP does not relay resource subscriptions. `resources/read` results are cacheable, so mark them `private`.
- **Tasks (M2d, gated by ADR-0001).** Before M2d the proxy declares the extension nowhere: a compliant upstream then never answers with a task, and one that cannot work without it returns `-32021`, which we pass through. From M2d on: the upstream decides per request whether to answer with a task; the agent only declares the extension.
  - Forwarded calls: declare the tasks extension to the upstream only if the agent declared it on that request. An upstream then never returns a task the agent cannot handle, and we never return a task to an agent that did not declare it.
  - Routing: `tasks/get` and `tasks/update` carry only a task id. When a forwarded call returns a task, record it in `task_route` and hand the agent a proxy task id; route later task calls through that map. Pass `tasks/cancel` through the same way (the C# SDK wires it beside get and update; confirm the method set in the extension spec during M0).
  - Held calls never start an upstream task. They return the ordinary provisional result, which is allowed because the server may always answer with a standard result.
  - At commit the proxy declares the extension itself and handles tasks as in 5.8.
- **Protocol generations, both sides.** Upstreams will be a mix of 2026-07-28 and legacy for a long time, and they ask for input differently: modern ones return `input_required`, legacy ones send a server-initiated `elicitation/create` while the call is open. Proposed MVP behaviour for forwarded calls (confirm in ADR-0001):

  | | 2026-07-28 upstream | legacy upstream |
  |---|---|---|
  | **2026-07-28 agent** | MRTR passes through untouched. Mirror the agent's declared client capabilities on the upstream request, the same way as for tasks. | The forwarding client does not declare elicitation, so a compliant upstream does not ask. Translating a live elicitation into `input_required` means parking an open upstream call behind a `requestState` we mint: later feature. |
  | **legacy agent** | The agent cannot read `input_required`. For a write in hold mode, turn it into a hold: journal the call, return the provisional result, and let the reviewer answer at commit (the first round is expected to be free of side effects, section 2). Otherwise return a tool error saying the tool needs interactive input that this client cannot give through the proxy. | As above: no elicitation declared on forwarded calls. |

  At commit the proxy is the client on both generations, so the reviewer can answer either kind of prompt (5.8).

### 5.2 Agent auth and sessions

- Agents authenticate with a proxy-issued bearer key, stored hashed. Never forward it upstream.
- The endpoint runs stateless, so the SDK gives us no session id on either protocol generation. Every request resolves its session the same way, including `tools/list` (5.1). Session resolution, first match wins:
  1. run id in the URL: `/mcp/{agentId}/r/{runId}`
  2. `X-Session-Key` header
  3. one `pakka stdio` process = one session
  4. idle windowing (same agent, last activity within `session_idle`, default 5 min) — **observe mode only**
- **Hold mode requires 1, 2 or 3.** Idle windowing would merge parallel runs of the same agent into one review, so a hold-mode request without a key is rejected with an error that says how to add one. Setting the run id is a URL change, not a code change.
- Rule 3 only fits agents that spawn a stdio process per run. Some hosts are reported to start stdio servers when the app launches and keep them until it quits (Claude Desktop is described this way), which would put every task in that app into one review. Document this, point such hosts at the HTTP endpoint with a run id, and check the real behaviour of target hosts during M1.
- A session closes on explicit `POST /api/sessions/{id}/close`, stdio bridge exit, or idle timeout. If it has pending held writes it becomes `awaiting_review` and the notifier fires. Hold mode has its own idle timeout, `hold_idle` (default 30 min): agents pause for long model turns and for people, and closing under them splits one task into two reviews. `session_idle` (5 min) stays for observe-mode windowing.
- Late calls. A write for a session that is no longer `open`: if it was closed by idle timeout and no reviewer has opened it (`review_started_at` is null), reopen it. Otherwise reject it with an error that says to start a new run id; a review must never grow while someone is reading it. Reads are still forwarded, with the overlay.
- Run ids and session keys are identifiers, not credentials. They show up in URLs and access logs. They are scoped to the agent (`(agent_id, key)` is unique) and only ever used after the agent key has been checked.

### 5.3 Classification and postures

Four postures: **PASS** (forward, minimal logging), **LOG** (forward, record prior value, undo where a true inverse exists), **STAGE** (hold for end-of-session review), **HOLD** (staged and can never be released by learning).

Where a hold lives is a separate choice from whether to hold. STAGE and HOLD say that a person decides. `tool_policy.stage` says where the held thing waits: in the journal (5.4), or natively in the target when the catalog has a `stage_via` block for the tool and the team has not switched it off (5.4a). Native is the preference, the journal is the floor. The decision order below is unchanged by it.

Decision order, first match wins:
1. hard rules set by the team (always HOLD or always STAGE)
2. condition rules on arguments (below)
3. envelope breach for a released tool → STAGE this call (5.10)
4. team-set posture
5. learned posture
6. catalog default for the upstream kind
7. heuristics: annotations (`readOnlyHint: true` → read; `false` proves nothing, section 2), then name verbs (`get|list|search|read|fetch|query` → read; `create|update|delete|send|post|merge|pay|refund|publish` → write)
8. unknown → treat as write → STAGE

Condition rules are small and declarative: `{path, op, value}` with ops `gt, lt, in, not_in, matches, len_gt`. Paths are dotted with `*` wildcards; write this helper yourself, no JSONPath library. Built-in limits expressed as rules: max records per session, amount thresholds, recipients outside a list of internal domains.

Tools whose **result steers the agent** (catalog flag `result_matters`, e.g. a payment authorization) cannot be given a provisional result. Their options are LOG or `pause` (return an error telling the agent to stop and wait). Never STAGE them. A native stage does not change this: the result of the staged form is not the result of the requested action (an authorization's `requires_capture` is not a charge's `succeeded`), so a `result_matters` tool is still never staged, natively or otherwise.

Tools known to **confirm with the user upstream** through MRTR (catalog flag `confirms_upstream`; Supabase has said it will do this for destructive queries) can be staged only because the reviewer can answer the prompt at commit (5.8). If that flow is switched off, they default to LOG or `pause`.

In **observe mode** everything is forwarded, and `would_posture` records what hold mode would have done. This powers the census.

### 5.4 Journal and provisional results

This is the journal hold, the floor that works for every tool. When the tool has a native stage (5.4a), the journal entry, the placeholder rules and the substitution below still apply, and 5.4a lists what differs.

For STAGE and HOLD:
1. Capture the prior value (5.6).
2. Append the call to the journal with a placeholder (shape below). Record a `depends_on` edge for every placeholder found in this call's arguments. Mint the write's `idempotency_key` now, so every later attempt carries the same one (5.8).
3. Return a transparent provisional result, `isError: false`, as a text block:

   > HELD FOR REVIEW, not yet applied. Your call to `{tool}` was recorded as `{placeholder}` and will be applied after a person approves this session. Continue the rest of your task as if this step succeeded. Do not retry it. If you need to refer to what this call creates, use the id `{placeholder}`.

4. Provisional results are **text only**. Never invent field values: a synthesized `amount: 0` or empty `status` invites wrong reasoning. This is valid because holdable tools do not advertise an `outputSchema` (5.1).

**Placeholder shape follows the id type** when it is known (catalog `id_type`, the creating tool's upstream output schema, or real ids seen in observe mode):
- string ids → `held_<uuidv7>`
- uuid ids → a freshly minted UUID, recorded as a placeholder
- integer ids → a negative integer from a per-session counter

**Consuming arguments** are the arguments that could receive this entity's id: the catalog's entity argument names for the entity type, otherwise id-like arguments on the same upstream whose name contains the entity type (for example `contact_id` for a contact). Checking only these, not every tool on the upstream, keeps most creates stageable.

`pause` a create instead of staging it when its placeholder cannot fit a consuming argument:
- the id type is unknown and a consuming argument is integer-typed or uuid-formatted, or
- the id type is integer and a consuming argument's schema sets `minimum` or `exclusiveMinimum` to zero or more, so a negative placeholder would be rejected.

Later calls whose arguments contain a placeholder are journaled as-is. At commit, after the creating call runs, extract the real id (catalog `id_path`, else first top-level key matching `^id$|Id$|_id$` in structured or JSON-parsed output, when that output is an object; `structuredContent` may be any JSON value, so for an array or a scalar only `id_path` applies) and substitute it in every dependent call:
- String and uuid placeholders are replaced anywhere, including inside longer strings such as a link in an email body. A freshly minted UUID makes accidental matches negligible, and leaving one unsubstituted would send an id that looks real but is not.
- Integer placeholders are replaced only inside id-like argument fields. If one also appears anywhere else (free text, URLs), set `placeholder_in_text` and flag that write in review: that occurrence will be sent unchanged.

If the id cannot be found, pause the commit and ask the reviewer to supply it.

### 5.4a Native staging

Where the target system has a form that is not yet live, the hold is placed there instead of in the journal. The guarantee is the one in 5.4: nothing the agent asked for goes live until a person decides. What changes is where the held thing waits, who validates it, and what the reviewer can look at.

**Why it is preferred where it exists.**
- The target validates the write at session time: recipients, permissions, schema, quota. Most commit-time failures move into the session, where the agent can still react.
- The reviewer sees the real thing in the real tool: the draft in the mailbox with its attachments rendered, the pull request with its diff and its checks, the uncaptured payment in the Stripe dashboard. The review page links to it where the catalog can build a URL.
- Some ids are real from the start (a PaymentIntent, a draft invoice and a pull request keep their id through promotion), so dependents need no placeholder.
- A person can finish the work in the target's own UI, and the proxy still knows.

**Through MCP only.** Every step below is a `tools/call` on the same upstream; the catalog names the tools (section 6, `stage_via`). The proxy never talks to a vendor API of its own: it has no credential for one (section 2, token passthrough), and the dependency list stays at four. An upstream whose MCP server does not expose a mechanism's promote, withdraw and read-back tools has no native stage, and the journal holds the call. Which tools a server exposes is checked per server in M0 (question 15): GitHub's REST API cannot mark a draft pull request ready, its MCP server can.

**Three cases.** For a tool whose `tool_policy.stage` is `native`:
1. *Rewrite.* The agent calls the live tool (`send_message`). The proxy journals the call with `stage_kind: native`, `native_state: staging` and a placeholder as in 5.4, mints the `idempotency_key`, then forwards the mapped `create` call (`create_draft`, with the live call's arguments mapped onto it). That is a normal forwarded call: MRTR passes through to the agent (5.1), tasks per 5.1. On success it persists `native_ref_json` (`{upstream, kind, id, url}`), `native_state: staged` and `stage_expires_at` where the mechanism has one. On an error it returns the upstream's error to the agent as the tool result and the journal entry ends `failed` with that message: the target refused the write, and the agent should know now, not at commit. It never falls back to the journal on an error, because the agent would then believe a write the target already refused. The agent need not know any of this. This is the default.
2. *Stage tool called directly.* The agent calls `create_draft` itself (it is listed, 5.1). The call is forwarded, its real result returned, and it is journaled as a native stage in state `staged`. Under `expose: draft_only` this is the only way in, because the live tool is not listed: the agent knows it is drafting. Use that exposure for agents whose task is to prepare rather than to act, and for tools whose `outputSchema` requires a real id (5.1).
3. *Live tool on an existing staged form.* The agent calls `send_message` with a `draftId` the session staged. Nothing is created: the write is journaled as a native stage of that form, and the ordinary review decides whether it is sent.

All three end in the same review, and commit promotes them the same way.

**Provisional result.** Text only, as in 5.4, plus one sentence that names the staged form: "Held as Gmail draft `r-1234`; it will be sent after a person approves this session." Where `id_stable` is true the agent gets the real id in place of the placeholder. Where it is false the placeholder stays and 5.4's substitution runs after promotion. Never copy fields of the staged form into the result as if they were the result of the requested action: an authorization's status is not a charge's status. In the overlay (5.5) the note names the staged form instead of the placeholder.

**Side-effect classes.** A staged form is not nothing. The catalog classes each mechanism by what it does in the world, and the class decides whether it may be a hold at all:
- `inert`: visible only to the owning account, no notification, no money moves. Gmail and Graph drafts, Stripe draft invoices. Stages by default.
- `visible`: others can see it and automation may run on it. A branch and draft pull request: collaborators see it, and workflows run on `opened` and `synchronize` unless the repository's workflows exclude drafts. Stages by default; the setup page says so.
- `consequential`: something happens to a third party. An uncaptured PaymentIntent reserves the customer's funds and may show on their statement. Off by default; a person turns it on per tool, and the review page shows the expiry.
- `fused`: goes live by itself at a deadline. Slack and Twilio scheduled messages, Stripe `automatic_delayed` capture. Never a hold. Usable only as LOG's undo window (5.9).

**Expiry.** `stage_expires_at` is set from the mechanism (a Stripe charge's `capture_before`; none for a draft). The review page counts down, and the notifier fires again `expiry_warning` (default 24 h) before it (5.12). A stage past its expiry is `expired` and cannot be promoted: its dependents become `skipped` (`failed_dependency`), and the page offers "re-run at commit", which re-issues the original call through the journal on the reviewer's explicit click. Nothing re-issues by itself.

**Promotion, at commit.** In 5.8's order, a native stage is promoted where a journal hold is executed:
1. Read the staged form back with the `read_back` tool and hash it as in section 4. If it differs from what was staged, set `edited_natively`, show the difference (the agent's version → what is there) and require the reviewer's confirmation; what is there is what gets promoted. If the read-back says not found, the form was withdrawn or promoted outside the proxy: mark `unknown` and say so. A Gmail draft disappears when it is sent, so absence alone does not say which.
2. Persist `promoting`, then call the `promote` tool with the staged id as an ordinary argument, with the `idempotency_key` where the tool accepts one. A promote that times out or is cancelled after it was sent is `unknown`, exactly as in 5.8 step 4.
3. Persist `promoted` with the real id: from the promote result where the mechanism returns one (`drafts.send` returns the sent message), from read-back where it returns nothing (Graph's send answers `202 Accepted` with no body), or the staged id itself where `id_stable` is true. Substitute into dependents as in 5.4.

The unresolved-placeholder guard (5.8) runs on the promote call's arguments and on the read-back content, so a draft that still quotes a placeholder is never sent.

**Discard and withdrawal.** For a native stage, discard is not "nothing was ever sent": the staged form exists and is withdrawn (`delete_draft`; close the pull request and delete the branch; cancel the PaymentIntent; delete the draft invoice). Persist `withdrawing` before the call and `withdrawn` after. A withdrawal that fails leaves the write `unknown` with the error, listed on the session page until a person marks it resolved. Never silent: an orphaned draft is a write waiting to be sent by mistake. The cascade is unchanged: dependents are `skipped`.

**Leave.** A fourth verdict, for native stages only: leave the staged form where it is and stop tracking it (`native_state: left`). The draft stays in Drafts for a person to finish; the pull request stays open. It counts as a discard for the scorecard (the agent's version was not good enough to send) and is audited.

**Edit.** Editing a native stage's arguments (5.7) re-stages: through the mechanism's `update` tool where it has one (Gmail `update_draft`), else withdraw and create again. The original is kept, as for a journal hold.

**Promoted by hand.** A reviewer may promote in the target's own UI, clicking Send in the mailbox or merging the pull request, instead of on the review page. At the next commit, or on "check now", read-back tells: the form is gone or already promoted. The page asks the reviewer to confirm what happened and marks the write `promoted` (with the real id where read-back can find it, such as the sent message under `SENT`) or `withdrawn`. The proxy never guesses.

**Orphans.** A crash between the `create` call and its persistence leaves a staged form the journal does not know by id. On restart every write still `staging` is listed as a possible orphan, beside the `list` tool's output for that upstream over the session's window, for a person to match or delete. Where the mechanism can carry a marker (a pull request body, Stripe `metadata`) the create call includes the write id, so those match themselves; an email draft carries none through MCP tools and stays a manual match.

**What does not change.** The decision order (5.3), `result_matters` and `confirms_upstream`, the conflict check, dependency ordering, the unresolved-placeholder guard, crash safety (`promoting` and `withdrawing` persisted before the upstream call), `unknown` semantics, and the learning loop, except that `edited_natively` counts as `edited` and envelopes are built from what was promoted (5.10).

**Where it is not available.** A tool without `stage_via`, an upstream that lacks one of the mechanism's tools, a class the team has not enabled, or a `fused` mechanism: the journal holds the call, as in 5.4. The journal is the floor; native is the preference.

### 5.5 Read overlay

- From each held write, collect **entity keys**: values of argument fields whose name looks like an id, plus the placeholder.
- When any later read result contains one of those keys, append one extra text block:

  > [review-layer note] This session has uncommitted changes to data in this result: • deal 123: stage "Qualified" → "Closed Won" (held_…)

- After a held **create**, the new record will not appear in list or search results, and the agent may create it again. So any later read against the same upstream also gets a short note listing that session's held creates, even when no key matches.
- A native stage is partly visible to reads on its own: a list of drafts shows the draft, a search of sent mail does not. The note names the staged form ("held as Gmail draft `r-1234`") instead of the placeholder, and the held-creates note after a native create still applies.
- Never modify `structuredContent`.

### 5.6 Prior values

Order of attempts: (1) the most recent read result in this session containing the entity key; (2) a catalog mapping from write tool to read tool plus argument mapping, executed live; (3) none, and the UI says "prior value unknown". Store as `prior_json`.

### 5.7 Review UI

Pages: sessions list; session review; setup (tools and postures); agent settings; scorecard; weekly statement; audit log.

Session review shows held writes grouped by system, each as old → new with arguments expandable, plus the agent's surrounding calls for context. A native stage also shows its class, a link to open it in the target where the catalog can build one, the countdown to `stage_expires_at`, and, after read-back, the difference between the agent's version and what is there (5.4a). Actions: commit all, discard all, per-write discard (it cascades to every write that depends on it, transitively, and the page shows the cascade before the person confirms), edit arguments (validated against the tool's input schema; original kept; `depends_on` edges are recomputed from the edited arguments), leave (native stages only: keep the draft, stop tracking it, 5.4a), reason tag (`wrong record | wrong value | wrong recipient | should not have acted | other`) and optional note.

Flag likely duplicates: the same tool with the same normalized arguments more than once in a session (`duplicate_of`). Show them collapsed together with a warning.

Flag writes where an integer placeholder appears outside an id-like field (`placeholder_in_text`), showing where it will be sent unchanged.

A write in `unknown` offers two actions (5.8): **check now**, which runs the catalog's prior-value read and shows the current value beside the intended one, and, only when the tool has an `idempotency_arg`, **retry safely**. After checking, the reviewer marks the write executed or failed by hand.

Track `review_seconds` and which groups were expanded. This feeds the rubber-stamp guard in 5.10.

The session page also lists the session's failed withdrawals and possible orphans (5.4a) until a person resolves each one.

Auth: single admin password, session cookie (`HttpOnly`, `SameSite=Strict`, `Secure` when served over TLS), CSRF token on every POST, sent as a header on htmx requests; test that a POST without it fails. The UI has its own listener, bound to 127.0.0.1 unless configured otherwise (section 4). Render every agent-, upstream- and reviewer-supplied string through `html/template` escaping only.

### 5.8 Commit engine

State machine per held write: `pending → executing → executed | failed`, plus `needs_input`, `skipped` and `unknown`. A native stage runs `staged → promoting → promoted` in place of `pending → executing → executed`, and `withdrawing → withdrawn` on discard, with `expired` and `left` as terminal states (5.4a).

1. **Claim.** Move the session from `awaiting_review` to `committing` with a compare-and-swap in one transaction. A second commit, from another tab or another person, gets a 409.
2. **Conflict check.** Re-run every `read_dep` that shares an entity key with a held write. Compare hashes after removing catalog-listed volatile fields. On mismatch show the diff; the reviewer may commit anyway.
3. **Order.** Dependencies first. Build a graph from the `depends_on` edges and run it in topological order, so a call never runs before the call that creates its id. Among calls that are ready, run the ones not flagged `irreversible` first; an `irreversible` call runs as late as its dependents allow. Journal order breaks ties. A cycle is a bug: refuse to commit.
4. **Execute.** Before each upstream call, persist `executing`. After it, persist `executed` with the real id, or `failed` with the error. A call that times out or is cancelled after it was sent becomes `unknown`, not `failed`: since v1.8 the SDK returns at once and sends the cancel notification asynchronously, so the write may still land. Use `failed` only when the error shows the request never reached the upstream or the upstream rejected it. Right before sending, scan the final arguments for any placeholder minted in this session (string and uuid placeholders anywhere, integer placeholders in id-like fields). If one is left, do not send: the write is `failed` with "unresolved placeholder". If the tool's catalog entry names an `idempotency_arg`, put the write's `idempotency_key` in it on every attempt and count `attempts`. Stop on the first `failed` or `unknown`; the session becomes `partial`. When a create ends `failed` or `skipped`, everything that depends on it becomes `skipped` (`failed_dependency`); when it ends `unknown`, its dependents wait until a person resolves it.
5. **Tasks (M2d).** Before M2d, commit calls do not declare the extension, and a `-32021` answer fails the write with "this tool needs the tasks extension, which this build does not support yet". From M2d on, commit calls declare the tasks extension, so tools that require tasks still work. If the upstream answers with a task, persist its id in `upstream_task_id` before polling, then poll `tasks/get` at the server's `pollIntervalMs` until `completed`, `failed` or `cancelled`. If polling times out, send `tasks/cancel` and mark the write `unknown`.
6. **Resume.** Never re-run `executed`. On daemon restart, a write still `executing` with a stored `upstream_task_id` resumes polling. Any other write still `executing` becomes `unknown`, and the UI tells the reviewer to check the target system by hand. Do not guess.
7. **Upstream prompts.** MRTR: if an upstream answers with `input_required`, set the write to `needs_input` and persist its `inputRequests` and opaque `requestState`. Show the questions to the reviewer, then retry the call with `inputResponses` and the same `requestState`, unchanged. Tasks: if a task reaches `input_required`, show its requests the same way and answer through `tasks/update`. Legacy upstreams ask through a server-initiated `elicitation/create` while the call is still open: the commit client declares elicitation to them, and its handler sets `needs_input`, persists the request and blocks until the reviewer answers or `prompt_timeout` (default 10 min) passes. On timeout answer `cancel`; the write becomes `unknown` unless the upstream then returns an error. A daemon restart while a legacy call is parked also leaves it `unknown`. Support confirmation, enum and short-text forms. Any other request type, or a rejected retry, fails that write with the upstream's message.
8. Discard = mark every journal hold `skipped`: nothing was ever sent. Every native stage is withdrawn (5.4a); a withdrawal that fails is `unknown`, listed, never silent.
9. **Resolving `unknown`.** Never automatic. With an `idempotency_arg`, the reviewer may retry with the same key. Without one, "check now" runs the catalog's prior-value read (5.6) and shows the current value beside the intended one; the reviewer then marks the write executed or failed, and the engine carries on from there.
10. **Native stages.** Read back, then promote, in the order above; the real id comes from the promote result, from read-back, or is the staged id (5.4a). A write past `stage_expires_at` is `expired` and is never promoted.

Wording in the UI and docs: "ordered and resumable", never "atomic".

### 5.9 LOG posture

Forward immediately, store prior value and result. Offer undo only when a true inverse exists: a field update with a stored prior value, or a create whose catalog entry names a delete tool. Label it "best effort": notifications already fired will not unwind. A `fused` mechanism (5.4a) may back the undo: a message the team allows under LOG can be scheduled `undo_window` ahead through the upstream's scheduling tool, and undo deletes it, allowed until the mechanism's cut-off (60 s before posting on Slack). Off by default, per tool. It is an undo window, never a hold: if nobody acts, it goes out.

### 5.10 Trust ladder and envelope

Scorecard per agent and tool: reviewed, committed, discarded, edited, sessions, attentive reviews.

**Promotion proposal** (defaults, all configurable): at least 20 reviewed writes across at least 5 sessions; discard plus edit rate at most 5%; only attentive reviews count. A review is attentive if the session page was open at least `max(10s, 2s × held writes)` and the tool's group was expanded. HOLD tools are never proposed. A person accepts with one click; the tool moves to LOG with envelope enforcement on.

**Envelope**, built from committed writes only (for a native stage, from the read-back that was promoted, not from the agent's arguments; an `edited_natively` write counts as `edited` in the scorecard), per argument path to depth 3: numeric → min and max with 10% padding; low-cardinality strings (≤ 20 values) → allowed set; email-like → domain set; arrays → max length; plus writes per session (max × 1.5). A call outside it is staged with a plain reason, e.g. `amount 5400 > max 1200`.

**Automatic demotion** back to STAGE when: the tool's hash changes (it covers the description and annotations as well as the schemas, section 4); the agent's `version_label` changes (set in config or sent as `X-Agent-Version`; the proxy cannot see prompt or model changes on its own, so document this); envelope breaches exceed a threshold; or a person flags an incident.

Counts and thresholds only. No model in this loop.

### 5.11 Feedback

- Store every correction pair: original args, edited args, reason tag, note.
- Export as JSONL (`pakka export feedback`).
- Standing rules: cluster repeated reasons into a proposed `rule`; a person activates it; active rules are appended to that tool's description in `tools/list` under a marked heading. Rules are versioned and retirable. Rule text ends up in the agent's prompt, so it is plain text written or approved by a person, capped (default 300 characters per rule, 5 active rules per tool) and never copied verbatim from agent arguments or upstream results. Every description change invalidates clients' cached tool lists and prompt caches, so rule changes go out in **batches**: an explicit "publish rules" action, at most once a day. A session keeps the `rule_version` it started with; its `tools/list` requests carry the session key so they get that version (5.1). Show "discards for this reason, before vs after".
- Returning a rejection reason to the agent inside the same session only works if the session is still open. Treat that as a later feature.

### 5.12 Notifications and weekly statement

Slack incoming webhook and a generic webhook for "session awaiting review", fired again `expiry_warning` (default 24 h) before the earliest `stage_expires_at` in a session awaiting review (5.4a). Weekly statement page per agent: sessions, writes by system and posture, held/committed/discarded, envelope breaches, most-changed fields, each against the trial baseline. Optional Slack summary.

### 5.13 Security

Authenticate first: a request without a valid agent key never reaches routing or an upstream (an MCP middleware that forwarded unauthenticated Streamable HTTP requests downstream was reported as CVE-2026-48039 *(secondary: [write-up](https://ssojet.com/blog/mcp-authentication-vulnerabilities); check NVD)*). Secrets encrypted at rest with a key from `PAKKA_SECRET_KEY`; refuse to store secrets without it; each ciphertext carries a key id, so the key can be rotated later, and a fresh random nonce. Agent keys hashed (section 3). Run ids and session keys are identifiers, never credentials. Redact argument fields matching `password|secret|token|api_?key` in UI and logs. Size caps and timeouts everywhere, set to our own constants. Configure `CrossOriginProtection` explicitly; keep the SDK's localhost DNS-rebinding protection on. Mark every cacheable result `cacheScope: private` (`server/discover`, the four lists, `resources/read`); the SDK default is `public`. Upstream OAuth credentials are stored per issuer and never reused across issuers. Everything an agent, an upstream or a reviewer typed is untrusted text in the UI: `html/template` escaping only, never `template.HTML`. Never set `MCPGODEBUG`. No telemetry. Append-only audit table, enforced by triggers, for every verdict, posture change and rule change. A staged form is real data in a real system: the upstream credential must be able to create, read back and withdraw it, and a send-only credential cannot draft (Gmail's `gmail.send` is "Send email on your behalf"; the narrowest scope that both drafts and sends is `gmail.compose`, "Manage drafts and send emails", which Google marks Restricted). Markers written into staged forms (a write id in a pull request body or in Stripe `metadata`) are identifiers, never secrets. A failed withdrawal is listed until resolved, never dropped (5.4a).

---

## 6. Catalog

Embedded YAML, overridable per deployment. Per upstream kind and tool name pattern: default posture, `irreversible`, `result_matters`, `confirms_upstream`, `id_path`, `id_type`, `entity_type`, entity argument names, prior-value read mapping, volatile fields, recipient path, inverse tool, `idempotency_arg` (the argument that carries an idempotency key, where the upstream supports one). Ship generic heuristics plus hand-written entries for the two dogfood systems. Everything else is learned from the team's choices.

Native staging is a catalog fact about a pair of tools on one upstream, per upstream kind and tool name pattern:

```yaml
stage_via:
  create:    [{tool, args}]      # one or more calls that make the staged form; args maps the live call's arguments, later calls may use earlier results
  update:    {tool, args}        # optional: edit in place; otherwise withdraw and create again
  promote:   {tool, args}        # takes the staged id as an ordinary argument
  withdraw:  [{tool, args}]
  read_back: {tool, args}
  list:      {tool, args}        # for orphan matching
  id_stable: true | false        # does the promoted object keep the staged id
  id_path:   ...                 # where the real id is in the promote result, when it is not stable
  class:     inert | visible | consequential | fused
  expires:   {field | duration | none}
  marker:    arg                 # optional: where the write id can be written into the staged form
expose: live | draft_only
```

Shipped entries: Gmail (`send_message` → `create_draft`; promote `send_message(draftId)`; withdraw `delete_draft`; `id_stable: false`; `inert`), Microsoft Graph mail (the same shape), GitHub (a write to the default branch → a branch, the same write there, and a draft pull request; promote = ready for review, or merge when the team says so; withdraw = close and delete the branch; `visible`), Stripe PaymentIntent (charge → `capture_method: manual`; promote = capture; withdraw = cancel; expires from `capture_before`; `consequential`, off by default), Stripe invoices (finalize → draft; promote = finalize; withdraw = delete; `inert`). Examples with their facts checked but not shipped: Shopify draft orders (`id_stable: false`). Marked `fused` and never stages: Slack and Twilio scheduled messages, Stripe `automatic_delayed`. Tool names are the MCP server's, not the vendor's, so every entry is confirmed against the server the team runs (question 15).

---

## 7. Milestones

**M0 — Skeleton and spike (S).** Repo, Makefile, CI, pinned deps, migrations. Spike: aggregated endpoint in front of one stdio upstream. Write `docs/adr/0001-sdk-findings.md` answering:
1. Stateless or stateful endpoint? Default is stateless with our own session keys. Say why we diverge from GitHub's gateway, which is stateful. Check whether one Go endpoint can serve both protocol generations well, or whether a stateful endpoint that lets new clients negotiate down is simpler. Since v1.8 a stateful handler answers a 2026-07-28 request with a JSON-RPC error, so new clients can renegotiate down instead of dropping the connection. But see the discovery trap in section 2: a stateful handler that still answers `server/discover` strands modern clients, so a stateful choice must also set `SupportedProtocolVersions`.
2. How do we register pass-through tools without the SDK re-validating upstream schemas?
3. How do we stop the SDK's client-side MRTR middleware from answering `input_required` on upstream clients, so the prompt reaches the agent (forwarded calls) or the reviewer (commit), with `requestState` intact?
4. `CommandTransport` has no frame-size cap in v1.8.0 (section 2). Confirm in the pinned source, then decide how we bound the child's stdout (a size-limited reader between the pipe and the transport?).
5. Tasks. Confirm in the pinned source that there is still no typed Tasks API (section 2). If so: can `tasks/get`, `tasks/update` and `tasks/cancel` be served and sent as custom methods on both sides? Can a `tools/call` result carry `resultType: "task"` through the typed `CallToolResult` on both sides? Can an upstream client mirror the agent's declared capabilities (tasks, elicitation) request by request? Estimate M2d from the answers. The method set itself is confirmed.
6. Does `SetCacheable` let us set `private` and a TTL per agent and per rule version, for all six cacheable results (`server/discover`, the four lists, `resources/read`)?
7. How does the SDK surface a timed-out or cancelled call? Can we tell "never sent" from "sent, no answer", so only the second becomes `unknown`?
8. Do our target clients cope with a tool that has no `outputSchema` but whose upstream sometimes returns `structuredContent`?
9. Which SDK behaviours do we depend on, and what canary test guards each?
10. Legacy agent on a stateless endpoint: can the SDK deliver anything server-initiated to it, and what does its server-side MRTR shim do there? This settles the legacy-agent row of the matrix in 5.1.
11. Legacy upstreams at commit: can the client-side elicitation handler block for minutes while a reviewer answers? Which timeout applies to the parked call?
12. Does a stateless SDK endpoint serve `subscriptions/listen` to agents? (v1.8.0 made the SDK client tolerate a 404 from it in stateless mode.) If agents cannot subscribe, `ttlMs` alone bounds how long an agent keeps a stale list: choose it on purpose and write it down.
13. Does an argument marked `x-mcp-header` round-trip: agent → proxy (`Mcp-Param-*` checked against the body) → upstream (re-emitted by the client)? Does upstream progress reach the agent on a forwarded call?
14. Does the SDK's JSON Schema package validate 2020-12, and can we call it for edited arguments without a new dependency?
15. Native staging per dogfood upstream: which of its MCP server's tools create, update, read back, list, promote and withdraw the staged form, does the promote tool take the staged id as an ordinary argument, and does the server's credential have a scope that drafts (5.13)? REST docs do not settle this: GitHub's REST API cannot mark a draft ready, its MCP server can. Record `id_stable` and the side-effect class per mechanism (5.4a).
*Accept:* a legacy client and a 2026-07-28 client can both list and call tools through the proxy, against a fake upstream in each generation; `server/discover` answers with merged capabilities; a request without a valid agent key never reaches the upstream; the ADR is written and reviewed, including an estimate for M2d and the per-upstream tool pairs from question 15.

**M1 — Observe mode and census (M).** Agents, keys, upstreams (stdio, and HTTP with static headers), sessions (5.2), call log, classifier with `would_posture`, sessions list and session report pages, `pakka report`, `server/discover`, the pass-through benchmark.
*Accept:* against two fake upstreams, a scripted run shows one session spanning both, every call classified, and the report prints share of sessions writing to ≥ 2 systems and share of writes with no undo; every cacheable result carries `cacheScope: private`; a fake tool that cannot work without tasks surfaces `-32021` to the agent, and no agent ever receives a task; the pass-through benchmark number is recorded; the report also prints the share of writes whose tool has a native stage in the catalog.

**M2a — Hold, review, commit for independent writes (M).** Hold mode with required session keys, journal, text-only provisional results, review page with commit/discard/edit and reason tags, commit engine with crash safety and resume, notifier.
*Accept:* scenario "update deal → send email" is fully held; fake upstreams show zero effects before commit and exactly one of each after; a hold-mode request without a session key is rejected with a helpful error; two parallel runs of one agent produce two sessions; killing the daemon mid-commit yields `unknown`, never a double send; a write that times out during commit becomes `unknown`, not `failed`; a second commit on the same session gets a 409; a write that arrives after review has started is rejected with a helpful error, and one that arrives after an idle close nobody has opened reopens the session; an `unknown` write on a tool with an `idempotency_arg` is retried and lands exactly once.

**M2b — Dependent writes and read coherence (M).** Typed placeholders, consuming-argument checks, `depends_on` graph and dependency-first ordering, id substitution, both read-overlay rules, prior values from session reads, duplicate and placeholder-in-text flags, discard cascade, the unresolved-placeholder guard.
*Accept:* scenario "create contact → update deal → send email" commits with real ids on a fake CRM that uses integer ids for one object and uuids for another; a uuid placeholder inside the email body is replaced with the real id; an integer placeholder in free text is flagged; a create whose consuming argument has `minimum: 1` and an integer id is paused, not staged; a property test shows no call ever runs before the call that creates its id, with irreversible calls as late as dependencies allow; a list call after a held create carries the held-creates note; a repeated identical create is flagged; discarding the create cascades to the update and the email, and the page shows that before the person confirms; no test run ever shows a placeholder in an upstream's effects log; an array-valued `structuredContent` does not break id extraction.

**M2c — Upstream prompts at commit (M).** Reviewer answers to `input_required` at commit (MRTR), the same through elicitation for legacy upstreams, `prompt_timeout`, and the legacy-agent rule from the matrix in 5.1.
*Accept:* a tool that asks for confirmation upstream commits after the reviewer answers, and its retry carries the original `requestState`; the same scenario passes against the fake running as a legacy upstream; a parked legacy prompt that times out never ends `executed`; a legacy agent whose forwarded write draws `input_required` gets a provisional result in hold mode and a clear tool error in observe mode.

**M2e — Native staging (M; after M2b, independent of M2c and M2d).** `stage_via` in the catalog, the three cases, side-effect classes, provisional results that name the staged form, read-back, promote, withdraw, `leave`, expiry, orphans, `draft_only` exposure, and the Gmail, Graph, GitHub and Stripe entries against the fakes.
*Accept:* scenario "send two emails, the second quoting the first's id" against `fakemail`: both sends become drafts; the effects log shows two staged drafts and no live send before commit and exactly two sends after, in dependency order, with the first's sent message id (not its draft id) substituted into the second; each provisional result names its draft id; discard deletes both drafts and no send ever appears; a draft edited out of band shows as a difference and the edited body is what is sent; a stage past the fake's expiry never promotes and its dependents are skipped; a failed `delete_draft` ends `unknown` and is listed on the session page; killing the daemon between the draft's creation and its journaling lists an orphan on restart; under `draft_only`, `send_email` is absent from `tools/list`, `create_draft` returns its real result with its `outputSchema` intact, and the drafts are still sent on commit; `send_email` with a `draftId` the session staged creates nothing and is reviewed as that draft; on `fakepay` a `consequential` mechanism is not used until a person enables it, and once enabled the page shows the expiry; a `fused` mechanism is never used as a stage; a draft whose read-back still contains a placeholder is never sent; `leave` sends nothing and deletes nothing; enabling `draft_only` changes `tools/list` once, on publish; a `result_matters` tool is still never staged.

**M2d — Tasks (L, gated by ADR-0001; may ship after M5).** Build only what M0 question 5 showed is needed: serve and send `tasks/get`, `tasks/update` and `tasks/cancel`, carry `resultType: "task"` results on both sides, `task_route`, per-request mirroring of the agent's declaration, tasks at commit with persisted ids and resume (5.1, 5.8). Advertise the extension in `server/discover` only now.
*Accept:* an agent that declares tasks can poll a forwarded task through the proxy, and an agent that does not never receives one; a task paused in `input_required` is answered by the reviewer through `tasks/update`; killing the daemon while a committed call is running as a task resumes polling on restart; if polling times out the write is `unknown`.

**M3 — Postures, limits, setup flow (M).** Catalog, decision order, condition rules, hard-hold list, `result_matters` handling, setup page, LOG with best-effort undo.
*Accept:* table-driven tests cover every branch of the decision order.

**M4 — Scorecard and ladder (M).** Stats, attentive-review guard, promotion proposals, automatic demotion on schema or version change.
*Accept:* simulated history produces a proposal; a three-second review does not count; a schema change demotes, and so does a description-only change; promotion or demotion never changes `tools/list`.

**M5 — Envelope and weekly statement (M).**
*Accept:* a released tool forwards an in-envelope call and stages an out-of-envelope one with a readable reason.

**M6 — Feedback (S).** Reason tags, correction pairs, JSONL export, versioned rules injected into descriptions and published in batches.
*Accept:* activating three rules changes `tools/list` once, on publish; an open session keeps its rule version.

**M7 — Remote OAuth upstreams and packaging (L).** Proxy as OAuth client using the SDK's client-side support; token storage and refresh; Docker image with `pakka health` as its `HEALTHCHECK`; `pakka stdio`; quickstart docs. Then dogfood against two real systems.
Registration order, following the spec: (1) **static pre-registered client credentials**, entered in the UI and bound to the issuer. This is the default for a self-hosted proxy. (2) Client ID Metadata Documents, only when the deployment has a public https URL with a path to host the document. (3) Dynamic Client Registration as a deprecated fallback. Write a short ADR before building. Note for later: if agents ever register with the proxy dynamically, the spec requires the proxy to get user consent per registered client before forwarding to a third-party authorization server.
Lean on the SDK for issuer validation (it ships an issuer mix-up mitigation since v1.7.0) and key stored credentials by issuer. Canary: an authorization response with a mismatched `iss` never reaches the token endpoint.

---

## 8. Testing

- `internal/fake/fakecrm` and `internal/fake/fakemail`: real MCP servers built on the SDK with in-memory state and an effects log, so tests can assert "nothing landed" and "exactly once".
  - `fakecrm` uses integer ids for one object type and uuids for another, and one id argument sets `minimum: 1`.
  - One tool declares an `outputSchema`.
  - One tool returns an MRTR `input_required` asking for confirmation and rejects a retry whose `requestState` differs from the one it sent.
  - One tool answers with a task when the client declares the extension; the task can pause in `input_required` and honours `tasks/cancel`.
  - One tool can hang past the call timeout and then apply its effect anyway.
  - Both fakes can emit a tool-list change.
  - Both fakes run in either protocol generation: 2026-07-28, or legacy 2025-11-25, where the confirmation tool asks through `elicitation/create` instead of MRTR.
  - One tool accepts an idempotency key and dedupes on it.
  - One tool cannot answer without the tasks extension and returns `-32021`.
  - One tool returns an array as `structuredContent`.
  - One tool's description can change while its schemas stay the same.
  - One tool marks an argument `x-mcp-header`.
  - `fakemail` has `send_email`, `create_draft`, `update_draft`, `get_draft`, `list_drafts`, `delete_draft`, and `send_email` accepts a `draft_id`; sending a draft deletes it and returns a message with a new id, as Gmail does. Test hooks edit a draft out of band and make `delete_draft` fail once.
  - `internal/fake/fakepay`: `authorize` (manual capture), `capture`, `cancel` and `read`, with a fake clock for `capture_before`, and an `automatic_delayed` flag the catalog marks `fused`.
  - `fakecrm` has no native stage, so it exercises the journal path.
  - Effects logs distinguish `staged` effects from `live` ones: "nothing landed" means no live effect, and tests count the staged ones.
- Scenario tests are table-driven and run the daemon in-process.
- Protocol matrix: every scenario runs with a legacy client and a 2026-07-28 client, against fakes in both generations (2×2).
- Crash test for the commit engine, including a crash while a task is being polled and one between a native stage's creation and its journaling. Property test for commit ordering. Fuzz test for placeholder substitution, including integer and uuid placeholders inside longer strings. A test that no placeholder ever leaves the proxy. Always `-race`. CI fails if `MCPGODEBUG` is set.
- Canary tests for every SDK behaviour we lean on. At least: schemas pass through unvalidated and unrewritten; the client-side MRTR middleware stays out of the way; all six cacheable results come out `private`; a cancelled call returns at once; an `x-mcp-header` argument round-trips; the stateless endpoint ignores `Mcp-Session-Id`; a staged id round-trips as an ordinary argument on the promote call.

---

## 9. Repo layout

```
cmd/pakka/            main, subcommands
internal/agentep/     agent-facing MCP endpoint
internal/upstream/    upstream clients, tool registry, task routing
internal/policy/      classifier, postures, rules, envelope check
internal/journal/     holds, placeholders, overlay, prior values, native stages (5.4a)
internal/commit/      commit engine: execute, promote, withdraw
internal/learn/       scorecard, promotion, envelope builder, demotion
internal/feedback/    pairs, rules, export
internal/ui/          handlers, templates, static (embedded)
internal/store/       SQLite, migrations, queries
internal/notify/      Slack, webhook
internal/catalog/     embedded YAML + loader
internal/fake/        fake upstreams for tests
docs/adr/
```

Make targets: `make dev`, `make test`, `make check` (vet, staticcheck, govulncheck, test -race), `make bench`, `make build`, `make docker`.

---

## 10. CLAUDE.md starter

```
# Project rules
- Read BUILD_PLAN.md before any task. Work only on the current milestone.
- MCP and go-sdk changed heavily in July 2026. Check the pinned SDK source and docs/ in the module cache before writing protocol code. Do not rely on memory.
- No new dependencies without asking.
- Go 1.27.x. IDs come from the standard-library uuid package. YAML is go.yaml.in/yaml/v3, never gopkg.in/yaml.v3.
- htmx is 2.0.x, vendored. Use only htmx 2 attributes and events; the htmx website now documents 4.x.
- Never set MCPGODEBUG.
- Run `make check` before reporting a task done. Tests must pass with -race.
- Never forward an agent's Authorization header upstream. Never log secrets.
- Check the agent key before anything else. Nothing unauthenticated reaches routing or an upstream.
- Text from agents, upstreams and reviewers is untrusted in the UI: html/template escaping only, never template.HTML.
- Provisional results are text only. Never invent field values.
- Prefer a native stage when the catalog has one. It is still a hold: nothing the agent asked for goes live until a person decides. The journal is the floor.
- Native staging uses the upstream's own tools over MCP. Never call a vendor API directly.
- Only `inert` and `visible` mechanisms stage by default; `consequential` needs a person's opt-in per tool; `fused` (scheduled sends, automatic capture) is never a hold.
- Read a staged form back before promoting it. Promote what is there, show the difference.
- Discard withdraws native stages. A failed withdrawal is `unknown` and listed, never silent.
- The staged form's result is not the requested action's result. Never present one as the other.
- Hash full payloads before truncating them.
- Every cacheable result (server/discover, the four lists, resources/read) is cacheScope private. tools/list changes only on a rules publish or a real upstream change.
- Echo MRTR requestState verbatim. Never return a task to an agent that did not declare the tasks extension. Before M2d, declare the tasks extension nowhere.
- A write that was sent and then timed out or was cancelled is `unknown`, never `failed`.
- Never send a call that still contains a placeholder. Discarding a write skips everything that depends on it.
- SQLite runs with synchronous=FULL. Do not relax it.
- All timestamps UTC. Wrap errors with context. Every upstream call has a timeout.
- Table-driven tests. New mechanism = new scenario test against the fake upstreams.
- UI copy says "ordered and resumable", never "atomic".
- Unclear decision → short ADR in docs/adr/ and ask.

# Commands
make dev | make test | make check | make bench | make build
```

---

## 11. Questions for the human before M2a (7 and 9 are needed for M0)

1. Which two real systems will we dogfood on? That decides the two hand-written catalog entries.
2. Hold mode requires a run id in the MCP URL or a session header. Can our own agent and the first design partners set one? If any of them will use `pakka stdio`, does their host start a new process per run?
3. Holdable tools will not advertise an `outputSchema`, which costs the agent structured output on those tools. Acceptable?
4. Licence and final name.
5. htmx 2.0.x (the default here) or 4.0.x?
6. Does any dogfood tool run long enough to need tasks? If not, M2d ships after M5.
7. Which protocol revision do the two dogfood upstreams and our own agent speak today? That decides which cell of the 2×2 in 5.1 we harden first.
8. Does any write tool on the dogfood systems accept an idempotency key?
9. Which write tools on the dogfood systems have a native stage, and does each system's MCP server expose the promote, withdraw and read-back tools by id? For GitHub: is "ready for review" or "merge" the promote step?
10. Whose account do staged forms live in? A Gmail draft is created in the mailbox the upstream credential belongs to; a reviewer who is not that account can review it only on the proxy's page. Is a shared mailbox acceptable, or does each agent run on the reviewer's own credential?
11. May the proxy place `consequential` stages (a card authorization holds the customer's funds for up to 7 days) on any dogfood tool, or is that class off for the MVP?
12. Should `draft_only` be the default exposure for email agents, so the agent never sees a send tool, with the rewrite path kept for agents that must believe they sent?
