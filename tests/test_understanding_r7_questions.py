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
    rows = _play("english", ["{a} has 6 {p}.", "How many {p} did {a} lose?", "How many {p} does {a} have hidden?"],
                 3, **EN_WORDS)
    assert all(row.get("status") != "answered" for row in rows[1:])


# ---------------------------------------------------------------------------
# short follow-ups, comparisons of two named holders, lookups under a near key (effort 2; 0 is main)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("follow_up,expected", [("What about {b}, please?", "4"), ("Maybe {b}?", "4")])
def test_a_follow_up_with_a_word_that_says_nothing_is_read(follow_up, expected):
    rows = _play("english", ["{a} has 6 {p}.", "{b} has 4 {p}.", "How many {p} does {a} have?", follow_up], 3, **EN_WORDS)
    assert rows[-1]["status"] == "answered" and expected in rows[-1]["answer"]


@pytest.mark.parametrize("language,frames", [
    ("english", ["{a} has 6 {p}.", "How many {p} does {a} have?", "{z}?"]),
    ("한국어", ["{a}는 {p}이 6개 있어.", "{a}는 {p}이 몇 개야?", "{z}는?"]),
])
def test_a_follow_up_naming_a_holder_never_counted_is_held_naming_it(language, frames):
    words = dict(EN_WORDS if language == "english" else KO_WORDS, z="Zed" if language == "english" else "제드")
    rows = _play(language, frames, 3, **words)
    assert rows[-1]["status"] != "answered" and words["z"] in rows[-1]["answer"]
    assert _play(language, frames, 0, **words)[-1] == {}


@pytest.mark.parametrize("language,frames,winner", [
    ("english", ["{a} has 6 {p}.", "{b} has 4 {p}.", "Between {a} and {b}, who has more {p}?"], "Nora"),
    ("english", ["{a} has 6 {p}.", "{b} has 4 {p}.", "{a} or {b}, who has fewer {p}?"], "Ivo"),
    ("english", ["{a} has 6 {p}.", "{b} has 4 {p}.", "Does {b} have more {p} than {a}?"], "Nora"),
    ("한국어", ["{a}는 {p}이 6개 있어.", "{b}는 {p}이 4개 있어.", "{b}가 {a}보다 {p}이 더 많아?"], "노라"),
])
def test_two_named_holders_compared_around_the_question_word(language, frames, winner):
    rows = _play(language, frames, 3, **(EN_WORDS if language == "english" else KO_WORDS))
    assert rows[-1]["status"] == "answered" and winner in rows[-1]["answer"]


@pytest.mark.parametrize("frames,expected", [
    (["{a} has 6 {p}.", "How many quill does {a} have?"], "6"),
    (["The red shed has 2 {p}.", "The blue shed has 5 {c}.", "How many {p} does the shed have?"], "2"),
    (["My uncle {b} has 3 {p}.", "How many {p} does my uncle have?"], "3"),
])
def test_a_count_asked_under_a_near_key_takes_the_one_key_it_names(frames, expected):
    rows = _play("english", frames, 3, **EN_WORDS)
    assert rows[-1]["status"] == "answered" and expected in rows[-1]["answer"]
    two = _play("english", ["The red shed has 2 {p}.", "The blue shed has 5 {p}.", "How many {p} does the shed have?"],
                3, **EN_WORDS)
    assert two[-1]["status"] != "answered"


# ---------------------------------------------------------------------------
# which person: words that describe several holders are asked back naming every one (effort 2; 0 is main)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language,frames,names,value", [
    ("english", ["My cousin {x} has 5 {p}.", "My cousin {y} has 3 {p}.", "How many {p} does my cousin have?", "{x}."],
     ("Lena", "Omar"), "5"),
    ("english", ["The nurse, {x}, has 5 {p}.", "The nurse, {y}, has 3 {p}.", "How many {p} does the nurse have?", "{y}."],
     ("Lena", "Omar"), "3"),
    ("한국어", ["제 친구 {x}은 {p}이 5개 있어.", "제 친구 {y}는 {p}이 3개 있어.", "그 친구는 {p}이 몇 개야?", "{x}이요."],
     ("미경", "수아"), "5"),
    ("한국어", ["김 과장님은 {p}이 5개 있어.", "이 과장님은 {p}이 3개 있어.", "과장님은 {p}이 몇 개야?", "김 과장님이요."],
     ("김 과장", "이 과장"), "5"),
])
def test_words_that_describe_several_holders_are_asked_back_and_the_reply_is_answered(language, frames, names, value):
    words = dict(EN_WORDS if language == "english" else KO_WORDS, x=names[0], y=names[1])
    rows = _play(language, frames, 3, **words)
    asked, reply = rows[-2], rows[-1]
    assert asked["status"] != "answered" and asked["meaning"]["reason"] == "which_referent"
    assert all(name in asked["answer"] for name in names)
    assert reply["status"] == "answered" and value in reply["answer"]


