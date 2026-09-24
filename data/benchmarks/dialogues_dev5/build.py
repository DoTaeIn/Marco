"""Development set v5 (goal G5.1): round 4's generator around round 4's blocking classes, with surface variation.

The truth is a scenario and the wording comes from the phrasing model, exactly as in v4
(``data/benchmarks/dialogues_dev4/build.py``, loaded here as a module and reused: its checker, its
prompts, its phrasing loop, its dialogue assembly). What is new:

* **Focus families** are the classes round 4's check half was blocked on (the freeze queue, G4 row):
  ``transfer_verbs`` weighted to send, give back, pass and receive; ``places`` (a place holds, gives
  and receives); ``relations`` (a holder said by a relation, named or not, or by a role); ``only``
  (only-quantities, with zero and vague-then-exact beside them); ``fronting``; ``question_forms``
  (with two forms v4 did not have: *still* and, in Korean, the relative 가진 / in English the echo
  question). Each dialogue has one primary family and two others; the class tags are v4's, so the
  cause tables read them the same way.
* **New vocabulary.** Names, items, places, relation words, roles and Korean job titles are tables of
  their own, disjoint from v4's and from the packs' declared example words, cut into disjoint build
  and check halves. The Korean job titles are eight titles v4 did not use (a closed class a reader
  declared in full reads them too).
* **Surface variation of the same scenario** (design note §18): for ``VARIED_PER_HALF`` scenarios per
  language and half, two more phrasings of the same scenario (same truth, same expectations), each a
  declared overlay of style features: variant 1 changes the register and the word order (a count or
  a receiver first, the thing as topic, a passive with *by*, another verb of having, another question
  form); variant 2 leaves out or pronominalises the subject a statement shares with the one before
  it, uses honorifics toward titled and elder holders (Korean), a particle-less question (Korean),
  and another question form. The three dialogues of one scenario are a triple (``triples.txt``).

Build and check halves come from different scenario seeds, disjoint vocabulary halves, and are phrased
at different sampling seeds; a variant is phrased at its own seeds (its scenario id differs).

    python data/benchmarks/dialogues_dev5/build.py scenarios             # scenarios.jsonl (no model; variants
                                                                         # are derived from it when loaded)
    python data/benchmarks/dialogues_dev5/build.py phrase --lang ko      # regular dialogues, then variants
    python data/benchmarks/dialogues_dev5/build.py assemble              # dev5_*.json, split.txt, triples.txt
    python data/benchmarks/dialogues_dev5/build.py coverage              # the class table, by scenario tags

The frozen exam sets are never read: the overlap check reads the tracked corpus files without them and
the earlier development sets (v4's ``corpus_files``); the owner runs the frozen overlap check.
"""
import argparse
import copy
import importlib.util
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
_spec = importlib.util.spec_from_file_location("dialogues_dev4_build", HERE.parent / "dialogues_dev4" / "build.py")
v4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v4)

SEED = 20260925
SCENARIO_SEEDS = {"build": 5507, "check": 9907}
SAMPLING = {"build": 2273, "check": 4441}
PER_HALF = 40               # regular dialogues per language per half: 160 in all
VARIED_PER_HALF = 10        # triples per language per half: 40 scenarios phrased three ways
SCENARIOS = HERE / "scenarios.jsonl"
LANGS = ("ko", "en")


def phrasings_path(lang):
    return HERE / ("phrasings_%s.jsonl" % lang)


# ---------------------------------------------------------------------------
# vocabulary: new tables, none in v4's and none a pack's declared example word
# ---------------------------------------------------------------------------
EN_GIVEN = {
    "f": ["Ava", "Emma", "Isabella", "Mia", "Amelia", "Harper", "Evelyn", "Ella", "Scarlett", "Lily", "Aria",
          "Zoey", "Riley", "Stella", "Ellie", "Audrey", "Claire", "Anna", "Caroline", "Aaliyah", "Allison",
          "Madelyn", "Sadie", "Naomi", "Alexa", "Eva", "Ariana", "Josephine", "Eliana", "Cora", "Lydia",
          "Margaret", "Diana", "Beth", "Cecilia", "Esther", "Gloria", "Judy", "Marian", "Sylvia", "Tina", "Vivian",
          "Yvonne", "Norma", "Doris", "Agnes"],
    "m": ["Oliver", "Elijah", "William", "Henry", "Alexander", "Sebastian", "Michael", "Logan", "Levi", "Wyatt",
          "Jayden", "Grayson", "Luke", "Dylan", "Anthony", "Lincoln", "Charles", "Christopher", "Joshua", "Andrew",
          "Julian", "Aiden", "Isaiah", "Nolan", "Adrian", "Cameron", "Connor", "Dominic", "Easton", "Jaxon",
          "Landon", "Nicholas", "Roman", "Silas", "Tyler", "Vincent", "Xavier", "Austin", "Calvin", "Dennis",
          "Edgar", "Harold", "Ivan", "Jerome", "Keith", "Lloyd", "Marcus", "Norman", "Otis", "Ralph", "Stanley",
          "Wesley"],
}
EN_SURNAMES = ["Chavez", "Bennett", "Mendoza", "Ruiz", "Hughes", "Alvarez", "Castillo", "Sanders", "Myers", "Ross",
               "Foster", "Jimenez", "Powell", "Jenkins", "Perry", "Russell", "Sullivan", "Coleman", "Henderson",
               "Gonzales", "Vasquez", "Simmons", "Romero", "Patterson", "Hamilton", "Graham", "Reynolds", "Griffin",
               "Wallace", "Moreno", "Bryant", "Herrera", "Gibson", "Ellis", "Tran", "Medina", "Aguilar", "Stevens",
               "Murray", "Castro", "Marshall", "Owens", "Harrison", "Fernandez", "Vargas", "Chen", "Freeman", "Webb",
               "Tucker", "Guzman", "Crawford", "Olson", "Simpson", "Mendez", "Silva", "Snyder", "Dixon", "Hicks",
               "Holmes", "Wagner", "Robertson", "Boyd", "Salazar", "Warren", "Meyer", "Schmidt", "Garza", "Ferguson"]
KO_GIVEN = {
    "f": ["지민", "수민", "예진", "지현", "민경", "혜진", "은비", "소희", "서영", "채린", "윤아", "하영", "가영", "예나",
          "주희", "보영", "선희", "은영", "정민", "효진", "은주", "지은", "민아", "채연", "수현", "은희", "미정", "영숙",
          "혜린", "슬기", "아영", "경희", "순자", "명희", "진아", "연희", "지선", "해진", "민주", "소영"],
    "m": ["민호", "동현", "준영", "성민", "현준", "지훈", "승현", "민성", "우현", "태현", "준혁", "상우", "재현", "동욱",
          "성훈", "영민", "창민", "재훈", "형준", "민재", "경수", "진혁", "용준", "승민", "태호", "규민", "원준", "대현",
          "인호", "정우", "석진", "현석", "종민", "광수", "대성", "윤호", "진수", "상민", "호준", "병철"],
}
KO_SURNAMES = ["성", "차", "민", "진", "엄", "채", "원", "방", "현", "함", "변", "염", "추", "석", "선", "설", "길", "연",
               "위", "표", "명", "왕", "금", "옥", "맹", "탁", "국", "봉", "편", "용"]
