from pathlib import Path
from unittest.mock import patch
from unittest.mock import patch

import engine
import marco.storage.kgpack as kgpack
from relational_semantics import RelationalParser
from marco.reasoning.context import ReasoningContext
from views.kgpack_ui import AppState
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default

KG = "graphs/graph_일상추론.kg"


def test_dialogue_replays_events_once_and_does_not_share_memory():
    first, second = engine.Dialogue(), engine.Dialogue()
    assert first.say("돌은 23개 있다.")[1] == "상태기억"
    assert first.say("돌 8개를 꺼냈다.")[1] == "상태기억"
    for _ in range(2):
        assert first.say("지금 돌은 몇 개야?")[2] == "15개입니다."
    assert second.say("지금 돌은 몇 개야?")[1] == "미지"


def test_each_conversation_reuses_its_parser_but_never_shares_it_with_another_conversation():
    first, second = ReasoningContext(), ReasoningContext()
    assert first._parser() is first._parser()
    assert first._parser() is not second._parser()


def test_direct_state_append_and_correction_replay_only_the_affected_suffix():
    context = ReasoningContext()
    with patch.object(context, "_replay", wraps=context._replay) as replay:
        first = context.turn("민수 구슬은 8개 있다.", KG)
        assert first["verification"]["replay_scope"] == "full"
        assert context.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."
        assert context.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."
        assert replay.call_count == 1
        appended = context.turn("민수가 구슬 2개를 꺼냈다.", KG)
        assert appended["verification"]["replay_scope"] == "append_suffix"
        answered = context.turn("지금 민수 구슬은 몇 개야?", KG)
        assert answered["answer"] == "6개입니다."
        assert answered["verification"]["replay_scope"] == "same_input"
        # 직접 사실은 새 원문 하나만 읽어 기존 근거 뒤에 붙인다. 전체 재생은
        # 정의·조건·보완처럼 과거 뜻을 바꿀 수 있는 경우에만 쓴다.
        assert replay.call_count == 1
        corrected = context.correct(0, "민수 구슬은 10개 있다.", KG)
        assert corrected["verification"]["replay_scope"] == "correction_suffix"
        assert context.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."
        assert replay.call_count == 1


def test_learned_or_conditional_event_keeps_the_safe_full_replay_fallback():
    context = ReasoningContext()
    with patch.object(context, "_replay", wraps=context._replay) as replay:
        context.turn("돌은 8개 있다.", KG)
        context.turn("보관하다는 물건을 가방으로 옮기는 것이다.", KG)
        # 이미 해석을 끝낸 정의 뒤에 온 직접 상태는 과거 뜻을 바꾸지 않으므로
        # 접두어를 다시 읽을 필요가 없다.
        context.turn("돌은 9개 있다.", KG)
        assert replay.call_count == 2
        context.turn("하린이 돌을 보관했다.", KG)
        assert replay.call_count == 3


def test_correction_after_a_settled_learned_prefix_replays_only_the_direct_suffix():
    """복잡한 앞부분 자체가 아니라 그 뒤 직접 사실만 고치면 앞은 다시 읽지 않는다."""
    context = ReasoningContext()
    with patch.object(context, "_replay", wraps=context._replay) as replay:
        context.turn("돌은 8개 있다.", KG)
        context.turn("보관하다는 물건을 가방으로 옮기는 것이다.", KG)
        context.turn("돌은 9개 있다.", KG)
        assert replay.call_count == 2
        corrected = context.correct(2, "돌은 10개 있다.", KG)
        assert corrected["verification"]["replay_scope"] == "correction_suffix"
        assert context.turn("지금 돌은 몇 개야?", KG)["answer"] == "10개입니다."
        assert replay.call_count == 2


def test_context_observation_limit_keeps_the_last_verified_state_instead_of_dropping_events_silently():
    """긴 대화 한도는 값이 아니라 사건을 보류한다고 명시한다."""
    context = ReasoningContext(max_turns=2)
    context.turn("돌은 23개 있다.", KG)
    context.turn("돌 8개를 꺼냈다.", KG)
    limited = context.turn("돌 1개를 넣었다.", KG)
    assert limited["status"] == "unresolved"
    assert "상태 기록 한도" in limited["answer"]
    assert context.snapshot()["observations"] == ["돌은 23개 있다.", "돌 8개를 꺼냈다."]
    blocked = context.turn("지금 돌은 몇 개야?", KG)
    assert blocked["status"] == "unresolved"
    assert "상태 기록 한도" in blocked["answer"]


def test_capacity_guard_keeps_an_older_affected_subject_after_newer_overflow_events():
    """최근 보류만 남겨 돌의 미확인 변화를 잊어서는 안 된다."""
    context = ReasoningContext(max_turns=2)
    context.turn("돌은 23개 있다.", KG)
    context.turn("공책은 5개 있다.", KG)
    context.turn("돌 1개를 꺼냈다.", KG)
    context.turn("공책 1개를 꺼냈다.", KG)
    context.turn("공책 2개를 꺼냈다.", KG)
    blocked = context.turn("지금 돌은 몇 개야?", KG)
    assert blocked["status"] == "unresolved"
    assert "23개입니다." not in blocked["answer"]
    assert "상태 기록 한도" in blocked["answer"]
    assert any(item["text"] == "돌 1개를 꺼냈다." for item in context.snapshot()["unread_guard"])
    restored = ReasoningContext(max_turns=2)
    restored.restore(context.snapshot())
    assert "상태 기록 한도" in restored.turn("지금 돌은 몇 개야?", KG)["answer"]