# ---------------------------------------------------------------------------
# a direction swap said two turns after its transfer (effort 2; 0 is main)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language,correction", [
    ("english", "{a} was the one who got two {p} from {b}, not the one giving."),
    ("english", "No, it was {b} who gave {a} the two {p}, not the other way."),
    ("한국어", "아니, 그게 아니야. {a}가 준 게 아니라 {b}가 {p}을 준 거야."),
    ("한국어", "아니, {a}가 아니라 {b}가 {p}을 {a}에게 줬어."),
    ("한국어", "아니, {a}가 {b}한테서 {p}을 받은 거야."),
])
def test_a_direction_swap_two_turns_after_its_transfer_is_corrected(language, correction):
    start = (EN_START + ["{b} has 3 {c}."]) if language == "english" else (KO_START + ["{b}는 컵이 3개 있어."])
    ask = "How many {p} does {b} have?" if language == "english" else "{b}는 {p}이 몇 개 있어?"
    words = EN_WORDS if language == "english" else KO_WORDS
    rows = _play(language, start + [correction, ask], 3, **words)
    assert rows[4]["status"] == "observed" and rows[4]["meaning"]["act"] == "revise"
    assert rows[5]["status"] == "answered" and "2" in rows[5]["answer"]
    main = _play(language, start + [correction, ask], 0, **words)
    assert main[5]["status"] != "answered"


@pytest.mark.parametrize("language,frames,names,value", [
    ("english", ["{x} has 5 {p}.", "{y} has 3 {p}.", "How many does the tall one have now?", "{y}, I guess."],
     ("Lena", "Omar"), "3"),
    ("english", ["My brother {x} has 5 {p}.", "His friend {y} has 3 {p}.", "How many does that guy have now?",
                 "{y}, the friend."], ("Lena", "Omar"), "3"),
    ("한국어", ["제 친구 {x}은 {p}이 3개 있어.", "제 동생 {y}는 {p}이 5개 있어.", "그 분은 이제 몇 개예요?", "{y} 씨요."],
     ("미경", "수아"), "5"),
    ("한국어", ["제 친구 {x}은 {p}이 3개 있어.", "제 동생 {y}는 {p}이 5개 있어.", "그 사람은 지금 몇 개야?",
               "{y} 말이에요 아마."], ("미경", "수아"), "5"),
])
def test_a_pointer_or_description_with_no_thing_asks_among_the_holders_of_the_conversations_thing(
        language, frames, names, value):
    words = dict(EN_WORDS if language == "english" else KO_WORDS, x=names[0], y=names[1])
    rows = _play(language, frames, 3, **words)
    asked, reply = rows[-2], rows[-1]
    assert asked["status"] != "answered" and asked["meaning"]["reason"] == "which_referent"
    assert all(name in asked["answer"] for name in names)
    assert reply["status"] == "answered" and value in reply["answer"]


def test_a_description_said_with_one_holder_answers_for_it():
    rows = _play("english", ["My brother {x} has 5 {p}.", "His friend {y} has 3 {p}.", "How many does her brother have now?"],
                 3, **dict(EN_WORDS, x="Lena", y="Omar"))
    assert rows[-1]["status"] == "answered" and "5" in rows[-1]["answer"]


def test_the_reply_to_a_which_person_ask_keeps_the_thing_asked_about():
    frames = ["{x}은 {p}이 3개 있어.", "{y}는 {p}이 5개 있어.", "{y}는 컵이 2개 있어.", "{x}과 {y}는 {p}이 몇 개야?",
              "그 분은 이제 몇 개예요?", "{y} 씨요."]
    rows = _play("한국어", frames, 3, **dict(KO_WORDS, x="미경", y="수아"))
    assert rows[-2]["meaning"]["reason"] == "which_referent"
    assert rows[-1]["status"] == "answered" and "5" in rows[-1]["answer"]


