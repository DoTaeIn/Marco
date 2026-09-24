"""Understanding round 4: natural language, not templates.

Every test uses its own names, items and amounts; none of these sentences is in a
development set, and the overlap tests at the end check that.
"""
import importlib.util
import json
from pathlib import Path
import re

import pytest

from pack_model import development_model
from reasoning_context import ReasoningContext

ROOT = Path(__file__).resolve().parents[1]
DEV4 = ROOT / "data/benchmarks/dialogues_dev4"
_MODELS = {}


def model(language):
    if language not in _MODELS:
        _MODELS[language] = development_model(language)
    return _MODELS[language]


def context(language):
    other = "english" if language == "한국어" else "한국어"
    return ReasoningContext(model=model(language), companions=[model(other)])


def play(language, lines):
    current, rows = context(language), []
    for line in lines:
        rows.append(current.turn(line) or {"status": None, "answer": None})
    return rows


def asserted_numbers(text):
    import bench.dialogue_gate as gate
    return gate.quantities(gate.asserted(text or ""))


def state_after(language, lines):
    from graph_inference import current_facts
    current = context(language)
    for line in lines:
        current.turn(line)
    parser = current._parser()
    facts, _d, _p, _r = current._cached_replay(parser, current.observations, current.fills)
    state, _c = current_facts(facts, parser.data.get("mutable_predicates", []), parser.data.get("numeric_updates", {}))
    return {row["triple"][0]: row["triple"][2] for row in state if row["triple"][1] == "count"}


def facts_of(language, text):
    parsed = model(language).parser().parse(text, partial=True, events=True, repair=True) or {}
    return sorted(tuple(map(str, row["triple"])) for row in parsed.get("facts", []))


# G4.5 (a): a referent repair re-binds the previous question's pointer and answers it ------------
#
# Each case asks about one person (by name or by a pointer), then says who was meant in a
# turn of its own; the repair is answered with the meant person's count.

REPAIRS = [
    ("english", ["Tamsin has 7 quills.", "Fergus has 3 quills.", "How many quills does Fergus have?"],
     "I mean Tamsin.", 7),
    ("english", ["Tamsin has 7 quills.", "Fergus has 3 quills.", "How many quills does Fergus have?"],
     "Tamsin, I mean.", 7),
    ("english", ["Tamsin has 7 quills.", "Oona has 3 quills.", "How many quills does she have now?"],
     "Oona is who I meant.", 3),
    ("english", ["Dr. Leif has 8 thimbles.", "Tamsin has 2 thimbles.", "How many thimbles does Tamsin hold?"],
     "Sorry, I meant Dr. Leif.", 8),
    ("english", ["Tamsin has 7 quills.", "Fergus has 3 quills.", "Tamsin gave Fergus 2 quills.",
                 "How many quills has Fergus got?", "And how many has he got now?"], "I meant Tamsin.", 5),
    ("한국어", ["하늬는 골무가 7개 있어요.", "라온은 골무가 3개 있어요.", "라온은 골무가 몇 개 있어요?"], "하늬 말이에요.", 7),
    ("한국어", ["하늬는 골무가 7개 있어요.", "라온은 골무가 3개 있어요.", "그분은 지금 골무가 몇 개 있어요?"],
     "제 말은 라온 씨예요.", 3),
    ("한국어", ["하늬는 골무가 7개 있어요.", "라온은 골무가 3개 있어요.", "라온은 골무가 몇 개 남았어요?"], "아, 하늬요.", 7),
    ("한국어", ["도담 씨는 도토리가 9개 있습니다.", "하늬는 도토리가 4개 있습니다.", "하늬는 도토리를 몇 개 가지고 있습니까?"],
     "도담 씨 말입니다.", 9),
    ("한국어", ["하늬는 골무가 7개 있어.", "라온은 골무가 3개 있어.", "하늬가 라온한테 골무 2개를 줬어.",
              "라온은 골무가 몇 개 있어?", "걔는 지금 몇 개야?"], "하늬 말이야.", 5),
]


