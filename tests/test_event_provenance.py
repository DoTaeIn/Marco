"""Regression cases for the durable event/proof ledger."""

from marco.reasoning.inference import closure_with_provenance
from marco.reasoning.context import ReasoningContext
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


KG = "graphs/graph_일상추론.kg"


def test_independent_proof_bundles_survive_one_support_becoming_invalid():
    facts = [
        {"id": "fact:p", "triple": ["a", "p", "b"], "evidence": {}},
        {"id": "fact:q", "triple": ["a", "q", "b"], "evidence": {}},
    ]
    rules = [
        {"id": "via-p", "version": "r1", "body": [["?x", "p", "?y"]],
         "head": ["?x", "reachable", "?y"]},
        {"id": "via-q", "version": "r2", "body": [["?x", "q", "?y"]],
         "head": ["?x", "reachable", "?y"]},
    ]
    result = closure_with_provenance(facts, rules)
    target = ("a", "reachable", "b")
    assert result["complete"] is True
    assert {row["rule"] for row in result["proof_bundles"][target]} == {"via-p", "via-q"}

    corrected = closure_with_provenance(facts[1:], rules)
    assert target in corrected["facts"]
    assert [row["rule"] for row in corrected["proof_bundles"][target]] == ["via-q"]


def test_provenance_limit_is_not_reported_as_a_complete_search():
    result = closure_with_provenance(
        [{"id": "fact:seed", "triple": ["a", "p", "b"], "evidence": {}}],
        [{"id": "r", "body": [["?x", "p", "?y"]], "head": ["?x", "r", "?y"]}],
        search_limit=1,
    )
    assert result["complete"] is False
    assert result["reason"] == "proof_or_search_limit"


def test_provenance_cycle_without_a_ground_fact_cannot_create_its_own_support():
    result = closure_with_provenance([], [
        {"id": "p-to-q", "body": [["?x", "p", "?y"]], "head": ["?x", "q", "?y"]},
        {"id": "q-to-p", "body": [["?x", "q", "?y"]], "head": ["?x", "p", "?y"]},
    ])
    assert result["facts"] == {}
    assert result["complete"] is True


def test_event_id_and_program_survive_role_correction_and_restore():
    context = ReasoningContext()
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 1개 있다.",
                 "민수가 지연에게 베풀었다."):
        assert context.turn(text, KG)["status"] == "observed"
    before = context.snapshot()
    event_row = next(row for row in before["events"] if row["event"]["action"] == "베풀")
    event = event_row["event"]
    assert event["program"]["definition_version"] == event["definition_version"]
    assert before["inference_bundles"]["complete"] is True
    assert {change["operation"] for change in event_row["state_changes"]} == {"quantity_update"}

    context.turn("정정: 민수가 지연에게 베풀었다. => 민수가 가람에게 베풀었다.", KG)
    after = context.snapshot()
    corrected = next(row for row in after["events"] if row["event"]["action"] == "베풀")["event"]
    assert corrected["id"] == event["id"]
    assert after["event_revisions"][-1]["event_id"] == event["id"]

    restored = ReasoningContext()
    restored.restore(after)
    replayed = next(row for row in restored.snapshot()["events"]
                    if row["event"]["action"] == "베풀")["event"]
    assert replayed["id"] == event["id"]
    assert restored.turn("지금 가람 구슬은 몇 개야?", KG)["answer"] == "3개입니다."


def test_restored_snapshot_answers_from_saved_semantic_replay_not_old_text_parse(monkeypatch):
    context = ReasoningContext()
    history = ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
               "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
               "민수가 지연에게 베풀었다.")
    for text in history:
        context.turn(text, KG)
    restored = ReasoningContext()
    restored.restore(context.snapshot())
    parser = restored._parser()
    original = parser.parse

    def parse_only_new(text, *args, **kwargs):
        if text in history:
            raise AssertionError("restored history must use the saved replay record")
        return original(text, *args, **kwargs)

    monkeypatch.setattr(parser, "parse", parse_only_new)
    assert restored.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "5개입니다."


