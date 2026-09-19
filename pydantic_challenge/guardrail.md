# Guardrail: redact bank details before the request leaves the gateway

Configured in the Pydantic AI Gateway on the `pakka` route Tom's agent uses (**Gateway → Guardrails → New protection → Custom pattern**). Nothing in the agent or the layer changes. A guardrail is a different guarantee from a prompt instruction: the model is not asked to behave, it is never given the data.

## Two custom patterns

| Protection name | Regex | Apply to | Action |
|---|---|---|---|
| `UK sort code` | `\b\d{2}-\d{2}-\d{2}\b` | the `pakka` endpoint | **Redact** |
| `UK account number` | `\b\d{8}\b` | the `pakka` endpoint | **Redact** |

No lookarounds, so they stay portable across regex engines. `Observe` only records and demonstrates nothing; `Flag response` is the reply side. Pick **Redact**.

The gateway replaces a match with its own placeholder (`[REDACTED]` in the hackathon setup). If the gateway offers per-value placeholders, use `<SORT_CODE_n>` / `<ACCOUNT_n>` so the model can still tell two accounts apart; if it does not, `[REDACTED]` is fine for the echo test, and the agent's task does not depend on it (the demo's transcripts are generated with the guardrail off).

## Pattern tests (stored with the protection)

Should match:

```
Payment sent to sort code 40-27-19, account 60138824.
Account on file: 60-83-71 55204418
Please quote 30-91-26 / 40711985 on the remittance
```

Should not match (near misses):

```
Invoice total 1234.56          INV-20102 is due 2026-09-25
Ref 2026-09-19                 Phone 020 7946 0958
Budget is 25000 GBP            Version 2.1.4 shipped
```

## Where it applies

On the **request**: everything sent to the model, including tool results. So when Tom's agent reads Halden's supplier record through the gateway, it sees `[REDACTED]` where the account was, and an email it drafts cannot contain the sort code. Pakka's Friday-1 rule ("hold `send_remittance_email` when `body` contains a sort code") then has nothing to fire on. That is the intended layering: the gateway governs what the agent thinks with; pakka governs what it does.

## The echo test

```
uv run --env-file .env python pydantic_challenge/echo_test.py     # or: python pydantic_challenge/echo_test.py with .env in place
```

The script reads Halden Ltd's supplier record from the Friday-1 world and asks the model to repeat the account number and sort code character for character, with no other words. It reports:

- **PASS** — the answer contains a redaction placeholder and none of the real digit groups: the model never saw them.
- **FAIL** — the answer contains the digits: the guardrail did not fire on this route.

An output that merely omits the value proves nothing (a terse rule can drop a line for unrelated reasons); the echo is the proof. The script also prints the trace id. The proof for the submission is the trace in Logfire showing the guardrail event on that request. Do not claim the guardrail fired unless the trace shows it.

## The main demo does not depend on it

The 60-second demo's transcripts are generated with the guardrail **off**, so the story on screen, an email carrying a sort code, Tom's edit, the rule, does not depend on gateway configuration.
