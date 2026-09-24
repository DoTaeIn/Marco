"""Understanding round 3.

Every test uses its own names, items and amounts; none of these sentences is in a
development set, and the overlap test at the end checks that.
"""
import json
from pathlib import Path
import re

import pytest

from pack_model import development_model
from reasoning_context import ReasoningContext

ROOT = Path(__file__).resolve().parents[1]
_MODELS = {}


def model(language):
    if language not in _MODELS:
        _MODELS[language] = development_model(language)
    return _MODELS[language]


def context(language):
    other = "english" if language == "한국어" else "한국어"
    return ReasoningContext(model=model(language), companions=[model(other)])


def restarted(old, language):
    """A new context over the saved state, as a restarted app builds it."""
    fresh = context(language)
    fresh.restore(json.loads(json.dumps(old.snapshot(), ensure_ascii=False)))
    return fresh


def play(language, lines):
    """Turns in one conversation; a line ``("restart", text)`` restarts before it."""
    current, rows = context(language), []
    for line in lines:
        if isinstance(line, tuple):
            current = restarted(current, language)
            line = line[1]
        rows.append(current.turn(line) or {"status": None, "answer": None})
    return rows


def asserted_numbers(text):
    """Numbers the reply states, not the ones it quotes (as the gate scorer reads it)."""
    import bench.dialogue_gate as gate
    return gate.quantities(gate.asserted(text or ""))


# G3.0 (a): a pointer the discourse does not fix is asked back, never answered ----------
#
# Each case has a value for every candidate, so an answer was available; the pointer
# could mean two people, so the act is to ask. None is answered, none states a value.

CLARIFY = [
    ("english", ["Tove has 7 plums.", "Una has 3 plums."], "How many plums does she have now?"),
    ("english", ["Tove has 7 plums.", "Una has 3 plums.", "How many plums does Tove have?",
                 "How many plums do Tove and Una have together?"], "How many has she got?"),
    ("english", ["Tove has 7 plums.", "Una has 3 plums.", "How many plums does Una have?",
                 "Who has more plums, Tove or Una?"], "How many plums does that person have?"),
    ("english", ["Tove has 7 plums.", "Una has 3 plums.", "How many plums does Tove have?",
                 "How many plums does Wyn have?"], "How many plums does she have?"),
    ("english", ["Tove has 7 plums.", "How many plums does Tove have?", "Una has 3 plums."],
     "How many plums does she have now?"),
    ("한국어", ["새롬이는 자두가 7개 있어.", "누리는 자두가 3개 있어."], "걔는 지금 자두 몇 개 있어?"),
    ("한국어", ["새롬이는 자두가 7개 있어.", "누리는 자두가 3개 있어.", "새롬이는 자두가 몇 개 있어?",
              "새롬이와 누리는 자두가 모두 몇 개야?"], "걔는 몇 개야?"),
    ("한국어", ["새롬이는 자두가 7개 있어.", "누리는 자두가 3개 있어.", "누리는 자두가 몇 개 있어?",
              "새롬이와 누리 중 누가 자두가 더 많아?"], "그 사람은 자두가 몇 개 있어?"),
    ("한국어", ["새롬이는 자두가 7개 있어.", "누리는 자두가 3개 있어.", "새롬이는 자두가 몇 개 있어?",
              "하랑이는 자두가 몇 개 있어?"], "그 애는 자두가 몇 개야?"),
    ("한국어", ["새롬이는 자두가 7개 있어.", "새롬이는 자두가 몇 개 있어?", "누리는 자두가 3개 있어."],
     "걔는 지금 자두 몇 개 있어?"),
]


@pytest.mark.parametrize("language,lines,question", CLARIFY)
def test_a_pointer_two_people_could_mean_is_asked_never_answered(language, lines, question):
    rows = play(language, lines + [question])
    last = rows[-1]
    assert last["status"] != "answered"
    assert last["meaning"]["act"] in ("ask", "hold")
    # Nothing is answered: no holder's count is stated in the reply.
    assert not asserted_numbers(last["answer"]) & {7, 3, 10}


def test_injected_clarify_cases_are_ten_in_both_languages():
    assert len(CLARIFY) >= 10
    assert {language for language, _l, _q in CLARIFY} == {"english", "한국어"}


