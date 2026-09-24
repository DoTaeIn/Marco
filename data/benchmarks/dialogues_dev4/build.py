"""Development set v4 (goal G4.1): the truth from a scenario, the wording from a language model.

Every set before this one was template output, and the frozen dialogues are
natural adult language. So v4 is built in two steps, and no sentence of it is
written by a grammar in this file:

1. **Scenario generator** (``scenario``): holders (bare names, titled names,
   relational descriptions with and without a name, appositions, the first
   person, places), items with counts (zero, vague then exact, "only has"),
   events of the transfer and possession verb classes, corrections of an amount
   or of a recipient, referent repairs, and questions, each with its expected
   semantic answer computed by replaying the events. The scenario is the ground
   truth; nothing in it is prose. Each turn carries its class tags.
2. **Phrasing model**: ``PHRASER`` (a local instruction model run through
   ``mlx-lm``; loaded only inside ``phrase``, never imported by product code)
   writes each turn as one natural message, in Korean or English, at
   temperature 0.7, with the dialogue's register and the turn's style note, the
   earlier accepted messages as context. Several variants are sampled per turn
   (``ATTEMPTS``); **the checker** (``check``) keeps the first that states every
   number, name, item and place of the turn's facts, the right direction of a
   transfer, the turn's class cues and nothing else, and discards the rest.
   Nothing is edited by hand. A scenario whose turn fails every variant is
   dropped and the next scenario index is tried.

Build and check halves come from different scenario seeds, from disjoint halves
of every vocabulary table (names, items, places, relation words and roles),
and are phrased at different sampling seeds (``SAMPLING``).

Vocabulary sources: English given names from the U.S. Social Security
Administration's most popular names by decade (public data); English surnames
from the U.S. Census Bureau's 2010 frequently occurring surnames (public data);
Korean given names from the Supreme Court's birth registration name statistics
(대법원 전자가족관계등록시스템, most common given names); Korean surnames from
Statistics Korea's 2015 census (성씨 통계). Items, places, relation words and
roles are everyday nouns chosen here; none is a pack's declared example word.

    python data/benchmarks/dialogues_dev4/build.py scenarios   # scenarios.jsonl (no model)
    python data/benchmarks/dialogues_dev4/build.py phrase      # sample and check; phrasings.jsonl
    python data/benchmarks/dialogues_dev4/build.py assemble    # dev4_*.json and split.txt from the cache
    python data/benchmarks/dialogues_dev4/build.py coverage    # the class table, by scenario tags
"""
import argparse
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCHEMA = "marco1-dialogue-gate-v1"
SEED = 20260924
SCENARIO_SEEDS = {"build": 4401, "check": 8803}
SAMPLING = {"build": 1511, "check": 2939}
PER_HALF = 42               # dialogues per language per half: 168 in all
ATTEMPTS = 10               # sampled variants per turn before the scenario is dropped
PHRASER = {"model": "Qwen/Qwen2.5-7B-Instruct", "weights": "mlx-community/Qwen2.5-7B-Instruct-4bit",
           "revision": "c26a38f6a37d0a51b4e9a1eb3026530fa35d9fed", "backend": "mlx-lm", "temperature": 0.7,
           "max_tokens": 90, "cache_limit_mb": 512}
SCENARIOS = HERE / "scenarios.jsonl"         # one scenario per line (not *.json: the gate reads those)
PHRASINGS = HERE / "phrasings.jsonl"
LANGS = ("ko", "en")

# ---------------------------------------------------------------------------
# vocabulary (each table is cut into disjoint build and check halves by SEED)
# ---------------------------------------------------------------------------
EN_GIVEN = {
    "f": ["Abigail", "Alice", "Amara", "Anika", "Bianca", "Brenda", "Carla", "Chloe", "Daisy", "Delia", "Elena",
          "Erin", "Fiona", "Gemma", "Greta", "Hannah", "Helen", "Ines", "Irene", "Jasmine", "Joanna", "Julia",
          "Karen", "Kira", "Laura", "Leah", "Lena", "Lucy", "Maria", "Maya", "Megan", "Molly", "Nadia", "Nina",
          "Nora", "Olivia", "Paula", "Petra", "Priya", "Rachel", "Rosa", "Ruth", "Sara", "Sofia", "Tara", "Tessa",
          "Vera", "Wendy", "Yara", "Zoe"],
    "m": ["Aaron", "Adam", "Ahmed", "Arthur", "Ben", "Brian", "Carlos", "Colin", "Daniel", "David", "Diego",
          "Eli", "Eric", "Ethan", "Felix", "Frank", "Gavin", "George", "Hugo", "Ian", "Isaac", "Jack", "Jacob",
          "James", "Jason", "Kevin", "Leo", "Liam", "Lucas", "Luis", "Mateo", "Martin", "Nathan", "Neil", "Noah",
          "Omar", "Oscar", "Owen", "Paul", "Peter", "Rafael", "Ryan", "Samuel", "Simon", "Theo", "Tom", "Victor",
          "Walter", "Yusuf", "Zack"],
}
EN_SURNAMES = ["Smith", "Johnson", "Williams", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
               "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
               "Perez", "Thompson", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
               "Allen", "Wright", "Scott", "Torres", "Nguyen", "Flores", "Adams", "Nelson", "Rivera", "Campbell",
               "Mitchell", "Roberts", "Gomez", "Phillips", "Evans", "Diaz", "Edwards", "Collins", "Reyes",
               "Stewart", "Morris", "Morales", "Murphy", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper",
               "Peterson", "Bailey", "Kelly", "Howard", "Ramos", "Richardson", "Patel", "Novak", "Fischer"]
KO_GIVEN = {
    "f": ["서연", "서윤", "서현", "민서", "하은", "하윤", "윤서", "지유", "채원", "수아", "지아", "지윤", "은서",
          "다은", "예은", "수빈", "소율", "예린", "지안", "예원", "하린", "시은", "유나", "가은", "채은", "아린",
          "서아", "연서", "민지", "은정", "지영", "수진", "미경", "혜원", "소연", "나연", "유진", "보람", "다인",
          "세영"],
    "m": ["민준", "서준", "도윤", "예준", "시우", "하준", "주원", "지호", "지후", "준우", "준서", "건우", "현우",
          "우진", "선우", "서진", "연우", "유준", "승우", "시윤", "은우", "유찬", "윤우", "시후", "진우", "지원",
          "재윤", "시현", "한결", "태윤", "상훈", "정호", "성진", "동훈", "재민", "영호", "기현", "태민", "준호",
          "도현"],
}
KO_SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권", "황", "안",
               "송", "홍", "고", "문", "양", "손", "배", "백", "허", "남", "심", "노", "곽"]
KO_JOB_TITLES = ["과장", "대리", "팀장", "선생", "기사", "사장", "실장", "부장"]
EN_TITLES = {"m": ["Mr."], "f": ["Ms.", "Mrs."], "any": ["Dr."]}

# (plural, singular) -- plural is the item's key
EN_ITEMS = [("umbrellas", "umbrella"), ("chairs", "chair"), ("markers", "marker"), ("candles", "candle"),
            ("lanterns", "lantern"), ("buckets", "bucket"), ("blankets", "blanket"), ("towels", "towel"),
            ("pillows", "pillow"), ("tickets", "ticket"), ("stamps", "stamp"), ("envelopes", "envelope"),
            ("postcards", "postcard"), ("notebooks", "notebook"), ("folders", "folder"), ("binders", "binder"),
            ("magazines", "magazine"), ("novels", "novel"), ("batteries", "battery"), ("bulbs", "bulb"),
            ("flashlights", "flashlight"), ("helmets", "helmet"), ("mugs", "mug"), ("plates", "plate"),
            ("bowls", "bowl"), ("spoons", "spoon"), ("baskets", "basket"), ("crates", "crate"),
            ("backpacks", "backpack"), ("suitcases", "suitcase"), ("bottles", "bottle"),
            ("apples", "apple"), ("oranges", "orange"), ("lemons", "lemon"), ("peaches", "peach"),
            ("onions", "onion"), ("potatoes", "potato"), ("tomatoes", "tomato"), ("eggs", "egg"),
            ("muffins", "muffin"), ("cookies", "cookie"), ("sandwiches", "sandwich"), ("bagels", "bagel"),
            ("tents", "tent"), ("bicycles", "bicycle"), ("scooters", "scooter"), ("laptops", "laptop"),
            ("tablets", "tablet"), ("chargers", "charger"), ("badges", "badge"), ("medals", "medal"),
            ("trophies", "trophy"), ("balloons", "balloon"), ("ribbons", "ribbon"), ("stickers", "sticker"),
            ("coins", "coin"), ("rulers", "ruler"), ("paintbrushes", "paintbrush"), ("cushions", "cushion"),
            ("rugs", "rug"), ("lamps", "lamp"), ("heaters", "heater"), ("mats", "mat"), ("shovels", "shovel"),
            ("rakes", "rake"), ("ladders", "ladder"), ("hammers", "hammer"), ("wrenches", "wrench"),
            ("knives", "knife")]
# (noun, counter)
KO_ITEMS = [("우산", "개"), ("의자", "개"), ("볼펜", "자루"), ("색연필", "자루"), ("양초", "개"), ("손전등", "개"),
            ("양동이", "개"), ("담요", "장"), ("수건", "장"), ("베개", "개"), ("티켓", "장"), ("우표", "장"),
            ("봉투", "장"), ("엽서", "장"), ("잡지", "권"), ("소설책", "권"), ("건전지", "개"), ("전구", "개"),
            ("헬멧", "개"), ("장갑", "켤레"), ("양말", "켤레"), ("머그컵", "개"), ("접시", "개"), ("그릇", "개"),
            ("숟가락", "개"), ("바구니", "개"), ("배낭", "개"), ("여행가방", "개"), ("생수", "병"), ("음료수", "병"),
            ("자두", "개"), ("오렌지", "개"), ("레몬", "개"), ("복숭아", "개"), ("양파", "개"), ("감자", "개"),
            ("토마토", "개"), ("달걀", "개"), ("머핀", "개"), ("쿠키", "개"), ("샌드위치", "개"), ("도넛", "개"),
            ("텐트", "개"), ("자전거", "대"), ("킥보드", "대"), ("노트북", "대"), ("태블릿", "대"), ("충전기", "개"),
            ("명찰", "개"), ("메달", "개"), ("트로피", "개"), ("풍선", "개"), ("리본", "개"), ("스티커", "장"),
            ("동전", "개"), ("방석", "개"), ("선풍기", "대"), ("난로", "대"), ("사다리", "개"), ("망치", "개"),
            ("장작", "묶음"), ("신문", "묶음"), ("꽃다발", "개"), ("휴지", "묶음"), ("빗자루", "개"),
            ("국자", "개"), ("주전자", "개"), ("젓가락", "벌"), ("셔츠", "벌")]
# places: (entity, article)
EN_PLACES = ["north warehouse", "south warehouse", "east warehouse", "west warehouse", "front office",
             "back office", "storage room", "supply closet", "break room", "mailroom", "garage", "basement",
             "attic", "shed", "workshop", "studio", "classroom", "gym", "library", "lobby", "cafe", "bakery",
             "pharmacy", "clinic", "main hall", "community center", "reception desk", "loading dock",
             "greenhouse", "barn", "locker room", "music room", "art room", "science lab", "staff room",
             "corner shop", "pantry", "boathouse", "stockroom", "front porch"]
KO_PLACES = ["북쪽 창고", "남쪽 창고", "동쪽 창고", "서쪽 창고", "사무실", "보관실", "비품실", "휴게실", "우편실",
             "차고", "지하실", "다락방", "작업실", "공방", "교실", "체육관", "도서관", "로비", "카페", "빵집",
             "약국", "진료실", "강당", "주민센터", "교무실", "안내 데스크", "하역장", "온실", "탈의실", "음악실",
             "미술실", "과학실", "매점", "편의점", "본관", "별관", "세탁실", "주방 창고", "현관", "관리실"]
# relation words: (word, gender or None)
EN_RELATIONS = [("cousin", None), ("friend", None), ("sister", "f"), ("brother", "m"), ("neighbor", None),
                ("coworker", None), ("roommate", None), ("classmate", None), ("teammate", None), ("aunt", "f"),
                ("uncle", "m"), ("niece", "f"), ("nephew", "m"), ("partner", None)]
KO_RELATIONS = [("사촌", None), ("친구", None), ("동생", None), ("이웃", None), ("동료", None), ("룸메이트", None),
                ("후배", None), ("선배", None), ("팀원", None), ("조카", None), ("짝꿍", None), ("동기", None)]
EN_ROLES = ["the courier", "our driver", "the new intern", "the janitor", "the cashier", "the librarian",
            "our coach", "the landlord", "the chef", "the nurse", "the caretaker", "the receptionist"]
KO_ROLES = ["택배 기사", "운전기사", "인턴", "관리인", "계산원", "사서", "코치", "집주인", "요리사", "간호사",
            "경비원", "접수 담당"]
# words the style notes use to show a pattern; the checker refuses them in a phrasing
PATTERN_WORDS = {"en": ["Rowan", "Quinn", "jars", "jar", "flags", "flag", "cellar", "yard"],
                 "ko": ["수호", "하람", "화분", "깃발", "헛간", "마당"]}


def halves():
    """{"build"|"check": {lang: {table: [...]}}}: every table cut in two by SEED."""
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


# ---------------------------------------------------------------------------
# numerals (for the fact lines and the checker)
# ---------------------------------------------------------------------------
EN_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}
KO_NATIVE_PRE = {"한": 1, "두": 2, "세": 3, "석": 3, "네": 4, "넉": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8,
                 "아홉": 9}