@pytest.mark.parametrize("frames,subject,expected", [
    (["{x}은 {p}이 6개 있어.", "{x} 삼촌 태오는 {p}이 3개 있어."], "{x}", "6"),          # H, beside H H H T
    (["{x}은 {p}이 6개 있어.", "{y}는 {p}이 3개 있어."], "{x} 거", "6"),                 # H + a word for "the thing"
    (["{x}은 {p}이 6개 있어.", "{y}는 {p}이 3개 있어."], "{x} 씨", "6"),                 # H + a title
    (["탐이 {p}을 6개 가지고 있어.", "{y}는 {p}이 3개 있어."], "탐은", "6"),              # a particle left on the name
])
def test_a_korean_count_asked_under_a_near_key_takes_the_holders_one_thing(frames, subject, expected):
    from pack_model import development_model
    from marco.reasoning.context import ReasoningContext
    words = dict(KO_WORDS, x="민석", y="수아")
    context = ReasoningContext(model=development_model("한국어"), effort=3)
    for frame in frames:
        context.turn(frame.format(**words))
    parser = context._parser()
    facts, _d, _p, _r = context._cached_replay(parser, context.observations, context.fills)
    query = [{"triple": [subject.format(**words), "count", "?n"], "render": ["$n", "개입니다."]}]
    grounded, _ask = context._ground_lookup(parser, query, facts)
    assert parser.answer({"facts": facts, "query": grounded})["answer"].startswith(expected)


def test_a_korean_count_under_a_noun_never_counted_is_left_as_asked():
    rows = _play("한국어", ["{x}은 {p}이 6개 있어.", "{y}는 {p}이 3개 있어.", "{x} 사과는 몇 개야?"], 3,
                 **dict(KO_WORDS, x="민석", y="수아"))
    assert rows[-1]["status"] != "answered"


# ---------------------------------------------------------------------------
# "the two": a total or a comparison whose holders are given as a number (effort 2; 0 is main)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language,frames,expected", [
    ("english", ["{a} has 6 {p}.", "{b} has 4 {p}.", "How many {p} does {a} have?", "How many {p} does {b} have?",
                 "How many do the two of them have altogether?"], "10"),
    ("english", ["{a} has 6 {p}.", "{b} has 4 {p}.", "How many {p} does {a} have?", "How many {p} does {b} have?",
                 "Which of the two has more?"], "Nora"),
    ("한국어", ["{a}는 {p}이 6개 있어.", "{b}는 {p}이 4개 있어.", "{a}는 {p}이 몇 개야?", "{b}는 {p}이 몇 개야?",
               "둘 중 누가 더 많아?"], "노라"),
    ("한국어", ["{a}는 {p}이 6개 있어.", "{b}는 {p}이 4개 있어.", "{a}는 {p}이 몇 개야?", "{b}는 {p}이 몇 개야?",
               "둘이 합쳐서 몇 개야?"], "10"),
])
def test_the_two_are_the_two_holders_just_asked_about(language, frames, expected):
    words = EN_WORDS if language == "english" else KO_WORDS
    rows = _play(language, frames, 3, **words)
    assert rows[-1]["status"] == "answered" and expected in rows[-1]["answer"]
    if frames[-1] != "둘이 합쳐서 몇 개야?":        # (main already sums the two when one thing is counted)
        assert _play(language, frames, 0, **words)[-1].get("status") != "answered"


def test_the_two_among_three_holders_of_the_thing_with_one_asked_about_is_not_answered():
    rows = _play("english", ["{a} has 6 {p}.", "{b} has 4 {p}.", "Kim has 2 {p}.", "How many {p} does {a} have?",
                             "How many do the two of them have altogether?", "Which of the two has more?"], 3, **EN_WORDS)
    assert rows[-1]["status"] != "answered" and rows[-2]["status"] != "answered"


def test_that_one_with_the_thing_named_is_a_pointer_not_a_holder_that():
    # the declared words for "the thing" (one, stuff) are no modifiers of the question frame
    rows = _play("english", ["{a} has 5 {p}.", "{b} has 3 {p}.", "{a} gave {b} a quill.",
                             "So how many {p} does that one have?"], 3, **EN_WORDS)
    assert rows[-1]["meaning"]["reason"] == "which_referent"
    assert "Nora" in rows[-1]["answer"] and "Ivo" in rows[-1]["answer"]


