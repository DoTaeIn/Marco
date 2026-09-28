"""Development set v6 (goal G6.0, G6.0c, G6.1): scenarios for the exam's own classes, phrased outside.

The truth is a scenario; the wording comes from a phrasing source outside this repository, which receives the
scenario files and ``PHRASING.md`` only (the data rule of ``docs/ko/2026-09-22-freeze-decision.md``). Nothing
here writes a sentence.

* **Scenarios** (``scenarios``): holders, things, and turns as structured facts, each turn with the form it must
  take (``FORMS``: the prompts of G6.0, by class of ``docs/ko/2026-09-25-understanding-r6-goal.md``) and its
  class tags. Counts are asked as words in at least half of the statements; the question forms of section B
  by class; topic-switch ellipsis turns; repair-plus-question turns; fragment counts; double-object and
  particle-verb transfers; why-with-fact turns after an answer; one question in the other language in more
  than 10% of dialogues; and a class the goal does not list (15): a transfer to a holder whose starting count
  is never stated (the giver's count is answerable, the receiver's is held). Build and check halves use
  disjoint names, things and places, new beside v4's and v5's.
* **Checker** (``Checker6``): keeps a written turn only if it says its facts and its form: every count (digits,
  English number words, Korean native numerals), no other number, every holder it names and no holder the
  scenario does not name, the thing, the direction of a transfer, the form's cue, the register.
* **Assembly** (``assemble --phrasings-from``): phrasing records written outside (scenario id, language, the
  turns as written, the source's name and date) are checked turn by turn; failed turns and failed records are
  dropped and counted; every expected value is recomputed from the scenario (``gate_turns``), never read from
  the text; a turn that shares a sentence with the corpus or with dev to dev5 is dropped.

    python data/benchmarks/dialogues_dev6/build.py scenarios      # scenarios_{build,check}_{ko,en}.jsonl, PHRASING.md
    python data/benchmarks/dialogues_dev6/build.py coverage       # classes by language and half, from the scenarios
    python data/benchmarks/dialogues_dev6/build.py assemble --phrasings-from FILE.jsonl [FILE2.jsonl ...]

The frozen exam sets are never read: the overlap check reads the tracked corpus without them (``FROZEN``).
"""
import argparse
import importlib.util
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "bench"))
import dialogue_gate as gate  # noqa: E402


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v4 = _module("dialogues_dev4_build_for_v6", HERE.parent / "dialogues_dev4" / "build.py")
v5 = _module("dialogues_dev5_build_for_v6", HERE.parent / "dialogues_dev5" / "build.py")

# the frozen exam sets: named only to leave them out of the overlap corpus (never listed, opened or read)
FROZEN = ("data/benchmarks/dialogues_v1", "data/benchmarks/reasoning_v1")
assert FROZEN == v4.FROZEN
OTHER_SETS = ("dialogues_dev", "dialogues_dev2", "dialogues_dev3", "dialogues_dev4", "dialogues_dev5")
SEED = 20260928
SCENARIO_SEEDS = {"build": 6617, "check": 9967}
PER_HALF = 60               # dialogues per language per half: 240 in all
CROSS_EVERY = 8             # slot % 8 == 0: one question in the other language (8 of 60 per half, 13%)
LANGS = ("ko", "en")
HALVES = ("build", "check")
PHRASING = HERE / "PHRASING.md"


def scenarios_path(half, lang, folder=HERE):
    return Path(folder) / ("scenarios_%s_%s.jsonl" % (half, lang))


# ---------------------------------------------------------------------------
# vocabulary: new tables, none in v4's or v5's (asserted below)
# ---------------------------------------------------------------------------
EN_GIVEN = {
    "f": ["Bella", "Brooke", "Camila", "Daphne", "Eden", "Elise", "Flora", "Georgia", "Leila", "Luna", "Mabel",
          "Maeve", "Nell", "Piper", "Rhea", "Thea", "Ursula", "Willa", "Xena", "Zara", "Adele", "Bonnie",
          "Celeste", "Dora", "Eloise", "Frida", "Gwen", "Harriet"],
    "m": ["Abel", "Alan", "Blake", "Bruno", "Caleb", "Derek", "Eddie", "Elliot", "Finn", "Jonah", "Joel", "Kurt",
          "Nate", "Pablo", "Quentin", "Reid", "Rudy", "Seth", "Troy", "Vince", "Boris", "Emil", "Gordon", "Hector",
          "Igor", "Jasper", "Kenji", "Otto"],
}
EN_SURNAMES = ["Barnes", "Burke", "Daniels", "Dunn", "Fleming", "Fowler", "Hayes", "Holt", "Hopkins", "Jennings",
               "Keller", "Lambert", "Lawson", "Lynch", "Maxwell", "McCoy", "Norris", "Quinlan", "Reeves", "Rhodes",
               "Sutton", "Walsh", "Whitaker", "Yates", "Brennan", "Doyle"]
EN_TITLES = {"f": ["Ms.", "Mrs.", "Dr."], "m": ["Mr.", "Dr."]}
# (plural, singular); the plural is the thing's key
EN_ITEMS = [("pencils", "pencil"), ("highlighters", "highlighter"), ("sharpeners", "sharpener"),
            ("clipboards", "clipboard"), ("sketchbooks", "sketchbook"), ("diaries", "diary"),
            ("journals", "journal"), ("textbooks", "textbook"), ("dictionaries", "dictionary"),
            ("atlases", "atlas"), ("thumbtacks", "thumbtack"), ("pears", "pear"), ("apricots", "apricot"),
            ("limes", "lime"), ("coconuts", "coconut"), ("pineapples", "pineapple"), ("avocados", "avocado"),
            ("pumpkins", "pumpkin"), ("turnips", "turnip"), ("radishes", "radish"), ("dumplings", "dumpling"),
            ("waffles", "waffle"), ("pancakes", "pancake"), ("croissants", "croissant"), ("scones", "scone"),
            ("buttons", "button"), ("thimbles", "thimble"), ("spools", "spool"), ("needles", "needle"),
            ("marbles", "marble"), ("whistles", "whistle"), ("flutes", "flute"), ("drums", "drum"),
            ("guitars", "guitar"), ("violins", "violin"), ("tambourines", "tambourine"),
            ("harmonicas", "harmonica"), ("globes", "globe"), ("telescopes", "telescope"),
            ("compasses", "compass"), ("wallets", "wallet"), ("purses", "purse"), ("briefcases", "briefcase"),
            ("belts", "belt"), ("bracelets", "bracelet"), ("necklaces", "necklace"), ("teacups", "teacup"),
            ("saucers", "saucer"), ("platters", "platter"), ("graters", "grater"), ("peelers", "peeler"),
            ("skillets", "skillet"), ("chisels", "chisel"), ("screwdrivers", "screwdriver"),
            ("wheelbarrows", "wheelbarrow"), ("trowels", "trowel"), ("puppets", "puppet"), ("robots", "robot")]
# things counted in bundles (the question "how many bundles" of class 9)
EN_BUNDLES = [("bundles of kindling", "bundle of kindling"), ("bundles of straw", "bundle of straw"),
              ("bundles of herbs", "bundle of herbs"), ("bundles of twigs", "bundle of twigs"),
              ("bundles of reeds", "bundle of reeds"), ("bundles of letters", "bundle of letters")]
EN_PLACES = ["stationery store", "barber shop", "butcher shop", "eyeglass shop", "shoe store", "bank",
             "tailor shop", "deli", "mill", "boiler room", "exhibit hall", "practice room", "study hall",
             "rest stop", "campsite", "pier", "bus depot", "station office", "factory", "chapel", "gazebo",
             "cabin", "marina", "stable", "vineyard", "sunroom", "mudroom", "carport", "patio", "veranda",
             "recording room", "club room", "recycling area", "herb garden", "guesthouse", "ice rink",
             "bowling alley", "flower stall", "box office", "sewing room"]
KO_GIVEN = {
    "f": ["다현", "은지", "혜수", "가람", "보은", "세희", "윤희", "인영", "재희", "진희", "현정", "희정", "미란",
          "선아", "영주", "예슬", "은숙", "정아", "채영", "태희", "현아", "경아", "다솜", "수향", "연주", "혜미"],
    "m": ["동하", "민규", "성호", "영훈", "재석", "준기", "지성", "태식", "현철", "형석", "기범", "도훈", "병훈",
          "상현", "석훈", "세훈", "시혁", "용호", "원석", "은호", "재성", "정훈", "종현", "창수", "태웅", "한수"],
}
# (no Sino-Korean numeral syllable: 구 or 육 before a title read as a count)
KO_SURNAMES = ["유", "전", "우", "하", "주", "마", "경", "인", "여", "천", "감", "태", "모", "목", "반", "기", "라",
               "복", "계", "빈", "도", "피"]
KO_JOB_TITLES = sorted(set(v4.KO_JOB_TITLES) | set(v5.KO_JOB_TITLES))      # a closed class: both halves
# (noun, counter)
KO_ITEMS = [("연필", "자루"), ("형광펜", "자루"), ("만년필", "자루"), ("샤프", "자루"), ("모종삽", "자루"),
            ("공책", "권"), ("일기장", "권"), ("사전", "권"), ("만화책", "권"), ("교과서", "권"), ("동화책", "권"),
            ("스케치북", "권"), ("수첩", "권"), ("도화지", "장"), ("색종이", "장"), ("편지지", "장"),
            ("영수증", "장"), ("손수건", "장"), ("팬케이크", "장"), ("파인애플", "개"), ("아보카도", "개"),
            ("코코넛", "개"), ("라임", "개"), ("살구", "개"), ("자몽", "개"), ("석류", "개"), ("만두", "개"),
            ("와플", "개"), ("크루아상", "개"), ("호떡", "개"), ("붕어빵", "개"), ("단추", "개"), ("골무", "개"),
            ("바늘", "개"), ("구슬", "개"), ("호루라기", "개"), ("바이올린", "대"), ("탬버린", "개"),
            ("하모니카", "개"), ("지구본", "개"), ("망원경", "대"), ("핸드백", "개"), ("서류가방", "개"),
            ("목걸이", "개"), ("팔찌", "개"), ("반지", "개"), ("찻잔", "개"), ("강판", "개"), ("드라이버", "개"),
            ("로봇", "대"), ("장미", "송이"), ("튤립", "송이"), ("국화", "송이"), ("스피커", "대")]
KO_BUNDLES = [("빨대", "묶음"), ("고무줄", "묶음"), ("편지", "묶음"), ("서류", "묶음"), ("약초", "묶음"),
              ("이쑤시개", "묶음")]
KO_PLACES = ["세탁소", "문구점", "미용실", "정육점", "사진관", "안경점", "신발가게", "은행", "매표소", "수선집",
             "반찬가게", "떡집", "방앗간", "목공실", "기계실", "전시실", "연습실", "독서실", "휴게소", "캠핑장",
             "선착장", "정류장", "역무실", "물류센터", "공장", "연구실", "실험실", "탕비실", "수위실", "동아리방",
             "합주실", "녹음실", "분리수거장", "텃밭", "비닐하우스", "매장", "창구", "세차장", "주유소", "양복점"]
# relation words and roles are closed classes, not names: both halves keep all (v4's and v5's, 누나 left out:
# it holds 나, the Korean first person's entity)
EN_RELATIONS = list(v4.EN_RELATIONS) + list(v5.EN_RELATIONS)
KO_RELATIONS = [r for r in list(v4.KO_RELATIONS) + list(v5.KO_RELATIONS) if "나" not in r[0]]
EN_ROLES = list(v4.EN_ROLES) + list(v5.EN_ROLES)
KO_ROLES = list(v4.KO_ROLES) + list(v5.KO_ROLES)
# words that fill a turn's detail (never a name, a thing or a place of any table)
EN_PURPOSES = ["a school project", "the bake sale", "a craft class", "a birthday party", "the spring fair",
               "a window display"]
