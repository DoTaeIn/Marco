"""Round 6, reading 2: a held count released by a later statement of it, and the classes that still
failed on dialogues written outside the repository."""
from pack_model import development_model
from reasoning_context import ReasoningContext

KG = "graphs/graph_일상추론.kg"


def context(language):
    other = "english" if language == "한국어" else "한국어"
    return ReasoningContext(model=development_model(language), companions=[development_model(other)])


def run(language, lines):
    current = context(language)
    return [current.turn(line, KG) for line in lines]


# --- A. a held count is released only by a later statement of that holder's count ---

def test_a_later_statement_of_the_count_releases_the_hold():
    *_, asked = run("한국어", ["다래가 부채 여섯 개를 가지고 있어.", "그중 하나를 빌려줬어.",
                               "다래는 부채 5개가 있어.", "다래는 부채가 몇 개야?"])
    assert asked["status"] == "answered" and "5" in asked["answer"]


def test_without_a_later_statement_the_count_stays_held():
    *_, asked = run("한국어", ["다래가 부채 여섯 개를 가지고 있어.", "그중 하나를 빌려줬어.",
                               "다래는 부채가 몇 개야?"])
    assert asked["status"] != "answered"


def test_a_later_statement_of_another_holders_count_does_not_release_it():
    *_, other, asked = run("한국어", ["다래가 부채 여섯 개를 가지고 있어.", "보라가 부채 세 개를 가지고 있어.",
                                      "그중 하나를 빌려줬어.", "보라는 부채 5개가 있어.",
                                      "보라는 부채가 몇 개야?", "다래는 부채가 몇 개야?"])
    assert other["status"] == "answered" and "5" in other["answer"]
    assert asked["status"] != "answered"