KO_NATIVE_NOUN = {"하나": 1, "둘": 2, "셋": 3, "넷": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
KO_TENS = {"열": 10, "스물": 20, "스무": 20, "서른": 30}
KO_SINO = "일이삼사오육칠팔구십"
KO_COUNTERS = ["개", "자루", "장", "권", "병", "켤레", "대", "벌", "묶음", "마리", "명", "상자", "통", "봉지",
               "조각", "알", "잔", "송이"]


def en_numbers(text, singulars=()):
    """[(value, start, end)]: digits, number words (not the pronoun 'one'), and a/an/single before one of
    ``singulars`` (1); -1 for a word that states or derives an amount no scenario gives (dozen, half ...)."""
    out = []
    for m in re.finditer(r"(?<![\w.])(\d+)(?![\d]|\.\d)", text):
        out.append((int(m.group(1)), m.start(), m.end()))
    low = text.lower()
    tens = "|".join(EN_TENS)
    units = "|".join(sorted(EN_WORDS, key=len, reverse=True))
    for m in re.finditer(r"(?<![a-z'-])(?:(%s)(?:-(one|two|three|four|five|six|seven|eight|nine))?|(%s))(?![a-z'-])"
                         % (tens, units), low):
        if m.group(3) == "one" and re.search(r"(?:the|that|this|which|each|every|no|any|some|another|a)\s+$",
                                             low[:m.start()]):
            continue
        if m.group(3) == "one" and re.match(r"\s+another\b", low[m.end():]):
            continue
        if m.group(1):
            value = EN_TENS[m.group(1)] + (EN_WORDS[m.group(2)] if m.group(2) else 0)
        else:
            value = EN_WORDS[m.group(3)]
        out.append((value, m.start(), m.end()))
    if singulars:
        nouns = "|".join(re.escape(s.lower()) for s in singulars)
        for m in re.finditer(r"(?<![a-z'-])(?:a|an|a single|one single|single)\s+(?:[a-z]+\s+)?(?:%s)(?![a-z])"
                             % nouns, low):
            if not any(s <= m.start() < e for _v, s, e in out):
                out.append((1, m.start(), m.end()))
    for m in re.finditer(r"(?<![a-z])(dozen|dozens|half|twice|double|triple|couple|several|few|pair|pairs|"
                         r"hundred|thousand)(?![a-z])", low):
        out.append((-1, m.start(), m.end()))          # an amount the scenario never states
    return out


def _ko_native():
    """({determiner form: value}, {noun form: value}) for 1..29: 한/두/세 ... 열한 ... 스무, 하나/둘 ... 스물."""
    pre, noun = {}, {}
    for tens, tv in (("", 0), ("열", 10), ("스물", 20)):
        for word, v in KO_NATIVE_PRE.items():
            pre[tens + word] = tv + v
        for word, v in KO_NATIVE_NOUN.items():
            noun[tens + word] = tv + v
    pre.update({"열": 10, "스무": 20})
    noun.update({"열": 10, "스물": 20})
    return pre, noun


KO_PRE_FULL, KO_NOUN_FULL = _ko_native()
KO_NOUN_TAILS = ("", "이", "가", "을", "를", "은", "는", "도", "만", "씩", "이에요", "예요", "이요", "요", "야", "이야",
                 "입니다", "이다", "다", "밖에", "뿐", "이서", "서", "의", "에", "이었어요", "였어요", "이었습니다",
                 "였습니다", "이었어", "였어", "이라", "라", "이고", "고", "이죠", "죠", "인데", "는데")


def ko_numbers(text):
    """[(value, start, end)]: digits; a native numeral before a counter, apart (세 개) or attached (세개);
    a native numeral noun with a particle (하나도, 둘이); -2 for a Sino-Korean numeral word before a counter
    (삼 자루: the wrong numeral system for a native counter)."""
    out = []
    counters = sorted(KO_COUNTERS, key=len, reverse=True)
    for m in re.finditer(r"(?<![\d])(\d+)(?![\d])", text):
        out.append((int(m.group(1)), m.start(), m.end()))
    tokens = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[^\s.,!?~]+", text)]
    for i, (tok, start, end) in enumerate(tokens):
        if re.search(r"\d", tok):
            continue
        after = tokens[i + 1][0] if i + 1 < len(tokens) else ""
        starts_counter = any(after.startswith(c) for c in counters)
        if tok in KO_PRE_FULL and starts_counter:
            out.append((KO_PRE_FULL[tok], start, end))
            continue
        attached = next(((w, c) for w in sorted(KO_PRE_FULL, key=len, reverse=True) for c in counters
                         if tok.startswith(w + c)), None)
        if attached:
            out.append((KO_PRE_FULL[attached[0]], start, end))
            continue
        noun = next((w for w in sorted(KO_NOUN_FULL, key=len, reverse=True)
                     if tok.startswith(w) and tok[len(w):] in KO_NOUN_TAILS), None)
        if noun:
            out.append((KO_NOUN_FULL[noun], start, end))
            continue
        if tok and all(ch in KO_SINO for ch in tok) and starts_counter:
            out.append((-2, start, end))
    return out


def en_amount(n):
    return str(n)


def ko_amount(n, counter):
    return "%d%s" % (n, counter)


# ---------------------------------------------------------------------------
# the scenario: holders, items, events, questions -- no prose
# ---------------------------------------------------------------------------
FAMILIES = ("zero_vague", "transfer_verbs", "holders", "fronting", "partitives", "question_forms",
            "referent_repairs", "korean_register")
HOLDER_KINDS = ("name", "title", "relation", "relation_unnamed", "apposition", "first_person", "place")
EN_TRANSFER = ("give", "lend", "pass", "hand_over", "give_back", "send", "transfer", "borrow", "receive")
KO_TRANSFER = ("give", "lend", "pass", "hand_over", "give_back", "send", "borrow", "receive")
PLACE_VERBS = ("leave_at", "move", "move_passive", "take_from")
USE_VERBS = ("use_up", "use_for", "lose")
HAS_VERBS = {"en": ("has", "has_got", "holding", "carrying", "keeps", "owns", "responsible"),
             "ko": ("exist", "hold", "carry", "keep", "responsible", "exist")}
RARE_VERBS = {"lend", "pass", "hand_over", "give_back", "send", "transfer", "leave_at", "move", "move_passive",
              "take_from", "use_up", "use_for", "borrow", "holding", "carrying", "keeps", "owns", "responsible",
              "hold", "carry", "keep"}


class Holder:
    def __init__(self, hid, kind, entity, gender=None, intro=None, short=None, tokens=(), cue=None,
                 anchor=None, relation=None):
        self.id, self.kind, self.entity, self.gender = hid, kind, entity, gender
        self.intro, self.short = intro or entity, short or entity
        self.tokens = list(tokens)          # words the checker requires when the holder is named
        self.cue = cue                      # a class cue the introducing turn must carry
        self.anchor, self.relation = anchor, relation

    def json(self):
        return {"id": self.id, "kind": self.kind, "entity": self.entity, "gender": self.gender,
                "intro": self.intro, "short": self.short, "tokens": self.tokens, "cue": self.cue,
                "relation": self.relation, "anchor": self.anchor}


class Planner:
    """One scenario: a cast, one or two items, and a list of turns with structured facts and expectations."""

    def __init__(self, lang, half, index, vocab, focus, rng):
        self.lang, self.half, self.index, self.v, self.focus, self.rng = lang, half, index, vocab, focus, rng
        self.register = self._register()
        self.state, self.touched, self.by_turn = {}, {}, {}
        self.turns, self.classes = [], set()
        self.correction = None
        self.used = set()
        self.introduced = set()
        self.last_change, self.last_ask = {}, {}

    # -- cast ------------------------------------------------------------------------------------
    def _register(self):
        if self.lang == "en":
            return self.rng.choice(["casual", "casual", "neutral", "neutral", "formal"])
        if "korean_register" in self.focus:
            return self.rng.choice(["haeyo", "haeyo", "hapsyo", "hapsyo"])
        return self.rng.choice(["haeyo", "haeyo", "haeyo", "hapsyo", "hapsyo", "banmal"])

    def _pick(self, key):
        pool = [x for x in self.v[key] if json.dumps(x, ensure_ascii=False) not in self.used]
        choice = self.rng.choice(pool)
        self.used.add(json.dumps(choice, ensure_ascii=False))
        return choice

    def _given(self, gender=None):
        gender = gender or self.rng.choice("fm")
        return self._pick("given_" + gender), gender

    def holder(self, hid, kind, anchor=None):
        en = self.lang == "en"
        polite = self.register in ("haeyo", "hapsyo")
        if kind == "name":
            name, g = self._given()
            return Holder(hid, kind, name, g, tokens=[name])
        if kind == "title":
            if en:
                g = self.rng.choice("fm")
                title = self.rng.choice(EN_TITLES[g] + EN_TITLES["any"])
                surname = self._pick("surnames")
                return Holder(hid, kind, surname, g, intro="%s %s" % (title, surname),
                              short="%s %s" % (title, surname), tokens=[surname], cue="title")
            if self.rng.random() < 0.6:
                name, g = self._given()
                return Holder(hid, kind, name, g, intro=name + " 씨", short=name + " 씨", tokens=[name],
                              cue="title")
            surname, job = self._pick("surnames"), self.rng.choice(self.v["job_titles"])
            entity = "%s %s" % (surname, job)
            return Holder(hid, kind, entity, self.rng.choice("fm"), intro=entity + "님", short=entity + "님",
                          tokens=[entity], cue="title")
        if kind == "relation":
            relation, rg = self._pick("relations")
            name, g = self._given(rg)
            if anchor is None:
                owner = "my" if en else ("제" if polite else "내")
            else:
                owner = (anchor.short + "'s") if en else anchor.short
            return Holder(hid, kind, name, g, intro="%s %s %s" % (owner, relation, name), short=name,
                          tokens=[name], cue="relation", anchor=anchor.id if anchor else "speaker",
                          relation=relation)
        if kind == "relation_unnamed":
            relation, rg = self._pick("relations")
            owner = "my" if en else ("제" if polite else "내")
            return Holder(hid, kind, relation, rg or self.rng.choice("fm"), intro="%s %s" % (owner, relation),
                          short="%s %s" % (owner, relation), tokens=[relation], cue="relation",
                          anchor="speaker", relation=relation)
        if kind == "apposition":
            role = self._pick("roles")
            if en:
                g = self.rng.choice("fm")
                title = self.rng.choice(EN_TITLES[g])
                surname = self._pick("surnames")
                return Holder(hid, kind, surname, g, intro="%s, %s %s" % (role, title, surname),
                              short="%s %s" % (title, surname), tokens=[surname], cue="role", relation=role)
            name, g = self._given()
            return Holder(hid, kind, name, g, intro="%s %s 씨" % (role, name), short=name + " 씨", tokens=[name],
                          cue="role", relation=role)
        if kind == "first_person":
            entity = "I" if en else "나"
            say = "I (me)" if en else ("저" if polite else "나")
            return Holder(hid, kind, entity, None, intro=say, short=say, tokens=[], cue="first_person")
        if kind == "place":
            place = self._pick("places")
            return Holder(hid, kind, place, None, intro=("the " + place) if en else place,
                          short=("the " + place) if en else place, tokens=[place], cue="place")
        raise ValueError(kind)

    def cast(self):
        """Two or three holders: at least one person, at most two places, one first person and one
        unnamed relation; the referent-repair flows get two named people."""
        f, rng = self.focus, self.rng
        kinds = []
        if "holders" in f:
            kinds.append(rng.choice(["title", "relation", "relation_unnamed", "apposition", "first_person",
                                     "place", "place", "first_person"]))
        n = 3 if rng.random() < 0.35 else 2
        while len(kinds) < n:
            k = rng.choice(["name", "name", "name", "title", "relation", "apposition", "first_person",
                            "relation_unnamed", "place"])
            if k in ("first_person", "relation_unnamed") and k in kinds:
                continue
            if k == "place" and kinds.count("place") >= 2:
                continue
            kinds.append(k)
        if kinds.count("place") == 1 and rng.random() < 0.5 and len(kinds) < 3:
            kinds.append("place")
        if all(k == "place" for k in kinds):
            kinds.append("name")
        named = [k for k in kinds if k in ("name", "title", "relation", "apposition")]
        while "referent_repairs" in f and len(named) < 2:
            kinds.append("name")
            named.append("name")
        rng.shuffle(kinds)
        holders = []
        for i, k in enumerate(kinds):
            anchor = None
            if k == "relation" and holders and rng.random() < 0.5:
                named_h = [h for h in holders if h.kind in ("name", "title")]
                anchor = named_h[0] if named_h else None
            holders.append(self.holder("ABCDE"[i], k, anchor))
        return holders

    def item(self):
        if self.lang == "en":
            plural, one = self._pick("items")
            return {"key": plural, "plural": plural, "one": one}
        noun, counter = self._pick("items")
        return {"key": noun, "noun": noun, "counter": counter}

    def mention(self, h):
        first = h.id not in self.introduced
        self.introduced.add(h.id)
        return {"who": h.intro if first else h.short, "first": first, "kind": h.kind, "id": h.id}

    # -- state -----------------------------------------------------------------------------------
    def apply(self, ev):
        if ev["type"] == "has":
            self.state[ev["holder"], ev["item"]] = ev["quantity"]
        elif ev["type"] == "use":
            self.state[ev["holder"], ev["item"]] -= ev["quantity"]
        else:
            self.state[ev["from"], ev["item"]] -= ev["quantity"]
            self.state[ev["to"], ev["item"]] = self.state.get((ev["to"], ev["item"]), 0) + ev["quantity"]

    def record(self, events, say, check, classes, tags):
        n = len(self.turns) + 1
        for ev in events:
            self.apply(ev)
            for key in ("holder", "from", "to"):
                if key in ev:
                    self.touched.setdefault(ev[key], []).append(n)
                    self.last_change[ev[key]] = n
        self.by_turn[n] = events
        rows = []
        for ev in events:
            for key in ("holder", "from", "to"):
                if key in ev and (ev[key], ev["item"]) not in [(r["entity"], r["item"]) for r in rows]:
                    rows.append({"entity": ev[key], "item": ev["item"],
                                 "quantity": self.state[ev[key], ev["item"]]})
        self.turns.append({"n": n, "say": say, "check": check, "classes": sorted(set(classes)), "label": "hold",
                           "tags": sorted(set(tags)),
                           "expect": {"act": "record", "entity": None, "quantity": None, "relation": None,
                                      "evidence": {"turns": [n]}, "events": events, "state": rows}})
        self.classes |= set(classes)
        return n

    def other(self, expect, say, check, classes, tags, label):
        n = len(self.turns) + 1
        self.turns.append({"n": n, "say": say, "check": check, "classes": sorted(set(classes)), "label": label,
                           "tags": sorted(set(tags)), "expect": expect})
        self.classes |= set(classes)
        return n

    def evidence(self, entity):
        return sorted(set(self.touched.get(entity, [])))

    def tags_for(self, entity):
        moved = any(e["type"] != "has" for t in self.touched.get(entity, []) for e in self.by_turn.get(t, []))
        return ["transfer"] if moved else ["ownership"]

    def answer_expect(self, h, item):
        e = {"act": "answer", "entity": h.entity, "quantity": self.state[h.entity, item["key"]],
             "relation": "count", "evidence": {"turns": self.evidence(h.entity)}, "item": item["key"]}
        c = self.correction
        if c and c["target"] in self.touched.get(h.entity, []):
            value = e["quantity"]
            ev = c["event"]
            if c["field"] == "quantity":
                old, new = c["old"], c["new"]
                if h.entity == ev["to"]:
                    retracted, rerun = value - new + old, value + old
                elif h.entity == ev["from"]:
                    retracted, rerun = value + new - old, value - old
                else:
                    retracted = rerun = value
            else:
                # read uncorrected, the old recipient keeps k and the new one lacks it; re-executed as a
                # second transfer, the giver gives k twice
                k = ev["quantity"]
                if h.entity == c["old"]:
                    retracted, rerun = value + k, value + k
                elif h.entity == c["new"]:
                    retracted, rerun = value - k, value
                elif h.entity == ev["from"]:
                    retracted, rerun = value, value - k
                else:
                    retracted = rerun = value
            if retracted != value:
                e["retracted_quantity"] = retracted
            if rerun not in (value, retracted):
                e["reexecuted_quantity"] = rerun
        return e


# ---------------------------------------------------------------------------
# features: the style of a turn, said to the phrasing model as a note and a shape with placeholders
# ---------------------------------------------------------------------------
FEATURES = {
    "en": {
        "only": ("say this is the only thing the holder has, with the number after the thing",
                 ["(holder) only has (things), N of them.", "All (holder) has is (things), N of them."]),
        "zero": ("say the holder has none at all, with no digit", ["(holder) has no (things) at all.",
                                                                   "(holder) doesn't have a single (thing).",
                                                                   "(holder) hasn't got any (things)."]),
        "vague": ("say the holder has some, with no number", ["(holder) has some (things) too.",
                                                             "(holder) also has some (things), not sure how many."]),
        "exact": ("give the number now, a short follow-up about the same things",
                  ["There are N of them, by the way.", "It's N (things), I just counted.", "N of them, to be exact."]),
        "vague_exact": ("two sentences: first that the holder has some, no number; then the number",
                        ["(holder) has some (things). N of them, actually."]),
        "also_some": ("the holder has the counted things and also some of the second thing, no number for it",
                      ["(holder) has N (things) and also some (other things)."]),
        "place_has": ("the things are in the place", ["(place) holds N (things).", "There are N (things) in (place).",
                                                      "N (things) are in (place)."]),
        "first_person": ("the speaker talks about themselves: I, me, my", []),
        "relation": ("introduce the person by the relation and the name, as given", ["... {holder} ..."]),
        "relation_unnamed": ("refer to the person only by the given relation, with 'my', no name",
                             ["... {holder} ..."]),
        "apposition": ("introduce the person by the given role, then a comma and the titled name",
                       ["{Holder}, ..."]),
        "title": ("keep the title before the name", []),
        "has_got": ("use 'has got' or ''s got'", []), "holding": ("use 'is holding'", []),
        "carrying": ("use 'is carrying'", []), "keeps": ("use 'keeps'", []), "owns": ("use 'owns'", []),
        "responsible": ("say the holder is responsible for them", ["(holder) is responsible for N (things)."]),
        "lend": ("use the verb lend", []), "pass": ("use the verb pass", []),
        "hand_over": ("use 'hand over'", []),
        "give_back": ("the receiver had them before: use 'give back' or 'return'", []),
        "send": ("use the verb send", []), "transfer": ("use the verb transfer", []),
        "borrow": ("the receiver is the subject: 'borrowed ... from'", []),
        "receive": ("the receiver is the subject: 'got ... from' or 'received ... from'", []),
        "leave_at": ("the person left them at the place", ["(person) left N (things) at (place)."]),
        "move": ("someone moved them from the first place to the second; say both places",
                 ["We moved N (things) from (place) to (place)."]),
        "move_passive": ("passive, no person: they were moved from the first place to the second",
                         ["N (things) were moved from (place) to (place)."]),
        "take_from": ("the person took them from the place", ["(person) took N (things) from (place)."]),
        "use_up": ("the holder used them up", []), "use_for": ("the holder used them for something (an event, a "
                                                               "job)", ["(holder) used N (things) for the party."]),
        "lose": ("the holder lost them", []),
        "front_recipient": ("start the sentence with the receiver: 'To (receiver), ...'",
                            ["To (receiver), (giver) (verb) N (things)."]),
        "front_purpose": ("start the sentence with the purpose: 'For ..., ...' (a purpose, not a place or a name)",
                          ["For the trip, (the fact).", "For the fundraiser, (the fact)."]),
        "front_then": ("start the sentence with 'Then' or 'After that'", ["Then (the fact).",
                                                                         "After that, (the fact)."]),
        "adv_apparently": ("end with ', apparently'", ["(the fact), apparently."]),
        "adv_moment": ("add 'at the moment' or 'right now'", []),
        "partitive": ("count them with 'N of them' (or 'N of hers' / 'N of his') instead of naming the things",
                      ["... N of them ...", "... N of hers ...", "... N of his ..."]),
        "same": ("call the things 'the same' ones", ["... N of the same (things) ..."]),
        "q_got": ("use 'got'", ["How many (things) has (holder) got now?"]),
        "q_left": ("ask how many are left", ["How many (things) does (holder) have left?"]),
        "q_two_total": ("say 'the two of them' instead of the names", ["How many (things) do the two of them have "
                                                                       "in total?"]),
        "q_place_now": ("ask how many are in the place now", ["How many (things) are in (place) now?"]),
        "q_hold": ("use the verb hold", ["How many (things) does (holder) hold?"]),
        "q_plain": ("", []),
        "q_pronoun": ("use only 'she' or 'he', no name", ["How many (things) does she have now?",
                                                          "And how many (things) has he got now?"]),
        "repair": ("a short repair: only the name that was meant, not a question",
                   ["I mean (name).", "(name), I mean.", "(name) is who I meant.", "Sorry, I meant (name)."]),
        "correct_amount": ("a short self-correction with only the two numbers",
                           ["Sorry, it was N, not M.", "Wait, make that N, not M.", "Actually it was N, not M."]),
        "correct_recipient": ("a short self-correction: they went to the second person, not the first; call the "
                              "things 'them'", ["Wait, (giver) gave them to (new), not (old).",
                                                "Actually they went to (new), not (old)."]),
    },
    "ko": {
        "only": ("그 물건만 있다고, 수량은 물건 뒤에", ["(누구)은 (물건)만 N개 있어요."]),
        "zero": ("하나도 없다고, 숫자 없이", ["(누구)은 (물건)이 하나도 없어요.", "(누구)한테는 (물건)이 한 개도 없어요."]),
        "vague": ("좀 있다고만, 숫자 없이", ["(누구)도 (물건)이 좀 있어요.", "(누구)도 (물건)을 좀 가지고 있어요."]),
        "exact": ("그 수를 이제 짧게 덧붙이듯이", ["세어 보니 N개예요.", "정확히는 N개예요."]),
        "vague_exact": ("두 문장: 먼저 좀 있다고만, 다음 문장에서 수", ["(누구)도 (물건)이 좀 있어요. 세어 보니 N개네요."]),
        "also_some": ("센 물건과 함께 두 번째 물건도 좀 있다고, 두 번째는 숫자 없이", ["(누구)는 (물건)이 N개 있고 (다른 물건)도 좀 있어요."]),
        "place_has": ("그 장소에 있다", ["(장소)에는 (물건)이 N개 있어요.", "(물건) N개가 (장소)에 있어요."]),
        "first_person": ("말하는 사람이 자기 얘기를: 저/제가/나/내가", []),
        "relation": ("주어진 관계와 이름을 둘 다 그대로", ["{holder}은 ..."]),
        "relation_unnamed": ("이름 없이 주어진 관계 그대로 ('제'/'내'도 그대로)", ["{holder}은 ..."]),
        "apposition": ("주어진 직업과 이름을 그대로", ["{holder}가 ..."]),
        "title": ("이름 뒤에 호칭을 그대로", []),
        "hold": ("가지고 있다 / 갖고 있다", []), "carry": ("들고 있다", []), "keep": ("보관하고 있다", []),
        "responsible": ("맡고 있다", ["(물건) N개는 (누구)가 맡고 있어요."]),
        "lend": ("빌려주다", []), "pass": ("넘기다 / 넘겨주다", []), "hand_over": ("건네다 / 건네주다", []),
        "give_back": ("받는 쪽이 원래 주인: 돌려주다", []), "send": ("보내다", []),
        "borrow": ("받는 쪽이 주어: 빌리다", ["(받는 사람)이 (주는 사람)한테 (물건) N개를 빌렸어요."]),
        "receive": ("받는 쪽이 주어: 받다", ["(받는 사람)이 (주는 사람)한테서 (물건) N개를 받았어요."]),
        "leave_at": ("그 장소에 두고 오다 / 맡기다", ["(누구)가 (장소)에 (물건) N개를 두고 왔어요."]),
        "move": ("한 장소에서 다른 장소로 옮기다, 두 장소 모두", ["(물건) N개를 (장소)에서 (장소)로 옮겼어요."]),
        "move_passive": ("사람 없이, 한 장소에서 다른 장소로 옮겨졌다", ["(물건) N개가 (장소)에서 (장소)로 옮겨졌어요."]),
        "take_from": ("그 장소에서 가져가다", ["(누구)가 (장소)에서 (물건) N개를 가져갔어요."]),
        "use_up": ("다 써 버리다 / 쓰다", []), "use_for": ("어떤 일에 쓰다 / 사용하다", ["(누구)가 행사에 (물건) N개를 썼어요."]),
        "lose": ("잃어버리다", []),
        "front_recipient": ("받는 사람을 문장 맨 앞에", ["(받는 사람)한테는 (주는 사람)이 (물건) N개를 (동사)."]),
        "count_first": ("수량 표현을 문장 맨 앞에", ["(물건) N개를 (주는 사람)이 (받는 사람)한테 (동사)."]),
        "front_purpose": ("목적을 문장 앞에 (장소나 사람이 아닌 목적)", ["행사 때문에 (사실).", "이사 준비로 (사실)."]),
        "front_then": ("문장을 그다음에 / 그러고 나서 로 시작", ["그다음에 (사실).", "그러고 나서 (사실)."]),
        "adv_apparently": ("전해 들은 말로: 과거형 끝의 -어요를 -대요로 (예: {hearsay}), 또는 -다고 해요", []),
        "adv_moment": ("지금은 / 현재 를 넣어서", []),
        "partitive": ("물건 이름 대신 그중 / 그거 로", ["... 그중 N개를 ...", "... 그거 N개를 ..."]),
        "same": ("같은 물건이라고", ["... 같은 (물건) N개를 ..."]),
        "q_left": ("몇 개 남았는지", ["(누구)은 (물건)이 몇 개 남았어요?"]),
        "q_two_total": ("이름 없이 두 사람 / 둘이 합쳐서", ["두 사람 합쳐서 (물건)이 몇 개예요?", "둘이 합쳐서 (물건)이 모두 몇 개예요?"]),
        "q_place_now": ("지금 그 장소에 몇 개 있는지", ["지금 (장소)에 (물건)이 몇 개 있어요?"]),
        "q_hold": ("가지고 있다 로 묻기", ["(누구)은 (물건)을 몇 개 가지고 있어요?"]),
        "q_got": ("수 없이 '몇'으로 묻기", ["(누구)은 지금 (물건)이 몇 개 있어요?"]),
        "q_plain": ("수 없이 '몇'으로 묻기", ["(누구)은 지금 (물건)이 몇 개 있어요?",
                                        "(누구)한테 (물건)이 지금 몇 개 있어요?"]),
        "q_pronoun": ("이름 없이 그분 / 그 사람 / 걔 로", ["그분은 지금 (물건)이 몇 개 있어요?"]),
        "repair": ("방금 물은 사람을 바로잡는 짧은 말, 이름만, 물음 아님",
                   ["(이름) 말이에요.", "아, (이름)요.", "제 말은 (이름) 씨예요.", "(이름) 씨를 말한 거예요."]),
        "correct_amount": ("두 수만으로 짧게 바로잡기", ["아, M개가 아니라 N개였어요.", "잘못 말했어요, M개 말고 N개예요."]),
        "correct_recipient": ("받은 사람을 바로잡기: 처음 사람이 아니라 다른 사람, 물건과 수는 되풀이하지 않기",
                              ["아, (처음 사람)이 아니라 (다른 사람)한테 줬어요."]),
    },
}
EN_VERB_WORD = {"give": "gave", "lend": "lent", "pass": "passed", "hand_over": "handed over",
                "give_back": "gave back (or returned)", "send": "sent", "transfer": "transferred",
                "borrow": "borrowed", "receive": "received (or got)", "leave_at": "left", "move": "moved",
                "move_passive": "were moved", "take_from": "took", "use_up": "used up",
                "use_for": "used (for some purpose)", "lose": "lost",
                "has": "has", "has_got": "has got", "holding": "is holding", "carrying": "is carrying",
                "keeps": "keeps", "owns": "owns", "responsible": "is responsible for"}
KO_VERB_WORD = {"give": "주다", "lend": "빌려주다", "pass": "넘기다", "hand_over": "건네다", "give_back": "돌려주다",
                "send": "보내다", "borrow": "빌리다", "receive": "받다", "leave_at": "두고 오다", "move": "옮기다",
                "move_passive": "옮겨지다", "take_from": "가져가다", "use_up": "다 쓰다", "use_for": "쓰다",
                "lose": "잃어버리다", "exist": "있다", "hold": "가지고 있다", "carry": "들고 있다",
                "keep": "보관하고 있다", "responsible": "맡고 있다"}
KO_PAST_FORM = {"give": "줬어요", "lend": "빌려줬어요", "pass": "넘겼어요", "hand_over": "건넸어요",
                "give_back": "돌려줬어요", "send": "보냈어요", "borrow": "빌렸어요", "receive": "받았어요",
                "leave_at": "두고 왔어요", "move": "옮겼어요", "move_passive": "옮겨졌어요", "take_from": "가져갔어요",
                "use_up": "다 썼어요", "use_for": "썼어요", "lose": "잃어버렸어요"}


def _jong_of(ch):
    code = ord(ch) - 0xAC00
    return code % 28 if 0 <= code < 11172 else None


def fix_josa(text):
    """``윤우이(가)`` -> ``윤우가``: a particle pair written in an instruction takes the form the word before it
    selects (the model copies what it is shown, so it is shown the right form)."""
    def pick(m):
        word, pair = m.group(1), m.group(2)
        last = next((ch for ch in reversed(word) if _jong_of(ch) is not None), None)
        vowel = last is None or _jong_of(last) == 0
        if pair == "(으)로":
            return word + ("로" if vowel or _jong_of(last) == 8 else "으로")
        consonant_form, vowel_form = {"이(가)": ("이", "가"), "을(를)": ("을", "를"), "와(과)": ("과", "와"),
                                      "은(는)": ("은", "는")}[pair]
        return word + (vowel_form if vowel else consonant_form)
    return re.sub(r"(\S+?)(이\(가\)|을\(를\)|와\(과\)|은\(는\)|\(으\)로)", pick, text)


_KO_PAIR = {"은": "은(는)", "는": "은(는)", "이": "이(가)", "가": "이(가)", "을": "을(를)", "를": "을(를)",
            "와": "와(과)", "과": "와(과)"}


def _fill_ko(note, say):
    """A Korean shape with the turn's own holder, giver, receiver, place and thing in its placeholders, each
    followed by the particle its last syllable takes, and the thing's own counter after N (the model copies a
    shape's particles and counters as shown)."""
    words = {}
    item = say.get("item") or {}
    if item.get("noun"):
        words["물건"] = [item["noun"]]
        note = note.replace("N개", "N" + item["counter"])
    holder = say.get("holder") if isinstance(say.get("holder"), dict) else None
    giver, taker = say.get("giver"), say.get("taker")
    if holder:
        words["누구"] = [holder["who"]]
        if holder.get("kind") == "place":
            words["장소"] = [holder["who"]]
    if isinstance(giver, dict) and isinstance(taker, dict):
        words["주는 사람"], words["받는 사람"] = [giver["who"]], [taker["who"]]
        verb = say.get("verb")
        if verb == "take_from":
            words["누구"], words["장소"] = [taker["who"]], [giver["who"]]
        elif verb == "leave_at":
            words["누구"], words["장소"] = [giver["who"]], [taker["who"]]
        elif verb in ("move", "move_passive"):
            words["장소"] = [giver["who"], taker["who"]]
    used = {}

    def put(m):
        name, particle = m.group(1), m.group(2) or ""
        if name not in words:
            return m.group(0)
        options = words[name]
        word = options[min(used.get(name, 0), len(options) - 1)]
        used[name] = used.get(name, 0) + 1
        return word + (_KO_PAIR.get(particle, particle))
    return re.sub(r"\((누구|물건|장소|주는 사람|받는 사람)\)(은|는|이|가|을|를|와|과)?", put, note)


def to_register(text, register):
    """A 해요체 shape or example said in the dialogue's register (합쇼체 or 반말), so the model sees the endings
    it must write. Only the endings the shapes and examples use are converted."""
    if register == "haeyo":
        return text
    out = text
    if register == "hapsyo":
        out = re.sub(r"([가-힣])(?:어요|아요)(?=[.?!]|$|\s|\))",
                     lambda m: m.group(1) + ("습니다" if _jong_of(m.group(1)) in (18, 20) else "ㅂ니다"), out)
        out = re.sub(r"(?:이에요|예요)(?=[.?!]|$|\s|\))", "입니다", out)
        out = re.sub(r"네요(?=[.?!]|$|\s|\))", "습니다", out)
        out = re.sub(r"개습니다", "개입니다", out)
        out = re.sub(r"대요(?=[.?!]|$|\s|\))", "답니다", out)
        out = re.sub(r"([가-힣])요\.", lambda m: m.group(1) + "입니다.", out)
        out = out.replace("습니다?", "습니까?").replace("입니다?", "입니까?")
        # a syllable left open for ㅂ니다 (줘 -> 줍니다 is not a past form; the shapes use only the forms above)
        out = out.replace("ㅂ니다", "습니다")
        return out
    out = re.sub(r"([가-힣])(어|아)요(?=[.?!]|$|\s|\))", r"\1\2", out)
    out = re.sub(r"이에요(?=[.?!]|$|\s|\))", "이야", out)
    out = re.sub(r"예요(?=[.?!]|$|\s|\))", "야", out)
    out = re.sub(r"네요(?=[.?!]|$|\s|\))", "네", out)
    out = re.sub(r"대요(?=[.?!]|$|\s|\))", "대", out)
    out = re.sub(r"([가-힣])요\.", r"\1.", out)
    return out


def ko_verb(verb, register="haeyo"):
    """The verb as the fact line says it: the dictionary form and, for an event, its past form in the register."""
    past = KO_PAST_FORM.get(verb)
    return KO_VERB_WORD[verb] + (" (지난 일, 과거형: %s)" % to_register(past, register) if past else "")


def scenario(lang, half, index, vocab):
    """One dialogue's ground truth, or None when the draw breaks a constraint (the caller redraws)."""
    rng = random.Random("%d/%s/%s/%d" % (SCENARIO_SEEDS[half], lang, half, index))
    families = [f for f in FAMILIES if lang == "ko" or f != "korean_register"]
    primary = families[index % len(families)]
    focus = {primary} | set(rng.sample([f for f in families if f != primary], 2))
    p = Planner(lang, half, index, vocab, focus, rng)
    try:
        ok = _plan(p)
    except (KeyError, ValueError, IndexError) as exc:   # a draw that cannot be played out
        ok, p.error = False, str(exc)
    return p if ok else None


def _plan(p):
    rng, en, f = p.rng, p.lang == "en", p.focus
    cast = p.cast()
    x = p.item()
    y = p.item() if ("zero_vague" in f and rng.random() < 0.4) else None
    p.cast_list, p.items = cast, [i for i in (x, y) if i]
    first_person = "I" if en else "나"

    def token(h):
        return h.tokens[0] if h.tokens else first_person

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
        """The holder a relation was introduced with ('Omar's friend Lucas'): it may be named beside it."""
        return [c for c in cast if c.id == h.anchor]

    def hfeature(h, first):
        return {"title": "title", "relation": "relation", "relation_unnamed": "relation_unnamed",
                "apposition": "apposition", "first_person": "first_person"}.get(h.kind) if first else None

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
        if "zero_vague" in f:
            options += ["zero", "vague_exact", "vague", "only", "only"]
            if y is not None and h.kind != "place":
                options += ["also_some", "also_some"]
        styles[h.id] = rng.choice(options)
    if all(s == "zero" for s in styles.values()):
        styles[cast[0].id] = "plain"
    plain = [h for h in cast if styles[h.id] == "plain" and h.kind in ("name", "title")]
    merged = plain[:2] if len(plain) >= 2 and rng.random() < 0.4 else None
    vague = {}
    for h in cast:
        if merged and h is merged[1]:
            continue
        if merged and h is merged[0]:
            a, b = merged
            ma, mb = p.mention(a), p.mention(b)
            evs = [{"type": "has", "holder": a.entity, "item": x["key"], "quantity": start[a.id]},
                   {"type": "has", "holder": b.entity, "item": x["key"], "quantity": start[b.id]}]
            p.record(evs, {"act": "state", "what": "has_two", "holders": [dict(ma, n=start[a.id]),
                                                                          dict(mb, n=start[b.id])],
                           "item": x, "features": [ft for ft in (hfeature(a, ma["first"]), hfeature(b, mb["first"]))
                                                    if ft]},
                     spec([start[a.id], start[b.id]], [a, b], x, cues=hcues(a, ma["first"]) + hcues(b, mb["first"])),
                     hclasses(a, ma["first"]) + hclasses(b, mb["first"]) + ["multi_fact"], ["ownership"])
            continue
        m = p.mention(h)
        n, s = start[h.id], styles[h.id]
        cls, cues = hclasses(h, m["first"]), hcues(h, m["first"])
        feats = [ft for ft in (hfeature(h, m["first"]),) if ft]
        verb = "place" if h.kind == "place" else (rng.choice(HAS_VERBS[p.lang]) if s == "plain" else
                                                  HAS_VERBS[p.lang][0])
        if h.kind == "place":
            feats.append("place_has")
        say = {"act": "state", "what": "has", "holder": m, "n": n, "item": x, "verb": verb, "mode": s,
               "features": feats}
        events = [{"type": "has", "holder": h.entity, "item": x["key"], "quantity": n}]
        numbers, zero = [n], False
        if s == "plain":
            if verb in RARE_VERBS and "transfer_verbs" in f:
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
        elif s == "vague":
            feats.append("vague"), cls.append("zero_vague:vague"), cues.append("vague")
            events[0]["quantity"], numbers, say["n"] = None, [], None
            vague[h.id] = x
        elif s == "also_some":
            feats.append("also_some"), cls.append("zero_vague:also_some"), cues.append("vague")
            say["item2"] = y
            events.append({"type": "has", "holder": h.entity, "item": y["key"], "quantity": None})
            vague[h.id] = y
        check = spec(numbers, [h], x, cues=cues, zero=zero)
        if s == "also_some":
            check["item2"] = y["key"]
        p.record(events, say, check, cls, ["ownership"])

    # a vague count asked about is held; the number comes later
    for hid, item in list(vague.items()):
        h = next(c for c in cast if c.id == hid)
        if item is x and rng.random() < 0.7:
            if rng.random() < 0.6:
                m = p.mention(h)
                p.other({"act": "hold", "entity": h.entity, "quantity": None, "relation": "count",
                         "evidence": {"turns": [len(p.turns) + 1]}, "item": item["key"]},
                        {"act": "ask", "what": "vague", "holder": m, "item": item, "features": []},
                        spec([], [h], item, question=True), ["zero_vague:vague_asked"], ["missing_premise"], "hold")
            m = p.mention(h)
            n = start[hid]
            p.record([{"type": "has", "holder": h.entity, "item": item["key"], "quantity": n}],
                     {"act": "state", "what": "exact", "holder": m, "n": n, "item": item, "features": ["exact"]},
                     spec([n], [], item, anaphor=True, cues=["first_person"] if h.kind == "first_person" else [],
                          may=[h]),
                     ["zero_vague:exact_later"], ["ownership"])
            del vague[hid]
        elif item is not x and rng.random() < 0.5:
            m = p.mention(h)
            p.other({"act": "hold", "entity": h.entity, "quantity": None, "relation": "count",
                     "evidence": {"turns": [len(p.turns) + 1]}, "item": item["key"]},
                    {"act": "ask", "what": "vague", "holder": m, "item": item, "features": []},
                    spec([], [h], item, question=True), ["zero_vague:vague_asked"], ["missing_premise"], "hold")
    unknown = {hid for hid, item in vague.items() if item is x}

    def counted(h):
        return h.id not in unknown and p.state.get((h.entity, x["key"])) is not None

    def fresh():
        """Holders with a known, non-zero count that changed since they were last asked about."""
        return [h for h in cast if counted(h) and p.state.get((h.entity, x["key"])) not in (None, 0)
                and p.last_ask.get(h.entity, -1) < p.last_change.get(h.entity, 0)]

    def ask(h, form=None):
        p.last_ask[h.entity] = len(p.turns) + 1
        m = p.mention(h)
        e = p.answer_expect(h, x)
        if h.kind == "place":
            form = "q_place_now"
        form = form or rng.choice(["q_plain", "q_plain", "q_left", "q_got" if en else "q_hold", "q_hold"])
        cls = ["question_forms:" + form] if form != "q_plain" else []
        cues = {"q_got": ["q_got"], "q_left": ["q_left"], "q_hold": ["q_hold"],
                "q_place_now": ["place:" + h.entity]}.get(form, [])
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
        pool = EN_TRANSFER if en else KO_TRANSFER
        return rng.choice([v for v in pool if v != "give"] if "transfer_verbs" in f else pool)

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

    # -- the body: events, each followed by a question or two ---------------------------------------
    last_event = None
    for step in range(rng.randint(1, 3)):
        givers = [h for h in cast if counted(h) and p.state[h.entity, x["key"]] >= 2]
        if not givers:
            break
        giver = rng.choice(givers)
        takers = [h for h in cast if h is not giver and (counted(h) or styles[h.id] == "zero")]
        if not takers:
            break
        zero = [h for h in takers if p.state.get((h.entity, x["key"])) == 0]
        taker = zero[0] if zero else rng.choice(takers)
        if rng.random() < 0.2 and step > 0 and giver.kind != "place":
            k = rng.randint(1, min(3, p.state[giver.entity, x["key"]] - 1))
            m = p.mention(giver)
            verb = rng.choice(USE_VERBS)
            feats = ["partitive"] if "partitives" in f and rng.random() < 0.5 else []
            p.record([{"type": "use", "holder": giver.entity, "item": x["key"], "quantity": k}],
                     {"act": "state", "what": "use", "holder": m, "n": k, "item": x, "verb": verb,
                      "features": [verb] + feats},
                     spec([k], [giver], x, anaphor=bool(feats), cues=feats + hcues(giver, m["first"])),
                     ["transfer_verbs:" + verb] + ["partitives:" + ft for ft in feats] + hclasses(giver, m["first"]),
                     ["transfer"])
            last_event = None
        else:
            k = rng.randint(1, min(5, p.state[giver.entity, x["key"]] - 1))
            verb = pick_verb(giver, taker)
            feats = []
            if "fronting" in f and rng.random() < 0.7:
                ft = rng.choice(["front_recipient", "front_purpose", "front_then", "adv_apparently"]
                                + ([] if en else ["count_first", "count_first"]))
                if verb == "move_passive" or (ft == "front_recipient" and (
                        taker.kind == "place" or verb in ("borrow", "receive", "take_from"))) or (
                        ft == "count_first" and verb in ("move", "move_passive")):
                    ft = "front_then"
                feats.append(ft)
            if "partitives" in f and rng.random() < 0.6:
                feats.append(rng.choice(["partitive", "partitive", "same"]))
            last_event = transfer(giver, taker, k, verb, feats)
        for _ in range(rng.choice([1, 1, 2])):
            candidates = fresh()
            if not candidates:
                break
            moved = [h for h in candidates if p.last_change.get(h.entity) == len(p.turns) - (
                0 if p.turns[-1]["expect"]["act"] == "record" else 1)]
            h = rng.choice(moved if moved and rng.random() < 0.75 else candidates)
            ask(h)

    # -- a correction of the last transfer: its amount, or its recipient -----------------------------
    if last_event is not None and ("partitives" in f or rng.random() < 0.3):
        ev = p.by_turn[last_event][0]
        giver = next(h for h in cast if h.entity == ev["from"])
        taker = next(h for h in cast if h.entity == ev["to"])
        others = [h for h in cast if h not in (giver, taker) and h.kind != "place" and counted(h)]
        if "partitives" in f and others and taker.kind != "place" and rng.random() < 0.6:
            new = rng.choice(others)
            k = ev["quantity"]
            p.state[taker.entity, x["key"]] -= k
            p.state[new.entity, x["key"]] += k
            new_event = dict(ev, to=new.entity)
            p.by_turn[last_event] = [new_event]
            p.correction = {"target": last_event, "field": "to", "old": taker.entity, "new": new.entity, "event": ev}
            n = len(p.turns) + 1
            for key in (giver.entity, taker.entity, new.entity):
                p.touched.setdefault(key, []).append(n)
                p.last_change[key] = n
            mn, mo, mg = p.mention(new), p.mention(taker), p.mention(giver)
            check = spec([], [new, taker], None, anaphor=True, cues=["not"], may=[giver])
            check["contrast"] = {"new": token(new), "old": token(taker)}
            p.other({"act": "revise", "entity": None, "quantity": None, "relation": None,
                     "evidence": {"turns": [last_event, n]}, "target_turn": last_event, "replaces": [ev],
                     "with": [new_event], "state": [{"entity": e, "item": x["key"], "quantity": p.state[e, x["key"]]}
                                                    for e in (giver.entity, taker.entity, new.entity)]},
                    {"act": "correct", "what": "recipient", "giver": mg, "new": mn, "old": mo, "item": x,
                     "features": ["correct_recipient"]},
                    check, ["partitives:gave_them_not", "corrections:recipient"], ["correction"], "correction")
        else:
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
                         "with": [new_event], "state": [{"entity": e, "item": x["key"],
                                                         "quantity": p.state[e, x["key"]]}
                                                        for e in (giver.entity, taker.entity)]},
                        {"act": "correct", "what": "amount", "new": new, "old": old, "item": x,
                         "features": ["correct_amount"]},
                        check, ["corrections:amount"], ["correction"], "correction")
        if p.correction:
            live = [h for h in cast if counted(h) and p.state.get((h.entity, x["key"])) not in (None, 0)
                    and h.entity in (p.correction["event"]["from"], p.correction["event"]["to"],
                                     p.correction.get("new"))]
            live = [h for h in live if h in fresh()]
            if live:
                ask(rng.choice(live))

    # -- referent repairs: a pronoun two people could mean, or the wrong name, then "I mean X" ----------
    persons = [h for h in cast if h.kind in ("name", "title", "relation", "apposition") and counted(h)
               and p.state.get((h.entity, x["key"])) not in (None, 0)]
    if "referent_repairs" in f and len(persons) >= 2:
        a, b = rng.sample(persons, 2)
        same = [h for h in persons if h is not a and (not en or h.gender == a.gender)]
        if rng.random() < 0.5 and same:
            b = same[0]
            pron = ("she" if a.gender == "f" else "he") if en else rng.choice(["그분", "그 사람", "걔"])
            p.other({"act": "clarify", "entity": None, "quantity": None, "relation": None,
                     "evidence": {"turns": [len(p.turns) + 1]}, "candidates": sorted([a.entity, b.entity])},
                    {"act": "ask", "what": "pronoun", "pronoun": pron, "item": x, "features": ["q_pronoun"]},
                    spec([], [], x, question=True, absent=a.tokens + b.tokens, cues=["pronoun"]),
                    ["referent_repairs:pronoun_asked"], ["ambiguous_referent"], "ambiguous")
            asked = None
        else:
            ask(b)
            asked = b
        ma = p.mention(a)
        p.other(p.answer_expect(a, x),
                {"act": "repair", "meant": ma, "asked": p.mention(asked) if asked else None, "item": x,
                 "features": ["repair"]},
                spec([], [a], None, cues=["repair"], may=[asked] if asked else []), ["referent_repairs:i_mean"],
                ["ambiguous_referent"] + p.tags_for(a.entity), "answerable")
    elif len(persons) >= 2 and rng.random() < 0.25:
        a, b = rng.sample(persons, 2)
        va, vb = p.state[a.entity, x["key"]], p.state[b.entity, x["key"]]
        p.other({"act": "answer", "entity": a.entity if va > vb else b.entity, "quantity": None, "relation": "more",
                 "candidates": [a.entity, b.entity], "item": x["key"],
                 "evidence": {"turns": sorted(set(p.evidence(a.entity) + p.evidence(b.entity)))}},
                {"act": "ask", "what": "more", "a": p.mention(a), "b": p.mention(b), "item": x, "features": []},
                spec([], [a, b], x, question=True), [], ["transfer"], "answerable")

    # -- a total, and sometimes why ------------------------------------------------------------------
    counted_now = [h for h in cast if counted(h)]
    pairs = [(a, b) for a in counted_now for b in counted_now
             if a.id < b.id and (a.kind == "place") == (b.kind == "place")]
    if pairs and ("question_forms" in f or rng.random() < 0.35):
        a, b = rng.choice(pairs)
        total = p.state[a.entity, x["key"]] + p.state[b.entity, x["key"]]
        # 'the two of them' is said only where two holders are all the dialogue has
        form = "q_two_total" if a.kind != "place" and len(cast) == 2 and rng.random() < 0.8 else "q_plain"
        p.other({"act": "answer", "entity": [a.entity, b.entity], "quantity": total, "relation": "total",
                 "evidence": {"turns": sorted(set(p.evidence(a.entity) + p.evidence(b.entity)))}, "item": x["key"]},
                {"act": "ask", "what": "total", "a": p.mention(a), "b": p.mention(b), "item": x,
                 "features": [form] if form != "q_plain" else []},
                spec([], [] if form == "q_two_total" else [a, b], x, question=True,
                     allow=[2] if form == "q_two_total" else [],
                     cues=["two_of_them"] if form == "q_two_total" else []),
                ["question_forms:q_two_total"] if form == "q_two_total" else [], ["transfer"], "answerable")
    whys = [h for h in cast if counted(h) and p.state.get((h.entity, x["key"])) not in (None, 0)
            and h.kind != "first_person"]
    if whys and rng.random() < 0.15:
        h = rng.choice(whys)
        p.other({"act": "explain", "entity": h.entity, "quantity": p.state[h.entity, x["key"]], "relation": "count",
                 "evidence": {"turns": p.evidence(h.entity)}, "item": x["key"]},
                {"act": "ask", "what": "why", "holder": p.mention(h), "item": x, "features": []},
                spec([], [h], x, question=True), [], ["why"], "why")
    if "korean_register" in f and p.lang == "ko":
        p.classes.add("korean_register:" + p.register)
    return _valid(p)