KO_PURPOSES = ["생일 장식", "선물 꾸러미", "학교 과제", "전시 작품", "바자회 준비", "만들기 수업"]
EN_OCCASIONS = ["the picnic", "the fundraiser", "the open house", "the school fair", "the reunion",
                "the charity run"]
KO_VEHICLES = ["트럭", "수레", "승합차"]
# person words a writer might add for a holder the scenario lacks
EN_PERSON_WORDS = sorted({w for w, _g in EN_RELATIONS} | {r.split()[-1] for r in EN_ROLES}
                         | {"mom", "dad", "mother", "father", "teacher", "boss"})
KO_PERSON_WORDS = sorted({w for w, _g in KO_RELATIONS if len(w) >= 2} | set(KO_ROLES)
                         | {"엄마", "아빠", "어머니", "아버지", "부모님", "아저씨", "아주머니"})


def _old_words():
    """{"en"|"ko": {names, things, places}} of v4 and v5 (and v4's pattern words)."""
    out = {}
    for lang in LANGS:
        names, things, places = set(v4.PATTERN_WORDS[lang]), set(), set()
        for m in (v4, v5):
            given = getattr(m, "EN_GIVEN" if lang == "en" else "KO_GIVEN")
            names |= set(given["f"]) | set(given["m"])
            if lang == "en":
                names |= set(m.EN_SURNAMES)
                things |= {w for pair in m.EN_ITEMS for w in pair}
                places |= set(m.EN_PLACES)
            else:
                things |= {noun for noun, _c in m.KO_ITEMS}
                places |= set(m.KO_PLACES)
        out[lang] = {"names": names, "things": things, "places": places}
    return out


OLD_WORDS = _old_words()


def _new_words():
    return {"en": {"names": set(EN_GIVEN["f"] + EN_GIVEN["m"] + EN_SURNAMES),
                   "things": {w for pair in EN_ITEMS + EN_BUNDLES for w in pair}, "places": set(EN_PLACES)},
            "ko": {"names": set(KO_GIVEN["f"] + KO_GIVEN["m"]),
                   "things": {n for n, _c in KO_ITEMS + KO_BUNDLES}, "places": set(KO_PLACES)}}


NEW_WORDS = _new_words()
for _lang in LANGS:
    for _table in ("names", "things", "places"):
        assert not NEW_WORDS[_lang][_table] & OLD_WORDS[_lang][_table], (_lang, _table)
    # no Korean name inside another name, a thing or a place, and none holding the first person's 나
    if _lang == "ko":
        _all = NEW_WORDS["ko"]["names"] | NEW_WORDS["ko"]["things"] | NEW_WORDS["ko"]["places"]
        assert not [(a, b) for a in NEW_WORDS["ko"]["names"] for b in _all if a != b and a in b]
        assert not [w for w in _all if "나" in w]


def halves():
    """{"build"|"check": {lang: {table: [...]}}}: every table cut in two by SEED."""
    rng = random.Random(SEED)
    tables = {"en": {"given_f": EN_GIVEN["f"], "given_m": EN_GIVEN["m"], "surnames": EN_SURNAMES,
                     "items": EN_ITEMS, "bundles": EN_BUNDLES, "places": EN_PLACES},
              "ko": {"given_f": KO_GIVEN["f"], "given_m": KO_GIVEN["m"], "surnames": KO_SURNAMES,
                     "items": KO_ITEMS, "bundles": KO_BUNDLES, "places": KO_PLACES}}
    out = {"build": {}, "check": {}}
    for lang, named in tables.items():
        for key, pool in named.items():
            pool = sorted(pool, key=lambda x: json.dumps(x, ensure_ascii=False))
            rng.shuffle(pool)
            cut = len(pool) // 2
            out["build"].setdefault(lang, {})[key] = pool[:cut]
            out["check"].setdefault(lang, {})[key] = pool[cut:]
    return out


# ---------------------------------------------------------------------------
# classes (G6 sections A to C, plus 15) and forms (the prompts: what a turn must look like)
# ---------------------------------------------------------------------------
CLASSES = ("1_count_words", "2_en_transfer_forms", "3_partitive", "4_fragment_count", "5_ko_transfer_verbs",
           "6_holder_forms", "7_leftover_questions", "8_time_adverb_questions", "9_other_predicates",
           "10_topic_switch", "11_repair_with_question", "12_cross_language", "13_why_with_fact",
           "15_unstated_receiver")
NOT_IN = {"en": {"5_ko_transfer_verbs"}, "ko": {"2_en_transfer_forms"}}
# the classes a dialogue is built around (1 is in every dialogue's statements, 12 by slot)
FOCUS = {lang: [c for c in CLASSES if c not in NOT_IN[lang] and c not in ("1_count_words", "12_cross_language")]
         for lang in LANGS}

# form code -> (class, description for the writer, by language)
FORMS = {
    # statements
    "fragment": ("4_fragment_count", {
        "en": "Say the fact without the number first, then give the number alone in a short fragment after it, "
              "in the same message: (holder) has some (things). (N), to be exact. / (giver) gave (receiver) "
              "some (things). (N) of them.",
        "ko": "먼저 수량 없이 말하고, 바로 뒤에 수량만 짧은 조각으로 덧붙인다 (한 메시지 안에서): (누구)한테 (물건)이 있어. "
              "(N) (단위)야. / (누구)가 (누구)한테 (물건)을 줬어. (N) (단위)."}),
    "title_ege_omit": ("6_holder_forms", {
        "ko": "직함이 붙은 사람을 '-에게는'(또는 '-한테는', '-께는')으로 말하고 물건 이름은 생략한다 (바로 앞 턴의 물건이다): "
              "(성) (직함)에게는 (N) (단위)가 있습니다."}),
    "job_apposition": ("6_holder_forms", {
        "en": "Introduce the holder with the job word first, then the name: (job), (title) (surname), ...",
        "ko": "직업 이름을 이름 바로 앞에 붙여 소개한다: (직업) (이름) 씨는 ..."}),
    "relation_also_vague": ("6_holder_forms", {
        "en": "Introduce the holder by a relation to someone already named, say they also have some of the "
              "thing, with no number: (anchor)'s (relation), (name), also has some (things).",
        "ko": "이미 나온 사람과의 관계로 소개하고 '도'를 붙여, 수량 없이 그 물건을 가지고 있다고만 말한다: "
              "(기준 인물) (관계) (이름)도 (물건)을 가지고 있어요."}),
    "responsible_front": ("6_holder_forms", {
        "en": "Start with the occasion, then say what the holder is responsible for: For (occasion), (holder) "
              "is responsible for (N) (things)."}),
    "place_receiver": ("6_holder_forms", {
        "en": "The receiver is a place: the giver left the things at the place (left N (things) at the (place)).",
        "ko": "받는 쪽이 장소다: 그 장소에 맡겼다/두고 왔다 ((장소)에 (N) (단위)를 맡겼습니다)."}),
    "carry_load": ("5_ko_transfer_verbs", {
        "ko": "'싣고 있다'로 말한다: (누구)는 (탈것)에 (물건)을 (N) (단위) 싣고 있어요."}),
    # transfers
    "double_object": ("2_en_transfer_forms", {
        "en": "Double object, no 'to': (giver) (verb) (receiver) (N) (things)."}),
    "particle_verb": ("2_en_transfer_forms", {
        "en": "Split particle verb: the things between the verb and its particle, then 'to' and the receiver: "
              "(giver) handed (N) (things) over to (receiver) / gave (N) (things) back to (receiver) / passed "
              "(N) (things) on to (receiver)."}),
    "partitive": ("3_partitive", {
        "en": "Refer to the things with a partitive pronoun instead of naming them: one of them, (N) of them "
              "(gave two of them to ..., used three of them for ...).",
        "ko": "물건 이름 대신 '그중'으로 가리킨다: 그중 하나, 그중 (N) (단위) (그중 두 개를 ...에게 줬어요, 그중 세 개로 ...을 "
              "만들었어요)."}),
    "omit_subject": ("5_ko_transfer_verbs", {
        "ko": "앞 턴과 주는 사람이 같으니 주어를 말하지 않고 이어서 말한다: 그리고 (받는 사람)에게 (N) (단위)를 주었다."}),
    # questions about one holder's count
    "q_plain": (None, {"en": "An ordinary question of how many the holder has.",
                       "ko": "몇 개 가지고 있는지 묻는 보통 질문."}),
    "q_left": ("7_leftover_questions", {
        "en": "Ask what is left or remains: how many does (holder) have left / are left with (holder) / remain "
              "with (holder).",
        "ko": "남은 수를 묻는다: (누구)에게 남은 (물건)은 몇 (단위)인가 / (물건) 몇 개 남았어."}),
    "q_now": ("8_time_adverb_questions", {
        "en": "Ask with a time adverb: at the moment, now.",
        "ko": "시간 부사를 넣어 묻는다: 이제, 지금 ((누구)는 이제 몇 개야?)."}),
    "q_got": ("9_other_predicates", {"en": "Ask with 'has ... got': How many (things) has (holder) got?"}),
    "q_responsible": ("9_other_predicates", {
        "en": "Ask with 'responsible for': How many (things) is (holder) responsible for?",
        "ko": "'맡고 있다'로 묻는다: (누구)는 (물건)을 몇 (단위) 맡고 있습니까?"}),
    "q_bundles": ("9_other_predicates", {
        "en": "Ask by the unit: How many bundles does (holder) have?",
        "ko": "단위로 묻는다: (누구)는 (물건)이 몇 묶음입니까?"}),
    "q_all": ("9_other_predicates", {
        "en": "Ask for the holder's count in all: How many (things) does (holder) have in all?",
        "ko": "'모두'로 묻는다: (누구)의 (물건)은 모두 몇 (단위)입니까?"}),
    # questions about two holders
    "q_combined": ("9_other_predicates", {
        "en": "Ask for the two holders' count together, naming both: combined / in total.",
        "ko": "두 사람을 이름으로 말하고 합한 수를 묻는다: 합쳐서 / 모두."}),
    "q_two_total": ("9_other_predicates", {
        "en": "Ask for the two holders' count together without their names: the two of them in total.",
        "ko": "이름 없이 두 사람이 합쳐 몇 개인지 묻는다: 둘이 합쳐서 몇 개예요?"}),
    "q_more": ("9_other_predicates", {
        "en": "Ask which of the two named holders has more.",
        "ko": "이름이 나온 두 사람 중 누가 더 많은지 묻는다: 둘 중에 누가 더 많이 가지고 있어요?"}),
    # topic switch: the previous question again, about a new holder, place or thing, by ellipsis only
    "switch_holder": ("10_topic_switch", {
        "en": "Only the new holder, as an ellipsis of the question before: What about (holder)? / And (holder)?",
        "ko": "앞 질문을 새 사람에 대해 생략형으로만: (누구)는요? / (누구)는?"}),
    "switch_place": ("10_topic_switch", {
        "en": "Only the new place, as an ellipsis of the question before: And in the (place)? / What about the "
              "(place)?",
        "ko": "앞 질문을 새 장소에 대해 생략형으로만: (장소)는요? / (장소)는 어떻습니까?"}),
    "switch_thing": ("10_topic_switch", {
        "en": "Only the new thing, as an ellipsis of the question before (same holder): And (things)?",
        "ko": "앞 질문을 같은 사람의 다른 물건에 대해 생략형으로만: (물건)은요? / (물건)은?"}),
    # repairs: the speaker meant another holder than the one just asked about
    "repair_question": ("11_repair_with_question", {
        "en": "Say which holder you meant and ask again in the same message: I mean (holder). How many does "
              "(holder) have? / It's (holder). How many does (holder) hold?",
        "ko": "뜻한 사람을 밝히고 같은 메시지에서 다시 묻는다: (누구) 말입니다. 몇 묶음입니까? / (누구)요. (누구)는 몇 개예요?"}),
    "repair_bare": ("11_repair_with_question", {
        "en": "Only the name of the holder you meant, no question: (holder), I mean. / (holder) is the one I mean.",
        "ko": "뜻한 사람의 이름만, 질문 없이: (누구)요. / (누구) 님입니다."}),
    # why, restating the fact
    "why_has": ("13_why_with_fact", {
        "en": "Why, naming the holder and the number: Why does (holder) have (N)?",
        "ko": "사람과 수를 넣어 왜냐고 묻는다: 왜 (누구)가 (N) (단위)야?"}),
    "why_end_up": ("13_why_with_fact", {
        "en": "Why, with 'end up': Why does (holder) end up with (N)?",
        "ko": "'되다'로 묻는다: (누구) (물건)이 왜 (N) (단위)가 되었습니까?"}),
    "why_reason": ("13_why_with_fact", {
        "en": "Ask for the reason, naming the holder and the number: What is the reason (holder) has (N)?",
        "ko": "까닭이나 이유를 묻는다: (누구)의 (물건)이 (N) (단위)가 된 까닭은 무엇인가?"}),
    "why_that_number": ("13_why_with_fact", {
        "en": "Why, with the number only (no holder): Why is that number (N)?",
        "ko": "사람 없이 수만 넣어: 왜 (N) (단위)예요?"}),
    "why_how": ("13_why_with_fact", {
        "en": "Ask how the last answer came about, with no holder and no number.",
        "ko": "방금 답이 어떻게 그렇게 되었는지 묻는다. 사람도 수도 넣지 않는다."}),
    "why_only_me": ("13_why_with_fact", {
        "en": "The speaker asks about their own count with 'only': Why do I only have (N)?",
        "ko": "말하는 사람 자신의 수를 '밖에'나 '만'으로: 왜 저는 (N) (단위)밖에 없어요?"}),
}
# transfer verbs: code -> description (the verb the writer uses), by language
VERBS = {
    "en": {"give": "gave", "send": "sent", "pass": "passed", "lend": "lent", "transfer": "transferred",
           "give_back": "returned (or gave ... back)", "hand_over": "handed ... over", "leave_at": "left ... at"},
    "ko": {"give": "주다 (줬다, 드렸다)", "give_formal": "주었다 (주었어요, 주었습니다)", "share_out": "나눠 주다",
           "lend": "빌려주다", "send": "보내다", "entrust": "맡기다 (장소에)"},
}
VERB_CLASS = {"en": {"transfer": "2_en_transfer_forms", "give_back": "2_en_transfer_forms",
                     "send": "2_en_transfer_forms", "pass": "2_en_transfer_forms", "leave_at": "2_en_transfer_forms",
                     "hand_over": "2_en_transfer_forms"},
              "ko": {"give_formal": "5_ko_transfer_verbs", "share_out": "5_ko_transfer_verbs",
                     "lend": "5_ko_transfer_verbs", "send": "5_ko_transfer_verbs",
                     "entrust": "5_ko_transfer_verbs"}}
