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


# ---------------------------------------------------------------------------
# ranking: the declared order, a clear win answers, a tie asks, none holds (amendment A4)
# ---------------------------------------------------------------------------
def test_rank_candidates_decides_by_the_first_check_that_differs():
    from marco.reasoning.context import ReasoningContext
    context = ReasoningContext(effort=3)
    a = {"label": "a", "fit": {"state": 1, "reasoning": 0, "grammar": 5, "cost": 3}}
    b = {"label": "b", "fit": {"state": 1, "reasoning": 1, "grammar": 0, "cost": 9}}
    winner, deciding, ranking = context._rank_candidates([a, b])
    assert winner is b and deciding == "reasoning" and [c["label"] for c in ranking] == ["b", "a"]
    cheap = {"label": "c", "fit": {"state": 1, "reasoning": 1, "grammar": 0, "cost": 1}}
    assert context._rank_candidates([b, cheap])[:2] == (cheap, "cost")
    assert context._rank_candidates([b, dict(b, label="b2")])[:2] == (None, "tie")
    assert context._rank_candidates([a])[:2] == (a, "only")
    assert context._rank_candidates([]) == (None, None, [])
    assert [r["decided_by"] for r in context._trace_rankings] == ["reasoning", "cost", "tie", "only", None]
    assert context._trace_rankings[0]["effort"] == 3 and context._trace_rankings[0]["winner"] == "b"


def test_rank_treats_a_missing_check_as_zero_and_bools_as_fits():
    from marco.reasoning.context import ReasoningContext
    context = ReasoningContext()
    fits = {"label": "fits", "fit": {"state": True}}
    bare = {"label": "bare", "fit": {}}
    assert context._rank_candidates([bare, fits])[:2] == (fits, "state")


def test_rank_refuses_a_fit_that_is_not_a_count():
    from marco.reasoning.context import ReasoningContext
    context = ReasoningContext()
    for fit in ({"state": 0.7}, {"grammar": "1"}, {"cost": -1}, {"weight": 1}):
        with pytest.raises(ValueError):
            context._rank_candidates([{"label": "x", "fit": fit}, {"label": "y", "fit": {}}])


# ---------------------------------------------------------------------------
# A5: effort 3 is turn-local deliberation only
# ---------------------------------------------------------------------------
def _writes_under(monkeypatch, folders):
    """Record every file this process opens for writing, or moves into place, under ``folders`` (other tests
    running in parallel may write there; only this process's writes are this test's)."""
    import builtins
    import io
    import os
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    roots = [root / folder for folder in folders]
    written = []

    def watched(path):
        try:
            resolved = Path(path).resolve()
        except (TypeError, OSError):
            return False
        return any(resolved.is_relative_to(r) for r in roots)
    real_open, real_io_open, real_replace, real_rename = builtins.open, io.open, os.replace, os.rename

    def spy_open(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in "wax+") and watched(file):
            written.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    def spy_io_open(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in "wax+") and watched(file):
            written.append(str(file))
        return real_io_open(file, mode, *args, **kwargs)

    def spy_move(real):
        def move(src, dst, *args, **kwargs):
            if watched(dst):
                written.append(str(dst))
            return real(src, dst, *args, **kwargs)
        return move
    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(io, "open", spy_io_open)
    monkeypatch.setattr(os, "replace", spy_move(real_replace))
    monkeypatch.setattr(os, "rename", spy_move(real_rename))
    return written


def test_effort_three_leaves_packs_graphs_and_declarations_untouched_and_calls_no_research(monkeypatch):
    from bench import dialogue_gate as gate
    monkeypatch.setenv("MARCO_EFFORT", "3")
    # written as frames and filled here, so that no full sentence of another corpus stands in this file
    frames = ["{a} has 6 {p}.", "{b} has 4 {p}.", "{a} has 11 {c}.", "Jasper's aunt, {w}, has 3 {p}.",
              "How many {p} does {a} have?", "And {c}?", "What about {b}?", "{w}, I mean.",
              "How many {p} do {a} and {b} have combined?", "Who has more {p} left, {a} or {b}?"]
    turns = [f.format(a="Nell", b="Ivo", w="Tamsin", p="quills", c="bowls") for f in frames]
    dialogue = {"id": "r7_a5_pin", "language": "en", "turns": [{"n": i + 1, "say": t} for i, t in enumerate(turns)]}
    written = _writes_under(monkeypatch, ("styles", "axioms", "graphs", "marco/language/realizer"))
    answers = gate.run([dialogue])
    monkeypatch.undo()
    assert written == []
    rows = answers["r7_a5_pin"]
    assert len(rows) == len(turns) and not any(r.get("error") for r in rows)
    assert all(r.get("research_calls") == 0 for r in rows)