def test_social_pack_records_explicit_promise_and_cancellation_not_the_promised_act():
    context = ReasoningContext()
    for text in ("약속하다는 내가 상대에게 약속을 만드는 것이다.",
                 "취소하다는 내가 상대와 약속을 취소 상태로 만드는 것이다.",
                 "민수가 지연에게 약속했다."):
        assert context.turn(text, KG)["status"] == "observed"
    assert context.turn("민수와 지연의 약속 상태가 어때?", KG)["answer"] == "active입니다."
    # No location/quantity fact is inferred merely because somebody promised.
    assert context.turn("지금 민수 구슬은 몇 개야?", KG)["status"] == "unresolved"
    context.turn("민수가 지연과 취소했다.", KG)
    assert context.turn("민수와 지연의 약속 상태가 어때?", KG)["answer"] == "cancelled입니다."


def test_negative_event_is_persisted_without_becoming_an_actual_effect():
    context = ReasoningContext()
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다.", "민수가 지연에게 베풀지 않았다."):
        context.turn(text, KG)
    negative = next(row for row in context.snapshot()["events"]
                    if row["status"] == "negative")
    assert negative["event"]["polarity"] is False
    assert negative["effects"] == []
    assert context.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."


def test_planned_events_stay_distinct_from_uninterpreted_across_world_domains_and_restart():
    cases = [
        (("베풀다는 상대에게 구슬 2개를 주는 것이다.", "민수 구슬은 8개 있다.",
          "민수가 지연에게 베풀 예정이다."), "Quantity", "지금 민수 구슬은 몇 개야?", "8개입니다."),
        (("옮기다는 내가 물건을 서랍으로 옮기는 것이다.", "하루는 책상에 있었다.",
          "하루가 공책을 옮길 예정이다."), "Location", "지금 공책은 어디에 있어?", None),
        (("약속하다는 내가 상대에게 약속을 만드는 것이다.", "민수 구슬은 1개 있다.",
          "민수가 지연에게 약속할 예정이다."), "Social", "민수와 지연의 약속 상태가 어때?", None),
    ]
    for history, domain, question, answer in cases:
        context = ReasoningContext()
        for text in history:
            context.turn(text, KG)
        record = context.snapshot()["events"][-1]
        assert record["event"]["domain"] == domain
        assert record["event"]["modality"] == record["status"] == "planned"
        assert record["reason"] == "planned_observation"
        assert record["effects"] == record["state_changes"] == []
        restored = ReasoningContext()
        restored.restore(context.snapshot())
        resumed = restored.snapshot()["events"][-1]
        assert resumed["status"] == "planned"
        result = restored.turn(question, KG)
        if answer:
            assert result["answer"] == answer
        else:
            assert result["status"] == "unresolved"


def test_nonactual_incomplete_events_do_not_become_pending_or_execute_after_role_reply():
    cases = [
        (("베풀다는 상대에게 구슬 2개를 주는 것이다.", "민수 구슬은 8개 있다."),
         "지연에게 베풀", "지연에게 베풀지 않았다", "민수", "지금 민수 구슬은 몇 개야?", "8개입니다."),
        (("옮기다는 내가 물건을 서랍으로 옮기는 것이다.", "공책은 책상에 있었다."),
         "공책을 옮길", "공책을 옮기지 않았다", "하루", "지금 공책은 어디에 있어?", "책상에 있습니다."),
        (("약속하다는 내가 상대에게 약속을 만드는 것이다.",),
         "지연에게 약속할", "지연에게 약속하지 않았다", "민수", "민수와 지연의 약속 상태가 어때?", None),
    ]
    for setup, planned, negative, reply, question, baseline in cases:
        for text, status in ((planned + " 예정이다.", "planned"), (negative, "negative")):
            context = ReasoningContext()
            for initial in setup:
                context.turn(initial, KG)
            context.turn(text, KG)
            context.turn(reply, KG)
            record = next(row for row in context.snapshot()["events"] if row["status"] == status)
            assert record["effects"] == record["state_changes"] == []
            restored = ReasoningContext()
            restored.restore(context.snapshot())
            resumed = next(row for row in restored.snapshot()["events"] if row["status"] == status)
            assert resumed["effects"] == resumed["state_changes"] == []
            result = restored.turn(question, KG)
            assert result["status"] == "unresolved" or result["answer"] == baseline


