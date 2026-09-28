"""Open-vocabulary probe (goal G3.1): words from public word lists, never from a dialogue set.

Sources, all read from local copies; no word here is typed by hand:

* Item and place nouns: 국립국어원 「한국어기초사전」 (krdict), the XML export
  ``krdict_*.xml`` (CC BY-SA 2.0 KR; the copy the repository's ``dict_extract.py``
  reads from ``data/사전/``, redistributed by spellcheck-ko/korean-dict-nikl).
  A noun is taken when its entry is a 명사 whose ``semanticCategory`` is one of
  ``ITEM_CATEGORIES`` (items) or ``PLACE_CATEGORIES`` (places), and whose first
  sense has an English equivalent that is one lowercase word listed in Webster's
  Second International (``/usr/share/dict/web2``, public domain). The Korean
  lemma is the Korean word; that English equivalent is the English word.
* English given names: ``/usr/share/dict/propernames`` (BSD dict, public
  domain), one capitalised word of 3 to 8 letters that is not also a
  lowercase word of web2.
* Korean given names: the full names in the proper-noun lexicon of Kiwi
  (``kiwipiepy_model`` 0.22.1, ``default.dict``, LGPL-3.0) written as a surname
  and a two-syllable given name. A given name is taken when it follows at least
  five of the ten most common surnames (통계청 2015 인구주택총조사:
  ``SURNAMES``) -- a given name, not one family -- and is not a krdict headword.

A word that already appears in a language pack (``styles/*.json``) or in the
seen development sets (``dialogues_dev``, ``dialogues_dev2``) is left out: the probe
measures words the rules never met. The frozen set is not read.

Each word is used in one statement and one question in each language by the
grammar below. Items and places are said in their own language (the Korean
lemma in Korean, its English equivalent in English); every name is said in both
(an English name in Latin letters inside Korean text; a Korean name in Korean,
and in its Revised Romanization in English). The holder of an item and the
thing of a place are fixed, so a failure is the probe word's.

    python data/benchmarks/vocab_probe/build.py --dict <folder with krdict_*.xml>
    python data/benchmarks/vocab_probe/build.py --check      # rebuild from words.json, compare
"""
import argparse
import glob
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SEED = 20260924
WEB2 = Path("/usr/share/dict/web2")
PROPERNAMES = Path("/usr/share/dict/propernames")
ITEM_CATEGORIES = ["주생활 > 생활 용품", "식생활 > 조리 도구", "교육 > 학습 관련 사물", "삶 > 여가 도구",
                   "의생활 > 옷 종류", "의생활 > 모자, 신발, 장신구", "동식물 > 동물류", "식생활 > 식재료",
                   "사회 생활 > 교통 수단", "동식물 > 식물류"]
PLACE_CATEGORIES = ["경제 생활 > 경제 행위 장소", "삶 > 여가 시설", "사회 생활 > 교통 이용 장소",
                    "정치와 행정 > 공공 기관", "주생활 > 건물 종류", "교육 > 교육 기관", "교육 > 학교 시설",
                    "삶 > 치료 시설", "식생활 > 식생활 관련 장소", "문화 > 문화 생활 장소",
                    "종교 > 종교 활동 장소", "주생활 > 주거 지역"]
# Korean counter the grammar uses for a category; anything else is counted with 개.
COUNTERS = {"동식물 > 동물류": "마리", "의생활 > 옷 종류": "벌", "사회 생활 > 교통 수단": "대"}
WANT = {"items": 300, "places": 100, "names_en": 100, "names_ko": 100}
SURNAMES = "김이박최정강조윤장임"
SEEN = ["styles", "data/benchmarks/dialogues_dev", "data/benchmarks/dialogues_dev2"]


# ---------------------------------------------------------------------------
# reading the sources
# ---------------------------------------------------------------------------
def _entries(folder):
    for path in sorted(glob.glob(str(Path(folder) / "krdict_*.xml"))):
        text = Path(path).read_text(encoding="utf-8")
        for entry in re.findall(r"<LexicalEntry.*?</LexicalEntry>", text, re.S):
            yield entry


def _feat(entry, name):
    found = re.search(r'att="%s" val="([^"]*)"' % re.escape(name), entry)
    return found.group(1) if found else None


def _english(entry):
    """The first sense's English equivalent: its first comma- or semicolon-separated word."""
    sense = re.search(r"<Sense .*?</Sense>", entry, re.S)
    if not sense:
        return None
    for block in re.findall(r"<Equivalent>.*?</Equivalent>", sense.group(0), re.S):
        if _feat(block, "language") == "영어":
            lemma = (_feat(block, "lemma") or "").strip()
            return re.split(r"[,;/(]", lemma)[0].strip() or None
    return None