KO_JOB_TITLES = ["주임", "차장", "이사", "원장", "소장", "반장", "교수", "대표"]
EN_ITEMS = [("staplers", "stapler"), ("socks", "sock"), ("gloves", "glove"), ("hats", "hat"), ("scarves", "scarf"),
            ("jackets", "jacket"), ("boots", "boot"), ("sweaters", "sweater"), ("keys", "key"), ("locks", "lock"),
            ("pots", "pot"), ("pans", "pan"), ("forks", "fork"), ("napkins", "napkin"), ("sponges", "sponge"),
            ("brushes", "brush"), ("combs", "comb"), ("mirrors", "mirror"), ("clocks", "clock"),
            ("radios", "radio"), ("cameras", "camera"), ("cables", "cable"), ("drills", "drill"),
            ("screws", "screw"), ("bags", "bag"), ("plums", "plum"), ("bananas", "banana"), ("carrots", "carrot"),
            ("cucumbers", "cucumber"), ("peppers", "pepper"), ("melons", "melon"), ("pies", "pie"),
            ("cupcakes", "cupcake"), ("donuts", "donut"), ("pretzels", "pretzel"), ("crackers", "cracker"),
            ("puzzles", "puzzle"), ("dolls", "doll"), ("kites", "kite"), ("crayons", "crayon"), ("maps", "map"),
            ("posters", "poster"), ("calendars", "calendar"), ("stools", "stool"), ("benches", "bench"),
            ("shelves", "shelf"), ("sheets", "sheet"), ("quilts", "quilt"), ("hoses", "hose"), ("bricks", "brick"),
            ("tires", "tire"), ("erasers", "eraser"), ("notepads", "notepad"), ("vases", "vase"), ("trays", "tray"),
            ("teapots", "teapot"), ("kettles", "kettle"), ("ladles", "ladle"), ("whisks", "whisk"),
            ("aprons", "apron"), ("magnets", "magnet"), ("clips", "clip"), ("rackets", "racket"),
            ("frisbees", "frisbee"), ("skateboards", "skateboard"), ("sleds", "sled"), ("paddles", "paddle"),
            ("lunchboxes", "lunchbox")]
KO_ITEMS = [("가위", "개"), ("테이프", "개"), ("앨범", "권"), ("달력", "개"), ("액자", "개"), ("거울", "개"), ("시계", "개"),
            ("모자", "개"), ("목도리", "개"), ("조끼", "벌"), ("바지", "벌"), ("치마", "벌"), ("운동화", "켤레"),
            ("슬리퍼", "켤레"), ("냄비", "개"), ("프라이팬", "개"), ("도마", "개"), ("컵", "개"), ("쟁반", "개"),
            ("행주", "장"), ("앞치마", "장"), ("귤", "개"), ("참외", "개"), ("수박", "통"), ("포도", "송이"),
            ("바나나", "개"), ("키위", "개"), ("망고", "개"), ("고구마", "개"), ("옥수수", "개"), ("당근", "개"),
            ("오이", "개"), ("호박", "개"), ("떡", "개"), ("빵", "개"), ("케이크", "개"), ("초콜릿", "개"), ("사탕", "개"),
            ("주스", "병"), ("와인", "병"), ("인형", "개"), ("퍼즐", "개"), ("카드", "장"), ("사진", "장"),
            ("포스터", "장"), ("지도", "장"), ("쿠폰", "장"), ("지갑", "개"), ("열쇠", "개"), ("자물쇠", "개"),
            ("이어폰", "개"), ("마우스", "개"), ("키보드", "개"), ("모니터", "대"), ("프린터", "대"), ("카메라", "대"),
            ("라디오", "대"), ("청소기", "대"), ("양산", "개"), ("부채", "개")]
EN_PLACES = ["kitchen", "hallway", "laundry room", "guest room", "dining room", "living room", "conference room",
             "print room", "server room", "tool shed", "gift shop", "flower shop", "hardware store", "bookstore",
             "post office", "town hall", "fire station", "front desk", "back room", "coat room", "equipment room",
             "file room", "copy room", "tea room", "north depot", "south depot", "east depot", "west depot",
             "main office", "field house", "boat shed", "farm stand", "market stall", "bike shed", "guard booth",
             "school office", "waiting room", "dressing room", "prop room", "nursery"]
KO_PLACES = ["부엌", "거실", "안방", "작은방", "복도", "베란다", "옥상", "회의실", "인쇄실", "서버실", "자료실", "상담실",
             "원장실", "행정실", "꽃집", "철물점", "서점", "우체국", "구청", "소방서", "경비실", "주차장", "농장", "과수원",
             "학원", "대기실", "분장실", "준비실", "급식실", "보건실", "방송실", "옷방", "신발장", "사물함", "뒷방",
             "가게 창고", "교회", "성당", "체육 창고", "지하 주차장"]
EN_RELATIONS = [("boss", None), ("assistant", None), ("mentor", None), ("grandmother", "f"), ("grandfather", "m"),
                ("stepbrother", "m"), ("stepsister", "f"), ("daughter", "f"), ("son", "m"), ("wife", "f"),
                ("husband", "m"), ("girlfriend", "f"), ("boyfriend", "m"), ("housemate", None), ("colleague", None),
                ("supervisor", None), ("trainee", None), ("landlady", "f"), ("tenant", None), ("godson", "m")]
KO_RELATIONS = [("언니", "f"), ("누나", "f"), ("형", "m"), ("오빠", "m"), ("남편", "m"), ("아내", "f"), ("아들", "m"),
                ("딸", "f"), ("이모", "f"), ("삼촌", "m"), ("고모", "f"), ("할머니", "f"), ("할아버지", "m"), ("사위", "m"),
                ("며느리", "f"), ("제자", None), ("상사", None), ("손녀", "f"), ("손자", "m"), ("처제", "f")]
EN_ROLES = ["the plumber", "the mail carrier", "our tutor", "the florist", "the baker", "the guard",
            "the pharmacist", "the gardener", "the electrician", "the waiter", "the barista", "the usher"]
KO_ROLES = ["배달원", "정비사", "미용사", "약사", "정원사", "청소 담당", "교사", "강사", "비서", "매니저", "바리스타", "목수"]
# holders spoken of with honorifics in Korean (variant 2): titled and elder relations
KO_ELDERS = {"할머니", "할아버지", "이모", "삼촌", "고모"}
# the v4 tables, kept for the checker: a word of either set in a phrasing that its scenario lacks is refused
V4_TABLES = {name: getattr(v4, name) for name in ("EN_GIVEN", "EN_SURNAMES", "KO_GIVEN", "KO_SURNAMES", "EN_ITEMS",
                                                   "KO_ITEMS", "EN_PLACES", "KO_PLACES")}


def halves():
    """{"build"|"check": {lang: {table: [...]}}}: every v5 table cut in two by SEED."""
    rng = random.Random(SEED)
    tables = {
        "en": {"given_f": EN_GIVEN["f"], "given_m": EN_GIVEN["m"], "surnames": EN_SURNAMES,
               "items": EN_ITEMS, "places": EN_PLACES, "relations": EN_RELATIONS, "roles": EN_ROLES},
        "ko": {"given_f": KO_GIVEN["f"], "given_m": KO_GIVEN["m"], "surnames": KO_SURNAMES,
               "items": KO_ITEMS, "places": KO_PLACES, "relations": KO_RELATIONS, "roles": KO_ROLES,
               "job_titles": KO_JOB_TITLES},
    }
    out = {"build": {}, "check": {}}
    for lang, named in tables.items():
        for key, pool in named.items():
            pool = sorted(pool, key=lambda x: json.dumps(x, ensure_ascii=False))
            rng.shuffle(pool)
            cut = len(pool) // 2
            if key == "job_titles":          # a closed class of eight: both halves keep all
                out["build"].setdefault(lang, {})[key] = list(pool)
                out["check"].setdefault(lang, {})[key] = list(pool)
                continue
            out["build"].setdefault(lang, {})[key] = pool[:cut]
            out["check"].setdefault(lang, {})[key] = pool[cut:]
    return out