@pytest.mark.parametrize("language,lines,question,value", [
    ("english", ["Tove has 7 plums.", "Una has 3 plums.", "Tove gave Una 2 plums.",
                 "How many plums does Una have?"], "How many has she got?", 5),
    ("english", ["Tove has 7 plums."], "How many plums does she have?", 7),
    ("한국어", ["새롬이는 자두가 7개 있어.", "누리는 자두가 3개 있어.", "새롬이가 누리에게 자두 2개를 줬어.",
              "누리는 자두가 몇 개 있어?"], "걔는 지금 몇 개야?", 5),
    ("한국어", ["새롬이는 자두가 7개 있어."], "걔는 자두가 몇 개 있어?", 7),
])
def test_a_pointer_the_discourse_fixes_to_one_person_is_read(language, lines, question, value):
    rows = play(language, lines + [question])
    assert rows[-1]["status"] == "answered" and asserted_numbers(rows[-1]["answer"]) == {value}


def test_the_people_a_pointer_may_mean_survive_a_restart():
    rows = play("english", ["Tove has 7 plums.", "Una has 3 plums.",
                            ("restart", "How many plums does she have now?")])
    assert rows[-1]["status"] != "answered"


# G3.0 (b): after a correction the retracted value is unreachable -----------------------
#
# Every dialogue states two counts, one transfer and a correction; ``old`` are the
# counts the uncorrected statements gave that the correction changed. Every later
# question -- counts, the sum, the comparison, why, after a restart, and in the other
# language -- is asked; no later reply states an old value, and an answered count is
# the corrected one.

EN_AFTER = ["How many pears does Yuri have?", "How many pears does Mina have?",
            "How many pears do Mina and Yuri have together?", "Who has more pears, Mina or Yuri?",
            "Why does Yuri have that many pears?", ("restart", "How many pears does Yuri have now?"),
            "How many does Mina have now?", "유리는 지금 몇 개 있어?"]
KO_AFTER = ["솔이는 호두가 몇 개 있어?", "다래는 호두가 몇 개 있어?", "다래와 솔이는 호두가 모두 몇 개야?",
            "다래와 솔이 중 누가 호두가 더 많아?", "솔이는 왜 호두가 그만큼 있어?",
            ("restart", "솔이는 지금 호두 몇 개야?"), "다래는 몇 개야?", "How many does Darae have now?"]
EN_START = ["Mina has 9 pears.", "Yuri has 2 pears.", "Mina gave Yuri 4 pears."]
KO_START = ["다래는 호두가 9개 있어.", "솔이는 호두가 2개 있어.", "다래가 솔이에게 호두 4개를 줬어."]
CORRECTED = [
    # (language, turns up to and with the correction, {holder: count now}, old counts)
    ("english", EN_START + ["No, it was 1, not 4."], {"Yuri": 3, "Mina": 8}, {5, 6}),
    ("english", EN_START + ["How many pears does Yuri have?", "Actually, Mina gave Yuri 1 pear, not 4."],
     {"Yuri": 3, "Mina": 8}, {5, 6}),
    ("english", EN_START + ["The one Mina gave was 1, not 4."], {"Yuri": 3, "Mina": 8}, {5, 6}),
    ("english", EN_START + ["No, it was 11, not 9."], {"Yuri": 6, "Mina": 7}, {5}),
    ("english", ["Mina has 9 pears.", "Yuri has 4 pears.", "Mina gave Yuri 4 pears.", "No, it was 1, not 4."],
     None, {5, 8}),
    ("한국어", KO_START + ["아니, 4개가 아니라 1개였어."], {"솔이": 3, "다래": 8}, {5, 6}),
    ("한국어", KO_START + ["솔이는 호두가 몇 개 있어?", "아, 호두 4개가 아니라 1개였어."], {"솔이": 3, "다래": 8}, {5, 6}),
    ("한국어", KO_START + ["아까 준 건 4개가 아니라 1개야."], {"솔이": 3, "다래": 8}, {5, 6}),
    ("한국어", KO_START + ["아니, 9개가 아니라 11개였어."], {"솔이": 6, "다래": 7}, {5}),
    ("한국어", ["다래는 호두가 9개 있어.", "솔이는 호두가 4개 있어.", "다래가 솔이에게 호두 4개를 줬어.",
              "아니, 4개가 아니라 1개였어."], None, {5, 8}),
]


@pytest.mark.parametrize("language,lines,now,old", CORRECTED)
def test_no_later_reply_states_a_retracted_value(language, lines, now, old):
    after = EN_AFTER if language == "english" else KO_AFTER
    rows = play(language, lines + after)
    correction = rows[len(lines) - 1]
    assert correction["meaning"]["act"] == ("correct" if now else "hold")
    for line, row in zip(after, rows[len(lines):]):
        stated = asserted_numbers(row["answer"])
        assert not stated & old, (line, row["answer"])
        if now is None:
            # Unapplied: the user called a value wrong, so nothing it touched is answered.
            assert row["status"] != "answered", line
    if now is not None:
        taker, giver = list(now)
        counts = [rows[len(lines) + i] for i in (0, 1, 2)]
        assert all(row["status"] == "answered" for row in counts)
        assert [asserted_numbers(row["answer"]) for row in counts] == [
            {now[taker]}, {now[giver]}, {now[taker] + now[giver]}]