def read_krdict(folder):
    headwords, nouns = set(), []
    for entry in _entries(folder):
        lemma = re.search(r'<Lemma>\s*<feat att="writtenForm" val="([^"]+)"', entry)
        if not lemma:
            continue
        word = lemma.group(1)
        headwords.add(word)
        if _feat(entry, "partOfSpeech") != "명사":
            continue
        nouns.append({"ko": word, "category": _feat(entry, "semanticCategory"),
                      "level": _feat(entry, "vocabularyLevel"), "en": _english(entry)})
    return headwords, nouns


def korean_names(headwords):
    import kiwipiepy_model
    lexicon = Path(kiwipiepy_model.__file__).resolve().parent / "default.dict"
    surnames = {}
    for line in lexicon.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if line.startswith("#") or len(parts) < 2 or parts[1] != "NNP":
            continue
        if re.fullmatch(r"[가-힣]{3}", parts[0]) and parts[0][0] in SURNAMES:
            surnames.setdefault(parts[0][1:], set()).add(parts[0][0])
    return sorted(name for name, seen in surnames.items() if len(seen) >= 5 and name not in headwords)


def seen_text():
    parts = []
    for top in SEEN:
        for path in sorted((ROOT / top).rglob("*.json")):
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _seen_word(word, text, korean):
    if korean:
        # a Korean word stands at the start of a word, a particle may follow it
        return re.search(r"(?<![가-힣])%s" % re.escape(word), text) is not None
    return re.search(r"(?<![A-Za-z])%s(?:s|es)?(?![A-Za-z])" % re.escape(word), text, re.I) is not None


def select(folder):
    web2 = set(WEB2.read_text(encoding="utf-8").split())
    lower = {w for w in web2 if w.islower()}
    headwords, nouns = read_krdict(folder)
    seen = seen_text()
    rng = random.Random(SEED)

    def usable(row):
        return (row["en"] and re.fullmatch(r"[a-z]{3,12}", row["en"]) and row["en"] in lower
                and re.fullmatch(r"[가-힣]{1,4}", row["ko"])
                and not _seen_word(row["ko"], seen, True) and not _seen_word(row["en"], seen, False))

    def take(categories, want, used_en, used_ko):
        rows = [row for row in nouns if row["category"] in categories and usable(row)]
        # everyday words first: 초급, then 중급, then the rest
        rank = {"초급": 0, "중급": 1}
        rows.sort(key=lambda row: (rank.get(row["level"], 2), row["ko"]))
        out = []
        for row in rows:
            if row["en"] in used_en or row["ko"] in used_ko:
                continue
            used_en.add(row["en"])
            used_ko.add(row["ko"])
            out.append({"ko": row["ko"], "en": row["en"], "category": row["category"], "level": row["level"]})
            if len(out) == want:
                break
        return out
    used_en, used_ko = set(), set()
    places = take(PLACE_CATEGORIES, WANT["places"], used_en, used_ko)
    items = take(ITEM_CATEGORIES, WANT["items"], used_en, used_ko)
    for row in items:
        row["counter"] = COUNTERS.get(row["category"], "개")
    english = [w for w in PROPERNAMES.read_text(encoding="utf-8").split()
               if re.fullmatch(r"[A-Z][a-z]{2,7}", w) and w.lower() not in lower
               and not _seen_word(w, seen, False)]
    korean = [w for w in korean_names(headwords) if not _seen_word(w, seen, True)]
    rng.shuffle(english)
    rng.shuffle(korean)
    return {"items": items, "places": places,
            "names": [{"name": w, "script": "latin"} for w in sorted(english[:WANT["names_en"]])]
            + [{"name": w, "script": "hangul"} for w in sorted(korean[:WANT["names_ko"]])]}


# ---------------------------------------------------------------------------
# the generator: one statement and one question per word and language
# ---------------------------------------------------------------------------
_IRREGULAR = {"man": "men", "woman": "women", "child": "children", "tooth": "teeth", "foot": "feet",
              "goose": "geese", "mouse": "mice", "person": "people", "ox": "oxen", "sheep": "sheep",
              "deer": "deer", "fish": "fish", "knife": "knives", "wife": "wives", "life": "lives",
              "leaf": "leaves", "loaf": "loaves", "wolf": "wolves", "calf": "calves", "half": "halves",
              "shelf": "shelves", "thief": "thieves", "scarf": "scarves", "potato": "potatoes",
              "tomato": "tomatoes", "hero": "heroes", "echo": "echoes", "mango": "mangoes"}