def use_v5_tables():
    """Point the v4 module at v5's tables and files (its functions read them as module globals)."""
    v4.EN_GIVEN, v4.EN_SURNAMES, v4.KO_GIVEN, v4.KO_SURNAMES = EN_GIVEN, EN_SURNAMES, KO_GIVEN, KO_SURNAMES
    v4.EN_ITEMS, v4.KO_ITEMS, v4.EN_PLACES, v4.KO_PLACES = EN_ITEMS, KO_ITEMS, EN_PLACES, KO_PLACES
    v4.KO_JOB_TITLES = KO_JOB_TITLES
    v4.SCENARIOS, v4.SAMPLING = SCENARIOS, SAMPLING
    v4.RESEEDED = HERE / "reseeded.txt"
    v4.PER_HALF = PER_HALF
    v4.halves = halves


# ---------------------------------------------------------------------------
# families and their v4 classes
# ---------------------------------------------------------------------------
FAMILIES = ("transfer_verbs", "places", "relations", "only", "fronting", "question_forms")
# the v5 family a v4 class tag counts under (coverage)
FAMILY_OF = {"transfer_verbs": "transfer_verbs", "holders:place": "places", "holders:relation": "relations",
             "holders:relation_unnamed": "relations", "holders:apposition": "relations",
             "zero_vague:only": "only", "fronting": "fronting", "question_forms": "question_forms"}
# the blocking verbs of round 4 weighted three to one (send 10, give back 7, pass 6, receive 6 of 34)
EN_TRANSFER5 = ("send", "send", "send", "give_back", "give_back", "give_back", "pass", "pass", "pass", "receive",
                "receive", "receive", "lend", "hand_over", "borrow", "transfer")
KO_TRANSFER5 = ("send", "send", "send", "give_back", "give_back", "give_back", "pass", "pass", "pass", "receive",
                "receive", "receive", "lend", "hand_over", "borrow")


TRANSFER_CLASS_VERBS = {"lend", "pass", "hand_over", "give_back", "send", "transfer", "borrow", "receive",
                        "leave_at", "move", "move_passive", "take_from"}


def families_of(classes):
    """The v5 families a dialogue's class tags show (transfer verbs: a verb of giving or taking other than give;
    a verb of having or using is not one)."""
    out = set()
    for c in classes:
        head, _, arg = c.partition(":")
        if head == "transfer_verbs":
            if arg in TRANSFER_CLASS_VERBS:
                out.add("transfer_verbs")
            continue
        for key, family in FAMILY_OF.items():
            if c == key or head == key:
                out.add(family)
    return out


# ---------------------------------------------------------------------------
# new style features (notes and shapes for the phrasing model; cues for the checker)
# ---------------------------------------------------------------------------
NEW_FEATURES = {
    "en": {
        "only": ("say this is the only thing the holder has, with the number",
                 ["(holder) only has (things), N of them.", "All (holder) has is N (things).",
                  "(holder) has just N (things), nothing else.", "The only thing (holder) has is (things), N of them."]),
        "q_still": ("ask how many the holder still has", ["How many (things) does (holder) still have?"]),
        "q_echo": ("an echo question: the holder first, then 'how many'", ["(holder) has how many (things) now?"]),
        "passive_by": ("passive: the things were given (with the given verb) to the receiver by the giver",
                       ["N (things) were (verb) to (receiver) by (giver)."]),
        "pronoun_subject": ("the giver was just mentioned: start with 'She' or 'He' for the giver, not the name",
                            ["She (verb) N (things) to (receiver).", "He (verb) (receiver) N (things)."]),
        "pronoun_taker": ("the receiver was just mentioned: start with 'She' or 'He' for the receiver, not the name",
                          ["She (verb) N (things) from (giver)."]),
    },
    "ko": {
        "only": ("그 물건만 있다고, 수량과 함께", ["(누구)은 (물건)만 N개 있어요.", "(누구)은 (물건)이 N개밖에 없어요.",
                                            "(누구)한테는 (물건) N개뿐이에요."]),
        "q_still": ("'아직'으로 묻기", ["(누구)은 아직 (물건)이 몇 개 있어요?"]),
        "q_relative": ("'가진'으로 묻기", ["(누구)이 가진 (물건)은 몇 개예요?", "(누구)이 가지고 있는 (물건)은 지금 몇 개예요?"]),
        "q_bare": ("조사 없이 짧게 묻기", ["(누구) (물건) 몇 개 있어요?"]),
        "has_dative_topic": ("가진 사람을 -한테는 으로 문장 앞에", ["(누구)한테는 (물건)이 N개 있어요."]),
        "object_topic": ("물건을 문장 맨 앞에 두고 가진 사람을 그 뒤에", ["(물건)은 (누구)이 N개 가지고 있어요."]),
        "dative_ege": ("받는 사람에 -에게를 붙여서", []),
        "omit_subject": ("앞 문장의 사람이 주어이니 주어는 말하지 않고 이어서", ["그리고 (받는 사람)한테 (물건) N개를 (동사)."]),
        "omit_taker": ("앞 문장의 사람이 받은 쪽이니 주어는 말하지 않고 이어서", ["그리고 (주는 사람)한테서 (물건) N개를 (동사)."]),
        "honorific": ("높임말로: 호칭이 붙은 사람이나 윗사람이 받으면 -께 ...드렸어요, 그분이 주어면 -께서 ...셨어요, "
                      "그분에 대해 물을 때는 ...가지고 계세요?", []),
    },
}
NEW_CUES = {
    "en": {"q_still": r"\bstill\b", "q_echo": r"\b(?:has|have|holds?|got)\s+how many\b",
           "passive_by": r"\b(?:was|were)\s+\w+(?:\s+\w+)?\s.*\bby\b", "only": r"\bonly\b|\ball (?:\w+ )?(?:has|have|had|got)\b|\bjust\b|\bnothing else\b"},
    "ko": {"q_still": r"아직|여전히", "q_relative": r"가진|갖고 있는|가지고 있는", "dative_ege": r"에게",
           "honorific": r"께|드렸|드려|드립|셨|시었|계세|계십|으세요|세요\?|십니까|시나요",
           "only": r"만\s|만$|만[이가을를은는도]|밖에|뿐",
           "count_first": r"^\s*(?:[가-힣]+\s)?(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열[가-힣]*|스무|스물[가-힣]*)\s?"
                          r"(?:개|자루|장|권|병|켤레|대|벌|묶음|통|송이)"},
}


_ORIGINAL_PHRASER = v4.Phraser
_MODEL = []


def _one_phraser():
    """The phrasing model, loaded once per process (v4's phrase loop asks for it on every call)."""
    if not _MODEL:
        _MODEL.append(_ORIGINAL_PHRASER())
    return _MODEL[0]


def load_all():
    """The regular scenarios of scenarios.jsonl and, derived from each, its two variants (not stored: a variant is
    a function of its base)."""
    out = []
    for line in SCENARIOS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            base = json.loads(line)
            out += [base, variant(base, 1), variant(base, 2)]
    return out


def install_features():
    v4.load_scenarios = load_all
    v4.Phraser = _one_phraser
    for lang in LANGS:
        v4.FEATURES[lang].update(NEW_FEATURES[lang])
    v4.EN_CUES.update(NEW_CUES["en"])
    v4.KO_CUES.update(NEW_CUES["ko"])
    v4.PATTERN_WORDS["en"] = list(v4.PATTERN_WORDS["en"])
    v4.PATTERN_WORDS["ko"] = list(v4.PATTERN_WORDS["ko"])


