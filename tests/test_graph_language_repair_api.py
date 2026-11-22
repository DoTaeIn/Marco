import copy
import json

from experiments.graph_language_repair import public_api


def _assert_json_finite(value):
    json.dumps(value, ensure_ascii=False, allow_nan=False)


def test_answer_uses_existing_reading_and_returns_paired_exact_evidence():
    reading = public_api.read("가람이 책을 나래에게 전달했다.")
    before = copy.deepcopy(reading)
    result = public_api.answer(reading, "가람이 무엇을 전달했나요?")

    _assert_json_finite(result)
    assert reading == before
    assert result["facts"] == public_api.to_json_finite(reading["rows"])
    if result["status"] == "answered":
        assert result["answer"]
        assert result["evidence"]
        assert result["answer_spans"]
        for record in result["evidence"]:
            source = next(item for item in result["sources"] if item["claim"] == record["claim"])
            assert any(item["row"] == record["id"] for item in source["rows"])
            for span in record["spans"]:
                assert span["quote"] == reading["text"][span["start"] : span["end"]]


def test_answer_fails_closed_when_search_completion_is_missing_or_false():
    reading = public_api.read("가람이 책을 나래에게 전달했다.")
    real_search = public_api._core_search_rows

    def incomplete(completion):
        def run(doc, query, *args, **kwargs):
            world = real_search(doc, query, *args, **kwargs)
            if completion is not ...:
                world["complete"] = completion
            else:
                world.pop("complete", None)
            return world
        return run

    for completion in (False, None, ...):
        result = public_api.answer(reading, "가람이 무엇을 전달했나요?",
                                   search_rows=incomplete(completion))
        _assert_json_finite(result)
        assert result["status"] == "incomplete_search"
        assert result["abstained"] is True
        assert result["answer"] is None
        assert result["search"]["complete"] is False


def test_answer_fails_closed_when_selected_support_reference_is_missing():
    reading = public_api.read("가람이 책을 나래에게 전달했다.")

    def broken_search(doc, query, *args, **kwargs):
        world = public_api._core_search_rows(doc, query, *args, **kwargs)
        for source in world.get("fact_sources", ()):
            original = source.get("original_fact", {})
            triple = original.get("triple", ())
            if len(triple) == 3 and triple[1] == "object":
                source["source_ref"] = {"rows": ["row:missing"], "row": "row:missing"}
        return world

    result = public_api.answer(reading, "가람이 무엇을 전달했나요?",
                               search_rows=broken_search)
    _assert_json_finite(result)
    assert result["status"] == "provenance_incomplete"
    assert result["abstained"] is True
    assert result["answer"] is None
    assert any(ref.get("kind") == "row" and ref.get("id") == "row:missing"
               for ref in result["missing_references"])


def test_merged_source_refs_keep_row_claim_span_pairing():
    reading = public_api.read("가람이 책을 전달했다. 가람이 책을 전달했다.")
    result = public_api.answer(reading, "가람이 무엇을 전달했나요?")
    _assert_json_finite(result)
    rows = {row["id"]: row for row in reading["rows"]}
    for source in result["sources"]:
        for item in source["rows"]:
            row = rows[item["row"]]
            assert row["claim"] == source["claim"]
            assert item["spans"] == [
                {"start": span[0], "end": span[1], "quote": reading["text"][span[0]:span[1]]}
                for span in row["spans"]
            ]


def test_same_answer_role_in_every_surviving_reading_is_not_a_fact_conflict():
    reading = public_api.read("박검사관이 창고에서 부품을 확인했다.")
    result = public_api.answer(reading, "부품을 창고에서 확인한 사람은 누구인가요?")
    _assert_json_finite(result)
    assert result["status"] == "answered"
    assert result["value"] == "박검사관"
    assert result["answer"] == "박검사관입니다."
    conflict = next(item for item in result["conflicts"]["contradictions"]
                    if item.get("kind") == "reading_conflict")
    assert conflict["answer_supported_in_readings"] == ["reading:0", "reading:1"]
