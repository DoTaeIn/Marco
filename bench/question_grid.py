"""Question grid probe (goal G7-Q.0): the question reader measured by structure, not by sample.

A small state is stated first, in plain statements the reader records; then every question
cell is asked in a dialogue of its own, over that state:

* **base cells**: operator x modifier x holder form. Operators: ``count``, ``total`` (two
  holders), ``more``, ``fewer``, ``same`` (two holders), ``left`` (what remains), ``where``
  (a place's count), ``why`` (a restated fact). Modifiers: the words that do not change the
  operator (``in all``, ``now``, ``still``, ``left`` ...; 모두, 지금, 아직, 남은 ...), each
  with the operators it is said with in the language. Holder forms: a name, a title and a
  name, a name and a title, a relational noun, the speaker, a place.
* **follow-up cells**: a base question, then a partial question that names one slot only:
  ``holder`` (What about Bo? / 보라는?), ``item`` (And cups? / 컵은?), ``place`` (And in
  the shed? / 헛간에는?), ``repair`` (a bare name after an answer: Bo, I mean. / 보라요.),
  ``ask`` (a bare name after the engine asked which: the pointer question first); and a holder follow-up
  after what came before it: a held question, a clarify exchange, a why, a restart of the conversation
  (``after_held``, ``after_clarify``, ``after_why``, ``after_restart``: the follow-up asks the count). And corrections of a transfer said just before (or two
  turns before): its amount only (No, three.), or its direction (the giver and receiver swapped), scored by
  the receiver's count asked after it.

Every turn is played through the dialogue gate's own player (``bench.dialogue_gate.run``,
the UI turn handler) and scored against the value the state gives: correct, hold (not
answered), wrong (a value, winner or verdict other than the state's). A cell whose state
statements were not all recorded is ``blocked``, not a question failure. The frozen sets are
never read. Sentences are composed here at run time from the frames below.

    python bench/question_grid.py [--language ko|en] [--effort 0-3] [--jobs N] [--out report.json] [--cells]
"""
import argparse
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OPERATORS = ("count", "total", "more", "fewer", "same", "left", "where", "why")
FOLLOW_UPS = ("holder", "item", "place", "repair", "ask")
# a holder follow-up after what came before it: a held question, a clarify exchange, a why
CONTEXTS = ("after_held", "after_clarify", "after_why", "after_restart")
RESTART = "\x00restart\x00"      # a turn said after the conversation was reopened


# ---------------------------------------------------------------------------
# Korean particles by the final consonant of the word before them
# ---------------------------------------------------------------------------
def _batchim(word):
    last = word.rstrip()[-1:]
    if not ("가" <= last <= "힣"):
        return False
    return (ord(last) - 0xAC00) % 28 != 0


def _p(word, pair):
    """``_p("민석", "은/는")`` -> ``민석은``."""
    with_, without = pair.split("/")
    return word + (with_ if _batchim(word) else without)


# ---------------------------------------------------------------------------
# The state: holders by form, two items, counts that differ everywhere
# ---------------------------------------------------------------------------
# key: the holder's slot in the grid; said: how it is named; the rest: its grammar.
EN = {
    "items": {"pen": "pens", "cup": "cups"},
    "holders": {
        "name": {"subj": "Nora", "obj": "Nora", "aux": "does", "have": "has", "names": ["Nora"]},
        "other": {"subj": "Bo", "obj": "Bo", "aux": "does", "have": "has", "names": ["Bo"]},
        "title_name": {"subj": "Dr. Kim", "obj": "Dr. Kim", "aux": "does", "have": "has", "names": ["Kim"]},
        "relation": {"subj": "my sister", "obj": "my sister", "aux": "does", "have": "has",
                     "names": ["sister"], "cap": "My sister"},
        "me": {"subj": "I", "obj": "me", "aux": "do", "have": "have", "names": ["you", "I"]},
        "place": {"subj": "the garage", "obj": "the garage", "aux": "does", "have": "has", "names": ["garage"],
                  "place": True, "in": "in the garage"},
        "place2": {"subj": "the shed", "obj": "the shed", "aux": "does", "have": "has", "names": ["shed"],
                   "place": True, "in": "in the shed"},
    },
    "forms": ("name", "title_name", "relation", "me", "place"),
    "pointer": "she",
}
KO = {
    "items": {"pen": "연필", "cup": "컵"},
    "holders": {
        "name": {"name": "노라", "names": ["노라"]},
        "other": {"name": "민석", "names": ["민석"]},
        "title_name": {"name": "택배 기사 준호 씨", "short": "준호 씨", "names": ["준호"]},
        "name_title": {"name": "기 대표님", "names": ["기 대표"]},
        "relation": {"name": "내 동생", "short": "동생", "names": ["동생"]},
        "me": {"name": "나", "names": ["나", "고객님", "당신"], "me": True},
        "place": {"name": "창고", "names": ["창고"], "place": True},
        "place2": {"name": "헛간", "names": ["헛간"], "place": True},
    },
    "forms": ("name", "title_name", "name_title", "relation", "me", "place"),
    "pointer": "걔",
}
COUNTS = {"name": (6, 11), "other": (4, 9), "title_name": (5, 12), "name_title": (3, 14), "relation": (13, 18),
          "me": (7, 15), "place": (8, 16), "place2": (10, 17)}


