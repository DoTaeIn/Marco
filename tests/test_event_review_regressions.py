"""Review regressions for durable semantic continuation and relationship state."""

from marco.reasoning.inference import closure_with_provenance
from marco.reasoning.context import ReasoningContext
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


KG = "graphs/graph_일상추론.kg"


def _guard_history_parse(context, history, monkeypatch):
    parser = context._parser()
    original = parser.parse

    def parse_new_only(text, *args, **kwargs):
        if text in history:
            raise AssertionError("historical source was reparsed: %s" % text)
        return original(text, *args, **kwargs)

    monkeypatch.setattr(parser, "parse", parse_new_only)


def test_restored_semantics_continue_new_action_resume_and_direct_correction_without_old_parse(monkeypatch):
    history = ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
               "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
               "민수가 지연에게 베풀었다.")
    context = ReasoningContext()
    for text in history:
        context.turn(text, KG)
    restored = ReasoningContext()
    restored.restore(context.snapshot())
    _guard_history_parse(restored, history, monkeypatch)

    # The newly typed event is parsed, while the first event/program/state is
    # read from the saved semantic ledger.  3 + 2 + 2 = 7.
    assert restored.turn("민수가 지연에게 베풀었어.", KG)["status"] == "observed"
    assert restored.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "7개입니다."
    assert restored.snapshot()["replay"]["facts"]

    # A direct correction rebuilds the dependent action from its envelope,
    # without parsing the original definition or action text.
    changed = restored.turn("정정: 민수 구슬은 8개 있다 => 민수 구슬은 10개 있다.", KG)
    assert changed["status"] == "observed"
    assert restored.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "6개입니다."


def test_restored_pending_event_resumes_from_saved_program_without_old_parse(monkeypatch):
    history = ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
               "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
               "지연에게 베풀었다.")
    context = ReasoningContext()
    for text in history:
        context.turn(text, KG)
    restored = ReasoningContext()
    restored.restore(context.snapshot())
    _guard_history_parse(restored, history, monkeypatch)
    assert restored.turn("민수야", KG)["status"] == "observed"
    assert restored.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "5개입니다."
    assert restored.snapshot()["events"]


def test_app_restart_continues_saved_event_with_a_new_action(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
                 "민수가 지연에게 베풀었다."):
        app.turn(text, "semantic_continue", conversation_id=chat)
    restarted = create_app(tmp_path)
    assert restarted.turn("민수가 지연에게 베풀었어.", "semantic_continue_new",
                          conversation_id=chat)["phase"] == "answer"
    answer = restarted.turn("지금 지연 구슬은 몇 개야?", "semantic_continue_new",
                            conversation_id=chat)
    assert answer["answer"]["answer"] == "7개입니다."
    assert answer["answer"]["verification"]["replay_scope"] == "same_input"


def test_app_restart_resumes_pending_event_then_corrects_saved_direct_fact(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
                 "지연에게 베풀었다."):
        app.turn(text, "semantic_resume", conversation_id=chat)
    restarted = create_app(tmp_path)
    restarted.turn("민수야", "semantic_resume_new", conversation_id=chat)
    assert restarted.turn("지금 지연 구슬은 몇 개야?", "semantic_resume_new",
                          conversation_id=chat)["answer"]["answer"] == "5개입니다."
    restarted.turn("정정: 민수 구슬은 8개 있다 => 민수 구슬은 10개 있다.",
                   "semantic_resume_new", conversation_id=chat)
    assert restarted.turn("지금 민수 구슬은 몇 개야?", "semantic_resume_new",
                          conversation_id=chat)["answer"]["answer"] == "8개입니다."


def test_new_proof_for_existing_conclusion_reaches_its_dependent_and_order_is_invariant():
    facts = [{"id": "p", "triple": ["a", "p", "b"], "evidence": {}},
             {"id": "r", "triple": ["a", "r", "b"], "evidence": {}}]
    rules = [
        {"id": "p-q", "version": 1, "body": [["?x", "p", "?y"]], "head": ["?x", "q", "?y"]},
        {"id": "r-q", "version": 1, "body": [["?x", "r", "?y"]], "head": ["?x", "q", "?y"]},
        {"id": "q-s", "version": 1, "body": [["?x", "q", "?y"]], "head": ["?x", "s", "?y"]},
    ]
    forward, reversed_rules = closure_with_provenance(facts, rules), closure_with_provenance(facts, list(reversed(rules)))
    target = ("a", "s", "b")
    assert forward["complete"] is reversed_rules["complete"] is True
    assert {row["premise_fact_ids"][0] for row in forward["proof_bundles"][target]} == {
        row["premise_fact_ids"][0] for row in reversed_rules["proof_bundles"][target]
    }
    assert len(forward["proof_bundles"][target]) == 2


