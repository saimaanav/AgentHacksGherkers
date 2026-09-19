"""A rule in a person's words, read into a rule the layer can save. No model: a small grammar over the tools' names and fields.

    always hold <tool> when <field> contains <words | a pattern the layer knows | "exact words" | /regex/>
    hold <tool> when <field> is over <number>            is under · is one of a, b · is not one of a, b
    it's fine if <field> contains <words>                don't hold <tool> when …    (an exception: no rule)

Where a sentence names no tool or field, it is about the write in front of the person; the popup passes those
along as hints. The reading comes back in plain words so the person can check it before anything is saved.
"""

from __future__ import annotations

import re
from typing import Any

from pakka.learning import RULE_PATTERNS
from pakka.models import RuleReading, RuleRequest, RuleText, ToolSpec

# ---------------------------------------------------------------------------
# The grammar
# ---------------------------------------------------------------------------

FILLER_RE = re.compile(r"^(?:(?:from now on|in future|going forward|please|and|also|so|then|ok|okay)\b[\s,:]*)+", re.I)
ALLOW_RE = re.compile(
    r"^(?:it'?s\s+fine|it\s+is\s+fine|that'?s\s+fine|fine|ok(?:ay)?|allow|accept|permit|let\s+(?:it\s+|them\s+|these\s+)?through|"
    r"(?:don'?t|do\s+not|never|stop|no\s+need\s+to)\s+(?:hold(?:ing)?|stop(?:ping)?|flag(?:ging)?|block(?:ing)?|ask(?:ing)?)(?:\s+(?:me|it|them|about\s+it|about\s+this|this))?|"
    r"pass|wave\s+through|no\s+rule(?:\s+for)?)\b[\s,:]*",
    re.I,
)
HOLD_RE = re.compile(
    r"^(?:(?:always|still)\s+)?(?:hold(?:\s+back|\s+up)?|stop|flag|check|review|block|catch|pause|"
    r"(?:don'?t|do\s+not|never)\s+(?:send|let\s+through|pass|allow)|ask\s+me(?:\s+first|\s+about)?|show\s+me)\b[\s,:]*",
    re.I,
)
HOLD_TAIL_RE = re.compile(
    r"\b(?:should|must|need(?:s)?\s+to)\s+be\s+(?:held|checked|reviewed|flagged|stopped|blocked)\b[.\s]*$|"
    r"\b(?:needs?|requires?)\s+(?:a\s+)?(?:review|approval|sign-?off|a\s+look)\b[.\s]*$",
    re.I,
)
LEAD_RE = re.compile(r"^(?:me\s+)?(?:about\s+|on\s+|for\s+)?(?:every|any|all|each|the|an?|this|these|those)?\s*", re.I)
# condition phrases by kind; the regex tries them longest first so "is not one of" beats "is" and "is over" beats "is"
OP_PHRASES: dict[str, list[str]] = {
    "not_in": [r"is\s+not\s+(?:one|any)\s+of", r"isn'?t\s+(?:one|any)\s+of", r"is\s+none\s+of", r"is\s+not\s+in", r"is\s+neither", r"not\s+in", r"is\s+not", r"isn'?t"],
    "in": [r"is\s+(?:one|any|either)\s+of", r"is\s+equal\s+to", r"is\s+exactly", r"is\s+in", r"equals", r"is", r"in", r"=+"],
    "gt": [r"is\s+(?:over|above|more\s+than|greater\s+than|larger\s+than|bigger\s+than|higher\s+than)", r"more\s+than", r"greater\s+than", r"larger\s+than", r"bigger\s+than", r"higher\s+than", r"exceed(?:s|ing)?", r"over", r"above", r">"],
    "lt": [r"is\s+(?:under|below|less\s+than|smaller\s+than|lower\s+than)", r"less\s+than", r"smaller\s+than", r"lower\s+than", r"under", r"below", r"<"],
    "matches": [r"contain(?:s|ing)?", r"include(?:s|ing)?", r"mention(?:s|ing)?", r"match(?:es|ing)?", r"having", r"has", r"have", r"saying", r"says", r"say", r"reads", r"read"],
}
_ALL_PHRASES = sorted(((p, kind) for kind, ps in OP_PHRASES.items() for p in ps), key=lambda x: -len(x[0]))
OP_RE = re.compile("|".join(rf"(?<![\w])(?:{p})(?![\w])" if not p.startswith(("=", ">", "<")) else p for p, _ in _ALL_PHRASES), re.I)
OP_KIND: list[tuple[re.Pattern[str], str]] = [(re.compile(rf"^(?:{p})$", re.I), kind) for p, kind in _ALL_PHRASES]
LINK_RE = re.compile(r"\b(?:when(?:ever)?|if|whose|where|that|which)\b", re.I)
WITH_RE = re.compile(r"\b(?:with|containing|mentioning|including)\b", re.I)
IN_FIELD_RE = re.compile(r"\s+in\s+(?:its|the|their|any|an?)?\s*([a-z][a-z_ ]*?)\s*$", re.I)
OP_WORDS = {"matches": "contains", "gt": "is over", "lt": "is under", "in": "is one of", "not_in": "is not one of"}
STOP = {
    "a", "an", "the", "of", "to", "for", "from", "in", "on", "at", "by", "with", "and", "or", "is", "are", "be", "it", "its",
    "this", "that", "these", "those", "any", "every", "each", "all", "one", "when", "if", "as", "into", "returns", "return",
    "id", "new", "given", "exactly", "then", "than", "your", "our", "their", "my", "me", "them", "up", "out", "toolref",
}
FORMS = "“always hold ‹tool› when ‹field› contains ‹words›”, “hold ‹tool› when ‹field› is over ‹number›”, “hold ‹tool› when ‹field› is one of a, b” or “it's fine if ‹field› contains ‹words›”"


