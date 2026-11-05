"""Compose one asserted statement from a parser's declared examples.

The text comes only from a parser's annotated examples and template slots; no
observed source sentence is ever consulted. The result is accepted only when
the parser strictly reads it back as exactly the target positive asserted
triple. Unfilled or unknown slots yield ``None`` (a hold), never a guess.

A bare triple carries no time. An example is eligible only when the selected
model explicitly declares ``source_answer.temporal`` as ``neutral`` or
``timeless``. This is an output interpretation declaration, not sourced time.
Explicit temporal realization requires a richer conclusion and is held here.
"""
from __future__ import annotations

import re

from marco.language.hangul import fix_particles

_OTHER_MEANING = ("정의", "사건", "가정사건", "조건", "가정", "원인", "이유물음", "수선", "사건정정")


def _triple(value):
    return (isinstance(value, (list, tuple)) and len(value) == 3
            and all(isinstance(item, str) and item and len(item) <= 2000 for item in value))


def _bind(pattern, target):
    """Exact binding of a length-3 template triple; ``$name`` terms are slots."""
    bound = {}
    for term, value in zip(pattern, target):
        if term.startswith("$") and len(term) > 1:
            if bound.setdefault(term[1:], value) != value:
                return None
        elif term != value:
            return None
    return bound


def _declared_output_time(example):
    declared = example.get("source_answer")
    inflection = example.get("inflection") or {}
    return (isinstance(declared, dict) and set(declared) == {"temporal"}
            and isinstance(declared["temporal"], str)
            and declared["temporal"] in {"neutral", "timeless"}
            and isinstance(inflection, dict)
            # A neutral marker cannot override an explicitly timed template.
            # A bare target has no temporal value with which to justify it.
            and inflection.get("tense") is None and not inflection.get("tenses"))


def has_declared_output_time(parser, target):
    """Whether this selected model declares a neutral realization for target."""
    if not _triple(target):
        return False
    for example in parser.data.get("examples", []):
        pattern = (example.get("meaning") or {}).get("triple")
        if (_triple(pattern) and _declared_output_time(example)
                and _bind(pattern, target) is not None):
            return True
    return False


def _plain_fact_reading(parsed):
    return (isinstance(parsed, dict) and isinstance(parsed.get("facts"), list)
            and not parsed.get("query") and not any(parsed.get(key) for key in _OTHER_MEANING))


def statement_matches(parser, text, target):
    """True only if ``text`` reads as exactly one asserted positive ``target``."""
    if not isinstance(text, str) or not text.strip() or not _triple(target):
        return False
    parsed = parser.parse(text, partial=True)
    if not _plain_fact_reading(parsed) or len(parsed["facts"]) != 1:
        return False
    fact = parsed["facts"][0]
    return (tuple(fact.get("triple") or ()) == tuple(target) and fact.get("polarity", True) is True
            and fact.get("modality", "asserted") == "asserted")


def compose_statement(parser, target):
    """Return a round-trip-verified statement for ``target`` or ``None``."""
    if not _triple(target):
        return None
    for example in parser.data.get("examples", []):
        meaning, slots = example.get("meaning") or {}, example.get("slots") or {}
        pattern, text = meaning.get("triple"), example.get("text")
        if (not _triple(pattern) or not isinstance(text, str) or not slots
                or not _declared_output_time(example)
                or meaning.get("polarity", True) is not True
                or meaning.get("modality", "asserted") != "asserted" or meaning.get("scope") is not None
                or set(meaning) - {"triple", "polarity", "modality", "scope"}):
            continue
        bound = _bind(pattern, target)
        if bound is None or any(key not in bound for key in slots):
            continue
        literals = {}
        for key, literal in slots.items():
            if not isinstance(literal, str) or not literal or literals.setdefault(literal, bound[key]) != bound[key]:
                literals = None
                break
        if not literals or any(literal not in text for literal in literals):
            continue
        # One left-to-right pass over source spans, longest literal first, so a
        # literal nested in another is never replaced inside an earlier result.
        spans = "|".join(re.escape(literal) for literal in sorted(literals, key=len, reverse=True))
        statement = re.sub(spans, lambda match: literals[match.group()], text)
        statement = fix_particles(statement, list(literals.values())).rstrip(".!?") + "."
        if statement_matches(parser, statement, target):
            return statement
    return None
