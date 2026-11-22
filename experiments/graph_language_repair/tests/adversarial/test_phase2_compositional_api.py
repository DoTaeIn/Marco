"""Public API controls for compositional, opaque predicate questions."""
from experiments.graph_language_repair import public_api
from experiments.graph_language_repair.core import analyze_predicates


def _event_action(reading):
    events = reading.get("events") or []
    assert len(events) == 1
    return events[0]["action"]


def _answer_row(result):
    rows = [row for row in result["evidence"] if row.get("carries_answer")]
    assert rows
    return rows[0]


def test_new_opaque_lemma_is_shared_between_body_question_and_exact_provenance():
    text = "다온이 목재를 벨람했다."
    reading = public_api.read(text)
    analysis = analyze_predicates(text)[0]
    result = public_api.answer(reading, "다온이 목재를 벨람했나요?")

    assert analysis["semantic_status"] == "opaque"
    assert analysis["lemma"] == "벨람"
    assert analysis["action"] == _event_action(reading)
    assert result["status"] == "answered" and result["value"] == "true"
    question_analysis = result["plan"]["question_graph"]["predicate_analyses"][0]
    assert question_analysis["action"] == analysis["action"]
    assert result["plan"]["required_action"] == analysis["action"]

    answer_row = _answer_row(result)
    assert answer_row["triple"] == ["event:0", "polarity", "true"]
    assert any(span["quote"] == "벨람했다" for span in answer_row["spans"])
    assert answer_row["triple"][0] == "event:0"
    assert any(row.get("triple") == ["event:0", "action_type", analysis["action"]]
               for row in reading["rows"])
    assert not any(row.get("triple") == ["event:0", "action", "action:transfer"]
                   or row.get("triple") == ["event:0", "action", "action:check"]
                   for row in reading["rows"])


def test_opaque_action_identity_varies_by_stem_not_by_inflection_or_values():
    one = analyze_predicates("누리가 새 종이를 도람했다.")[0]
    one_question = analyze_predicates("누리가 새 종이를 도람했나요?", mode="question")[0]
    other = analyze_predicates("누리가 새 종이를 미결했다.")[0]
    assert one["action"] == one_question["action"]
    assert one["action"] != other["action"]
    assert one["lemma"] == one_question["lemma"] == "도람"

    reading = public_api.read("누리가 새 종이를 도람했다.")
    answer = public_api.answer(reading, "새 종이를 누가 도람했나요?")
    assert answer["status"] == "answered" and answer["value"] == "누리"
    row = _answer_row(answer)
    assert row["triple"][1:] == ["actor", "누리"]
    assert any(item["triple"] == ["event:0", "object", "새 종이"]
               for item in answer["evidence"])
    assert all(span["quote"] in reading["text"] for span in row["spans"])


def test_known_and_opaque_predicate_mismatch_is_held_in_both_directions():
    opaque = public_api.read("라온이 목재를 벨람했다.")
    known_question = public_api.answer(opaque, "라온이 목재를 확인했나요?")
    assert known_question["status"] != "answered"
    assert known_question["value"] is not True

    known = public_api.read("라온이 목재를 확인했다.")
    opaque_question = public_api.answer(known, "라온이 목재를 벨람했나요?")
    assert opaque_question["status"] != "answered"
    assert opaque_question["value"] is not True


def test_new_opaque_active_passive_and_negative_forms_keep_voice_and_polarity():
    active = public_api.read("라온이 목재를 벨람했다.")
    active_result = public_api.answer(active, "라온이 목재를 벨람했나요?")
    assert active_result["value"] == "true"
    assert _event_action(active) == active_result["plan"]["required_action"]
    assert active["events"][0]["voice"] == "active"

    negative = public_api.read("라온이 목재를 벨람하지 않았다.")
    negative_result = public_api.answer(negative, "라온이 목재를 벨람했나요?")
    assert negative_result["status"] == "answered"
    assert negative_result["value"] == "false"
    negative_row = _answer_row(negative_result)
    assert negative_row["triple"] == ["event:0", "polarity", "false"]
    assert any(span["quote"] == "벨람하지 않았다" for span in negative_row["spans"])

    passive = public_api.read("새 목재가 다온에게 나훌되었다.")
    passive_result = public_api.answer(passive, "나훌되었나요?")
    assert passive_result["status"] == "answered" and passive_result["value"] == "true"
    assert passive["events"][0]["voice"] == "passive"
    assert passive_result["plan"]["required_voice"] == "passive"
    assert _event_action(passive) == passive_result["plan"]["required_action"]