class Checker5(v4.Checker):
    """v4's checker, knowing v4's words too (a v4 name in a v5 phrasing is a word its scenario lacks), with two
    cue kinds of the variants: the thing said before its holder, and a question with no particle after the
    holder."""

    def __init__(self):
        super().__init__()
        for lang, given, surnames, items, places in (
                ("en", V4_TABLES["EN_GIVEN"], V4_TABLES["EN_SURNAMES"], V4_TABLES["EN_ITEMS"], V4_TABLES["EN_PLACES"]),
                ("ko", V4_TABLES["KO_GIVEN"], V4_TABLES["KO_SURNAMES"], V4_TABLES["KO_ITEMS"],
                 V4_TABLES["KO_PLACES"])):
            pool = self.pools[lang]
            pool["names"] |= set(given["f"]) | set(given["m"])
            if lang == "en":
                pool["names"] |= set(surnames)
                pool["items"] |= {w for pair in items for w in pair}
            else:
                pool["items"] |= {noun for noun, _c in items}
            pool["places"] |= set(places)

    def check(self, scn, turn, text, said=()):
        ok, reason = super().check(scn, turn, text, said)
        if not ok:
            return ok, reason
        spec = turn["check"]
        item = next((i for i in scn["items"] if i["key"] == spec.get("item")), None)
        for cue in spec.get("order_cues") or []:
            kind, _, token = cue.partition(":")
            if item is None or scn["language"] != "ko":
                continue
            at_item, at_holder = text.find(item["noun"]), text.find(token)
            if kind == "item_first" and not (0 <= at_item < at_holder):
                return False, "cue:item_first"
            if kind == "bare" and not v4.re.search(v4.re.escape(token) + r"(?:\s?(?:씨|님))?\s" + v4.re.escape(
                    item["noun"]), text):
                return False, "cue:bare"
        return True, "ok"


# ---------------------------------------------------------------------------
# the scenario
# ---------------------------------------------------------------------------
class Planner5(v4.Planner):
    def __init__(self, lang, half, index, vocab, focus5, rng):
        self.focus5 = set(focus5)
        focus = set()
        for family in focus5:
            focus |= {"transfer_verbs": {"transfer_verbs"}, "places": {"holders"}, "relations": {"holders"},
                      "only": {"zero_vague"}, "fronting": {"fronting"},
                      "question_forms": {"question_forms"}}[family]
        super().__init__(lang, half, index, vocab, focus, rng)

    def cast(self):
        """Two or three holders: a place (and often a second) when the family is places; a relation, a role or an
        unnamed relation when it is relations; at least one person."""
        rng, f5 = self.rng, self.focus5
        kinds = []
        if "places" in f5:
            kinds.append("place")
            if rng.random() < 0.5:
                kinds.append("place")
        if "relations" in f5:
            kinds.append(rng.choice(["relation", "relation", "relation_unnamed", "relation_unnamed", "apposition"]))
        n = 3 if rng.random() < 0.35 else 2
        while len(kinds) < n:
            k = rng.choice(["name", "name", "name", "title", "relation", "first_person", "relation_unnamed",
                            "apposition", "place"])
            if k in ("first_person", "relation_unnamed") and k in kinds:
                continue
            if k == "place" and kinds.count("place") >= 2:
                continue
            kinds.append(k)
        if all(k == "place" for k in kinds):
            kinds.append("name")
        rng.shuffle(kinds)
        holders = []
        for i, k in enumerate(kinds):
            anchor = None
            if k == "relation" and holders and rng.random() < 0.5:
                named_h = [h for h in holders if h.kind in ("name", "title")]
                anchor = named_h[0] if named_h else None
            holders.append(self.holder("ABCDE"[i], k, anchor))
        return holders


def scenario5(lang, half, index, vocab):
    rng = random.Random("%d/%s/%s/%d" % (SCENARIO_SEEDS[half], lang, half, index))
    primary = FAMILIES[index % len(FAMILIES)]
    focus5 = {primary} | set(rng.sample([f for f in FAMILIES if f != primary], 2))
    p = Planner5(lang, half, index, vocab, focus5, rng)
    try:
        ok = _plan5(p)
    except (KeyError, ValueError, IndexError) as exc:
        ok, p.error = False, str(exc)
    return p if ok else None