@pytest.mark.parametrize("language,lines,repair,value", REPAIRS)
def test_i_mean_x_rebinds_the_last_question_and_answers_it(language, lines, repair, value):
    rows = play(language, lines + [repair])
    assert rows[-1]["status"] == "answered", rows[-1]["answer"]
    assert asserted_numbers(rows[-1]["answer"]) == {value}


def test_referent_repairs_are_ten_in_both_languages():
    assert len(REPAIRS) >= 10 and {row[0] for row in REPAIRS} == {"english", "한국어"}


# G4.5 (b): "gave them to Y, not Z" corrects the recipient in place ------------------------------

RECIPIENTS = [
    ("english", ["Tamsin has 7 quills.", "Fergus has 3 quills.", "Oona has 1 quill.", "Tamsin gave Fergus 2 quills."],
     "Actually they went to Oona, not Fergus.", {"Tamsin quills": "5", "Fergus quills": "3", "Oona quills": "3"}),
    ("english", ["Tamsin has 7 quills.", "Fergus has 3 quills.", "Oona has 1 quill.", "Tamsin lent Fergus 2 quills."],
     "Wait, Tamsin gave them to Oona, not Fergus.", {"Tamsin quills": "5", "Fergus quills": "3", "Oona quills": "3"}),
    ("english", ["I have 4 quills.", "Fergus has 3 quills.", "Tamsin has 6 quills.", "Tamsin passed Fergus 2 quills."],
     "Sorry, they went to me, not Fergus.", {"I quills": "6", "Fergus quills": "3", "Tamsin quills": "4"}),
    ("english", ["I have 4 quills.", "Fergus has 3 quills.", "Tamsin has 6 quills.", "Tamsin handed me 2 quills."],
     "Actually they went to Fergus, not me.", {"I quills": "4", "Fergus quills": "5", "Tamsin quills": "4"}),
    ("english", ["Dr. Leif has 8 thimbles.", "Tamsin has 2 thimbles.", "Oona has 5 thimbles.",
                 "Oona sent Dr. Leif 3 thimbles."], "No, Oona sent them to Tamsin, not Dr. Leif.",
     {"Leif thimbles": "8", "Tamsin thimbles": "5", "Oona thimbles": "2"}),
    ("한국어", ["하늬는 골무가 7개 있어요.", "라온은 골무가 3개 있어요.", "솔비는 골무가 1개 있어요.", "하늬가 라온한테 골무 2개를 줬어요."],
     "아, 라온이 아니라 솔비한테 줬어요.", {"하늬 골무": "5", "라온 골무": "3", "솔비 골무": "3"}),
    ("한국어", ["하늬는 골무가 7개 있어요.", "라온은 골무가 3개 있어요.", "솔비는 골무가 1개 있어요.", "하늬가 라온한테 골무 2개를 빌려줬어요."],
     "잘못 말했어요, 라온이 아니라 솔비한테 빌려줬어요.", {"하늬 골무": "5", "라온 골무": "3", "솔비 골무": "3"}),
    ("한국어", ["저는 골무가 4개 있어요.", "라온은 골무가 3개 있어요.", "하늬는 골무가 6개 있어요.", "하늬가 라온한테 골무 2개를 넘겼어요."],
     "아, 라온이 아니라 저한테 넘겼어요.", {"나 골무": "6", "라온 골무": "3", "하늬 골무": "4"}),
    ("한국어", ["저는 골무가 4개 있어요.", "라온은 골무가 3개 있어요.", "하늬는 골무가 6개 있어요.", "하늬가 저한테 골무 2개를 줬어요."],
     "아, 제가 아니라 라온한테 줬어요.", {"나 골무": "4", "라온 골무": "5", "하늬 골무": "4"}),
    ("한국어", ["도담 씨는 도토리가 8개 있습니다.", "하늬는 도토리가 2개 있습니다.", "라온은 도토리가 5개 있습니다.",
              "라온이 도담 씨한테 도토리 3개를 보냈습니다."], "도담 씨가 아니라 하늬한테 보냈습니다.",
     {"도담 도토리": "8", "하늬 도토리": "5", "라온 도토리": "2"}),
]