def test_compacted_capacity_guards_still_block_old_state_confirmation():
    """보류 단서 자체가 한도를 넘어도 범용 보류의 시점은 잃지 않는다."""
    context = ReasoningContext(max_turns=2)
    context.turn("돌은 23개 있다.", KG)
    context.turn("공책은 5개 있다.", KG)
    for amount in range(1, 20):
        context.turn("돌 %d개를 꺼냈다." % amount, KG)
    assert any(item.get("범용") for item in context.unread_guard)
    blocked = context.turn("지금 돌은 몇 개야?", KG)
    assert blocked["status"] == "unresolved"
    assert "23개입니다." not in blocked["answer"]


def test_context_combines_facts_across_turns_with_source_turn_ids():
    context = ReasoningContext()
    context.turn("서우는 도아보다 키가 크다.", KG)
    context.turn("도아는 라온보다 키가 크다.", KG)
    result = context.turn("서우와 라온 중 누가 더 커?", KG)
    assert result["answer"] == "서우입니다."
    assert {step["evidence"]["turn"] for step in result["transitions"] if "evidence" in step} == {0, 1}


def test_invalid_event_is_not_committed_and_unknown_text_is_not_a_fact():
    """앞말과 어긋나는 사건은 **안 일어난 일이 아니다.**

    3개에서 8개를 꺼낼 수는 없다. 그렇다고 사용자가 일어났다고 말한 일을 우리가
    없던 일로 바꿀 수는 없다 — 처음 수량이 틀렸을 수도, 중간 사건이 빠졌을 수도
    있다. 사실로 쓰지는 않되 두 말을 다 남기고, 지금 값은 확정하지 않는다.
    """
    context = ReasoningContext()
    context.turn("돌은 3개 있다.", KG)
    말 = context.turn("돌 8개를 꺼냈다.", KG)
    assert 말["status"] == "unresolved"
    assert "셈이 맞지 않습니다" in 말["answer"]
    assert context.turn("만약 돌을 전부 없애면 어떻게 될까?", KG) is None
    assert len(context.observations) == 1          # 사실로는 안 쓴다
    assert [x["text"] for x in context.unread] == ["돌 8개를 꺼냈다."]   # 버리지도 않는다
    이제 = context.turn("지금 돌은 몇 개야?", KG)["answer"]
    assert "3개입니다." not in 이제
    assert "돌 8개를 꺼냈다" in 이제


def test_whole_question_fact_is_not_replayed_twice():
    context = ReasoningContext()
    text = "돌은 23개 있다. 돌 8개를 꺼냈다. 지금 돌은 몇 개야?"
    assert context.turn(text, KG)["answer"] == "15개입니다."
    assert context.turn("지금 돌은 몇 개야?", KG)["answer"] == "15개입니다."


def test_hypothetical_quantity_question_projects_only_the_assumed_events():
    """조건 사건은 실제 기록과 분리해 물음에만 임시 적용한다.

    세 최소 재현은 받는 쪽 증가·꺼내기·넣기이고, 두 반례는 가정이 실제 값을
    바꾸지 않는 것과 실제 사건은 계속 값을 바꾸는 것이다.
    """
    cases = (
        ("민수 구슬은 8개 있다. 지연 구슬은 3개 있다. "
         "만약 민수가 지연에게 구슬 2개를 줬으면 지금 지연 구슬은 몇 개야?", "5개입니다."),
        ("사과는 8개 있다. 만약 사과 3개를 꺼냈으면 지금 사과는 몇 개야?", "5개입니다."),
        ("사과는 4개 있다. 만약 사과 3개를 넣었으면 지금 사과는 몇 개야?", "7개입니다."),
    )
    for text, expected in cases:
        context = ReasoningContext()
        result = context.turn(text, KG)
        assert result["answer"] == expected
        assert any(step["operation"] == "hypothetical_assumption" for step in result["transitions"])

    context = ReasoningContext()
    context.turn(cases[0][0], KG)
    assert context.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "3개입니다."

    actual = ReasoningContext()
    assert actual.turn("민수 구슬은 8개 있다. 지연 구슬은 3개 있다. "
                       "민수가 지연에게 구슬 2개를 줬다. 지금 지연 구슬은 몇 개야?", KG)["answer"] == "5개입니다."