def _valid(p):
    turns = p.turns
    if not 4 <= len(turns) <= 10 or sum(t["label"] == "answerable" for t in turns) < 2:
        return False
    for t in turns:
        e = t["expect"]
        if e["act"] != "answer":
            continue
        state = _state_at(turns, t["n"])
        if e["relation"] in ("count", "total") and (e["quantity"] is None or e["quantity"] <= 0):
            return False
        if e["relation"] == "count" and any(v == e["quantity"] for (h, i), v in state.items()
                                            if i == e["item"] and h != e["entity"]):
            return False
        if e["relation"] == "more":
            a, b = e["candidates"]
            if None in (state.get((a, e["item"])), state.get((b, e["item"]))) or \
                    state[a, e["item"]] == state[b, e["item"]]:
                return False
    return True


def _state_at(turns, upto):
    """State after the turns before ``upto``, corrections applied (as the scorer replays it)."""
    replaced = {t["expect"]["target_turn"]: t["expect"]["with"] for t in turns[:upto]
                if t["expect"]["act"] == "revise"}
    state = {}
    for t in turns[:upto]:
        if t["expect"]["act"] == "record":
            for ev in replaced.get(t["n"], t["expect"]["events"]):
                if ev["type"] == "has":
                    state[ev["holder"], ev["item"]] = ev["quantity"]
                elif ev["type"] == "use":
                    state[ev["holder"], ev["item"]] -= ev["quantity"]
                else:
                    state[ev["from"], ev["item"]] -= ev["quantity"]
                    state[ev["to"], ev["item"]] = state.get((ev["to"], ev["item"]), 0) + ev["quantity"]
    return state


