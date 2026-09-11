import copy

import pytest

from expression_learning import from_paraphrase, propose_paraphrase
from relational_semantics import RelationalParser


def payload():
    return {"text": "모래에 비하면 하루의 키가 더 크다", "equivalent": "하루는 모래보다 키가 크다",
            "validation": [
                {"id": "new", "text": "미소에 비하면 유나의 키가 더 크다", "equivalent": "유나는 미소보다 키가 크다"},
                {"id": "reverse", "text": "유나에 비하면 미소의 키가 더 크다", "equivalent": "미소는 유나보다 키가 크다"},
                {"id": "negative", "text": "미소에 비하면 유나의 키가 더 크지 않다", "unrecognized": True}]}


def test_role_alignment_is_from_meaning_not_word_order_and_transfers_to_runtime(tmp_path, monkeypatch):
    import engine
    parser = RelationalParser()
    report = propose_paraphrase(parser, payload())
    assert report["accepted"]
    assert report["inferred_annotation"]["meaning"]["triple"] == ["$subject", "taller", "$object"]
    path = tmp_path / "relations.json"
    parser.save(path)
    monkeypatch.setenv("NAI_RELATIONAL_MODEL", str(path))
    result = engine.answer("다미에 비하면 소라의 키가 더 크다. 다미는 유리보다 키가 크다. 소라와 유리 중 누가 더 커?")
    assert result[2] == "소라입니다."
    assert "소라" not in str(parser.data)


def test_wrong_validation_cannot_publish_or_change_parser():
    parser = RelationalParser()
    data = payload()
    data["validation"][0]["equivalent"] = "미소는 유나보다 키가 크다"
    before = copy.deepcopy(parser.data)
    assert not propose_paraphrase(parser, data)["accepted"]
    assert parser.data == before


def test_unknown_reference_and_missing_shared_entities_require_clarification():
    parser = RelationalParser()
    with pytest.raises(ValueError, match="one_known_fact"):
        from_paraphrase(parser, "새 표현", "이 표현도 아직 모른다")
    with pytest.raises(ValueError, match="shared_entities"):
        from_paraphrase(parser, "그 사람이 더 크다", "하루는 모래보다 키가 크다")


def test_negative_reference_keeps_polarity_without_manual_triple_annotation():
    parser = RelationalParser()
    correction = from_paraphrase(parser, "하루의 키는 모래를 넘지 않는다", "하루는 모래보다 키가 크지 않다")
    assert correction["meaning"]["polarity"] is False
    assert correction["meaning"]["triple"] == ["$subject", "taller", "$object"]


def test_quantity_paraphrase_infers_numeric_slot_and_composes_with_events(tmp_path, monkeypatch):
    import engine
    parser = RelationalParser()
    data = {"text": "구슬은 18개 남아있다", "equivalent": "구슬은 18개 있다",
            "validation": [
                {"text": "공은 27개 남아있다", "equivalent": "공은 27개 있다"},
                {"text": "공은 여러 개 남아있다", "unrecognized": True}]}
    assert propose_paraphrase(parser, data)["accepted"]
    path = tmp_path / "model.json"
    parser.save(path)
    monkeypatch.setenv("NAI_RELATIONAL_MODEL", str(path))
    assert engine.answer("돌은 서른두 개 남아있다. 돌 다섯 개를 꺼냈다. 지금 돌은 몇 개야?")[2] == "27개입니다."


def test_cli_accepts_sentence_pairs_without_explicit_semantic_annotations(tmp_path):
    import json
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    source, output = tmp_path / "pairs.json", tmp_path / "model.json"
    source.write_text(json.dumps(payload(), ensure_ascii=False), encoding="utf-8")
    result = subprocess.check_output([sys.executable, str(root / "semantic_feedback.py"), "paraphrase",
                                      str(source), "--output", str(output)], text=True, cwd=root)
    assert json.loads(result)["accepted"]
    restored = RelationalParser(model_path=output)
    assert restored.parse("다미에 비하면 소라의 키가 더 크다", partial=True)["facts"][0]["triple"] == ["소라", "taller", "다미"]
