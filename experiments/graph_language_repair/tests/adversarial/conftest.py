# -*- coding: utf-8 -*-
"""Shared helpers for the public adversarial controls in this directory.

These are frozen development tests for the documented public interface in
``experiments/graph_language_repair/CONTRACT.md`` (``read_text``,
``search_rows``, the reading-document schema). They exercise the mechanism
end to end through that interface only -- no private evaluation cases, no
golds, no author/core-internal helpers.

PASSING THESE TESTS IS NOT INDEPENDENT BENCHMARK EVIDENCE. They are written
by a development-side agent as regression controls over the public contract,
not a blinded evaluation. the evaluator's separately frozen, blinded evaluation is
the only evidence of real performance on unseen cases.

If ``experiments.graph_language_repair.core`` does not yet export
``read_text``/``search_rows`` (CONTRACT.md #0), every test in this directory
is skipped with an explicit "dependency unavailable" message rather than
failing or inventing a stand-in core.

This module imports real ``pytest`` when it is installed for the running
interpreter, and degrades to plain functions (no fixture injection, no
``pytest.skip``) when it is not, so that ``run_controls.py`` in this same
directory -- a standard-library-only runner -- can import this file and call
``_core_interface()`` directly without requiring pytest. Behaviour under a
real pytest install is unchanged either way.
"""

try:
    import pytest
except ImportError:  # pragma: no cover - exercised only without pytest installed
    pytest = None


class _DependencyUnavailable(Exception):
    """experiments.graph_language_repair.core does not yet export
    read_text/search_rows (CONTRACT.md #0)."""


def _core_interface():
    try:
        from experiments.graph_language_repair.core import read_text, search_rows
    except ImportError as exc:
        message = (
            "experiments.graph_language_repair.core does not yet export "
            "read_text/search_rows (CONTRACT.md #0): %r" % (exc,)
        )
        if pytest is not None:
            pytest.skip(message)
        raise _DependencyUnavailable(message) from exc
    return read_text, search_rows


_fixture = pytest.fixture if pytest is not None else (lambda fn: fn)


@_fixture
def read_text():
    fn, _ = _core_interface()
    return fn


@_fixture
def search_rows():
    _, fn = _core_interface()
    return fn


def _questions_interface():
    try:
        from experiments.graph_language_repair.questions.compile import compile_question
        from experiments.graph_language_repair.questions.select import execute_plan
        from experiments.graph_language_repair.questions.respond import render
    except ImportError as exc:
        message = (
            "experiments.graph_language_repair.questions does not yet "
            "expose compile_question/execute_plan/render: %r" % (exc,)
        )
        if pytest is not None:
            pytest.skip(message)
        raise _DependencyUnavailable(message) from exc
    return compile_question, execute_plan, render


@_fixture
def compile_question():
    fn, _, _ = _questions_interface()
    return fn


@_fixture
def execute_plan():
    _, fn, _ = _questions_interface()
    return fn


@_fixture
def render():
    _, _, fn = _questions_interface()
    return fn


def ask(compile_question, execute_plan, render, reading, question_text):
    """End-to-end helper: question text + reading -> (plan, result, rendered
    text). Only touches the public functions above -- no reimplementation of
    compilation, selection or rendering."""
    plan = compile_question(question_text)
    result = execute_plan(plan, reading)
    rendered = render(result, plan)
    return plan, result, rendered


def ordered_events(reading):
    """Events in document order, per CONTRACT #3 (event ids are allocation
    order, never derived from a value)."""
    return sorted(reading["events"], key=lambda ev: ev["span"][0])


def rows_matching(reading, subject=None, predicate=None, obj=None):
    """Filter ``reading["rows"]`` by triple components. A plain filter over
    an already-produced list -- no inference, no grammar, no private case
    data."""
    out = []
    for row in reading["rows"]:
        s, p, o = row["triple"]
        if subject is not None and s != subject:
            continue
        if predicate is not None and p != predicate:
            continue
        if obj is not None and o != obj:
            continue
        out.append(row)
    return out


def claim_scope_kind(reading, claim_id):
    rows = rows_matching(reading, subject=claim_id, predicate="scope_kind")
    return rows[0]["triple"][2] if rows else None


def event_claim(reading, event_id):
    rows = rows_matching(reading, subject=event_id, predicate="in_claim")
    return rows[0]["triple"][2] if rows else None


def entity_of_mention(reading, mention_id):
    for row in reading["rows"]:
        s, p, o = row["triple"]
        if s == mention_id and p == "mention_of":
            return o
    return None


def identity_key(reading, mention):
    """A comparable identity for a mention: its merged entity if one was
    explicitly emitted, otherwise the mention itself. Using the bare mention
    id as a fallback (instead of treating two absent entity ids as equal)
    keeps a "must stay distinct" assertion meaningful even when no entity
    row was emitted at all."""
    entity = entity_of_mention(reading, mention["id"])
    return entity if entity is not None else ("mention", mention["id"])


def span_within(span, outer):
    return outer[0] <= span[0] and span[1] <= outer[1]


def assert_exact_value_spans(reading):
    """CONTRACT C3: text[start:end] == value for every role and value row."""
    text = reading["text"]
    for role in reading.get("roles", []):
        start, end = role["value_span"]
        got = text[start:end]
        assert got == role["value"], (
            "C3 violated: role %r on %s span %r -> %r != %r"
            % (role["role"], role["event"], role["value_span"], got, role["value"])
        )


def query(search_rows, reading, triple):
    world = search_rows(reading, list(triple))
    assert world is not None, "search_rows gave no world for %r" % (triple,)
    return world


def bound_values(world, var="?x"):
    return sorted({m["bindings"][var] for m in world["matches"] if var in m["bindings"]})


def source_refs_for(world, var_value, var="?x"):
    by_id = {d["premise_id"]: d for d in world["fact_sources"]}
    refs = []
    for match in world["matches"]:
        if match["bindings"].get(var) != var_value:
            continue
        for support_id in match["support_ids"]:
            descriptor = by_id.get(support_id)
            if descriptor is not None and descriptor.get("source_ref") is not None:
                refs.append(descriptor["source_ref"])
    return refs