def scenario_json(p, sid):
    return {"id": sid, "language": p.lang, "half": p.half, "index": p.index, "register": p.register,
            "focus": sorted(p.focus), "holders": [h.json() for h in p.cast_list], "items": p.items,
            "classes": sorted(p.classes | {c for t in p.turns for c in t["classes"]}), "turns": p.turns}


def generate_scenarios(count=PER_HALF, extra=100):
    """For each half and language, ``count + extra`` scenarios by index (a draw that breaks a constraint is
    redrawn at the next index); the phrasing step takes them in order until ``count`` are phrased."""
    vocab = halves()
    out = []
    for half in ("build", "check"):
        for lang in LANGS:
            index, made = 0, 0
            while made < count + extra:
                p = scenario(lang, half, index, vocab[half][lang])
                index += 1
                if p is None:
                    continue
                made += 1
                out.append(scenario_json(p, "s4_%s_%s_%03d" % (lang, half[0], index)))
    return out


# ---------------------------------------------------------------------------
# prompts: the structured facts of a turn, said in the dialogue's language
# ---------------------------------------------------------------------------
REGISTER_NOTE = {
    "en": {"casual": "casual, like a text message between friends (contractions are fine)",
           "neutral": "plain everyday English",
           "formal": "polite and businesslike, like a note to a colleague"},
    "ko": {"haeyo": "해요체 (-어요/-아요/-예요, 물음은 -요?)",
           "hapsyo": "합쇼체 (-습니다/-ㅂ니다, 물음은 -습니까?/-ㅂ니까?)",
           "banmal": "친한 사이의 반말 (-어/-아/-야, -요 없이)"},
}
SYSTEM = {
    "en": ("You write one message of the user's side of a chat. The user is an adult keeping an assistant up to "
           "date about who has how many of something, and sometimes asks the assistant about it. Write the next "
           "message in natural English, {register}, the way people really type: complete, grammatical sentences, "
           "no lists.\n\n"
           "Rules:\n"
           "- Say exactly the fact or question given: the same people, places, things and numbers, and the same "
           "direction (who gives, who receives).\n"
           "- Write every given number, as digits or as a word; add no other number.\n"
           "- Use the given names, titles and places; add no other name, place or thing.\n"
           "- The speaker is 'I'. Never write 'the speaker' or 'the user'.\n"
           "- A QUESTION ends with a question mark and does not answer itself. A FACT or a REPAIR is not a question.\n"
           "- Follow the style note. A shape in a style note shows the pattern with placeholders in brackets; fill "
           "them with the turn's own words and never write the brackets.\n"
           "- No greetings, no thanks, no quotation marks, no explanations. Write only the message.\n\n"
           "Examples, with other people and things than yours (never use these words):\n"
           "FACT. holder: Rowan / verb: has / things: 4 jars  ->  Rowan's got 4 jars.\n"
           "FACT. giver: Rowan / receiver: Quinn / things: 2 jars / verb: lent  ->  Rowan lent Quinn two jars.\n"
           "QUESTION (the user asks; do not answer it). the number of jars Quinn has now  ->  "
           "How many jars does Quinn have now?\n"
           "FACT. a correction of the last transfer: the number was 3, not 2  ->  Sorry, that was 3, not 2."),
    "ko": ("당신은 채팅에서 사용자 쪽 메시지 하나를 씁니다. 사용자는 어른이고, 누가 무엇을 몇 개 가지고 있는지 비서에게 "
           "알려 주거나 물어봅니다. 다음 메시지를 자연스러운 한국어 {register}로 한 번만 씁니다. 실제 한국 사람이 채팅에 "
           "쓰듯이, 조사를 바르게 쓴 완전한 문장으로 씁니다.\n\n"
           "규칙:\n"
           "- 주어진 사실이나 물음을 그대로 말합니다. 사람, 장소, 물건, 수, 누가 주고 누가 받는지를 바꾸지 않습니다.\n"
           "- 주어진 수는 반드시 씁니다. 수는 숫자(3개)나 고유어 수사(세 개)로 쓰고, 삼 개 같은 한자어 수사는 쓰지 "
           "않습니다. 다른 수는 덧붙이지 않습니다.\n"
           "- 주어진 이름, 호칭, 장소만 씁니다. 다른 이름, 장소, 물건을 덧붙이지 않습니다. 영어와 한자를 쓰지 않습니다.\n"
           "- 말하는 사람 자신은 저/제가/나/내가 로 말합니다. '사용자', '말하는 사람'이라는 말은 쓰지 않습니다.\n"
           "- 물음이면 물음표로 끝나고 답을 말하지 않습니다. 사실이나 바로잡기면 물음이 아닙니다.\n"
           "- 말투 지시를 따릅니다. 모양 예시의 괄호는 자리 표시입니다. 그 턴의 낱말로 채우고 괄호는 쓰지 않습니다.\n"
           "- 인사, 감사, 따옴표, 설명 없이 메시지만 씁니다.\n\n"
           "예시 (다른 사람과 물건입니다. 이 낱말들은 쓰지 않습니다):\n"
           "사실. 가진 쪽: 수호 / 물건: 화분 4개, 고유어로 네 개 / 동사: 있다  ->  수호는 화분이 네 개 있어요.\n"
           "사실. 주는 쪽: 수호 / 받는 쪽: 하람 / 물건: 화분 2개, 고유어로 두 개 / 동사: 빌려주다 (지난 일, 과거형: 빌려줬어요)"
           "  ->  수호가 하람이한테 화분 두 개를 빌려줬어요.\n"
           "사실. 받는 쪽 (주어): 저 / 준 쪽: 하람 / 물건: 화분 1개, 고유어로 한 개 / 동사: 받다 (지난 일, 과거형: 받았어요)"
           "  ->  저는 하람이한테서 화분 한 개를 받았어요.\n"
           "물음 (사용자가 비서에게 묻는 말, 답은 말하지 않음). 하람이(가) 지금 화분을(를) 몇 개 가지고 있는지  ->  "
           "하람이는 지금 화분이 몇 개 있어요?\n"
           "실제 메시지는 주어진 말투로 씁니다."),
}
# The Korean dialogues' instructions are written in English (the phrasing model follows English instructions
# more closely); the facts, examples and style notes stay in Korean words.
SYSTEM_KO_EN = (
    "You write one message of the user's side of a chat, in natural Korean. The user is an adult keeping an "
    "assistant up to date about who has how many of something, and sometimes asks the assistant about it. Write "
    "the next message in Korean, {register}, the way Korean adults really type in a chat: complete sentences "
    "with the right particles (은/는, 이/가, 을/를, 한테/에게, 한테서).\n\n"
    "Rules:\n"
    "- Say exactly the given fact (사실) or question (물음): the same people, places, things and numbers, and "
    "the same direction (who gives, who receives).\n"
    "- Write every given number, as digits (3개) or as a native Korean numeral (세 개), never a Sino-Korean one "
    "(삼 개). Add no other number.\n"
    "- Use only the given names, titles and places; add no other name, place or thing. No English letters and "
    "no Chinese characters.\n"
    "- The speaker speaks of themselves as 저/제가 (나/내가 in 반말).\n"
    "- A question (물음) is asked of the assistant: it ends with '?', has no number in it, and does not answer "
    "itself. A fact or a correction (바로잡기) is not a question.\n"
    "- Follow the style note (말투). A shape (모양) shows a pattern with placeholders in brackets; fill them with "
    "the turn's own words and never write the brackets.\n"
    "- No greetings, no thanks, no quotation marks, no explanations. Write only the message.\n\n"
    "Examples, with other people and things than yours (never use these words); your message uses the register given above:\n"
    "사실. 가진 쪽: 수호 / 물건: 화분 4개, 고유어로 네 개 / 동사: 있다  ->  수호는 화분이 네 개 있어요.\n"
    "사실. 주는 쪽: 수호 / 받는 쪽: 하람 / 물건: 화분 2개, 고유어로 두 개 / 동사: 빌려주다 (지난 일, 과거형: 빌려줬어요)"
    "  ->  수호가 하람이한테 화분 두 개를 빌려줬어요.\n"
    "사실. 받는 쪽 (주어): 저 / 준 쪽: 하람 / 물건: 화분 1개, 고유어로 한 개 / 동사: 받다 (지난 일, 과거형: 받았어요)"
    "  ->  저는 하람이한테서 화분 한 개를 받았어요.\n"
    "물음 (사용자가 비서에게 묻는 말, 답은 말하지 않음). 하람이(가) 지금 화분을(를) 몇 개 가지고 있는지  ->  "
    "하람이는 지금 화분이 몇 개 있어요?\n"
    "바로잡기. 방금 말한 주고받기의 수가 2개이(가) 아니라 3개이었다  ->  아, 두 개가 아니라 세 개였어요.")
