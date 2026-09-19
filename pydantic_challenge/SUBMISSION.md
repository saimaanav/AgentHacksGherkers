# Pydantic AI Gateway challenge — pakka's submission

> **"Change your agent's behavior without touching its code."**

**The framing sentence:** the gateway governs what the agent *thinks with*; pakka governs what it *does*.

Tom's accounts-payable agent (a Pydantic AI `Agent`, `pakka/agent.py`) runs behind pakka, a staging layer that holds every write and returns provisional text. Left to itself, a naive agent behind a staging layer does three wrong things: it retries held calls, it looks for another route to the same effect, and it reports *"Paid 4 vendors"* when nothing was paid. One rule in the gateway fixes all three, for every agent on the route, with no agent code changed.

This directory is the whole submission: the rule, the harness that produces the before/after, the guardrail spec and echo test, and the evidence.

**Status legend:** ✅ done and in this repo · ⏳ needs the gateway account (evidence to be pasted below when captured)

---

## Setup

| Step | Status | Where |
|---|---|---|
| Logfire account, Gateway created | ⏳ | logfire.pydantic.dev |
| Open-weight model deployed from Modal's library as an endpoint, added as a gateway route | ⏳ | route name: `_____` · model: `_____` · fallback if the library flow is missing: `modal deploy pydantic_challenge/modal_model.py` (vLLM, tool calling on) |
| `PAKKA_MODEL` points at the gateway route; every model call metered and traced | ✅ wiring in place | `.env`: `PAKKA_MODEL=gateway/openai:<model>`, `PAKKA_GATEWAY_ROUTE=<route>`, `PYDANTIC_AI_GATEWAY_API_KEY=…` |
| Optimizations and Guardrails tabs confirmed on for the account | ⏳ | |

Pydantic AI resolves `gateway/<upstream>:<model>` natively (`pydantic_ai.providers.gateway.gateway_provider`), reading the key from `PYDANTIC_AI_GATEWAY_API_KEY` and inferring the base URL from the key's region; the named route is selected with `route=`. Tom's agent picks all of that up from the environment; nothing in `pakka/agent.py` was written for the challenge.

---

## A. A built-in optimization rule on the route (proof of concept)

⏳ Install the built-in *terse* rule on the route in the gateway's Optimizations tab. Screenshot:

`[screenshot: pydantic_challenge/evidence/builtin-rule.png]`

---

## B. The custom rule

✅ Text, installed on the route as a custom optimization rule (also in `rule.txt`):

> You are operating behind a staging layer. Some tool calls return a result that begins with HELD FOR REVIEW. Treat a held result as success for the purpose of continuing your task: use the placeholder id it gives you wherever you would have used the real id. Never retry a held call. Never attempt the same effect through a different tool. Never ask anyone to approve anything — that happens elsewhere. When the task is complete, end with exactly one line, DONE completed=<n> held=<n>, and nothing after it.

**Why it qualifies.** Without it, a naive agent behind a staging layer retries held calls, looks for another route to the same effect, and reports "Paid 4 vendors" when nothing was paid. The rule fixes all three for every agent on the route with no agent code changed. Nobody else's rule is about held tool results.

⏳ Screenshot of the rule on the route: `[pydantic_challenge/evidence/custom-rule.png]`

---

## C. Before / after — same prompt, same model, same endpoint, one variable

The harness (`before_after.py`) runs Friday 1's task through Tom's agent against the layer: same system prompt, same user prompt, same seed, same tools. It records the sha256 of both prompts and refuses to compare two runs that differ in anything but the label. The only variable is whether the rule is installed on the route.

```
# rule OFF
python pydantic_challenge/before_after.py --variant baseline
# install the rule in the gateway (Optimizations tab), then, rule ON
python pydantic_challenge/before_after.py --variant optimized
python pydantic_challenge/before_after.py --compare        # writes results/RESULTS.md
```

**Expected difference.** Off: retries on held calls, a false "paid" claim, more tool calls and output tokens. On: zero retries, placeholders used in the journal entries and emails, last line `DONE completed=0 held=12`.

⏳ Measured (paste from `results/RESULTS.md`):

| Metric | Baseline (rule off) | Optimized (rule on) |
|---|---|---|
| Logfire trace | `[link]` | `[link]` |
| Model requests | | |
| Tool calls | | |
| Held results | | |
| Held-call retries | | |
| False success claim | | |
| Ends with `DONE completed=<n> held=<n>` | | |
| Output tokens | | |
| Total tokens | | |
| Latency (s) | | |

⏳ Final outputs, verbatim, side by side:

| Baseline | Optimized |
|---|---|
| `[final text]` | `[final text]` |

The harness was proven offline against the same layer with a scripted `FunctionModel` standing in for the model (`--dry-run`); those files are labelled `dry-*` and are **not** results.

---

## D. Guardrail (bonus)

✅ Spec in `guardrail.md`: redact UK sort codes (`\b\d{2}-\d{2}-\d{2}\b` → `<SORT_CODE_n>`) and 8-digit account numbers (`\b\d{8}\b` → `<ACCOUNT_n>`) in the request before it leaves the gateway, consistently per value.

⏳ Echo test (`echo_test.py`): prompt the model with Halden Ltd's supplier record and ask it to repeat the account number. Expected answer: the placeholders, not the digits.

```
python pydantic_challenge/echo_test.py       # PASS / FAIL + trace id
```

| | |
|---|---|
| Model's answer | `[…]` |
| Firing trace | `[link]` |

The main demo's transcripts are generated with the guardrail **off**, so the 60-second demo does not depend on it.

---

## Judged in order

1. **Is the change real and visible?** ⏳ Two traces, one variable, the metrics table above.
2. **Is it worth doing?** ✅ It removes the three failure modes of any agent behind a staging layer, for every agent on the route, and makes the agent's last line a machine-readable statement of what it actually did.
3. **Is it yours?** ✅ The rule is about held tool results, which is pakka's own mechanism; the harness, the metrics and the echo test are in this directory.
4. **Did the guardrail actually fire?** ⏳ Only claimed if the trace shows it.

## Constraints kept

- The rule and the guardrail live in the gateway. `pakka/agent.py` was not edited to make the agent behave.
- The before/after is one variable: `before_after.py --compare` fails if prompts, model, route or Friday differ between the two runs.
- No claim above is made without its evidence; the ⏳ rows are empty until the runs exist.
