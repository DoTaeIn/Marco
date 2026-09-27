from bench.understanding_grounding_reproduction import run
from reasoning_context import ReasoningContext

KG = "graphs/graph_일상추론.kg"
LANGUAGE = "styles/한국어.json"


def play(lines, **options):
    context = ReasoningContext(language=LANGUAGE, **options)
    return context, [context.turn(line, KG) for line in lines]


def test_grounding_raises_transfer_without_adding_wrong_answers():
    report = run()
    # The dropped-particle case is grammar, so it resolves in both modes.
    assert report["before"]["outcomes"] == {"solved": 1, "safe_hold": 21, "wrong": 0}
    assert report["after"]["outcomes"] == {"solved": 16, "safe_hold": 6, "wrong": 0}
    for row in report["after"]["cases"]:
        if row["must_ask"] is not None:
            assert row["asks"] == row["must_ask"], row["id"]
    # With the path off nothing is ever asked.
    assert not any(row["asks"] for row in report["before"]["cases"])


def test_the_ask_names_the_change_and_several_changes_wait_for_a_pick():
    context, replies = play(["민수 구슬은 8개 있다.", "민수가 구슬 3개를 뺐어."])
    asked = replies[-1]
    assert asked["status"] == "unresolved"
    assert asked["meaning"]["reason"] == "unknown_word_guesses"
    assert [[row["뒤"] for row in effect] for effect in asked["meaning"]["effects"]] == [["5"], ["11"]]
    # A bare yes picks nothing, and nothing is decided until a pick.
    assert context.turn("맞아", KG) is None
    assert context.turn("지금 민수 구슬은 몇 개야?", KG)["status"] == "unresolved"
    assert context.aliases == []


def test_a_confirmed_form_keeps_the_definition_it_was_confirmed_against():
    context, _ = play(["베풀다는 상대에게 구슬 2개를 주는 것이다.",
                       "민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
                       "민수가 지연에게 쥐여줬다.", "맞아",
                       "베풀다는 상대에게 구슬 3개를 주는 것이다.",
                       "민수가 지연에게 쥐여줬다."])
    assert context.aliases[0]["판"] == 0
    assert context.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "7개입니다."
    restored = ReasoningContext(language=LANGUAGE)
    restored.restore(context.snapshot())
    assert restored.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "7개입니다."
    # The taught verb itself follows its own redefinition.
    context.turn("민수가 지연에게 베풀었다.", KG)
    assert context.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "10개입니다."


def test_a_meaning_learned_from_an_observed_change_survives_restore():
    context, replies = play(["민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
                             "민수가 지연에게 구슬을 쥐여줬다.",
                             "민수 구슬은 6개 있다. 지연 구슬은 5개 있다."])
    assert replies[1]["meaning"]["reason"] == "unknown_word"
    assert replies[2]["status"] == "observed"
    assert replies[2]["meaning"]["from"] == "observed_change"
    assert context.turn("맞아", KG)["verification"]["checks"][0]["kind"] == "observed_change"
    restored = ReasoningContext(language=LANGUAGE)
    restored.restore(context.snapshot())
    for line in ("하루 구슬은 9개 있다. 도윤 구슬은 1개 있다.", "하루가 도윤에게 구슬을 쥐여줬다."):
        assert restored.turn(line, KG)["status"] == "observed"
    assert restored.turn("지금 도윤 구슬은 몇 개야?", KG)["answer"] == "3개입니다."


def test_a_snapshot_without_aliases_still_restores():
    context, _ = play(["민수 구슬은 8개 있다."])
    snapshot = context.snapshot()
    snapshot.pop("aliases")
    restored = ReasoningContext(language=LANGUAGE)
    restored.restore(snapshot)
    assert restored.aliases == []
    assert restored.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."


def test_a_confirmed_form_is_temporary_until_used_in_two_different_sentences():
    context, _ = play(["공책은 책상에 있었다.", "하루가 공책을 서랍으로 치웠다.", "맞아"])
    assert [row["status"] for row in context.learned_expressions()] == ["temporary"]
    for line in ("연필은 가방에 있었다.", "민수가 연필을 상자로 치웠다."):
        assert context.turn(line, KG)["status"] == "observed"
    learned = context.learned_expressions()
    assert [row["status"] for row in learned] == ["active"]
    assert learned[0]["사례"] == ["하루가 공책을 서랍으로 치웠다.", "민수가 연필을 상자로 치웠다."]