def test_opaque_proposition_conflict_has_abstaining_status_and_qualified_text():
    reading = public_api.read("라온이 목재를 벨람했다. 라온이 목재를 벨람하지 않았다.")
    result = public_api.answer(reading, "라온이 목재를 벨람했나요?")
    assert result["status"] == "contradicted"
    assert result["abstained"] is True
    assert result["value"] == "conflicting"
    assert result["answer"] and "충돌" in result["answer"]
    assert any(row.get("carries_answer") and row["triple"][1] == "polarity"
               for row in result["evidence"])


def test_opaque_source_question_preserves_inner_action_and_attribution():
    reading = public_api.read("보고서에 따르면 라온이 목재를 벨람했다.")
    result = public_api.answer(reading, "라온이 목재를 벨람했다고 누가 보고했나요?")
    assert result["status"] == "answered" and result["value"] == "보고서"
    target = result["plan"]["question_graph"]["target_predicates"][0]
    assert target["semantic_status"] == "opaque"
    assert target["action"] == _event_action(reading)
    assert result["plan"]["required_action"] == target["action"]
    assert any(source.get("kind") == "attribution" for source in result["sources"])
    assert result["answer_spans"]
    assert any(span["quote"] == "보고서" for evidence in result["evidence"]
               for span in evidence["spans"])

    negative_reading = public_api.read("보고서에 따르면 라온이 목재를 벨람하지 않았다.")
    negative = public_api.answer(
        negative_reading,
        "라온이 목재를 벨람하지 않았다고 누가 보고했나요?",
    )
    negative_target = negative["plan"]["question_graph"]["target_predicates"][0]
    assert negative["status"] == "answered" and negative["value"] == "보고서"
    assert negative_target["polarity"] is False
    assert negative_target["action"] == _event_action(negative_reading)
    assert any(source.get("kind") == "attribution" for source in negative["sources"])

    mismatched = public_api.answer(
        public_api.read("보고서에 따르면 라온이 목재를 벨람했다."),
        "라온이 목재를 벨람하지 않았다고 누가 보고했나요?",
    )
    assert mismatched["status"] != "answered"


def test_unique_implicit_role_target_answers_but_multiple_targets_abstain():
    one = public_api.answer(public_api.read("다온이 목재를 나훌했다."), "누가 나훌했나요?")
    assert one["status"] == "answered" and one["value"] == "다온"

    many = public_api.answer(
        public_api.read("다온이 목재를 나훌했다. 가람이 철판을 나훌했다."),
        "누가 나훌했나요?",
    )
    assert many["status"] in ("ambiguous_answer", "ambiguous_reading")
    assert many["abstained"] is True
    assert many["answer"] and "후보" in many["answer"]

    missing_role = public_api.answer(public_api.read("다온이 목재를 나훌했다."),
                                     "누구에게 나훌했나요?")
    assert missing_role["status"] == "no_evidence"
    assert missing_role["abstained"] is True


def test_opaque_noun_with_particle_does_not_invent_a_predicate():
    analyses = analyze_predicates("다온이 벨람을 확인했다.")
    assert len(analyses) == 1
    assert analyses[0]["semantic_status"] == "declared"
    assert analyses[0]["lemma"] == "확인"

    reading = public_api.read("다온이 벨람을 확인했다.")
    assert len(reading["events"]) == 1
    assert reading["events"][0]["action"] == "action:check"
    assert not any(row.get("triple", (None,))[0] == "event:1"
                   and row.get("triple", (None, None, None))[1] == "action"
                   for row in reading["rows"])


