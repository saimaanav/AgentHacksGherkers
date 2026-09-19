"""Shared pieces of the Pydantic AI Gateway challenge harness.

The challenge: change the agent's behaviour without touching its code. A rule
installed in the gateway injects instructions on every call of a route; the
proof is a before/after of the same prompt with the rule off vs on. This
module holds what both scripts need: the scenario, the model builder, the
trace id of a Logfire span, and the JSON writer. It never adds a word to any
prompt; pakka/agent.py is not edited.

Facts below were read from the installed pydantic_ai 2.46 and logfire 5.1
sources, not remembered:
- `gateway/<upstream>:<model>` strings resolve through `pydantic_ai.models.infer_model`,
  which maps the upstream name to a model class (`openai` -> OpenAIResponsesModel,
  `openai-chat` -> OpenAIChatModel, `anthropic` -> AnthropicModel, `groq` -> GroqModel).
- A named gateway route is `pydantic_ai.providers.gateway.gateway_provider(upstream, route=...)`;
  the key comes from `PYDANTIC_AI_GATEWAY_API_KEY`, the base URL from
  `PYDANTIC_AI_GATEWAY_BASE_URL` or the key's region.
- `logfire.span(...)` returns a LogfireSpan that delegates attribute access to the
  underlying OpenTelemetry span, so `span.get_span_context().trace_id` is the trace id.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # `python pydantic_challenge/x.py` puts pydantic_challenge/ first, not the repo
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

DEFAULT_SCENARIO_MODULE = "pakka.sim.scenarios.finance"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
SPAN_NAME = "pydantic_challenge.run"
ECHO_SPAN_NAME = "pydantic_challenge.echo"


# ---------------------------------------------------------------------------
# Scenario and agent (written elsewhere; used as they are)
# ---------------------------------------------------------------------------


def scenario_module() -> Any:
    """The scenario module: `PAKKA_SCENARIO` (a module path) or the finance scenario."""
    return importlib.import_module(os.environ.get("PAKKA_SCENARIO") or DEFAULT_SCENARIO_MODULE)


def is_real_finance(mod: Any) -> bool:
    return getattr(mod, "__name__", "") == DEFAULT_SCENARIO_MODULE


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def build_model(model_string: str, route: str | None = None) -> Any:
    """A Pydantic AI model (or a model string) for `model_string`.

    - `gateway/<upstream>:<name>`: through the Pydantic AI Gateway. With `route`, the named
      gateway route is selected via `gateway_provider(upstream, route=route)`; the model
      class is chosen by Pydantic AI's own `infer_model` mapping. Without a route the
      string is handed back and Pydantic AI resolves it (default route for the upstream).
    - a plain `provider:name` string: returned as is.
    - env `PAKKA_BASE_URL`: any OpenAI-compatible endpoint (chat completions) via
      `OpenAIChatModel(name, provider=OpenAIProvider(base_url=..., api_key=...))`.
    """
    if not model_string:
        raise RuntimeError("no model: pass --model or set PAKKA_MODEL (e.g. gateway/openai-chat:<model>)")
    if model_string.startswith("gateway/"):
        # The same wiring Tom's agent uses (pakka.agent.gateway_model): gateway_provider on the named route,
        # plus the widening of the OpenAI `metadata` field that a Modal endpoint fills with a list. Using the
        # agent's own function keeps the harness the same agent, not a second variable.
        from pakka.agent import gateway_model

        return gateway_model(model_string, route)
    # Everything else (openrouter, PAKKA_BASE_URL, plain provider:model) is the agent's own resolution.
    from pakka.agent import real_model

    return real_model(model_string)


def usage_of(result: Any) -> Any:
    """`AgentRunResult.usage` is a property in the installed Pydantic AI (it was a method in earlier releases)."""
    usage = getattr(result, "usage", None)
    return usage() if callable(usage) else usage


def model_label(model: Any, model_string: str) -> str:
    if isinstance(model, str):
        return model
    return model_string or getattr(model, "model_name", str(model))


# ---------------------------------------------------------------------------
# Logfire: the trace id of a span, and a query a person can paste
# ---------------------------------------------------------------------------


def trace_id_of(span: Any) -> str | None:
    """32 hex chars, or None when the span is not recording (no tracer)."""
    try:
        ctx = span.get_span_context()
    except Exception:  # pragma: no cover - a non-OTel span
        return None
    tid = getattr(ctx, "trace_id", 0) or 0
    return format(tid, "032x") if tid else None


def logfire_query(trace_id: str | None, span_name: str = SPAN_NAME) -> str:
    """A Logfire explore query (SQL over records) for the run's spans."""
    if not trace_id:
        return f"span_name = '{span_name}'  -- no trace id was recorded"
    return f"trace_id = '{trace_id}'"


def logfire_link(trace_id: str | None) -> str | None:
    """A search link when the project URL is known (env LOGFIRE_PROJECT_URL); the query is the fallback."""
    base = os.environ.get("LOGFIRE_PROJECT_URL", "").rstrip("/")
    if not base or not trace_id:
        return None
    return f"{base}?q=trace_id%3D%27{trace_id}%27"


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
