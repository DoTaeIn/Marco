"""Frozen dialogue set v2 (goal X2): schema and replay, composition, hash, scorer self-tests.

Nothing here runs the engine on the set: it is scored once, at the release.
"""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmarks/dialogues_v2"

_spec = importlib.util.spec_from_file_location("dialogue_gate", ROOT / "bench/dialogue_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

LABELS = {"answerable": 108, "hold": 170, "unsupported": 6, "ambiguous": 12, "correction": 18, "why": 26}
PER_LANGUAGE = {"answerable": 54, "hold": 85, "unsupported": 3, "ambiguous": 6, "correction": 9, "why": 13}


@pytest.fixture(scope="module")
def dialogues():
    return gate.load(DATASET)


def test_schema_and_replay(dialogues):
    assert gate.validate(dialogues) == []
    assert len(dialogues) == 52
    assert {code: sum(d["language"] == code for d in dialogues) for code in gate.LANGUAGES} == {"ko": 26, "en": 26}
    assert all(4 <= len(d["turns"]) <= 10 for d in dialogues)
    assert sum(len(d["turns"]) for d in dialogues) == 340


def test_composition(dialogues):
    table = gate.category_table(dialogues)
    assert table["labels"] == LABELS
    for code in gate.LANGUAGES:
        turns = [t for d in dialogues if d["language"] == code for t in d["turns"]]
        assert {label: sum(t["label"] == label for t in turns) for label in gate.LABELS} == PER_LANGUAGE
        assert sum(t["expect"]["act"] == "hold" for t in turns) == 10
    for name in gate.CATEGORIES:
        assert table["categories"][name]["ko"] >= 5, name
        assert table["categories"][name]["en"] >= 5, name
    assert table["categories"]["cross_language"]["dialogues"] == 6


def test_no_name_carries_a_digit(dialogues):
    for d in dialogues:
        for t in d["turns"]:
            for event in t["expect"].get("events", []) + t["expect"].get("with", []):
                for key in ("holder", "from", "to", "item"):
                    assert not any(ch.isdigit() for ch in event.get(key, "")), (d["id"], t["n"])


def test_no_sentence_shared_with_the_repository(dialogues):
    result = gate.overlaps(dialogues, disk_root=str(ROOT), owned=("data/benchmarks/dialogues_v2/",))
    assert result["sentences"] >= 340
    assert result["overlaps"] == []


def test_frozen(dialogues):
    assert gate.frozen_hash(DATASET / "FROZEN.sha256") == gate.tree_hash(DATASET)


def test_perfect_answers_score_everything(dialogues):
    report = gate.score(dialogues, gate.synthesize(dialogues, "perfect"))
    assert report["gate"]["n"] == 108
    assert report["gate"]["correct"] == 108
    assert report["gate"]["needed"] == 98
    assert report["failures"] == []
    assert report["dialogues_fully_passed"] == 52


def test_wrong_answers_score_nothing(dialogues):
    report = gate.score(dialogues, gate.synthesize(dialogues, "wrong"))
    assert report["gate"]["correct"] == 0
    assert all(counts["correct"] == 0 for counts in report["other_labels"].values())
    assert report["dialogues_fully_passed"] == 0


def test_swapping_two_expected_quantities_changes_only_that_dialogue(dialogues):
    answers = gate.synthesize(dialogues, "perfect")
    for index, d in enumerate(dialogues):
        counts = [t for t in d["turns"] if t["expect"]["act"] == "answer" and t["expect"]["relation"] == "count"]
        pair = next(((a, b) for a in counts for b in counts
                     if a["expect"]["quantity"] != b["expect"]["quantity"]), None)
        if pair:
            break
    else:
        pytest.fail("no dialogue with two different count answers")
    swapped = copy.deepcopy(dialogues)
    first, second = (swapped[index]["turns"][t["n"] - 1]["expect"] for t in pair)
    first["quantity"], second["quantity"] = second["quantity"], first["quantity"]
    report = gate.score(swapped, answers)
    assert {row["dialogue"] for row in report["failures"]} == {d["id"]}
    assert report["gate"]["correct"] == 108 - 2
    assert report["dialogues_fully_passed"] == 51
