"""Connectors: tool sets a job can write through, beside the scenario's own systems.

A connector is what the layer is agnostic about: a name, a description, its tools as `ToolSpec`s (a name, a kind
and a JSON schema, the same shape an MCP tool has), and how to register reads and writes on a `World`. The staging
layer, the checks and the learning see connector tools exactly as they see the scenario's: every write is held,
flagged, reviewed and learned from, and a real one leaves the building only when a person approves it.

Every connector has a **demo mode** that needs no setup, and a **live mode** a team configures for itself
(`POST /connectors/{name}`, stored in the team's state, never in the server's environment). In demo mode the
targets are simulated and an approved write is recorded as `simulated`; in live mode it is `delivered`. A delivery
that fails leaves the write approved and unsent (`delivery_error`), with no effect and nothing learned, until a
person retries it (`POST /retry/{run}`). The agent only ever sees target names (a channel, a table, a repo, an
endpoint), never a URL or a key; the target field of a write tool is an enum of this team's targets, so a write to
a target that does not exist is refused when the agent makes it; and a key never comes back out of the API.

| connector | tools | demo | live (settings) |
|---|---|---|---|
| notes     | list_notes, write_note            | simulated notes            | — (always simulated) |
| webhook   | list_channels, post_message       | channels ops, alerts       | `channels`: name → https incoming-webhook URL (Slack, Discord, Zapier, n8n) |
| email     | list_senders, send_email          | simulated outbox           | `api_key`, `from` (Resend's HTTP API) |
| tickets   | list_tickets, open_ticket         | repo demo/board            | `token`, `repo` (GitHub Issues) |
| records   | list_tables, append_record        | tables contacts, tasks     | `api_key`, `base_id`, `tables` (Airtable) |
| http      | list_endpoints, call_endpoint     | endpoint echo              | `endpoints`: name → {url, method?, headers?} (any JSON API) |

`PAKKA_WEBHOOKS="name=url,…"` in the environment is a default for the webhook on a single-team, self-hosted
install; a team's own settings win over it. The scenario's own systems (the three the demo writes to) are not
connectors: they are the world the recorded runs were played in. A real connector for them is the product's adapter
work (docs/PRODUCT_PLAN.md).
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable

from pakka.models import ConnectorView, ToolSpec
from pakka.sim.systems import World

Config = dict[str, Any]
ConfigBook = dict[str, Config]  # connector name -> its config (State.connector_config)
Detail = dict[str, Any]


# ---------------------------------------------------------------------------
# HTTP, stdlib only. Every live connector goes through this one function, so a test swaps it once.
# ---------------------------------------------------------------------------


def request_json(method: str, url: str, payload: Any = None, headers: dict[str, str] | None = None, timeout: float = 15.0) -> Detail:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        body: Any = None
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        return {"status": "delivered", "http_status": r.status, "body": body}


def _obj(properties: dict[str, dict[str, str]], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": {k: {"type": "string", **v} for k, v in properties.items()}, "required": required}


def _ident(name: str, what: str) -> str:
    name = str(name).strip()
    if not name or not name.replace("-", "").replace("_", "").replace("/", "").replace(".", "").isalnum():
        raise ValueError(f"{what} {name!r}: letters, digits, - _ / . only")
    return name


def _https(url: str, what: str) -> str:
    url = str(url).strip()
    if not url.startswith("https://"):
        raise ValueError(f"{what}: the URL must start with https://")
    return url


def _secret(config: Config, key: str) -> str:
    v = str(config.get(key, "")).strip()
    if not v:
        raise ValueError(f"{key} is required")
    return v


# ---------------------------------------------------------------------------
# The shape every connector shares
# ---------------------------------------------------------------------------


class BaseConnector:
    name = ""
    description = ""
    real = True
    system_prefix = "x"
    demo_targets: list[str] = []
    settings: dict[str, str] = {}  # what the settings form asks for, field -> hint
    read_tool = ""
    write_tool = ""

    def tools(self, config: Config | None = None) -> list[ToolSpec]:
        """The tool specs. With a config, the target field is an enum of this team's targets (demo or live), so a
        write to a target that does not exist is refused when the agent makes it, not after someone approves it."""
        specs = self.specs()
        if config is None or not self.target_word:
            return specs
        names = self.targets(config) or list(self.demo_targets)
        out: list[ToolSpec] = []
        for t in specs:
            props = dict(t.args_schema.get("properties", {}))
            if t.kind == "write" and self.target_word in props and names:
                props[self.target_word] = {**props[self.target_word], "enum": list(names)}
                t = t.model_copy(update={"args_schema": {**t.args_schema, "properties": props}})
            out.append(t)
        return out

    def specs(self) -> list[ToolSpec]:
        raise NotImplementedError

    def targets(self, config: Config) -> list[str]:
        """Live targets from the team's settings, else [] (demo mode)."""
        return []

    def validate(self, config: Config) -> Config:
        return {}

    def record(self, args: dict[str, Any], new_id: str) -> dict[str, Any]:
        return {"id": new_id, **args}

    def send(self, config: Config, args: dict[str, Any], new_id: str) -> Detail:
        raise NotImplementedError

    def read(self, system_records: dict[str, dict[str, Any]], names: list[str], config: Config) -> Any:
        return list(names)

    target_word = "target"

    # -- the same for all --------------------------------------------------

    def live(self, config: Config) -> bool:
        return bool(self.targets(config))

    def view(self, config: Config) -> ConnectorView:
        live = self.live(config)
        return ConnectorView(
            name=self.name,
            description=self.description,
            real=self.real,
            configured=live or not self.real,
            mode="live" if live else "demo",
            tools=[t.name for t in self.tools()],
            targets=self.targets(config) if live else list(self.demo_targets),
            settings=dict(self.settings),
        )

    def register(self, world: World, config: Config) -> None:
        world.add_tools(self.tools())
        system = world.system(self.name, self.system_prefix, connector=self.name)
        live = self.live(config)
        names = self.targets(config) if live else list(self.demo_targets)
        if self.read_tool:
            world.on_read(self.read_tool, lambda args: self.read(system.records, names, config))

        def send(args: dict[str, Any], new_id: str) -> Detail:
            target = self.target_of(args) or (names[0] if names else "")  # a connector with one fixed target (email's sender)
            if names and target not in names:
                raise ValueError(f"no {self.target_word} named {target!r}")
            if not live:
                return {"status": "simulated", self.target_word: target}
            out = self.send(config, args, new_id)
            return {"status": out.get("status", "delivered"), self.target_word: target, **{k: v for k, v in out.items() if k in ("http_status", "url")}}

        world.on_write(self.write_tool, self.name, self.record, send=send if self.real else None)

    def target_of(self, args: dict[str, Any]) -> str:
        return str(args.get(self.target_word, ""))


