"""Public, actual-core counterexamples for selector and API integration."""
from experiments.graph_language_repair import public_api


def test_negative_receive_does_not_answer_transfer_role_as_negative_transfer():
    reading = public_api.read("가람이 책을 받지 않았다.")
    result = public_api.answer(reading, "가람이 무엇을 전달했나요?")
    assert result["status"] != "answered" or result["answer"] != "책입니다."
    assert result["value"] != "책"


def test_report_source_question_keeps_inner_action_constraint():
    reading = public_api.read("보고서에 따르면 가람이 책을 전달했다.")
    transfer = public_api.answer(reading, "가람이 책을 전달했다고 누가 보고했나요?")
    loan = public_api.answer(reading, "가람이 책을 대여했다고 누가 보고했나요?")
    assert transfer["value"] == "보고서"
    assert loan["status"] != "answered" or loan["value"] != "보고서"


def test_source_answer_is_invariant_across_same_frame_readings():
    reading = public_api.read("보고서에 따르면 라온이 끈을 묶었다.")
    result = public_api.answer(reading, "라온이 끈을 묶었다고 누가 보고했나요?")
    assert result["status"] == "answered"
    assert result["value"] == "보고서"
    assert result["answer"] and "보고서" in result["answer"]
    assert result["compatible_readings"] == ["reading:0", "reading:1"]
    assert result["answer_spans"]
    assert any(row["triple"][1] == "reporter" and row["triple"][2] == "보고서"
               for row in result["evidence"])


def test_divergent_source_answers_remain_held():
    reading = public_api.read(
        "보고서에 따르면 라온이 끈을 묶었다. "
        "신문에 따르면 라온이 끈을 묶었다."
    )
    result = public_api.answer(reading, "라온이 끈을 묶었다고 누가 보고했나요?")
    assert result["status"] in ("ambiguous_answer", "ambiguous_reading",
                                "competing_readings", "contradicted")
    assert result["abstained"] is True
    assert result["value"] != "보고서" or result["status"] == "answered"


def test_report_only_occurrence_is_held_but_explicit_check_is_supported():
    report_only = public_api.read("보고서에 따르면 미린이 도면을 색인했다.")
    question = "미린이 도면을 색인한 일이 실제로 일어났나요?"
    held = public_api.answer(report_only, question)
    assert held["status"] == "reported_only" and held["abstained"] is True
    assert held["value"] == "attribution"
    assert "독립적으로" in held["answer"]
    assert held["semantic_value"] is None

    checked = public_api.read(
        "보고서에 따르면 미린이 도면을 색인했다. "
        "감사팀이 그 작업을 사실로 확인했다."
    )
    confirmed = public_api.answer(checked, question)
    assert confirmed["status"] == "answered" and confirmed["value"] == "confirmed"
    assert confirmed["semantic_relation"] == "independent_result"
    assert confirmed["semantic_value"] == "confirmed"


def test_explicit_not_performed_check_differs_from_missing_witness():
    text = "보고서에 따르면 미린이 도면을 색인했다. 감사팀이 그 작업을 확인하지 않았다."
    result = public_api.answer(public_api.read(text), "감사팀이 그 작업을 확인했나요?")
    assert result["status"] == "answered"
    assert result["semantic_relation"] == "checking_occurred"
    assert result["semantic_value"] == "not_performed"
    assert result["value"] == "action_not_performed"


def test_reported_check_and_directly_stated_result_keep_separate_sources():
    reading = public_api.read(
        "보고서에 따르면 서진이 부품을 다온에게 전달했다. "
        "감사팀이 그 전달을 사실로 확인했다."
    )
    report = public_api.answer(reading, "서진이 부품을 전달했다고 누가 보고했나요?")
    check = public_api.answer(reading, "감사팀이 그 전달을 사실로 확인했나요?")
    assert report["value"] == "보고서"
    assert any(source.get("kind") == "attribution" for source in report["sources"])
    assert any(source.get("kind") == "checking_action" for source in check["sources"])
    assert check["value"] in ("confirmed", "conflicting", "event_conflict")


def test_opposite_event_claims_render_a_qualified_conflict():
    reading = public_api.read("가람이 책을 나래에게 전달했다. 가람이 책을 나래에게 전달하지 않았다.")
    result = public_api.answer(reading, "가람이 무엇을 전달했나요?")
    assert result["status"] == "contradicted"
    assert result["abstained"] is True
    assert result["value"] == "event_conflict"
    assert result["answer"] and "충돌" in result["answer"]


def test_opposite_check_results_keep_exact_conflict_provenance():
    text = "감사팀이 그 전달을 사실로 확인했지만 허위로 확인했다."
    reading = public_api.read(text)
    result = public_api.answer(reading, "감사팀이 그 전달을 확인했나요?")
    assert result["status"] == "contradicted"
    assert result["value"] == "conflicting"
    assert result["answer"] and "상반된" in result["answer"]
    outcome = next(row for row in result["evidence"]
                   if row["triple"][1] == "checking_outcome")
    assert outcome["triple"][2] == "conflicting"
    quotes = {span["quote"] for span in outcome["spans"]}
    assert "사실로" in quotes and "허위로" in quotes
    assert all(text[span["start"]:span["end"]] == span["quote"]
               for span in outcome["spans"])


def test_destination_question_does_not_choose_an_instrument_reading():
    ambiguous = public_api.read("서진이 전화로 소식을 전달했다.")
    result = public_api.answer(ambiguous, "서진이 소식을 어디로 전달했나요?")
    assert result["status"] in ("ambiguous_reading", "competing_readings", "ambiguous_answer")
    assert result["value"] != "전화"

    clear = public_api.read("서진이 소식을 다온에게 전달했다.")
    positive = public_api.answer(clear, "서진이 소식을 누구에게 전달했나요?")
    assert positive["status"] == "answered" and positive["value"] == "다온"