def _state_en(lang):
    out = []
    for key, h in lang["holders"].items():
        for index, (item, plural) in enumerate(lang["items"].items()):
            n = COUNTS[key][index]
            if h.get("place"):
                out.append(("There are %d %s %s." % (n, plural, h["in"]), key))
            else:
                subject = h.get("cap") or h["subj"]
                out.append(("%s %s %d %s." % (subject, h["have"], n, plural), key))
    return out


def _state_ko(lang):
    out = []
    for key, h in lang["holders"].items():
        for index, item in enumerate(lang["items"].values()):
            n = COUNTS[key][index]
            if h.get("place"):
                out.append(("%s에 %s %d개 있어." % (h["name"], _p(item, "이/가"), n), key))
            elif h.get("me"):
                out.append(("나는 %s %d개 있어." % (_p(item, "이/가"), n), key))
            else:
                out.append(("%s %s %d개 있어." % (_p(h["name"], "은/는"), _p(item, "이/가"), n), key))
    return out


# ---------------------------------------------------------------------------
# Question frames, per language: operator -> modifier -> sentence
# ---------------------------------------------------------------------------
# A modifier row: (name, kind) where kind says which operators the language says it with.
EN_MODIFIERS = {
    "none": OPERATORS,
    "in all": ("count", "total", "where"), "altogether": ("count", "total", "where"),
    "combined": ("total",), "in total": ("count", "total", "where"), "between them": ("total",),
    "all together": ("total",),
    "now": OPERATORS, "at the moment": ("count", "total", "more", "fewer", "left", "where"),
    "still": ("count", "where"),
    "left": ("count", "total", "more", "fewer", "where"), "remaining": ("count", "where"),
}
KO_MODIFIERS = {
    "none": OPERATORS,
    "모두": ("count", "total", "where"), "다": ("count", "total"), "전부": ("count", "total", "where"),
    "합쳐서": ("total",), "다 합쳐": ("total",), "총": ("count", "total", "where"),
    "이제": OPERATORS, "지금": OPERATORS, "아직": ("count", "where"),
    "남은": ("count", "total", "where"),
}


def _en_pair(form):
    """The two holders a two-holder question names for a holder form."""
    return (form, "place2") if form == "place" else (form, "other")


def en_question(op, mod, form, item="pen"):
    """(sentence, expectation) or None when the language does not say it."""
    L, H = EN, EN["holders"]
    plural = L["items"][item]
    h = H[form]
    index = list(L["items"]).index(item)
    time = {"now": " now", "at the moment": " at the moment"}.get(mod, "")
    if op in ("count", "left", "where", "why"):
        if op == "where" and not h.get("place"):
            return None
        if op != "where" and h.get("place") and op != "count":
            return None
        value = COUNTS[form][index]
        if op == "why":
            if mod not in ("none", "now"):
                return None
            return ("Why %s %s have %d %s%s?" % (h["aux"], h["subj"], value, plural, time),
                    {"kind": "why", "holder": form, "item": item, "value": value})
        if op == "where":
            place = h["in"]
            text = {"none": "How many %s are there %s?" % (plural, place),
                    "in all": "How many %s are there %s in all?" % (plural, place),
                    "altogether": "How many %s are there %s altogether?" % (plural, place),
                    "in total": "How many %s are there %s in total?" % (plural, place),
                    "now": "How many %s are %s now?" % (plural, place),
                    "at the moment": "How many %s are %s at the moment?" % (plural, place),
                    "still": "How many %s are still %s?" % (plural, place),
                    "left": "How many %s are left %s?" % (plural, place),
                    "remaining": "How many %s are remaining %s?" % (plural, place)}.get(mod)
        elif op == "left":
            text = {"none": "How many %s %s %s have left?" % (plural, h["aux"], h["subj"]),
                    "now": "How many %s %s %s have left now?" % (plural, h["aux"], h["subj"])}.get(mod)
            if mod == "none" and form == "name":
                text = "How many %s are left with %s?" % (plural, h["obj"])
        else:
            base = "How many %s %s %s have" % (plural, h["aux"], h["subj"])
            text = {"none": base + "?", "in all": base + " in all?", "altogether": base + " altogether?",
                    "in total": base + " in total?", "now": base + " now?", "at the moment": base + " at the moment?",
                    "still": "How many %s %s %s still have?" % (plural, h["aux"], h["subj"]),
                    "left": base + " left?",
                    "remaining": base + " remaining?"}.get(mod)
        return (text, {"kind": "value", "holder": form, "item": item, "value": value}) if text else None
    a, b = _en_pair(form)
    ha, hb = H[a], H[b]
    va, vb = COUNTS[a][index], COUNTS[b][index]
    if op == "total":
        if form == "me":
            pair = "%s and I" % hb["subj"]
        else:
            pair = "%s and %s" % (ha["subj"], hb["subj"])
        base = "How many %s do %s have" % (plural, pair)
        tail = {"none": "?", "in all": " in all?", "altogether": " altogether?", "combined": " combined?",
                "in total": " in total?", "between them": " between them?", "all together": " all together?",
                "now": " now?", "at the moment": " at the moment?", "left": " left?"}.get(mod)
        if tail is None:
            return None
        if mod == "between them" and form == "me":
            base, tail = "How many %s do %s have" % (plural, pair), " between us?"
        return base + tail, {"kind": "value", "holder": [a, b], "item": item, "value": va + vb}
    if op in ("more", "fewer"):
        word = "more" if op == "more" else "fewer"
        first = "me" if form == "me" else ha["obj"]
        left = " left" if mod == "left" else ""
        text = "Who has %s %s%s%s, %s or %s?" % (word, plural, left, time, first, hb["obj"])
        if form == "me" and mod == "none":
            text = "Which of us has %s %s, me or %s?" % (word, plural, hb["obj"])
        if mod not in ("none", "now", "at the moment", "left"):
            return None
        winner = (a if va > vb else b) if op == "more" else (a if va < vb else b)
        return text, {"kind": "winner", "winner": winner, "loser": b if winner == a else a, "item": item}
    if op == "same":
        if mod not in ("none", "now"):
            return None
        pair = "%s and I" % hb["subj"] if form == "me" else "%s and %s" % (ha["subj"], hb["subj"])
        return ("Do %s have the same number of %s%s?" % (pair, plural, time),
                {"kind": "same", "same": va == vb, "values": [va, vb], "item": item})
    return None


