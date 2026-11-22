# -*- coding: utf-8 -*-
"""The runtime law, checked mechanically.

These tests are the ones an auditor should run first.  They do not ask whether
the reading is good; they ask whether language knowledge is where the contract
says it is, whether every policy refers to evidence that exists, and whether
the import graph of the core stays inside the standard library and the one
existing search helper.
"""
import ast
import json
import os
import sys

import pytest

from experiments.graph_language_repair.core import comparators, load_graphs

CORE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
GRAPH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "graphs", "core")

FORBIDDEN_IMPORTS = ("torch", "tensorflow", "numpy", "scipy", "sklearn", "transformers",
                     "sentencepiece", "tokenizers", "openai", "anthro" + "pic", "requests",
                     "urllib", "http", "socket", "konlpy", "mecab", "kiwipiepy", "nltk",
                     "spacy", "gensim", "fasttext")

ALLOWED_NON_STDLIB = ("experiments.graph_language_repair",
                      "marco.reasoning.relation_hypotheses")


def _core_modules():
    for name in sorted(os.listdir(CORE_DIR)):
        if name.endswith(".py"):
            yield os.path.join(CORE_DIR, name)


def _parsed(path):
    with open(path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def _is_hangul(character):
    return "가" <= character <= "힣" or "ᄀ" <= character <= "ᇿ"


def _docstring_nodes(tree):
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        body = getattr(node, "body", ())
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            found.add(id(body[0].value))
    return found


@pytest.mark.parametrize("path", list(_core_modules()))
def test_no_language_form_is_hardcoded_in_python(path):
    """C10: no string literal the core runs on may hold a language form.

    Docstrings are exempt — they explain the mechanism and are not read at
    runtime.  Everything else must come from ``graphs/core/``.
    """
    tree = _parsed(path)
    exempt = _docstring_nodes(tree)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in exempt:
            continue
        if any(_is_hangul(character) for character in node.value):
            offenders.append((node.lineno, node.value))
    assert offenders == [], "%s hardcodes language forms: %r" % (path, offenders)


@pytest.mark.parametrize("path", list(_core_modules()))
def test_core_imports_only_stdlib_and_the_existing_search(path):
    tree = _parsed(path)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        root = name.split(".")[0]
        assert root not in FORBIDDEN_IMPORTS, "%s imports %s" % (path, name)
        if name.startswith(ALLOWED_NON_STDLIB):
            continue
        assert root in sys.stdlib_module_names, "%s imports non-stdlib %s" % (path, name)


def test_the_existing_search_is_used_and_not_reimplemented():
    from experiments.graph_language_repair.core import search
    from marco.reasoning import relation_hypotheses
    assert search._evaluate_world is relation_hypotheses._evaluate_world
    source = ast.unparse(_parsed(os.path.join(CORE_DIR, "search.py")))
    for word in ("def _evaluate_world", "closure_with_provenance", "def unify"):
        assert word not in source


def test_every_graph_file_loads_and_declares_its_schema():
    store = load_graphs()
    assert store.files
    for name in os.listdir(GRAPH_DIR):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(GRAPH_DIR, name), "r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["schema"] == "graph-language-repair-graph-v1"
        assert isinstance(document.get("note"), str) and document["note"]


def test_every_declared_comparator_exists():
    store = load_graphs()
    for kind in ("identity_evidence", "link_evidence", "verification_evidence"):
        records = store.of_kind(kind)
        assert records, kind
        for record in records:
            assert record["comparator"] in comparators.REGISTRY, record["key"]


def test_every_policy_rule_refers_to_a_declared_label():
    store = load_graphs()
    labels = set()
    for kind in ("identity_evidence", "link_evidence", "verification_evidence"):
        for record in store.of_kind(kind):
            labels.add(record.get("label", record["key"]))
    for record in store.of_kind("policy"):
        for section in ("accept_rules", "reject_rules", "candidate_rules", "ambiguity_rules"):
            for rule in record.get(section, ()):
                for label in list(rule.get("all_of", ())) + list(rule.get("any_of", ())):
                    assert label in labels, "%s: %s refers to %r" % (record["key"],
                                                                     rule.get("id"), label)
        for label in record.get("insufficient_alone", ()):
            assert label in labels, "%s: %r" % (record["key"], label)


def test_item_identity_is_declared_insufficient_on_its_own():
    """C1 as data: the policy itself must say so."""
    store = load_graphs()
    policy = store.get("event-link:rules")
    insufficient = set(policy["insufficient_alone"])
    assert {"shared_item_mention", "entity_identity"} <= insufficient


def test_no_accept_rule_can_fire_on_insufficient_labels_alone():
    store = load_graphs()
    policy = store.get("event-link:rules")
    insufficient = set(policy["insufficient_alone"])
    for rule in policy["accept_rules"]:
        used = set(rule.get("all_of", ())) | set(rule.get("any_of", ()))
        assert not used <= insufficient, rule.get("id")


def test_a_report_scope_is_never_verification_eligible():
    """C5 as data."""
    store = load_graphs()
    for record in store.of_kind("scope_kind"):
        if record["label"] in ("reported_claim", "attribution"):
            assert record["verification_eligible"] is False
            assert record["truth_claimed_by_document"] is False
    policy = store.get("verification:rules")
    assert set(policy["forbidden_source_scopes"]) >= {"reported_claim", "attribution"}
    assert policy["requires_scope_kind"] == "checking_action"


def test_marker_classes_are_mapped_by_frames_not_by_markers():
    """A marker record may not name a role; only a frame may."""
    store = load_graphs()
    roles = set()
    for frame in store.of_kind("frame"):
        for mapping in frame["roles"].values():
            roles.update(mapping.values())
    for marker in store.of_kind("marker"):
        assert not set(marker["classes"]) & roles, marker["key"]


def test_limits_are_declared_and_finite():
    store = load_graphs()
    limits = store.limits()
    for key, value in limits.items():
        if key in ("key", "kind") or key.startswith("note"):
            continue
        assert isinstance(value, int) and value > 0, key
    # the per-clause reading cap must stay under the existing engine's support
    # limit, or per-reading copies of one row can push a projection into
    # support_limit before any question is asked
    from marco.reasoning import relation_hypotheses
    assert limits["max_solutions_per_segment"] < relation_hypotheses._SUPPORT_LIMIT
    assert limits["max_rival_readings_per_clause"] < relation_hypotheses._SUPPORT_LIMIT


def test_a_caller_may_not_shadow_a_core_record():
    from experiments.graph_language_repair.core import GraphDataError
    with pytest.raises(GraphDataError):
        load_graphs(extra_graphs=[[{"key": "marker:가", "kind": "marker", "forms": ["가"],
                                    "classes": ["subject"], "attachment": "closing"}]])