REGISTERS = {"en": ("casual", "neutral", "formal"), "ko": ("haeyo", "hapsyo", "banmal", "haera")}


# ---------------------------------------------------------------------------
# the scenario
# ---------------------------------------------------------------------------
class Plan:
    """One dialogue's truth: holders, things, and turns of structured facts with their forms."""

    def __init__(self, lang, half, slot, vocab, focus, rng, cross):
        self.lang, self.half, self.slot, self.v, self.focus, self.rng = lang, half, slot, vocab, set(focus), rng
        self.en = lang == "en"
        self.cross = cross
        self.register = rng.choice(REGISTERS[lang])
        self.used = set()
        self.holders, self.things, self.turns = [], [], []
        self.introduced = set()
        self.state = {}                 # (holder id, thing id) -> count, None when stated without one

    def pick(self, key):
        pool = [x for x in self.v[key] if json.dumps(x, ensure_ascii=False) not in self.used]
        choice = self.rng.choice(pool)
        self.used.add(json.dumps(choice, ensure_ascii=False))
        return choice

    def given(self, gender=None):
        gender = gender or self.rng.choice("fm")
        return self.pick("given_" + gender), gender

    def holder(self, kind, anchor=None):
        rng, en = self.rng, self.en
        hid = "ABCDE"[len(self.holders)]
        h = {"id": hid, "kind": kind}
        if kind == "name":
            name, _g = self.given()
            h.update(entity=name, tokens=[name], first=name, later=name)
        elif kind == "title":
            if en:
                g = rng.choice("fm")
                title, surname = rng.choice(EN_TITLES[g]), self.pick("surnames")
                h.update(entity=surname, tokens=[surname], first="%s %s" % (title, surname),
                         later="%s %s" % (title, surname), title=title)
            else:
                surname, job = self.pick("surnames"), rng.choice(KO_JOB_TITLES)
                entity = "%s %s" % (surname, job)
                h.update(entity=entity, tokens=[entity], first=entity + "님", later=entity + "님", title=job)
        elif kind == "relation":
            relation, rg = rng.choice(KO_RELATIONS if not en else EN_RELATIONS)
            name, _g = self.given(rg)
            if anchor is not None:
                owner = (anchor["later"] + "'s") if en else anchor["later"]
                h["anchor"] = anchor["id"]
            else:
                owner = "my" if en else ("내" if self.register in ("banmal", "haera") else "제")
            first = ("%s %s, %s" if en else "%s %s %s") % (owner, relation, name)
            h.update(entity=name, tokens=[name], first=first, later=name, relation=relation)
        elif kind == "apposition":
            role = rng.choice(EN_ROLES if en else KO_ROLES)
            if en:
                g = rng.choice("fm")
                title, surname = rng.choice(EN_TITLES[g]), self.pick("surnames")
                h.update(entity=surname, tokens=[surname], first="%s, %s %s" % (role, title, surname),
                         later="%s %s" % (title, surname), role=role)
            else:
                name, _g = self.given()
                h.update(entity=name, tokens=[name], first="%s %s 씨" % (role, name), later=name + " 씨", role=role)
        elif kind == "first_person":
            h.update(entity="I" if en else "나", tokens=[],
                     first="I (the speaker)" if en else "나 (말하는 사람 자신: 저/나)",
                     later="I (the speaker)" if en else "나 (말하는 사람 자신: 저/나)")
        elif kind == "place":
            place = self.pick("places")
            h.update(entity=place, tokens=[place], first=("the " + place) if en else place,
                     later=("the " + place) if en else place)
        else:
            raise ValueError(kind)
        self.holders.append(h)
        return h

    def thing(self, bundle=False):
        tid = "xyz"[len(self.things)]
        if self.en:
            plural, one = self.pick("bundles" if bundle else "items")
            t = {"id": tid, "key": plural, "plural": plural, "one": one}
        else:
            noun, counter = self.pick("bundles" if bundle else "items")
            t = {"id": tid, "key": noun, "noun": noun, "counter": counter}
        if bundle:
            t["unit"] = "bundles" if self.en else "묶음"
        self.things.append(t)
        return t

    def count_as(self):
        return "word" if self.rng.random() < 0.62 else "digits"

    def turn(self, act, mentioned, forms=(), classes=(), **fields):
        n = len(self.turns) + 1
        refer, first = {}, []
        for h in mentioned:
            if h["id"] not in self.introduced:
                first.append(h["id"])
                self.introduced.add(h["id"])
                refer[h["id"]] = h["first"]
            else:
                refer[h["id"]] = h["later"]
            if h.get("anchor") and h["id"] in first:
                a = next(x for x in self.holders if x["id"] == h["anchor"])
                refer.setdefault(a["id"], a["later"])
        forms = [f for f in forms if f]
        cls = set(classes) | {FORMS[f][0] for f in forms if FORMS[f][0]}
        if fields.get("count_as") == "word":
            cls.add("1_count_words")
        if fields.get("verb") in VERB_CLASS[self.lang]:
            cls.add(VERB_CLASS[self.lang][fields["verb"]])
        t = {"n": n, "act": act, **fields, "forms": forms, "refer": refer, "first": first, "classes": sorted(cls)}
        self.turns.append(t)
        return t

    # -- facts -------------------------------------------------------------------------------------
    def has(self, h, x, count, forms=(), **extra):
        self.state[h["id"], x["id"]] = count
        fields = {"holder": h["id"], "thing": x["id"], "count": count, **extra}
        if count is not None:
            fields["count_as"] = self.count_as()
        return self.turn("has", [h], forms, **fields)

    def give(self, g, r, x, k, verb, forms=(), classes=()):
        self.state[g["id"], x["id"]] -= k
        if self.state.get((r["id"], x["id"])) is not None:
            self.state[r["id"], x["id"]] += k
        else:
            self.state[r["id"], x["id"]] = None
        mentioned = [r] if "omit_subject" in forms else [g, r]
        if r["kind"] == "place":
            forms = list(forms) + ["place_receiver"]
        return self.turn("give", mentioned, forms, classes, giver=g["id"], receiver=r["id"], thing=x["id"],
                         count=k, count_as=self.count_as(), verb=verb)

    def use(self, h, x, k, forms=()):
        self.state[h["id"], x["id"]] -= k
        purpose = self.rng.choice(EN_PURPOSES if self.en else KO_PURPOSES)
        return self.turn("use", [h], forms, holder=h["id"], thing=x["id"], count=k, count_as=self.count_as(),
                         purpose=purpose)

    def value(self, h, x):
        return self.state.get((h["id"], x["id"]))


def _asks_ok(p, h, x):
    """A holder whose count may be asked: known, above zero, and no other holder of the thing at that count."""
    v = p.value(h, x)
    if v is None or v <= 0:
        return False
    return not any(val == v for (hid, tid), val in p.state.items() if tid == x["id"] and hid != h["id"])