def _plan5(p):
    """v4's plan (``dialogues_dev4/build.py`` ``_plan``) with v5's weights: only-styles under ``only``, the
    blocking verbs under ``transfer_verbs``, the new question forms, no referent-repair flow."""
    rng, en, f, f5 = p.rng, p.lang == "en", p.focus, p.focus5
    cast = p.cast()
    x = p.item()
    y = p.item() if ("only" in f5 and rng.random() < 0.25) else None
    p.cast_list, p.items = cast, [i for i in (x, y) if i]

    def hclasses(h, first):
        if h.kind == "name":
            return []
        if h.kind in ("place", "first_person") or first:
            return ["holders:" + h.kind]
        return []

    def hcues(h, first):
        if h.cue == "first_person":
            return ["first_person"]
        if h.cue == "place":
            return ["place:" + h.entity]
        if first and h.cue == "title":
            return ["title:" + h.entity]
        if first and h.cue in ("relation", "role"):
            return ["%s:%s" % (h.cue, h.relation)]
        return []

    def anchors(h):
        return [c for c in cast if c.id == h.anchor]

    def hfeature(h, first):
        return {"title": "title", "relation": "relation", "relation_unnamed": "relation_unnamed",
                "apposition": "apposition", "first_person": "first_person"}.get(h.kind) if first else None

    def token(h):
        return h.tokens[0] if h.tokens else ("I" if en else "나")

    def spec(numbers=(), holders=(), item=None, anaphor=False, cues=(), allow=(), direction=None, absent=(),
             zero=False, question=False, may=(), **extra):
        out = {"numbers": sorted(set(numbers)), "names": [t for h in holders for t in h.tokens],
               "item": item["key"] if item else None, "anaphor": anaphor, "cues": sorted(set(cues)),
               "allow": sorted(set(allow)), "direction": direction, "absent": list(absent), "zero": zero,
               "question": question,
               "may": sorted({t for h in list(may) + [a for h in holders for a in anchors(h)] for t in h.tokens})}
        out.update(extra)
        return out

    # -- openings --------------------------------------------------------------------------------
    start = dict(zip([h.id for h in cast], rng.sample(range(3, 17), len(cast))))
    styles = {}
    for h in cast:
        options = ["plain"]
        if "only" in f5:
            options = ["only", "only", "only", "zero", "vague_exact", "plain"]
            if y is not None and h.kind != "place":
                options += ["also_some"]
        styles[h.id] = rng.choice(options)
    if "only" in f5 and not any(s == "only" for s in styles.values()):
        styles[rng.choice(cast).id] = "only"
    if all(s == "zero" for s in styles.values()):
        styles[cast[0].id] = "plain"
    vague = {}
    for h in cast:
        m = p.mention(h)
        n, s = start[h.id], styles[h.id]
        cls, cues = hclasses(h, m["first"]), hcues(h, m["first"])
        feats = [ft for ft in (hfeature(h, m["first"]),) if ft]
        verb = "place" if h.kind == "place" else (rng.choice(v4.HAS_VERBS[p.lang]) if s == "plain" else
                                                  v4.HAS_VERBS[p.lang][0])
        if h.kind == "place":
            feats.append("place_has")
        say = {"act": "state", "what": "has", "holder": m, "n": n, "item": x, "verb": verb, "mode": s,
               "features": feats}
        events = [{"type": "has", "holder": h.entity, "item": x["key"], "quantity": n}]
        numbers, zero = [n], False
        if s == "plain":
            if verb in v4.RARE_VERBS and "transfer_verbs" in f:
                cls.append("transfer_verbs:" + verb)
                feats.append(verb)
            if "fronting" in f and rng.random() < 0.3:
                feats.append("adv_moment")
                cls.append("fronting:adv_moment")
                cues.append("adv_moment")
        elif s == "only":
            feats.append("only"), cls.append("zero_vague:only"), cues.append("only")
        elif s == "zero":
            feats.append("zero"), cls.append("zero_vague:zero"), cues.append("zero")
            start[h.id], n, numbers, zero = 0, 0, [], True
            say["n"] = 0
            events[0]["quantity"] = 0
        elif s == "vague_exact":
            feats.append("vague_exact"), cls.append("zero_vague:vague_then_exact"), cues.append("vague")
        elif s == "also_some":
            feats.append("also_some"), cls.append("zero_vague:also_some"), cues.append("vague")
            say["item2"] = y
            events.append({"type": "has", "holder": h.entity, "item": y["key"], "quantity": None})
            vague[h.id] = y
        check = spec(numbers, [h], x, cues=cues, zero=zero)
        if s == "also_some":
            check["item2"] = y["key"]
        p.record(events, say, check, cls, ["ownership"])

    for hid, item in list(vague.items()):
        h = next(c for c in cast if c.id == hid)
        if rng.random() < 0.5:
            m = p.mention(h)
            p.other({"act": "hold", "entity": h.entity, "quantity": None, "relation": "count",
                     "evidence": {"turns": [len(p.turns) + 1]}, "item": item["key"]},
                    {"act": "ask", "what": "vague", "holder": m, "item": item, "features": []},
                    spec([], [h], item, question=True), ["zero_vague:vague_asked"], ["missing_premise"], "hold")

    def counted(h):
        return p.state.get((h.entity, x["key"])) is not None

    def fresh():
        return [h for h in cast if counted(h) and p.state.get((h.entity, x["key"])) not in (None, 0)
                and p.last_ask.get(h.entity, -1) < p.last_change.get(h.entity, 0)]

    def ask(h, form=None):
        p.last_ask[h.entity] = len(p.turns) + 1
        m = p.mention(h)
        e = p.answer_expect(h, x)
        if h.kind == "place":
            form = "q_place_now"
        if form is None:
            forms = ["q_plain", "q_plain", "q_left", "q_got" if en else "q_hold", "q_hold"]
            if "question_forms" in f5:
                forms = ["q_plain", "q_left", "q_got" if en else "q_hold", "q_hold", "q_still", "q_still",
                         "q_echo" if en else "q_relative", "q_echo" if en else "q_relative"]
            form = rng.choice(forms)
        cls = ["question_forms:" + form] if form != "q_plain" else []
        cues = {"q_got": ["q_got"], "q_left": ["q_left"], "q_hold": ["q_hold"], "q_still": ["q_still"],
                "q_echo": ["q_echo"], "q_relative": ["q_relative"], "q_place_now": ["place:" + h.entity]}.get(form, [])
        if h.kind in ("place", "first_person"):
            cls.append("holders:" + h.kind)
        if h.kind == "first_person":
            cues.append("first_person")
        return p.other(e, {"act": "ask", "what": "place" if h.kind == "place" else "count", "holder": m,
                           "item": x, "features": [form] if form != "q_plain" else []},
                       spec([], [h], x, cues=cues, question=True), cls, p.tags_for(h.entity), "answerable")

    def pick_verb(giver, taker):
        if giver.kind == "place" and taker.kind == "place":
            return rng.choice(["move", "move_passive"])
        if taker.kind == "place":
            return "leave_at"
        if giver.kind == "place":
            return "take_from"
        if "transfer_verbs" in f5:
            return rng.choice(EN_TRANSFER5 if en else KO_TRANSFER5)
        return rng.choice(v4.EN_TRANSFER if en else v4.KO_TRANSFER)

    def transfer(giver, taker, k, verb, feats):
        ev = {"type": "transfer", "from": giver.entity, "to": taker.entity, "item": x["key"], "quantity": k}
        mg, mt = p.mention(giver), p.mention(taker)
        cls = hclasses(giver, mg["first"]) + hclasses(taker, mt["first"])
        cues = hcues(giver, mg["first"]) + hcues(taker, mt["first"])
        features = [ft for ft in (hfeature(giver, mg["first"]), hfeature(taker, mt["first"])) if ft]
        if verb != "give":
            cls.append("transfer_verbs:" + verb)
            features.append(verb)
        anaphor = False
        for ft in feats:
            features.append(ft)
            if ft in ("front_recipient", "front_purpose", "front_then", "adv_apparently", "count_first"):
                cls.append("fronting:" + ft)
                cues.append(ft)
            elif ft in ("partitive", "same"):
                cls.append("partitives:" + ft)
                cues.append(ft)
                anaphor = anaphor or ft == "partitive"
        side = "take" if verb in ("borrow", "receive", "take_from") else "give"
        direction = {"giver": token(giver), "taker": token(taker), "giver_kind": giver.kind,
                     "taker_kind": taker.kind, "side": side, "verb": verb}
        return p.record([ev], {"act": "state", "what": "transfer", "giver": mg, "taker": mt, "n": k, "item": x,
                               "verb": verb, "features": features},
                        spec([k], [giver, taker], x, anaphor=anaphor, cues=cues, direction=direction), cls,
                        ["transfer"])

    last_event = None
    for step in range(rng.randint(1, 3)):
        givers = [h for h in cast if counted(h) and p.state[h.entity, x["key"]] >= 2]
        if not givers:
            break
        giver = rng.choice(givers)
        takers = [h for h in cast if h is not giver and counted(h)]
        if not takers:
            break
        zero = [h for h in takers if p.state.get((h.entity, x["key"])) == 0]
        taker = zero[0] if zero else rng.choice(takers)
        if rng.random() < 0.15 and step > 0 and giver.kind != "place":
            k = rng.randint(1, min(3, p.state[giver.entity, x["key"]] - 1))
            m = p.mention(giver)
            verb = rng.choice(v4.USE_VERBS)
            p.record([{"type": "use", "holder": giver.entity, "item": x["key"], "quantity": k}],
                     {"act": "state", "what": "use", "holder": m, "n": k, "item": x, "verb": verb,
                      "features": [verb]},
                     spec([k], [giver], x, cues=hcues(giver, m["first"])),
                     ["transfer_verbs:" + verb] + hclasses(giver, m["first"]), ["transfer"])
            last_event = None
        else:
            k = rng.randint(1, min(5, p.state[giver.entity, x["key"]] - 1))
            verb = pick_verb(giver, taker)
            feats = []
            if "fronting" in f5 and rng.random() < 0.75:
                ft = rng.choice(["front_recipient", "front_purpose", "front_then", "adv_apparently"]
                                + ([] if en else ["count_first", "count_first"]))
                if verb == "move_passive" or (ft == "front_recipient" and (
                        taker.kind == "place" or verb in ("borrow", "receive", "take_from"))) or (
                        ft == "count_first" and verb in ("move", "move_passive")):
                    ft = "front_then"
                feats.append(ft)
            last_event = transfer(giver, taker, k, verb, feats)
        for _ in range(rng.choice([1, 1, 2])):
            candidates = fresh()
            if not candidates:
                break
            moved = [h for h in candidates if p.last_change.get(h.entity) == len(p.turns) - (
                0 if p.turns[-1]["expect"]["act"] == "record" else 1)]
            h = rng.choice(moved if moved and rng.random() < 0.75 else candidates)
            ask(h)

    # -- a correction of the last transfer's amount, sometimes --------------------------------------
    if last_event is not None and rng.random() < 0.25:
        ev = p.by_turn[last_event][0]
        giver = next(h for h in cast if h.entity == ev["from"])
        taker = next(h for h in cast if h.entity == ev["to"])
        old = ev["quantity"]
        choices = [q for q in range(1, p.state[giver.entity, x["key"]] + old) if q != old]
        if choices:
            new = rng.choice(choices)
            p.state[giver.entity, x["key"]] += old - new
            p.state[taker.entity, x["key"]] -= old - new
            new_event = dict(ev, quantity=new)
            p.by_turn[last_event] = [new_event]
            p.correction = {"target": last_event, "field": "quantity", "old": old, "new": new, "event": ev}
            n = len(p.turns) + 1
            for key in (giver.entity, taker.entity):
                p.touched.setdefault(key, []).append(n)
                p.last_change[key] = n
            check = spec([new, old], [], None, anaphor=True, may=[giver, taker])
            check["contrast"] = {"new_number": new, "old_number": old}
            p.other({"act": "revise", "entity": None, "quantity": None, "relation": None,
                     "evidence": {"turns": [last_event, n]}, "target_turn": last_event, "replaces": [ev],
                     "with": [new_event], "state": [{"entity": e, "item": x["key"], "quantity": p.state[e, x["key"]]}
                                                    for e in (giver.entity, taker.entity)]},
                    {"act": "correct", "what": "amount", "new": new, "old": old, "item": x,
                     "features": ["correct_amount"]},
                    check, ["corrections:amount"], ["correction"], "correction")
            live = [h for h in cast if counted(h) and p.state.get((h.entity, x["key"])) not in (None, 0)
                    and h.entity in (ev["from"], ev["to"]) and h in fresh()]
            if live:
                ask(rng.choice(live))

    # -- a comparison or a total --------------------------------------------------------------------
    persons = [h for h in cast if h.kind != "place" and counted(h) and p.state.get((h.entity, x["key"])) not in (None, 0)]
    if len(persons) >= 2 and rng.random() < 0.2:
        a, b = rng.sample(persons, 2)
        va, vb = p.state[a.entity, x["key"]], p.state[b.entity, x["key"]]
        p.other({"act": "answer", "entity": a.entity if va > vb else b.entity, "quantity": None, "relation": "more",
                 "candidates": [a.entity, b.entity], "item": x["key"],
                 "evidence": {"turns": sorted(set(p.evidence(a.entity) + p.evidence(b.entity)))}},
                {"act": "ask", "what": "more", "a": p.mention(a), "b": p.mention(b), "item": x, "features": []},
                spec([], [a, b], x, question=True), [], ["transfer"], "answerable")
    counted_now = [h for h in cast if counted(h)]
    pairs = [(a, b) for a in counted_now for b in counted_now
             if a.id < b.id and (a.kind == "place") == (b.kind == "place")]
    if pairs and ("question_forms" in f5 or rng.random() < 0.3):
        a, b = rng.choice(pairs)
        total = p.state[a.entity, x["key"]] + p.state[b.entity, x["key"]]
        form = "q_two_total" if a.kind != "place" and len(cast) == 2 and rng.random() < 0.6 else "q_plain"
        p.other({"act": "answer", "entity": [a.entity, b.entity], "quantity": total, "relation": "total",
                 "evidence": {"turns": sorted(set(p.evidence(a.entity) + p.evidence(b.entity)))}, "item": x["key"]},
                {"act": "ask", "what": "total", "a": p.mention(a), "b": p.mention(b), "item": x,
                 "features": [form] if form != "q_plain" else []},
                spec([], [] if form == "q_two_total" else [a, b], x, question=True,
                     allow=[2] if form == "q_two_total" else [],
                     cues=["two_of_them"] if form == "q_two_total" else []),
                ["question_forms:q_two_total"] if form == "q_two_total" else [], ["transfer"], "answerable")
    return v4._valid(p)