# ---------------------------------------------------------------------------
# a correction of a transfer whose numbers did not add up (kept unread): said again with the new amount
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language,correction", [
    ("english", "Not five, two."), ("english", "No, 2, not 5."), ("english", "No, two."),
    ("한국어", "아니, 다섯 개가 아니라 두 개야."),
])
def test_a_correction_of_a_refused_transfer_holds_naming_it_and_no_count_statement_is_touched(language, correction):
    if language == "english":
        frames = ["Wren has 3 figs.", "Tobin has 2 figs.", "Wren gave Tobin 5 figs.", correction,
                  "How many figs does Tobin have?", "How many figs does Wren have?"]
    else:
        frames = ["보늬는 자두가 3개 있어.", "하람은 자두가 2개 있어.", "보늬가 하람에게 자두를 5개 줬어.", correction,
                  "하람은 자두가 몇 개야?", "보늬는 자두가 몇 개야?"]
    rows = _play(language, frames, 3)
    # the transfer was never recorded: recording it at the correction would add an event, so the correction is held
    # naming it, and nothing is recorded (the count statement carrying the new amount least of all)
    assert rows[3]["status"] != "observed" and rows[3]["meaning"]["reason"] == "unread_event"
    assert frames[2] in rows[3]["answer"]
    assert rows[4]["status"] != "answered" and rows[5]["status"] != "answered"


@pytest.mark.parametrize("thing,total", [("과자 봉지", "모두"), ("우유 병", "전부"), ("연필 자루", "총")])
def test_a_counter_inside_the_things_name_is_no_scope_word(thing, total):
    frames = ["보늬는 %s가 3개 있어." % thing, "하람은 %s가 2개 있어." % thing, "보늬 %s는 %s 몇 개야?" % (thing, total)]
    rows = _play("한국어", frames, 3)
    assert rows[-1]["status"] == "answered" and "3" in rows[-1]["answer"]


def test_a_follow_up_named_only_by_an_unread_statement_takes_the_role_its_particle_gave_it():
    frames = ["보늬는 자두가 3개 있어.", "다온은 트럭에 자두를 한가득 싣고 달려왔어.", "보늬는 자두가 몇 개야?", "다온은?"]
    rows = _play("한국어", frames, 3)
    # 다온은 in the unread statement: a holder; the follow-up waits on that statement instead of asking which slot
    assert rows[-1]["meaning"]["reason"] == "unread_event" and frames[1] in rows[-1]["answer"]


def test_a_question_naming_the_thing_and_describing_the_person_asks_among_that_things_holders():
    rows = _play("english", ["{a} has 5 {p}.", "{b} has 3 {p}.", "{a} gave {b} a quill.",
                             "How many {p} does the other one have now?"], 3, **EN_WORDS)
    assert rows[-1]["meaning"]["reason"] == "which_referent"
    assert "Nora" in rows[-1]["answer"] and "Ivo" in rows[-1]["answer"]


@pytest.mark.parametrize("question", ["How many {s} {p} does the other one have now?", "How many {p} does my cousin have?",
                                      "How many {s} {m} {p} does my cousin have?"])
@pytest.mark.parametrize("reply,value", [("{b}.", "3"), ("{a}.", "5")])
def test_a_name_reply_answers_the_holder_who_said_the_thing_with_fewer_words(question, reply, value):
    # one thing node (step 3, statements 2); b counts it under the key b's statement said, which the lookup must use
    words = dict(EN_WORDS, s="speckled", m="linen", p="bowls")
    rows = _play("english", ["My cousin {a} has 5 {s} {m} {p}.", "My cousin {b} has 3 {s} {p}.", question, reply],
                 3, **words)
    assert rows[-2]["meaning"]["reason"] == "which_referent"
    assert rows[-1]["status"] == "answered" and value in rows[-1]["answer"]


