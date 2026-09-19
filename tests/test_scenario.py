"""§9 Scenario schema: the finance scenario validates; a rule whose pattern doesn't compile fails at construction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pakka.models import Rule, Scenario
from tests.conftest import SCENARIO

ROOT = Path(__file__).resolve().parent.parent


def test_finance_scenario_validates():
    assert Scenario.model_validate(SCENARIO.model_dump()) == SCENARIO
    assert Scenario.model_validate_json(SCENARIO.model_dump_json()) == SCENARIO
    assert {t.kind for t in SCENARIO.tools} == {"read", "write"}
    assert len(SCENARIO.write_tools()) == 3
    for t in SCENARIO.tools:
        t.args_model()  # every tool's schema builds a model


def test_schema_file_matches_the_model():
    path = ROOT / "docs" / "scenario.schema.json"
    assert path.exists(), "run: python -c 'from pakka.models import Scenario; import json; print(json.dumps(Scenario.model_json_schema(), indent=2))' > docs/scenario.schema.json"
    assert json.loads(path.read_text()) == Scenario.model_json_schema()


def test_bad_pattern_cannot_be_saved():
    with pytest.raises(ValidationError):
        Rule(id="r", tool="*", field="body", op="matches", value="(unclosed")
    with pytest.raises(ValidationError):
        Rule(id="r", tool="*", field="amount", op="gt", value="ten")
    Rule(id="r", tool="*", field="amount", op="gt", value=10000)


def test_anomalies_are_declared_on_the_fridays_the_demo_speaks_to():
    runs = sorted(a.run for a in SCENARIO.anomalies)
    assert runs[0] == 1
    first_autopilot = [a for a in SCENARIO.anomalies if a.run in SCENARIO.autopilot_runs]
    assert len(first_autopilot) == 4
    assert len({a.expected for a in first_autopilot}) >= 2
    assert {a.expected for a in SCENARIO.anomalies} == {"grounding", "envelope", "rule", "memory"}
