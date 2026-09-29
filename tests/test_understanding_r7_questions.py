"""Goal G7-Q: questions read as a frame plus slots, follow-ups as partial frames, under an effort budget.

Effort (amendment A2): level 0 is main's behaviour as it was when round 7 began (8c90141/da949e9),
byte for byte; each higher level only adds candidates the checks then validate.
"""
import os

import pytest

os.environ.setdefault("KG_ENCODER", "문자")

# The seven-step replies on main before round 7 (da949e9), both languages.
SEVEN_STEP_MAIN = {
    "english": [
        "Recorded. Jiyeon has 2 apples.",
        "Recorded. Minsu gave Jiyeon 2 apples. Now Minsu has 3 apples and Jiyeon has 4.",
        "4 apples.",
        "This conversation never stated the location of Jiyeon. So I did not answer.",
        "I changed the amount in the same event \"Minsu gave Jiyeon two.\" from 2 to 1. No new event was added. "
        "Now Minsu has 4 apples and Jiyeon has 3.",
        "Now Minsu has 4 apples and Jiyeon has 3. This is because of the correction \"Actually, the one given was "
        "one, not two.\". I changed the amount in the same event \"Minsu gave Jiyeon two.\" from 2 to 1. No new "
        "event was added. The giver loses that many. The receiver gains that many. It rests on \"Minsu has five "
        "apples, and Jiyeon has two.\", \"Minsu gave Jiyeon 1.\", \"Minsu gave Jiyeon two.\" and \"Actually, the "
        "one given was one, not two.\".",
        "I do not know who 'that one' refers to. Which of 'Jiyeon' and 'Minsu' do you mean?",
        "3개입니다.",
        "3 apples.",
        "3개입니다.",
    ],
    "한국어": [
        "반영했습니다. 민수 사과는 5개, 지연은 2개입니다.",
        "반영했습니다. 민수가 지연에게 사과 2개를 줬습니다. 이제 민수 사과는 3개, 지연은 4개입니다.",
        "4개입니다.",
        "이 대화에서 지연의 위치는 나온 적이 없습니다. 그래서 답하지 않았습니다.",
        "같은 사건 \"민수가 지연에게 두 개 줬어.\"의 수량을 2개에서 1개로 고쳤습니다. 새 사건은 더하지 않았습니다. "
        "이제 민수 사과는 4개, 지연은 3개입니다.",
        "이제 민수 사과는 4개, 지연은 3개입니다. 정정 \"아까 준 건 두 개가 아니라 한 개야.\" 때문입니다. 같은 사건 "
        "\"민수가 지연에게 두 개 줬어.\"의 수량을 2개에서 1개로 고쳤습니다. 새 사건은 더하지 않았습니다. 주는 쪽에서 "
        "그만큼 뺍니다. 받는 쪽에 그만큼 더합니다. 근거는 \"민수는 사과 다섯 개, 지연은 두 개가 있어.\", \"민수가 "
        "지연에게 한 개 줬어.\", \"민수가 지연에게 두 개 줬어.\", \"아까 준 건 두 개가 아니라 한 개야.\"입니다. 이 "
        "가운데 수정으로 읽은 말: \"민수는 사과 다섯 개\" → \"민수 사과는 다섯 개\"; \"지연은 두 개가 있어\" → "
        "\"지연은 두 개 있어\"; \"민수가 지연에게 한 개 줬어\" → \"민수가 지연에게 한 개를 줬어\".",
        "'그 사람'이 누구를 가리키는지 알지 못합니다. '민수', '지연' 가운데 누구인가요?",
        "3 apples.",
        "3개입니다.",
        "3 apples.",
    ],
}


# ---------------------------------------------------------------------------
# effort: the declared setting
# ---------------------------------------------------------------------------
def test_effort_is_declared_per_context_then_by_environment(monkeypatch):
    from marco.reasoning.context import ReasoningContext
    monkeypatch.delenv("MARCO_EFFORT", raising=False)
    assert ReasoningContext().effort == 3
    assert ReasoningContext(effort=1).effort == 1
    monkeypatch.setenv("MARCO_EFFORT", "0")
    assert ReasoningContext().effort == 0
    assert ReasoningContext(effort=2).effort == 2
    with pytest.raises(ValueError):
        ReasoningContext(effort=4)


@pytest.mark.parametrize("language", ["english", "한국어"])
@pytest.mark.parametrize("effort", ["0", "3"])
def test_seven_step_replies_at_effort_are_mains(monkeypatch, language, effort):
    from bench.seven_step_dialogue import run
    monkeypatch.setenv("MARCO_EFFORT", effort)
    report = run(language)
    assert report["passed"] == report["total"] == 7
    assert [reply["answer"] for reply in report["replies"]] == SEVEN_STEP_MAIN[language]