# ---------------------------------------------------------------------------
# notes: simulated, nothing to configure
# ---------------------------------------------------------------------------


class NotesConnector(BaseConnector):
    name = "notes"
    description = "A simulated notes system: write a note, list notes. Stands in for a CRM, a wiki or a ticket tracker. Always simulated."
    real = False
    system_prefix = "note"
    read_tool, write_tool = "list_notes", "write_note"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="list_notes", kind="read", description="Notes already on file (title, body, id).", args_schema=_obj({}, [])),
            ToolSpec(name="write_note", kind="write", description="Write a note. Returns its id.", args_schema=_obj({"title": {"description": "A short title"}, "body": {"description": "The note"}}, ["title", "body"])),
        ]

    def read(self, system_records: dict[str, dict[str, Any]], names: list[str], config: Config) -> Any:
        return list(system_records.values())


# ---------------------------------------------------------------------------
# webhook: named incoming webhooks
# ---------------------------------------------------------------------------


def env_channels() -> dict[str, str]:
    """`PAKKA_WEBHOOKS="name=url,name=url"` → {name: url}: a self-hosted default. Only https URLs are kept."""
    out: dict[str, str] = {}
    for part in os.environ.get("PAKKA_WEBHOOKS", "").split(","):
        name, _, url = part.strip().partition("=")
        if name and url.startswith("https://"):
            out[name.strip()] = url.strip()
    return out


