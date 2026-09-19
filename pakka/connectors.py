"""Connectors: tool sets a job can write through, beside the scenario's own systems.

A connector is what the layer is agnostic about: a name, a description, its tools as `ToolSpec`s (a name, a kind
and a JSON schema, the same shape an MCP tool has), and how to register reads and writes on a `World`. The staging
layer, the checks and the learning see connector tools exactly as they see the scenario's: every write is held,
flagged, reviewed and learned from, and a real one leaves the building only when a person approves it.

Every connector has a **demo mode** that needs no setup, and a **live mode** a team configures for itself
(`POST /connectors/{name}`, stored in the team's state, never in the server's environment):

- `notes`: a simulated notes system (the shape of a CRM or wiki write). Always demo; nothing to configure.
- `webhook`: demo mode offers two simulated channels, `ops` and `alerts`, and an approved `post_message` is recorded
  as *simulated*. Live mode is the team's own channels, `{"channels": {"ops": "https://hooks.slack.com/…"}}`;
  an approved message is POSTed as `{"text": …}` to that URL, and nowhere else. Slack, Discord, Zapier, n8n and
  most incoming-webhook endpoints accept that body. The agent only ever sees channel names, never a URL.

`PAKKA_WEBHOOKS="name=url,…"` in the environment is a default for a single-team, self-hosted install; a team's own
settings win over it. The scenario's own systems (the three the demo writes to) are not connectors: they are the
world the recorded runs were played in. A real connector for them is the product's adapter work (docs/PRODUCT_PLAN.md).
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Protocol

from pakka.models import ConnectorView, ToolSpec
from pakka.sim.systems import World

Config = dict[str, Any]
DEMO_CHANNELS = ["ops", "alerts"]


class Connector(Protocol):
    name: str
    description: str
    real: bool

    def tools(self) -> list[ToolSpec]: ...

    def view(self, config: Config) -> ConnectorView: ...

    def validate(self, config: Config) -> Config: ...

    def register(self, world: World, config: Config) -> None: ...


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

    def view(self, config: Config) -> ConnectorView:
        return ConnectorView(name=self.name, description=self.description, real=False, configured=True, mode="demo", tools=[t.name for t in self.tools()])

    def validate(self, config: Config) -> Config:
        return {}

    def register(self, world: World, config: Config) -> None:
        world.add_tools(self.tools())
        system = world.system("notes", "note", connector=self.name)
        world.on_read("list_notes", lambda args: list(system.records.values()))
        world.on_write("write_note", "notes", lambda args, new_id: {"id": new_id, **args})


# ---------------------------------------------------------------------------
# webhook: demo channels, or the team's own
# ---------------------------------------------------------------------------


def env_channels() -> dict[str, str]:
    """`PAKKA_WEBHOOKS="name=url,name=url"` → {name: url}: a self-hosted default. Only https URLs are kept."""
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
    description = "Post a message to a named channel. Demo mode: simulated channels, no setup. Live mode: your own incoming webhooks (Slack, Discord, Zapier, n8n); the URL is yours, the agent only sees the name."
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

    def channels(self, config: Config) -> dict[str, str]:
        """The team's own channels, else the environment's default; {} means demo mode."""
        own = {str(k): str(v) for k, v in (config.get("channels") or {}).items()}
        return own or env_channels()

    def view(self, config: Config) -> ConnectorView:
        live = self.channels(config)
        return ConnectorView(
            name=self.name,
            description=self.description,
            real=True,
            configured=bool(live),
            mode="live" if live else "demo",
            tools=[t.name for t in self.tools()],
            channels=sorted(live) if live else list(DEMO_CHANNELS),
            settings={"channels": "name → https URL of an incoming webhook (Slack, Discord, Zapier, n8n); one per line. Leave empty for demo mode."},
        )

    def validate(self, config: Config) -> Config:
        channels = config.get("channels") or {}
        if not isinstance(channels, dict):
            raise ValueError("channels must be a mapping of name to https URL")
        clean: dict[str, str] = {}
        for name, url in channels.items():
            name, url = str(name).strip(), str(url).strip()
            if not name or not name.replace("-", "").replace("_", "").isalnum():
                raise ValueError(f"channel name {name!r}: letters, digits, - and _ only")
            if not url.startswith("https://"):
                raise ValueError(f"channel {name!r}: the URL must start with https://")
            clean[name] = url
        return {"channels": clean} if clean else {}

    def register(self, world: World, config: Config) -> None:
        world.add_tools(self.tools())
        world.system("webhook", "msg", connector=self.name)
        live = self.channels(config)
        names = sorted(live) if live else list(DEMO_CHANNELS)
        world.on_read("list_channels", lambda args: list(names))

        def send(args: dict[str, Any], new_id: str) -> dict[str, Any]:
            channel = str(args.get("channel", ""))
            if channel not in names:
                raise ValueError(f"no channel named {channel!r}")
            if not live:
                return {"status": "simulated", "channel": channel}
            return {**(self.sender or post_json)(live[channel], {"text": str(args.get("text", ""))}), "channel": channel}

        world.on_write("post_message", "webhook", lambda args, new_id: {"id": new_id, "status": "queued", **args}, send=send)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

ConfigBook = dict[str, Config]  # connector name -> its config (State.connector_config)


def registry() -> dict[str, Connector]:
    return {c.name: c for c in (NotesConnector(), WebhookConnector())}


def views(configs: ConfigBook | None = None) -> list[ConnectorView]:
    configs = configs or {}
    return [c.view(configs.get(c.name, {})) for c in registry().values()]


def all_tools() -> list[ToolSpec]:
    return [t for c in registry().values() for t in c.tools()]


def register_all(world: World, configs: ConfigBook | None = None) -> None:
    configs = configs or {}
    for c in registry().values():
        c.register(world, configs.get(c.name, {}))


def tools_for(names: list[str] | None) -> list[ToolSpec]:
    """The tools of the named connectors, for one job. Unknown names raise KeyError."""
    reg = registry()
    return [t for n in (names or []) for t in reg[n].tools()]


def configure(configs: ConfigBook, name: str, config: Config) -> ConnectorView:
    """Validate and store one connector's settings for a team. Unknown name: KeyError; bad settings: ValueError."""
    connector = registry()[name]
    clean = connector.validate(config)
    if clean:
        configs[name] = clean
    else:
        configs.pop(name, None)
    return connector.view(configs.get(name, {}))
