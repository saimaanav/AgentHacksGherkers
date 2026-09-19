"""The record: Logfire, written to and never read from. Plus the tiny .env loader."""

from __future__ import annotations

import os
from pathlib import Path

import logfire

_configured = False


def load_env(path: str | Path | None = None) -> None:
    """Load KEY=VALUE lines from .env if present. Existing environment wins."""
    p = Path(path) if path else Path(__file__).resolve().parent.parent / ".env"
    if not p.exists():
        return
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