@pytest.mark.parametrize("language,lines,correction,state", RECIPIENTS)
def test_a_recipient_correction_moves_the_amount_to_the_new_recipient(language, lines, correction, state):
    rows = play(language, lines + [correction])
    assert rows[-1]["status"] == "observed", rows[-1]["answer"]
    assert rows[-1]["meaning"]["field"] == "recipient"
    got = state_after(language, lines + [correction])
    assert {key: got.get(key) for key in state} == state
    # No new event: the corrected statement took the old one's place.
    assert len([row for row in rows if row["status"] == "observed"]) == len(lines) + 1


def test_recipient_corrections_are_ten_in_both_languages():
    assert len(RECIPIENTS) >= 10 and {row[0] for row in RECIPIENTS} == {"english", "한국어"}


def test_an_unread_recipient_correction_holds_every_holder():
    rows = play("english", ["Tamsin has 7 quills.", "Fergus has 3 quills.", "Tamsin gave Fergus 2 quills.",
                            "Actually they went to Wystan, not Fergus.", "How many quills does Tamsin have?"])
    assert rows[-1]["status"] != "answered"


# G4.6: places hold, receive, give and are asked about -----------------------------------------

PLACES = [
    ("english", ["The north shed has 5 quills.", "Tamsin has 4 quills.", "Tamsin left 2 quills at the north shed."],
     "How many quills are in the north shed now?", 7),
    ("english", ["There are 6 quills in the back hall.", "Tamsin has 1 quill.", "Tamsin took 2 quills from the back hall."],
     "How many quills are in the back hall now?", 4),
    ("english", ["There are 6 quills in the back hall.", "The north shed has 1 quill.",
                 "3 quills were moved from the back hall to the north shed."], "How many quills are in the north shed now?", 4),
    ("english", ["The north shed doesn't have a single quill.", "Tamsin has 4 quills.",
                 "Tamsin put 3 quills in the north shed."], "How many quills does the north shed have?", 3),
    ("한국어", ["북쪽 헛간에는 골무가 5개 있어요.", "하늬는 골무가 4개 있어요.", "하늬가 북쪽 헛간에 골무 2개를 두고 왔어요."],
     "지금 북쪽 헛간에 골무가 몇 개 있어요?", 7),
    ("한국어", ["뒤뜰 창고에는 골무가 6개 있어요.", "하늬는 골무가 1개 있어요.", "하늬가 뒤뜰 창고에서 골무 2개를 가져갔어요."],
     "지금 뒤뜰 창고에 골무가 몇 개 있어요?", 4),
    ("한국어", ["뒤뜰 창고에는 골무가 6개 있어요.", "북쪽 헛간에는 골무가 1개 있어요.",
              "골무 3개가 뒤뜰 창고에서 북쪽 헛간으로 옮겨졌어요."], "지금 북쪽 헛간에 골무가 몇 개 있어요?", 4),
    ("한국어", ["북쪽 헛간에는 골무가 하나도 없어요.", "하늬는 골무가 4개 있어요.", "하늬가 북쪽 헛간에 골무 3개를 맡겼어요."],
     "지금 북쪽 헛간에 골무가 몇 개 있어요?", 3),
]


@pytest.mark.parametrize("language,lines,question,value", PLACES)
def test_a_place_holds_receives_gives_and_is_asked_about(language, lines, question, value):
    rows = play(language, lines + [question])
    assert all(row["status"] == "observed" for row in rows[:-1]), [row["answer"] for row in rows[:-1]]
    assert rows[-1]["status"] == "answered" and asserted_numbers(rows[-1]["answer"]) == {value}


# G4.3: the holder forms, zero and vague counts, fronting and partitives, each class -------------