def plural(word):
    """English plural by the ordinary spelling rules (the generator's own table)."""
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if re.search(r"(s|x|z|ch|sh)$", word):
        return word + "es"
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    return word + "s"


def _batchim(word):
    ch = word[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28
    return 0 if ch.lower() in "aeiouy" else 1


def _p(word, pair):
    return word + (pair[0] if _batchim(word) else pair[1])


def _ro(word):
    """(으)로: 로 after a vowel or ㄹ."""
    b = _batchim(word)
    return word + ("로" if b in (0, 8) else "으로")


def _en_amount(n, word):
    return "%d %s" % (n, word if n == 1 else plural(word))


def _romanized(name):
    from marco.language.hangul import romanize
    table = json.loads((ROOT / "styles/한국어.json").read_text(encoding="utf-8"))["로마자"]
    spelled = romanize(name, table)
    return spelled[:1].upper() + spelled[1:] if spelled else None


_NATIVE = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉"}
_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def _ko_amount(n, counter, native):
    return "%s %s" % (_NATIVE[n], counter) if native else "%d%s" % (n, counter)


def _en_number(n, words):
    return _WORDS[n] if words else str(n)


def pairs(words):
    """Every probe case: {kind, word, language, frame, statement, question, expect}.

    A word's frame is chosen by its position in its list, so every declared
    statement frame below meets a share of the words: possession verbs and
    tenses, the genitive and dative owner, a second holder after the first
    (the item left to the first clause), digits and numeral words, and each
    question form of the frame.
    """
    out = []

    def add(kind, word, language, frame, statement, question, expect):
        out.append({"kind": kind, "word": word, "language": language, "frame": frame,
                    "statement": statement, "question": question, "expect": expect})
    for i, row in enumerate(words["items"]):
        n = 1 if i % 5 == 0 else 2 + i % 8
        m = 9 if n != 9 else 8
        en, many, num = row["en"], plural(row["en"]), _en_number(n, (i // 6) % 2)
        amount = "%s %s" % (num, en if n == 1 else many)
        frame = i % 6
        if frame == 0:
            add("item", en, "en", "has", "Haru has %s." % amount, "How many %s does Haru have?" % many, {"count": n})
        elif frame == 1:
            add("item", en, "en", "had", "Haru had %s." % amount, "How many %s does Haru have now?" % many,
                {"count": n})
        elif frame == 2:
            add("item", en, "en", "owns", "Haru owns %s." % amount, "How many %s has Haru got?" % many, {"count": n})
        elif frame == 3:
            add("item", en, "en", "holding", "Haru is holding %s." % amount,
                "How many %s does Haru have left?" % many, {"count": n})
        elif frame == 4:
            add("item", en, "en", "second_holder", "Moru has %d %s and Haru has %s." % (m, many, num),
                "How many %s does Haru have?" % many, {"count": n})
        else:
            add("item", en, "en", "there_are", "There are %s." % amount, "How many %s are there?" % many,
                {"count": n})
        ko, c = row["ko"], row["counter"]
        amount = _ko_amount(n, c, (i // 6) % 2)
        subj, obj, top = _p(ko, ("이", "가")), _p(ko, ("을", "를")), _p(ko, ("은", "는"))
        if frame == 0:
            add("item", ko, "ko", "existential", "하루는 %s %s 있어." % (subj, amount),
                "하루는 %s 몇 %s 있어?" % (subj, c), {"count": n})
        elif frame == 1:
            add("item", ko, "ko", "possessive_verb", "하루는 %s %s 가지고 있어." % (ko, _p(amount, ("을", "를"))),
                "하루는 %s 몇 %s 가지고 있어?" % (obj, c), {"count": n})
        elif frame == 2:
            add("item", ko, "ko", "genitive_copula", "하루의 %s %s." % (top, _copula(amount)),
                "하루의 %s 몇 %s?" % (top, _copula(c)), {"count": n})
        elif frame == 3:
            add("item", ko, "ko", "dative", "하루한테는 %s %s 있어요." % (subj, amount),
                "하루한테 %s 몇 %s 남았어요?" % (subj, c), {"count": n})
        elif frame == 4:
            add("item", ko, "ko", "second_holder", "모래는 %s %s, 하루는 %s 있어." % (subj, _ko_amount(m, c, False), amount),
                "하루는 %s 몇 %s 있어?" % (subj, c), {"count": n})
        else:
            add("item", ko, "ko", "topic_count", "%s %s 있다." % (top, amount), "%s 몇 %s 남았어?" % (top, c),
                {"count": n})
    for i, row in enumerate(words["places"]):
        frame = i % 3
        en, ko = row["en"], row["ko"]
        if frame == 0:
            add("place", en, "en", "moved", "Haru moved the pencil to the %s." % en, "Where is the pencil now?",
                {"place": en})
            add("place", ko, "ko", "moved", "하루가 연필을 %s 옮겼어." % _ro(ko), "지금 연필은 어디에 있어?", {"place": ko})
        elif frame == 1:
            add("place", en, "en", "thing_in", "The pencil is in the %s." % en, "Where is the pencil?", {"place": en})
            add("place", ko, "ko", "thing_in", "연필은 %s에 있어." % ko, "연필은 어디에 있어?", {"place": ko})
        else:
            add("place", en, "en", "person_in", "Haru is in the %s." % en, "Where is Haru?", {"place": en})
            add("place", ko, "ko", "person_in", "하루는 %s에 있어." % ko, "하루는 어디에 있어?", {"place": ko})
    for i, row in enumerate(words["names"]):
        n = 2 + i % 8
        m = 9 if n != 9 else 8
        name = row["name"]
        english = name if row["script"] == "latin" else _romanized(name)
        frame = i % 4
        if frame == 0:
            add("name", name, "en", "has", "%s has %d pencils." % (english, n),
                "How many pencils does %s have?" % english, {"count": n})
        elif frame == 1:
            add("name", name, "en", "had", "%s had %s pencils." % (english, _WORDS[n]),
                "How many pencils does %s have now?" % english, {"count": n})
        elif frame == 2:
            add("name", name, "en", "first_holder", "%s has %d pencils and Moru has %d." % (english, n, m),
                "How many pencils does %s have?" % english, {"count": n})
        else:
            add("name", name, "en", "second_holder", "Moru has %d pencils and %s has %d." % (m, english, n),
                "How many pencils does %s have?" % english, {"count": n})
        called = name + "이" if row["script"] == "hangul" and _batchim(name) and frame in (1, 2) else name
        if frame == 0:
            add("name", name, "ko", "topic", "%s 연필이 %d자루 있어." % (_p(called, ("은", "는")), n),
                "%s 연필이 몇 자루 있어?" % _p(called, ("은", "는")), {"count": n})
        elif frame == 1:
            add("name", name, "ko", "suffixed_topic", "%s 연필이 %s 있어." % (_p(called, ("은", "는")),
                                                                         _ko_amount(n, "자루", True)),
                "%s 연필 몇 자루야?" % _p(called, ("은", "는")), {"count": n})
        elif frame == 2:
            add("name", name, "ko", "subject_possessive", "%s 연필을 %d자루 가지고 있어." % (_p(called, ("이", "가")), n),
                "%s 연필이 몇 자루 있어?" % _p(called, ("은", "는")), {"count": n})
        else:
            add("name", name, "ko", "dative", "%s한테는 연필이 %d자루 있어요." % (called, n),
                "%s한테 연필이 몇 자루 있어요?" % called, {"count": n})
    return out


def _copula(word):
    """Casual copula after a noun phrase: 세 개야 / 세 권이야."""
    return word + ("이야" if _batchim(word) else "야")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dict", help="folder with krdict_*.xml")
    parser.add_argument("--check", action="store_true", help="regenerate probe.json from words.json and compare")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    if args.check:
        words = json.loads((HERE / "words.json").read_text(encoding="utf-8"))
        same = json.loads((HERE / "probe.json").read_text(encoding="utf-8"))["cases"] == pairs(words)
        print("probe.json matches words.json:", same)
        return 0 if same else 1
    if not args.dict:
        parser.error("--dict is required to select words")
    words = select(args.dict)
    words = {"sources": {
        "items_places": "국립국어원 한국어기초사전 (krdict) XML export, CC BY-SA 2.0 KR; English: the first "
                        "sense's English equivalent, checked against Webster's Second International (web2)",
        "names_en": "/usr/share/dict/propernames (BSD dict, public domain)",
        "names_ko": "Kiwi (kiwipiepy_model 0.22.1) default.dict proper nouns: surname + given name, "
                    "given names following at least five of the ten most common surnames",
        "seed": SEED, "item_categories": ITEM_CATEGORIES, "place_categories": PLACE_CATEGORIES},
        **words}
    (HERE / "words.json").write_text(json.dumps(words, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    cases = pairs(words)
    (HERE / "probe.json").write_text(json.dumps({"seed": SEED, "cases": cases}, ensure_ascii=False, indent=1)
                                     + "\n", encoding="utf-8")
    counts = {key: len(words[key]) for key in ("items", "places", "names")}
    print("words", counts, "latin names", sum(r["script"] == "latin" for r in words["names"]),
          "hangul names", sum(r["script"] == "hangul" for r in words["names"]), "cases", len(cases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