REGISTER_NOTE_KO_EN = {"haeyo": "in 해요체 (polite: every sentence ends in -요: 있어요, 줬어요, 몇 개예요?)",
                       "hapsyo": "in 합쇼체 (formal polite: every sentence ends in -습니다/-ㅂ니다, a question in "
                                 "-습니까?/-ㅂ니까?)",
                       "banmal": "in 반말 (casual: -어/-아/-야 endings, never -요)"}
KO_INSTRUCTIONS = "en"
KO_NATIVE_SAY = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉", 10: "열",
                 11: "열한", 12: "열두", 13: "열세", 14: "열네", 15: "열다섯", 16: "열여섯", 17: "열일곱", 18: "열여덟",
                 19: "열아홉", 20: "스무"}


def _amount(lang, n, item):
    if lang == "en":
        return "%d %s" % (n, item["one"] if n == 1 else item["plural"])
    c = item["counter"]
    # the native numeral is said after the word 고유어로, never alone in brackets: a bracketed amount is a
    # sentence of its own to a full-sentence comparison, and one other dialogue file has such a sentence
    return "%s %d%s, 고유어로 %s %s" % (item["noun"], n, c, KO_NATIVE_SAY.get(n, str(n)), c)


def _note(lang, feature, rng, attempt=0, verb=None):
    """The feature's note, with one of its shapes: a different one on each sampled attempt."""
    note, shapes = FEATURES[lang].get(feature, ("", []))
    if "{hearsay}" in note:
        past = KO_PAST_FORM.get(verb or "give", "줬어요")
        note = note.format(hearsay=past[:-2] + "대요")
    if not note and not shapes:
        return ""
    if shapes:
        shape = shapes[(rng.randrange(len(shapes)) + attempt) % len(shapes)]
        return "%s%s%s" % (note, " — " if note else "", ("shape: " if lang == "en" else "모양: ") + shape)
    return note


def render(scn, turn, attempt=0):
    """The phrasing model's instruction for one turn: its facts and its style notes."""
    lang, say = scn["language"], turn["say"]
    rng = random.Random("%s/%d" % (scn["id"], turn["n"]))
    en = lang == "en"
    act, what = say["act"], say.get("what")
    item = say.get("item")

    def w(m):
        return m["who"] if m else ""
    if en:
        if act == "state" and what == "has_two":
            a, b = say["holders"]
            line = "FACT. %s has %s and %s has %s." % (w(a), _amount(lang, a["n"], item), w(b),
                                                       _amount(lang, b["n"], item))
        elif act == "state" and what == "has":
            h, mode = say["holder"], say["mode"]
            if say["verb"] == "place":
                line = "FACT. place: %s / things: %s" % (w(h), _amount(lang, say["n"], item) if say["n"] else
                                                         item["plural"])
            else:
                line = "FACT. holder: %s / verb: %s / things: %s" % (
                    w(h), EN_VERB_WORD.get(say["verb"], "has"),
                    _amount(lang, say["n"], item) if say["n"] else item["plural"])
            line += {"plain": "", "only": " / nothing else", "zero": " / number: none at all (zero)",
                     "vague": " / number: unknown (say only 'some')",
                     "vague_exact": " / number: %d, said in a second sentence after 'some'" % (say["n"] or 0),
                     "also_some": " / also: some %s (number unknown)" % (say.get("item2") or {}).get("plural", "")
                     }[mode]
        elif act == "state" and what == "exact":
            line = "FACT. the %s %s has, said before as 'some', number: %d" % (item["plural"], w(say["holder"]),
                                                                            say["n"])
        elif act == "state" and what == "transfer":
            verb = say["verb"]
            if verb in ("move", "move_passive"):
                line = "FACT. from place: %s / to place: %s / things: %s / verb: moved" % (
                    w(say["giver"]), w(say["taker"]), _amount(lang, say["n"], item))
            elif verb == "leave_at":
                line = "FACT. person: %s / left at place: %s / things: %s" % (w(say["giver"]), w(say["taker"]),
                                                                           _amount(lang, say["n"], item))
            elif verb == "take_from":
                line = "FACT. person: %s / took from place: %s / things: %s" % (w(say["taker"]), w(say["giver"]),
                                                                             _amount(lang, say["n"], item))
            elif verb in ("borrow", "receive"):
                line = "FACT. receiver (the subject): %s / from: %s / things: %s / verb: %s" % (
                    w(say["taker"]), w(say["giver"]), _amount(lang, say["n"], item), EN_VERB_WORD[verb])
            else:
                line = "FACT. giver: %s / receiver: %s / things: %s / verb: %s" % (
                    w(say["giver"]), w(say["taker"]), _amount(lang, say["n"], item), EN_VERB_WORD[verb])
        elif act == "state" and what == "use":
            line = "FACT. holder: %s / things: %s / verb: %s" % (w(say["holder"]), _amount(lang, say["n"], item),
                                                               EN_VERB_WORD[say["verb"]])
        elif act == "ask" and what == "count":
            line = "QUESTION (the user asks; do not answer it). the number of %s %s has now" % (item["plural"], w(say["holder"]))
        elif act == "ask" and what == "place":
            line = "QUESTION (the user asks; do not answer it). the number of %s in %s now" % (item["plural"], w(say["holder"]))
        elif act == "ask" and what == "vague":
            line = "QUESTION (the user asks; do not answer it). the number of %s %s has" % (item["plural"], w(say["holder"]))
        elif act == "ask" and what == "total" and "q_two_total" in say.get("features", []):
            line = "QUESTION (the user asks; do not answer it). the number of %s the two of them have in total (no names)" % item["plural"]
        elif act == "ask" and what == "total":
            line = "QUESTION (the user asks; do not answer it). the number of %s %s and %s have in total" % (item["plural"], w(say["a"]), w(say["b"]))
        elif act == "ask" and what == "more":
            line = "QUESTION (the user asks; do not answer it). who has more %s now, %s or %s" % (item["plural"], w(say["a"]), w(say["b"]))
        elif act == "ask" and what == "pronoun":
            line = "QUESTION (the user asks; do not answer it). the number of %s '%s' has now (no name: it is unclear who is meant)" % (
                item["plural"], say["pronoun"])
        elif act == "ask" and what == "why":
            line = "QUESTION (the user asks; do not answer it). why %s has that many %s now" % (w(say["holder"]), item["plural"])
        elif act == "repair":
            line = ("REPAIR. the last question was %s; the speaker meant %s. Say only that %s is meant."
                    % ("about %s" % w(say["asked"]) if say["asked"] else "unclear", w(say["meant"]), w(say["meant"])))
        elif act == "correct" and what == "amount":
            line = "FACT. a correction of the last transfer: the number was %d, not %d" % (say["new"], say["old"])
        elif act == "correct" and what == "recipient":
            line = "FACT. a correction of the last transfer: %s gave them to %s, not to %s" % (
                w(say["giver"]), w(say["new"]), w(say["old"]))
        else:
            raise ValueError(say)
    else:
        def amount(n):
            return _amount(lang, n, item)
        if act == "state" and what == "has_two":
            a, b = say["holders"]
            line = "사실. %s: %s / %s: %s (한 번에 두 사람)" % (w(a), amount(a["n"]), w(b), amount(b["n"]))
        elif act == "state" and what == "has":
            h, mode = say["holder"], say["mode"]
            what_n = amount(say["n"]) if say["n"] else item["noun"]
            if say["verb"] == "place":
                line = "사실. 장소: %s / 있는 물건: %s" % (w(h), what_n)
            else:
                line = "사실. 가진 쪽: %s / 물건: %s / 동사: %s" % (w(h), what_n, KO_VERB_WORD.get(say["verb"], "있다"))
            line += {"plain": "", "only": " / 다른 물건은 없음", "zero": " / 수: 하나도 없음 (0)",
                     "vague": " / 수: 모름 (좀 있다고만)",
                     "vague_exact": " / 수는 두 번째 문장에서, 먼저 좀 있다고",
                     "also_some": " / 그리고 %s도 좀 (수 모름)" % (say.get("item2") or {}).get("noun", "")}[mode]
        elif act == "state" and what == "exact":
            line = "사실. 앞에서 좀 있다고 한 %s의 %s 수: %s" % (w(say["holder"]), item["noun"], amount(say["n"]))
        elif act == "state" and what == "transfer":
            verb = say["verb"]
            if verb in ("move", "move_passive"):
                line = "사실. 나간 장소: %s / 들어간 장소: %s / 물건: %s / 동사: %s" % (
                    w(say["giver"]), w(say["taker"]), amount(say["n"]), ko_verb(verb, scn["register"]))
            elif verb == "leave_at":
                line = "사실. 사람: %s / 두고 온 장소: %s / 물건: %s / 동사: %s" % (
                    w(say["giver"]), w(say["taker"]), amount(say["n"]), ko_verb("leave_at", scn["register"]))
            elif verb == "take_from":
                line = "사실. 사람: %s / 가져간 장소: %s / 물건: %s / 동사: %s" % (
                    w(say["taker"]), w(say["giver"]), amount(say["n"]), ko_verb("take_from", scn["register"]))
            elif verb in ("borrow", "receive"):
                line = "사실. 받는 쪽 (주어): %s / 준 쪽: %s / 물건: %s / 동사: %s" % (
                    w(say["taker"]), w(say["giver"]), amount(say["n"]), ko_verb(verb, scn["register"]))
            else:
                line = "사실. 주는 쪽: %s / 받는 쪽: %s / 물건: %s / 동사: %s" % (
                    w(say["giver"]), w(say["taker"]), amount(say["n"]), ko_verb(verb, scn["register"]))
        elif act == "state" and what == "use":
            line = "사실. 쓴 쪽: %s / 물건: %s / 동사: %s" % (w(say["holder"]), amount(say["n"]),
                                                      ko_verb(say["verb"], scn["register"]))
        elif act == "ask" and what == "count":
            line = "물음 (사용자가 비서에게 묻는 말, 답은 말하지 않음). %s이(가) 지금 %s을(를) 몇 %s 가지고 있는지" % (w(say["holder"]), item["noun"], item["counter"])
        elif act == "ask" and what == "place":
            line = "물음 (사용자가 비서에게 묻는 말, 답은 말하지 않음). 지금 %s에 %s이(가) 몇 %s 있는지" % (w(say["holder"]), item["noun"], item["counter"])
        elif act == "ask" and what == "vague":
            line = "물음 (사용자가 비서에게 묻는 말, 답은 말하지 않음). %s이(가) %s을(를) 몇 %s 가지고 있는지" % (w(say["holder"]), item["noun"], item["counter"])
        elif act == "ask" and what == "total" and "q_two_total" in say.get("features", []):
            line = "물음 (사용자가 비서에게 묻는 말, 답은 말하지 않음). 두 사람이 합쳐서 %s을(를) 몇 %s 가지고 있는지 (이름 없이 '두 사람' 또는 '둘이')" % (
                item["noun"], item["counter"])
        elif act == "ask" and what == "total":
            line = "물음 (사용자가 비서에게 묻는 말, 답은 말하지 않음). %s와(과) %s이(가) 합쳐서 %s을(를) 몇 %s 가지고 있는지" % (w(say["a"]), w(say["b"]), item["noun"],
                                                                  item["counter"])
        elif act == "ask" and what == "more":
            line = "물음 (사용자가 비서에게 묻는 말, 답은 말하지 않음). %s와(과) %s 중 누가 지금 %s을(를) 더 많이 가지고 있는지" % (w(say["a"]), w(say["b"]), item["noun"])
        elif act == "ask" and what == "pronoun":
            line = "물음 (사용자가 비서에게 묻는 말, 답은 말하지 않음). 이름 없이 '%s'(으)로 가리켜서, 지금 %s이(가) 몇 %s 있는지 (누구인지 분명하지 않음)" % (
                say["pronoun"], item["noun"], item["counter"])
        elif act == "ask" and what == "why":
            line = "물음 (사용자가 비서에게 묻는 말, 답은 말하지 않음). %s이(가) 왜 지금 %s을(를) 그만큼 가지고 있는지" % (w(say["holder"]), item["noun"])
        elif act == "repair":
            line = "바로잡기. 방금 물음은 %s, 사실은 %s을(를) 말한 것이다. %s만 짧게 바로잡기." % (
                ("%s에 대한 것이었는데" % w(say["asked"])) if say["asked"] else "누구인지 분명하지 않았는데",
                w(say["meant"]), w(say["meant"]))
        elif act == "correct" and what == "amount":
            line = "바로잡기. 방금 말한 주고받기의 수가 %d%s이(가) 아니라 %d%s이었다" % (
                say["old"], item["counter"], say["new"], item["counter"])
        elif act == "correct" and what == "recipient":
            line = "바로잡기. %s이(가) 준 것은 %s이(가) 아니라 %s한테 간 것이었다" % (
                w(say["giver"]), w(say["old"]), w(say["new"]))
        else:
            raise ValueError(say)
    features = list(say.get("features", []))
    mentions = [m for m in [say.get(k) for k in ("holder", "giver", "taker", "meant", "new", "old")]
                + list(say.get("holders") or []) if isinstance(m, dict) and m.get("first")]
    if not en and act == "ask" and what in ("count", "vague") and not any(f.startswith("q_") for f in features):
        features.append("q_plain")
    if not en:
        line = fix_josa(line)
    notes = []
    for ft in features:
        note = _note(lang, ft, rng, attempt, say.get("verb"))
        if "{holder}" in note.lower():
            who = next((m["who"] for m in mentions if m.get("kind") == ft), None)
            if who is None:
                continue
            last = _jong_of(who[-1])
            note = (note.replace("{holder}은", who + ("는" if last == 0 else "은"))
                    .replace("{holder}가", who + ("가" if last == 0 else "이"))
                    .replace("{holder}", who).replace("{Holder}", who[:1].upper() + who[1:]))
        if note:
            notes.append(note)
    if not en and scn["register"] != "haeyo":
        notes.append({"hapsyo": "끝맺음은 합쇼체 (-습니다 / -습니까?)", "banmal": "끝맺음은 반말 (-어 / -야, -요 없이)"}[
            scn["register"]])
    if not en:
        notes = [fix_josa(_fill_ko(to_register(n, scn["register"]), say)) for n in notes]
    if notes:
        line += ("\nStyle: " if en else "\n말투: ") + "; ".join(notes)
    return line


