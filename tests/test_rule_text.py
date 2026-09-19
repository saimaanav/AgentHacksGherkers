"""A rule in a person's words is read by a grammar over the tools, not a model: what it reads, what it refuses, and why."""

from __future__ import annotations

import re

import pytest

from pakka import rule_text
from pakka.learning import RULE_PATTERNS
from pakka.models import RuleText, ToolSpec

TOOLS = [
    ToolSpec(
        name="post_message",
        kind="write",
        description="Post a note to a channel. Returns a message id.",
        args_schema={"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}}, "required": ["channel", "text"]},
    ),
    ToolSpec(
        name="move_funds",
        kind="write",
        description="Make a transfer between two accounts. Returns a transfer id.",
        args_schema={"type": "object", "properties": {"to": {"type": "string"}, "amount": {"type": "number"}, "note": {"type": "string"}}, "required": ["to", "amount"]},
    ),
    ToolSpec(name="list_channels", kind="read", description="The channels.", args_schema={"type": "object", "properties": {}}),
]


def read(text: str, tool: str | None = None, field: str | None = None):
    return rule_text.read(RuleText(text=text, tool=tool, field=field), [t for t in TOOLS if t.kind == "write"])


def test_the_popup_prefill_round_trips_for_every_pattern_the_layer_knows():
    for label, regex in RULE_PATTERNS:
        r = read(f"Always hold Post message when text contains {label}")
        assert r.intent == "hold" and r.rule is not None
        assert (r.rule.tool, r.rule.field, r.rule.op, r.rule.value, r.rule.label) == ("post_message", "text", "matches", regex, label)
        assert r.sentence == f"Hold Post message when text contains {label}"
        assert r.pattern == regex


def test_a_tool_can_be_named_by_a_word_from_its_description_and_a_number_carries_a_unit():
    r = read("always hold transfers over £10k")
    assert r.intent == "hold" and r.rule is not None
    assert (r.rule.tool, r.rule.field, r.rule.op, r.rule.value) == ("move_funds", "amount", "gt", 10000)
    assert r.sentence == "Hold Move funds when amount is over 10,000"
    assert read("hold transfers when amount is under 1,250.50").rule.value == 1250.5


def test_a_sentence_about_nothing_in_particular_is_about_the_write_in_front_of_the_person():
    r = read("From now on, it's fine if it contains a sort code", tool="post_message", field="text")
    assert r.intent == "allow" and r.rule is not None
    assert (r.rule.tool, r.rule.field, r.rule.op) == ("post_message", "text", "matches")
    assert r.rule.value == dict(RULE_PATTERNS)["a sort code"]
    assert r.sentence == "It's fine when text contains a sort code in Post message"
    r = read("hold it when the text has an account number in it", tool="post_message", field="text")
    assert r.intent == "hold" and r.rule.field == "text" and r.rule.label == "an account number"


def test_with_reads_as_contains_and_the_field_can_trail_the_value():
    r = read("hold every message with an account number in the text")
    assert r.intent == "hold" and (r.rule.tool, r.rule.field, r.rule.op) == ("post_message", "text", "matches")


def test_exact_words_and_a_regex():
    r = read('hold post message when text contains "urgent"')
    assert r.rule.value == "urgent" and r.rule.label == "“urgent”" and r.sentence.endswith("contains “urgent”")
    r = read("hold post message when text contains two words")
    assert re.search(r.rule.value, "these two words here") and r.rule.value == "two words"
    r = read("hold post message when text matches /\\d{4}/")
    assert r.rule.value == "\\d{4}" and r.rule.label == "/\\d{4}/"


def test_sets_one_of_and_not_one_of():
    assert read("hold post message when channel is one of alerts, ops").rule.model_dump(include={"op", "value"}) == {"op": "in", "value": ["alerts", "ops"]}
    assert read("hold post message when channel is alerts or ops").rule.value == ["alerts", "ops"]
    assert read("hold post message when channel is not one of ops, general").rule.model_dump(include={"op", "value"}) == {"op": "not_in", "value": ["ops", "general"]}
    assert read("hold post message when channel is not ops").rule.op == "not_in"


def test_no_tool_named_means_any_tool_when_the_field_is_named():
    r = read("hold when amount is over 10")
    assert r.intent == "hold" and (r.rule.tool, r.rule.field, r.rule.op, r.rule.value) == ("*", "amount", "gt", 10)
    assert r.sentence == "Hold any tool when amount is over 10"
    r = read("hold when it is over 10")
    assert r.intent == "unclear" and "Name the field" in r.problem


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("make it faster", "Start with what to do"),
        ("hold post message when", "Say the condition"),
        ("hold transfers over ten thousand", "isn't a number"),
        ("hold post message when text contains /[/", "doesn't compile"),
        ("hold post message when", "Say the condition"),
        ("hold post message when text contains", "Finish the sentence"),
        ("hold post message when channel is", "Finish the sentence"),
        ("", "Say what to do"),
    ],
)
def test_what_cannot_be_read_says_why_and_never_raises(text: str, fragment: str):
    r = read(text)
    assert r.intent == "unclear" and r.rule is None
    assert fragment in (r.problem or "")


def test_a_tie_between_tools_asks_unless_the_write_in_front_breaks_it():
    tools = TOOLS[:2] + [ToolSpec(name="post_note", kind="write", description="Post a note somewhere else.", args_schema={"type": "object", "properties": {"text": {"type": "string"}}})]
    r = rule_text.read(RuleText(text="hold posts when text contains a sort code"), tools)
    assert r.intent == "unclear" and r.problem.startswith("Which tool: ")
    r = rule_text.read(RuleText(text="hold posts when text contains a sort code", tool="post_note", field="text"), tools)
    assert r.intent == "hold" and r.rule.tool == "post_note"


def test_a_field_that_is_not_named_is_the_only_one_of_its_kind_or_a_question():
    assert read("hold transfers over 100").rule.field == "amount"  # the only number
    assert read("hold post message when it is one of alerts").intent == "unclear"  # two text fields: channel or text?
    r = read("hold post message when it contains x")
    assert r.intent == "unclear" and r.problem == "Which field of Post message: channel or text?"


def test_same_value_ignores_what_json_did_to_types():
    assert rule_text.same_value(10000, 10000.0)
    assert rule_text.same_value(["a", "b"], ["a", "b"]) and not rule_text.same_value(["a"], "a")
    assert rule_text.same_value("\\d", "\\d") and not rule_text.same_value(True, 1)