def _plan(p):
    rng, en, f = p.rng, p.en, p.focus
    form6 = None
    if "6_holder_forms" in f:
        form6 = rng.choice(["job_apposition", "relation_also_vague", "place_receiver"]
                           + (["responsible_front"] if en else ["title_ege_omit"]))
    switch = None
    if "10_topic_switch" in f:
        switch = rng.choice(["switch_holder", "switch_holder", "switch_place", "switch_thing"])
    only_me = "13_why_with_fact" in f and rng.random() < 0.3
    bundles = "9_other_predicates" in f and rng.random() < 0.35

    # -- cast: the holders with a stated count first --------------------------------------------------
    kinds = ["name", rng.choice(["name", "name", "title", "relation"])]
    if rng.random() < 0.3:
        kinds[0] = rng.choice(["title", "relation"])
    if form6 == "job_apposition":
        kinds[1] = "apposition"
    if form6 == "title_ege_omit":
        kinds[1] = "title"
    if only_me:
        kinds[0] = "first_person"
    if switch == "switch_place":
        kinds = [kinds[0], "place", "place"]
    elif form6 == "place_receiver" or rng.random() < 0.15:
        kinds.append("place")
    elif rng.random() < 0.3:
        kinds.append("name")
    rng.shuffle(kinds)
    if only_me and kinds[0] != "first_person":
        kinds.remove("first_person")
        kinds.insert(0, "first_person")
    if form6 == "title_ege_omit" and kinds.index("title") == 0:
        kinds[0], kinds[1] = kinds[1], kinds[0]
    stated = []
    for k in kinds:
        anchor = stated[0] if k == "relation" and stated and rng.random() < 0.5 and stated[0]["kind"] in (
            "name", "title") else None
        stated.append(p.holder(k, anchor))
    x = p.thing(bundle=bundles)
    y = p.thing() if switch == "switch_thing" else None
    vague = None
    if form6 == "relation_also_vague":
        anchors = [h for h in stated if h["kind"] in ("name", "title")]
        if not anchors:
            return False
        vague = p.holder("relation", anchors[0])
    unstated = p.holder(rng.choice(["name", "name", "title"])) if "15_unstated_receiver" in f else None

    # -- openings -------------------------------------------------------------------------------------
    starts = rng.sample(range(3, 25), len(stated))
    fragment_done = False
    for i, (h, n) in enumerate(zip(stated, starts)):
        forms = []
        extra = {}
        if form6 == "title_ege_omit" and h["kind"] == "title" and i > 0:
            forms.append("title_ege_omit")
        elif form6 == "job_apposition" and h["kind"] == "apposition":
            forms.append("job_apposition")
        elif form6 == "responsible_front" and i == 0 and h["kind"] != "place":
            forms.append("responsible_front")
            extra["occasion"] = rng.choice(EN_OCCASIONS)
        elif "4_fragment_count" in f and not fragment_done and rng.random() < 0.6:
            forms.append("fragment")
            fragment_done = True
        elif not en and "5_ko_transfer_verbs" in f and h["kind"] not in ("place",) and rng.random() < 0.35:
            forms.append("carry_load")
            extra["vehicle"] = rng.choice(KO_VEHICLES)
        p.has(h, x, n, forms, **extra)
        if y is not None and i == 0:
            p.has(h, y, rng.choice([v for v in range(3, 25) if v not in starts]))
    if vague is not None:
        p.has(vague, x, None, ["relation_also_vague"])

    # -- events ---------------------------------------------------------------------------------------
    persons = [h for h in stated if h["kind"] != "place"]
    places = [h for h in stated if h["kind"] == "place"]

    def pick_verb(r):
        if r["kind"] == "place":
            return "leave_at" if en else "entrust"
        if en:
            pool = ["give", "send", "pass", "lend"]
            if "2_en_transfer_forms" in f:
                pool = ["transfer", "give_back", "send", "pass", "hand_over", "give"]
        else:
            pool = ["give", "give", "send", "lend"]
            if "5_ko_transfer_verbs" in f:
                pool = ["give_formal", "share_out", "lend", "send", "give"]
        return rng.choice(pool)

    def give_forms(verb, previous_mentions_x, first_event):
        forms = []
        if en and "2_en_transfer_forms" in f and verb != "leave_at":
            if verb in ("hand_over", "give_back", "pass") and rng.random() < 0.6:
                forms.append("particle_verb")
            elif verb in ("give", "send", "pass", "lend") and rng.random() < 0.7:
                forms.append("double_object")
        if "3_partitive" in f and previous_mentions_x and rng.random() < 0.6:
            forms.append("partitive")
        elif "4_fragment_count" in f and not fragment_done and first_event:
            forms.append("fragment")
        return forms

    givers = [h for h in persons if (p.value(h, x) or 0) >= 3]
    if not givers:
        return False
    g = rng.choice(givers)
    if unstated is not None:
        r = unstated
    elif form6 == "place_receiver" and places:
        r = places[0]
    else:
        others = [h for h in stated if h is not g and p.value(h, x) is not None]
        if not others:
            return False
        r = rng.choice(others)
    verb = pick_verb(r)
    k = rng.randint(1, min(5, p.value(g, x) - 1))
    prev = p.turns[-1]
    forms = give_forms(verb, prev.get("thing") == x["id"] and g["id"] in (prev.get("holder"), prev.get("receiver")),
                       True)
    fragment_done = fragment_done or "fragment" in forms
    p.give(g, r, x, k, verb, forms, ["15_unstated_receiver"] if r is unstated else [])
    # a second event: the same giver again with the subject left out (ko 5), a partitive use (3), or another give
    if not en and "5_ko_transfer_verbs" in f and p.value(g, x) >= 2 and rng.random() < 0.6:
        targets = [h for h in stated if h is not g and h["kind"] != "place" and p.value(h, x) is not None]
        if targets:
            r2 = rng.choice(targets)
            p.give(g, r2, x, rng.randint(1, min(4, p.value(g, x) - 1)), rng.choice(["give_formal", "give"]),
                   ["omit_subject"])
    elif "3_partitive" in f and not any("partitive" in t["forms"] for t in p.turns):
        users = [h for h in persons if (p.value(h, x) or 0) >= 3]
        if users:
            h = rng.choice(users)
            p.use(h, x, rng.randint(1, min(4, p.value(h, x) - 1)), ["partitive"])
    elif rng.random() < 0.35:
        more = [h for h in persons if (p.value(h, x) or 0) >= 3]
        if more:
            g2 = rng.choice(more)
            targets = [h for h in stated if h is not g2 and p.value(h, x) is not None]
            if targets:
                r2 = rng.choice(targets)
                verb2 = pick_verb(r2)
                p.give(g2, r2, x, rng.randint(1, min(4, p.value(g2, x) - 1)), verb2,
                       give_forms(verb2, True, False))

    # -- questions ------------------------------------------------------------------------------------
    ask_forms = []
    if "7_leftover_questions" in f:
        ask_forms.append("q_left")
    if "8_time_adverb_questions" in f:
        ask_forms.append("q_now")
    if "9_other_predicates" in f:
        options = ["q_responsible", "q_all"] + (["q_got"] if en else [])
        ask_forms.append("q_bundles" if bundles else rng.choice(options))
    rng.shuffle(ask_forms)

    def next_form(h):
        for form in list(ask_forms):
            if h["kind"] == "place" and form in ("q_got", "q_responsible", "q_all"):
                continue
            if h["kind"] == "first_person" and form == "q_responsible":
                continue
            ask_forms.remove(form)
            return form
        return "q_plain"

    cross_left = [p.cross]
    last = {}

    def ask(h, thing=None, form=None):
        thing = thing or x
        form = form or next_form(h)
        fields = {}
        if cross_left[0] and form == "q_plain" and h["kind"] != "first_person":
            fields["ask_in"] = "ko" if en else "en"
            cross_left[0] = False
        t = p.turn("ask", [h], [form], ["12_cross_language"] if fields else [], holder=h["id"], thing=thing["id"],
                   **fields)
        last.update(holder=h, thing=thing, n=t["n"])
        return t

    def askable(pool, thing=None):
        return [h for h in pool if _asks_ok(p, h, thing or x)]

    first_q = askable([g] + [h for h in stated if h is not g])
    if only_me:
        first_q = [h for h in first_q if h["kind"] == "first_person"] or first_q
    if switch == "switch_place":
        first_q = [h for h in first_q if h["kind"] == "place"] or first_q
    if switch == "switch_thing":
        first_q = [h for h in first_q if h is stated[0]] or first_q
    if not first_q:
        return False
    q1 = first_q[0]
    if "11_repair_with_question" in f:
        # the repair: a question about one holder, then the one meant
        meant = [h for h in askable(stated) if h is not q1 and h["kind"] != "place"]
        if not meant or q1["kind"] == "place":
            return False
        a = meant[0]
        ask(q1)
        if rng.random() < 0.5:
            t = p.turn("repair", [a], ["repair_question"], holder=a["id"], asked=q1["id"], thing=x["id"],
                       after=last["n"])
            last.update(holder=a, thing=x, n=t["n"])
        else:
            p.turn("repair", [a], ["repair_bare"], holder=a["id"], asked=q1["id"], thing=x["id"], after=last["n"])
            ask(a)
    else:
        ask(q1)
    if switch:
        h0 = last["holder"]
        if switch == "switch_thing":
            if h0 is not stated[0] or not _asks_ok(p, h0, y):
                return False
            t = p.turn("switch", [], ["switch_thing"], holder=h0["id"], thing=y["id"], after=last["n"])
            last.update(thing=y, n=t["n"])
        else:
            pool = [h for h in askable(stated) if h is not h0 and (h["kind"] == "place") == (switch == "switch_place")]
            if not pool:
                return False
            h1 = pool[0]
            t = p.turn("switch", [h1], [switch], holder=h1["id"], thing=x["id"], after=last["n"])
            last.update(holder=h1, thing=x, n=t["n"])
    if "13_why_with_fact" in f:
        h, thing = last["holder"], last["thing"]
        if h["kind"] == "first_person":
            form = "why_only_me"
        else:
            form = rng.choice(["why_has", "why_end_up", "why_reason", "why_that_number", "why_how"])
        count = p.value(h, thing)
        fields = {"holder": h["id"], "thing": thing["id"], "after": last["n"]}
        if form != "why_how":
            fields.update(count=count, count_as=p.count_as())
        p.turn("why", [] if form in ("why_that_number", "why_how") else [h], [form], **fields)
    if unstated is not None:
        if last.get("holder") is not g and _asks_ok(p, g, x):
            ask(g)
        p.turn("ask", [unstated], [next_form(unstated)], ["15_unstated_receiver"], holder=unstated["id"],
               thing=x["id"], hold=True)
    if vague is not None:
        p.turn("ask", [vague], [next_form(vague)], ["6_holder_forms"], holder=vague["id"], thing=x["id"], hold=True)
    if "9_other_predicates" in f:
        pair = [h for h in stated if h["kind"] != "place" and (p.value(h, x) or 0) > 0]
        if len(pair) >= 2:
            a, b = pair[:2]
            options = ["q_combined", "q_more"] + (["q_two_total"] if len(p.holders) == 2 else [])
            form = rng.choice(options)
            if form == "q_more" and p.value(a, x) == p.value(b, x):
                form = "q_combined"
            p.turn("ask_more" if form == "q_more" else "ask_total", [] if form == "q_two_total" else [a, b],
                   [form], holders=[a["id"], b["id"]], thing=x["id"])
    # the forms and the cross-language question not placed yet go on questions about the others
    rest = [h for h in askable(stated) if h is not last.get("holder")]
    def answerable():
        return sum(t["act"] in ("ask", "switch", "repair", "ask_total", "ask_more") and not t.get("hold")
                   for t in p.turns)
    while (ask_forms or cross_left[0] or answerable() < 2) and rest and len(p.turns) < 10:
        ask(rest.pop(0))
    if ask_forms or cross_left[0]:
        return False
    return True


def scenario_json(p, sid):
    return {"id": sid, "language": p.lang, "half": p.half, "register": p.register,
            "classes": sorted({c for t in p.turns for c in t["classes"]}), "focus": sorted(p.focus),
            "holders": p.holders, "things": p.things, "turns": p.turns}


def valid(scn):
    """The scenario plays out: 4 to 10 turns, two answerable questions or more, and every expectation replays
    (``bench/dialogue_gate.py`` ``validate`` on the dialogue the scenario becomes)."""
    turns = gate_turns(scn, scn["turns"])
    if not 4 <= len(turns) <= 10 or sum(t["label"] == "answerable" for t in turns) < 2:
        return False
    for t, st in zip(turns, scn["turns"]):
        if st["act"] == "why" and st.get("count") is not None and st["count"] != t["expect"]["quantity"]:
            return False
        if t["label"] == "hold" and t["expect"]["act"] == "hold" and not st.get("hold"):
            return False
    d = dialogue_json(scn, turns, "check")
    problems = [x for x in gate.validate([d]) if x.startswith(d["id"])]
    return not problems


def generate(half, lang, vocab=None):
    """PER_HALF scenarios: slot j is built around its focus classes; a draw that does not play out is drawn
    again (the attempt is part of the seed)."""
    vocab = vocab or halves()
    focus_pool = FOCUS[lang]
    out = []
    for slot in range(PER_HALF):
        focus = {focus_pool[(slot + k) % len(focus_pool)] for k in (0, 4, 7)}
        for attempt in range(500):
            rng = random.Random("%d/%s/%s/%d/%d" % (SCENARIO_SEEDS[half], lang, half, slot, attempt))
            p = Plan(lang, half, slot, vocab[half][lang], focus, rng, slot % CROSS_EVERY == 0)
            try:
                ok = _plan(p)
            except (KeyError, ValueError, IndexError):
                ok = False
            if not ok:
                continue
            scn = scenario_json(p, "s6_%s_%s_%03d" % (lang, half[0], slot + 1))
            if valid(scn):
                out.append(scn)
                break
        else:
            raise RuntimeError("slot %d of %s %s does not play out" % (slot, half, lang))
    return out


