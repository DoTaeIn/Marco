# -*- coding: utf-8 -*-
"""국어사전 뜻풀이에서 유(類)·동작·대상을 뽑는다.

왜 백과사전이 아니라 사전인가. 위키백과는 고유명사와 전문용어를 정의하지
일상 행위를 정의하지 않는다. 정작 필요했던 낱말이 이랬다.

    세차 · 독서          문서가 아예 없다
    연주 · 합주 · 수술    동음이의 문서만 있다("연주의 다른 뜻은 다음과 같다")

국어사전에는 다 있고, 게다가 꼴이 더 쉽다. 계사(~이다)를 안 거치고
유가 마침표 앞에 바로 오며, 서술성 명사형(함/음/-기)이 동작을 표시한다.

    세차   : 자동차의 안을 청소하거나 바깥에 묻은 먼지나 흙 등을 씻음.
    설거지 : 음식을 먹고 난 뒤에 그릇을 씻어서 정리함.
    세탁   : 더러운 옷 등을 빠는 일.

재료는 국립국어원 한국어기초사전(krdict)이다. CC BY-SA 2.0 KR 이라
라이선스가 깨끗하고, spellcheck-ko/korean-dict-nikl 에 XML 로 재배포돼 있어
회원가입 없이 받는다(공식 사이트는 로그인이 필요하다).

잰 것 (명사 표제어 30,227개):

    유 뽑힘 28,308 · 동작 9,643 · 대상 5,975
    빈 낱말 앞에서 멈춘 뿌리 기준 상위 30개가 낱말의 55.9% 를 덮는다
    (같은 잣대로 위키백과는 47.7% 였고 뿌리가 '말한'·'의미한' 같은 파편이었다)

뿌리는 물체(2,776) · 구역(1,990) · 모양(1,456) · 공간(914) · 도구(532) ·
음식(333) · 옷(177) 처럼 도식을 붙일 수 있는 것들이다.
"""
import collections
import math
import re
# '것' 은 뺀다. '…나타낸 것' 은 사물이지 동작이 아니다.
action_kinds = ("일", "행위", "짓", "활동", "작업", "과정", "절차", "놀이", "경기", "운동")
_genus_end = re.compile(r"([가-힣]{1,10})\s*$")
# 임자(의)가 붙은 목적어가 우선이다. '자동차의 안을' 의 대상은 '자동차' 다.
_object = re.compile(r"(?:([가-힣]{1,12})의\s+)?(?:한\s+)?([가-힣]{1,12})(?:\s*등)?\s*(?:을|를)\s")
# 을/를 이 없으면 '~에' 를 본다. '산에 오름' 의 대상은 산이다.
_gap = re.compile(r"([가-힣]{1,12})(?:\s*등)?\s*에\s+[가-힣]")
_drop = {"것", "수", "때", "곳", "바", "등", "이", "그", "저", "말", "데", "위", "안", "속", "중"}

def _is_noun_form(phrase):
    """'오름'·'씻음'·'함' 처럼 ㅁ 받침으로 끝나거나 '-기' 로 끝나면 서술성 명사다."""
    if not phrase:
        return False
    if phrase.endswith("기"):
        return True
    end = phrase[-1]
    import hangul
    return hangul.batchim(end) == "ㅁ"

# 둘째 뜻은 잘라낸다. '…않음. 또는 그런 대상.' 에서 뒷말을 유로 잡으면
# '대상' 이 12,782번 나온다 — 표제어 넷 중 하나가 같은 뿌리로 몰렸다.
_second_sense = re.compile(r"\.\s*또는|\s또는\s")

