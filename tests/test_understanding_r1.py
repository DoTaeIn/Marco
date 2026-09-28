"""Understanding round 1: each rule reads a class of sentences, not one sentence.

Every test uses its own names, items and amounts. None of these sentences is
in the development set (``data/benchmarks/dialogues_dev``), and the last test
checks that no development sentence appears in a file this round changed.
"""
from pathlib import Path
import re

import pytest

from pack_model import development_model
from marco.reasoning.context import ReasoningContext

ROOT = Path(__file__).resolve().parents[1]


def play(language, lines):
    other = "english" if language == "한국어" else "한국어"
    context = ReasoningContext(model=development_model(language), companions=[development_model(other)])
    return [context.turn(line) or {"status": None, "answer": None} for line in lines]


def numbers(text):
    return re.findall(r"\d+", text or "")


def test_a_suffixed_korean_name_is_one_holder():
    rows = play("한국어", ["소민이는 단추 다섯 개 있어.", "재현이는 단추 한 개 있어.",
                          "소민이가 재현이한테 단추 두 개를 줬어.", "재현이는 몇 개야?"])
    assert [r["status"] for r in rows] == ["observed", "observed", "observed", "answered"]
    assert numbers(rows[-1]["answer"]) == ["3"]


def test_a_connective_carries_the_item_like_a_comma():
    rows = play("english", ["Pia has six kites and Rui has one.", "How many kites does Rui have?"])
    assert rows[-1]["status"] == "answered" and numbers(rows[-1]["answer"]) == ["1"]


def test_one_thing_and_its_plural_are_the_same_holding():
    rows = play("english", ["Ola had one lamp.", "Ivo has 5 lamps.", "Ivo gave Ola 2 lamps.",
                            "How many lamps does Ola have?"])
    assert rows[-1]["status"] == "answered" and numbers(rows[-1]["answer"]) == ["3"]


def test_a_marked_owner_is_split_off_a_stated_count():
    rows = play("한국어", ["미소는 모자가 일곱 개 있다.", "강이는 모자가 두 개 있다.",
                          "미소가 강이에게 모자 세 개를 주었다.", "미소는 모자가 몇 개 남았어?"])
    assert [r["status"] for r in rows[:3]] == ["observed"] * 3
    assert numbers(rows[-1]["answer"]) == ["4"]


def test_any_declared_counter_and_the_formal_ending_read_alike():
    rows = play("한국어", ["다온이는 공 여섯 권을 가지고 있습니다.", "시안이는 공이 두 권 있습니다.",
                          "다온이가 시안이한테 공 세 권을 드렸습니다.", "시안이는 공 몇 권이야?"])
    assert [r["status"] for r in rows[:3]] == ["observed"] * 3
    assert numbers(rows[-1]["answer"]) == ["5"]


def test_verbs_declared_with_a_known_frame_move_amounts():
    rows = play("english", ["Ula owns 8 cups.", "Bo owns 1 cup.", "Ula handed Bo 3 cups.",
                            "How many cups does Bo have now?"])
    assert numbers(rows[-1]["answer"]) == ["4"]


def test_declared_phrases_read_as_their_variant():
    rows = play("english", ["Cy's got 7 rings.", "Di's got 2 rings.", "Then Cy gave Di 3 of them.",
                            "How many rings does Di have?"])
    assert [r["status"] for r in rows[:3]] == ["observed"] * 3
    assert numbers(rows[-1]["answer"]) == ["5"]


def test_a_korean_count_question_is_read_by_its_parts():
    rows = play("한국어", ["보미는 연필이 아홉 자루 있다.", "보미는 지금 연필 몇 자루가 남았지?"])
    assert rows[-1]["status"] == "answered" and numbers(rows[-1]["answer"]) == ["9"]


def test_a_reply_that_names_a_person_asks_about_them():
    rows = play("english", ["Kit has 4 pens and Lu has 9.", "How many pens does Kit have?", "And Lu?"])
    assert numbers(rows[-1]["answer"]) == ["9"]
    rows = play("english", ["Kit has 4 pens and Lu has 9.", "Kit gave Lu one pen.",
                            "How many pens does she have now?", "I mean Kit."])
    assert rows[-2]["status"] == "unresolved" and "Kit" in rows[-2]["answer"] and "Lu" in rows[-2]["answer"]
    assert rows[-1]["status"] == "answered" and numbers(rows[-1]["answer"]) == ["3"]


def test_a_contrast_corrects_the_one_statement_that_carried_the_old_amount():
    rows = play("english", ["Ed has 9 coins.", "Fi has 2 coins.", "Ed gave Fi 4 coins.",
                            "No, it was three coins, not four.", "How many coins does Fi have?"])
    assert rows[3]["status"] == "observed"
    assert numbers(rows[-1]["answer"]) == ["5"]
    rows = play("english", ["Ed has 4 coins.", "Fi has 4 coins.", "Actually it was five, not four."])
    assert rows[-1]["status"] == "unresolved"   # two statements carried 4: asked, not picked


def test_a_total_and_a_comparison_read_current_counts():
    rows = play("english", ["Gil has 6 caps and Hal has 3.", "Gil gave Hal 1 cap.",
                            "How many caps do Gil and Hal have together?",
                            "Who has more caps now, Gil or Hal?"])
    assert numbers(rows[2]["answer"]) == ["9"]
    assert "Gil" in rows[3]["answer"] and "Hal" not in rows[3]["answer"]


def test_a_total_is_held_while_an_event_is_unread():
    rows = play("english", ["Gil has 6 caps and Hal has 3.", "Gil flurbed Hal two caps.",
                            "How many caps do Gil and Hal have together?"])
    assert rows[-1]["status"] != "answered"


def test_role_reversed_frames_move_the_amount_the_right_way():
    rows = play("english", ["Jo has 5 bells and Ki has 2 bells.", "Ki took two bells from Jo.",
                            "How many bells does Jo have?"])
    assert numbers(rows[-1]["answer"]) == ["3"]
    rows = play("한국어", ["나리는 공이 세 개 있어.", "도담이는 공이 여섯 개 있어.",
                          "나리가 도담이한테서 공 두 개를 받았어.", "나리는 공이 몇 개야?"])
    assert numbers(rows[-1]["answer"]) == ["5"]


def test_several_people_named_in_a_turn_leave_a_pointer_open():
    rows = play("english", ["Ma has 3 hats and Ne has 5.", "Ma gave Ne one hat.", "How many hats does she have?"])
    assert rows[-1]["status"] != "answered"


def test_no_development_sentence_is_in_a_file_this_round_changed():
    import bench.dialogue_gate as gate
    dialogues = gate.load(ROOT / "data/benchmarks/dialogues_dev")
    sentences = gate.dialogue_sentences(dialogues)
    owned = ["marco/language/frames.py", "language_components.py", "relational_semantics.py", "marco/language/hangul.py",
             "engine.py", "explain.py", "marco/reasoning/context.py", "marco/reasoning/state.py", "bench/dialogue_gate.py",
             "tests/test_understanding_r1.py"] + sorted(
        p.relative_to(ROOT).as_posix() for p in (ROOT / "styles").glob("*.json"))
    found = []
    for name in owned:
        text = gate._normalize_corpus((ROOT / name).read_text(encoding="utf-8"))
        for did, n, raw, norm in sentences:
            if norm in text and gate._full_sentence_at(text, norm):
                found.append((did, n, raw, name))
    assert found == []