def load_scenarios(folder=HERE):
    out = {}
    for half in HALVES:
        for lang in LANGS:
            path = scenarios_path(half, lang, folder)
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        scn = json.loads(line)
                        out[scn["id"]] = scn
    return out


# ---------------------------------------------------------------------------
# expectations: recomputed from the scenario, never from a text
# ---------------------------------------------------------------------------
SCHEMA = gate.SCHEMA


def gate_turns(scn, kept, texts=None):
    """The dialogue turns (gate format) of the scenario turns ``kept``, numbered from 1: every expectation by
    replaying the kept statements (``gate._apply``); ``texts`` {scenario turn n: text} fills ``say``."""
    holders = {h["id"]: h for h in scn["holders"]}
    things = {t["id"]: t for t in scn["things"]}
    state, touched, moved, out = {}, {}, set(), []
    other = {"en": "ko", "ko": "en"}[scn["language"]]

    def entity(hid):
        return holders[hid]["entity"]

    def evidence(e):
        return sorted(set(touched.get(e, [])))

    def answer(hid, key, n):
        e = entity(hid)
        value = state.get((e, key))
        if value is None:
            return {"act": "hold", "entity": e, "quantity": None, "relation": "count", "evidence": {"turns": [n]},
                    "item": key}, "hold", ["missing_premise"]
        return ({"act": "answer", "entity": e, "quantity": value, "relation": "count",
                 "evidence": {"turns": evidence(e)}, "item": key}, "answerable",
                ["transfer" if e in moved else "ownership"])

    for i, t in enumerate(kept):
        n = i + 1
        act = t["act"]
        key = things[t["thing"]]["key"] if t.get("thing") else None
        if act in ("has", "give", "use"):
            if act == "has":
                events = [{"type": "has", "holder": entity(t["holder"]), "item": key, "quantity": t["count"]}]
            elif act == "give":
                events = [{"type": "transfer", "from": entity(t["giver"]), "to": entity(t["receiver"]), "item": key,
                           "quantity": t["count"]}]
            else:
                events = [{"type": "use", "holder": entity(t["holder"]), "item": key, "quantity": t["count"]}]
            rows = []
            for ev in events:
                gate._apply(state, ev)
                for field in ("holder", "from", "to"):
                    if field in ev:
                        touched.setdefault(ev[field], []).append(n)
                        if act != "has":
                            moved.add(ev[field])
                        rows.append({"entity": ev[field], "item": key, "quantity": state.get((ev[field], key))})
            expect = {"act": "record", "entity": None, "quantity": None, "relation": None,
                      "evidence": {"turns": [n]}, "events": events, "state": rows}
            label, tags = "hold", ["ownership" if act == "has" else "transfer"]
        elif act in ("ask", "switch", "repair"):
            expect, label, tags = answer(t["holder"], key, n)
            if act == "switch":
                tags = tags + ["follow_up"]
            if act == "repair":
                tags = tags + ["ambiguous_referent"]
        elif act == "why":
            e = entity(t["holder"])
            expect = {"act": "explain", "entity": e, "quantity": state.get((e, key)), "relation": "count",
                      "evidence": {"turns": evidence(e)}, "item": key}
            label, tags = "why", ["why"]
        elif act == "ask_total":
            names = [entity(h) for h in t["holders"]]
            values = [state.get((e, key)) for e in names]
            expect = {"act": "answer", "entity": names, "quantity": sum(values), "relation": "total",
                      "evidence": {"turns": sorted({x for e in names for x in evidence(e)})}, "item": key}
            label, tags = "answerable", ["transfer" if set(names) & moved else "ownership"]
        elif act == "ask_more":
            a, b = [entity(h) for h in t["holders"]]
            expect = {"act": "answer", "entity": a if state[a, key] > state[b, key] else b, "quantity": None,
                      "relation": "more", "candidates": [a, b], "item": key,
                      "evidence": {"turns": sorted(set(evidence(a) + evidence(b)))}}
            label, tags = "answerable", ["transfer" if {a, b} & moved else "ownership"]
        else:
            raise ValueError(act)
        turn = {"n": n, "say": (texts or {}).get(t["n"], "x"), "label": label, "tags": sorted(set(tags)),
                "classes": t["classes"], "scenario_turn": t["n"], "expect": expect}
        if t.get("ask_in"):
            turn["lang"] = other
            turn["tags"] = sorted(set(turn["tags"]) | {"cross_language"})
        out.append(turn)
    return out


def dialogue_json(scn, turns, new_id=None, source=None):
    return {"schema": SCHEMA, "id": new_id or scn["id"], "language": scn["language"], "domain": "everyday",
            "categories": sorted({tag for t in turns for tag in t["tags"]}),
            "variation": {"word_order": "free", "register": scn["register"],
                          "split": "multi_fact" if len(turns[0]["expect"].get("events") or []) > 1 else
                          "one_fact_per_turn",
                          "correction_position": "none", "roles": "scenario", "initial_values": {},
                          "scenario": scn["id"], "half": scn["half"], "focus": scn["focus"],
                          "phraser": source, "classes": sorted({c for t in turns for c in t["classes"]})},
            "turns": turns}


# ---------------------------------------------------------------------------
# the checker
# ---------------------------------------------------------------------------
EN_NUMBER_WORDS = set(v4.EN_WORDS) | set(v4.EN_TENS)
QUESTION_WORDS = {"en": r"\bhow many\b|\bhow much\b|\bwho\b|\bwhich\b|\bwhy\b|\bhow come\b|\bwhat\b|\bhow\b",
                  "ko": r"몇|누가|누구|얼마|왜|무엇|뭐|까닭|이유|어떻게"}
WHY_WORDS = {"en": r"\bwhy\b|\breason\b|\bhow come\b|\bhow\b", "ko": r"왜|까닭|이유|어째서|어떻게"}
EN_STARTERS = {"it", "that", "this", "there", "what", "who", "which", "how", "why", "and", "but", "so", "then",
               "now", "she", "he", "they", "we", "you", "oh", "well", "also", "actually", "sorry", "right", "okay",
               "ok", "yes", "no", "please", "just", "only", "both", "all", "each", "some", "the", "my", "our", "his",
               "her", "their", "your", "for", "after", "later", "apparently", "together", "anyway", "in", "at",
               "to", "a", "an", "is", "does", "do", "did", "has", "have", "are", "was"} | set(v4.EN_WORDS)
EN_SUBJECT_VERBS = (r"has|have|had|gave|got|is|was|used|left|sent|passed|handed|returned|transferred|lent|keeps|"
                    r"kept|owns|holds|also|'s")
FORM_CUES = {
    "en": {
        "responsible_front": r"^\s*for\b.*\bresponsible for\b",
        "relation_also_vague": r"\balso\b|\btoo\b|\bas well\b",
        "partitive": r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+) of (?:them|those|these)\b",
        "q_plain": r"\bhow many\b",
        "q_left": r"\bleft\b|\bremain",
        "q_now": r"\bat the moment\b|\bnow\b|\bcurrently\b|\bat present\b",
        "q_got": r"\bgot\b",
        "q_responsible": r"\bresponsible for\b",
        "q_bundles": r"\bhow many bundles\b",
        "q_all": r"\bin all\b|\baltogether\b|\bin total\b|\ball together\b",
        "q_combined": r"\bcombined\b|\bin total\b|\btogether\b|\baltogether\b|\bbetween them\b",
        "q_two_total": r"\btwo of them\b|\bboth of them\b",
        "q_more": r"\b(?:who|which)\b.*\bmore\b",
        "switch_holder": r"^\s*(?:and|what about|how about)\b",
        "switch_place": r"^\s*(?:and|what about|how about)\b",
        "switch_thing": r"^\s*(?:and|what about|how about)\b",
        "why_end_up": r"\bend(?:s|ed)? up\b",
        "why_reason": r"\breason\b",
        "why_only_me": r"\bonly\b",
        "repair_question": r"\bmean\b|\bmeant\b|\bit's\b|\bit is\b|\btalking about\b|\basking about\b|\bsorry\b|\bactually\b",
        "repair_bare": r"\bmean\b|\bmeant\b|\bone\b",
    },
    "ko": {
        "title_ege_omit": None,          # checked with the holder's token below
        "relation_also_vague": r"도\s",
        "carry_load": r"싣|실었|실어|실은",
        "partitive": r"그중|그 중|그 가운데",
        "q_plain": r"몇",
        "q_left": r"남",
        "q_now": r"이제|지금",
        "q_responsible": r"맡",
        "q_bundles": r"몇\s?묶음",
        "q_all": r"모두|전부|다 합",
        "q_combined": r"합|모두|전부|같이",
        "q_two_total": r"둘이|두 사람|두 분|둘 다|둘을|두 명|둘은|둘의|둘 합|둘 모두|둘이서",
        "q_more": r"(?:누가|누구).*더|더.*(?:누가|누구)",
        "why_end_up": r"되었|됐|된|돼",
        "why_reason": r"까닭|이유",
        "why_only_me": r"밖에|만\s|뿐",
        "repair_question": r"말입니다|말이에요|말이야|말이요|말씀|요\.|입니다\.|이에요\.|예요\.|이야\.|야\.",
        "repair_bare": r"요\.?$|입니다\.?$|이에요\.?$|예요\.?$|이요\.?$|야\.?$|이야\.?$|말이에요\.?$|말입니다\.?$",
    },
}
EN_VERB_CUES = {"give": r"\bgave\b", "send": r"\bsent\b", "pass": r"\bpassed\b", "lend": r"\blent\b|\bloaned\b",
                "transfer": r"\btransferred\b", "give_back": r"\breturned\b|\bgave\b.{0,40}\bback\b",
                "hand_over": r"\bhanded\b", "leave_at": r"\bleft\b|\bdropped off\b", "use": r"\bused\b|\bus(?:e|ing)\b"}
KO_VERB_CUES = {"give": r"줬|주었|줘|준|주고|드렸|드려|드린|드립|주셨", "give_formal": r"주었|드렸",
                "share_out": r"나눠\s?주|나눠\s?줬|나누어\s?주|나눠\s?드|나누어\s?드",
                "lend": r"빌려\s?주|빌려\s?줬|빌려\s?드", "send": r"보냈|보내|보낸", "entrust": r"맡겼|맡겨|맡기|맡긴",
                "use": r"썼|써|사용|만들|쓰"}


def _sentences(text):
    return [s for s in re.split(r"(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bMrs\.)(?<=[.!?])\s+", text.strip()) if s.strip()]


def _normalize_numbers(lang, text):
    """'twenty four' reads as 'twenty-four'; 스물 네 as 스물네 (the numeral tables read the joined forms)."""
    if lang == "en":
        return re.sub(r"(?i)\b(twenty|thirty|forty|fifty) (one|two|three|four|five|six|seven|eight|nine)\b",
                      r"\1-\2", text)
    return re.sub(r"(?<![가-힣])(열|스물) (한|두|세|네|다섯|여섯|일곱|여덟|아홉|하나|둘|셋|넷)", r"\1\2", text)


def numbers(lang, text, singulars=()):
    """[(value, start, end)]: digits, English number words, Korean native numerals (-1: an amount no scenario
    gives, such as a dozen or a few; -2: a Sino-Korean numeral before a native counter)."""
    return v4.en_numbers(text, singulars) if lang == "en" else v4.ko_numbers(text)


def _has(lang, text, token):
    if lang == "en" or re.fullmatch(r"[A-Za-z .'-]+", token):
        return re.search(r"(?<![A-Za-z])%s(?![a-z])" % re.escape(token), text, re.I) is not None
    return token in text or token.replace(" ", "") in text.replace(" ", "")


def _at(lang, text, token):
    if lang == "en" or re.fullmatch(r"[A-Za-z .'-]+", token):
        m = re.search(r"(?<![A-Za-z])%s(?![a-z])" % re.escape(token), text, re.I)
        return m.start() if m else None
    i = text.find(token)
    return i if i >= 0 else None


