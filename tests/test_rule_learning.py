import copy

import pytest

from relational_semantics import RelationalParser
from rule_learning import induce, propose


def example(prefix, expected=True, reverse=False):
    a, b, c = (prefix + str(i) for i in range(3))
    return {"id": prefix, "premises": [[a, "taller", b], [b, "taller", c]],
            "conclusion": [c, "taller", a] if reverse else [a, "taller", c], "expected": expected}


def test_induction_retains_variable_identity_across_premises():
    candidate = induce([example("a"), example("b")])
    assert candidate["body"] == [["?v0", "taller", "?v1"], ["?v1", "taller", "?v2"]]
    assert candidate["head"] == ["?v0", "taller", "?v2"]
    # Predicate names are not special to the learner.
    examples = [example("a"), example("b")]
    for e in examples:
        e["premises"][0][1] = "p"
        e["premises"][1][1] = "q"
        e["conclusion"][1] = "r"
    assert induce(examples)["head"][1] == "r"


def test_negative_validation_blocks_overgeneralization_without_mutation():
    model = {"rules": []}
    before = copy.deepcopy(model)
    report = propose(model, [example("a"), example("b")], [example("c"), example("d", False)])
    assert not report["accepted"]
    assert model == before


def test_validation_entities_cannot_be_reused_from_training():
    with pytest.raises(ValueError, match="overlap"):
        propose({"rules": []}, [example("a"), example("b")], [example("a"), example("d", False, True)])


def test_learned_rule_survives_reload_and_changes_actual_runtime(tmp_path, monkeypatch):
    import engine
    parser = RelationalParser()
    # Explicit ablation: recover a deliberately withheld rule, not a production
    # baseline improvement. Templates and all other rules remain available.
    parser.data["rules"] = [r for r in parser.data["rules"] if r["id"] != "strict-height-transitivity"]
    path = tmp_path / "model.json"
    parser.save(path)
    monkeypatch.setenv("NAI_RELATIONAL_MODEL", str(path))
    question = "서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다. 서우와 라온 중 누가 더 커?"
    assert engine.answer(question)[1] == "미지"
    report = parser.learn_rule([example("a"), example("b")], [example("c"), example("d", False, True)])
    assert report["accepted"]
    parser.save(path)
    assert engine.answer(question)[2] == "서우입니다."
    loaded = RelationalParser(model_path=path)
    answer = loaded.answer(loaded.parse(question))
    assert any(step.get("rule", "").startswith("learned-") for step in answer["transitions"])


def test_unconnected_validation_chain_is_not_invented():
    negative = example("z", False)
    negative["premises"][1][0] = "unconnected"
    report = propose({"rules": []}, [example("a"), example("b")], [example("c"), negative])
    assert report["accepted"]


def test_diagnosis_separates_missing_expression_from_missing_rule():
    parser = RelationalParser()
    parser.data["rules"] = []
    assert parser.diagnose("아직 배우지 않은 말")["stage"] == "semantic_parse"
    report = parser.diagnose("서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다. 서우와 라온 중 누가 더 커?")
    assert report["stage"] == "graph_inference"
    assert len(report["facts"]) == 2


@pytest.mark.parametrize("accepted", [False, True])
def test_cli_publishes_only_validated_rule(tmp_path, accepted):
    import json
    from pathlib import Path
    import subprocess
    import sys
    parser = RelationalParser()
    parser.data["rules"] = []
    model = tmp_path / "model.json"
    parser.save(model)
    feedback = tmp_path / "feedback.json"
    feedback.write_text(json.dumps({"corrections": [example("a"), example("b")],
                                    "validation": [example("c"), example("d", False, accepted)]}), encoding="utf-8")
    destination = tmp_path / "candidate.json"
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "semantic_feedback.py"),
               "rule", str(feedback), "--model", str(model), "--output", str(destination)]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    report = json.loads(completed.stdout)
    assert report["accepted"] == accepted
    assert (report["before_sha256"] != report["after_sha256"]) == accepted
    assert destination.exists() == accepted
    if accepted:
        loaded = RelationalParser(model_path=destination)
        assert loaded.diagnose("서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다. 서우와 라온 중 누가 더 커?")["answer"] == "서우입니다."