def ko_question(op, mod, form, item="pen"):
    L, H = KO, KO["holders"]
    noun = L["items"][item]
    h = H[form]
    index = list(L["items"]).index(item)
    name = h["name"]
    pre = {"이제": "이제 ", "지금": "지금 ", "아직": "아직 "}.get(mod, "")
    total_word = {"모두": "모두 ", "다": "다 ", "전부": "전부 ", "합쳐서": "합쳐서 ", "다 합쳐": "다 합쳐 ",
                  "총": "총 "}.get(mod, "")
    if op in ("count", "left", "where", "why"):
        if op == "where" and not h.get("place"):
            return None
        if op != "where" and h.get("place") and op != "count":
            return None
        value = COUNTS[form][index]
        topic = "나는" if h.get("me") else _p(name, "은/는")
        if op == "why":
            if mod not in ("none", "지금"):
                return None
            subject = "내가" if h.get("me") else _p(name, "이/가")
            return ("%s왜 %s %s %d개야?" % (pre, subject, _p(noun, "이/가"), value),
                    {"kind": "why", "holder": form, "item": item, "value": value})
        if op == "where":
            place = name + "에는"
            if mod == "남은":
                text = "%s에 남은 %s 몇 개야?" % (name, _p(noun, "은/는"))
            else:
                text = "%s%s %s %s몇 개 있어?" % (pre, place, _p(noun, "이/가"), total_word)
        elif op == "left":
            if mod not in ("none", "이제", "지금"):
                return None
            giver = "나한테" if h.get("me") else name + "에게"
            text = "%s%s 남은 %s 몇 개야?" % (pre, giver, _p(noun, "은/는"))
        else:
            if mod == "남은":
                giver = "나한테" if h.get("me") else name + "에게"
                text = "%s 남은 %s 몇 개야?" % (giver, _p(noun, "은/는"))
            else:
                text = "%s%s %s %s몇 개야?" % (pre, topic, _p(noun, "이/가"), total_word)
                if mod == "아직":
                    text = "%s %s 아직 몇 개 있어?" % (topic, _p(noun, "이/가"))
        return (text, {"kind": "value", "holder": form, "item": item, "value": value}) if text else None
    a, b = (form, "place2") if form == "place" else (form, "other")
    ha, hb = H[a], H[b]
    va, vb = COUNTS[a][index], COUNTS[b][index]
    first = "나" if ha.get("me") else ha["name"]
    second = hb["name"]
    if op == "total":
        if mod in ("아직",):
            return None
        joined = "%s %s" % (_p(first, "과/와"), _p(second, "은/는"))
        if mod == "남은":
            text = "%s %s 남은 %s 몇 개야?" % (_p(first, "과/와"), second + "에게", _p(noun, "은/는"))
        else:
            text = "%s%s %s %s몇 개야?" % (pre, joined, _p(noun, "이/가"), total_word)
        return text, {"kind": "value", "holder": [a, b], "item": item, "value": va + vb}
    if op in ("more", "fewer"):
        if mod not in ("none", "이제", "지금"):
            return None
        word = "많이" if op == "more" else "적게"
        text = "%s%s %s 중에 누가 %s 더 %s 가지고 있어?" % (pre, _p(first, "과/와"), second, _p(noun, "을/를"), word)
        winner = (a if va > vb else b) if op == "more" else (a if va < vb else b)
        return text, {"kind": "winner", "winner": winner, "loser": b if winner == a else a, "item": item}
    if op == "same":
        if mod not in ("none", "지금"):
            return None
        text = "%s%s %s %s 같아?" % (pre, _p(first, "과/와"), _p(second, "은/는"), _p(noun, "이/가"))
        return text, {"kind": "same", "same": va == vb, "values": [va, vb], "item": item}
    return None