def test_late_alternative_x_proof_reaches_z_in_the_required_rule_order_and_withdraws_cleanly():
    facts = [{"id": "p", "triple": ["a", "p", "b"], "evidence": {}}]
    rules = [
        {"id": "x-z", "body": [["?x", "x", "?y"]], "head": ["?x", "z", "?y"]},
        {"id": "v-x", "body": [["?x", "v", "?y"]], "head": ["?x", "x", "?y"]},
        {"id": "u-v", "body": [["?x", "u", "?y"]], "head": ["?x", "v", "?y"]},
        {"id": "p-x", "body": [["?x", "p", "?y"]], "head": ["?x", "x", "?y"]},
        {"id": "p-u", "body": [["?x", "p", "?y"]], "head": ["?x", "u", "?y"]},
    ]
    target = ("a", "z", "b")
    forward = closure_with_provenance(facts, rules)
    reverse = closure_with_provenance(facts, list(reversed(rules)))
    assert forward["complete"] is reverse["complete"] is True
    assert len(forward["proof_bundles"][target]) == len(reverse["proof_bundles"][target]) == 2
    assert {row["premise_fact_ids"][0] for row in forward["proof_bundles"][target]} == {
        row["premise_fact_ids"][0] for row in reverse["proof_bundles"][target]
    }
    # Removing the long branch removes exactly its z support; removing the
    # only remaining branch withdraws z rather than leaving a cyclic remnant.
    short = closure_with_provenance(facts, [rules[0], rules[3]])
    assert target in short["facts"] and len(short["proof_bundles"][target]) == 1
    gone = closure_with_provenance([], rules)
    assert target not in gone["facts"]


def test_current_location_proof_excludes_obsolete_state_across_restart_and_hypothesis():
    context = ReasoningContext()
    for text in ("넣다는 내가 물건을 책상으로 옮기는 것이다.",
                 "공책은 책상에 있었다.", "하루가 공책을 서랍으로 옮겼다."):
        context.turn(text, KG)
    snapshot = context.snapshot()
    assert any(row["triple"] == ["공책", "location", "책상"] for row in snapshot["replay"]["facts"])
    current_conclusions = {tuple(row["conclusion"]) for row in snapshot["inference_bundles"]["bundles"]}
    assert ("공책", "location", "책상") not in current_conclusions
    assert context.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."

    restored = ReasoningContext()
    restored.restore(snapshot)
    assert restored.turn("정정: 공책은 책상에 있었다 => 공책은 책장에 있었다.", KG)["status"] == "observed"
    assert restored.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."
    assert restored.turn("만약 하루가 공책을 넣었으면 지금 공책은 어디에 있어?", KG)["answer"] == "책상에 있습니다."
    assert restored.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."


def test_social_relation_id_isolated_and_ambiguous_cancellation_resumes_one_target():
    context = ReasoningContext()
    for text in ("약속하다는 내가 상대에게 약속을 만드는 것이다.",
                 "취소하다는 내가 상대와 약속을 취소 상태로 만드는 것이다.",
                 "민수가 지연에게 약속했다.", "민수가 가람에게 약속했다."):
        assert context.turn(text, KG)["status"] == "observed"
    asked = context.turn("민수가 취소했다.", KG)
    assert asked["status"] == "unresolved"
    assert context.turn("지연", KG)["status"] == "observed"
    assert context.turn("민수와 지연의 약속 상태가 어때?", KG)["answer"] == "cancelled입니다."
    assert context.turn("민수와 가람의 약속 상태가 어때?", KG)["answer"] == "active입니다."


def test_planned_role_completion_stays_nonactual_after_restore(monkeypatch):
    history = ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
               "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
               "지연에게 베풀 예정이다.")
    context = ReasoningContext()
    for text in history:
        context.turn(text, KG)
    restored = ReasoningContext()
    restored.restore(context.snapshot())
    _guard_history_parse(restored, history, monkeypatch)
    assert restored.turn("민수야", KG)["status"] == "observed"
    assert restored.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."
    assert restored.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "3개입니다."
    planned = next(row["event"] for row in restored.snapshot()["events"]
                   if row["event"]["action"] == "베풀")
    assert planned["modality"] == "planned"


def test_restored_definition_add_and_definition_correction_use_saved_semantics(monkeypatch):
    history = ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
               "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
               "민수가 지연에게 베풀었다.")
    context = ReasoningContext()
    for text in history:
        context.turn(text, KG)
    restored = ReasoningContext()
    restored.restore(context.snapshot())
    _guard_history_parse(restored, history, monkeypatch)
    # A new definition is compiled from this new source alone and applies to
    # a later action without changing the saved quantity action program.
    assert restored.turn("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.", KG)["status"] == "observed"
    assert restored.turn("하린은 서랍에 있었다.", KG)["status"] == "observed"
    assert restored.turn("하린이 공책을 모았다.", KG)["status"] == "observed"
    assert restored.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."
    assert restored.turn(
        "정정: 베풀다는 상대에게 구슬 2개를 주는 것이다. => 베풀다는 상대에게 구슬 4개를 주는 것이다.", KG
    )["status"] == "observed"
    assert restored.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "4개입니다."


def test_same_party_relationship_occurrences_are_independent_and_selection_persists(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    for text in ("약속하다는 내가 상대에게 약속을 만드는 것이다.",
                 "취소하다는 내가 상대와 약속을 취소 상태로 만드는 것이다.",
                 "민수가 지연에게 약속했다.", "민수가 지연에게 약속했다.",
                 "민수가 취소했다.", "지연"):
        app.turn(text, "relation_occurrences", conversation_id=chat)
    pending = app.reasoning_contexts["chat_" + chat]
    request = next(ask["필요"] for ask in pending.asked
                   if ask.get("종류") == "조회" and ask.get("필요", {}).get("kind") == "relation")
    assert len(request["candidates"]) == 2
    app.turn("첫 번째", "relation_occurrences", conversation_id=chat)

    restarted = create_app(tmp_path)
    restarted.turn("민수와 지연의 약속 상태가 어때?", "relation_occurrences",
                   conversation_id=chat)
    context = restarted.reasoning_contexts["chat_" + chat]
    statuses = {row[0]: row[2] for row in context.current_state()
                if row[1] == "relation_status"}
    assert set(statuses) == set(request["candidates"])
    assert sorted(statuses.values()) == ["active", "cancelled"]
