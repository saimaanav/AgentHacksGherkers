"""Tom's agent: a Pydantic AI tool-calling agent whose tools are the scenario's ToolSpecs, routed through the staging layer.

One Agent class, three models: a real provider (PAKKA_MODEL) for --generate and --live,
a FunctionModel that replays a saved transcript for the demo, and a FunctionModel that
scripts the naive policy for tests and for the "naive" transcripts.

`python -m pakka.agent --generate --fridays 26 --tag naive` writes transcripts;
`modal run pakka/agent.py --generate --fridays 26` does the same on Modal.
"""

import argparse
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic_ai import Agent, Tool
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from pakka import record, staging
from pakka.models import AgentChoice, RunMode, RunResult, Scenario, State, ToolCall, ToolSpec, Transcript

TRANSCRIPTS_DIR = Path(__file__).resolve().parent / "sim" / "transcripts"
DEFAULT_SCENARIO_MODULE = "pakka.sim.scenarios.finance"
NAIVE_TAG = "naive"

Policy = Callable[[list[ModelMessage], AgentInfo], ModelResponse]


def scenario_module(path: str | None = None) -> Any:
    """The scenario module: `PAKKA_SCENARIO` (a module path) or the default."""
    return importlib.import_module(path or os.environ.get("PAKKA_SCENARIO") or DEFAULT_SCENARIO_MODULE)


# ---------------------------------------------------------------------------
# Tools: the scenario's ToolSpecs as Pydantic AI tools, each routed through staging.Run
# ---------------------------------------------------------------------------


def make_tool(spec: ToolSpec, run: staging.Run) -> Tool:
    model = spec.args_model()

    def fn(args) -> Any:  # noqa: ANN001 - the annotation is set below so the model's schema becomes the tool schema
        data = args.model_dump()
        if spec.kind == "read":
            return run.read(spec.name, data)
        return run.write(spec.name, data)

    fn.__name__ = spec.name
    fn.__qualname__ = spec.name
    fn.__doc__ = spec.description
    fn.__annotations__ = {"args": model, "return": Any}
    return Tool(fn, name=spec.name, description=spec.description)


def build_tools(scenario: Scenario, run: staging.Run, tools: list[ToolSpec] | None = None) -> list[Tool]:
    return [make_tool(spec, run) for spec in (tools if tools is not None else scenario.tools)]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def _returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [p for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart)]