# ---------------------------------------------------------------------------
# Follow-ups: the partial question after a base question
# ---------------------------------------------------------------------------
def en_follow_up(kind, form):
    """(base form, follow-up sentence, holder the answer is about, item, operator) list."""
    H = EN["holders"]
    out = []
    if kind == "holder":
        # the base names the plain name; the follow-up names the form (the plain name asks about Bo)
        target = "other" if form == "name" else form
        said = "me" if target == "me" else H[target]["obj"]
        out.append(("name", "What about %s?" % said, target))
        out.append(("name", "And %s?" % said, target))
    elif kind == "item":
        out.append((form, "And cups?", form))
        out.append((form, "What about cups?", form))
    elif kind == "place":
        base = form if form != "place" else "name"
        out.append((base, "And in the shed?", "place2"))
        out.append((base, "What about in the garage?", "place"))
    elif kind == "repair":
        target = "other" if form == "name" else form
        said = H[target]["obj"] if target != "me" else "me"
        cap = said[0].upper() + said[1:]
        if target == "me":
            out.append(("name", "I mean me.", target))
        else:
            out.append(("name", "%s, I mean." % cap, target))
            out.append(("name", "I mean %s." % said, target))
            out.append(("name", "%s is the one I mean." % cap, target))
    elif kind == "ask":
        if form in ("name", "title_name"):
            said = H[form]["obj"]
            out.append(("ask", "%s, I mean." % said, form))
    return out


def ko_follow_up(kind, form):
    H = KO["holders"]
    out = []
    if kind == "holder":
        target = "other" if form == "name" else form
        said = H[target].get("short") or H[target]["name"]
        out.append(("name", "%s?" % _p(said, "은/는"), target))
        out.append(("name", "%s요?" % _p(said, "은/는"), target))
        out.append(("name", "그럼 %s?" % _p(said, "은/는"), target))
    elif kind == "item":
        out.append((form, "%s?" % _p(KO["items"]["cup"], "은/는"), form))
        out.append((form, "%s요?" % _p(KO["items"]["cup"], "은/는"), form))
    elif kind == "place":
        base = form if form != "place" else "name"
        out.append((base, "헛간에는?", "place2"))
        out.append((base, "창고는요?", "place"))
    elif kind == "repair":
        target = "other" if form == "name" else form
        if target == "me":
            out.append(("name", "저요.", target))
        else:
            said = H[target].get("short") or H[target]["name"]
            out.append(("name", "%s요." % said if not _batchim(said) else "%s이요." % said, target))
            out.append(("name", "%s 말이야." % said, target))
    elif kind == "ask":
        if form in ("name", "title_name", "name_title"):
            said = H[form].get("short") or H[form]["name"]
            out.append(("ask", "%s 말이야." % said, form))
    return out


# ---------------------------------------------------------------------------
# Building the dialogues
# ---------------------------------------------------------------------------
def _lang(code):
    return {"en": (EN, _state_en, en_question, en_follow_up, EN_MODIFIERS),
            "ko": (KO, _state_ko, ko_question, ko_follow_up, KO_MODIFIERS)}[code]