FEEDBACK = {
    "en": {"question_mark": "It must be a question to the assistant, ending with '?', that does not answer itself.",
           "statement_is_question": "It must be a statement, not a question.",
           "question_with_preamble": "Write the question as one sentence, nothing before it.",
           "meta_question": "Ask the question itself; do not talk about asking.",
           "missing_name": "Name everyone the fact names, as given.", "missing_number": "Say every given number.",
           "extra_number": "Use no number other than the given ones.",
           "direction": "Keep who gives and who receives exactly as given.", "verb": "Use the given verb.",
           "cue": "Follow the style note.", "missing_item": "Name the things, as given.",
           "other_holder": "Name only the people and places of this fact.",
           "too_many_sentences": "One or two sentences only.", "contrast": "Say the new value, then 'not' the old one.",
           "relation_owner": "Say 'my' before the relation, as given (my cousin).",
           "missing_item2": "Name the second thing exactly as given."},
    "ko": {"question_mark": "비서에게 묻는 물음으로, 물음표로 끝내고 답은 말하지 않습니다.",
           "statement_is_question": "물음이 아니라 사실을 말하는 문장입니다.",
           "question_with_preamble": "물음 한 문장만 씁니다.", "meta_question": "묻는다는 말 없이 물음만 씁니다.",
           "register": "모든 문장을 주어진 말투({register})로 끝냅니다.",
           "missing_name": "주어진 이름을 모두 씁니다.", "missing_number": "주어진 수를 모두 씁니다.",
           "extra_number": "주어진 수 말고 다른 수는 쓰지 않습니다.",
           "direction": "누가 주고 누가 받는지 그대로: 받는 쪽에 -한테/-에게, 준 쪽에서 받을 때는 -한테서.",
           "direction_unmarked": "받는 사람에 -한테 또는 -에게를 붙입니다.", "verb": "주어진 동사를 씁니다.",
           "cue": "말투 지시를 따릅니다.", "missing_item": "물건 이름을 씁니다.",
           "particle": "명사 뒤 조사를 받침에 맞게 씁니다 (을/를, 이/가, 은/는, 으로/로).",
           "hearsay_form": "전해 들은 말은 과거형에 -대요 (보냈대요, 줬대요) 로 씁니다.",
           "counted_object_as_subject": "물건 수 뒤에는 -를/-을 을 씁니다 (접시 세 개를 맡고 있어요).",
           "person_as_place": "사람 뒤에는 -에/-에서 대신 -한테/-에게 를 씁니다.",
           "too_many_sentences": "한두 문장만 씁니다.", "contrast": "'M개가 아니라 N개' 처럼 바로잡습니다.",
           "relation_owner": "관계 앞의 '제'(반말은 '내')를 그대로 씁니다 (제 룸메이트).",
           "missing_item2": "두 번째 물건 이름을 주어진 그대로 씁니다.",
           "glued": "이름과 조사를 바르게 띄어 씁니다 (조사는 하나만).", "ellipsis": "말줄임표 없이 씁니다."},
}


def _feedback(lang, reason, register):
    table = FEEDBACK[lang]
    key = reason.split(":")[0]
    if key == "cue" and reason.split(":")[1] in FEATURES[lang]:
        note, shapes = FEATURES[lang][reason.split(":")[1]]
        said = note + ((" — " + ("shape: " if lang == "en" else "모양: ") + shapes[0]) if shapes else "")
        if said.strip():
            return said if lang == "en" else to_register(said, register)
    text = table.get(key) or table.get(reason)
    if not text:
        return None
    return text.format(register=REGISTER_NOTE[lang][register]) if "{register}" in text else text


def prompt_messages(scn, turn, said, attempt=0, rejected=None):
    """The instruction for one turn; ``rejected`` is the checker's reason for the previous sample, said back
    to the model as a rule to keep (the checker still decides)."""
    lang = scn["language"]
    if lang == "ko" and KO_INSTRUCTIONS == "en":
        system = SYSTEM_KO_EN.format(register=REGISTER_NOTE_KO_EN[scn["register"]])
    else:
        system = SYSTEM[lang].format(register=REGISTER_NOTE[lang][scn["register"]])
    if lang == "ko":
        lines = system.split("\n")
        system = fix_josa("\n".join(to_register(line, scn["register"]) if "->" in line else line for line in lines))
    so_far = "\n".join("User: %s" % s for s in said[-3:]) or "(nothing yet)"
    if lang == "en":
        user = "Conversation so far:\n%s\n\nNext message:\n%s" % (so_far, render(scn, turn, attempt))
    else:
        user = "지금까지의 대화:\n%s\n\n다음 메시지:\n%s" % (so_far.replace("(nothing yet)", "(아직 없음)"),
                                                       render(scn, turn, attempt))
    note = _feedback(lang, rejected, scn["register"]) if rejected else None
    if note:
        user += ("\n(The last try was not usable: %s)" if lang == "en" else "\n(앞의 시도는 쓸 수 없었습니다: %s)") % note
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
# the checker
# ---------------------------------------------------------------------------
EN_FIRST = re.compile(r"(?<![A-Za-z'])(I|I'm|I've|I'd|I'll|me|my|mine|myself)(?![A-Za-z'])")
KO_FIRST = re.compile(r"(?<![가-힣])(저는|저도|저한테|저에게|저의|제가|제게|제|저|나는|나도|나한테|나에게|내가|내게|내|나)(?![가-힣])")
EN_CUES = {
    "only": r"\bonly\b|\ball (?:\w+ )?(?:has|have|had|got)\b|\bjust\b",
    "zero": r"\bno\b|\bnone\b|\bzero\b|\bany\b|\bnot a single\b|n't (?:have|has|got)",
    "vague": r"\bsome\b",
    "q_got": r"\bgot\b",
    "q_left": r"\bleft\b|\bremain",
    "q_hold": r"\bhold",
    "two_of_them": r"\btwo of them\b|\bboth of them\b|\bthe two\b|\bboth\b",
    "front_recipient": r"^\s*(?:and\s+|so\s+|then\s+)?to\s",
    "front_purpose": r"^\s*(?:and\s+|so\s+)?for\s",
    "front_then": r"^\s*(?:and\s+)?(?:then|after that|afterwards|next|later)\b",
    "adv_apparently": r"\bapparently\b|\bi heard\b|\bit seems\b|\bseemingly\b",
    "adv_moment": r"\bat the moment\b|\bright now\b|\bcurrently\b|\bnow\b|\bat present\b",
    "partitive": r"\b(?:\w+) of (?:them|hers|his|theirs|those|these|mine|yours|ours)\b",
    "same": r"\bsame\b",
    "repair": r"\bmean\b|\bmeant\b|\btalking about\b|\bwho i\b",
    "not": r"\bnot\b|n't\b|\binstead\b",
    "pronoun": r"\b(?:she|he|her|him)\b",
}
KO_CUES = {
    "only": r"만\s|만$|만[이가을를은는도]|밖에",
    "zero": r"없",
    "vague": r"좀|조금|약간|몇\s?(?:개|자루|장|권|병|켤레|대|벌|묶음)\s?(?:있|가지)|여러",
    "q_left": r"남",
    "q_hold": r"가지고|갖고|들고|보관|맡",
    "two_of_them": r"둘이|두 사람|두 분|둘 다|둘을|두 명|둘은|둘의|둘 합|둘 모두",
    "front_recipient": r"^\s*[가-힣]+(?:\s씨|\s님|님)?\s?(?:한테|에게|께)(?:는|도)?\s",
    "count_first": r"^\s*(?:[가-힣]+\s)?(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열[가-힣]*|스무|스물[가-힣]*)\s?(?:개|자루|장|권|병|켤레|대|벌|묶음)",
    "front_purpose": r"^\s*[^,]{0,20}(?:때문에|위해서|위해|용으로|하려고|으로 쓰려고|로 쓰려고|준비로|준비하느라)",
    "front_then": r"^\s*(?:그다음에|그 다음에|그러고 나서|그리고 나서|그 뒤에|그 후에|그 후|그다음|이어서|그런 다음)",
    "adv_apparently": r"대요|래요|다고 해요|다고 합니다|답니다|대\.|래\.|다더라|다고 하더라|다네요|다고 하네요|랍니다",
    "adv_moment": r"지금|현재|이제",
    "partitive": r"그중|그 중|그거|그것|그 가운데|그것들|중에서|중에",
    "same": r"같은",
    "repair": r"말이에요|말이야|말입니다|말한 거|말씀|말했|요\.?\s*$|이에요\.?\s*$|예요\.?\s*$|입니다\.?\s*$|이야\.?\s*$|야\.?\s*$|라고요",
    "not": r"아니라|아니고|말고|아니에요|아닙니다|아니야",
    "pronoun": r"그분|그 사람|걔|그 애|그 친구|그녀|그는",
}
KO_TITLES = ("씨", "님")
# the verb of the turn's class must be the verb the phrasing uses (a class tag says what the text does)
EN_VERB_CUES = {
    "give": r"\bg[ai]ve[sn]?\b|\bgiving\b", "lend": r"\blen[dt]s?\b|\blending\b|\bloan",
    "pass": r"\bpass(?:ed|es|ing)?\b", "hand_over": r"\bhand(?:ed|s|ing)?\b.{0,40}\bover\b",
    "give_back": r"\bg[ai]ve[sn]?\b.{0,40}\bback\b|\breturn(?:ed|s|ing)?\b",
    "send": r"\bsen[dt]s?\b|\bsending\b", "transfer": r"\btransfer(?:red|s|ring)?\b",
    "borrow": r"\bborrow(?:ed|s|ing)?\b", "receive": r"\breceiv(?:e|ed|es|ing)\b|\bgot\b|\bgets?\b",
    "leave_at": r"\bleft\b|\bleav(?:e|es|ing)\b|\bdropped off\b", "move": r"\bmov(?:e|ed|es|ing)\b",
    "move_passive": r"\b(?:were|was|got|have been|had been)\s+moved\b",
    "take_from": r"\btook\b|\btak(?:e|es|en|ing)\b", "use_up": r"\bus(?:e|ed|es|ing)\b.{0,30}\bup\b",
    "use_for": r"\bus(?:e|ed|es|ing)\b.{0,60}\bfor\b", "lose": r"\blos(?:t|e|es|ing)\b",
    "has": r"\bha(?:s|ve|d)\b|'s got\b|\bgot\b", "has_got": r"\bgot\b", "holding": r"\bhold(?:s|ing)?\b",
    "carrying": r"\bcarr(?:y|ies|ying)\b", "keeps": r"\bkeep(?:s|ing)?\b|\bkept\b", "owns": r"\bowns?\b",
    "responsible": r"\bresponsible\b",
}
KO_VERB_CUES = {
    "give": r"줬|주었|줘|준|주고|드렸|드려|드린", "lend": r"빌려\s?줬|빌려\s?주|빌려\s?줘|빌려\s?드",
    "pass": r"넘겼|넘기|넘겨", "hand_over": r"건넸|건네|건내", "give_back": r"돌려\s?줬|돌려\s?주|돌려\s?줘|돌려\s?드|반납",
    "send": r"보냈|보내|보낸", "borrow": r"빌렸|빌리|빌려(?!\s?(?:주|줬|줘|드))", "receive": r"받",
    "leave_at": r"두고|맡겼|맡기|놓고|놔두|놔뒀|둬|뒀", "move": r"옮겼|옮기|옮겨",
    "move_passive": r"옮겨졌|옮겨지|옮겨져", "take_from": r"가져갔|가져가|가지고 갔|챙겨|꺼내|꺼냈",
    "use_up": r"다\s?썼|다\s?써|써\s?버|다\s?사용", "use_for": r"썼|써|사용", "lose": r"잃어버|잃었|분실",
    "exist": r"있|없", "hold": r"가지고|갖고|가졌", "carry": r"들고", "keep": r"보관", "responsible": r"맡",
}
EN_META = r"\bask(?:ing|ed)?\b|\bquestion\b|\bwonder|\bcurious\b"
KO_META = r"물어|질문|궁금|여쭤|여쭙"
KO_PARTICLES = (("으로", "으로"), ("이랑", "이랑"), ("은", "은"), ("는", "는"), ("이", "이"), ("가", "가"),
                ("을", "을"), ("를", "를"), ("과", "과"), ("와", "와"), ("로", "로"), ("랑", "랑"), ("예요", "예요"),
                ("이에요", "이에요"))


