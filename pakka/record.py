"""The record: Logfire, written to and never read from. Plus the tiny .env loader."""

from __future__ import annotations

import os
from pathlib import Path

import logfire

_configured = False


def load_env(path: str | Path | None = None) -> None:
    """Load KEY=VALUE lines from `.env` and `pakka.env` (a visible twin, for people whose file browser hides
    dotfiles) at the repo root, if present. Existing environment wins; both files are gitignored."""
    root = Path(__file__).resolve().parent.parent
    paths = [Path(path)] if path else [root / ".env", root / "pakka.env"]
    for p in paths:
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


def setup(service_name: str = "pakka", send: bool | str | None = None) -> None:
    """Configure Logfire once and instrument Pydantic AI. With no token, spans are emitted and dropped."""
    global _configured
    if _configured:
        return
    load_env()
    if send is None:
        send = "if-token-present"
    logfire.configure(
        service_name=service_name,
        send_to_logfire=send,
        console=False,
        environment=os.environ.get("PAKKA_ENV", "local"),
    )
    logfire.instrument_pydantic_ai()
    _configured = True