@pytest.mark.parametrize("language,text,facts", [
    ("english", "I have 12 quills.", [("I quills", "count", "12")]),
    ("english", "My cousin Tamsin keeps 6 quills.", [("Tamsin quills", "count", "6")]),
    ("english", "Fergus's neighbor Oona is holding 4 quills.", [("Oona quills", "count", "4")]),
    ("english", "The porter, Mr. Leif, owns 9 quills.", [("Leif quills", "count", "9")]),
    ("english", "my aunt is responsible for 5 quills.", [("aunt quills", "count", "5")]),
    ("english", "Tamsin has no quills at all.", [("Tamsin quills", "count", "0")]),
    ("english", "Oona only has quills, 8 of them.", [("Oona quills", "count", "8")]),
    ("english", "To Oona, Tamsin passed 2 quills.",
     [("Oona quills", "count_add", "2"), ("Tamsin quills", "count_remove", "2")]),
    ("english", "For the fair, Tamsin lent Oona 3 quills.",
     [("Oona quills", "count_add", "3"), ("Tamsin quills", "count_remove", "3")]),
    ("english", "Tamsin gave 2 of them to Oona.", [("Oona", "count_add", "2"), ("Tamsin", "count_remove", "2")]),
    ("한국어", "저는 골무 열두 개를 가지고 있어요.", [("나 골무", "count", "12")]),
    ("한국어", "제 사촌 하늬는 골무가 여섯 개 있어요.", [("하늬 골무", "count", "6")]),
    ("한국어", "경비원 라온 씨가 골무 네 개를 들고 있습니다.", [("라온 골무", "count", "4")]),
    ("한국어", "솔비는 골무가 하나도 없어요.", [("솔비 골무", "count", "0")]),
    ("한국어", "솔비는 골무만 여덟 개 있어요.", [("솔비 골무", "count", "8")]),
    ("한국어", "잔치 때문에 하늬가 라온한테 골무 두 개를 빌려줬어요.",
     [("라온 골무", "count_add", "2"), ("하늬 골무", "count_remove", "2")]),
    ("한국어", "골무 두 개를 하늬가 라온한테 넘겼대요.", [("라온 골무", "count_add", "2"), ("하늬 골무", "count_remove", "2")]),
])
def test_holder_zero_fronting_and_partitive_classes(language, text, facts):
    assert facts_of(language, text) == sorted(facts)


@pytest.mark.parametrize("language,lines,question", [
    ("english", ["Tamsin has some quills, not sure how many."], "How many quills does Tamsin have?"),
    ("한국어", ["하늬도 골무가 좀 있어요."], "하늬는 골무가 몇 개 있어요?"),
])
def test_a_vague_count_is_recorded_and_its_question_held_naming_the_holder(language, lines, question):
    rows = play(language, lines + [question])
    assert rows[0]["status"] == "observed" and rows[0]["meaning"]["reason"] == "vague_count"
    assert rows[-1]["status"] != "answered" and rows[-1]["meaning"]["reason"] == "vague_count"
    name = "Tamsin" if language == "english" else "하늬"
    assert name in rows[-1]["answer"]


@pytest.mark.parametrize("language,lines,question,value", [
    ("english", ["Tamsin has some quills. 9 of them, actually."], "How many quills does Tamsin have?", 9),
    ("english", ["Fergus has 2 quills.", "Tamsin has some quills too.", "Tamsin has 6 of them, to be exact."],
     "How many quills does Tamsin have?", 6),
    ("한국어", ["하늬도 골무가 좀 있어요. 세어 보니 아홉 개네요."], "하늬는 골무가 몇 개 있어요?", 9),
])
def test_a_count_said_later_without_its_holder_is_the_vague_one(language, lines, question, value):
    rows = play(language, lines + [question])
    assert rows[-1]["status"] == "answered" and asserted_numbers(rows[-1]["answer"]) == {value}


def test_a_pointer_never_means_the_user():
    rows = play("english", ["I have 4 quills.", "Tamsin has 7 quills.", "Oona has 3 quills.",
                            "How many quills do I have?", "And how many has she got?"])
    assert rows[-1]["status"] != "answered"


def test_a_statement_read_only_as_a_question_holds_what_it_names():
    rows = play("한국어", ["하늬는 골무가 7개 있어요.", "라온은 골무가 3개 있어요.", "하늬가 라온한테 골무 한 개를 주다고 해요.",
                          "라온은 골무가 몇 개 있어요?"])
    assert rows[-1]["status"] != "answered"


# G4.1: development set v4 ------------------------------------------------------------------------

