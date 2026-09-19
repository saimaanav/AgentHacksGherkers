"""The Pydantic AI Gateway challenge harness, proven offline: both scripts with --dry-run, then --compare."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BEFORE_AFTER = ROOT / "pydantic_challenge" / "before_after.py"
ECHO_TEST = ROOT / "pydantic_challenge" / "echo_test.py"
REAL_FINANCE = "pakka.sim.scenarios.finance"

RUN_KEYS = {
    "variant", "dry_run", "scenario", "scenario_module", "seed", "friday", "model", "route", "note", "trace_id",
    "logfire_query", "system_prompt_sha256", "user_prompt_sha256", "metrics", "counts", "final_text", "journal",
}
METRIC_KEYS = {
    "latency_s", "model_requests", "tool_calls", "tool_calls_by_tool", "held_results", "held_retries",
    "duplicate_effect_attempts", "effects", "false_success_claim", "paid_claims", "done_line_ok", "done_line_truthful",
    "done_line", "usage",
}
ECHO_KEYS = {"dry_run", "read_tool", "record", "real_values", "model", "route", "trace_id", "logfire_query", "answer", "guardrail_seen_by_model"}


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYDANTIC_AI_NO_BANNER": "1"}
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT, env=env, capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("challenge")
    for variant in ("baseline", "optimized"):
        proc = _run(BEFORE_AFTER, "--variant", variant, "--dry-run", "--out", str(out), "--note", f"test {variant}")
        assert proc.returncode == 0, proc.stderr
    return out


def _real_scenario() -> bool:
    return (os.environ.get("PAKKA_SCENARIO") or REAL_FINANCE) == REAL_FINANCE


def test_before_after_dry_run_files(out_dir: Path):
    for variant in ("baseline", "optimized"):
        data = json.loads((out_dir / f"dry-{variant}.json").read_text())
        assert RUN_KEYS <= set(data), RUN_KEYS - set(data)
        assert METRIC_KEYS <= set(data["metrics"]), METRIC_KEYS - set(data["metrics"])
        assert data["variant"] == variant and data["dry_run"] is True
        assert data["metrics"]["effects"] == 0
        assert len(data["trace_id"]) == 32
        assert (out_dir / f"dry-{variant}.md").exists()
        assert data["journal"] and data["journal"][0]["seq"] == 1
        assert all(len(j["result_text"]) <= 200 for j in data["journal"])


def test_friday_one_holds_twelve(out_dir: Path):
    if not _real_scenario():
        pytest.skip("held count is specific to the finance scenario")
    data = json.loads((out_dir / "dry-baseline.json").read_text())
    assert data["scenario_module"] == REAL_FINANCE
    assert data["metrics"]["held_results"] == 12
    assert data["metrics"]["held_retries"] == 0
    assert data["metrics"]["duplicate_effect_attempts"] == 0
    assert data["metrics"]["false_success_claim"] is True  # the naive agent says "Paid ..." with nothing sent
    assert data["metrics"]["done_line_ok"] is False


def test_one_variable_rule_is_recorded(out_dir: Path):
    a = json.loads((out_dir / "dry-baseline.json").read_text())
    b = json.loads((out_dir / "dry-optimized.json").read_text())
    assert a["system_prompt_sha256"] == b["system_prompt_sha256"]
    assert a["user_prompt_sha256"] == b["user_prompt_sha256"]
    assert a["model"] == b["model"] and a["route"] == b["route"] and a["friday"] == b["friday"]


def test_compare_writes_results(out_dir: Path):
    proc = _run(BEFORE_AFTER, "--compare", "--dry-run", "--out", str(out_dir))
    assert proc.returncode == 0, proc.stderr
    results = out_dir / "dry-RESULTS.md"
    assert results.exists()
    text = results.read_text()
    assert "| metric | baseline (rule off) | optimized (rule on) |" in text
    assert "## Final outputs (verbatim)" in text and "trace_id = '" in text


def test_compare_refuses_a_two_variable_pair(out_dir: Path, tmp_path: Path):
    a = json.loads((out_dir / "dry-baseline.json").read_text())
    b = json.loads((out_dir / "dry-optimized.json").read_text())
    b["user_prompt_sha256"] = "0" * 64
    (tmp_path / "dry-baseline.json").write_text(json.dumps(a))
    (tmp_path / "dry-optimized.json").write_text(json.dumps(b))
    proc = _run(BEFORE_AFTER, "--compare", "--dry-run", "--out", str(tmp_path))
    assert proc.returncode != 0
    assert "user prompt differs" in proc.stderr
    assert not (tmp_path / "dry-RESULTS.md").exists()


def _stand_in(name: str, variant: str, tmp_path: Path) -> dict:
    """Run a stand-in policy (tests/stand_ins/<name>.py) through the harness; the finance world underneath."""
    if not _real_scenario():
        pytest.skip("the stand-ins wrap the finance scenario")
    env = {**os.environ, "PYDANTIC_AI_NO_BANNER": "1", "PAKKA_SCENARIO": f"tests.stand_ins.{name}"}
    proc = subprocess.run(
        [sys.executable, str(BEFORE_AFTER), "--variant", variant, "--dry-run", "--out", str(tmp_path)],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads((tmp_path / f"dry-{variant}.json").read_text())


def test_held_retry_is_counted(tmp_path: Path):
    m = _stand_in("retry_held", "baseline", tmp_path)["metrics"]
    assert m["tool_calls_by_tool"]["create_payout"] == 5 and m["held_results"] == 13
    assert m["held_retries"] == 1 and m["duplicate_effect_attempts"] == 1
    assert m["false_success_claim"] is True and m["done_line_ok"] is False
    assert m["effects"] == 0


def test_truthful_done_line_is_not_a_false_claim(tmp_path: Path):
    m = _stand_in("done_line", "optimized", tmp_path)["metrics"]
    assert m["done_line"] == "DONE completed=0 held=12"
    assert m["done_line_ok"] is True and m["done_line_truthful"] is True
    assert m["false_success_claim"] is False and m["paid_claims"] == []  # "nothing was paid yet" is a report, not a claim
    assert m["held_retries"] == 0


def test_well_formed_but_wrong_done_line(tmp_path: Path):
    m = _stand_in("lying_done", "optimized", tmp_path)["metrics"]
    assert m["done_line_ok"] is True and m["done_line_truthful"] is False
    assert m["false_success_claim"] is True and m["paid_claims"] == ["Paid 4 vendors, £9,415.50"]


def test_compare_refuses_a_renamed_dry_run(out_dir: Path, tmp_path: Path):
    """A dry-run file renamed to look like a real run must not become RESULTS.md."""
    for variant in ("baseline", "optimized"):
        (tmp_path / f"{variant}.json").write_text((out_dir / f"dry-{variant}.json").read_text())
    proc = _run(BEFORE_AFTER, "--compare", "--out", str(tmp_path))
    assert proc.returncode != 0 and "dry run" in proc.stderr
    assert not (tmp_path / "RESULTS.md").exists()


def test_dry_outputs_are_labelled(out_dir: Path):
    for name in ("dry-baseline.md", "dry-optimized.md", "dry-RESULTS.md"):
        text = (out_dir / name).read_text() if (out_dir / name).exists() else ""
        if text:
            assert text.startswith("# DRY RUN (harness proof)"), name
            assert "not a result" in text


def test_echo_dry_run_fails_by_design(tmp_path: Path):
    proc = _run(ECHO_TEST, "--dry-run", "--out", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("FAIL")
    data = json.loads((tmp_path / "dry-echo.json").read_text())
    assert ECHO_KEYS <= set(data), ECHO_KEYS - set(data)
    assert data["guardrail_seen_by_model"] is False and data["verdict"] == "FAIL"
    assert data["real_values"] and all(v in data["answer"] for v in data["real_values"])
    assert "DRY RUN" in proc.stdout and "not the guardrail" in proc.stdout
    if _real_scenario():
        assert data["read_tool"] == "list_vendors"
        assert str(data["record"]["name"]).startswith("Halden")