# what may follow a noun of the scenario inside its word: a name suffix, a title, one case particle, one
# delimiter, a copula ending -- in that order (승우가에게 stacks two case particles and is refused)
_KO_CASE = ("이|가|을|를|의|한테|에게|께|께서|과|와|랑|이랑|하고|에|에서|로|으로|한테서|에게서|까지|부터|처럼|보다|"
            "이나|나|말고|만큼")
_KO_DELIM = "은|는|도|만|요|이라도|라도"
_KO_COPULA = ("이요|예요|이에요|입니다|입니까|이야|야|이다|다|였어요|이었어요|였습니다|이었습니다|였어|이었어|이라고|라고|"
              "이라|라|이고|고|인데|는데|이죠|죠|이었|였")
KO_TAILS_RE = re.compile(r"(?:이)?(?:씨|님|들)?(?:%s)?(?:%s)?(?:%s)?" % (_KO_CASE, _KO_DELIM, _KO_COPULA))


def scn_nouns_inner(scn):
    """Nouns that may end another word (a job title after a surname is its own word; nothing here)."""
    return set()


def _jong(ch):
    """The final consonant index of a Hangul syllable (0: none, 8: ㄹ), or None for anything else."""
    code = ord(ch) - 0xAC00
    return code % 28 if 0 <= code < 11172 else None


def _ko_particle_error(noun, particle):
    """True when ``particle`` is the wrong allomorph after ``noun``'s last syllable."""
    jong = _jong(noun[-1])
    if jong is None:
        return False
    vowel = jong == 0
    wrong_after_vowel = {"은", "이", "을", "과", "으로", "이랑", "이에요"}
    wrong_after_consonant = {"는", "가", "를", "와", "랑", "예요"}
    if particle == "로":
        return not vowel and jong != 8
    if particle == "으로":
        return vowel or jong == 8
    return particle in (wrong_after_vowel if vowel else wrong_after_consonant)


def _ko_has(text, word):
    return word in text or word.replace(" ", "") in text.replace(" ", "")


def _mentions_en(text, token):
    return re.search(r"(?<![A-Za-z])%s(?![a-z])" % re.escape(token), text, re.I) is not None


class Checker:
    """Keeps a phrasing only if it says the turn's facts, in the right direction, with its cues, and nothing
    else: no other number, name, item or place from any vocabulary table or style pattern."""

    def __init__(self):
        self.pools = {"en": {"names": set(), "items": set(), "places": set()},
                      "ko": {"names": set(), "items": set(), "places": set()}}
        for lang, given, surnames, items, places in (
                ("en", EN_GIVEN, EN_SURNAMES, EN_ITEMS, EN_PLACES), ("ko", KO_GIVEN, KO_SURNAMES, KO_ITEMS, KO_PLACES)):
            pool = self.pools[lang]
            pool["names"] |= set(given["f"]) | set(given["m"])
            if lang == "en":
                pool["names"] |= set(surnames)
                pool["items"] |= {w for pair in items for w in pair}
            else:
                pool["items"] |= {noun for noun, _c in items}
            pool["places"] |= set(places)
            pool["names"] |= set(PATTERN_WORDS[lang])

    def check(self, scn, turn, text, said=()):
        """(True, "ok") or (False, reason)."""
        lang = scn["language"]
        spec = turn["check"]
        text = text.strip()
        if not text:
            return False, "empty"
        if "\n" in text or len(text) > 240:
            return False, "shape"
        if re.search(r"[\"“”()\[\]]|^user\s*:|사용자|말하는 사람|the user|the speaker|assistant", text, re.I):
            return False, "quote_or_role"
        if lang == "ko" and re.search(r"[A-Za-z]", text):
            return False, "latin_in_korean"
        if lang == "en" and re.search(r"[가-힣぀-ヿ一-鿿]", text):
            return False, "script"
        if lang == "ko" and re.search(r"[぀-ヿ一-鿿]", text):
            return False, "script"
        if "..." in text or "…" in text:
            return False, "ellipsis"
        sentences = [x for x in re.split(r"(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bMrs\.)(?<=[.!?])\s+",
                                         text.strip()) if x.strip()]
        question = text.rstrip().endswith("?")
        if question and len(sentences) > 1:
            return False, "question_with_preamble"
        if not question and len(sentences) > 2:
            return False, "too_many_sentences"
        if question and re.search(EN_META if lang == "en" else KO_META, text, re.I):
            return False, "meta_question"
        if spec["question"] != question:
            return False, "question_mark" if spec["question"] else "statement_is_question"
        if "?" in text[:-1]:
            return False, "two_questions"
        if text in said and not spec["question"]:
            return False, "repeat"
        # numbers
        found = en_numbers(text, [i["one"] for i in scn["items"]]) if lang == "en" else ko_numbers(text)
        values = [v for v, _s, _e in found]
        if -2 in values:
            return False, "sino_korean_numeral"
        if -1 in values:
            return False, "vague_or_derived_amount"
        allowed = set(spec["numbers"]) | set(spec["allow"])
        if spec.get("zero"):
            allowed |= {0, 1}
        extra = [v for v in values if v not in allowed]
        if extra:
            return False, "extra_number:%s" % extra
        for n in spec["numbers"]:
            if n not in values:
                return False, "missing_number:%d" % n
        # names, items, places
        holders = {h["id"]: h for h in scn["holders"]}
        own = set()
        for h in scn["holders"]:
            own |= set(h["tokens"])
        for token in spec["names"]:
            if not (_mentions_en(text, token) if lang == "en" else _ko_has(text, token)):
                if spec.get("names_optional"):
                    continue
                return False, "missing_name:%s" % token
        allowed_names = set(spec["names"]) | set(spec.get("may", []))
        for h in scn["holders"]:
            for token in h["tokens"]:
                if token in allowed_names or any(token in a for a in allowed_names):
                    continue
                if (_mentions_en(text, token) if lang == "en" else _ko_has(text, token)):
                    return False, "other_holder:%s" % token
            if h["kind"] == "relation_unnamed" and any(t in spec["names"] for t in h["tokens"]):
                owner = r"\bmy\s+%s" if lang == "en" else r"(?:제|내|우리)\s?%s"
                if not re.search(owner % re.escape(h["relation"]), text, re.I):
                    return False, "relation_owner"
        for token in spec.get("absent", []):
            if (_mentions_en(text, token) if lang == "en" else _ko_has(text, token)):
                return False, "named_a_pointer:%s" % token
        pool = self.pools[lang]
        items_own = {i["key"] for i in scn["items"]} | {i.get("one") for i in scn["items"] if i.get("one")}
        for word in pool["names"] | pool["items"] | pool["places"]:
            if word in own or word in items_own:
                continue
            if lang == "en":
                if _mentions_en(text, word) and not any(_mentions_en(o, word) for o in own):
                    return False, "foreign_word:%s" % word
            elif word in text and not any(word in o for o in own | items_own):
                return False, "foreign_word:%s" % word
        if lang == "en":
            own_words = {w.lower() for o in own for w in o.split()}
            for m in re.finditer(r"(?<![.!?]\s)\b([A-Z][a-z]+)\b", text):
                word = m.group(1)
                if m.start() == 0 or word in ("Mr", "Ms", "Mrs", "Dr") or word.lower() in own_words:
                    continue
                if word in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"):
                    continue
                return False, "capitalized:%s" % word
        item = next((i for i in scn["items"] if i["key"] == spec["item"]), None)
        if item is not None and not spec["anaphor"]:
            if lang == "en":
                if not (_mentions_en(text, item["plural"]) or _mentions_en(text, item["one"])):
                    return False, "missing_item"
            elif not _ko_has(text, item["noun"]):
                return False, "missing_item"
        if spec.get("item2"):
            second = next(i for i in scn["items"] if i["key"] == spec["item2"])
            if not ((lang == "en" and (_mentions_en(text, second["plural"]) or _mentions_en(text, second["one"])))
                    or (lang == "ko" and second["noun"] in text)):
                return False, "missing_item2"
        for i in scn["items"]:
            if i["key"] != spec["item"] and i["key"] != spec.get("item2"):
                if (lang == "en" and (_mentions_en(text, i["plural"]) or _mentions_en(text, i["one"]))) or (
                        lang == "ko" and i["noun"] in text):
                    return False, "other_item"
        # cues
        cues = EN_CUES if lang == "en" else KO_CUES
        for cue in spec["cues"]:
            kind, _, arg = cue.partition(":")
            if kind == "first_person":
                if not (EN_FIRST if lang == "en" else KO_FIRST).search(text):
                    return False, "cue:first_person"
            elif kind == "place":
                ok = _mentions_en(text, arg) if lang == "en" else _ko_has(text, arg)
                if not ok:
                    return False, "cue:place"
            elif kind == "title":
                if lang == "en":
                    if not re.search(r"\b(?:Mr|Ms|Mrs|Dr)\.?\s+%s\b" % re.escape(arg), text):
                        return False, "cue:title"
                elif not re.search(r"%s\s?(?:씨|님)" % re.escape(arg), text):
                    return False, "cue:title"
            elif kind in ("relation", "role"):
                if not (_mentions_en(text, arg) if lang == "en" else _ko_has(text, arg)):
                    return False, "cue:" + kind
            elif kind in cues:
                flags = re.I if lang == "en" else 0
                if not re.search(cues[kind], text, flags):
                    return False, "cue:" + kind
        # the turn's verb, as its class tag says
        verb = (turn.get("say") or {}).get("verb")
        if turn["say"].get("act") == "state" and verb and "transfer_verbs:" + verb in turn["classes"]:
            table = EN_VERB_CUES if lang == "en" else KO_VERB_CUES
            if verb in table and not re.search(table[verb], text, re.I if lang == "en" else 0):
                return False, "verb:" + verb
        # a Korean phrasing in the dialogue's register, with a person never marked like a place
        if lang == "ko":
            reason = self._korean(scn, text, question)
            if reason:
                return False, reason
        # a correction says the new value before the old one's negation (en: 'N, not M'; ko: 'M가 아니라 N')
        if spec.get("contrast"):
            reason = self._contrast(lang, spec["contrast"], text, found)
            if reason:
                return False, reason
        # the direction of a transfer
        if spec.get("direction"):
            reason = self._direction(lang, spec["direction"], text)
            if reason:
                return False, reason
        return True, "ok"

    @staticmethod
    def _contrast(lang, c, text, found):
        if "new_number" in c:
            new = [s for v, s, _e in found if v == c["new_number"]]
            old = [s for v, s, _e in found if v == c["old_number"]]
            if not new or not old:
                return "contrast"
            marker = re.search(r"\bnot\b|n't\b|\binstead of\b" if lang == "en" else r"아니라|아니고|말고|아니",
                               text)
            if marker is None:
                return "contrast"
            if lang == "en" and not (min(new) < marker.start() < max(old) or max(old) < min(new)
                                     and "instead of" not in text):
                return "contrast"
            if lang == "ko" and not min(old) < marker.start() < max(new):
                return "contrast"
            return None
        new, old = c["new"], c["old"]
        if lang == "en":
            def at(token):
                if token == "I":
                    m = re.search(r"\b(?:me|myself)\b", text, re.I)
                else:
                    m = re.search(r"(?<![A-Za-z])%s(?![a-z])" % re.escape(token), text, re.I)
                return m.start() if m else None
            marker = re.search(r"\bnot\b|\binstead of\b", text, re.I)
            a, b = at(new), at(old)
            if marker is None or a is None or b is None:
                return "contrast"
            if "instead of" in text.lower():
                return None if a < marker.start() < b else "contrast"
            return None if a < marker.start() < b or (b > marker.start() and a < b) else "contrast"
        def at(token):
            if token == "나":
                m = re.search(r"(?:저한테|저에게|제게|나한테|나에게|내게|저|나)", text)
            else:
                m = re.search(re.escape(token), text)
            return m.start() if m else None
        marker = re.search(r"아니라|아니고|말고", text)
        a, b = at(new), at(old)
        if marker is None or a is None or b is None or not b < marker.start() < a:
            return "contrast"
        return None

    @staticmethod
    def _korean(scn, text, question):
        last = re.split(r"(?<=[.!?])\s+", text.strip())[-1].rstrip(".!?~ ")
        reg = scn["register"]
        if reg == "haeyo" and not re.search(r"요$", last):
            return "register"
        if reg == "hapsyo" and not re.search(r"(니다|니까|시오|세요)$", last):
            return "register"
        if reg == "banmal" and re.search(r"(요|니다|니까)$", last):
            return "register"
        for h in scn["holders"]:
            if h["kind"] in ("place",):
                continue
            for token in h["tokens"]:
                if re.search(r"%s(?:\s?(?:씨|님))?(?:에|에서)(?![게])(?:는|도)?(?:\s|$)" % re.escape(token), text):
                    return "person_as_place"
        if re.search(r"(?:자루|장|켤레|묶음)\s?(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s?개", text):
            return "counter_as_noun"
        nouns = {t for h in scn["holders"] for t in h["tokens"]} | {i["noun"] for i in scn["items"]} | {"씨", "님"}
        nouns |= {h["relation"] for h in scn["holders"] if h.get("relation")}
        for noun in sorted(nouns, key=len, reverse=True):
            for m in re.finditer(re.escape(noun), text):
                rest = text[m.end():]
                if noun == "씨" and m.start() > 0 and re.match(r"[가-힣]", text[m.start() - 1]):
                    continue           # 씨 inside another word (아저씨) or attached to a name
                if _jong(noun[-1]) == 0 and re.match(r"이(?:가|는|를|도|한테|에게|랑|와|의|만)", rest):
                    return "particle:%s이" % noun      # 유나이가: the name suffix 이 follows a consonant only
                for particle, _p in KO_PARTICLES:
                    if rest.startswith(particle) and (len(rest) == len(particle) or not re.match(
                            r"[가-힣]", rest[len(particle)]) or particle in ("예요", "이에요") or
                            particle in ("은", "는", "을", "를", "과", "와")):
                        if _ko_particle_error(noun, particle):
                            return "particle:%s%s" % (noun, particle)
                        break
        tails = KO_TAILS_RE
        for noun in sorted(nouns - {"씨", "님"}, key=len, reverse=True):
            for m in re.finditer(re.escape(noun), text):
                if m.start() > 0 and re.match(r"[가-힣]", text[m.start() - 1]) and noun not in scn_nouns_inner(scn):
                    continue
                rest = re.match(r"[^\s.,!?~]*", text[m.end():]).group(0)
                if rest and not tails.fullmatch(rest) and not any(
                        o != noun and noun in o and text.find(o) != -1 for o in nouns):
                    return "glued:%s%s" % (noun, rest)
        for m in re.finditer(r"([가-힣])대(?:요|\.|$|\s)", text):
            if _jong(m.group(1)) not in (4, 20):        # 줬대요 (ㅆ), 준대요 (ㄴ); 주대요 is not a word
                return "hearsay_form"
        if re.search(r"(?:개|자루|장|권|병|켤레|대|벌|묶음)[이가]\s?(?:맡고|가지고|갖고|들고|보관하고|빌려|넘겨|넘겼|"
                     r"건네|건넸|돌려|보내|보냈|옮겼|가져|써|썼|잃어)", text):
            return "counted_object_as_subject"
        return None

    @staticmethod
    def _direction(lang, d, text):
        giver, taker, side = d["giver"], d["taker"], d["side"]
        if lang == "en":
            low = text
            lead = r"(?:(?:the|my|our|his|her|their|mr\.|ms\.|mrs\.|dr\.|(?-i:[A-Z][a-z]+'s|[a-z]+,))\s+){0,3}"

            def near(prep, token):
                if token == "I":
                    return re.search(r"\b%s\s+me\b" % prep, low, re.I) is not None
                return re.search(r"\b%s\s+%s%s\b" % (prep, lead, re.escape(token)), low, re.I) is not None

            def at(token, role):
                if token == "I":
                    m = re.search(r"\bI\b" if role == "subject" else r"\bme\b", low)
                else:
                    m = re.search(r"(?<![A-Za-z])%s(?![a-z])" % re.escape(token), low, re.I)
                return m.start() if m else None
            if near("to", giver) or near("from", taker):
                return "direction"
            verb = d["verb"]
            if verb in ("move", "move_passive"):
                if not (near("from", giver) and (near("to", taker) or near("into", taker))):
                    return "direction"
                return None
            if verb == "take_from":
                return None if near("from", giver) or near("out of", giver) else "direction"
            if verb == "leave_at":
                return None if near("at", taker) or near("in", taker) or near("with", taker) else "direction"
            if side == "take":
                return None if near("from", giver) or near("off", giver) else "direction"
            if near("to", taker) or near("back to", taker):
                return None
            a, b = at(giver, "subject"), at(taker, "object")
            if a is None or b is None or not a < b:
                return "direction"
            return None
        # Korean: the receiver is marked as a receiver, the giver never is
        dative = r"(?:\s?(?:씨|님))?\s?(?:한테|에게|께)(?!서)"
        source = r"(?:\s?(?:씨|님))?\s?(?:한테서|에게서|께서|한테|에게)"

        def marked(token, pattern):
            if token == "나":
                forms = {"dative": r"(?:저한테|저에게|제게|나한테|나에게|내게)(?!서)",
                         "source": r"(?:저한테서|저에게서|나한테서|나에게서|저한테|나한테|저에게|나에게)"}
                return re.search(forms["dative" if pattern is dative else "source"], text) is not None
            return re.search(re.escape(token) + r"(?:이)?" + pattern, text) is not None
        if d["giver_kind"] == "place" or d["taker_kind"] == "place":
            if d["verb"] in ("move", "move_passive"):
                if not re.search(re.escape(giver) + r"\s?에서", text) or not re.search(
                        re.escape(taker) + r"\s?(?:으로|로|에)", text):
                    return "direction"
            elif d["verb"] == "leave_at":
                if not re.search(re.escape(taker) + r"\s?(?:에|에다|에다가)(?!서)", text):
                    return "direction"
            elif d["verb"] == "take_from":
                if not re.search(re.escape(giver) + r"\s?에서", text):
                    return "direction"
            return None
        if side == "give":
            if marked(giver, dative) and not marked(taker, dative):
                return "direction"
            if not marked(taker, dative):
                return "direction_unmarked"
        else:
            if not marked(giver, source) or marked(taker, dative):
                return "direction"
        return None