def scenario_json(p, sid):
    out = v4.scenario_json(p, sid)
    out["focus5"] = sorted(p.focus5)
    return out


def generate_scenarios(count=PER_HALF, extra=110):
    vocab = halves()
    out = []
    for half in ("build", "check"):
        for lang in LANGS:
            index, made = 0, 0
            while made < count + extra:
                p = scenario5(lang, half, index, vocab[half][lang])
                index += 1
                if p is None:
                    continue
                made += 1
                out.append(scenario_json(p, "s5_%s_%s_%03d" % (lang, half[0], index)))
    return out


# ---------------------------------------------------------------------------
# surface variation: two more phrasings of the same scenario
# ---------------------------------------------------------------------------
OTHER_REGISTER = {"ko": {"haeyo": "hapsyo", "hapsyo": "haeyo", "banmal": "haeyo"},
                  "en": {"casual": "formal", "neutral": "casual", "formal": "casual"}}
PERSON_GIVE = ("give", "lend", "pass", "hand_over", "give_back", "send", "transfer")
PERSON_TAKE = ("borrow", "receive")
FRONTS = ("front_recipient", "front_purpose", "front_then", "adv_apparently", "count_first")
Q_SWAP = {("en", 1): {"q_plain": "q_echo", "q_got": "q_still", "q_hold": "q_plain", "q_left": "q_still",
                      "q_still": "q_got", "q_echo": "q_plain"},
          ("en", 2): {"q_plain": "q_got", "q_got": "q_plain", "q_hold": "q_still", "q_left": "q_plain",
                      "q_still": "q_left", "q_echo": "q_hold"},
          ("ko", 1): {"q_plain": "q_relative", "q_hold": "q_still", "q_left": "q_relative", "q_got": "q_relative",
                      "q_still": "q_plain", "q_relative": "q_hold"},
          ("ko", 2): {"q_plain": "q_bare", "q_hold": "q_plain", "q_left": "q_bare", "q_got": "q_bare",
                      "q_still": "q_bare", "q_relative": "q_bare"}}
Q_CUES = {"q_got": ["q_got"], "q_left": ["q_left"], "q_hold": ["q_hold"], "q_still": ["q_still"], "q_echo": ["q_echo"],
          "q_relative": ["q_relative"]}
EN_HAS_SWAP = {"has": "has_got", "has_got": "keeps", "holding": "has", "carrying": "has_got", "keeps": "holding",
               "owns": "has", "responsible": "has"}


def _mentioned(turn):
    say = turn["say"]
    out = [say[k] for k in ("holder", "giver", "taker", "a", "b", "meant", "new", "old") if isinstance(say.get(k), dict)]
    return out + [m for m in say.get("holders") or [] if isinstance(m, dict)]