def _thing_named(lang, text, thing):
    if lang == "en" or "plural" in thing:
        words = [thing.get("plural"), thing.get("one")] + (["bundle", "bundles"] if thing.get("unit") else [])
        return any(w and _has("en", text, w) for w in words)
    return _has("ko", text, thing["noun"])


class Checker6:
    """Keeps a written turn only if it says the turn's facts in the turn's form, and nothing else."""

    def __init__(self):
        self.pools = {lang: {"names": OLD_WORDS[lang]["names"] | NEW_WORDS[lang]["names"],
                             "things": OLD_WORDS[lang]["things"] | NEW_WORDS[lang]["things"],
                             "places": OLD_WORDS[lang]["places"] | NEW_WORDS[lang]["places"]}
                      for lang in LANGS}

    def check(self, scn, turn, text):
        """(True, "ok") or (False, reason)."""
        if not isinstance(text, str):
            return False, "not_text"
        text = _normalize_numbers(scn["language"], text.strip())
        lang = turn.get("ask_in") or scn["language"]
        forms = turn["forms"]
        holders = {h["id"]: h for h in scn["holders"]}
        things = {t["id"]: t for t in scn["things"]}
        if not text:
            return False, "empty"
        if "\n" in text or len(text) > 300:
            return False, "shape"
        if re.search(r"[\"“”()\[\]{}<>]|^\w+\s*:", text):
            return False, "quote_or_label"
        if "..." in text or "…" in text:
            return False, "ellipsis_dots"
        # script: the dialogue's language, the other only in a name of the scenario
        rest = text
        for h in scn["holders"]:
            for tok in h["tokens"]:
                rest = rest.replace(tok, " ")
        for t in scn["things"]:
            rest = rest.replace(t.get("noun") or t["plural"], " ")
        if lang == "en" and re.search(r"[가-힣぀-ヿ一-鿿]", rest):
            return False, "script"
        if lang == "ko" and re.search(r"[A-Za-z぀-ヿ一-鿿]", rest):
            return False, "script"
        question = text.endswith("?")
        wants_question = turn["act"] not in ("has", "give", "use") and "repair_bare" not in forms
        if question != wants_question:
            return False, "question_mark" if wants_question else "statement_is_question"
        if "?" in text[:-1] and "repair_question" not in forms:
            return False, "two_questions"
        sentences = _sentences(text)
        if len(sentences) > (2 if forms and forms[0] in ("fragment", "repair_question", "omit_subject") or
                             turn["act"] in ("has", "give", "use") else 1):
            return False, "too_many_sentences"
        # numbers
        things_here = [things[turn["thing"]]] if turn.get("thing") else []
        found = numbers(lang, text, [t.get("one") for t in scn["things"] if t.get("one")])
        values = [v for v, _s, _e in found]
        if -2 in values:
            return False, "sino_korean_numeral"
        if -1 in values:
            return False, "vague_or_derived_amount"
        wanted = [] if turn.get("count") is None or "why_how" in forms else [turn["count"]]
        allowed = set(wanted)
        if set(forms) & {"q_two_total", "q_combined", "q_more"}:
            allowed.add(2)
        extra = [v for v in values if v not in allowed]
        if extra:
            return False, "extra_number:%s" % extra
        for v in wanted:
            if v not in values:
                return False, "missing_number:%d" % v
        if wanted and turn.get("count_as") == "word" and re.search(r"\d", text):
            return False, "count_not_in_words"
        if wanted and turn.get("count_as") == "digits" and not re.search(r"(?<!\d)%d(?!\d)" % wanted[0], text):
            return False, "count_not_in_digits"
        # holders: the ones the turn names, and no other
        required = [holders[hid] for hid in turn["refer"] if hid in self._named(turn)]
        may = set(turn["refer"]) | ({turn["asked"]} if turn.get("asked") else set())
        for h in required:
            for tok in h["tokens"]:
                if not _has(lang, text, tok):
                    return False, "missing_holder:%s" % tok
            if h["kind"] == "first_person" and not (v4.EN_FIRST if lang == "en" else v4.KO_FIRST).search(text):
                return False, "missing_first_person"
            if h["id"] in turn["first"]:
                for word in (h.get("relation"), h.get("role")):
                    if word and not _has(lang, text, word.replace("the ", "").replace("our ", "")):
                        return False, "missing_intro:%s" % word
                if lang == "en" and h.get("title") and not re.search(
                        r"\b%s\.?\s*%s\b" % (re.escape(h["title"].rstrip(".")), re.escape(h["entity"])), text):
                    return False, "missing_title"
        for h in scn["holders"]:
            if h["id"] in may:
                continue
            for tok in h["tokens"]:
                named = _has(lang, text, tok) if lang == "en" or not re.match(r"[가-힣]", tok) else \
                    re.search(r"(?<![가-힣])" + re.escape(tok), text) is not None
                if named and not any(tok in o for hid in may for o in holders[hid]["tokens"]):
                    return False, "other_holder:%s" % tok
        reason = self._unnamed(scn, turn, lang, text, may)
        if reason:
            return False, reason
        # things
        thing = things_here[0] if things_here else None
        optional = turn["act"] in ("why", "repair", "switch") or bool(turn.get("ask_in")) or \
            set(forms) & {"partitive", "omit_subject", "title_ege_omit", "q_bundles"}
        if thing is not None and not optional and not _thing_named(lang, text, thing):
            return False, "missing_thing"
        if "switch_thing" in forms and not _thing_named(lang, text, thing):
            return False, "missing_thing"
        if "title_ege_omit" in forms and _thing_named(lang, text, thing):
            return False, "thing_not_omitted"
        for t in scn["things"]:
            if t is not thing and _thing_named(lang, text, t):
                return False, "other_thing"
        # the form
        cues = FORM_CUES[lang]
        for form in forms:
            if cues.get(form) and not re.search(cues[form], text, re.I if lang == "en" else 0):
                return False, "form:" + form
        reason = self._shape(scn, turn, lang, text, sentences, found, holders)
        if reason:
            return False, reason
        if turn["act"] in ("ask", "ask_total", "ask_more") and not re.search(QUESTION_WORDS[lang], text, re.I):
            return False, "no_question_word"
        if turn["act"] == "why" and not re.search(WHY_WORDS[lang], text, re.I):
            return False, "no_why_word"
        # the verb and the direction of a transfer
        if turn["act"] in ("give", "use"):
            verb = turn.get("verb", "use")
            table = EN_VERB_CUES if lang == "en" else KO_VERB_CUES
            if not re.search(table[verb], text, re.I if lang == "en" else 0):
                return False, "verb:" + verb
        if turn["act"] == "give":
            g, r = holders[turn["giver"]], holders[turn["receiver"]]

            def token(h):
                return h["tokens"][0] if h["tokens"] else ("I" if lang == "en" else "나")
            d = {"giver": token(g), "taker": token(r), "giver_kind": g["kind"], "taker_kind": r["kind"],
                 "side": "give", "verb": "leave_at" if turn["verb"] in ("leave_at", "entrust") else "give"}
            reason = v4.Checker._direction(lang, d, text)
            if reason:
                return False, reason
        if lang == "ko" and not turn.get("ask_in") and not set(forms) & {"switch_holder", "switch_place",
                                                                          "switch_thing", "repair_bare"}:
            reason = self._register(scn["register"], sentences[-1])
            if reason:
                return False, reason
        return True, "ok"

    @staticmethod
    def _named(turn):
        """The holder ids a turn must name."""
        act, forms = turn["act"], turn["forms"]
        if act == "give":
            return [turn["receiver"]] if "omit_subject" in forms else [turn["giver"], turn["receiver"]]
        if act in ("ask_total", "ask_more"):
            return [] if "q_two_total" in forms else list(turn["holders"])
        if act == "switch":
            return [] if "switch_thing" in forms else [turn["holder"]]
        if act == "why" and set(forms) & {"why_that_number", "why_how"}:
            return []
        return [turn["holder"]]

    def _unnamed(self, scn, turn, lang, text, may):
        """A holder the scenario does not name: a name, thing or place of any table the scenario lacks, a person
        word it lacks, a capitalized word used as a name (en), a word with 씨 or 님 that is none of its holders
        (ko)."""
        own = {tok for h in scn["holders"] for tok in h["tokens"]}
        own_words = {w.lower() for tok in own for w in tok.split()}
        own_things = {w for t in scn["things"] for w in (t.get("plural"), t.get("one"), t.get("noun")) if w}
        # a question in the other language may name the thing in that language: names only there
        for kind in ("names",) if turn.get("ask_in") else ("names", "things", "places"):
            for word in self.pools[lang][kind]:
                if word in own or word in own_things:
                    continue
                # a Korean name starts a word (병훈은 서류 holds no 은서)
                if kind == "names" and lang == "ko":
                    hit = re.search(r"(?<![가-힣])" + re.escape(word), text) is not None
                else:
                    hit = _has(lang, text, word)
                if hit and not any(_has(lang, o, word) for o in own | own_things):
                    return "unnamed_%s:%s" % (kind[:-1], word)
        person_words = {w for h in scn["holders"] for w in (h.get("relation"), h.get("role"), h.get("title")) if w}
        person_words |= {w.split()[-1] for w in person_words}
        for word in (EN_PERSON_WORDS if lang == "en" else KO_PERSON_WORDS):
            if word not in person_words and _has(lang, text, word):
                return "unnamed_person:%s" % word
        if lang == "en":
            allowed = own_words | {"i", "mr", "ms", "mrs", "dr"}
            for m in re.finditer(r"(?<![A-Za-z'])([A-Z][a-z]+)", text):
                word = m.group(1)
                if word.lower() in allowed or word.lower() in EN_STARTERS:
                    continue
                start = m.start() == 0 or re.search(r"[.!?,]\s*$", text[:m.start()]) is not None
                if not start:
                    return "unnamed_capitalized:%s" % word
                if re.match(r"(?:\s+(?:%s)\b|'s\b)" % EN_SUBJECT_VERBS, text[m.end():]):
                    return "unnamed_subject:%s" % word
        else:
            titles = set(KO_JOB_TITLES)
            for m in re.finditer(r"(?<![가-힣])([가-힣]{2,4})\s?(?:씨|님)", text):
                word = m.group(1)
                if any(word.endswith(tok.split()[-1]) or tok.endswith(word) for tok in own):
                    continue
                if word in titles and any(h.get("title") == word for h in scn["holders"]):
                    continue
                if any(word.endswith(tok) for tok in own):
                    continue
                return "unnamed_titled:%s" % word
        return None

    @staticmethod
    def _shape(scn, turn, lang, text, sentences, found, holders):
        forms = turn["forms"]
        if "fragment" in forms:
            if len(sentences) != 2:
                return "fragment_shape"
            cut = text.find(sentences[1])
            if any(s < cut for _v, s, _e in found) or not any(s >= cut for _v, s, _e in found):
                return "fragment_count_place"
            if len(sentences[1].split()) > 5:
                return "fragment_too_long"
        if set(forms) & {"switch_holder", "switch_place", "switch_thing"}:
            if len(text.split()) > (8 if lang == "en" else 5):
                return "switch_too_long"
            if re.search(r"\bhow many\b|몇", text, re.I):
                return "switch_not_elliptic"
        if "repair_bare" in forms and len(text.split()) > (7 if lang == "en" else 4):
            return "repair_too_long"
        if "repair_question" in forms:
            if len(sentences) != 2 or not sentences[-1].endswith("?"):
                return "repair_shape"
        if "title_ege_omit" in forms:
            tok = holders[turn["holder"]]["tokens"][0]
            if not re.search(re.escape(tok) + r"\s?님?\s?(?:에게는|한테는|께는)", text):
                return "form:title_ege_omit"
        if "job_apposition" in forms:
            h = holders[turn["holder"]]
            role = h["role"].replace("the ", "").replace("our ", "")
            a, b = _at(lang, text, role), _at(lang, text, h["tokens"][0])
            if a is None or b is None or not a < b or (lang == "ko" and b - a > len(role) + 2):
                return "form:job_apposition"
        if "relation_also_vague" in forms:
            h = holders[turn["holder"]]
            anchor = holders[h["anchor"]]["tokens"][0]
            a, r, b = _at(lang, text, anchor), _at(lang, text, h["relation"]), _at(lang, text, h["tokens"][0])
            if None in (a, r, b) or not a < r < b:
                return "form:relation_also_vague"
        if "double_object" in forms:
            receiver = holders[turn["receiver"]]
            tok = receiver["tokens"][0] if receiver["tokens"] else "me"
            verb = re.search(r"\b(?:gave|sent|passed|lent|handed|loaned)\b", text, re.I)
            at = _at("en", text, tok)
            first_number = min([s for _v, s, _e in found] or [None], key=lambda s: s if s is not None else 10 ** 6)
            if verb is None or at is None or first_number is None or not verb.start() < at < first_number:
                return "form:double_object"
            if re.search(r"\bto\s+(?:\w+\s+){0,2}%s\b" % re.escape(tok), text, re.I):
                return "form:double_object"
        if "particle_verb" in forms:
            receiver = holders[turn["receiver"]]
            tok = receiver["tokens"][0] if receiver["tokens"] else "me"
            if not re.search(r"\b(?:handed|gave|passed|sent)\s+(?!over\b|back\b|on\b)\S.{0,50}?\b(?:over|back|on)\s+to\s+"
                             r"(?:\w+\.?\s+){0,2}?%s\b" % re.escape(tok), text, re.I):
                return "form:particle_verb"
        if "place_receiver" in forms:
            place = holders[turn["receiver"]]["tokens"][0]
            if lang == "en" and not re.search(r"\b(?:at|in|with)\s+(?:the\s+)?%s\b" % re.escape(place), text, re.I):
                return "form:place_receiver"
        if "omit_subject" in forms and lang == "ko":
            if re.search(r"(?:제가|저는|내가|나는)", text):
                return "form:omit_subject"
        if set(forms) & {"why_that_number", "why_how"}:
            for h in scn["holders"]:
                if any(_has(lang, text, tok) for tok in h["tokens"]):
                    return "why_names_a_holder"
        return None

    @staticmethod
    def _register(register, last):
        last = last.rstrip(".!?~ ")
        if register == "haeyo" and not re.search(r"요$", last):
            return "register"
        if register == "hapsyo" and not re.search(r"(니다|니까|시오|세요)$", last):
            return "register"
        if register == "banmal" and re.search(r"(요|니다|니까)$", last):
            return "register"
        if register == "haera" and (re.search(r"(요|니다|니까)$", last) or not re.search(r"(다|가|나|냐|니|지|까|인가)$", last)):
            return "register"
        return None