class WebhookConnector(BaseConnector):
    name = "webhook"
    description = "Post a message to a named channel. Demo: simulated channels. Live: your own incoming webhooks (Slack, Discord, Zapier, n8n); the URL is yours, the agent only sees the name."
    system_prefix = "msg"
    demo_targets = ["ops", "alerts"]
    settings = {"channels": "name → https URL of an incoming webhook (Slack, Discord, Zapier, n8n); one per line. Leave empty for demo mode."}
    read_tool, write_tool, target_word = "list_channels", "post_message", "channel"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="list_channels", kind="read", description="The channels a message can be posted to.", args_schema=_obj({}, [])),
            ToolSpec(name="post_message", kind="write", description="Post a message to a named channel. Returns the message id.", args_schema=_obj({"channel": {"description": "One of the channels from list_channels"}, "text": {"description": "The message"}}, ["channel", "text"])),
        ]

    def channels(self, config: Config) -> dict[str, str]:
        own = {str(k): str(v) for k, v in (config.get("channels") or {}).items()}
        return own or env_channels()

    def targets(self, config: Config) -> list[str]:
        return sorted(self.channels(config))

    def validate(self, config: Config) -> Config:
        channels = config.get("channels") or {}
        if not isinstance(channels, dict):
            raise ValueError("channels must be a mapping of name to https URL")
        clean = {_ident(n, "channel name"): _https(u, f"channel {n!r}") for n, u in channels.items()}
        return {"channels": clean} if clean else {}

    def send(self, config: Config, args: dict[str, Any], new_id: str) -> Detail:
        return request_json("POST", self.channels(config)[str(args["channel"])], {"text": str(args.get("text", ""))})


# ---------------------------------------------------------------------------
# email: Resend's HTTP API
# ---------------------------------------------------------------------------


class EmailConnector(BaseConnector):
    name = "email"
    description = "Send an email. Demo: a simulated outbox. Live: your Resend API key and a verified from-address; the key never leaves the server."
    system_prefix = "mail"
    demo_targets = ["outbox"]
    settings = {"api_key": "Resend API key (re_…)", "from": "the verified sender, e.g. Tom <tom@yourdomain.com>"}
    read_tool, write_tool, target_word = "list_senders", "send_email", "sender"  # sender is fixed by the settings, not an argument

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="list_senders", kind="read", description="The addresses mail can be sent from.", args_schema=_obj({}, [])),
            ToolSpec(name="send_email", kind="write", description="Send an email. Returns the message id.", args_schema=_obj({"to": {"description": "Recipient address"}, "subject": {}, "body": {"description": "Plain text"}}, ["to", "subject", "body"])),
        ]

    def targets(self, config: Config) -> list[str]:
        return [str(config["from"])] if config.get("api_key") and config.get("from") else []

    def validate(self, config: Config) -> Config:
        if not any(config.get(k) for k in self.settings):
            return {}
        sender = _secret(config, "from")
        if "@" not in sender:
            raise ValueError("from must be an email address")
        return {"api_key": _secret(config, "api_key"), "from": sender}

    def target_of(self, args: dict[str, Any]) -> str:
        return ""  # the sender is the configured one; nothing in the args to check against the targets

    def send(self, config: Config, args: dict[str, Any], new_id: str) -> Detail:
        return request_json(
            "POST", "https://api.resend.com/emails",
            {"from": config["from"], "to": [str(args["to"])], "subject": str(args.get("subject", "")), "text": str(args.get("body", ""))},
            {"Authorization": f"Bearer {config['api_key']}"},
        )


# ---------------------------------------------------------------------------
# tickets: GitHub Issues
# ---------------------------------------------------------------------------