def test_injected_corrections_are_ten_in_both_languages():
    assert len(CORRECTED) >= 10 and {row[0] for row in CORRECTED} == {"english", "한국어"}
    assert sum(row[2] is None for row in CORRECTED) >= 2


# G3.1: open vocabulary by rule ----------------------------------------------------------

PROBE = ROOT / "data/benchmarks/vocab_probe"


def _probe_build():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vocab_probe_build", PROBE / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    return build


def test_the_probe_has_its_sizes_and_is_what_its_generator_writes():
    words = json.loads((PROBE / "words.json").read_text(encoding="utf-8"))
    assert len(words["items"]) >= 300 and len(words["places"]) >= 100 and len(words["names"]) >= 200
    assert {row["script"] for row in words["names"]} == {"latin", "hangul"}
    assert all(words["sources"][key] for key in ("items_places", "names_en", "names_ko"))
    cases = json.loads((PROBE / "probe.json").read_text(encoding="utf-8"))["cases"]
    assert cases == _probe_build().pairs(words)
    for kind, key in (("item", "items"), ("place", "places"), ("name", "names")):
        for language in ("en", "ko"):
            assert sum(c["kind"] == kind and c["language"] == language for c in cases) == len(words[key])


def _word_in(text, word):
    return re.search(r"(?<![가-힣A-Za-z])%s(?![A-Za-z])" % re.escape(word), text) is not None


def test_no_probe_word_is_declared_in_a_pack_but_the_irregular_plurals():
    """The rules read the probe words; the packs do not list them. The one list
    the goal allows is English's irregular plurals, and it is a closed class."""
    words = json.loads((PROBE / "words.json").read_text(encoding="utf-8"))
    english = json.loads((ROOT / "styles/english.json").read_text(encoding="utf-8"))
    irregular = set(english["명사수"]["irregular"])
    english["명사수"].pop("irregular")
    english.pop("_명사수")
    packs = json.dumps(english, ensure_ascii=False) + (ROOT / "styles/한국어.json").read_text(encoding="utf-8")
    probe = ([row["en"] for row in words["items"] + words["places"]] + [row["ko"] for row in words["items"]
             + words["places"]] + [row["name"] for row in words["names"]])
    assert [word for word in probe if _word_in(packs, word)] == []
    # The irregular table is the grammar's closed list, not the probe's words.
    assert len(set(probe) & irregular) <= 10     # 7 of the 400 English probe nouns


PROBE_SAMPLE = 60


def test_a_sample_of_the_probe_is_recorded_and_answered():
    """Every 20th probe case, played through the reasoning context (the full probe
    runs through the UI handler with ``data/benchmarks/vocab_probe/run.py``)."""
    cases = json.loads((PROBE / "probe.json").read_text(encoding="utf-8"))["cases"][::20]
    assert len(cases) == PROBE_SAMPLE
    failed = []
    for case in cases:
        language = "english" if case["language"] == "en" else "한국어"
        statement, question = play(language, [case["statement"], case["question"]])
        expected = case["expect"]
        # The fact the engine answered with; how the reply words it is the realizer's.
        answered = {str(row["fact"][2]) for row in question.get("transitions") or []
                    if isinstance(row.get("fact"), list) and len(row["fact"]) == 3}
        want = str(expected["count"]) if "count" in expected else expected["place"]
        ok = statement["status"] == "observed" and question["status"] == "answered" and answered == {want}
        if not ok:
            failed.append((case["statement"], case["question"], question.get("answer")))
    assert failed == []


@pytest.mark.parametrize("one,many", [("wolf", "wolves"), ("goose", "geese"), ("trout", "trout"),
                                      ("tomato", "tomatoes"), ("child", "children"), ("box", "boxes")])
def test_an_irregular_plural_names_the_same_things_as_its_singular(one, many):
    rows = play("english", ["Ilse has one %s." % one, "How many %s does Ilse have?" % many])
    # The fact answered (the realizer's wording of "1 geese" is request G3-2's).
    facts = [row["fact"] for row in rows[-1]["transitions"] if row.get("fact")]
    assert rows[-1]["status"] == "answered" and facts == [["Ilse %s" % many, "count", "1"]]


