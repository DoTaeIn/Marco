"""An unread statement that carries a count holds every count it could have moved.

The count may be a numeral with a particle on it (``하나를``). Found with dialogues written outside
the repository: the statement was left unread, and the holder's old count was still said as known.
"""
from pack_model import development_model
from marco.reasoning.context import ReasoningContext

KG = "graphs/graph_일상추론.kg"


def context(language):
    other = "english" if language == "한국어" else "한국어"
    return ReasoningContext(model=development_model(language), companions=[development_model(other)])


def test_a_numeral_with_a_particle_counts_as_a_number():
    parser = context("한국어")._parser()
    assert ReasoningContext._counts_something("그중 하나를 빌려줬어.", parser)
    assert ReasoningContext._counts_something("셋을 더 넣었다", parser)
    # a word that only ends like a particle is not a number
    assert not ReasoningContext._counts_something("단추 이야기는 재밌다", parser)
    # a Sino-Korean digit that is also a word is not a count (일: a matter, 이: a tooth)
    assert not ReasoningContext._counts_something("도윤이 소라에게 베푼 일은 전달 가능한가", parser)
    assert not ReasoningContext._counts_something("이가 아프다", parser)


def test_an_unread_statement_with_such_a_numeral_holds_the_count():
    current = context("한국어")
    assert current.turn("다래가 부채 여섯 개를 가지고 있어.", KG)["status"] == "observed"
    unread = current.turn("그중 하나를 빌려줬어.", KG)
    assert (unread or {}).get("status") != "observed"
    asked = current.turn("다래한테 부채가 몇 개 남았어?", KG)
    assert asked["status"] != "answered"
    assert "6" not in (asked.get("answer") or "")