def human(name: str) -> str:
    s = str(name or "").replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def _stem(word: str) -> str:
    w = word.lower().strip("'’\"“”.,;:!?()")
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def _words(text: str) -> list[str]:
    return [w for w in (_stem(t) for t in re.split(r"[\s/_\-]+", text)) if w and w not in STOP]


def _norm_label(text: str) -> str:
    words = [w for w in re.split(r"\s+", text.strip().lower()) if w]
    while words and words[0] in ("a", "an", "the", "any", "some"):
        words.pop(0)
    return " ".join(_stem(w) for w in words)


# ---------------------------------------------------------------------------
# Resolving the tool, the field, the value
# ---------------------------------------------------------------------------


def _mask_tool(text: str, tools: list[ToolSpec]) -> tuple[str, str | None]:
    """A tool named in full becomes one token, so its own words are never read as the condition."""
    low = text.lower()
    for t in sorted(tools, key=lambda t: -len(t.name)):
        for form in (t.name.lower(), t.name.replace("_", " ").lower()):
            i = low.find(form)
            if i >= 0 and (i == 0 or not low[i - 1].isalnum()) and (i + len(form) == len(low) or not low[i + len(form)].isalnum()):
                return text[:i] + "TOOLREF" + text[i + len(form) :], t.name
    return text, None


def _tool_scores(part: str, tools: list[ToolSpec]) -> dict[str, int]:
    """How much of each tool's name (×2) and description (×1) the words in `part` cover."""
    words = set(_words(part))
    scores: dict[str, int] = {}
    for t in tools:
        name_words = set(_words(t.name))
        desc_words = set(_words(t.description)) - name_words
        score = 2 * len(words & name_words) + len(words & desc_words)
        if score:
            scores[t.name] = score
    return scores


def _resolve_tool(part: str, tools: list[ToolSpec], hint: str | None) -> tuple[str | None, str | None]:
    """(tool name or "*", problem)."""
    scores = _tool_scores(part, tools)
    if scores:
        best = max(scores.values())
        winners = [n for n, s in scores.items() if s == best]
        if len(winners) == 1:
            return winners[0], None
        if hint in winners:  # the write in front of the person breaks the tie
            return hint, None
        return None, "Which tool: " + " or ".join(human(w) for w in winners) + "?"
    if hint and any(t.name == hint for t in tools):
        return hint, None
    return "*", None


def _fields(tool: str | None, tools: list[ToolSpec]) -> dict[str, dict[str, Any]]:
    if tool == "*" or tool is None:
        out: dict[str, dict[str, Any]] = {}
        for t in tools:
            for name, schema in (t.args_schema.get("properties") or {}).items():
                out.setdefault(name, schema)
        return out
    spec = next((t for t in tools if t.name == tool), None)
    return dict((spec.args_schema.get("properties") or {}) if spec else {})