def cells(code):
    """[(cell id, cell key, [turn texts], expectation)]."""
    lang, state_of, question, follow_up, modifiers = _lang(code)
    state = [text for text, _key in state_of(lang)]
    out = []
    for op in OPERATORS:
        for mod, ops in modifiers.items():
            if op not in ops:
                continue
            for form in lang["forms"]:
                asked = question(op, mod, form)
                if asked is None:
                    continue
                text, expect = asked
                out.append(("%s|%s|%s|base" % (op, mod, form), {"op": op, "mod": mod, "form": form, "follow": "base"},
                            state + [text], expect))
    for kind in FOLLOW_UPS:
        for form in lang["forms"]:
            for base_form, said, target in follow_up(kind, form):
                ops = {"holder": ("count", "left", "why"), "item": ("count", "total", "more", "fewer", "same", "left"),
                       "place": ("count",), "repair": ("count", "left", "why"), "ask": ("count",)}[kind]
                for op in ops:
                    if kind == "ask":
                        first = ("How many %s does %s have?" % (lang["items"]["pen"], lang["pointer"]) if code == "en"
                                 else "%s %s 몇 개야?" % (_p(lang["pointer"], "은/는"), _p(lang["items"]["pen"], "이/가")))
                    else:
                        asked = question(op, "none", base_form)
                        if asked is None:
                            continue
                        first = asked[0]
                    item = "cup" if kind == "item" else "pen"
                    if kind in ("holder", "repair", "ask", "place"):
                        expect_q = question("where" if (kind == "place" or lang["holders"][target].get("place"))
                                            and op == "count" else op, "none", target, item)
                        if expect_q is None and op == "count":
                            expect_q = question("count", "none", target, item)
                    else:
                        expect_q = question(op, "none", base_form, item)
                    if expect_q is None:
                        continue
                    out.append(("%s|none|%s|%s:%s" % (op, form, kind, said),
                                {"op": op, "mod": "none", "form": form, "follow": kind},
                                state + [first, said], expect_q[1]))
    for kind in CONTEXTS:
        for form in lang["forms"]:
            target = "other" if form == "name" else form
            h = lang["holders"][target]
            if code == "en":
                said = "What about %s?" % ("me" if target == "me" else h["obj"])
                before = {"after_held": ["How many %s does Zed have?" % lang["items"]["pen"]],
                          "after_clarify": ["How many %s does she have?" % lang["items"]["pen"],
                                            "%s, I mean." % lang["holders"]["name"]["obj"]],
                          "after_why": [question("count", "none", "name")[0],
                                        question("why", "none", "name")[0]],
                          "after_restart": [question("count", "none", "name")[0]]}[kind]
            else:
                short = h.get("short") or h["name"]
                said = "%s?" % _p(short, "은/는")
                before = {"after_held": ["%s %s 몇 개야?" % (_p("제드", "은/는"), _p(lang["items"]["pen"], "이/가"))],
                          "after_clarify": ["%s %s 몇 개야?" % (_p(lang["pointer"], "은/는"),
                                                             _p(lang["items"]["pen"], "이/가")),
                                            "%s 말이야." % lang["holders"]["name"]["name"]],
                          "after_why": [question("count", "none", "name")[0],
                                        question("why", "none", "name")[0]],
                          "after_restart": [question("count", "none", "name")[0]]}[kind]
            if kind == "after_restart":
                said = RESTART + said
            expect_q = question("where" if h.get("place") else "count", "none", target)
            if expect_q is None:
                continue
            out.append(("count|none|%s|%s:%s" % (form, kind, said.replace(RESTART, "")), {"op": "count", "mod": "none",
                                                                                      "form": form,
                                                                     "follow": kind},
                        state + before + [said], expect_q[1]))
    # short follow-ups with a word that says nothing, a name never counted (held naming it), and comparisons
    # of two holders said around the question word
    a, b = ((EN["holders"]["name"]["subj"], EN["holders"]["other"]["subj"]) if code == "en"
            else (KO["holders"]["name"]["name"], KO["holders"]["other"]["name"]))
    pen = lang["items"]["pen"]
    first = question("count", "none", "name")[0]
    stranger = "Zed" if code == "en" else "제드"
    shorts = ({"polite": ["What about %s, please?" % b, "Maybe %s?" % b],
               "unknown_name": ["%s?" % stranger, "And %s?" % stranger]} if code == "en" else
              {"polite": ["혹시 %s요?" % _p(b, "은/는"), "%s 좀?" % _p(b, "은/는")],
               "unknown_name": ["%s?" % _p(stranger, "은/는"), "그럼 %s?" % _p(stranger, "은/는")]})
    for kind, turns in shorts.items():
        for said in turns:
            expect = (question("count", "none", "other")[1] if kind == "polite"
                      else {"kind": "held_named", "name": stranger})
            out.append(("count|none|name|%s:%s" % (kind, said), {"op": "count", "mod": "none", "form": "name",
                                                                "follow": kind}, state + [first, said], expect))
    compare = ([("more", "Between %s and %s, who has more %s?" % (a, b, pen)),
                ("more", "%s or %s, who has more %s?" % (a, b, pen)),
                ("more", "Does %s have more %s than %s?" % (a, pen, b)),
                ("fewer", "Does %s have fewer %s than %s?" % (b, pen, a))] if code == "en" else
               [("more", "%s %s보다 %s 더 많아?" % (_p(a, "이/가"), b, _p(pen, "이/가"))),
                ("fewer", "%s %s보다 %s 더 적어?" % (_p(b, "이/가"), a, _p(pen, "이/가")))])
    for op, said in compare:
        winner = "name" if op == "more" else "other"
        out.append(("%s|none|name|compare:%s" % (op, said), {"op": op, "mod": "none", "form": "name",
                                                            "follow": "compare"}, state + [said],
                    {"kind": "winner", "winner": winner, "loser": "other" if winner == "name" else "name",
                     "item": "pen"}))
    # which person: two holders said with the same relation or title; the question asks back naming both,
    # and the reply that names one is answered
    x, y = ("Lena", "Omar") if code == "en" else ("미경", "수아")
    pair = ((["My cousin %s has 5 %s." % (x, pen), "My cousin %s has 3 %s." % (y, pen)],
             "How many %s does my cousin have?" % pen, "%s." % x) if code == "en" else
            (["제 친구 %s %s 5개 있어." % (_p(x, "은/는"), _p(pen, "이/가")),
              "제 친구 %s %s 3개 있어." % (_p(y, "은/는"), _p(pen, "이/가"))],
             "제 친구는 %s 몇 개 있어?" % _p(pen, "이/가"), "%s요." % x))
    statements, asked, reply = pair
    out.append(("count|none|relation|which_person:ask", {"op": "count", "mod": "none", "form": "relation",
                                                          "follow": "which_person"},
                state + statements + [asked], {"kind": "ask_named", "names": [x, y]}))
    out.append(("count|none|relation|which_person:reply", {"op": "count", "mod": "none", "form": "relation",
                                                            "follow": "which_person"},
                state + statements + [asked, reply], {"kind": "value", "holder": None, "item": "pen", "value": 5}))
    # which person, no thing and no name: a pointer or a description over two holders of the thing just asked
    kite = "kites" if code == "en" else "연"
    # (the question before asks about both, so that no one person is the one the discourse points at)
    thing_state = (["%s has 5 %s." % (x, kite), "%s has 3 %s." % (y, kite),
                    "How many %s do %s and %s have?" % (kite, x, y)]
                   if code == "en" else
                   ["%s %s 5개 있어." % (_p(x, "은/는"), _p(kite, "이/가")), "%s %s 3개 있어." % (_p(y, "은/는"), _p(kite, "이/가")),
                    "%s %s %s 몇 개야?" % (_p(x, "과/와"), _p(y, "은/는"), _p(kite, "이/가"))])
    pointing = (["How many does the tall one have now?", "How many does that person have now?"] if code == "en"
                else ["그 분은 이제 몇 개예요?", "그 사람은 지금 몇 개야?"])
    replies = (["%s, I guess." % y] if code == "en" else ["%s 씨요." % y])
    for said in pointing:
        out.append(("count|none|relation|which_person:%s" % said, {"op": "count", "mod": "none", "form": "relation",
                                                                    "follow": "which_person"},
                    state + thing_state + [said], {"kind": "ask_named", "names": [x, y]}))
        out.append(("count|none|relation|which_person:%s/%s" % (said, replies[0]),
                    {"op": "count", "mod": "none", "form": "relation", "follow": "which_person"},
                    state + thing_state + [said, replies[0]], {"kind": "value", "holder": None, "item": "pen",
                                                              "value": 3}))
    # "the two": after a question about each of two holders, a total or a comparison over the two of them
    both_asked = [question("count", "none", "name")[0], question("count", "none", "other")[0]]
    pair_forms = ([("total", "How many do the two of them have altogether?", 10),
                   ("more", "Which of the two has more?", "name"), ("fewer", "Which of the two has fewer?", "other")]
                  if code == "en" else
                  [("total", "둘이 합쳐서 몇 개야?", 10), ("more", "둘 중 누가 더 많아?", "name"),
                   ("fewer", "두 사람 중 누가 더 적게 가지고 있어?", "other")])
    for op, said, want in pair_forms:
        expect = ({"kind": "value", "holder": ["name", "other"], "item": "pen", "value": want} if op == "total" else
                  {"kind": "winner", "winner": want, "loser": "other" if want == "name" else "name", "item": "pen"})
        out.append(("%s|none|name|the_two:%s" % (op, said), {"op": op, "mod": "none", "form": "name", "follow": "the_two"},
                    state + both_asked + [said], expect))
    # corrections: a transfer, then a correction of it (its amount, or its direction), then the receiver's count
    words = {"en": {"a": EN["holders"]["name"]["subj"], "b": EN["holders"]["other"]["subj"], "n": "three", "o": "two",
                    "t": EN["items"]["pen"]},
             "ko": {"a": KO["holders"]["name"]["name"], "b": KO["holders"]["other"]["name"], "n": "세", "o": "두",
                    "t": KO["items"]["pen"]}}[code]
    event = ("{a} gave {b} {o} {t}." if code == "en" else "{a}가 {b}에게 {t}을 {o} 개 줬어.").format(**words)
    other = lang["items"]["cup"]
    between = ("%s has 9 %s." % (words["b"], other) if code == "en"
               else "%s %s 9개 있어." % (_p(words["b"], "은/는"), _p(other, "이/가")))
    ask = question("count", "none", "other")[0]
    base_other = COUNTS["other"][0]
    for kind, said_list in CORRECTIONS[code].items():
        for said in said_list:
            before = [event] + ([between] if kind == "two_back" else [])
            value = base_other + (3 if kind in ("amount", "two_back") else -2)
            said = said.format(**words)
            out.append(("correct|none|%s|%s" % (kind, said), {"op": "correct", "mod": "none", "form": kind,
                                                            "follow": "correction"},
                        state + before + [said, ask], {"kind": "value", "holder": "other", "item": "pen",
                                                       "value": value}))
    return out, len(state)


