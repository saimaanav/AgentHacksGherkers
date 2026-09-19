"""Connectors: tool sets a job can write through, beside the scenario's own systems.

A connector is what the layer is agnostic about: a name, a description, its tools as `ToolSpec`s (a name, a kind
and a JSON schema, the same shape an MCP tool has), and how to register reads and writes on a `World`. The staging
layer, the checks and the learning see connector tools exactly as they see the scenario's: every write is held,
flagged, reviewed and learned from, and a real one leaves the building only when a person approves it.

Two ship with the demo:

- `notes`: a simulated notes system (the shape of a CRM or a wiki write). Deterministic, no credentials.
- `webhook`: a real one. `PAKKA_WEBHOOKS="ops=https://hooks.slack.com/services/…,alerts=https://…"` names the channels;
  `post_message(channel, text)` POSTs `{"text": …}` to that URL on approval, and nowhere else. Slack, Discord, Zapier,
  n8n and most incoming-webhook endpoints accept that body. Channels are named, so the agent never chooses a URL.

The scenario's own systems (the three the demo writes to) are not connectors: they are the world the recorded runs
were played in. A real connector for them is the product's adapter work (docs/PRODUCT_PLAN.md).
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Protocol

from pakka.models import ConnectorView, ToolSpec
from pakka.sim.systems import World


class Connector(Protocol):
    name: str
    description: str
    real: bool

    def tools(self) -> list[ToolSpec]: ...

    def configured(self) -> bool: ...

    def register(self, world: World) -> None: ...


# ---------------------------------------------------------------------------
# notes: simulated
# ---------------------------------------------------------------------------


class NotesConnector:
    name = "notes"
    description = "A simulated notes system: write a note, list notes. Stands in for a CRM, a wiki or a ticket tracker."
    real = False

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="list_notes", kind="read", description="Notes already on file (title, body, id).", args_schema={"type": "object", "properties": {}}),
            ToolSpec(
                name="write_note",
                kind="write",
                description="Write a note. Returns its id.",
                args_schema={
                    "type": "object",
                    "properties": {"title": {"type": "string", "description": "A short title"}, "body": {"type": "string", "description": "The note"}},
                    "required": ["title", "body"],
                },
            ),
        ]

    def configured(self) -> bool:
        return True

    def register(self, world: World) -> None:
        world.add_tools(self.tools())
        system = world.system("notes", "note", connector=self.name)
        world.on_read("list_notes", lambda args: list(system.records.values()))
        world.on_write("write_note", "notes", lambda args, new_id: {"id": new_id, **args})


# ---------------------------------------------------------------------------
# webhook: real
# ---------------------------------------------------------------------------


def webhook_channels() -> dict[str, str]:
    """`PAKKA_WEBHOOKS="name=url,name=url"` → {name: url}. Only https URLs are kept."""
    out: dict[str, str] = {}
    for part in os.environ.get("PAKKA_WEBHOOKS", "").split(","):
        name, _, url = part.strip().partition("=")
        if name and url.startswith("https://"):
            out[name.strip()] = url.strip()
    return out


def post_json(url: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return {"status": "delivered", "http_status": r.status}


class WebhookConnector:
    name = "webhook"
    description = "A real one: post a message to a named incoming webhook (Slack, Discord, Zapier, n8n). The URL is configured, never chosen by the agent."
    real = True

    def __init__(self, sender: Any = None) -> None:
        self.sender = sender  # None: post_json at call time, so a test can swap the module's sender

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="list_channels", kind="read", description="The channels a message can be posted to.", args_schema={"type": "object", "properties": {}}),
            ToolSpec(
                name="post_message",
                kind="write",
                description="Post a message to a named channel. Returns the message id.",
                args_schema={
                    "type": "object",
                    "properties": {"channel": {"type": "string", "description": "One of the channels from list_channels"}, "text": {"type": "string", "description": "The message"}},
                    "required": ["channel", "text"],
                },
            ),
        ]

    def configured(self) -> bool:
        return bool(webhook_channels())

    def register(self, world: World) -> None:
        world.add_tools(self.tools())
        world.system("webhook", "msg", connector=self.name)
        world.on_read("list_channels", lambda args: sorted(webhook_channels()))

        def send(args: dict[str, Any], new_id: str) -> dict[str, Any]:
            url = webhook_channels().get(str(args.get("channel", "")))
            if not url:
                raise ValueError(f"no channel named {args.get('channel')!r}")
            return (self.sender or post_json)(url, {"text": str(args.get("text", ""))})

        world.on_write("post_message", "webhook", lambda args, new_id: {"id": new_id, "status": "queued", **args}, send=send)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def registry() -> dict[str, Connector]:
    return {c.name: c for c in (NotesConnector(), WebhookConnector())}


def views() -> list[ConnectorView]:
    return [
        ConnectorView(name=c.name, description=c.description, real=c.real, configured=c.configured(), tools=[t.name for t in c.tools()])
        for c in registry().values()
    ]


def all_tools() -> list[ToolSpec]:
    return [t for c in registry().values() for t in c.tools()]


def register_all(world: World) -> None:
    for c in registry().values():
        c.register(world)


def tools_for(names: list[str] | None) -> list[ToolSpec]:
    """The tools of the named connectors, for one job. Unknown names raise KeyError."""
    reg = registry()
    return [t for n in (names or []) for t in reg[n].tools()]