def test_the_irregular_table_is_whole_word_only():
    from relational_semantics import declared_plural
    declared = model("english").parser().noun_number
    assert declared_plural("man", declared) == "men" and declared_plural("human", declared) == "humans"
    assert declared_plural("Wolf", declared) == "Wolves"


@pytest.mark.parametrize("statement,question,place", [
    ("수첩은 매점에 있어.", "수첩은 어디에 있어?", "매점"),
    ("수첩이 매점에 있어요.", "지금 수첩은 어디에 있어?", "매점"),
    ("보람은 매점에 있다.", "보람은 어디에 있어?", "매점"),
])
def test_a_korean_location_is_stated_in_the_present_as_in_the_past(statement, question, place):
    rows = play("한국어", [statement, question])
    assert rows[0]["status"] == "observed" and rows[-1]["status"] == "answered" and place in rows[-1]["answer"]


@pytest.mark.parametrize("statement,question", [
    ("보람의 고양이는 세 마리야.", "보람의 고양이는 몇 마리야?"),
    ("보람한테는 고양이가 세 마리 있어.", "보람한테는 고양이가 몇 마리 있어?"),
])
def test_a_delimiter_never_stacks_on_a_nominative_so_a_final_i_stays_in_the_noun(statement, question):
    rows = play("한국어", [statement, question])
    assert rows[-1]["status"] == "answered" and asserted_numbers(rows[-1]["answer"]) == {3}


@pytest.mark.parametrize("statement", ["보람은 고양이 세 마리를 가지고 있어.", "보람은 오이 3개를 가지고 있어.",
                                       "보람은 수첩 세 권을 가지고 있어요."])
def test_an_accusative_on_the_counter_is_read_on_the_counted_noun(statement):
    noun = statement.split()[1]
    rows = play("한국어", [statement, "보람은 %s 몇 개 가지고 있어?" % (noun + ("를" if noun[-1] in "이오" else "을"))])
    assert rows[0]["status"] == "observed" and "repair" not in rows[0]
    assert rows[-1]["status"] == "answered" and asserted_numbers(rows[-1]["answer"]) == {3}


def test_an_amount_is_never_read_inside_a_name():
    parser = model("한국어").parser()
    assert parser._names_an_amount({"triple": ["수첩", "location", "공책 세 권"]})
    assert not parser._names_an_amount({"triple": ["수첩", "location", "공 가게"]})


# G3.2: multi-clause statements -----------------------------------------------------------

def _clauses_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vocab_probe_clauses", PROBE / "clauses.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_clause_probe_is_what_its_generator_writes_and_varies_what_it_says():
    cases = json.loads((PROBE / "clauses.json").read_text(encoding="utf-8"))["cases"]
    assert cases == _clauses_module().generate()
    assert len(cases) == 200 and sum(c["language"] == "ko" for c in cases) == 100
    assert {c["holders"] for c in cases} == {1, 2, 3}
    assert {c["order"] for c in cases} == {0, 1}
    assert all(len(c["facts"]) >= 2 for c in cases)


def state_after(language, lines):
    current = context(language)
    for line in lines:
        current.turn(line)
    return {row[0]: row[2] for row in current.current_state() if row[1] == "count"}


def test_a_sample_of_the_clause_probe_records_every_fact():
    cases = json.loads((PROBE / "clauses.json").read_text(encoding="utf-8"))["cases"][::5]
    failed = []
    for case in cases:
        language = "english" if case["language"] == "en" else "한국어"
        want = {"%s %s" % (f["holder"], f["item"]): str(f["count"]) for f in case["facts"]}
        got = state_after(language, [case["statement"]])
        if got != want:
            failed.append((case["statement"], got))
    assert failed == []


@pytest.mark.parametrize("language,statement,state", [
    ("english", "Ilse has 4 kites. Omar has 2.", {"Ilse kites": "4", "Omar kites": "2"}),
    ("english", "Ilse had 4 kites, Omar 2.", {"Ilse kites": "4", "Omar kites": "2"}),
    ("english", "Ilse has 4 kites and 2 drums.", {"Ilse kites": "4", "Ilse drums": "2"}),
    ("english", "Ilse has 4 kites and Omar 2 drums.", {"Ilse kites": "4", "Omar drums": "2"}),
    ("english", "Omar has 2 kites, and Ilse, who has 5, gave Omar 3.", {"Ilse kites": "2", "Omar kites": "5"}),
    ("한국어", "보람은 연이 네 개 있고 다온은 두 개 있어.", {"보람 연": "4", "다온 연": "2"}),
    ("한국어", "보람은 연이 네 개 있으며 다온은 두 개 있다.", {"보람 연": "4", "다온 연": "2"}),
    ("한국어", "보람은 연이 네 개 있어. 그리고 다온은 두 개 있어.", {"보람 연": "4", "다온 연": "2"}),
    ("한국어", "보람은 연이 네 개, 북이 두 개 있어.", {"보람 연": "4", "보람 북": "2"}),
    ("한국어", "다온은 연이 두 개 있고, 연을 다섯 개 가진 보람이 다온에게 세 개를 줬어.", {"보람 연": "2", "다온 연": "5"}),
    ("한국어", "다온은 연이 두 개 있고, 연이 다섯 개 있는 보람이 다온에게 세 개를 줬어.", {"보람 연": "2", "다온 연": "5"}),
])
def test_every_fact_of_a_multi_clause_statement_is_recorded(language, statement, state):
    assert state_after(language, [statement]) == state