def _is_numeric(schema: dict[str, Any]) -> bool:
    jtype = schema.get("type")
    if isinstance(jtype, list):
        jtype = next((t for t in jtype if t != "null"), None)
    if jtype is None and "anyOf" in schema:
        jtype = next((o.get("type") for o in schema["anyOf"] if o.get("type") not in (None, "null")), None)
    return jtype in ("number", "integer")


def _resolve_field(part: str, tool: str, tools: list[ToolSpec], op: str, hint: str | None) -> tuple[str | None, str | None]:
    """(field, problem). A named field wins; then the hint; then the only field of the right kind."""
    fields = _fields(tool, tools)
    words = set(_words(part))
    flat = " " + re.sub(r"[\s_]+", " ", part.lower()) + " "
    named = [f for f in fields if f" {f.replace('_', ' ').lower()} " in flat or _stem(f) in words]
    if len(named) > 1:  # the one nearest the condition is the one it is about
        named.sort(key=lambda f: max(flat.rfind(f" {f.replace('_', ' ').lower()} "), flat.rfind(" " + _stem(f))))
    if named:
        return named[-1], None
    if hint and hint in fields:
        return hint, None
    if tool == "*":
        return None, "Name the field, for example “when amount is over 10000”, or name the tool."
    wanted = [f for f, s in fields.items() if _is_numeric(s)] if op in ("gt", "lt") else [f for f, s in fields.items() if not _is_numeric(s)]
    if len(wanted) == 1:
        return wanted[0], None
    options = wanted or list(fields)
    if not options:
        return None, f"{human(tool)} has no fields a rule could check."
    if len(options) == 1:
        return None, f"Which field of {human(tool)}: {human(options[0]).lower()}?"
    return None, f"Which field of {human(tool)}: " + ", ".join(human(f).lower() for f in options[:-1]) + f" or {human(options[-1]).lower()}?"


def _number(text: str) -> float | int | None:
    s = text.strip().lower().replace(",", "").replace(" ", "").rstrip(".")
    s = re.sub(r"^[£$€¥]|^[a-z]{3}(?=\d)", "", s)  # a currency sign or code up front is the person's, not the layer's
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(k|m|bn|b)?", s)
    if not m:
        return None
    n = float(m.group(1)) * {"k": 1e3, "m": 1e6, "b": 1e9, "bn": 1e9, None: 1}[m.group(2)]
    return int(n) if n == int(n) else n


def _unquote(text: str) -> tuple[str, bool]:
    m = re.fullmatch(r"\s*[\"“”'‘’](.+?)[\"“”'‘’]\s*", text)
    return (m.group(1), True) if m else (text.strip(), False)


def _pattern(value: str) -> tuple[str, str, str]:
    """(regex, words for the reading, label) for a `contains` value: a known pattern, a /regex/, or the exact words."""
    raw = value.strip().rstrip(".!")
    m = re.fullmatch(r"/(.+)/[a-z]*", raw)
    if m:
        return m.group(1), f"/{m.group(1)}/", f"/{m.group(1)}/"
    inner, quoted = _unquote(raw)
    if not quoted:
        norm = _norm_label(inner)
        for label, regex in RULE_PATTERNS:
            if norm == _norm_label(label):
                return regex, label, label
    words = f"“{inner}”"
    return re.escape(inner).replace("\\ ", " "), words, words