@pytest.mark.parametrize("question", ["How many {p} does my cousin have?", "How many {s} does my cousin have?"])
def test_a_thing_asked_with_some_of_its_words_is_that_thing_and_no_part_of_the_person_asked(question):
    words = dict(EN_WORDS, s="speckled", m="linen", p="bowls")
    rows = _play("english", ["My cousin {a} has 5 {s} {m} {p}.", "My cousin {b} has 3 {s} {p}.", question, "{b}."],
                 3, **words)
    assert rows[-2]["meaning"]["reason"] == "which_referent" and rows[-2]["meaning"]["word"] == "my cousin"
    assert rows[-1]["status"] == "answered" and "3" in rows[-1]["answer"]


@pytest.mark.parametrize("language,frames,value", [
    ("english", ["My cousin {a} has 5 {p}.", "My cousin {b} has 3 {p}.", "How many {p} does my cousin have?",
                 "I think {b}. How many does {b} have?"], "3"),
    ("english", ["My cousin {a} has 5 {p}.", "My cousin {b} has 3 {p}.", "How many {p} does my cousin have?",
                 "{a}, I think. How many does {a} have?"], "5"),
    ("한국어", ["제 친구 {a}는 {p}이 5개 있어.", "제 친구 {b}는 {p}이 3개 있어.", "그 친구는 {p}이 몇 개야?",
               "아마 {b}요. {b}는 몇 개야?"], "3"),
    ("한국어", ["제 친구 {a}는 {p}이 5개 있어.", "제 친구 {b}는 {p}이 3개 있어.", "그 친구는 {p}이 몇 개야?",
               "아마 {a}요."], "5"),
])
def test_a_name_with_a_few_words_then_the_question_again_answers_the_which_person_ask(language, frames, value):
    rows = _play(language, frames, 3, **(EN_WORDS if language == "english" else KO_WORDS))
    assert rows[-2]["meaning"]["reason"] == "which_referent"
    assert rows[-1]["status"] == "answered" and value in rows[-1]["answer"]


@pytest.mark.parametrize("said,held", [
    ("Remind me about the {p}.", False), ("Grab some spare {p}.", False),
    ("Rats chewed the {p}.", True), ("Mysteriously, the {p} vanished.", True), ("The {p} were stolen.", True),
    ("Someone misplaced the {p}.", True), ("Thieves took two {p}.", True), ("{a} misplaced the {p}.", True),
])
def test_an_unread_turn_that_could_not_have_changed_a_count_holds_no_question_after_it(said, held):
    # no holder, no amount, no verb, opened by a word nobody declared: a request or a remark, no event (effort 2)
    rows = _play("english", ["{a} has 5 {p}.", "{b} has 3 {p}.", said, "How many {p} does {b} have?"], 3, **EN_WORDS)
    if held:
        assert rows[-1]["status"] != "answered" and rows[-1]["meaning"]["reason"] == "unread_event"
    else:
        assert rows[-1]["status"] == "answered" and "3" in rows[-1]["answer"]
    at_main = _play("english", ["{a} has 5 {p}.", "{b} has 3 {p}.", said, "How many {p} does {b} have?"], 0, **EN_WORDS)
    assert at_main[-1]["status"] != "answered"


@pytest.mark.parametrize("language,frames", [
    ("english", ["{a} has 5 {p}.", "{b} has 3 {p}.", "How many {p} does {b} have?", "Then they vanished.",
                 "How many {p} does {b} have?"]),
    ("english", ["{a} has 5 {p}.", "{b} has 3 {p}.", "Later she misplaced them.", "How many {p} does {a} have?"]),
    ("한국어", ["{a}는 {p}이 5개 있어.", "{b}는 {p}이 3개 있어.", "그는 그걸 다 잃어버렸어.", "{b}는 {p}이 몇 개야?"]),
])
@pytest.mark.parametrize("effort", [0, 3])
def test_an_unread_turn_that_names_its_holder_by_a_pointer_holds_every_count_after_it(language, frames, effort):
    # the pointer may be any holder: the count asked after it is not said as known
    rows = _play(language, frames, effort, **(EN_WORDS if language == "english" else KO_WORDS))
    assert rows[-1]["status"] != "answered"


def test_a_statement_after_the_pointer_turn_pins_the_count_again():
    rows = _play("english", ["{a} has 5 {p}.", "{b} has 3 {p}.", "Then they vanished.", "{b} has 2 {p}.",
                             "How many {p} does {b} have?"], 3, **EN_WORDS)
    assert rows[-1]["status"] == "answered" and "2" in rows[-1]["answer"]