def variant(base, k):
    """The same scenario, phrased with a declared overlay of style features (see the module note). The truth and
    the expectations are the base's; only the style notes, the register and the checker's cues change."""
    out = copy.deepcopy(base)
    out["id"] = "%s_v%d" % (base["id"], k)
    lang = base["language"]
    en = lang == "en"
    holders = {h["id"]: h for h in base["holders"]}
    changes = []
    if k == 1:
        out["register"] = OTHER_REGISTER[lang][base["register"]]
        changes.append("register:%s" % out["register"])
    elif not en and base["register"] == "banmal":
        out["register"] = "haeyo"
        changes.append("register:haeyo")
    previous = None
    for turn in out["turns"]:
        say, check = turn["say"], turn["check"]
        feats = say.setdefault("features", [])
        act, what = say.get("act"), say.get("what")
        swap = Q_SWAP[lang, k]
        if act == "ask" and what == "count" and not check.get("absent"):
            form = next((ft for ft in feats if ft.startswith("q_")), "q_plain")
            new = swap.get(form)
            h = holders[say["holder"]["id"]]
            if new == "q_bare" and h["kind"] in ("place", "first_person", "relation_unnamed"):
                new = None
            if new and new != form:
                feats[:] = [ft for ft in feats if not ft.startswith("q_")] + ([] if new == "q_plain" else [new])
                check["cues"] = sorted(set(c for c in check["cues"] if c not in sum(Q_CUES.values(), []))
                                       | set(Q_CUES.get(new, [])))
                if new == "q_bare":
                    check["order_cues"] = ["bare:%s" % h["tokens"][0]]
                changes.append("%d:%s" % (turn["n"], new))
        elif act == "state" and what == "has" and say.get("mode") == "plain" and say.get("verb") != "place":
            h = holders[say["holder"]["id"]]
            if en and k == 1 and say["verb"] in EN_HAS_SWAP:
                say["verb"] = EN_HAS_SWAP[say["verb"]]
                feats[:] = [ft for ft in feats if ft not in v4.HAS_VERBS["en"]] + (
                    [say["verb"]] if say["verb"] != "has" else [])
                changes.append("%d:has:%s" % (turn["n"], say["verb"]))
            elif en and k == 2 and "adv_moment" not in feats:
                feats.append("adv_moment")
                check["cues"] = sorted(set(check["cues"]) | {"adv_moment"})
                changes.append("%d:adv_moment" % turn["n"])
            elif not en and k == 1 and h["kind"] not in ("first_person",):
                ft = "has_dative_topic" if turn["n"] % 2 else "object_topic"
                feats.append(ft)
                if ft == "object_topic" and h["tokens"]:
                    check["order_cues"] = ["item_first:%s" % h["tokens"][0]]
                changes.append("%d:%s" % (turn["n"], ft))
            elif not en and k == 2 and (h["kind"] in ("title", "apposition") or h.get("relation") in KO_ELDERS):
                feats.append("honorific")
                check["cues"] = sorted(set(check["cues"]) | {"honorific"})
                changes.append("%d:honorific" % turn["n"])
        elif act == "state" and what == "transfer":
            verb = say.get("verb")
            giver, taker = holders[say["giver"]["id"]], holders[say["taker"]["id"]]
            fronted = any(ft in FRONTS for ft in feats)
            persons = giver["kind"] != "place" and taker["kind"] != "place"
            subject = giver if verb in PERSON_GIVE else (taker if verb in PERSON_TAKE else None)
            shared = (previous is not None and subject is not None and previous["say"].get("act") == "state"
                      and [m["id"] for m in _mentioned(previous)] == [subject["id"]]
                      and not say["giver" if subject is giver else "taker"].get("first"))
            if k == 1 and persons and not fronted and verb in PERSON_GIVE and not (en and verb == "give"):
                if en:
                    feats.append("passive_by")
                    check["cues"] = sorted(set(check["cues"]) | {"passive_by"})
                    changes.append("%d:passive_by" % turn["n"])
                else:
                    feats.append("count_first")
                    check["cues"] = sorted(set(check["cues"]) | {"count_first"})
                    changes.append("%d:count_first" % turn["n"])
            elif k == 1 and not en and persons and verb in PERSON_GIVE:
                feats.append("dative_ege")
                check["cues"] = sorted(set(check["cues"]) | {"dative_ege"})
                changes.append("%d:dative_ege" % turn["n"])
            elif k == 2 and shared and not fronted and (
                    not en or (subject["kind"] in ("name", "title", "relation", "apposition") and subject.get("gender"))):
                role = "giver" if subject is giver else "taker"
                if en:
                    pronoun = "she" if subject["gender"] == "f" else "he"
                    feats.append("pronoun_subject" if role == "giver" else "pronoun_taker")
                    check["cues"] = sorted(set(check["cues"]) | {"pronoun"})
                    check["direction"] = dict(check["direction"], **{role: pronoun})
                    # the fact line names the role by the pronoun, not the name the phrasing must leave out
                    say[role] = dict(say[role], who="%s (the person just mentioned; write '%s', not the name)" % (
                        pronoun, pronoun.capitalize()))
                else:
                    feats.append("omit_subject" if role == "giver" else "omit_taker")
                    say[role] = dict(say[role], who="(방금 말한 그 사람: 이름도 주어도 쓰지 않음)")
                check["names"] = [t for t in check["names"] if t not in subject["tokens"]]
                check["absent"] = sorted(set(check.get("absent") or []) | set(subject["tokens"]))
                changes.append("%d:omit_%s" % (turn["n"], role))
            elif k == 2 and not en and (taker["kind"] in ("title", "apposition") or taker.get("relation") in KO_ELDERS
                                        or giver["kind"] in ("title", "apposition")
                                        or giver.get("relation") in KO_ELDERS):
                feats.append("honorific")
                check["cues"] = sorted(set(check["cues"]) | {"honorific"})
                changes.append("%d:honorific" % turn["n"])
        previous = turn if act == "state" else None
    out["variant"] = {"of": base["id"], "k": k, "changes": changes}
    return out


# ---------------------------------------------------------------------------
# phrasing: regular dialogues first, then the variants of the first usable ones
# ---------------------------------------------------------------------------
def _load_rows(lang):
    rows, status = {}, {}
    path = phrasings_path(lang)
    if not path.exists():
        return rows, status
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "dialogue" in row:
            status[row["scenario"]] = row
        else:
            rows.setdefault(row["scenario"], []).append(row)
    return rows, status


def phrase(lang, halves_=("build", "check")):
    use_v5_tables()
    install_features()
    v4.Checker = Checker5
    v4.PHRASINGS = phrasings_path(lang)
    scenarios = [s for s in v4.load_scenarios() if s["language"] == lang]
    regular = [s for s in scenarios if "variant" not in s]
    for half in halves_:
        ids = [s["id"] for s in regular if s["half"] == half]
        v4.phrase(PER_HALF, set(ids))
        _rows, status = _load_rows(lang)
        usable = [sid for sid in ids if (status.get(sid) or {}).get("dialogue")]
        # a base whose second variant leaves out or pronominalises a subject first (they are rare), then the rest
        by_id = {s["id"]: s for s in scenarios}
        usable.sort(key=lambda sid: not any("omit_" in c for c in by_id[sid + "_v2"]["variant"]["changes"]))
        triples = 0
        for sid in usable:
            if triples >= VARIED_PER_HALF:
                break
            wanted = {sid + "_v1", sid + "_v2"}
            v4.phrase(10 ** 6, wanted)
            _rows, status = _load_rows(lang)
            if all((status.get(v) or {}).get("dialogue") for v in wanted):
                triples += 1
        print("half %s %s: regular %d, triples %d" % (half, lang, min(len(usable), PER_HALF), triples), flush=True)


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
OTHER_SETS = ("dialogues_dev", "dialogues_dev2", "dialogues_dev3", "dialogues_dev4")
KEPT = HERE / "phrasings_kept.jsonl"
STATS = HERE / "phrasing_stats.jsonl"


def _overlapping(dialogues):
    sys.path.insert(0, str(ROOT / "bench"))
    import dialogue_gate as gate
    found = gate.overlaps(dialogues, files=v4.corpus_files(("data/benchmarks/dialogues_dev5/",)))
    out = {item["dialogue"] for item in found["overlaps"]}
    others = []
    for name in OTHER_SETS:
        folder = ROOT / "data/benchmarks" / name
        if folder.exists():
            others += [norm for _d, _n, _raw, norm in gate.dialogue_sentences(gate.load(folder))]
    others = set(others)
    for d in dialogues:
        text = gate._normalize_corpus("\n".join(t["say"] for t in d["turns"]))
        if any(norm in text and gate._full_sentence_at(text, norm) for norm in others):
            out.add(d["id"])
    return out


