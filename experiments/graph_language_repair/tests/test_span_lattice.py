"""Public controls for case-like name endings and adjunct ownership."""
import pytest
from experiments.graph_language_repair.core import load_graphs, read_text


def values(document, role):
    return {row["value"] for row in document["roles"] if row["role"] == role}


@pytest.mark.parametrize("text,role,whole,part", [
    ("어제 미린이 도면을 색인했다.", "actor", "어제 미린", "미린"),
    ("미린이 오늘 도면을 색인했다.", "object", "오늘 도면", "도면"),
])
def test_declared_adjunct_and_literal_value_are_distinct_readings(text, role, whole, part):
    document = read_text(text)
    assert {whole, part} <= values(document, role)
    assert document["limits"]["complete"] is True
    temporal = next(row for row in document["roles"] if row["role"] == "time")
    assert temporal["proof"]
    proof = next(item for item in document["proofs"] if item["id"] == temporal["proof"])
    assert load_graphs().has(proof["policy"])
    assert proof["kind"] == "construction_element"
    assert text[slice(*temporal["value_span"])] == temporal["value"]
    assert all(item["competes_with"] for item in document["readings"])


def test_incompatible_allomorph_preserves_multiword_name():
    document = read_text("마을 기록 담당자가 도면을 색인했다.")
    assert "마을 기록 담당자" in values(document, "actor")
    assert "마" not in values(document, "object")
    assert values(document, "object") == {"도면"}


@pytest.mark.parametrize("title", ["섬을 담당자", "밭이 기록 담당자"])
def test_compatible_marker_and_literal_name_stay_competing(title):
    document = read_text(title + "가 도면을 도람했다.")
    assert title in values(document, "actor")
    assert any(value != title for value in values(document, "actor"))
    assert any(reading["competes_with"] for reading in document["readings"])


def test_quoted_temporal_name_is_not_split_into_adjunct():
    document = read_text("'어제 미린'이 도면을 색인했다.")
    assert values(document, "actor") == {"어제 미린"}
    assert values(document, "time") == set()


def test_object_before_subject_keeps_its_supported_complete_reading():
    document = read_text("도면을 미린이 색인했다.")
    assert any({(role["role"], role["value"]) for role in document["roles"]
                if role["event"] == event["id"]} >= {("actor", "미린"), ("object", "도면")}
               for event in document["events"])


def test_span_lattice_preserves_report_and_negated_predicate_scope():
    document = read_text("보고서에 따르면 섬을 담당자가 도면을 도람하지 않았다.")
    claims = {claim["id"]: claim["kind"] for claim in document["claims"]}
    assert "섬을 담당자" in values(document, "actor")
    assert all(event["polarity"] is False for event in document["events"])
    assert all(claims[event["claim"]] == "attribution" for event in document["events"])
    assert all(row["claim"] != "claim:0" for row in document["rows"]
               if row["triple"][1] == "actor")


def test_unmarked_time_preserves_literal_entity_when_spelling_is_contained():
    document = read_text("어제마을 담당자가 도면을 도람했다.")
    assert values(document, "actor") == {"어제마을 담당자"}
    assert not values(document, "time")


def test_verification_uniqueness_counts_prior_clauses_not_reading_variants():
    document = read_text("서진이 전화로 소식을 전달했다. 감사팀이 그 전달을 사실로 확인했다.")
    check = next(event for event in document["events"] if event["emits_verification"])
    hypotheses = [item for item in document["hypotheses"]
                  if item["kind"] == "verification" and item["subjects"][1] == check["id"]]
    assert len(hypotheses) == 2
    assert all(item["status"] == "accepted" for item in hypotheses)
    assert all(item["result"] == "confirmed" for item in hypotheses)
    document = read_text("서진이 물건을 전달했다. 라온이 서류를 전달했다. 감사팀이 그 전달을 사실로 확인했다.")
    hypotheses = [item for item in document["hypotheses"] if item["kind"] == "verification"]
    assert len(hypotheses) == 2
    assert all(item["status"] == "candidate" for item in hypotheses)
    assert all("ambiguous_target:2" in item["blocked_by"] for item in hypotheses)