@pytest.mark.parametrize("language,statement", [
    ("english", "Ilse has 4 kites and Omar has a drum."),
    ("english", "Ilse, who likes kites, has 4 kites."),
    ("한국어", "보람이 있는 곳으로 상자를 옮긴다."),
])
def test_a_clause_that_is_not_an_amount_is_not_split_or_gapped(language, statement):
    parser = model(language).parser()
    assert parser._relative_clauses(statement) == statement


def test_a_remnant_names_no_more_than_the_clause_before_and_no_verb_of_it():
    parser = model("english").parser()
    rows = [["Ilse kites", "count", "4"]]
    assert parser._gapped("Omar 2", "Ilse has 4 kites", rows) == "Omar has 2 kites"
    assert parser._gapped("2 drums", "Ilse has 4 kites", rows) == "Ilse has 2 drums"
    assert parser._gapped("Omar has 2", "Ilse has 4 kites", rows) is None
    assert parser._gapped("Omar and Pia 2", "Ilse has 4 kites", rows) is None


# G3.3: development set v3 -------------------------------------------------------------------

DEV3 = ROOT / "data/benchmarks/dialogues_dev3"


def _dev3_build():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dev3_build", DEV3 / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(dialogues):
    import hashlib
    rows = sorted(json.dumps(d, ensure_ascii=False, sort_keys=True) for d in dialogues)
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def test_dev3_is_valid_generated_and_split_by_its_seed():
    import bench.dialogue_gate as gate
    dialogues = gate.load(DEV3)
    assert gate.validate(dialogues) == []
    counts = {code: sum(d["language"] == code for d in dialogues) for code in ("ko", "en")}
    assert len(dialogues) >= 80 and min(counts.values()) >= 40
    build = _dev3_build()
    generated, split = build.generate()
    # Compared by digest: a failure must not print a dialogue of the check half.
    assert _digest(generated) == _digest(dialogues)
    assert gate.split_ids(DEV3) == split
    assert (DEV3 / "split.txt").read_text(encoding="utf-8").startswith("seed %d\n" % build.SEED)
    assert not set(split["build"]) & set(split["check"])
    assert len(split["build"]) + len(split["check"]) == len(dialogues)


def test_dev3_halves_share_no_plan_and_no_name_or_item():
    import bench.dialogue_gate as gate
    halves = {name: gate.load(DEV3, name) for name in ("build", "check")}
    plans = {name: {d["variation"]["plan"] for d in rows} for name, rows in halves.items()}
    assert plans["build"] and plans["check"] and not plans["build"] & plans["check"]
    build = _dev3_build()
    assert not set(build.BUILD_PLANS) & set(build.CHECK_PLANS)

    def vocabulary(rows):
        words = set()
        for d in rows:
            words |= set(d["variation"]["initial_values"])
            for t in d["turns"]:
                e = t["expect"]
                for ev in e.get("events") or []:
                    words |= {ev.get(k) for k in ("holder", "from", "to", "item")} - {None}
                if e.get("item"):
                    words.add(e["item"])
        return words
    assert not vocabulary(halves["build"]) & vocabulary(halves["check"])
    vocab = build.vocabulary()
    for language in ("ko", "en"):
        for key in ("names", "items"):
            left, right = vocab["build"][language][key], vocab["check"][language][key]
            as_words = (lambda rows: {r["word"] for r in rows}) if key == "items" else set
            assert not as_words(left) & as_words(right)