# ---------------------------------------------------------------------------
# phrasing (the only place the model is loaded)
# ---------------------------------------------------------------------------
def _seed(half, sid, n, attempt):
    digest = hashlib.sha256(("%d/%s/%d/%d" % (SAMPLING[half], sid, n, attempt)).encode()).hexdigest()
    return int(digest[:8], 16)


class Phraser:
    def __init__(self):
        import os
        os.environ["HF_HUB_OFFLINE"] = "1"
        import mlx.core as mx
        import mlx_lm
        from huggingface_hub import snapshot_download
        from mlx_lm.sample_utils import make_sampler
        self.mx, self.mlx_lm = mx, mlx_lm
        path = snapshot_download(PHRASER["weights"], revision=PHRASER["revision"])
        mx.set_cache_limit(PHRASER["cache_limit_mb"] * 1024 * 1024)
        self.model, self.tokenizer = mlx_lm.load(str(path))
        self.sampler = make_sampler(temp=PHRASER["temperature"])

    def __call__(self, messages, seed):
        self.mx.random.seed(seed)
        prompt = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        text = self.mlx_lm.generate(self.model, self.tokenizer, prompt=prompt, max_tokens=PHRASER["max_tokens"],
                                    sampler=self.sampler, verbose=False)
        return text.strip()

    def peak_mb(self):
        return round(self.mx.get_peak_memory() / 2 ** 20)


def _clean(text):
    """The model's message as written, with only its framing taken off (a leading 'User:' label or one pair
    of surrounding quotation marks); no word of the message is changed."""
    text = text.strip()
    text = re.sub(r"^(?:User|사용자)\s*:\s*", "", text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def load_scenarios():
    return [json.loads(line) for line in SCENARIOS.read_text(encoding="utf-8").splitlines() if line.strip()]


def _skippable(turn):
    """A turn that changes no state (a question, a repair): when every sample of it fails, the dialogue goes on
    without it. A statement or a correction that fails ends the dialogue there."""
    return turn["expect"]["act"] not in ("record", "revise")


def _needs_context(turn):
    """Only a turn that points back (an anaphoric count, 'of them', a pronoun, 'the two of them') sees the
    messages before it; any other turn is phrased from its own facts, so no earlier number leaks into it."""
    features = (turn.get("say") or {}).get("features") or []
    return bool(turn["check"].get("anaphor")) or any(f in features for f in ("q_pronoun", "q_two_total", "exact",
                                                                              "partitive", "same"))


def build_dialogue(scn, texts):
    """The dialogue of the turns kept (``{n: text}``), renumbered from 1, evidence and targets mapped; or None
    when what is left is not a dialogue (fewer than four turns or two answerable questions)."""
    kept = [t for t in scn["turns"] if t["n"] in texts]
    if len(kept) < 4 or sum(t["label"] == "answerable" for t in kept) < 2:
        return None
    new = {t["n"]: i + 1 for i, t in enumerate(kept)}
    turns = []
    for t in kept:
        expect = json.loads(json.dumps(t["expect"]))
        ev = expect.get("evidence") or {}
        if any(n not in new for n in ev.get("turns", [])):
            return None
        expect["evidence"] = {**ev, "turns": [new[n] for n in ev.get("turns", [])]}
        if "target_turn" in expect:
            if expect["target_turn"] not in new:
                return None
            expect["target_turn"] = new[expect["target_turn"]]
        turns.append({"n": new[t["n"]], "say": texts[t["n"]], "label": t["label"], "tags": t["tags"],
                      "classes": t["classes"], "scenario_turn": t["n"], "expect": expect})
    return turns


def phrase(limit=None, only=None):
    scenarios = load_scenarios()
    done = {}
    if PHRASINGS.exists():
        for line in PHRASINGS.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done.setdefault(row["scenario"], []).append(row)
    checker = Checker()
    model = Phraser()
    kept = {}
    for scn in scenarios:
        key = (scn["half"], scn["language"])
        if only and scn["id"] not in only:
            continue
        if scn["id"] in done:
            if any(r.get("dialogue") for r in done[scn["id"]]):
                kept[key] = kept.get(key, 0) + 1
            continue
        if kept.get(key, 0) >= (limit or PER_HALF):
            continue
        rows, said, texts, skipped, failed = [], [], {}, [], None
        start = time.time()
        turns = scn["turns"]
        i = 0
        while i < len(turns):
            turn = turns[i]
            accepted, reason = None, None
            context = said if _needs_context(turn) else []
            for attempt in range(ATTEMPTS):
                seed = _seed(scn["half"], scn["id"], turn["n"], attempt)
                raw = model(prompt_messages(scn, turn, context, attempt, reason if attempt else None), seed)
                text = _clean(raw)
                ok, reason = checker.check(scn, turn, text, said)
                rows.append({"scenario": scn["id"], "n": turn["n"], "attempt": attempt, "seed": seed, "raw": raw,
                             "text": text, "ok": ok, "reason": reason})
                if ok:
                    accepted = text
                    break
            if accepted is None:
                if not _skippable(turn):
                    failed = turn["n"]
                    break
                skipped.append(turn["n"])
                # a repair names the question before it: it goes with it
                if i + 1 < len(turns) and turns[i + 1]["say"].get("act") == "repair":
                    skipped.append(turns[i + 1]["n"])
                    i += 1
                i += 1
                continue
            said.append(accepted)
            texts[turn["n"]] = accepted
            i += 1
        usable = build_dialogue(scn, texts) is not None
        status = {"scenario": scn["id"], "dialogue": usable, "kept": sorted(texts), "skipped": skipped,
                  "failed_turn": failed, "seconds": round(time.time() - start, 1), "peak_mb": model.peak_mb()}
        with PHRASINGS.open("a", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.write(json.dumps(status, ensure_ascii=False) + "\n")
        if usable:
            kept[key] = kept.get(key, 0) + 1
        print(scn["id"], "ok %d/%d" % (len(texts), len(turns)) if usable else "dropped", status["seconds"], "s",
              status["peak_mb"], "MB", flush=True)


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
KEPT = HERE / "phrasings_kept.jsonl"      # the accepted samples of the dialogues in the set, with their seeds
STATS = HERE / "phrasing_stats.json"      # what the phrasing run tried, kept and discarded, by reason
OTHER_SETS = ("dialogues_v1", "dialogues_dev", "dialogues_dev2", "dialogues_dev3")


def load_phrasings():
    """The raw phrasing log (every sample, kept or discarded) when it is here, else the kept samples."""
    rows, status = {}, {}
    path = PHRASINGS if PHRASINGS.exists() else KEPT
    if not path.exists():
        return rows, status
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "dialogue" in row:
            status[row["scenario"]] = row
        else:
            rows.setdefault(row["scenario"], []).append(row)
    return rows, status


def _overlapping(dialogues):
    """Ids of dialogues that share a full sentence with another dialogue file: one of theirs found in any
    corpus file outside this folder, or one of another set's found in theirs (the frozen set included, read
    by the gate's own functions; nothing of it is printed, only how many dialogues are left out)."""
    sys.path.insert(0, str(ROOT / "bench"))
    import dialogue_gate as gate
    found = gate.overlaps(dialogues, disk_root=ROOT, owned=("data/benchmarks/dialogues_dev4/",))
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
    """The dialogues from the phrasing cache: per half and language the first ``PER_HALF`` usable scenarios in
    scenario order that share no full sentence with another dialogue file or with a dialogue already taken,
    each with the turns its phrasing kept, every kept text checked again."""
    sys.path.insert(0, str(ROOT / "bench"))
    import dialogue_gate as gate
    scenarios = load_scenarios()
    rows, status = load_phrasings()
    checker = Checker()
    candidates, problems = [], []
    for scn in scenarios:
        st = status.get(scn["id"], {})
        if not st.get("dialogue"):
            continue
        texts, said = {}, []
        for turn in scn["turns"]:
            if turn["n"] not in st["kept"]:
                continue
            accepted = [r for r in rows[scn["id"]] if r["n"] == turn["n"] and r["ok"]]
            text = accepted[-1]["text"]
            ok, reason = checker.check(scn, turn, text, said)
            if not ok:
                problems.append("%s#%d %s" % (scn["id"], turn["n"], reason))
            said.append(text)
            texts[turn["n"]] = text
        turns = build_dialogue(scn, texts)
        if turns is None:
            problems.append("%s: not a dialogue" % scn["id"])
            continue
        candidates.append({
            "schema": SCHEMA, "id": scn["id"], "language": scn["language"], "domain": "everyday",
            "categories": sorted({tag for t in turns for tag in t["tags"]}),
            "variation": {"word_order": "free", "register": scn["register"],
                          "split": "multi_fact" if len(turns[0]["expect"].get("events") or []) > 1 else
                          "one_fact_per_turn",
                          "correction_position": "late" if any(t["label"] == "correction" for t in turns) else "none",
                          "roles": "scenario", "initial_values": {}, "scenario": scn["id"], "half": scn["half"],
                          "focus": scn["focus"], "phraser": PHRASER["weights"],
                          "classes": sorted({c for t in turns for c in t["classes"]})},
            "turns": turns})
    shared = _overlapping(candidates)
    dialogues, split, counts, taken, left_out = [], {"build": [], "check": []}, {}, set(), {"other_file": 0,
                                                                                         "same_set": 0}
    for d in candidates:
        key = (d["variation"]["half"], d["language"])
        if counts.get(key, 0) >= PER_HALF:
            continue
        sentences = {norm for _d, _n, _raw, norm in gate.dialogue_sentences([d])}
        if d["id"] in shared:
            left_out["other_file"] += 1
            continue
        if sentences & taken:
            left_out["same_set"] += 1
            continue
        taken |= sentences
        counts[key] = counts.get(key, 0) + 1
        d = dict(d, id="dev4_%s_%s_%02d" % (d["language"], d["variation"]["half"][0], counts[key]))
        dialogues.append(d)
        split[d["variation"]["half"]].append(d["id"])
    if write:
        for path in HERE.glob("dev4_*.json"):
            path.unlink()
        for d in dialogues:
            (HERE / (d["id"] + ".json")).write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n",
                                                    encoding="utf-8")
        lines = ["seed %d scenario_build %d scenario_check %d sampling_build %d sampling_check %d" % (
            SEED, SCENARIO_SEEDS["build"], SCENARIO_SEEDS["check"], SAMPLING["build"], SAMPLING["check"]),
            "build " + " ".join(split["build"]), "check " + " ".join(split["check"])]
        (HERE / "split.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if PHRASINGS.exists():
            used = {d["variation"]["scenario"] for d in dialogues}
            with KEPT.open("w", encoding="utf-8") as out:
                for scn in scenarios:
                    if scn["id"] not in used:
                        continue
                    for row in rows[scn["id"]]:
                        if row["ok"]:
                            out.write(json.dumps({k: row[k] for k in ("scenario", "n", "attempt", "seed", "text", "ok")},
                                                 ensure_ascii=False) + "\n")
                    out.write(json.dumps(status[scn["id"]], ensure_ascii=False) + "\n")
            STATS.write_text(json.dumps(phrasing_stats(rows, status, left_out), ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    return dialogues, split, problems


def phrasing_stats(rows, status, left_out):
    """What the phrasing run tried and discarded: samples by checker reason, scenarios by outcome, per half and
    language, and the dialogues left out for a shared sentence."""
    by_scenario = {s["id"]: s for s in load_scenarios()}
    out = {"phraser": PHRASER, "attempts_per_turn": ATTEMPTS, "left_out_for_a_shared_sentence": left_out,
           "by_half_language": {}}
    for sid, st in status.items():
        scn = by_scenario[sid]
        key = "%s_%s" % (scn["half"], scn["language"])
        row = out["by_half_language"].setdefault(key, {"scenarios": 0, "usable": 0, "ended_early": 0,
                                                       "turns_left_out": 0, "samples": 0, "reasons": {},
                                                       "peak_mb": 0, "seconds": 0.0})
        row["scenarios"] += 1
        row["usable"] += bool(st["dialogue"])
        row["ended_early"] += st.get("failed_turn") is not None
        row["turns_left_out"] += len(st.get("skipped") or [])
        row["peak_mb"] = max(row["peak_mb"], st.get("peak_mb") or 0)
        row["seconds"] = round(row["seconds"] + (st.get("seconds") or 0), 1)
        for r in rows.get(sid, []):
            row["samples"] += 1
            reason = r["reason"].split(":")[0]
            row["reasons"][reason] = row["reasons"].get(reason, 0) + 1
    return out


def coverage(dialogues):
    """{family: {"ko": n, "en": n, "ko_build": .., ...}}: dialogues that carry a class of that family."""
    table = {}
    for fam in FAMILIES + ("corrections",):
        row = {}
        for d in dialogues:
            classes = d["variation"]["classes"]
            if fam == "korean_register":
                hit = d["language"] == "ko" and d["variation"]["register"] in ("haeyo", "hapsyo")
            else:
                hit = any(c.split(":")[0] == fam for c in classes)
            if hit:
                for key in (d["language"], "%s_%s" % (d["language"], d["variation"]["half"])):
                    row[key] = row.get(key, 0) + 1
        table[fam] = row
    sub = {}
    for d in dialogues:
        for c in d["variation"]["classes"]:
            sub.setdefault(c, {}).setdefault(d["language"], 0)
            sub[c][d["language"]] += 1
    return table, sub


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["scenarios", "phrase", "assemble", "coverage"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--cache", type=Path, help="another phrasing cache (a trial run), not phrasings.jsonl")
    parser.add_argument("--ko-instructions", choices=["en", "ko"], help="a trial of the other instruction language")
    args = parser.parse_args(argv)
    if args.ko_instructions:
        global KO_INSTRUCTIONS
        KO_INSTRUCTIONS = args.ko_instructions
    if args.cache:
        global PHRASINGS
        PHRASINGS = args.cache
    if args.command == "scenarios":
        out = generate_scenarios()
        SCENARIOS.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out), encoding="utf-8")
        print("scenarios", len(out))
    elif args.command == "phrase":
        phrase(args.limit, args.only)
    elif args.command == "assemble":
        dialogues, split, problems = assemble()
        print("dialogues %d (build %d, check %d); rechecked problems %d" % (
            len(dialogues), len(split["build"]), len(split["check"]), len(problems)))
        for line in problems:
            print("  ", line)
    else:
        dialogues, _split, _p = assemble(write=False)
        table, sub = coverage(dialogues)
        print("%-18s %5s %5s   %s" % ("class", "ko", "en", "by half"))
        for fam, row in table.items():
            print("%-18s %5d %5d   %s" % (fam, row.get("ko", 0), row.get("en", 0),
                                         " ".join("%s=%d" % (k, v) for k, v in sorted(row.items()) if "_" in k)))
        for c, row in sorted(sub.items()):
            print("   %-36s ko %3d  en %3d" % (c, row.get("ko", 0), row.get("en", 0)))


if __name__ == "__main__":
    sys.exit(main())