# the corrections the grid says after the transfer: the amount (two to three) or the direction. Written as
# frames, filled at run time ({a} the giver, {b} the receiver, {n} the new amount, {o} the old one, {t} the thing).
CORRECTIONS = {
    "en": {"amount": ["No, {n}.", "Not {o}, {n}.", "Actually, it was {n}.", "Sorry, {n}.", "Wait, it was {n}, not {o}."],
           "two_back": ["Actually, it was {n} {t}, not {o}.", "Actually, {a} gave {b} {n}, not {o}."],
           "direction": ["No, {b} gave them to {a}.", "Sorry, {b} gave {a} {o} {t}, not {a} to {b}.",
                         "No, the other way around, {b} gave them to {a}."]},
    "ko": {"amount": ["아니, {n} 개.", "{o} 개가 아니라 {n} 개야.", "아니, {n} 개였어.", "잘못 말했어, {n} 개야."],
           "two_back": ["아니, {t}은 {n} 개였어.", "아까 준 건 {o} 개가 아니라 {n} 개야."],
           "direction": ["아니, {b}이 {a}한테 준 거야.", "{a}가 준 게 아니라 {b}이 {a}한테 준 거야.",
                         "반대로, {b}이 {a}에게 줬어."]},
}


def dialogues(code):
    rows, n_state = cells(code)
    out = []
    for index, (cell, key, turns, expect) in enumerate(rows):
        out.append({"id": "grid_%s_%04d" % (code, index), "language": code, "cell": cell, "key": key,
                    "expect": expect, "n_state": n_state,
                    "turns": [{"n": i + 1, "say": say[len(RESTART):], "restart_before": True}
                              if say.startswith(RESTART) else {"n": i + 1, "say": say}
                              for i, say in enumerate(turns)]})
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _names(code, key):
    return _lang(code)[0]["holders"][key]["names"]