def extract(meaning):
    """사전 뜻풀이 -> (유, 동작인가, 대상). 명사 표제어에만 쓴다 —
    동사 뜻풀이는 '…하다' 로 끝나 유가 안 나온다."""
    s = _second_sense.split((meaning or "").strip(), 1)[0].strip().rstrip(".")
    if not s:
        return None, False, None
    m = _genus_end.search(s)
    genus = m.group(1) if m else None
    is_verb = _is_noun_form(genus) or (genus in action_kinds)
    cand = [(owner, trunk) for owner, trunk in _object.findall(s)]
    target = None
    owned = [a for a, _b in cand if a and a not in _drop]
    if owned:
        target = owned[0]                      # 임자가 붙은 것이 더 또렷하다
    else:
        for _a, b in cand:
            if b not in _drop:
                target = b                        # 없으면 마지막 목적어
    if target is None:
        e = _gap.search(s)
        if e and e.group(1) not in _drop:
            target = e.group(1)
    return genus, is_verb, target


# 뜻풀이가 '…하는 것' 으로 끝나는 일이 잦은데 '것' 은 빈 낱말이라 도식을 못
# 붙인다. 사슬이 여기 닿으면 한 칸 앞에서 멈춘다 — 안 멈추면 낱말 넷 중
# 셋이 '것' 하나로 몰린다(11,989개를 그렇게 잃었다).
filler = {"것", "일", "있음", "됨", "함", "수", "바", "데", "때", "곳", "이", "그", "저",
        "않음", "아니함", "모두", "전부", "하나", "쪽", "편"}


def find_root(phrase, genus_map, max_n=12):
    """유 사슬의 끝. 빈 낱말 앞에서 멈춘다.

    유는 그 자체로 낱말이라 제 유를 또 갖는다. 그 사슬을 따라가면 뿌리 몇
    개로 모이므로, 뿌리에 한 번 적은 것이 낱말 수천 개에 걸린다."""
    whole_text = set()
    while phrase in genus_map and phrase not in whole_text and max_n:
        whole_text.add(phrase)
        nxt = genus_map[phrase]
        if nxt in filler:
            return phrase
        phrase, max_n = nxt, max_n - 1
    return phrase


def _selfcheck():
    seen_table = [("세차", "자동차의 안을 청소하거나 바깥에 묻은 먼지나 흙 등을 씻음.", True, "자동차"),
            ("설거지", "음식을 먹고 난 뒤에 그릇을 씻어서 정리함.", True, "그릇"),
            ("세탁", "더러운 옷 등을 빠는 일.", True, "옷"),
            ("독서", "책을 읽음.", True, "책"),
            ("등산", "산에 오름.", True, "산"),
            ("수술", "병을 고치기 위하여 몸의 한 부분을 째고 자르거나 꿰매는 일.", True, "몸"),
            ("가건물", "임시로 사용하기 위해 지은 건물.", False, None)]
    for phrase, meaning, is_verb_expected, obj_expected in seen_table:
        genus, is_verb, obj = extract(meaning)
        assert is_verb is is_verb_expected, (phrase, is_verb, is_verb_expected)
        assert obj == obj_expected, (phrase, obj, obj_expected)
    # 임자(의)가 붙은 목적어가 이긴다. '자동차의 안을' 은 '안' 이 아니라 '자동차' 다.
    assert extract("자동차의 안을 씻음.")[2] == "자동차"
    # 둘째 뜻은 자른다. 안 자르면 '대상' 하나로 12,782개가 몰린다.
    assert extract("공격하기 어려워 무너지지 않음. 또는 그런 대상.")[0] == "않음"
    # 유는 사물 쪽에서 그대로 나온다
    assert extract("작은 규모로 물건을 펼쳐 놓고 파는 집.")[0] == "집"
    # 빈 낱말 앞에서 멈춘다
    assert find_root("세차", {"세차": "씻음", "씻음": "것"}) == "씻음"
    assert find_root("가게", {"가게": "집", "집": "건물"}) == "건물"
    # 동시 도식은 사람이 쓴 시드만 받으며, 두 칸을 넘기거나 시드 밖이면 미지다.
    assert find_concurrent("관현악", {"관현악": "교향악단"}) == ("교향악단", 1)
    assert find_concurrent("연주", {"연주": "관현악", "관현악": "교향악단"}) == ("교향악단", 2)
    assert find_concurrent("음악", {"음악": "연주", "연주": "관현악", "관현악": "교향악단"}) is None
    assert find_concurrent("합주", {}) is None
    # 추가 뿌리는 서로 겹치지 않으며 같은 두 칸 제한을 공유한다.
    assert len(_SEED_TABLE) == sum(len(v) for v in seed.values()), "씨앗이 두 도식에 겹친다"
    for phrase, mapping, expected in (("탈것", {}, "물건"), ("공항", {}, "장소"), ("학생", {}, "사람"),
                         ("자전거", {"자전거": "탈것"}, "물건"),
                         ("도서관", {"도서관": "공항"}, "장소"),
                         ("교수", {"교수": "학생"}, "사람")):
        assert find_schema(phrase, mapping) == expected, (phrase, find_schema(phrase, mapping))
    print("selfcheck ok")