def replay_model(transcript: Transcript) -> FunctionModel:
    """Step k of the conversation issues call k of the transcript; after the last call, the final text."""
    calls = transcript.calls

    def replay(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        k = len(_returns(messages))
        if k < len(calls):
            return ModelResponse(parts=[ToolCallPart(calls[k].tool, dict(calls[k].args))])
        return ModelResponse(parts=[TextPart(transcript.final_text)])

    return FunctionModel(replay, model_name=f"replay:{transcript.model}")


def naive_model(policy: Policy) -> FunctionModel:
    return FunctionModel(policy, model_name=f"function:{NAIVE_TAG}")


def real_model(name: str | None = None) -> Model | str:
    """The model behind PAKKA_MODEL: `provider:model`, `openrouter:<org/model>`, `gateway/<upstream>:<model>`
    (the Pydantic AI Gateway; PAKKA_GATEWAY_ROUTE names a route such as a Modal endpoint), or any
    OpenAI-compatible endpoint via PAKKA_BASE_URL (Ollama, vLLM)."""
    name = name or os.environ.get("PAKKA_MODEL", "")
    if not name:
        raise RuntimeError("PAKKA_MODEL is not set (e.g. anthropic:claude-sonnet-5, openai:gpt-5, groq:llama-3.3-70b-versatile)")
    base_url = os.environ.get("PAKKA_BASE_URL")
    if name.startswith("gateway/"):
        return gateway_model(name, os.environ.get("PAKKA_GATEWAY_ROUTE"))
    if name.startswith("openrouter:"):
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        return OpenAIChatModel(name.split(":", 1)[1], provider=OpenRouterProvider(api_key=os.environ.get("OPENROUTER_API_KEY")))
    if base_url:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        model_name = name.split(":", 1)[1] if ":" in name else name
        api_key = os.environ.get("PAKKA_API_KEY") or os.environ.get("OPENAI_API_KEY") or "none"
        return OpenAIChatModel(model_name, provider=OpenAIProvider(base_url=base_url, api_key=api_key))
    return name


def gateway_model(name: str, route: str | None = None) -> Model | str:
    """`gateway/<upstream>:<model>` through the Pydantic AI Gateway. Without a route Pydantic AI resolves the
    string itself (key from PYDANTIC_AI_GATEWAY_API_KEY); with a route, the same provider on that route."""
    if not route:
        return name
    from pydantic_ai.providers.gateway import gateway_provider

    upstream, _, model_name = name.removeprefix("gateway/").partition(":")
    if not model_name:
        raise RuntimeError(f"PAKKA_MODEL={name!r} needs a model after the colon, e.g. gateway/openai-chat:<model>")
    _widen_openai_metadata()
    provider = gateway_provider(upstream, route=route)
    if upstream == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel

        return AnthropicModel(model_name, provider=provider)
    if upstream == "groq":
        from pydantic_ai.models.groq import GroqModel

        return GroqModel(model_name, provider=provider)
    if upstream.startswith("google"):
        from pydantic_ai.models.google import GoogleModel

        return GoogleModel(model_name, provider=provider)
    from pydantic_ai.models.openai import OpenAIChatModel

    return OpenAIChatModel(model_name, provider=provider)


def _widen_openai_metadata() -> None:
    """A Modal endpoint behind the gateway returns `metadata.weight_versions` as a list, which the OpenAI
    schema types as dict[str, str]. Widen it on both models that see the payload (the hackathon setup's fix)."""
    try:
        from openai.types.chat import ChatCompletion
        from pydantic_ai.models.openai import _ChatCompletion
    except ImportError:  # pragma: no cover
        return
    for model in (ChatCompletion, _ChatCompletion):
        try:
            field = model.model_fields["metadata"]
            if field.annotation == dict[str, Any] | None:
                continue  # already widened; the rebuild is process-wide, do it once
            field.annotation = dict[str, Any] | None
            model.model_rebuild(force=True)
        except Exception:  # a library layout this was not written for: leave the schema as it is
            continue


def live_available() -> bool:
    return bool(os.environ.get("PAKKA_MODEL"))


# ---------------------------------------------------------------------------
# Agent choices: which agent a job is routed through
# ---------------------------------------------------------------------------

_PROVIDER_KEYS = {
    "google": "GOOGLE_API_KEY",
    "google-gla": "GOOGLE_API_KEY",
    "gateway": "PYDANTIC_AI_GATEWAY_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


def _key_for(model: str) -> str | None:
    provider = model.split("/", 1)[0] if model.startswith("gateway/") else model.split(":", 1)[0]
    return _PROVIDER_KEYS.get(provider)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def available_agents() -> list[AgentChoice]:
    """The agents a job can be routed through. `replay` is the recorded run (instant, the demo); `live` is
    PAKKA_MODEL; `PAKKA_AGENTS="label=model,label=model"` adds more. A live agent is available when its key is set."""
    out: list[AgentChoice] = []
    tag = default_tag()
    if tag in available_tags():
        try:
            recorded = load_transcript(1, tag).model
        except Exception:
            recorded = tag
        out.append(AgentChoice(id="replay", label=f"Recorded run ({recorded})", model=f"replay:{tag}", kind="replay", detail="Plays the transcript the agent produced for this run; instant. Only the scenario's own prompt."))
    seen: set[str] = set()
    default = os.environ.get("PAKKA_MODEL", "")
    pairs = ([("live", default)] if default else []) + [
        (p.partition("=")[0].strip(), p.partition("=")[2].strip()) for p in os.environ.get("PAKKA_AGENTS", "").split(",") if "=" in p
    ]
    for label, model in pairs:
        if not model or model in seen:
            continue
        seen.add(model)
        key = _key_for(model)
        kind = "gateway" if model.startswith("gateway/") else "live"
        route = os.environ.get("PAKKA_GATEWAY_ROUTE", "")
        detail = f"through the Pydantic AI Gateway, route {route or 'default'}" if kind == "gateway" else "a live model call"
        if key and not os.environ.get(key):
            detail = f"needs {key}"
        out.append(AgentChoice(id=_slug(label) or _slug(model), label=label if label != "live" else model, model=model, kind=kind, available=not key or bool(os.environ.get(key)), detail=detail))
    return out


def resolve_agent(agent_id: str) -> AgentChoice:
    """The choice for an id; empty picks the first available live agent, else the replay."""
    choices = available_agents()
    if agent_id:
        for c in choices:
            if c.id == agent_id:
                return c
        raise KeyError(agent_id)
    live = [c for c in choices if c.kind != "replay" and c.available]
    if live:
        return live[0]
    if choices:
        return choices[0]
    raise KeyError("no agent is configured: set PAKKA_MODEL, or add transcripts to replay")


# ---------------------------------------------------------------------------
# One run of the agent through the layer
# ---------------------------------------------------------------------------


def transcript_of(scenario: Scenario, run: int, model_name: str, messages: list[ModelMessage], final_text: str) -> Transcript:
    calls: list[ToolCall] = []
    for m in messages:
        if not isinstance(m, ModelResponse):
            continue
        for part in m.parts:
            if isinstance(part, ToolCallPart):
                calls.append(ToolCall(seq=len(calls) + 1, tool=part.tool_name, args=part.args_as_dict()))
    return Transcript(
        run=run,
        model=model_name,
        scenario=scenario.name,
        seed=scenario.seed,
        calls=calls,
        final_text=final_text,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def run_agent(
    scenario: Scenario,
    world: staging.World,
    state: State,
    run: int,
    *,
    model: Model | str | None = None,
    model_name: str = "",
    supervisor: bool = True,
    mode: RunMode = "review",
    policy: Policy | None = None,
    prompt: str | None = None,
    tools: list[ToolSpec] | None = None,
) -> tuple[RunResult, Transcript]:
    """Run the agent once through the layer. Every write it makes is staged; nothing lands until someone decides.
    `tools` narrows which of the scenario's (and connectors') tools this agent gets; default all of the scenario's."""
    record.setup()
    if policy is not None:
        model = naive_model(policy)
        model_name = model_name or f"function:{NAIVE_TAG}"
    if model is None:
        raise ValueError("run_agent needs a model or a policy")
    if not model_name:
        model_name = model if isinstance(model, str) else getattr(model, "model_name", str(model))
    staged = staging.Run(scenario, world, state, run, supervisor=supervisor, mode=mode, model=model_name)
    agent = Agent(model, system_prompt=scenario.task, tools=build_tools(scenario, staged, tools))
    user_prompt = prompt or f"It's {scenario.run_label} {run}. Run the task."
    result = agent.run_sync(user_prompt)
    transcript = transcript_of(scenario, run, model_name, list(result.all_messages()), str(result.output))
    rr = staged.result(str(result.output))
    rr.prompt = user_prompt
    return rr, transcript


# ---------------------------------------------------------------------------
# Transcripts on disk: pakka/sim/transcripts/<tag>/friday_NN.json
# ---------------------------------------------------------------------------


def transcript_path(run: int, tag: str) -> Path:
    return TRANSCRIPTS_DIR / tag / f"friday_{run:02d}.json"


def available_tags() -> list[str]:
    if not TRANSCRIPTS_DIR.exists():
        return []
    return sorted(p.name for p in TRANSCRIPTS_DIR.iterdir() if p.is_dir() and any(p.glob("friday_*.json")))


def default_tag() -> str:
    env = os.environ.get("PAKKA_TRANSCRIPTS")
    if env:
        return env
    tags = available_tags()
    real = [t for t in tags if t != NAIVE_TAG]
    return real[0] if real else NAIVE_TAG


def load_transcript(run: int, tag: str | None = None) -> Transcript:
    path = transcript_path(run, tag or default_tag())
    if not path.exists():
        raise FileNotFoundError(f"no transcript for run {run} under {path.parent}")
    return Transcript.model_validate_json(path.read_text())


def save_transcript(transcript: Transcript, tag: str) -> Path:
    path = transcript_path(transcript.run, tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript.model_dump_json(indent=2) + "\n")
    return path


# ---------------------------------------------------------------------------
# Generation: the agent, one fresh run per Friday, nothing decided
# ---------------------------------------------------------------------------


def generate(
    tag: str,
    fridays: int,
    model: Model | str | None = None,
    model_name: str = "",
    scenario_mod: Any = None,
    save: bool = True,
) -> list[Transcript]:
    """Run the agent Friday by Friday against a fresh State in supervised mode without deciding (all held),
    so a transcript depends only on the scenario, never on a reviewer's choices."""
    mod = scenario_mod or scenario_module()
    scenario: Scenario = mod.SCENARIO
    prompt = getattr(mod, "AGENT_PROMPT", None)
    policy = mod.naive_policy if tag == NAIVE_TAG else None
    if policy is None:
        model = model or real_model()
        model_name = model_name or os.environ.get("PAKKA_MODEL", "") or (model if isinstance(model, str) else getattr(model, "model_name", ""))
    out: list[Transcript] = []
    for f in range(1, fridays + 1):
        state = State(scenario=scenario.name, seed=scenario.seed)
        world = mod.build_world(f, [])
        rr, t = run_agent(scenario, world, state, f, model=model, model_name=model_name, supervisor=True, mode="review", policy=policy, prompt=prompt)
        if save:
            save_transcript(t, tag)
        out.append(t)
        print(f"{scenario.run_label} {f}: {len(t.calls)} calls, {rr.counts.checked} writes checked, held {rr.counts.held} — {t.final_text}", file=sys.stderr)
    return out


def live(friday: int, model: Model | str | None = None, model_name: str = "", scenario_mod: Any = None) -> tuple[RunResult, Transcript]:
    """Run the real agent now, on a fresh State, and return what it did."""
    mod = scenario_mod or scenario_module()
    scenario: Scenario = mod.SCENARIO
    model = model or real_model()
    model_name = model_name or os.environ.get("PAKKA_MODEL", "") or (model if isinstance(model, str) else getattr(model, "model_name", ""))
    state = State(scenario=scenario.name, seed=scenario.seed)
    world = mod.build_world(friday, [])
    return run_agent(scenario, world, state, friday, model=model, model_name=model_name, supervisor=True, mode="live", prompt=getattr(mod, "AGENT_PROMPT", None))


# ---------------------------------------------------------------------------
# Modal: generate on Modal with `modal run pakka/agent.py --generate --fridays 26`
# ---------------------------------------------------------------------------

try:
    import modal
except ImportError:  # pragma: no cover
    modal = None

if modal is not None:
    app = modal.App("pakka-agent")
    image = (
        modal.Image.debian_slim(python_version="3.12")
        .pip_install("fastapi", "pydantic>=2", "pydantic-ai", "logfire")
        .add_local_python_source("pakka")
    )

    @app.function(image=image, secrets=[modal.Secret.from_name("pakka")], timeout=3600)
    def generate_transcripts(fridays: int = 26, model: str = "", tag: str = "") -> tuple[dict[str, str], str]:
        """Run the agent on Modal; returns ({filename: transcript JSON}, tag) for the local entrypoint to write."""
        if model:
            os.environ["PAKKA_MODEL"] = model
        tag = tag or (NAIVE_TAG if not os.environ.get("PAKKA_MODEL") else "real")
        transcripts = generate(tag, fridays, save=False)
        return {transcript_path(t.run, tag).name: t.model_dump_json(indent=2) for t in transcripts}, tag

    @app.local_entrypoint()
    def main(generate: bool = False, fridays: int = 26, model: str = "", tag: str = "") -> None:
        if not generate:
            print("nothing to do: pass --generate [--fridays N] [--model provider:model] [--tag naive|real]")
            return
        files, used_tag = generate_transcripts.remote(fridays, model, tag)
        for name, text in files.items():
            path = TRANSCRIPTS_DIR / used_tag / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n")
            print(f"wrote {path}")


# ---------------------------------------------------------------------------
# CLI: python -m pakka.agent --generate [--fridays 26] [--tag naive|real] [--model ...] | --live --friday N
# ---------------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pakka.agent", description=__doc__.splitlines()[0])
    parser.add_argument("--generate", action="store_true", help="write transcripts, one per run")
    parser.add_argument("--live", action="store_true", help="run the real agent on one run now")
    parser.add_argument("--fridays", type=int, default=26, help="how many runs to generate")
    parser.add_argument("--friday", type=int, default=1, help="which run to run live")
    parser.add_argument("--tag", default=None, help=f"transcript set: '{NAIVE_TAG}' scripts the naive policy; anything else uses the real model")
    parser.add_argument("--model", default="", help="overrides PAKKA_MODEL")
    args = parser.parse_args(argv)
    if args.model:
        os.environ["PAKKA_MODEL"] = args.model
    record.setup()
    if args.generate:
        tag = args.tag or (NAIVE_TAG if not os.environ.get("PAKKA_MODEL") else "real")
        transcripts = generate(tag, args.fridays)
        print(f"wrote {len(transcripts)} transcripts to {TRANSCRIPTS_DIR / tag}")
        return 0
    if args.live:
        try:
            rr, t = live(args.friday)
        except RuntimeError as e:
            print(f"cannot run live: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"agent_text": rr.agent_text, "counts": rr.counts.model_dump(), "flags": [
            {"write": w.id, "tool": w.tool, "reasons": [f.reason for f in w.flags]} for w in rr.writes if w.flags
        ], "calls": len(t.calls), "model": t.model}, indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
