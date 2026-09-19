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


class SimSystem:
    """One system the agent writes to: a store of records and the log of what landed."""

    def __init__(self, name: str, id_prefix: str) -> None:
        self.name = name
        self.id_prefix = id_prefix
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
        self.effects: list[Effect] = []

    # registration ---------------------------------------------------------

    def system(self, name: str, id_prefix: str) -> SimSystem:
        return self.systems.setdefault(name, SimSystem(name, id_prefix))

    def on_read(self, tool: str, handler: ReadHandler) -> None:
        if self.tools[tool].kind != "read":
            raise ValueError(f"{tool} is not a read")
        self._reads[tool] = handler

    def on_write(self, tool: str, system: str, handler: WriteHandler) -> None:
        if self.tools[tool].kind != "write":
            raise ValueError(f"{tool} is not a write")
        self._writes[tool] = (system, handler)

    # the staging layer's side --------------------------------------------

    def read(self, tool: str, args: dict[str, Any]) -> Any:
        return self._reads[tool](args)

    def apply(self, tool: str, args: dict[str, Any], run: int) -> Effect:
        system_name, handler = self._writes[tool]
        system = self.systems[system_name]
        seq = len(self.effects) + 1
        new_id = system.new_id(self.seed, run, seq)
        system.records[new_id] = handler(args, new_id)
        effect = Effect(seq=seq, run=run, tool=tool, system=system_name, args=args, result_id=new_id)
        self.effects.append(effect)
        return effect

    def replay_effects(self, effects: list[Effect]) -> None:
        """Rebuild the systems' records from a persisted effects log."""
        for e in effects:
            system_name, handler = self._writes[e.tool]
            self.systems[system_name].records[e.result_id] = handler(e.args, e.result_id)
            self.effects.append(e)