def test_dev3_draws_its_words_from_the_probe_lists_not_the_packs():
    import bench.dialogue_gate as gate
    words = json.loads((PROBE / "words.json").read_text(encoding="utf-8"))
    names = {r["name"] for r in words["names"]}
    items = {r["ko"] for r in words["items"]} | {r["en"] for r in words["items"]}
    build = _dev3_build()
    for d in gate.load(DEV3):
        for holder in d["variation"]["initial_values"]:
            assert holder in names
        for t in d["turns"]:
            for ev in t["expect"].get("events") or []:
                item = ev["item"]
                assert item in items or any(build.plural(one) == item for one in items if one.isascii())


def test_dev3_statements_are_mostly_multi_clause_and_most_dialogues_open_with_one():
    import bench.dialogue_gate as gate
    dialogues = gate.load(DEV3)
    records = [t for d in dialogues for t in d["turns"] if t["expect"]["act"] == "record"]
    assert 2 * sum(len(t["expect"]["events"]) > 1 for t in records) >= len(records)
    assert 2 * sum(len(d["turns"][0]["expect"].get("events") or []) > 1 for d in dialogues) >= len(dialogues)


def _tracked_corpus(owned):
    """The tracked files of the gate's corpus folders without the frozen exam sets (never listed, opened or
    read by a development run: the owner runs that overlap check) and without ``owned`` (G5)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("dialogues_dev4_build",
                                                  ROOT / "data/benchmarks/dialogues_dev4/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    return build.corpus_files(owned)


def test_dev3_shares_no_full_sentence_with_any_other_corpus_file():
    import bench.dialogue_gate as gate
    result = gate.overlaps(gate.load(DEV3), files=_tracked_corpus(("data/benchmarks/dialogues_dev3/",)))
    assert result["files"] > 100 and len(result["overlaps"]) == 0


def test_no_development_sentence_is_in_a_file_this_round_changed():
    import bench.dialogue_gate as gate
    sentences = []
    for folder in ("dialogues_dev", "dialogues_dev2", "dialogues_dev3"):
        sentences += gate.dialogue_sentences(gate.load(ROOT / "data/benchmarks" / folder))
    owned = ["frame_induction.py", "language_components.py", "relational_semantics.py", "hangul.py", "engine.py",
             "explain.py", "reasoning_context.py", "state_engine.py", "pack_model.py",
             "tests/test_understanding_r3.py"] + sorted(
        p.relative_to(ROOT).as_posix() for p in (ROOT / "styles").glob("*.json"))
    found = 0
    for name in owned:
        text = gate._normalize_corpus((ROOT / name).read_text(encoding="utf-8"))
        found += sum(1 for _d, _n, _raw, norm in sentences if norm in text and gate._full_sentence_at(text, norm))
    assert found == 0


# G3.4: rules from the dev3 build half's cause table -------------------------------------------

@pytest.mark.parametrize("language,statement,state", [
    # batch 1: statements
    ("english", "Tove had 6 plums. Una had 2.", {"Tove plums": "6", "Una plums": "2"}),
    ("english", "Tove had 6 plums, Una had 2.", {"Tove plums": "6", "Una plums": "2"}),
    ("english", "Tove's got 6 plums and 2 pears.", {"Tove plums": "6", "Tove pears": "2"}),
    ("english", "Tove's got 6 plums and Una 2.", {"Tove plums": "6", "Una plums": "2"}),
    ("한국어", "보람은 자두를 여섯 개 가지고 있고 다온은 두 개 가지고 있어.", {"보람 자두": "6", "다온 자두": "2"}),
    ("한국어", "보람은 자두를 6개 가지고 있다. 다온은 2개 가지고 있다.", {"보람 자두": "6", "다온 자두": "2"}),
])
def test_g34_statement_classes(language, statement, state):
    assert state_after(language, [statement]) == state


def test_a_correction_keeps_the_event_it_corrects_and_only_its_amount():
    # The new amount is typed with its counter and an ending (2마리야): only the
    # amount enters the corrected statement; the event is not lost.
    rows = play("한국어", ["보람은 자두가 여덟 개, 다온은 세 개 있어.", "자두 한 개를 보람이 다온에게 줬어.",
                          "아까 준 건 1개가 아니라 2개야.", "다온은 자두가 몇 개 있어?", "보람은 자두가 몇 개 있어?"])
    assert rows[2]["meaning"]["act"] == "correct"
    assert [asserted_numbers(row["answer"]) for row in rows[3:]] == [{5}, {6}]


def test_a_correction_whose_rewrite_would_change_the_facts_is_not_applied():
    import reasoning_context as rc
    current = context("한국어")
    for line in ["보람은 자두가 여덟 개, 다온은 세 개 있어.", "자두 한 개를 보람이 다온에게 줬어."]:
        current.turn(line)
    with pytest.MonkeyPatch.context() as patch:
        # Every rewrite is read as some other statement: the correction must hold.
        original = rc.ReasoningContext._read_source

        def other(parser, source, **kw):
            if "2" in source and "자두" in source:
                return original(parser, "보람은 자두가 2개 있어.", **kw)
            return original(parser, source, **kw)
        patch.setattr(rc.ReasoningContext, "_read_source", staticmethod(other))
        row = current.turn("아까 준 건 1개가 아니라 2개야.")
    assert row["status"] != "observed" and row["meaning"]["act"] == "hold"


@pytest.mark.parametrize("language,lines,question,value", [
    ("english", ["Tove has 6 plums and Una has 2.", "Una received 2 plums from Tove.",
                 "The one Tove handed was 3, not 2."], "How many plums does Una have?", 5),
    ("english", ["Tove has 6 plums and Una has 2.", "Tove passed Una one plum.",
                 "The one Tove passed was 3, not 1."], "How many plums does Una have?", 5),
    ("한국어", ["아라는 자두가 6개, 보라는 2개 있어.", "보라가 아라에게서 자두 2개를 받았어.",
              "아까 준 건 2개가 아니라 3개야."], "보라는 자두가 몇 개 있어?", 5),
])
def test_an_event_is_named_back_by_any_verb_of_its_frame(language, lines, question, value):
    rows = play(language, lines + [question])
    assert rows[2]["meaning"]["act"] == "correct"
    assert rows[-1]["status"] == "answered" and asserted_numbers(rows[-1]["answer"]) == {value}


@pytest.mark.parametrize("language,lines,question,value", [
    ("english", ["Tove has 6 plums and Una has 2.", "Tove gave Una 3 plums.", "Sorry, I misspoke: Tove gave Una 1."],
     "How many plums does Una have?", 3),
    ("english", ["Tove has 6 plums and Una has 2.", "Tove handed Una 3 plums.", "My mistake, Tove handed Una 4."],
     "How many plums does Tove have?", 2),
    ("한국어", ["아라는 자두가 6개, 보라는 2개 있어.", "아라가 보라에게 자두 3개를 줬어.", "잘못 말했어, 1개를 줬어."],
     "보라는 자두가 몇 개 있어?", 3),
    ("한국어", ["아라는 자두가 6개, 보라는 2개 있어요.", "아라가 보라에게 자두 3개를 건넸어요.", "잘못 말했어요, 4개를 건넸어요."],
     "아라는 자두가 몇 개 있어요?", 2),
])
def test_a_restated_event_corrects_its_amount(language, lines, question, value):
    rows = play(language, lines + [question])
    assert rows[2]["meaning"]["act"] == "correct" and rows[2]["meaning"]["by"] == "restatement"
    assert rows[-1]["status"] == "answered" and asserted_numbers(rows[-1]["answer"]) == {value}


# G3.6: the kinds the packs could not say (request F2-2) ---------------------------------------

@pytest.mark.parametrize("negated", ["Tove did not give Una 3 plums.", "Tove didn't give Una 3 plums.",
                                     "Tove didn't hand Una 3 plums.", "Una did not buy 3 plums.",
                                     "Tove doesn't have 9 plums.", "Una didn't lose 1 plum."])
def test_english_negation_of_transfer_and_possession_changes_nothing(negated):
    rows = play("english", ["Tove has 6 plums and Una has 2.", negated, "How many plums does Tove have?",
                            "How many plums does Una have?"])
    assert rows[1]["status"] == "observed"
    assert [asserted_numbers(row["answer"]) for row in rows[2:]] == [{6}, {2}]


def test_a_denied_count_is_not_a_count():
    rows = play("english", ["Wes doesn't have 4 plums.", "How many plums does Wes have?"])
    assert rows[0]["status"] == "observed" and rows[-1]["status"] != "answered"


def test_the_declared_korean_negation_changes_nothing():
    rows = play("한국어", ["아라는 자두가 6개, 보라는 2개 있어.", "아라가 보라에게 자두 3개를 주지 않았어.", "보라는 자두가 몇 개 있어?",
                          "지우개는 서랍에 있어.", "하루가 지우개를 책상으로 옮기지 않았다.", "지우개는 어디에 있어?"])
    assert rows[1]["status"] == rows[4]["status"] == "observed"
    assert asserted_numbers(rows[2]["answer"]) == {2} and "서랍" in rows[-1]["answer"]


@pytest.mark.parametrize("language,lines,question,expected", [
    ("english", ["Tove has 6 plums and Una has 2."], "Who has fewer plums, Tove or Una?", "Una"),
    ("english", ["Tove has 6 plums and Una has 2."], "Who has fewer now, Tove or Una?", "Una"),
    ("english", ["Tove has 6 plums and Una has 2."], "Do Tove and Una have the same number of plums?", "No"),
    ("english", ["Tove has 4 plums and Una has 4."], "Do Tove and Una have the same number?", "Yes"),
    ("english", ["Tove has 4 plums and Una has 4."], "Who has more plums, Tove or Una?", "both"),
    ("한국어", ["아라는 자두가 6개, 보라는 2개 있어."], "아라와 보라 중 누가 자두가 더 적어?", "보라"),
    ("한국어", ["아라는 자두가 6개, 보라는 2개 있어."], "아라와 보라는 자두가 같아?", "아니요"),
    ("한국어", ["아라는 자두가 4개, 보라는 4개 있어."], "아라와 보라는 자두 수가 똑같아?", "네"),
    ("한국어", ["아라는 자두가 4개, 보라는 4개 있어."], "아라와 보라 중 누가 자두가 더 많아?", "같습니다"),
])
def test_fewer_and_equal_comparisons(language, lines, question, expected):
    rows = play(language, lines + [question])
    assert rows[-1]["status"] == "answered" and expected in rows[-1]["answer"]


@pytest.mark.parametrize("language,lines,question,value", [
    ("english", ["Tove has 6 plums and Una has 2.", "Tove gave Una 3 plums.", "Una ate 1 plum."],
     "How many plums did Tove have before Tove gave Una 3 plums?", {6}),
    ("english", ["Tove has 6 plums and Una has 2.", "Tove gave Una 3 plums.", "Una ate 1 plum."],
     "After Tove gave Una 3, how many plums did Una have?", {5}),
    ("english", ["The box is in the hall.", "Tove moved the box to the attic."],
     "Where was the box before Tove moved the box to the attic?", "hall"),
    ("한국어", ["아라는 자두가 6개, 보라는 2개 있어.", "아라가 보라에게 자두 3개를 줬어.", "보라가 자두 1개를 먹었어."],
     "보라가 자두를 먹기 전에 보라는 자두가 몇 개 있었어?", {5}),
    ("한국어", ["아라는 자두가 6개, 보라는 2개 있어.", "아라가 보라에게 자두 3개를 줬어.", "보라가 자두 1개를 먹었어."],
     "아라가 보라에게 자두를 준 뒤에 아라는 자두가 몇 개 있었어?", {3}),
    ("한국어", ["연필은 서랍에 있어.", "하루가 연필을 책상으로 옮겼어."], "하루가 연필을 옮기기 전에 연필은 어디에 있었어?", "서랍"),
])
def test_state_before_or_after_one_earlier_event(language, lines, question, value):
    rows = play(language, lines + [question])
    assert rows[-1]["status"] == "answered" and rows[-1]["meaning"]["time"]["event"] in lines
    if isinstance(value, set):
        assert asserted_numbers(rows[-1]["answer"]) == value
    else:
        assert value in rows[-1]["answer"]


def test_an_order_in_time_that_fits_two_events_is_asked_back():
    rows = play("english", ["Tove has 6 plums and Una has 2.", "Tove gave Una 1 plum.", "Tove handed Una 1 plum.",
                            "How many plums did Una have before Tove gave Una 1 plum?"])
    assert rows[-1]["status"] != "answered"


@pytest.mark.parametrize("language,lines", [
    ("english", ["Tove has 7 plums.", "Una has 3 plums.", "How many plums does Una have?", "Will it snow on Friday?",
                 "How many has she got?"]),
    ("한국어", ["새롬이는 자두가 7개 있어.", "누리는 자두가 3개 있어.", "누리는 자두가 몇 개 있어?", "내일 비가 올까?",
              "걔는 몇 개야?"]),
])
def test_a_turn_the_conversation_did_not_read_breaks_the_thread_a_pointer_follows(language, lines):
    rows = play(language, lines)
    assert rows[2]["status"] == "answered"
    assert rows[-1]["status"] != "answered" and not asserted_numbers(rows[-1]["answer"]) & {7, 3}


def facts_of(language, text):
    parsed = model(language).parser().parse(text, partial=True, events=True, repair=True) or {}
    return [list(map(str, row["triple"])) for row in parsed.get("facts", [])]


def test_a_fused_amount_is_never_a_place_and_a_kept_phrase_still_reads_with_a_verb_variant():
    parser = model("한국어").parser()
    assert parser._names_an_amount({"triple": ["수첩", "location", "12개"]})
    assert facts_of("한국어", "보람은 자두를 열다섯 개 가지고 계십니다") == [["보람 자두", "count", "15"]]
