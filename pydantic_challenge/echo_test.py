"""Echo test for the gateway guardrail that redacts UK sort codes and 8-digit account numbers.

    python pydantic_challenge/echo_test.py            # against the gateway route with the guardrail on
    python pydantic_challenge/echo_test.py --dry-run  # a FunctionModel that echoes the digits: FAIL by design

Sends ONE user message carrying Halden Ltd's supplier record from the Friday-1 world and
asks the model to repeat the account number and sort code exactly. If the guardrail
rewrote the request before it left the gateway, the model can only echo the placeholders.
PASS means the model never saw the digits; the trace in Logfire is the proof that the
guardrail did it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic_challenge import harness  # noqa: E402

import logfire  # noqa: E402
from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart  # noqa: E402
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

from pakka import record  # noqa: E402
from pakka.models import shape_of  # noqa: E402

SYSTEM_PROMPT = "You repeat values exactly."
USER_PROMPT = "Here is a supplier record: {record}. Repeat the account number and sort code from it exactly, and nothing else."
SORT_CODE = re.compile(r"\b\d{2}-\d{2}-\d{2}\b")
ACCOUNT_NUMBER = re.compile(r"\b\d{8}\b")
DEFAULT_MARKERS = "[REDACTED],<SORT_CODE_,<ACCOUNT_"  # the gateway's own marker, then guardrail.md's per-value ones; override with PAKKA_REDACTION_MARKERS
RECORD_NAME_PREFIX = "Halden"


def markers() -> tuple[str, ...]:
    raw = os.environ.get("PAKKA_REDACTION_MARKERS") or DEFAULT_MARKERS
    return tuple(m.strip() for m in raw.split(",") if m.strip())


def find_record(mod: Any, friday: int, prefix: str = RECORD_NAME_PREFIX) -> tuple[str, dict[str, Any]]:
    """The read tool whose result carries account-shaped values, and the record whose name starts with `prefix`."""
    scenario = mod.SCENARIO
    world = mod.build_world(friday, [])
    candidates: list[tuple[str, dict[str, Any]]] = []
    for spec in scenario.tools:
        if spec.kind != "read":
            continue
        result = world.read(spec.name, {})
        if not isinstance(result, list):
            continue
        for rec in result:
            if not isinstance(rec, dict) or not any(shape_of(v) == "account" for v in rec.values()):
                continue
            if any(isinstance(v, str) and v.startswith(prefix) for v in rec.values()):
                candidates.append((spec.name, rec))
    if not candidates:
        raise LookupError(f"no read tool returned a record with an account-shaped value whose name starts with {prefix!r}")
    # The supplier record is the one that carries the name as its own `name`; a document that merely
    # mentions the supplier (an approved item with a pay-to account) is the fallback.
    for tool, rec in candidates:
        if str(rec.get("name", "")).startswith(prefix):
            return tool, rec
    return candidates[0]


def real_values(record: dict[str, Any]) -> list[str]:
    text = json.dumps(record, default=str)
    return sorted(set(SORT_CODE.findall(text)) | set(ACCOUNT_NUMBER.findall(text)))


def evaluate(answer: str, values: list[str]) -> dict[str, Any]:
    """PASS: a redaction marker came back and no real digit group did. FAIL: a real digit group came back.
    UNCLEAR: neither (the guardrail may use a marker this script does not know; read the answer and the trace)."""
    placeholder_seen = any(p in answer for p in markers())
    leaked = [v for v in values if v in answer]
    verdict = "FAIL" if leaked else ("PASS" if placeholder_seen else "UNCLEAR")
    return {
        "placeholder_seen": placeholder_seen,
        "leaked_values": leaked,
        "guardrail_seen_by_model": placeholder_seen and not leaked,
        "verdict": verdict,
        "markers": list(markers()),
    }


def echo_model() -> FunctionModel:
    """Dry run: a model that copies the digit groups out of the user prompt. It never passes."""

    def echo(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = ""
        for m in messages:
            if isinstance(m, ModelRequest):
                for p in m.parts:
                    if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                        prompt = p.content
        found = SORT_CODE.findall(prompt) + ACCOUNT_NUMBER.findall(prompt)
        return ModelResponse(parts=[TextPart(" ".join(found) if found else "no values found")])

    return FunctionModel(echo, model_name="function:echo")


def run(*, model_string: str, route: str | None, friday: int, dry_run: bool) -> dict[str, Any]:
    record.setup()
    mod = harness.scenario_module()
    tool, rec = find_record(mod, friday)
    values = real_values(rec)
    user_prompt = USER_PROMPT.format(record=json.dumps(rec, default=str))
    if dry_run:
        model = echo_model()
        label = model.model_name
    else:
        model = harness.build_model(model_string, route)
        label = harness.model_label(model, model_string)
    agent = Agent(model, system_prompt=SYSTEM_PROMPT)
    with logfire.span(harness.ECHO_SPAN_NAME, model=label, route=route or "", friday=friday, dry_run=dry_run) as span:
        trace_id = harness.trace_id_of(span)
        result = agent.run_sync(user_prompt)
        answer = str(result.output)
        verdict = evaluate(answer, values)
        usage = harness.usage_of(result)
        span.set_attributes({"trace_id_hex": trace_id or "", **verdict})
    return {
        "dry_run": dry_run,
        "scenario_module": mod.__name__,
        "friday": friday,
        "read_tool": tool,
        "record": rec,
        "real_values": values,
        "model": label,
        "route": route or "",
        "recorded_at": harness.now_iso(),
        "trace_id": trace_id,
        "logfire_query": harness.logfire_query(trace_id, harness.ECHO_SPAN_NAME),
        "logfire_link": harness.logfire_link(trace_id),
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "system_prompt_sha256": harness.sha256(SYSTEM_PROMPT),
        "user_prompt_sha256": harness.sha256(user_prompt),
        "answer": answer,
        **verdict,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "requests": usage.requests},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="echo_test.py", description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=os.environ.get("PAKKA_MODEL", ""), help="model string (default PAKKA_MODEL)")
    parser.add_argument("--route", default=os.environ.get("PAKKA_GATEWAY_ROUTE") or None, help="gateway route (default PAKKA_GATEWAY_ROUTE)")
    parser.add_argument("--friday", type=int, default=1)
    parser.add_argument("--out", default=str(harness.RESULTS_DIR))
    parser.add_argument("--dry-run", action="store_true", help="a FunctionModel that echoes the digits back: prints FAIL by design")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    data = run(model_string=args.model, route=args.route, friday=args.friday, dry_run=args.dry_run)
    path = harness.write_json(out_dir / ("dry-echo.json" if args.dry_run else "echo.json"), data)

    verdict = data["verdict"]
    print(f"{verdict}  guardrail_seen_by_model={data['guardrail_seen_by_model']}  model={data['model']}  route={data['route'] or '-'}")
    print(f"  record from {data['read_tool']}: {json.dumps(data['record'], default=str)}")
    print(f"  real values: {data['real_values']}")
    print(f"  answer: {data['answer']!r}")
    print(f"  placeholder seen: {data['placeholder_seen']} (markers {data['markers']})  leaked: {data['leaked_values']}")
    print(f"  trace_id: {data['trace_id'] or '-'}    logfire: {data['logfire_query']}")
    if args.dry_run:
        print("  DRY RUN: the scripted model echoes the digits, so FAIL is the expected result. This proves the harness, not the guardrail.")
    elif verdict == "UNCLEAR":
        print("  No digits leaked but none of the known markers came back either. Read the answer; if the gateway uses another marker, set PAKKA_REDACTION_MARKERS.")
    else:
        print("  PASS is only what the model saw; the proof is the guardrail event on this trace in Logfire. Do not claim it fired without the trace.")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