def assemble(write=True):
    use_v5_tables()
    install_features()
    scenarios = {s["id"]: s for s in load_all()}
    checker = Checker5()
    rows, status = {}, {}
    for lang in LANGS:
        r, s = _load_rows(lang)
        rows.update(r)
        status.update(s)
    candidates, problems = {}, []
    for sid, scn in scenarios.items():
        st = status.get(sid, {})
        if not st.get("dialogue"):
            continue
        keys = [h["entity"] for h in scn["holders"]]
        if any(a != b and a in b for a in keys for b in keys):
            problems.append("%s: one holder's name holds another's" % sid)
            continue
        texts, said = {}, []
        for turn in scn["turns"]:
            if turn["n"] not in st["kept"]:
                continue
            text = [r for r in rows[sid] if r["n"] == turn["n"] and r["ok"]][-1]["text"]
            ok, reason = checker.check(scn, turn, text, said)
            if not ok:
                problems.append("%s#%d %s" % (sid, turn["n"], reason))
            said.append(text)
            texts[turn["n"]] = text
        turns = v4.build_dialogue(scn, texts)
        if turns is None:
            problems.append("%s: not a dialogue" % sid)
            continue
        var = scn.get("variant")
        candidates[sid] = {
            "schema": v4.SCHEMA, "id": sid, "language": scn["language"], "domain": "everyday",
            "categories": sorted({tag for t in turns for tag in t["tags"]}),
            "variation": {"word_order": "free", "register": scn["register"],
                          "split": "multi_fact" if len(turns[0]["expect"].get("events") or []) > 1 else
                          "one_fact_per_turn",
                          "correction_position": "late" if any(t["label"] == "correction" for t in turns) else "none",
                          "roles": "scenario", "initial_values": {}, "scenario": sid, "half": scn["half"],
                          "focus": scn["focus5"], "phraser": v4.PHRASER["weights"],
                          "classes": sorted({c for t in turns for c in t["classes"]}),
                          **({"variant_of": var["of"], "variant": var["k"], "variant_changes": var["changes"]}
                             if var else {})},
            "turns": turns}
    shared = _overlapping(list(candidates.values()))
    # a regular dialogue in scenario order, up to PER_HALF per half and language; a triple only when all three are in
    dialogues, split, counts, left_out, triples = [], {"build": [], "check": [], "build_var": [], "check_var": []}, \
        {}, {"other_file": 0}, []
    base_ids = {}
    for sid, d in candidates.items():
        if d["variation"].get("variant"):
            continue
        key = (d["variation"]["half"], d["language"])
        if sid in shared:
            left_out["other_file"] += 1
            continue
        if counts.get(key, 0) >= PER_HALF:
            continue
        counts[key] = counts.get(key, 0) + 1
        new_id = "dev5_%s_%s_%02d" % (d["language"], d["variation"]["half"][0], counts[key])
        base_ids[sid] = new_id
        dialogues.append(dict(d, id=new_id))
        split[d["variation"]["half"]].append(new_id)
    made = {}
    for sid, new_id in base_ids.items():
        d = candidates[sid]
        key = (d["variation"]["half"], d["language"])
        vs = [candidates.get(sid + "_v%d" % k) for k in (1, 2)]
        if made.get(key, 0) >= VARIED_PER_HALF or any(v is None or v["id"] in shared for v in vs):
            continue
        made[key] = made.get(key, 0) + 1
        ids = [new_id]
        for k, v in zip((1, 2), vs):
            vid = "%s_v%d" % (new_id, k)
            dialogues.append(dict(v, id=vid))
            split[d["variation"]["half"] + "_var"].append(vid)
            ids.append(vid)
        triples.append((sid, ids))
    if write:
        for path in HERE.glob("dev5_*.json"):
            path.unlink()
        for d in dialogues:
            (HERE / (d["id"] + ".json")).write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n",
                                                    encoding="utf-8")
        lines = ["seed %d scenario_build %d scenario_check %d sampling_build %d sampling_check %d" % (
            SEED, SCENARIO_SEEDS["build"], SCENARIO_SEEDS["check"], SAMPLING["build"], SAMPLING["check"])]
        lines += ["%s %s" % (name, " ".join(ids)) for name, ids in split.items()]
        (HERE / "split.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (HERE / "triples.txt").write_text("".join("%s %s\n" % (sid, " ".join(ids)) for sid, ids in triples),
                                          encoding="utf-8")
        used = {d["variation"]["scenario"] for d in dialogues}
        with KEPT.open("w", encoding="utf-8") as out:
            for sid in scenarios:
                if sid not in used:
                    continue
                for row in rows[sid]:
                    if row["ok"]:
                        out.write(json.dumps({k: row[k] for k in ("scenario", "n", "attempt", "seed", "text", "ok")},
                                             ensure_ascii=False) + "\n")
                out.write(json.dumps(status[sid], ensure_ascii=False) + "\n")
        stats = {"phraser": v4.PHRASER, "attempts_per_turn": v4.ATTEMPTS, "left_out_for_a_shared_sentence": left_out,
                 "by_half_language": {}}
        for sid, st in status.items():
            scn = scenarios[sid]
            key = "%s_%s%s" % (scn["half"], scn["language"], "_var" if scn.get("variant") else "")
            row = stats["by_half_language"].setdefault(key, {"scenarios": 0, "usable": 0, "samples": 0, "reasons": {},
                                                             "peak_mb": 0, "seconds": 0.0})
            row["scenarios"] += 1
            row["usable"] += bool(st["dialogue"])
            row["peak_mb"] = max(row["peak_mb"], st.get("peak_mb") or 0)
            row["seconds"] = round(row["seconds"] + (st.get("seconds") or 0), 1)
            for r in rows.get(sid, []):
                row["samples"] += 1
                reason = r["reason"].split(":")[0]
                row["reasons"][reason] = row["reasons"].get(reason, 0) + 1
        STATS.write_text(json.dumps(stats, ensure_ascii=False) + "\n", encoding="utf-8")
    return dialogues, split, triples, problems


def coverage(dialogues):
    """{family: {lang: dialogues, lang_half: ...}} over the regular dialogues, by class tags."""
    table = {fam: {} for fam in FAMILIES}
    for d in dialogues:
        if d["variation"].get("variant"):
            continue
        for fam in families_of(d["variation"]["classes"]):
            for key in (d["language"], "%s_%s" % (d["language"], d["variation"]["half"])):
                table[fam][key] = table[fam].get(key, 0) + 1
    return table


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["scenarios", "phrase", "assemble", "coverage"])
    parser.add_argument("--lang", choices=LANGS)
    parser.add_argument("--half", choices=("build", "check"))
    args = parser.parse_args(argv)
    if args.command == "scenarios":
        use_v5_tables()
        out = generate_scenarios()
        SCENARIOS.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out), encoding="utf-8")
        print("scenarios", len(out), "(each with two variants derived at load)")
    elif args.command == "phrase":
        phrase(args.lang, (args.half,) if args.half else ("build", "check"))
    elif args.command == "assemble":
        dialogues, split, triples, problems = assemble()
        print("dialogues %d (%s); triples %d; rechecked problems %d" % (
            len(dialogues), ", ".join("%s %d" % (k, len(v)) for k, v in split.items()), len(triples), len(problems)))
        for line in problems[:20]:
            print("  ", line)
    else:
        dialogues, _split, triples, _p = assemble(write=False)
        table = coverage(dialogues)
        print("%-16s %4s %4s   %s" % ("family", "ko", "en", "by half"))
        for fam, row in table.items():
            print("%-16s %4d %4d   %s" % (fam, row.get("ko", 0), row.get("en", 0),
                                         " ".join("%s=%d" % (k, v) for k, v in sorted(row.items()) if "_" in k)))
        print("triples", len(triples))


if __name__ == "__main__":
    sys.exit(main())