def test_uninterpreted_event_stays_nonactual_and_unresolved_after_restore():
    context = ReasoningContext()
    context.turn("민수 구슬은 8개 있다.", KG)
    assert context.turn("민수가 지연에게 나눴다.", KG)["status"] == "unresolved"
    event = context.snapshot()["events"][-1]
    assert event["status"] == "uninterpreted"
    assert event["reason"] == "definition_unavailable"
    assert event["effects"] == event["state_changes"] == []
    assert context.turn("지금 민수 구슬은 몇 개야?", KG)["status"] == "unresolved"

    restored = ReasoningContext()
    restored.restore(context.snapshot())
    replayed = restored.snapshot()["events"][-1]
    assert replayed["status"] == "uninterpreted"
    assert replayed["effects"] == replayed["state_changes"] == []
    assert restored.turn("지금 민수 구슬은 몇 개야?", KG)["status"] == "unresolved"


def test_false_natural_conditions_remain_nonactual_across_world_domains_and_restart():
    cases = [
        (("베풀다는 상대에게 구슬 2개를 주는 것이다.",
          "민수 구슬은 4개 있다. 지연 구슬은 3개 있다.",
          "민수 구슬이 5개보다 많으면 민수가 지연에게 베풀었다."), "Quantity"),
        (("옮기다는 내가 물건을 서랍으로 옮기는 것이다.", "민수 구슬은 4개 있다.",
          "민수 구슬이 5개보다 많으면 하루가 공책을 옮겼다."), "Location"),
        (("약속하다는 내가 상대에게 약속을 만드는 것이다.", "민수 구슬은 4개 있다.",
          "민수 구슬이 5개보다 많으면 민수가 지연에게 약속했다."), "Social"),
    ]
    for history, domain in cases:
        context = ReasoningContext()
        for text in history:
            assert context.turn(text, KG)["status"] == "observed"
        record = context.snapshot()["events"][-1]
        assert record["event"]["domain"] == domain
        assert record["status"] == record["reason"] == "condition_false"
        assert record["effects"] == record["state_changes"] == []
        restored = ReasoningContext()
        restored.restore(context.snapshot())
        resumed = restored.snapshot()["events"][-1]
        assert resumed["status"] == resumed["reason"] == "condition_false"
        assert resumed["effects"] == resumed["state_changes"] == []


def test_role_completion_executes_the_same_world_event_across_domains_and_restart():
    cases = [
        (("베풀다는 상대에게 구슬 2개를 주는 것이다.",
          "민수 구슬은 8개 있다. 지연 구슬은 3개 있다."),
         "지연에게 베풀었다.", "민수", "지금 지연 구슬은 몇 개야?", "5개입니다.", "Quantity"),
        (("옮기다는 내가 물건을 서랍으로 옮기는 것이다.", "하루는 서랍에 있었다."),
         "공책을 옮겼다.", "하루", "지금 공책은 어디에 있어?", "서랍에 있습니다.", "Location"),
        (("약속하다는 내가 상대에게 약속을 만드는 것이다.", "민수 구슬은 1개 있다."),
         "지연에게 약속했다.", "민수", "민수와 지연의 약속 상태가 어때?", "active입니다.", "Social"),
    ]
    for setup, incomplete, reply, question, answer, domain in cases:
        context = ReasoningContext()
        for text in setup:
            context.turn(text, KG)
        assert context.turn(incomplete, KG)["status"] == "unresolved"
        pending = context.snapshot()["events"][-1]
        assert pending["event"]["domain"] == domain
        assert pending["status"] == "pending"
        assert pending["effects"] == pending["state_changes"] == []
        assert context.turn(reply, KG)["status"] == "observed"
        executed = context.snapshot()["events"][-1]
        assert executed["event"]["id"] == pending["event"]["id"]
        assert executed["status"] == "executed"
        restored = ReasoningContext()
        restored.restore(context.snapshot())
        assert restored.turn(question, KG)["answer"] == answer


