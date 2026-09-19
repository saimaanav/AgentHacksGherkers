"""In-memory systems with an effects log. Generic: a scenario registers reads and writes by name.

Ids are deterministic from (seed, run, sequence) so a replayed run produces the
same effects log every time.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

from pakka.models import Effect, ToolSpec

ReadHandler = Callable[[dict[str, Any]], Any]
WriteHandler = Callable[[dict[str, Any], str], dict[str, Any]]  # (args, new_id) -> stored record
SendHandler = Callable[[dict[str, Any], str], dict[str, Any]]  # (args, new_id) -> delivery details; the real side effect


class SimSystem:
    """One system the agent writes to: a store of records and the log of what landed."""

    def __init__(self, name: str, id_prefix: str, connector: str | None = None) -> None:
        self.name = name
        self.id_prefix = id_prefix
        self.connector = connector  # set when a connector, not the scenario, registered this system
        self.records: dict[str, dict[str, Any]] = {}

    def new_id(self, seed: int, run: int, seq: int) -> str:
        digest = hashlib.sha1(f"{self.name}:{seed}:{run}:{seq}".encode()).hexdigest()[:6]
        return f"{self.id_prefix}_{digest}"


class World:
    """The simulated systems for one run. Implements the `pakka.staging.World` protocol."""

    def __init__(self, seed: int, tools: list[ToolSpec]) -> None:
        self.seed = seed
        self.tools = {t.name: t for t in tools}
        self.systems: dict[str, SimSystem] = {}
        self._reads: dict[str, ReadHandler] = {}
        self._writes: dict[str, tuple[str, WriteHandler]] = {}
        self._sends: dict[str, SendHandler] = {}
        self.effects: list[Effect] = []

    # registration ---------------------------------------------------------

    def add_tools(self, tools: list[ToolSpec]) -> None:
        """A connector's tools join the scenario's; the layer treats them the same."""
        for t in tools:
            self.tools.setdefault(t.name, t)

    def system(self, name: str, id_prefix: str, connector: str | None = None) -> SimSystem:
        return self.systems.setdefault(name, SimSystem(name, id_prefix, connector))

    def on_read(self, tool: str, handler: ReadHandler) -> None:
        if self.tools[tool].kind != "read":
            raise ValueError(f"{tool} is not a read")
        self._reads[tool] = handler

    def on_write(self, tool: str, system: str, handler: WriteHandler, send: SendHandler | None = None) -> None:
        """`handler` builds the record and runs on replay too; `send` is the real side effect and runs once, on apply."""
        if self.tools[tool].kind != "write":
            raise ValueError(f"{tool} is not a write")
        self._writes[tool] = (system, handler)
        if send is not None:
            self._sends[tool] = send

    # the staging layer's side --------------------------------------------

    def read(self, tool: str, args: dict[str, Any]) -> Any:
        return self._reads[tool](args)

    def apply(self, tool: str, args: dict[str, Any], run: int) -> Effect:
        system_name, handler = self._writes[tool]
        system = self.systems[system_name]
        seq = len(self.effects) + 1
        new_id = system.new_id(self.seed, run, seq)
        record = handler(args, new_id)
        send = self._sends.get(tool)
        if send is not None:  # a real connector: the effect leaves the building here, and only here
            try:
                record = {**record, **send(args, new_id)}
            except Exception as e:  # the write was approved; a failed delivery is recorded, never retried silently
                record = {**record, "status": "failed", "error": str(e)[:200]}
        system.records[new_id] = record
        effect = Effect(seq=seq, run=run, tool=tool, system=system_name, args=args, result_id=new_id)
        self.effects.append(effect)
        return effect

    def replay_effects(self, effects: list[Effect]) -> None:
        """Rebuild the systems' records from a persisted effects log. Never re-sends."""
        for e in effects:
            system_name, handler = self._writes[e.tool]
            self.systems[system_name].records[e.result_id] = handler(e.args, e.result_id)
            self.effects.append(e)