def _list(value: str) -> list[str]:
    parts = re.split(r"\s*,\s*|\s+or\s+|\s+and\s+|\s*/\s*|\s*\|\s*", value.strip().rstrip("."))
    return [_unquote(p)[0] for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# The reading
# ---------------------------------------------------------------------------


def _unclear(req: RuleText, problem: str, *, tool: str | None = None, field: str | None = None) -> RuleReading:
    return RuleReading(text=req.text, intent="unclear", tool=tool, field=field, problem=problem)


def read(req: RuleText, tools: list[ToolSpec]) -> RuleReading:
    """Read a person's sentence against these write tools. Never raises: an unreadable sentence is an `unclear` reading."""
    text = re.sub(r"\s+", " ", req.text.strip())
    if not text:
        return _unclear(req, "Say what to do, for example " + FORMS + ".")
    text = FILLER_RE.sub("", text)
    m = ALLOW_RE.match(text)
    if m:
        intent, rest = "allow", text[m.end() :]
    else:
        m = HOLD_RE.match(text)
        if m:
            intent, rest = "hold", text[m.end() :]
        elif HOLD_TAIL_RE.search(text):
            intent, rest = "hold", HOLD_TAIL_RE.sub("", text)
        else:
            return _unclear(req, "Start with what to do: " + FORMS + ".")
    rest = LEAD_RE.sub("", rest.strip(), count=1)
    rest, named_tool = _mask_tool(rest, tools)

    # the condition: <head> <op> <value>. It sits after the first link word if there is one.
    link = LINK_RE.search(rest)
    start = link.end() if link else 0
    om = OP_RE.search(rest, start)
    wm = WITH_RE.search(rest, start)
    if wm is not None and (om is None or wm.start() < om.start()):
        head, op, value = rest[: wm.start()], "matches", rest[wm.end() :]
    elif om is not None:
        head, value = rest[: om.start()], rest[om.end() :]
        op = next(kind for pat, kind in OP_KIND if pat.match(om.group(0)))
    else:
        tool, _ = (named_tool, None) if named_tool else _resolve_tool(rest, tools, req.tool)
        return _unclear(req, "Say the condition: “… when ‹field› contains ‹words›”, “… when ‹field› is over ‹number›” or “… when ‹field› is one of a, b”.", tool=tool)
    value = value.strip()
    if op == "matches":
        tail = IN_FIELD_RE.search(value)
        if tail:
            value, head = value[: tail.start()], head + " " + tail.group(1)

    # what it is about: the tool before the link word, the field after it
    lm = LINK_RE.search(head)
    tool_part, field_part = (head[: lm.start()], head[lm.end() :]) if lm else (head, head)
    if named_tool:
        tool: str | None = named_tool
    else:
        tool, problem = _resolve_tool(tool_part, tools, req.tool)
        if problem:
            return _unclear(req, problem)
    assert tool is not None
    field, problem = _resolve_field(field_part, tool, tools, op, req.field if tool in (req.tool, "*") else None)
    if problem:
        return _unclear(req, problem, tool=tool)
    assert field is not None

    # the value, by op
    label: str | None = None
    parsed: Any
    if not value:
        return _unclear(req, f"What should {human(field).lower()} {OP_WORDS[op]}? Finish the sentence.", tool=tool, field=field)
    if op == "matches":
        regex, words, label = _pattern(value)
        try:
            re.compile(regex)
        except re.error as e:
            return _unclear(req, f"That pattern doesn't compile: {e}.", tool=tool, field=field)
        parsed = regex
    elif op in ("gt", "lt"):
        n = _number(value)
        if n is None:
            return _unclear(req, f"“{value}” isn't a number the layer can compare; try 10000 or £10k.", tool=tool, field=field)
        parsed, words = n, f"{n:,}" if isinstance(n, int) else f"{n:,.2f}"
    else:
        parsed = _list(value)
        if not parsed:
            return _unclear(req, "List the values, separated by commas.", tool=tool, field=field)
        words = ", ".join(parsed)

    subject = "any tool" if tool == "*" else human(tool)
    if intent == "hold":
        sentence = f"Hold {subject} when {human(field).lower()} {OP_WORDS[op]} {words}"
    else:
        sentence = f"It's fine when {human(field).lower()} {OP_WORDS[op]} {words}" + ("" if tool == "*" else f" in {subject}")
    return RuleReading(
        text=req.text,
        intent=intent,  # type: ignore[arg-type]
        rule=RuleRequest(tool=tool, field=field, op=op, value=parsed, label=label),  # type: ignore[arg-type]
        tool=tool,
        field=field,
        sentence=sentence,
        pattern=parsed if op == "matches" else None,
    )


def same_value(a: Any, b: Any) -> bool:
    """Whether two rules' values say the same thing, whatever JSON did to their types on the way."""
    if isinstance(a, list) or isinstance(b, list):
        return isinstance(a, list) and isinstance(b, list) and [str(x) for x in a] == [str(x) for x in b]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return float(a) == float(b)
    return str(a) == str(b)