def test_restored_event_correction_replaces_effects_without_reparsing_history(monkeypatch):
    history = ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
               "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
               "민수가 지연에게 베풀었다.")
    context = ReasoningContext()
    for text in history:
        context.turn(text, KG)
    original = next(row["event"] for row in context.snapshot()["events"]
                    if row["event"]["action"] == "베풀")
    restored = ReasoningContext()
    restored.restore(context.snapshot())
    parser = restored._parser()
    parse = parser.parse

    def parse_only_replacement(text, *args, **kwargs):
        if text in history:
            raise AssertionError("restored history must use the saved replay record")
        return parse(text, *args, **kwargs)

    monkeypatch.setattr(parser, "parse", parse_only_replacement)
    changed = restored.turn(
        "정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀지 않았다.", KG)
    assert changed["verification"]["replay_scope"] == "semantic_correction"
    event = next(row for row in restored.snapshot()["events"]
                 if row["event"]["action"] == "베풀")
    assert event["event"]["id"] == original["id"]
    assert event["status"] == "negative"
    assert event["effects"] == event["state_changes"] == []
    assert restored.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "3개입니다."


def test_restored_location_and_social_role_corrections_use_saved_events(monkeypatch):
    cases = [
        (("옮기다는 내가 물건을 서랍으로 옮기는 것이다.",
          "하루가 공책을 옮겼다."),
         "옮기", "정정: 하루가 공책을 옮겼다. => 하루가 연필을 옮겼다.",
         "지금 공책은 어디에 있어?", "지금 연필은 어디에 있어?", "서랍에 있습니다."),
        (("약속하다는 내가 상대에게 약속을 만드는 것이다.",
          "민수가 지연에게 약속했다."),
         "약속하", "정정: 민수가 지연에게 약속했다. => 민수가 하루에게 약속했다.",
         "민수와 지연의 약속 상태가 어때?", "민수와 하루의 약속 상태가 어때?", "active입니다."),
    ]
    for history, action, correction, old_question, new_question, answer in cases:
        context = ReasoningContext()
        for text in history:
            context.turn(text, KG)
        original = next(row["event"] for row in context.snapshot()["events"]
                        if row["event"]["action"] == action)
        restored = ReasoningContext()
        restored.restore(context.snapshot())
        parser = restored._parser()
        parse = parser.parse

        def parse_only_replacement(text, *args, **kwargs):
            if text in history:
                raise AssertionError("restored history must use the saved replay record")
            return parse(text, *args, **kwargs)

        monkeypatch.setattr(parser, "parse", parse_only_replacement)
        changed = restored.turn(correction, KG)
        event = next(row for row in restored.snapshot()["events"]
                     if row["event"]["action"] == action)
        assert changed["verification"]["replay_scope"] == "semantic_correction"
        assert event["event"]["id"] == original["id"]
        assert event["status"] == "executed"
        assert restored.turn(old_question, KG)["status"] == "unresolved"
        assert restored.turn(new_question, KG)["answer"] == answer


def test_app_restart_reads_saved_replay_record_before_answering(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
                 "민수가 지연에게 베풀었다."):
        app.turn(text, "saved_semantic_replay", conversation_id=chat)
    saved = app.conversations.reasoning_state(chat)
    assert saved["replay"]["facts"]

    restarted = create_app(tmp_path)
    result = restarted.turn("지금 지연 구슬은 몇 개야?", "saved_semantic_replay_new",
                            conversation_id=chat)
    assert result["answer"]["answer"] == "5개입니다."
    assert result["answer"]["verification"]["replay_scope"] == "same_input"