HERBS = ["{a} has 5 bundles of herbs.", "{b} has 3 bundles of herbs.", "{a} gave {b} 2 bundles."]
INKS = ["Dr. {a} has 5 green inks.", "Mr. {b} has 2.", "Dr. {a} gave 3 inks to Mr. {b}."]


@pytest.mark.parametrize("frames,correction,question,value", [
    (HERBS, "Not 2, 3.", "How many bundles of herbs does {b} have?", "6"),
    (HERBS, "Not two, three.", "How many bundles of herbs does {a} have?", "2"),
    (INKS, "No, 4 inks were given, not 3.", "How many inks does {b} have?", "6"),
    (INKS, "Let me fix that: 4 inks were given, not 3.", "How many green inks does {a} have?", "1"),
])
def test_a_correction_of_an_event_that_said_the_thing_with_fewer_words_corrects_it(frames, correction, question, value):
    # the event's thing was read through the thing node; its rewrite is the same event by node, read the same way
    rows = _play("english", frames + [correction, question], 3, **EN_WORDS)
    assert rows[-2]["status"] == "observed" and rows[-2]["meaning"]["act"] == "correct"
    assert rows[-1]["status"] == "answered" and value in rows[-1]["answer"]
    # the answer rests on the correction, never on the withdrawn wording (the gate's retracted-evidence rule)
    from bench.dialogue_gate import _norm
    withdrawn = _norm(frames[-1].format(**EN_WORDS))
    quoted = [x for row in rows[-1].get("transitions") or [] for x in (
        (row.get("evidence") or {}).get("text"), (row.get("evidence") or {}).get("source"),
        ((row.get("evidence") or {}).get("normalization") or {}).get("canonical")) if x]
    assert quoted and not [x for x in quoted if _norm(x) and _norm(x) in withdrawn]


def test_two_amounts_with_no_word_that_marks_the_old_one_ask_which_event_and_correct_nothing():
    rows = _play("english", HERBS + ["No 2, 3.", "How many bundles of herbs does {b} have?"], 3, **EN_WORDS)
    assert rows[-2]["meaning"]["reason"] == "reference_which_event"
    assert rows[-1]["status"] == "answered" and "5" in rows[-1]["answer"]



PACKS = ["{a} has 43 packs of {p}.", "There are 23 {p} in each pack.", "{a} has 8 extra {p}."]


@pytest.mark.parametrize("effort", [0, 3])
@pytest.mark.parametrize("frames,held", [
    # the unread turn names the thing asked and a thing the holder holds: the later count does not settle it
    (PACKS + ["How many {p} does {a} have?"], "There are 23 {p} in each pack."),
    (["{a} has 43 packs.", "There are 23 {p} in each pack.", "{a} has 8 {p}.", "How many {p} does {a} have?"],
     "There are 23 {p} in each pack."),
    # the thing said in its other number
    (["{a} has 8 {p}.", "{b} has 3 {c}.", "Every bowl was cracked overnight.", "How many {c} does {b} have?"],
     "Every bowl was cracked overnight."),
])
def test_an_unread_turn_that_mentions_a_thing_the_holder_counts_holds_the_question_naming_it(frames, held, effort):
    rows = _play("english", frames, effort, **EN_WORDS)
    assert rows[-1]["status"] != "answered" and held.format(**EN_WORDS) in rows[-1]["answer"]


@pytest.mark.parametrize("frames,value", [
    # the unread turn names no node of the conversation, or no thing this holder counts: nothing new is held
    (["{a} has 8 {p}.", "The weather was lovely all week.", "How many {p} does {a} have?"], "8"),
    (["{a} has 8 {p}.", "{b} has 3 {c}.", "Every bowl was cracked overnight.", "How many {p} does {a} have?"], "8"),
    # every count the unread turn shook is said again after it
    (PACKS + ["{a} has 40 packs of {p}.", "{a} has 9 {p}.", "How many {p} does {a} have?"], "9"),
])
def test_an_unread_turn_holds_nothing_it_does_not_mention_and_a_restated_count_is_known_again(frames, value):
    rows = _play("english", frames, 3, **EN_WORDS)
    assert rows[-1]["status"] == "answered" and value in rows[-1]["answer"]