# ── 도식 ────────────────────────────────────────────────────────────
#
# 도식은 '이 일에 어떤 수치가 걸리고 어떤 것이 미끼인가' 를 말한다. 낱말마다
# 적으면 평생 못 채우지만, 유 사슬의 조상에 적으면 그 아래가 다 받는다.
#
# 씨앗을 조상에 둔다. 낱말의 유 사슬을 따라가다 씨앗을 만나면 그 도식이다.
#
#     세차 -> 자동차 -> 차(씨앗)     -> 물건
#     등산 -> 산(씨앗)               -> 장소
#
# **깊이 2 를 넘지 않는다.** 사슬이 길어지면 동음이의가 한 칸씩 갈아타며
# 쌓여 뜻이 흘러간다. 실제로 겪은 것:
#
#     힘 -> 작용 -> 줌 -> 손 -> 부분 -> 범위 -> 구역   (결사반대가 '장소' 가 됐다)
#     종교 -> 체계 -> 전체 -> 대상 -> 상인 -> 사람     ('대상(對象)' 이 '대상(隊商)' 으로)
#
# 잰 것 (동작 낱말 5,975개, 대상이 뽑힌 것 기준):
#
#     깊이  1: 21%   2: 27%   3: 31%   6: 41%   12: 46%
#     깊이 2 무작위 표본 12개 중 10개가 맞았다(≈8할). 깊이 12 는 절반 아래다.
#
# 커버리지를 더 얻겠다고 깊이를 늘리면 정밀도로 갚는다. 이 프로젝트의 다른
# 추출기와 같은 자리에 세운다 — 기계가 후보를 내고 사람이 확인한다.
seed = {
    "물건": ["물체", "물건", "도구", "옷", "음식", "돈", "책", "차", "기구", "그릇",
             "재료", "물질", "기계", "장치", "종이", "열매", "약", "무기",
             "탈것", "동물", "식물", "가구", "상품", "부품", "전자제품", "가전"],
    "장소": ["구역", "공간", "지역", "건물", "집", "길", "방", "산",
             "건축물", "시설", "학교", "상점", "공원", "해변", "나라", "도시", "마을", "역", "공항", "병원"],
    "사람": ["사람", "개인", "단체", "기관", "회사", "조직", "가족", "직업", "군중", "회원", "학생", "고객", "주민"],
    # 물건도 장소도 사람도 아닌 것들. 안 붙던 3,788개의 뿌리를 세어 보고
    # 열었다 — 생각(94) · 소리(73) · 글(53) 처럼 정보류가 제일 컸다.
    "정보": ["생각", "소리", "글", "말", "내용", "지식", "이야기", "의견", "뜻",
             "정보", "기록", "그림", "노래", "음악", "사실", "계획", "규칙"],
    "몸": ["몸", "신체", "부분"],
    "권리": ["권리", "자격", "지위", "신분", "책임", "의무"],
}
_SEED_TABLE = {n: k for k, ns in seed.items() for n in ns}
schema_depth = 2