# ---------------------------------------------------------------------------
# assembly of phrasings written outside
# ---------------------------------------------------------------------------
def read_records(paths):
    """[(line, record or None)]: every line of the phrasing files (a line that is not a JSON object is None)."""
    out = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                record = None
            out.append((line, record if isinstance(record, dict) else None))
    return out


def _record_problem(record, scenarios):
    if record is None:
        return "not_a_record"
    for key in ("scenario", "language", "turns", "source", "date"):
        if key not in record:
            return "missing_field:%s" % key
    if record["scenario"] not in scenarios:
        return "unknown_scenario"
    if record["language"] != scenarios[record["scenario"]]["language"]:
        return "wrong_language"
    if not isinstance(record["turns"], list) or not all(isinstance(t, dict) and "n" in t and "text" in t
                                                        for t in record["turns"]):
        return "turns_shape"
    return None


def keep_turns(scn, texts, dropped):
    """The scenario turns kept: every turn with a text that passed; a statement that failed ends the dialogue
    there; a turn that continues a dropped question (``after``) goes with it."""
    kept, gone = [], set()
    for t in scn["turns"]:
        if t["n"] not in texts or t["n"] in dropped:
            if t["act"] in ("has", "give", "use"):
                break
            gone.add(t["n"])
            continue
        if t.get("after") in gone:
            gone.add(t["n"])
            continue
        kept.append(t)
    return kept


def overlapping_turns(dialogues, words=None):
    """{(dialogue id, turn n)}: turns holding a full sentence of dev to dev5, or with a sentence found in a
    tracked corpus file outside this folder (the frozen sets excluded, never read). ``words`` {dialogue id:
    its scenario's names, things and places}: a sentence with none of them (a bare fragment such as a count
    alone) is generic, and only the earlier sets' sentences count against it."""
    found = gate.overlaps(dialogues, files=v4.corpus_files(("data/benchmarks/dialogues_dev6/",)))
    out = set()
    for item in found["overlaps"]:
        own = (words or {}).get(item["dialogue"])
        if own is None or any(w.lower() in item["sentence"].lower() for w in own):
            out.add((item["dialogue"], item["turn"]))
    others = set()
    for name in OTHER_SETS:
        folder = ROOT / "data/benchmarks" / name
        if folder.exists():
            others |= {norm for _d, _n, _raw, norm in gate.dialogue_sentences(gate.load(folder))}
    for d in dialogues:
        for t in d["turns"]:
            text = gate._normalize_corpus(t["say"])
            if any(norm in text and gate._full_sentence_at(text, norm) for norm in others):
                out.add((d["id"], t["n"]))
    return out


def assemble(paths, folder=HERE, out_dir=None, write=True, overlap=overlapping_turns):
    """Dialogues from phrasing records written outside. Returns the dialogues, the split and the counts of what
    was dropped: records (by reason), turns (by checker reason), dialogues."""
    scenarios = load_scenarios(folder)
    checker = Checker6()
    stats = {"records": 0, "records_dropped": {}, "turns_checked": 0, "turns_dropped": {}, "dialogues_dropped": {},
             "sources": {}}

    def drop(table, reason):
        stats[table][reason] = stats[table].get(reason, 0) + 1

    candidates, seen = {}, set()
    for _line, record in read_records(paths):
        stats["records"] += 1
        problem = _record_problem(record, scenarios)
        if problem is None and record["scenario"] in seen:
            problem = "duplicate_scenario"
        if problem:
            drop("records_dropped", problem)
            continue
        seen.add(record["scenario"])
        scn = scenarios[record["scenario"]]
        written = {t["n"]: t["text"] for t in record["turns"]}
        texts, failed = {}, set()
        for t in scn["turns"]:
            if t["n"] not in written:
                continue
            stats["turns_checked"] += 1
            ok, reason = checker.check(scn, t, written[t["n"]])
            if ok:
                texts[t["n"]] = written[t["n"]].strip()
            else:
                failed.add(t["n"])
                drop("turns_dropped", reason.split(":")[0])
        candidates[scn["id"]] = (scn, texts, failed, record)
    # sentences shared with the corpus or an earlier set: those turns are dropped too
    first = []
    for sid, (scn, texts, failed, record) in candidates.items():
        kept = keep_turns(scn, texts, failed)
        first.append(dialogue_json(scn, gate_turns(scn, kept, texts)))
    words = {sid: {tok for h in scn["holders"] for tok in h["tokens"]}
             | {w for t in scn["things"] for w in (t.get("plural"), t.get("one"), t.get("noun")) if w}
             for sid, (scn, _t, _f, _r) in candidates.items()}
    shared = overlap(first, words) if first else set()
    by_id = {d["id"]: d for d in first}
    dialogues, split, counts = [], {"build": [], "check": []}, {}
    for sid, (scn, texts, failed, record) in candidates.items():
        numbered = {t["n"]: t["scenario_turn"] for t in by_id[sid]["turns"]}
        over = {numbered[n] for d, n in shared if d == sid}
        for _n in over:
            drop("turns_dropped", "overlap")
        kept = keep_turns(scn, texts, failed | over)
        turns = gate_turns(scn, kept, texts)
        if not 4 <= len(turns) <= 10 or sum(t["label"] == "answerable" for t in turns) < 2:
            drop("dialogues_dropped", "too_few_turns_left")
            continue
        key = (scn["half"], scn["language"])
        counts[key] = counts.get(key, 0) + 1
        new_id = "dev6_%s_%s_%02d" % (scn["language"], scn["half"][0], counts[key])
        d = dialogue_json(scn, turns, new_id, {"source": record["source"], "date": record["date"],
                                               "session": record.get("session")})
        problems = [x for x in gate.validate([d]) if x.startswith(new_id)]
        if problems:
            counts[key] -= 1
            drop("dialogues_dropped", "does_not_replay")
            continue
        dialogues.append(d)
        split[scn["half"]].append(new_id)
        src = "%s %s %s" % (record["source"], record["date"], record.get("session") or "")
        stats["sources"].setdefault(scn["half"], {}).setdefault(src.strip(), 0)
        stats["sources"][scn["half"]][src.strip()] += 1
    stats["dialogues"] = {"%s_%s" % k: v for k, v in sorted(counts.items())}
    stats["turns"] = sum(len(d["turns"]) for d in dialogues)
    stats["same_session_in_both_halves"] = sorted(set(stats["sources"].get("build", {}))
                                                  & set(stats["sources"].get("check", {})))
    if write:
        out_dir = Path(out_dir or folder)
        out_dir.mkdir(parents=True, exist_ok=True)
        for path in out_dir.glob("dev6_*.json"):
            path.unlink()
        for d in dialogues:
            (out_dir / (d["id"] + ".json")).write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n",
                                                       encoding="utf-8")
        lines = ["seed %d scenario_build %d scenario_check %d" % (SEED, SCENARIO_SEEDS["build"],
                                                                   SCENARIO_SEEDS["check"]),
                 "build " + " ".join(split["build"]), "check " + " ".join(split["check"])]
        (out_dir / "split.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (out_dir / "assemble_stats.jsonl").write_text(json.dumps(stats, ensure_ascii=False) + "\n",
                                                      encoding="utf-8")
    return dialogues, split, stats


# ---------------------------------------------------------------------------
# coverage and the instruction file
# ---------------------------------------------------------------------------
def coverage(scenarios):
    """{class: {lang_half: dialogues}} and turn counts, over scenario records."""
    table = {c: {} for c in CLASSES}
    turns = {}
    statements = {}
    for scn in scenarios:
        key = "%s_%s" % (scn["language"], scn["half"])
        turns[key] = turns.get(key, 0) + len(scn["turns"])
        for c in scn["classes"]:
            table[c][key] = table[c].get(key, 0) + 1
        for t in scn["turns"]:
            if t["act"] in ("has", "give", "use") and t.get("count") is not None:
                row = statements.setdefault(scn["language"], [0, 0])
                row[0] += 1
                row[1] += t.get("count_as") == "word"
    return table, turns, statements