@pytest.mark.parametrize("language,frames,value", [
    ("english", EN_START + ["No, the other way round.", "How many {p} does {b} have?"], "2"),
    ("english", ["{a} has 6 {p}.", "{b} has 4 {p}.", "{c} has 3 {p}.", "{a} gave {b} two {p}.", "{c} gave {a} one quill.",
                 "No, the other way round.", "How many {p} does {c} have?"], "4"),
    ("한국어", ["{a}는 {p} 6개가 있고, {b}는 4개가 있어.", "{a}가 {b}에게 {p} 2개를 줬어.", "{b}는 {p}이 몇 개야?",
               "아니, 반대야. 거꾸로 된 거야.", "{b}는 {p}이 몇 개야?"], "2"),
])
def test_the_other_way_round_with_no_name_swaps_the_last_transfer(language, frames, value):
    # a swap word with no holder and no amount: the latest transfer's giver and receiver swapped (effort 2)
    rows = _play(language, frames, 3, **(dict(EN_WORDS, c="Tam") if language == "english" else KO_WORDS))
    assert rows[-2]["status"] == "observed" and rows[-2]["meaning"]["act"] == "revise"
    assert rows[-1]["status"] == "answered" and value in rows[-1]["answer"]
    # the answer rests on the rewritten transfer, never on the withdrawn wording (the gate's retracted-evidence rule)
    from bench.dialogue_gate import _norm
    words = dict(EN_WORDS, c="Tam") if language == "english" else KO_WORDS
    transfers = [f.format(**words) for f in frames[:-2] if "gave" in f or "줬어" in f]
    withdrawn = _norm(transfers[-1])
    quoted = [x for row in rows[-1].get("transitions") or [] for x in (
        (row.get("evidence") or {}).get("text"), (row.get("evidence") or {}).get("source"),
        ((row.get("evidence") or {}).get("normalization") or {}).get("canonical")) if x]
    assert quoted and not [x for x in quoted if _norm(x) and _norm(x) in withdrawn]


def test_a_question_with_a_swap_word_swaps_nothing():
    rows = _play("english", EN_START + ["Was it the other way round?", "How many {p} does {b} have?"], 3, **EN_WORDS)
    assert rows[-2].get("status") != "observed"
    assert rows[-1]["status"] == "answered" and "6" in rows[-1]["answer"]


KO_GAVE = ["{a}는 {p} 6개가 있고, {b}는 4개가 있어.", "{a}가 {b}에게 {p} 2개를 줬어.", "{b}는 {p}이 몇 개야?"]


@pytest.mark.parametrize("correction", [
    "아니, 그렇게 된 게 아니야 사실은. {b}는 상대방한테 줬어.",
    "아니, 그게 아니고 다른 얘기야. {b}는 그 사람한테 줬어.",
])
def test_the_transfer_said_again_with_the_receiver_as_giver_and_no_other_name_swaps_it(correction):
    # no swap word: the event restated, one holder named with the giver's particle, the other slot a word that is no name
    rows = _play("한국어", KO_GAVE + [correction, "{b}는 {p}이 몇 개야?", "{a}는 {p}이 몇 개야?"], 3, **KO_WORDS)
    assert rows[-3]["status"] == "observed" and rows[-3]["meaning"]["act"] == "revise"
    assert rows[-2]["status"] == "answered" and "2" in rows[-2]["answer"]
    assert rows[-1]["status"] == "answered" and "8" in rows[-1]["answer"]
    from bench.dialogue_gate import _norm
    withdrawn = _norm(KO_GAVE[1].format(**KO_WORDS))
    quoted = [x for row in rows[-2].get("transitions") or [] for x in (
        (row.get("evidence") or {}).get("text"), (row.get("evidence") or {}).get("source"),
        ((row.get("evidence") or {}).get("normalization") or {}).get("canonical")) if x]
    assert quoted and not [x for x in quoted if _norm(x) and _norm(x) in withdrawn]


@pytest.mark.parametrize("correction", [
    "아니, 그렇게 된 게 아니야 사실은. {a}는 상대방한테 줬어.",      # the giver named as giver: the event as it was said
    "아니, 그렇게 된 게 아니야 사실은. {b}는 상대방한테 받았어.",    # another verb: not this event said again
])
def test_the_transfer_said_again_the_same_way_or_with_another_verb_swaps_nothing(correction):
    rows = _play("한국어", KO_GAVE + [correction], 3, **KO_WORDS)
    assert rows[-1].get("status") != "observed"
