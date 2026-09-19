# Protocol notes: holding writes at an MCP proxy

Research notes for the product. Nothing here is in scope for the hackathon build; the demo calls the layer in-process.

## What MCP gives a proxy

The Model Context Protocol has three primitives a staging proxy cares about.

**Tools.** A server publishes `tools/list`: name, description, `inputSchema` (JSON Schema, object). A client calls `tools/call` with `name` and `arguments` and gets back `content` (text, image, resource) and `isError`. This is exactly the layer's view of the world: a name, a schema, an argument dict. `pydantic.create_model` from `inputSchema` gives the validation model the review page edits against, which is why `ToolSpec` in the demo already carries `args_schema` rather than a Python class.

**Tool annotations.** Servers may attach hints: `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`. They are hints, not guarantees, and the spec says clients must not rely on them for security. The proxy uses them the way the layer treats a tool it has never seen: `readOnlyHint: true` lets a tool start as a read; everything else is a write until a person says otherwise. A person's classification overrides the hint and is remembered.

**Resources and prompts** pass through untouched. Reads are never held.

## Where the proxy sits

```
agent (any MCP client) ──stdio / streamable HTTP──▶ pakka proxy ──▶ team's MCP servers
                                                        │
                                                   review UI · SQLite · OTel
```

The proxy is an MCP server to the agent and an MCP client to each server behind it. It aggregates `tools/list` (namespacing on collision), forwards reads, and intercepts writes: assign a placeholder, record dependencies, run the checks, return the held text as the tool result. The agent sees an ordinary successful `tools/call`.

Transport: streamable HTTP for hosted agents; stdio for a local agent that spawns the proxy, with the proxy spawning the servers. Both are in the current spec.

## The held result

The layer returns text only. A `tools/call` result with a single text content block, *HELD FOR REVIEW, not yet applied. Recorded as `ph_…`. Continue as if this step succeeded. Do not retry it.*, is well-formed for every client. Structured `structuredContent` with an `outputSchema` would let a strict client validate the result; the proxy cannot fill an output schema without inventing values, so it does not use it. This is a deliberate limit: a tool whose output schema *requires* a real id cannot be staged without a native draft adapter.

## Applying later

Approve forwards the original `tools/call` with placeholders substituted from the results of already-applied dependencies. The result's text is parsed for identifiers by shape (the same `shape_of` as the checks) so that dependents can be substituted; where a server returns `structuredContent`, ids come from there. A server that fails on apply marks the write failed; nothing downstream is sent.

## Reads after held writes

A held write changes nothing, so the agent's later reads do not see it. In the demo that is harmless, because the finance run is read-then-write. In general it is not: an agent that updates a record and reads it back will see the old value and may re-issue the update. Memory already holds the re-issue; the product overlays held writes on later reads of the same resource by id (Product plan, hours 18–24).

## Elicitation and sampling

Servers may ask the client for input (elicitation) or for a completion (sampling). The proxy forwards both unchanged; it never makes a model call of its own, in the product as in the demo.

## What the proxy must not do

- Not rely on annotations for safety. Unknown means write.
- Not invent field values. Provisional results are text.
- Not send anything with a placeholder in it.
- Not learn from its own passes. Only a person's decisions widen the envelope.
- Not read its own telemetry back to decide anything. SQLite is the source of truth; Logfire is the record.

## References

- Model Context Protocol specification, tools and tool annotations.
- Model Context Protocol specification, transports (stdio, streamable HTTP).
- Leike et al., *AI Safety Gridworlds*, 2017: the separation of the reward an agent optimises from the performance function that measures what was wanted; the absent-supervisor and safe-interruptibility environments.
- The Agentic Trust Framework: agents earn autonomy per capability; they do not get it by default.