CLASS_TEXT = {
    "1_count_words": "Counts as words, not digits. English number words in transfer and ownership statements "
                     "(\"one\" to \"twenty-four\", \"some ... six, to be exact\"); Korean native numerals with "
                     "counters (한·두·세·네·여섯·스무 + 개·권·장·묶음·자루) in transfer statements.",
    "2_en_transfer_forms": "English double-object transfer (\"gave RECIPIENT N THINGS\", no \"to\") and split "
                           "particle verbs (\"handed N THINGS over to R\"), plus \"transferred\", \"returned\", "
                           "\"sent\", \"passed\", \"left N at PLACE\".",
    "3_partitive": "Partitive pronoun objects in transfers and use-ups: \"one of them\", \"N of them\", 그중 하나, "
                   "그중 N개, \"used three of them for ...\", 그중 N개로 만들었다.",
    "4_fragment_count": "A count given in a following fragment: \"X has some Y. N, to be exact.\" / "
                        "\"X한테 Y이 있어. 여섯 개야.\" / \"X가 Y한테 Z를 줬어. 두 개.\"",
    "5_ko_transfer_verbs": "Korean transfer verbs and compounds: 나눠 주다, 빌려주다, 보내다, 맡기다 (leave at a "
                           "place), 싣고 있다 (carry), 주었다 (plain past formal), and the subject omitted in a "
                           "second sentence (\"그리고 R에게 N개를 주었다\").",
    "6_holder_forms": "Holder forms: a title after a name with 에게는 and the thing omitted (\"X 과장에게는 두 "
                      "개가 있습니다\"); a job-title apposition before a name (\"택배 기사 X 씨는\"); a relational noun "
                      "with 도 and a vague count (\"X 친구 Y도 Y을 가지고 있어요\"); \"For the event, X is "
                      "responsible for N\" (fronting + responsible-for + number word); a place as recipient "
                      "(\"left N at the shop\" / \"편의점에 맡겼습니다\").",
    "7_leftover_questions": "Leftover and remaining forms: \"does X have left\", \"are left with X\", \"left for "
                            "X\", \"remain with X\", \"X에게 남은 Y은 몇 개인가\", \"Y 몇 개 남았어\", \"X 님께 남은 Y은 "
                            "몇 권입니까\".",
    "8_time_adverb_questions": "Aspect and time adverbs in questions: \"at the moment\", \"now\", 이제, 지금 "
                               "(\"X는 이제 몇 개야?\", \"그럼 X는 지금 몇 개예요?\").",
    "9_other_predicates": "Other question predicates: \"has X got\", \"is X responsible for\", \"맡고 있습니까\", "
                          "\"How many bundles\" / \"몇 묶음입니까\", \"모두 몇 개입니까\", \"combined\" / \"the two of "
                          "them in total\", \"둘 중에 누가 더 (many/few)\" asked of two named holders.",
    "10_topic_switch": "Topic-switch ellipsis: \"What about X?\", \"And X?\", \"And in PLACE?\", \"And THING?\", "
                       "\"X는요?\", \"X는?\", \"THING은?\", \"PLACE는 어떻습니까?\" (the question of the previous turn "
                       "asked again about a new holder, place or thing).",
    "11_repair_with_question": "Referent repair with the question in the same turn: \"I mean X. How many does X "
                               "hold?\", \"It's X. How many does X have?\", \"X 말입니다. 몇 묶음입니까?\", \"X요. X는 "
                               "몇 개예요?\"; and bare-name repairs as a turn (\"X요.\", \"X 님입니다.\", \"X, I "
                               "mean.\", \"X is the one I mean.\") followed by the question next turn.",
    "12_cross_language": "Cross-language turns: a question in the other language inside a dialogue.",
    "13_why_with_fact": "Why questions that restate the fact: \"Why does X have N?\", \"Why does X end up with "
                        "N?\", \"What is the reason X has N?\", \"Why is that number N?\", a why about how the last "
                        "answer came about, with no holder or number, \"Why do I only have N?\", \"왜 X가 N개야?\", "
                        "\"왜 N개예요?\", \"X의 Y이 N개가 된 까닭은 무엇인가?\", the same in Korean, \"X Y가 왜 N개가 "
                        "되었습니까?\".",
    "15_unstated_receiver": "A transfer to a holder whose starting count is never stated: the giver's count can "
                            "be answered, the receiver's cannot (it is asked, and the true answer is that it is "
                            "not known).",
}


def phrasing_md():
    """The one instruction file an outside writer follows (no sentence of any data set in it; tested)."""
    lines = [
        "# Writing the dialogues of development set v6",
        "",
        "You receive scenario files (`scenarios_build_<language>.jsonl`, `scenarios_check_<language>.jsonl`, "
        "language `en` or `ko`) and this file. Nothing else is needed.",
        "Each line of a scenario file is one short dialogue that a person types to an assistant, one message "
        "per turn. Only the person's messages are written; the assistant's replies are not.",
        "Your task is to write every turn of every scenario as one natural message.",
        "",
        "## The rules",
        "",
        "1. Every message is natural everyday language, the way a person would type it to an assistant in that "
        "language.",
        "2. A message says exactly what its scenario turn says, and nothing more: no other person, thing, place "
        "or number, no greeting, no comment, no story around it.",
        "3. Never copy the wording of a scenario record or of the examples in this file. The examples show a "
        "shape with placeholders in parentheses; write your own sentence in that shape.",
        "4. Use the names exactly as the turn's `refer` gives them (a person may be called by the given name, a "
        "title and surname, a relation, a job word; keep every word of it the first time, `first` lists who is "
        "mentioned for the first time). Name every holder the turn refers to, even when the turn before named "
        "them too: no he, she or they in place of a name. Do not add any name, relation or job word the turn "
        "does not have. A turn whose `refer` is empty names no holder at all.",
        "5. A count is written as the turn's `count_as` says: `word` means in words (English number words; "
        "Korean native numerals with a counter, e.g. 세 개, 스물네 권), `digits` means in digits (e.g. 7, 12개). "
        "Write English compound numbers with a hyphen (twenty-four). Never write any number the turn does not "
        "have, and never an amount word such as a dozen, a couple, a few, several, a pair, half.",
        "6. Korean messages follow the scenario's `register`: `haeyo` (every message ends in -요), `hapsyo` "
        "(-ㅂ니다, -ㅂ니까), `banmal` (plain speech, no -요), `haera` (written plain style: -다, -는가, -나?). "
        "English messages follow `casual`, `neutral` or `formal`.",
        "7. A question ends with a question mark and is one sentence, except where a form below asks for two. "
        "A statement never ends with a question mark.",
        "8. No quotation marks, parentheses, brackets, line breaks or three dots inside a message. No Latin "
        "letters in a Korean message and no Hangul in an English message, except inside a name the turn gives.",
        "9. A turn with `ask_in` is written in that other language (a question in English inside a Korean "
        "dialogue, or in Korean inside an English one). Keep the holder's name as written.",
        "10. Write the build files and the check files in two separate sessions, and give each session its own "
        "`session` value.",
        "",
        "## What a scenario record means",
        "",
        "- `id`: the scenario id; copy it into your output. `language`: `en` or `ko`. `register`: see rule 6.",
        "- `holders`: the people and places of the dialogue. `kind` is `name`, `title` (a title and surname, "
        "or in Korean a surname and job title), `relation` (introduced by a relation, sometimes to another "
        "holder, `anchor`), `apposition` (introduced with a job word), `first_person` (the person typing: I, "
        "me, my; 저, 나, 제가) or `place`. `tokens` are the words that name them.",
        "- `things`: the things counted. English: `plural` and `one`; Korean: `noun` and `counter` (the counter "
        "word used with a native numeral). A thing with `unit` is counted in bundles.",
        "- `turns`: the messages in order. Each has `n` (its number), `act`, the facts of the act, `refer` (how "
        "to call each holder in this message), `first`, `forms` (the shape the message must take, listed "
        "below) and `classes` (for information).",
        "",
        "The acts:",
        "",
        "- `has`: the holder has `count` of the `thing`. A `count` of null means the amount is not said at all "
        "(say they have some, with no number).",
        "- `give`: the `giver` gives `count` of the `thing` to the `receiver` with the verb `verb` (see the "
        "verbs below). When the receiver is a place, the giver left or entrusted the things there.",
        "- `use`: the holder used up `count` of the `thing` for the `purpose`.",
        "- `ask`: ask how many of the `thing` the holder has now.",
        "- `ask_total`: ask how many of the `thing` the two `holders` have together.",
        "- `ask_more`: ask which of the two `holders` has more of the `thing`.",
        "- `switch`: the question of the turn before, asked again about a new holder, place or thing, by an "
        "ellipsis only (only what changed is said).",
        "- `repair`: the person meant the holder `holder`, not `asked`, the one the turn before asked about.",
        "- `why`: ask why the holder has `count` of the `thing` now (the forms say whether the holder and the "
        "number are said).",
        "",
        "Other fields: `occasion` (the event a holder is responsible for), `vehicle` (what the things are loaded "
        "on), `purpose` (what used things went into), `after` and `hold` (for the checker; ignore them).",
        "",
        "The verbs of `give`:",
        "",
    ]
    for lang in LANGS:
        lines.append("- %s: %s" % (lang, "; ".join("`%s` %s" % kv for kv in VERBS[lang].items())))
    lines += ["", "## The forms", "",
              "A turn's `forms` say the shape of its message. The description is for the turn's language.", ""]
    for code, (_cls, text) in FORMS.items():
        for lang in LANGS:
            if lang in text:
                lines.append("- `%s` (%s): %s" % (code, lang, text[lang]))
    lines += ["", "## The classes", "",
              "Each turn is tagged with the classes it belongs to. These are the classes, as the goal of this set "
              "describes them; X, Y, N, R, THING and PLACE stand for the scenario's holders, things, numbers and "
              "places.", ""]
    for c in CLASSES:
        lines.append("- **%s**: %s" % (c, CLASS_TEXT[c]))
    lines += [
        "", "## The output", "",
        "One JSON object per line (JSON Lines, UTF-8), one line per scenario, in a file per session:", "",
        "```",
        "{\"scenario\": \"<id>\", \"language\": \"<en|ko>\", \"turns\": [{\"n\": 1, \"text\": \"<message>\"}, "
        "{\"n\": 2, \"text\": \"<message>\"}], \"source\": \"<the writer's name>\", \"date\": \"<YYYY-MM-DD>\", "
        "\"session\": \"<a name for this session>\"}",
        "```", "",
        "Write every turn of the scenario, in order, with its `n`. `source` names who wrote the messages; `date` "
        "is the day they were written.",
        "Messages are checked by a program against the scenario: a message that misses a number, a holder, the "
        "thing or the form, or adds anything, is dropped, and so is every later turn when the dropped message "
        "was a statement.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["scenarios", "coverage", "assemble"])
    parser.add_argument("--phrasings-from", nargs="+", type=Path, help="phrasing records written outside (jsonl)")
    parser.add_argument("--out", type=Path, help="where the dialogues go (default: this folder)")
    args = parser.parse_args(argv)
    if args.command == "scenarios":
        vocab = halves()
        for half in HALVES:
            for lang in LANGS:
                out = generate(half, lang, vocab)
                scenarios_path(half, lang).write_text(
                    "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in out), encoding="utf-8")
                print(half, lang, len(out), "scenarios")
        PHRASING.write_text(phrasing_md(), encoding="utf-8")
        return 0
    if args.command == "coverage":
        table, turns, statements = coverage(load_scenarios().values())
        keys = ["%s_%s" % (lang, half) for lang in LANGS for half in HALVES]
        print("%-26s %s" % ("class", " ".join("%9s" % k for k in keys)))
        for c, row in table.items():
            print("%-26s %s" % (c, " ".join("%9d" % row.get(k, 0) for k in keys)))
        print("%-26s %s" % ("turns", " ".join("%9d" % turns.get(k, 0) for k in keys)))
        for lang, (n, words) in sorted(statements.items()):
            print("%s statements with a count: %d, as words: %d (%.0f%%)" % (lang, n, words, 100.0 * words / n))
        return 0
    if not args.phrasings_from:
        parser.error("assemble needs --phrasings-from")
    dialogues, split, stats = assemble(args.phrasings_from, out_dir=args.out)
    print("dialogues %d (build %d, check %d), turns %d" % (len(dialogues), len(split["build"]),
                                                           len(split["check"]), stats["turns"]))
    print("records %d, dropped %s" % (stats["records"], json.dumps(stats["records_dropped"])))
    print("turns checked %d, dropped %s" % (stats["turns_checked"], json.dumps(stats["turns_dropped"])))
    print("dialogues dropped %s" % json.dumps(stats["dialogues_dropped"]))
    if stats["same_session_in_both_halves"]:
        print("warning: one session wrote both halves: %s" % stats["same_session_in_both_halves"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