class TicketsConnector(BaseConnector):
    name = "tickets"
    description = "Open a ticket. Demo: a simulated board. Live: issues in a GitHub repository of yours, with a fine-grained token that can write issues there."
    system_prefix = "tkt"
    demo_targets = ["demo/board"]
    settings = {"token": "GitHub token with Issues: write on the repository", "repo": "owner/name"}
    read_tool, write_tool, target_word = "list_tickets", "open_ticket", "repo"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="list_tickets", kind="read", description="Tickets opened through the layer so far, and the repositories available.", args_schema=_obj({}, [])),
            ToolSpec(name="open_ticket", kind="write", description="Open a ticket in a repository. Returns its id.", args_schema=_obj({"repo": {"description": "One of the repositories from list_tickets"}, "title": {}, "body": {}}, ["repo", "title", "body"])),
        ]

    def targets(self, config: Config) -> list[str]:
        return [str(config["repo"])] if config.get("token") and config.get("repo") else []

    def validate(self, config: Config) -> Config:
        if not any(config.get(k) for k in self.settings):
            return {}
        repo = _ident(_secret(config, "repo"), "repo")
        if repo.count("/") != 1:
            raise ValueError("repo must be owner/name")
        return {"token": _secret(config, "token"), "repo": repo}

    def read(self, system_records: dict[str, dict[str, Any]], names: list[str], config: Config) -> Any:
        return {"repos": list(names), "tickets": list(system_records.values())}

    def send(self, config: Config, args: dict[str, Any], new_id: str) -> Detail:
        out = request_json(
            "POST", f"https://api.github.com/repos/{config['repo']}/issues",
            {"title": str(args.get("title", "")), "body": str(args.get("body", ""))},
            {"Authorization": f"Bearer {config['token']}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )
        body = out.get("body") or {}
        return {**out, "url": body.get("html_url", "")} if isinstance(body, dict) else out


# ---------------------------------------------------------------------------
# records: Airtable
# ---------------------------------------------------------------------------


class RecordsConnector(BaseConnector):
    name = "records"
    description = "Append a record to a table. Demo: simulated tables. Live: an Airtable base of yours, with a personal access token; the shape of a CRM row."
    system_prefix = "rec"
    demo_targets = ["contacts", "tasks"]
    settings = {"api_key": "Airtable personal access token (pat…)", "base_id": "the base id (app…)", "tables": "table names the agent may append to, comma-separated"}
    read_tool, write_tool, target_word = "list_tables", "append_record", "table"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="list_tables", kind="read", description="The tables a record can be appended to, and records appended so far.", args_schema=_obj({}, [])),
            ToolSpec(
                name="append_record", kind="write", description="Append one record to a table. Returns its id.",
                args_schema={"type": "object", "properties": {"table": {"type": "string", "description": "One of the tables from list_tables"}, "fields": {"type": "object", "description": "column -> value", "additionalProperties": True}}, "required": ["table", "fields"]},
            ),
        ]

    def targets(self, config: Config) -> list[str]:
        return list(config.get("tables") or []) if config.get("api_key") and config.get("base_id") else []

    def validate(self, config: Config) -> Config:
        if not any(config.get(k) for k in self.settings):
            return {}
        tables_raw = config.get("tables") or []
        if not isinstance(tables_raw, (str, list)):
            raise ValueError("tables must be a comma-separated string or a list of names")
        items = tables_raw.split(",") if isinstance(tables_raw, str) else tables_raw
        if not all(isinstance(t, str) for t in items):
            raise ValueError("tables: every table name must be a string")
        tables = [t.strip() for t in items if t.strip()]
        if not tables:
            raise ValueError("tables: name at least one table")
        return {"api_key": _secret(config, "api_key"), "base_id": _ident(_secret(config, "base_id"), "base_id"), "tables": tables}

    def read(self, system_records: dict[str, dict[str, Any]], names: list[str], config: Config) -> Any:
        return {"tables": list(names), "records": list(system_records.values())}

    def send(self, config: Config, args: dict[str, Any], new_id: str) -> Detail:
        table = urllib.request.quote(str(args["table"]))
        return request_json(
            "POST", f"https://api.airtable.com/v0/{config['base_id']}/{table}",
            {"fields": dict(args.get("fields") or {})},
            {"Authorization": f"Bearer {config['api_key']}"},
        )


# ---------------------------------------------------------------------------
# http: any JSON API, as named endpoints
# ---------------------------------------------------------------------------