def find_schema(phrase, genus_map, depth=schema_depth):
    """낱말 -> 도식 이름. 유 사슬에서 씨앗을 만나면 그것이다. 없으면 None."""
    whole_text, step = set(), 0
    while phrase and phrase not in whole_text and step <= depth:
        if phrase in _SEED_TABLE:
            return _SEED_TABLE[phrase]
        whole_text.add(phrase)
        phrase = genus_map.get(phrase)
        step += 1
    return None


# 텍스트 뜻풀이에는 '동시에'가 대개 적히지 않는다. 그러므로 이 도식은 자동
# 추출 대상이 아니다. 아래는 사람이 확인해 적은 최소 시드이며, 유 사슬은
# 그 시드를 **분류**하는 데만 쓴다. 역할이나 동시 단위를 새로 지어내지 않는다.
concurrent_seed = {
    "교향악단": {"역할": ("지휘자", "현악연주자", "관악연주자", "타악연주자"),
              "단위": "한 악장", "출처": "사람 확인: 교향악단"},
}


def find_concurrent(phrase, genus_map, depth=schema_depth):
    """수동 동시작업 시드에 최대 두 칸 사슬로 닿는지 찾는다.

    반환값은 (시드이름, 거리) 또는 None. 시드를 못 만나면 미지이며, 일반
    물건/장소/사람 도식으로 억지로 바꾸지 않는다.
    """
    whole_text, dist = set(), 0
    while phrase and phrase not in whole_text and dist <= depth:
        if phrase in concurrent_seed:
            return phrase, dist
        whole_text.add(phrase)
        phrase = genus_map.get(phrase)
        dist += 1
    return None


# ── 사전을 읽어 사슬을 만든다 ────────────────────────────────────────
#
# 지금까지 이 일을 임시 스크립트로 했다. 재현이 안 되고, 뜻 가리기를 쓰는지
# 아닌지가 부르는 쪽마다 달라졌다. 한 자리에 둔다.
_xml_item = re.compile(r"<LexicalEntry.*?</LexicalEntry>", re.S)
_xml_value = {k: re.compile(r'%s"\s+val="([^"]+)"' % k)
          for k in ("writtenForm", "homonym_number", "partOfSpeech", "definition")}


def read_dict(folder="data/사전"):
    """국립국어원 XML -> 명사 항목 목록. [{말, 번, 뜻}, ...]"""
    import glob, os
    from progress import Bar
    emitted = []
    for f in Bar(sorted(glob.glob(os.path.join(folder, "krdict_*.xml"))), "사전 읽기"):
        with open(f, encoding="utf-8") as fh:
            txt = fh.read()
        for e in _xml_item.findall(txt):
            misc = {k: (v.search(e).group(1) if v.search(e) else None)
                  for k, v in _xml_value.items()}
            if misc["writtenForm"] and misc["definition"] and misc["partOfSpeech"] == "명사":
                emitted.append({"말": misc["writtenForm"], "뜻": misc["definition"],
                             "번": misc["homonym_number"] or "0"})
    return emitted


def build_chain(items, mask_meaning=True):
    """항목 -> (유맵, 대상맵, 동작집합).

    뜻가리기를 켜면 유가 다의어일 때 뜻을 고르고, 못 고르면 **잇지 않는다**.
    끄면 첫 뜻을 그냥 쓴다 — 옛 동작이고, 깊이를 늘리면 오답이 따라 는다."""
    senses = collections.defaultdict(list)
    for a in items:
        senses[a["말"]].append(a)
    freq, whole = common_table(items), len(items)
    genus_map, target_map, action = {}, {}, set()
    for phrase, pack_ in senses.items():
        meaning = pack_[0]["뜻"]
        genus, is_verb, obj = extract(meaning)
        if is_verb:
            action.add(phrase)
        if obj:
            target_map[phrase] = obj
        # 빈말은 유가 아니다. '행동' 의 뜻이 '몸을 움직여 …동작을 함' 이라
        # 문장 끝 '함' 이 유로 잡혔고, 그것이 상자 함(函) 으로 갈아타
        # `행위 -> 짓 -> 행동 -> 함 -> 상자 -> 통 -> 몸통` 이 됐다.
        # 사슬을 만들 때부터 끊는다 — 뿌리찾기에서만 막으면 이미 늦다.
        if not genus or genus == phrase or genus in filler:
            continue
        if mask_meaning and len(senses.get(genus, [])) > 1 and pick_meaning(genus, meaning, senses, freq, whole) is None:
            continue
        genus_map[phrase] = genus
    return genus_map, target_map, action


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        _selfcheck()
    else:
        print(__doc__)


