"""Development set v6 tooling (goal G6.0, G6.0c): the checker, the assembly of outside phrasings, the halves."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("dialogues_dev6_build", ROOT / "data/benchmarks/dialogues_dev6/build.py")
b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b)

# a scenario of its own (names, thing and place of no table), the one the phrasings below say
EN = {
    "id": "s6_en_b_900", "language": "en", "half": "build", "register": "casual", "focus": [],
    "holders": [
        {"id": "A", "kind": "name", "entity": "Morwenna", "tokens": ["Morwenna"], "first": "Morwenna",
         "later": "Morwenna"},
        {"id": "B", "kind": "name", "entity": "Barnaby", "tokens": ["Barnaby"], "first": "Barnaby",
         "later": "Barnaby"},
        {"id": "C", "kind": "place", "entity": "bandstand", "tokens": ["bandstand"], "first": "the bandstand",
         "later": "the bandstand"}],
    "things": [{"id": "x", "key": "kazoos", "plural": "kazoos", "one": "kazoo"}],
    "turns": [
        {"n": 1, "act": "has", "holder": "A", "thing": "x", "count": 7, "count_as": "word", "forms": [],
         "refer": {"A": "Morwenna"}, "first": ["A"], "classes": ["1_count_words"]},
        {"n": 2, "act": "has", "holder": "B", "thing": "x", "count": 12, "count_as": "digits", "forms": [],
         "refer": {"B": "Barnaby"}, "first": ["B"], "classes": []},
        {"n": 3, "act": "give", "giver": "A", "receiver": "B", "thing": "x", "count": 2, "count_as": "word",
         "verb": "give", "forms": ["double_object"], "refer": {"A": "Morwenna", "B": "Barnaby"}, "first": [],
         "classes": ["1_count_words", "2_en_transfer_forms"]},
        {"n": 4, "act": "give", "giver": "B", "receiver": "C", "thing": "x", "count": 3, "count_as": "digits",
         "verb": "leave_at", "forms": ["place_receiver"], "refer": {"B": "Barnaby", "C": "the bandstand"},
         "first": ["C"], "classes": ["15_unstated_receiver", "6_holder_forms"]},
        {"n": 5, "act": "ask", "holder": "A", "thing": "x", "forms": ["q_left"], "refer": {"A": "Morwenna"},
         "first": [], "classes": ["7_leftover_questions"]},
        {"n": 6, "act": "switch", "holder": "B", "thing": "x", "after": 5, "forms": ["switch_holder"],
         "refer": {"B": "Barnaby"}, "first": [], "classes": ["10_topic_switch"]},
        {"n": 7, "act": "why", "holder": "B", "thing": "x", "after": 6, "count": 11, "count_as": "word",
         "forms": ["why_end_up"], "refer": {"B": "Barnaby"}, "first": [], "classes": ["13_why_with_fact"]},
        {"n": 8, "act": "ask", "holder": "C", "thing": "x", "hold": True, "forms": ["q_plain"],
         "refer": {"C": "the bandstand"}, "first": [], "classes": ["15_unstated_receiver"]}]}
EN["classes"] = sorted({c for t in EN["turns"] for c in t["classes"]})
GOOD = {1: "Morwenna has seven kazoos.", 2: "Barnaby has 12 kazoos.", 3: "Morwenna gave Barnaby two kazoos.",
        4: "Barnaby left 3 kazoos at the bandstand.", 5: "How many kazoos does Morwenna have left?",
        6: "What about Barnaby?", 7: "Why does Barnaby end up with eleven?",
        8: "How many kazoos are at the bandstand?"}
KO = {
    "id": "s6_ko_b_900", "language": "ko", "half": "build", "register": "haeyo", "focus": [],
    "holders": [{"id": "A", "kind": "name", "entity": "모란", "tokens": ["모란"], "first": "모란", "later": "모란"},
                {"id": "B", "kind": "name", "entity": "보리", "tokens": ["보리"], "first": "보리", "later": "보리"}],
    "things": [{"id": "x", "key": "나팔", "noun": "나팔", "counter": "개"}],
    "turns": [
        {"n": 1, "act": "has", "holder": "A", "thing": "x", "count": 6, "count_as": "word", "forms": [],
         "refer": {"A": "모란"}, "first": ["A"], "classes": ["1_count_words"]},
        {"n": 2, "act": "give", "giver": "A", "receiver": "B", "thing": "x", "count": 2, "count_as": "word",
         "verb": "share_out", "forms": ["partitive"], "refer": {"A": "모란", "B": "보리"}, "first": ["B"],
         "classes": ["1_count_words", "3_partitive", "5_ko_transfer_verbs"]}]}


def test_the_checker_keeps_a_correct_phrasing():
    checker = b.Checker6()
    assert b.valid(EN)
    for turn in EN["turns"]:
        assert checker.check(EN, turn, GOOD[turn["n"]]) == (True, "ok"), turn["n"]
    assert checker.check(KO, KO["turns"][0], "모란한테 나팔이 여섯 개 있어요.") == (True, "ok")
    assert checker.check(KO, KO["turns"][1], "모란이 그중 두 개를 보리에게 나눠 줬어요.") == (True, "ok")


def test_the_checker_refuses_a_wrong_count_and_the_wrong_numeral_form():
    checker = b.Checker6()
    assert checker.check(EN, EN["turns"][0], "Morwenna has eight kazoos.")[1].startswith("extra_number")
    assert checker.check(EN, EN["turns"][0], "Morwenna has 7 kazoos.")[1] == "count_not_in_words"
    assert not checker.check(EN, EN["turns"][6], "Why does Barnaby end up with twelve?")[0]
    assert not checker.check(KO, KO["turns"][0], "모란한테 나팔이 다섯 개 있어요.")[0]
    assert checker.check(KO, KO["turns"][0], "모란한테 나팔이 육 개 있어요.")[1] == "sino_korean_numeral"


def test_the_checker_refuses_a_holder_the_scenario_does_not_name():
    checker = b.Checker6()
    assert checker.check(EN, EN["turns"][2], "Morwenna gave Barnaby and Rosalind two kazoos.")[1].startswith(
        "unnamed")
    assert checker.check(EN, EN["turns"][0], "Morwenna and her sister have seven kazoos.")[1].startswith("unnamed")
    assert checker.check(KO, KO["turns"][1], "모란이 그중 두 개를 보리랑 아저씨에게 나눠 줬어요.")[1].startswith("unnamed")
    # a holder of the scenario the turn does not name is refused too
    assert checker.check(EN, EN["turns"][4], "How many kazoos do Morwenna and Barnaby have left?")[1].startswith(
        "other_holder")


def test_the_checker_reads_the_direction_and_the_form():
    checker = b.Checker6()
    assert not checker.check(EN, EN["turns"][2], "Barnaby gave Morwenna two kazoos.")[0]
    assert checker.check(EN, EN["turns"][2], "Morwenna gave two kazoos to Barnaby.")[1] == "form:double_object"
    assert checker.check(EN, EN["turns"][5], "And how many kazoos does Barnaby have?")[1] == "switch_not_elliptic"


def _records(path, records):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path


def test_assemble_keeps_what_passes_and_counts_what_is_dropped(tmp_path):
    folder = tmp_path / "set"
    folder.mkdir()
    b.scenarios_path("build", "en", folder).write_text(json.dumps(EN) + "\n", encoding="utf-8")
    good = {"scenario": EN["id"], "language": "en", "source": "writer", "date": "2026-09-28",
            "turns": [{"n": n, "text": t} for n, t in GOOD.items()]}
    records = _records(tmp_path / "phrasings.jsonl", [
        good,
        dict(good, scenario="s6_en_b_999"),            # a scenario id that does not exist
        dict(good, language="ko"),
        "not a record"])
    dialogues, split, stats = b.assemble([records], folder=folder, write=False, overlap=lambda ds, words: set())
    assert len(dialogues) == 1 and split["build"] == ["dev6_en_b_01"]
    assert stats["records_dropped"] == {"unknown_scenario": 1, "wrong_language": 1, "not_a_record": 1}
    d = dialogues[0]
    assert [t["expect"]["quantity"] for t in d["turns"][4:7]] == [5, 11, 11]
    assert d["turns"][7]["expect"]["act"] == "hold" and d["turns"][7]["label"] == "hold"
    assert d["variation"]["phraser"]["source"] == "writer"
    # a failed question drops that turn and the turns that continue it; here one answerable question is left,
    # so the dialogue goes too
    bad = dict(good, turns=[{"n": n, "text": t if n != 6 else "What about Barnaby and Rosalind?"}
                            for n, t in GOOD.items()])
    dialogues, _split, stats = b.assemble([_records(tmp_path / "bad.jsonl", [bad])], folder=folder, write=False,
                                          overlap=lambda ds, words: set())
    assert stats["turns_dropped"] == {"unnamed_capitalized": 1}
    assert dialogues == [] and stats["dialogues_dropped"] == {"too_few_turns_left": 1}
    assert [t["n"] for t in b.keep_turns(EN, GOOD, {6})] == [1, 2, 3, 4, 5, 8]
    assert [t["n"] for t in b.keep_turns(EN, GOOD, {3})] == [1, 2]      # a failed statement ends it
    # a turn that shares a sentence with an earlier set is dropped at assembly
    dialogues, _split, stats = b.assemble([records], folder=folder, write=False,
                                          overlap=lambda ds, words: {(ds[0]["id"], 8)})
    assert stats["turns_dropped"] == {"overlap": 1} and len(dialogues[0]["turns"]) == 7


def test_an_earlier_set_sentence_is_found():
    dev5 = b.gate.load(ROOT / "data/benchmarks/dialogues_dev5")
    sentence = dev5[0]["turns"][0]["say"]
    fresh = " ".join(["Morwenna", "kept", "nine", "kazoos."])        # in no file, this one included
    probe = {"id": "probe", "turns": [{"n": 1, "say": fresh}, {"n": 2, "say": sentence}]}
    assert b.overlapping_turns([probe]) == {("probe", 2)}


def test_the_halves_share_no_name_thing_or_place():
    vocab = b.halves()
    for lang in b.LANGS:
        for key in ("given_f", "given_m", "surnames", "items", "bundles", "places"):
            build = {json.dumps(x, ensure_ascii=False) for x in vocab["build"][lang][key]}
            check = {json.dumps(x, ensure_ascii=False) for x in vocab["check"][lang][key]}
            assert build and check and not build & check, (lang, key)
    scenarios = b.load_scenarios()
    words = {"build": set(), "check": set()}
    for scn in scenarios.values():
        words[scn["half"]] |= {t for h in scn["holders"] if h["kind"] != "first_person" for t in h["tokens"]}
        words[scn["half"]] |= {t["key"] for t in scn["things"]}
    assert words["build"] and not words["build"] & words["check"]


def test_every_class_is_in_twelve_dialogues_per_language_and_counts_are_words_half_the_time():
    scenarios = list(b.load_scenarios().values())
    table, _turns, statements = b.coverage(scenarios)
    for lang in b.LANGS:
        assert sum(s["language"] == lang for s in scenarios) >= 100
        for c in b.CLASSES:
            if c in b.NOT_IN[lang]:
                continue
            assert sum(v for k, v in table[c].items() if k.startswith(lang)) >= 12, (lang, c)
        n, words = statements[lang]
        assert words * 2 >= n
        cross = [s for s in scenarios if s["language"] == lang and "12_cross_language" in s["classes"]]
        assert len(cross) * 10 >= sum(s["language"] == lang for s in scenarios)


def test_the_scenario_files_are_the_generator_output():
    vocab = b.halves()
    for half in b.HALVES:
        generated = b.generate(half, "en", vocab)
        written = [json.loads(line) for line in b.scenarios_path(half, "en").read_text(encoding="utf-8").splitlines()]
        assert generated == written


def test_the_instruction_file_has_no_sentence_of_an_earlier_set():
    assert b.PHRASING.read_text(encoding="utf-8") == b.phrasing_md()
    dialogues = []
    for name in b.OTHER_SETS:
        folder = ROOT / "data/benchmarks" / name
        if folder.exists():
            dialogues += b.gate.load(folder)
    found = b.gate.overlaps(dialogues, files=[str(b.PHRASING)])
    assert found["overlaps"] == []


@pytest.mark.parametrize("sid", ["s6_en_b_001", "s6_ko_c_001"])
def test_a_generated_scenario_plays_out(sid):
    assert b.valid(b.load_scenarios()[sid])