def test_actor_and_item_bind_to_one_quantity_target_without_turning_negation_or_hypothesis_real():
    """주격 행위자·대상·수량·동작은 이름을 바꿔도 같은 상태 결합으로 읽는다."""
    cases = (
        ("민수", "구슬", "가", "꺼냈다", 8, 2, 6),
        ("하린", "공책", "이", "넣었다", 12, 5, 17),
    )
    for actor, item, particle, verb, start, amount, expected in cases:
        subject = f"{actor} {item}"
        text = (f"{subject}은 {start}개 있다. {actor}{particle} {item} {amount}개를 "
                f"{verb}. 지금 {subject}은 몇 개야?")
        result = ReasoningContext().turn(text, KG)
        assert result["answer"] == f"{expected}개입니다."
        action = next(step for step in result["transitions"]
                      if step["operation"] == "quantity_update")
        assert action["subject"] == subject

    parser = RelationalParser()
    parsed = parser.parse("민수가 구슬 2개를 꺼냈다", partial=True)
    assert parsed["facts"][0]["roles"] == {"actor": "민수", "item": "구슬"}

    hypothetical = ReasoningContext()
    projected = hypothetical.turn("민수 구슬은 8개 있다. 만약 민수가 구슬 2개를 꺼냈으면 "
                                  "지금 민수 구슬은 몇 개야?", KG)
    assert projected["answer"] == "6개입니다."
    assert hypothetical.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."


def test_explicit_role_selects_one_of_multiple_unfilled_events_but_keeps_other_requirements_open():
    """보완으로 고른 사건과 실행 가능한 사건을 같은 것으로 취급하지 않는다."""
    context = ReasoningContext()
    for text in (
        "베풀다는 내가 구슬을 상대에게 주는 것이다.",
        "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 도윤 구슬은 1개 있다.",
        "지연에게 베풀었다.",
        "도윤에게 베풀었다.",
    ):
        context.turn(text, KG)
    ambiguous = context.turn("민수야", KG)
    assert ambiguous["status"] == "unresolved"
    assert "어느 쪽 답인지" in ambiguous["answer"]

    # 수신자가 닻이므로 지연 사건만 보완한다. 이 정의는 수량을 정하지 않았고,
    # 따라서 남은 대상 역할을 임의로 채워 실행하거나 되물음을 닫으면 안 된다.
    selected = context.turn("민수가 지연에게 베풀었다.", KG)
    assert selected["status"] == "unresolved"
    live = [ask for ask in context.asked if not ask["해결"]]
    assert len(live) == 2
    jiyeon = next(ask for ask in live if ask["자리"] == {"에게": "지연"})
    doyun = next(ask for ask in live if ask["자리"] == {"에게": "도윤"})
    assert jiyeon["빈자리"] == {"item": "의"}
    assert doyun["빈자리"] == {"item": "의", "giver": "은"}
    assert context.fills == [{"사건": jiyeon["사건"], "역할": "은", "값": "민수",
                              "근거": "민수가 지연에게 베풀었다."}]
    assert context.turn("지금 지연 구슬은 몇 개야?", KG)["status"] == "unresolved"

    restored = ReasoningContext()
    restored.restore(context.snapshot())
    restored_live = [ask for ask in restored.asked if not ask["해결"]]
    assert any(ask["자리"] == {"에게": "지연"} and ask["빈자리"] == {"item": "의"}
               for ask in restored_live)

    negative = ReasoningContext().turn("민수 구슬은 8개 있다. 민수가 구슬 2개를 꺼내지 않았다. "
                                        "지금 민수 구슬은 몇 개야?", KG)
    assert negative["answer"] == "8개입니다."
    assert not any(step.get("operation") == "quantity_update" for step in negative["transitions"])


def test_elided_state_subject_is_shared_by_quantity_and_location_but_never_guessed():
    """수량만의 최근 명사 규칙이 아니라 가변 관계의 공통 역할 결합이다."""
    context = ReasoningContext()
    context.turn("공책은 책상에 있었다.", KG)
    assert context.turn("창고로 옮겼다.", KG)["status"] == "observed"
    assert context.turn("지금 공책은 어디에 있어?", KG)["answer"] == "창고에 있습니다."

    ambiguous = ReasoningContext()
    ambiguous.turn("공책은 책상에 있었다. 연필은 서랍에 있었다.", KG)
    held = ambiguous.turn("창고로 옮겼다.", KG)
    assert held["status"] == "unresolved"
    assert ambiguous.turn("지금 공책은 어디에 있어?", KG)["status"] == "unresolved"


def test_ui_remembers_observation_and_separates_sessions(tmp_path):
    pack = tmp_path / "context.kgpack"
    kgpack.write_pack(pack, [Path(KG)] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research") as research:
        first = app.turn("공책은 서랍에 있었다.", "session_context1")
        moved = app.turn("서우가 공책을 창고로 옮겼다.", "session_context1")
        answer = app.turn("지금 공책은 어디에 있어?", "session_context1")
        other = app.turn("지금 공책은 어디에 있어?", "session_context2")
    research.assert_not_called()
    assert first["answer"]["trace"]["verdict"] == moved["answer"]["trace"]["verdict"] == "상태기억"
    assert answer["answer"]["answer"] == "창고에 있습니다."
    assert other["answer"]["trace"]["verdict"] == "조건부족"
