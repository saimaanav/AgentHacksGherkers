# Guardrail: redact bank details before the request leaves the gateway

Configured in the Pydantic AI Gateway on the route Tom's agent uses. Nothing in the agent or the layer changes.

## What it redacts

| Pattern | Regex | Replacement |
|---|---|---|
| UK sort code | `\b\d{2}-\d{2}-\d{2}\b` | `<SORT_CODE_n>` |
| 8-digit account number | `\b\d{8}\b` | `<ACCOUNT_n>` |

Replacement is **consistent per value** within a request: the same sort code always becomes the same `<SORT_CODE_1>`, a second distinct sort code becomes `<SORT_CODE_2>`, and likewise for accounts. The model can still tell two accounts apart, which is all the task needs; it never sees the digits.

## Where it applies

On the **request** (everything sent to the model: system prompt, user prompt, tool results). The model's reply and the tool calls it makes are not rewritten by the guardrail. So an agent that copies an account number from a tool result into an email body will write `<ACCOUNT_1>`, and the layer's rule ("hold `send_remittance_email` when `body` contains a sort code") will not fire on that email, because there is no sort code in it any more. That is the intended layering: the gateway governs what the agent thinks with; pakka governs what it does.

## The echo test

```
PYDANTIC_AI_GATEWAY_API_KEY=… PAKKA_MODEL=gateway/openai:<model> PAKKA_GATEWAY_ROUTE=<route> \
python pydantic_challenge/echo_test.py
```

The script reads Halden Ltd's supplier record from the Friday-1 world, sends it to the model with the instruction to repeat the account number and sort code exactly, and reports:

- **PASS** — the answer contains `<SORT_CODE_…>` / `<ACCOUNT_…>` and none of the real digit groups: the model never saw them.
- **FAIL** — the answer contains the digits: the guardrail did not fire on this route.

The script also prints the trace id. The proof is the trace in Logfire showing the guardrail event on that request; the script's PASS is only what the model saw. Do not claim the guardrail fired unless the trace shows it.

## The main demo does not depend on it

The 60-second demo's transcripts are generated with the guardrail **off** (`--generate` against a route without it), so the story on screen — an email carrying a sort code, Tom's edit, the rule — does not depend on gateway configuration.
