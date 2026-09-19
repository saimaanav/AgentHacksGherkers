"""§9 Agnostic grep and Logfire write-only. The layer must not know what an invoice is, and must never read its own record."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAKKA = ROOT / "pakka"
DOMAIN = re.compile(r"invoice|vendor|payout|remittance|ledger", re.IGNORECASE)


def _layer_files():
    for p in PAKKA.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".json") and "scenarios" not in p.parts and "transcripts" not in p.parts:
            yield p


def test_domain_words_only_in_the_scenario():
    hits = [(p.relative_to(ROOT), i, line.strip()) for p in _layer_files() for i, line in enumerate(p.read_text().splitlines(), 1) if DOMAIN.search(line)]
    assert hits == [], hits


def test_the_rg_command_from_the_plan():
    try:
        out = subprocess.run(
            ["rg", "-i", "invoice|vendor|payout|remittance|ledger", "pakka/", "--glob", "!pakka/sim/scenarios/*", "--glob", "!pakka/sim/transcripts/**"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return  # rg not installed; the Python walk above covers it
    assert out.returncode == 1, out.stdout  # rg exits 1 when nothing matches


def test_logfire_is_written_to_never_read_from():
    bad = re.compile(r"logfire\.(query|read|search|fetch|client|LogfireClient|get_)|from logfire.*(query|client)|logfire\.experimental")
    hits = [(p.relative_to(ROOT), line.strip()) for p in PAKKA.rglob("*.py") for line in p.read_text().splitlines() if bad.search(line)]
    assert hits == [], hits


def test_no_model_calls_in_the_layer():
    forbidden = re.compile(r"pydantic_ai|anthropic|openai|Agent\(|run_sync|\.run\(")
    for name in ("staging.py", "checks.py", "learning.py", "models.py"):
        text = (PAKKA / name).read_text()
        assert not forbidden.search(text), name