def _dev4_build():
    spec = importlib.util.spec_from_file_location("dev4_build", DEV4 / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dev4_is_valid_with_eighty_dialogues_a_language_and_halves_by_scenario():
    import bench.dialogue_gate as gate
    dialogues = gate.load(DEV4)
    assert gate.validate(dialogues) == []
    counts = {code: sum(d["language"] == code for d in dialogues) for code in ("ko", "en")}
    assert len(dialogues) >= 160 and min(counts.values()) >= 80
    split = gate.split_ids(DEV4)
    assert not set(split["build"]) & set(split["check"])
    assert len(split["build"]) + len(split["check"]) == len(dialogues)
    for d in dialogues:
        assert d["id"] in split[d["variation"]["half"]]
        assert d["variation"]["scenario"].split("_")[2][0] == d["variation"]["half"][0]
    build = _dev4_build()
    assert build.SAMPLING["build"] != build.SAMPLING["check"]
    assert build.SCENARIO_SEEDS["build"] != build.SCENARIO_SEEDS["check"]


def test_dev4_halves_share_no_name_item_or_place():
    import bench.dialogue_gate as gate
    build = _dev4_build()
    scenarios = {s["id"]: s for s in build.load_scenarios()}

    def vocabulary(rows):
        words = set()
        for d in rows:
            scn = scenarios[d["variation"]["scenario"]]
            words |= {t for h in scn["holders"] for t in h["tokens"]} | {i["key"] for i in scn["items"]}
        return words
    halves = {name: gate.load(DEV4, name) for name in ("build", "check")}
    assert not vocabulary(halves["build"]) & vocabulary(halves["check"])
    tables = build.halves()
    for language in ("en", "ko"):
        for key in ("given_f", "given_m", "surnames", "items", "places", "relations", "roles"):
            left = {json.dumps(x, ensure_ascii=False) for x in tables["build"][language][key]}
            right = {json.dumps(x, ensure_ascii=False) for x in tables["check"][language][key]}
            assert not left & right, (language, key)


def test_dev4_every_class_is_in_ten_dialogues_a_language():
    import bench.dialogue_gate as gate
    build = _dev4_build()
    table, _sub = build.coverage(gate.load(DEV4))
    for family in build.FAMILIES:
        for language in ("ko", "en"):
            if family == "korean_register" and language == "en":
                continue
            assert table[family].get(language, 0) >= 10, (family, language, table[family])


def test_dev4_texts_pass_the_checker_they_were_kept_by():
    import bench.dialogue_gate as gate
    build = _dev4_build()
    scenarios = {s["id"]: s for s in build.load_scenarios()}
    checker = build.Checker()
    failed = 0
    for d in gate.load(DEV4):
        scn, said = scenarios[d["variation"]["scenario"]], []
        for t in d["turns"]:
            ok, _reason = checker.check(scn, scn["turns"][t["scenario_turn"] - 1], t["say"], said)
            failed += not ok
            said.append(t["say"])
    assert failed == 0


def _tracked_corpus(owned):
    """The tracked files of the gate's corpus folders without the frozen exam sets (never listed, opened or
    read by a development run: the owner runs that overlap check) and without ``owned`` (G5)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("dialogues_dev4_build",
                                                  ROOT / "data/benchmarks/dialogues_dev4/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    return build.corpus_files(owned)


def test_dev4_shares_no_full_sentence_with_any_other_corpus_file():
    import bench.dialogue_gate as gate
    result = gate.overlaps(gate.load(DEV4), files=_tracked_corpus(("data/benchmarks/dialogues_dev4/",)))
    assert result["files"] > 100 and len(result["overlaps"]) == 0


def test_no_development_sentence_is_in_a_file_this_round_changed():
    import bench.dialogue_gate as gate
    sentences = []
    for folder in ("dialogues_dev", "dialogues_dev2", "dialogues_dev3", "dialogues_dev4"):
        sentences += gate.dialogue_sentences(gate.load(ROOT / "data/benchmarks" / folder))
    owned = ["relational_semantics.py", "reasoning_context.py", "language_components.py",
             "tests/test_understanding_r4.py", "styles/english.json", "styles/한국어.json"]
    found = 0
    for name in owned:
        text = gate._normalize_corpus((ROOT / name).read_text(encoding="utf-8"))
        found += sum(1 for _d, _n, _raw, norm in sentences if norm in text and gate._full_sentence_at(text, norm))
    assert found == 0