class HttpConnector(BaseConnector):
    name = "http"
    description = "Call a named JSON endpoint with a payload. Demo: a simulated echo endpoint. Live: your own endpoints (URL, method, headers); the agent only sees the names, so any API becomes a held write."
    system_prefix = "req"
    demo_targets = ["echo"]
    settings = {"endpoints": "name → {url (https), method (POST|PUT|PATCH, default POST), headers (optional, e.g. an Authorization header)}; one per line"}
    read_tool, write_tool, target_word = "list_endpoints", "call_endpoint", "endpoint"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="list_endpoints", kind="read", description="The endpoints that can be called.", args_schema=_obj({}, [])),
            ToolSpec(
                name="call_endpoint", kind="write", description="Send a JSON payload to a named endpoint. Returns the request id.",
                args_schema={"type": "object", "properties": {"endpoint": {"type": "string", "description": "One of the endpoints from list_endpoints"}, "payload": {"type": "object", "description": "The JSON body", "additionalProperties": True}}, "required": ["endpoint", "payload"]},
            ),
        ]

    def targets(self, config: Config) -> list[str]:
        return sorted(config.get("endpoints") or {})

    def validate(self, config: Config) -> Config:
        endpoints = config.get("endpoints") or {}
        if not isinstance(endpoints, dict):
            raise ValueError("endpoints must be a mapping of name to {url, method, headers}")
        clean: dict[str, dict[str, Any]] = {}
        for name, spec in endpoints.items():
            if isinstance(spec, str):
                spec = {"url": spec}
            if not isinstance(spec, dict):
                raise ValueError(f"endpoint {name!r}: must be a URL or {{url, method, headers}}")
            method = str(spec.get("method") or "POST").upper()
            if method not in ("POST", "PUT", "PATCH"):
                raise ValueError(f"endpoint {name!r}: method must be POST, PUT or PATCH")
            raw_headers = spec.get("headers") or {}
            if not isinstance(raw_headers, dict):
                raise ValueError(f"endpoint {name!r}: headers must be a mapping")
            headers = {str(k): str(v) for k, v in raw_headers.items()}
            clean[_ident(name, "endpoint name")] = {"url": _https(spec.get("url", ""), f"endpoint {name!r}"), "method": method, "headers": headers}
        return {"endpoints": clean} if clean else {}

    def send(self, config: Config, args: dict[str, Any], new_id: str) -> Detail:
        ep = config["endpoints"][str(args["endpoint"])]
        return request_json(ep["method"], ep["url"], dict(args.get("payload") or {}), ep.get("headers") or {})


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

_CONNECTORS: list[Callable[[], BaseConnector]] = [NotesConnector, WebhookConnector, EmailConnector, TicketsConnector, RecordsConnector, HttpConnector]


def registry() -> dict[str, BaseConnector]:
    return {c.name: c for c in (make() for make in _CONNECTORS)}


def views(configs: ConfigBook | None = None) -> list[ConnectorView]:
    configs = configs or {}
    return [c.view(configs.get(c.name, {})) for c in registry().values()]


def all_tools() -> list[ToolSpec]:
    return [t for c in registry().values() for t in c.tools()]


def register_all(world: World, configs: ConfigBook | None = None) -> None:
    configs = configs or {}
    for c in registry().values():
        c.register(world, configs.get(c.name, {}))


def tools_for(names: list[str] | None, configs: ConfigBook | None = None) -> list[ToolSpec]:
    """The tools of the named connectors, for one job, with this team's targets as enums. Unknown names raise KeyError."""
    reg = registry()
    configs = configs or {}
    return [t for n in (names or []) for t in reg[n].tools(configs.get(n, {}))]


def configure(configs: ConfigBook, name: str, config: Config) -> ConnectorView:
    """Validate and store one connector's settings for a team. Unknown name: KeyError; bad settings: ValueError."""
    connector = registry()[name]
    try:
        clean = connector.validate(config)
    except (TypeError, AttributeError) as e:  # a wrong-typed field the connector did not spell out
        raise ValueError(f"settings have the wrong shape: {e}") from e
    if clean:
        configs[name] = clean
    else:
        configs.pop(name, None)
    return connector.view(configs.get(name, {}))
