import copy

import pytest

from expression_learning import propose
from relational_semantics import RelationalParser


def payload():
    correction = {"text": "하루의 키는 모래의 키를 웃돈다",
                  "slots": {"a": "하루", "b": "모래"},
                  "meaning": {"triple": ["$a", "taller", "$b"]}}
    validation = [
        {"id": "forward", "text": "유나의 키는 미소의 키를 웃돈다",
         "expected": {"facts": [{"triple": ["유나", "taller", "미소"]}], "query": None}},
        {"id": "reversed", "text": "미소의 키는 유나의 키를 웃돈다",
         "expected": {"facts": [{"triple": ["미소", "taller", "유나"]}], "query": None}},
        {"id": "negation", "text": "유나의 키는 미소의 키를 웃돌지 않는다", "expected": None},
    ]
    return correction, validation


def test_validated_correction_reload_and_new_chain_use_actual_engine(tmp_path, monkeypatch):
    import engine
    parser = RelationalParser()
    correction, validation = payload()
    before_rules = copy.deepcopy(parser.data["rules"])
    report = propose(parser, correction, validation)
    assert report["accepted"]
    assert parser.data["rules"] == before_rules
    path = tmp_path / "learned.json"
    parser.save(path)
    monkeypatch.setenv("NAI_RELATIONAL_MODEL", str(path))
    text = "소라의 키는 다미의 키를 웃돈다. 다미는 유리보다 키가 크다. 소라와 유리 중 누가 더 커?"
    assert engine.answer(text)[2] == "소라입니다."
    assert all(name not in str(parser.data) for name in ("유나", "미소", "소라", "다미", "유리"))


def test_validation_failure_does_not_mutate_model_or_compiled_templates():
    parser = RelationalParser()
    correction, validation = payload()
    validation[0]["expected"]["facts"][0]["triple"] = ["미소", "taller", "유나"]
    before = copy.deepcopy(parser.data)
    compiled = list(parser.templates)
    assert not propose(parser, correction, validation)["accepted"]
    assert parser.data == before
    assert parser.templates == compiled


def test_training_entities_and_missing_negative_validation_are_rejected():
    parser = RelationalParser()
    correction, validation = payload()
    with pytest.raises(ValueError, match="positive_and_negative"):
        propose(parser, correction, validation[:2])
    validation[0]["text"] = correction["text"]
    with pytest.raises(ValueError, match="entity_overlap"):
        propose(parser, correction, validation)


def test_cli_only_publishes_successful_validation(tmp_path):
    import json
    from pathlib import Path
    import subprocess
    import sys
    correction, validation = payload()
    source = tmp_path / "correction.json"
    output = tmp_path / "model.json"
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / "semantic_feedback.py"), "expression", str(source),
               "--output", str(output)]
    invalid = copy.deepcopy(validation)
    invalid[0]["expected"]["facts"][0]["triple"] = ["wrong", "taller", "wrong"]
    source.write_text(json.dumps({"correction": correction, "validation": invalid}), encoding="utf-8")
    report = json.loads(subprocess.check_output(command, cwd=root, text=True))
    assert not report["accepted"] and not output.exists()
    source.write_text(json.dumps({"correction": correction, "validation": validation}), encoding="utf-8")
    report = json.loads(subprocess.check_output(command, cwd=root, text=True))
    assert report["accepted"] and output.exists()
    assert report["before_sha256"] != report["after_sha256"]
    published = output.read_bytes()
    source.write_text(json.dumps({"correction": correction, "validation": invalid}), encoding="utf-8")
    subprocess.check_output(command, cwd=root, text=True)
    assert output.read_bytes() == published