def test_opaque_positive_proposition_does_not_match_other_unrelated_events():
    reading = public_api.read("라온이 목재를 벨람했다. 다온이 철판을 자롬했다.")
    result = public_api.answer(reading, "라온이 무엇을 벨람했나요?")
    assert result["status"] == "answered" and result["value"] == "목재"
    row = _answer_row(result)
    assert row["triple"] == ["event:0", "object", "목재"]
    assert any(ref.get("row") == row["id"] for source in result["sources"]
               for source_row in source["rows"] for ref in [{"row": source_row["row"]}])


def test_opaque_morphology_provenance_and_serialization_are_detached():
    reading = public_api.read("누리가 새 종이를 도람하지 않았다.")
    before = public_api.to_json_finite(reading)
    result = public_api.answer(reading, "누리가 새 종이를 도람했나요?")
    assert public_api.to_json_finite(reading) == before
    public_api.json.dumps(result, ensure_ascii=False, allow_nan=False)
    assert result["value"] == "false"
    predicate = result["plan"]["question_graph"]["predicate_analyses"][0]
    assert predicate["derivation"]["grammar"] == "morphology:do_verb"
    assert predicate["semantic_status"] == "opaque"
    assert predicate["lemma"] == "도람"
    assert predicate["span"][0] < predicate["span"][1]
    assert result["search"]["complete"] is True


def test_crossvoice_questions_preserve_action_and_argument_roles():
    passive = public_api.answer(
        public_api.read("도면이 아린에 의해 분류되었다."),
        "누가 도면을 분류했나요?",
    )
    assert passive["status"] == "answered" and passive["value"] == "아린"
    assert any(row["triple"][1:] == ["actor", "아린"] for row in passive["evidence"])

    active = public_api.answer(
        public_api.read("아린이 도면을 분류했다."),
        "도면은 누구에 의해 분류되었나요?",
    )
    assert active["status"] == "answered" and active["value"] == "아린"
    assert any(row["triple"][1:] == ["actor", "아린"] for row in active["evidence"])

    proposition = public_api.answer(
        public_api.read("아린이 도면을 분류했다."),
        "도면이 아린에 의해 분류되었나요?",
    )
    assert proposition["status"] == "answered" and proposition["value"] == "true"

    wrong_actor = public_api.answer(
        public_api.read("아린이 도면을 분류했다."),
        "도면이 하린에 의해 분류되었나요?",
    )
    assert wrong_actor["status"] != "answered"
    assert wrong_actor["value"] is None

    wrong_object = public_api.answer(
        public_api.read("아린이 도면을 분류했다."),
        "문서가 아린에 의해 분류되었나요?",
    )
    assert wrong_object["status"] != "answered"
    assert wrong_object["value"] is None


def test_crossvoice_report_and_negated_role_keep_report_scope_and_negation():
    report = public_api.answer(
        public_api.read("보고서에 따르면 도면이 아린에 의해 색인되었다."),
        "누가 도면을 색인했나요?",
    )
    assert report["status"] == "answered" and report["value"] == "아린"
    assert report["qualifications"] == ["within_report"]
    assert "보고서" in report["answer"]

    negative = public_api.answer(
        public_api.read("도면이 아린에 의해 색인되지 않았다."),
        "누가 도면을 색인했나요?",
    )
    # Previously this positive question returned event_negated. It now
    # requires positive event polarity and therefore holds on negative-only evidence.
    assert negative["status"] == "constraints_unmet" and negative["abstained"]
    requested_negative = public_api.answer(
        public_api.read("도면이 아린에 의해 색인되지 않았다."),
        "누가 도면을 색인하지 않았나요?",
    )
    assert requested_negative["status"] == "answered" and requested_negative["value"] == "아린"
    assert "하지 않았다는" in requested_negative["answer"]
    assert requested_negative["evidence"]