def score_cell(d, observations):
    from bench import dialogue_gate as gate
    code, expect = d["language"], d["expect"]
    n_state = d["n_state"]
    if len(observations) < len(d["turns"]) or any(o.get("error") for o in observations):
        return "error", "execution_error"
    if any(gate.status(o) != "observed" for o in observations[:n_state]):
        return "blocked", "state_not_recorded"
    obs = observations[-1]
    st = gate.status(obs)
    if expect["kind"] == "ask_named":
        if st == "answered":
            return "wrong", "answered"
        said = obs.get("answer") or ""
        return ("correct", "asked_which") if all(n in said for n in expect["names"]) else ("hold", "vague_ask")
    if expect["kind"] == "held_named":
        # a question about a holder never counted: correct when held naming it
        if st == "answered":
            return "wrong", "answered"
        return ("correct", "held_named") if expect["name"] in (obs.get("answer") or "") else ("hold", "vague_hold")
    if st != "answered":
        return "hold", st
    text = gate.asserted(obs.get("answer") or "")
    kind = expect["kind"]
    if kind == "value":
        values = gate.quantities(text)
        if values == {expect["value"]}:
            return "correct", "value"
        if not values:
            return "wrong", "no_value"
        return "wrong", "value:%s" % sorted(values)
    if kind == "winner":
        win = any(gate._mentions(text, n) for n in _names(code, expect["winner"]))
        lose = any(gate._mentions(text, n) for n in _names(code, expect["loser"]))
        # the Korean user is left unsaid, named by the honorific verb (W5, request G4-2)
        honorific = code == "ko" and bool(re.search(r"(으)?(십니다|세요|셔요)", text))
        if code == "ko" and KO["holders"][expect["winner"]].get("me") and honorific and not lose:
            win = True
        if code == "ko" and KO["holders"][expect["loser"]].get("me") and honorific:
            lose = True
        if win and not lose:
            return "correct", "winner"
        return "wrong", "winner_named:%s/%s" % (win, lose)
    if kind == "same":
        folded = text.lower()
        negative = bool(re.search(r"\b(no|not)\b", folded)) or "않" in text or "아니" in text or "다릅" in text
        if negative != expect["same"]:
            return "correct", "verdict"
        return "wrong", "verdict"
    if kind == "held_named":
        return ("wrong", "answered") if st == "answered" else ("hold", "held")
    if kind == "why":
        # the explanation says the holder's count and cites the holder's own statement
        lang, state_of = _lang(code)[0], _lang(code)[1]
        cited = [text_ for text_, key in state_of(lang) if key == expect["holder"]]
        item_index = list(lang["items"]).index(expect["item"])
        needed = cited[item_index]
        said = obs.get("answer") or ""
        if needed.rstrip(".") in said and expect["value"] in gate.quantities(gate.asserted(said)):
            return "correct", "explained"
        return "wrong", "explanation"
    return "wrong", "unknown_kind"