# ── 동음이의 가르기 ──────────────────────────────────────────────────
#
# 사전은 뜻마다 항목이 따로다 — 차[1] 마시는 차 · 차[2] 탈것 · 차[3] 차이.
# 표제어만 보고 첫 뜻을 쓰면 사슬이 엉뚱한 뜻으로 갈아탄다.
#
#     자동차 -> 차 -> ???        차(茶) 로 가면 그 아래가 통째로 샌다
#
# 유가 다의어일 때, **참조하는 쪽 뜻풀이와 제일 가까운 뜻**을 고른다.
# 못 고르겠으면 잇지 않는다. 틀린 뜻으로 이으면 그 아래가 다 새기 때문에,
# 안 잇는 편이 낫다.
#
# 잰 것 (명사 30,227 항목 · 동작 낱말 5,975개 기준):
#
#     깊이  2    4    8   12
#     붙음 1780 2054 2187 2201     <- 깊이를 늘려도 안 무너진다
#
#   가리기 전에는 깊이 8에서 2,858개가 붙었는데, 늘어난 671개를 표본으로
#   보니 8할이 오답이었다(무호흡->숨=장소 · 자부심->능력=장소 ·
#   걸레질->물기=장소). 커버리지가 준 것이 아니라 오답을 버린 것이다.
_sense_words = re.compile(r"[가-힣]{2,}")
_sense_particle = ("으로", "에서", "에게", "이나", "라도", "부터", "까지", "처럼", "보다",
           "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만", "로")


def _stem(phrase):
    """조사를 뗀다. '바퀴를' 과 '바퀴가' 가 안 겹치던 것을 막는다 —
    그것 때문에 자동차의 유가 차(茶) 로 갔다."""
    for art in _sense_particle:
        if len(phrase) > len(art) + 1 and phrase.endswith(art):
            return phrase[: -len(art)]
    return phrase


def core(sentence):
    return {_stem(w) for w in _sense_words.findall(sentence or "")}


def common_table(items):
    """낱말이 몇 개의 뜻풀이에 나오나. 흔할수록 값이 낮다.

    '만든'·'것'·'때' 는 어느 뜻풀이에나 있어서, 세기만 하면 '바퀴' 같은
    내용어와 같은 무게를 갖는다. 실제로 그래서 자동차가 차(茶) 로 갔다."""
    freq = collections.Counter()
    for a in items:
        freq.update(core(a["뜻"]))
    return freq


def pick_meaning(phrase, context, senses, freq, whole):
    """다의어의 여러 뜻 중 맥락과 제일 가까운 것. 못 고르면 None.

    겹치는 낱말마다 흔함의 역수를 더한다. 흔한 말 여럿보다 드문 말 하나가
    세다. 1등이 2등보다 뚜렷이 나을 때만 고른다 — 비슷하면 안 고른다."""
    after = senses.get(phrase) or []
    if not after:
        return None
    if len(after) == 1:
        return after[0]
    base = core(context)
    score = sorted(
        ((sum(math.log(whole / (1 + freq.get(w, 0))) for w in base & core(a["뜻"])), a)
         for a in after), key=lambda x: -x[0])
    if score[0][0] <= 0 or (len(score) > 1 and score[0][0] < score[1][0] * 1.3):
        return None
    return score[0][1]