# ---------------------------------------------------------------------------
# partial readings grounded against the state (effort 2 and above; 0 is main)
# ---------------------------------------------------------------------------
def _play(language, frames, effort, companion=None, **words):
    from pack_model import development_model
    from marco.reasoning.context import ReasoningContext
    context = ReasoningContext(model=development_model(language), effort=effort,
                               companions=[development_model(companion)] if companion else [])
    return [context.turn(frame.format(**words)) or {} for frame in frames]


EN_WORDS = dict(a="Nora", b="Ivo", p="quills", c="bowls")
KO_WORDS = dict(a="노라", b="이보", p="깃펜")
EN_START = ["{a} has 6 {p}.", "{b} has 4 {p}.", "{a} gave {b} two {p}."]
KO_START = ["{a}는 {p}이 6개 있어.", "{b}는 {p}이 4개 있어.", "{a}가 {b}에게 {p}을 두 개 줬어."]


@pytest.mark.parametrize("language,start,correction,words,value", [
    ("english", EN_START, "No, three.", EN_WORDS, "7"),
    ("english", EN_START, "Not two, three.", EN_WORDS, "7"),
    ("english", EN_START, "No, {b} gave them to {a}.", EN_WORDS, "2"),
    ("한국어", KO_START, "아니, 세 개.", KO_WORDS, "7"),
    ("한국어", KO_START, "아니, {b}가 {a}한테 준 거야.", KO_WORDS, "2"),
])
def test_a_correction_with_open_slots_is_grounded_on_the_last_event(language, start, correction, words, value):
    ask = "How many {p} does {b} have?" if language == "english" else "{b}는 {p}이 몇 개 있어?"
    rows = _play(language, start + [correction, ask], 3, **words)
    assert rows[3]["meaning"]["act"] in ("correct", "revise") and rows[3]["status"] == "observed"
    assert rows[4]["status"] == "answered" and value in rows[4]["answer"]
    main = _play(language, start + [correction, ask], 0, **words)
    assert main[3] == {} and main[4]["status"] != "answered"


def test_a_question_in_the_other_language_takes_the_one_thing_its_holder_counts():
    rows = _play("english", ["{a} has 6 {p}.", "{b} has 4 {p}.", "{b} has 2 {c}.", "노라는 깃펜이 몇 개 있어?",
                             "이보는 깃펜이 몇 개 있어?"], 3, companion="한국어", **EN_WORDS)
    assert rows[3]["status"] == "answered" and "6" in rows[3]["answer"]
    # Ivo counts two things and no declared word says which: never answered
    assert rows[4]["status"] != "answered"
    main = _play("english", ["{a} has 6 {p}.", "노라는 깃펜이 몇 개 있어?"], 0, companion="한국어", **EN_WORDS)
    assert main[1]["status"] != "answered"


def test_an_unread_question_is_read_by_its_words_grounded_in_the_state():
    rows = _play("english", ["{a} has 6 {p}.", "{b} has 4 {p}.", "{a}, how many {p} now?",
                             "Zed has how many {p} now?"], 3, **EN_WORDS)
    assert rows[2]["status"] == "answered" and "6" in rows[2]["answer"]
    # a holder the conversation never counted: held naming it, not left unread
    assert rows[3]["status"] != "answered" and rows[3]["meaning"]["reason"] == "not_stated" and "Zed" in rows[3]["answer"]
    main = _play("english", ["{a} has 6 {p}.", "{a}, how many {p} now?"], 0, **EN_WORDS)
    assert main[1] == {}


def test_a_word_nobody_declared_still_leaves_a_question_unread():
    rows = _play("english", ["{a} has 6 {p}.", "How many {p} did {a} lose?", "How many {p} does {a} have, please?"], 3,
                 **EN_WORDS)
    assert rows[1] == {} and rows[2] == {}