def _run_shard(shard, effort=None):
    os.environ.setdefault("KG_ENCODER", "문자")
    if effort is not None:
        os.environ["MARCO_EFFORT"] = str(effort)
    from bench import dialogue_gate as gate
    return gate.run(shard, ROOT)


def run(codes, jobs=1, effort=None):
    ds = [d for code in codes for d in dialogues(code)]
    if jobs <= 1:
        answers = _run_shard(ds, effort)
    else:
        shards = [ds[i::jobs] for i in range(jobs)]
        answers = {}
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for part in pool.map(_run_shard, shards, [effort] * len(shards)):
                answers.update(part)
    rows = []
    for d in ds:
        bucket, reason = score_cell(d, answers.get(d["id"]) or [])
        obs = (answers.get(d["id"]) or [{}])[-1]
        rows.append({"id": d["id"], "language": d["language"], "cell": d["cell"], **d["key"], "bucket": bucket,
                     "reason": reason, "asked": [t["say"] for t in d["turns"][d["n_state"]:]],
                     "answer": (obs.get("answer") or "")[:200]})
    return rows


def tables(rows):
    """Per language: totals, and cells by operator x modifier, operator x holder form, follow-up x holder form."""
    out = {}
    for code in sorted({r["language"] for r in rows}):
        mine = [r for r in rows if r["language"] == code]
        scored = [r for r in mine if r["bucket"] != "blocked"]
        total = Counter(r["bucket"] for r in mine)
        views = {}
        for name, keyf in (("operator_x_modifier", lambda r: "%s | %s" % (r["op"], r["mod"])),
                           ("operator_x_holder", lambda r: "%s | %s" % (r["op"], r["form"])),
                           ("follow_up_x_holder", lambda r: "%s | %s" % (r["follow"], r["form"]))):
            table = defaultdict(Counter)
            for r in mine:
                if name != "operator_x_modifier" or r["follow"] == "base":
                    if name == "operator_x_holder" and r["follow"] != "base":
                        continue
                    table[keyf(r)][r["bucket"]] += 1
            views[name] = {k: dict(v) for k, v in sorted(table.items())}
        out[code] = {"cells": len(mine), "scored": len(scored), "buckets": dict(total),
                     "correct_rate": round(total["correct"] / len(scored), 4) if scored else None,
                     **views}
    return out


def format_tables(result, detail=False):
    lines = []
    for code, t in result.items():
        b = t["buckets"]
        lines.append("%s  cells %d  correct %d  hold %d  wrong %d  blocked %d  error %d  -> %.1f%% of scored %d" % (
            code, t["cells"], b.get("correct", 0), b.get("hold", 0), b.get("wrong", 0), b.get("blocked", 0),
            b.get("error", 0), 100.0 * (t["correct_rate"] or 0), t["scored"]))
        views = ("operator_x_modifier", "operator_x_holder", "follow_up_x_holder") if detail else ("operator_x_holder",
                                                                                                  "follow_up_x_holder")
        for view in views:
            lines.append("  %s" % view)
            for key, c in t[view].items():
                n = sum(c.values())
                lines.append("    %-32s %3d/%-3d%s" % (key, c.get("correct", 0), n,
                                                       "  wrong %d" % c["wrong"] if c.get("wrong") else ""))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--language", choices=("ko", "en"), action="append")
    parser.add_argument("--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 1)))
    parser.add_argument("--out", type=Path, help="write the rows and tables as JSON")
    parser.add_argument("--cells", action="store_true", help="print operator x modifier too, and every failing cell")
    parser.add_argument("--list", action="store_true", help="print the cells and their turns, run nothing")
    parser.add_argument("--effort", type=int, choices=(0, 1, 2, 3),
                        help="the reasoning context's effort budget (MARCO_EFFORT); default: the context's own")
    args = parser.parse_args(argv)
    codes = args.language or ["ko", "en"]
    if args.list:
        for code in codes:
            for d in dialogues(code):
                print(d["cell"], "|", " / ".join(t["say"] for t in d["turns"][d["n_state"]:]), "|",
                      json.dumps(d["expect"], ensure_ascii=False))
        return 0
    rows = run(codes, args.jobs, args.effort)
    result = tables(rows)
    print(format_tables(result, detail=args.cells))
    if args.cells:
        for r in rows:
            if r["bucket"] not in ("correct",):
                print("  %-6s %-3s %-40s %s -> %s" % (r["bucket"], r["language"], r["cell"][:40],
                                                     " / ".join(r["asked"]), r["answer"][:90]))
    if args.out:
        args.out.write_text(json.dumps({"tables": result, "rows": rows}, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    wrong = sum(t["buckets"].get("wrong", 0) for t in result.values())
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
