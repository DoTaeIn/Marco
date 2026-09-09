# -*- coding: utf-8 -*-
"""텍스트 폴더 -> 개념 지식 그래프. 주제를 가리지 않는다.

Mnemosyne 의 concept_graph 와 같은 모양이다.
  노드 = 개념 하나당 하나
  엣지 = 검증 가능한 사실 둘뿐
        설명함   — 그 대목의 제목이 이 개념이고 본문에 저 개념이 나온다
        같은조문 — 한 대목에 함께 나왔다
'A 가 B 를 함의한다' 를 지어내지 않는다. 그건 해석이지 사실이 아니다.

    python 짓기.py data/법지식              # 폴더 안 .txt/.md 전부
    python 짓기.py 내메모 --out 내.json
    python 짓기.py data/법지식 --min 3     # 3개 대목 이상 등장한 개념만

## 자기 지식으로 채우기

폴더에 .txt / .md 를 넣으면 된다. 대목을 나누는 기준은 자동으로 고른다:

  법령      제1조(제목) ...            -> 조문 단위
  마크다운   ## 제목                    -> 절 단위
  그 외      빈 줄로 나뉜 문단          -> 문단 단위

제목이 있으면 그것이 그 대목의 주제가 되어 '설명함' 엣지가 생긴다.
제목을 잘 달수록 그래프가 좋아진다.
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache

from passage_components import resolve_backend as excerpt_classifier

stopwords = {
    "경우", "때문", "정도", "가지", "대한", "통해", "위해", "다음", "이하", "이상",
    "다만", "전항", "본항", "규정", "적용", "제외", "포함", "사항", "내용", "부분",
    "여부", "관련", "기타", "그것", "이것", "자기", "타인", "해당", "각호", "동항",
    "전단", "후단", "본문", "단서", "조항", "항목", "이때", "당시", "이후", "이전",
    "일부", "전부", "이러", "저러", "무엇", "사람", "사용", "필요", "결과", "상태",
    # 개정 이력 표기 — 법 내용이 아니다
    "개정", "신설", "전문개정", "조신설", "본조신설", "전문", "시행", "삭제",
    "일부개정", "법률", "부칙", "공포", "종전", "구법", "개정법", "타법개정",
}
_amendment_mark = re.compile(r"<[^>]{0,80}(?:개정|신설|삭제)[^>]{0,80}>")
_addenda_start = re.compile(r"^\s*부\s*칙")
article_head = re.compile(r"^제\s*(\d+)\s*조(?:의\s*\d+)?\s*(?:\(([^)]*)\))?")
マ = None
markdown_head = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)


def _doc(src):
    """'형법 제21조(정당방위)' / '요리 / 김치찌개(김치찌개)' -> 문서 이름."""
    return re.split(r" 제\d|  ?/ |  ?문단\d", src)[0].strip()


def doc_name(path):
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"^법령_", "", name)
    name = re.sub(r"_?\(대한민국,?_?제\d+호\)$", "", name)
    return name.replace("_", " ").strip()


# 법제처 원문에는 계산식 이미지와 표 그림이 그대로 섞여 있다. 지식이 아니라
# 인쇄물의 흔적이다 — 개념으로도 뽑히고 발췌에도 딸려 나온다.
_residue = re.compile(r"<[^>]*>|https?://\S+|[┌┐└┘├┤┬┴┼─│┃━]+")


def _clean(txt):
    return " ".join(_residue.sub(" ", txt).split())


def split_passage(path):
    """문서를 '대목' 단위로 나눈다. Mne 의 슬라이드에 해당하는 단위다.

    법령이면 조문, 마크다운이면 절, 그 외에는 문단. 주제를 가리지 않으려면
    나누는 기준부터 주제를 안 가려야 한다."""
    whole_text = open(path, encoding="utf-8").read()
    if len(article_head.findall(whole_text)) >= 3 or re.search(r"^제\s*\d+\s*조", whole_text, re.M):
        block = split_article(path)
    elif len(markdown_head.findall(whole_text)) >= 2:
        block = split_clause(path, whole_text)
    else:
        block = split_para(path, whole_text)
    return [(src, _clean(body)) for src, body in block]


def split_clause(path, whole_text):
    name, block, cur, title = doc_name(path), [], [], None
    for line in whole_text.splitlines():
        m = markdown_head.match(line.strip())
        if m:
            if cur and title:
                block.append(("%s / %s(%s)" % (name, title, title), " ".join(cur)))
            title, cur = m.group(2), []
        elif line.strip():
            cur.append(line.strip())
    if cur and title:
        block.append(("%s / %s(%s)" % (name, title, title), " ".join(cur)))
    return block


def split_para(path, whole_text, min_n=40):
    name = doc_name(path)
    block = []
    for i, chunk in enumerate(re.split(r"\n\s*\n", whole_text), 1):
        chunk = " ".join(chunk.split())
        if len(chunk) >= min_n:
            head = chunk[:24].strip()
            block.append(("%s 문단%d(%s)" % (name, i, head), chunk))
    return block


def split_article(path):
    """법령 텍스트를 조문 단위로."""
    name = doc_name(path)
    block, cur, title = [], [], None
    idx = None
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if _addenda_start.match(line):
            idx = None                 # 부칙부터는 담지 않는다
            continue
        line = _amendment_mark.sub(" ", line)
        if not line.strip():
            continue
        m = article_head.match(line)
        if m:
            if cur and idx:
                block.append(("%s 제%s조%s" % (name, idx, "(%s)" % title if title else ""),
                             " ".join(cur)))
            idx, title, cur = m.group(1), m.group(2), [line]
        elif idx:
            cur.append(line)
    if cur and idx:
        block.append(("%s 제%s조%s" % (name, idx, "(%s)" % title if title else ""),
                     " ".join(cur)))
    return block


_kiwi = None


def extract_concepts(sentence):
    """복합명사를 하나로 붙여 뽑는다.

    '정당'+'방위' 가 아니라 '정당방위' 가 개념이다. 형태소를 낱개로 두면
    법률 용어가 전부 흩어진다.

    붙이는 조건은 두 가지다.
      1) 원문에서 실제로 붙어 있을 것. 공백을 넘어 이으면
         '경우 금융리스이용자' 가 '경우금융리스이용자' 라는 개념이 된다.
      2) 접미사(XSN)도 꼬리로 흡수할 것. '저작'+'권' 에서 끊으면
         '저작권' 이라는 개념이 아예 생기지 않는다 — 다만 '권' 은 홀로 개념이 아니다."""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    phrases, attached = set(), []
    end = -1

    def pack_vals():
        if attached:
            phrases.add("".join(f for f, _ in attached))
            phrases.update(f for f, alone in attached if alone and len(f) >= 2)
        attached.clear()

    for t in _kiwi.tokenize(sentence):
        noun = t.tag in ("NNG", "NNP", "SL")
        tail = t.tag == "XSN" and bool(attached)
        if not (noun or tail):
            pack_vals()
            continue
        if attached and t.start != end:
            pack_vals()
            if not noun:                      # 붙을 데가 없어진 접미사는 버린다
                continue
        attached.append((t.form, noun))
        end = t.start + t.len
    pack_vals()
    return {w for w in phrases if 2 <= len(w) <= 12 and w not in stopwords and not w.isdigit()}


_title_paren = re.compile(r"\(([^)]*)\)\s*$")


def title_concept(src):
    """'형법 제21조(정당방위)' -> {'정당방위'}.

    조문 제목은 그 조문의 주제다. 대칭적인 '같은조문' 보다 훨씬 많은 것을 말해준다 —
    무엇이 어디서 정의되는지, 그 조문이 무엇을 다루는지."""
    m = _title_paren.search(src)
    if not m:
        return set()
    phrase = m.group(1)
    emitted = set()
    for chunk in re.split(r"[,·]|등의|에 관한|의 ", phrase):
        chunk = chunk.strip()
        if 2 <= len(chunk) <= 14 and chunk not in stopwords:
            emitted.add(chunk)
    emitted |= extract_concepts(phrase)
    return {w for w in emitted if 2 <= len(w) <= 14 and w not in stopwords}


_DEFINITION_RE = [
    # 따옴표로 묶인 것은 정의 조항이다. 법령 제2조가 이 꼴이라 '은/는' 도 받는다.
    re.compile(r"[\"'“]([가-힣A-Za-z]{2,14})[\"'”]\s*(?:이란|란|이라 함은|라 함은|은|는)\s+(.{2,80}?)(?:을|를)\s*말한다"),
    # 따옴표가 없으면 '이란/란' 만 받는다. '은/는' 까지 받으면 보통 문장의
    # 괄호 삽입구가 정의로 둔갑한다 — '운전자는 도로(…에서는 차도를 말한다)의
    # 중앙…' 이 `운전자 -정의-> 차도` 를 만들고 있었다.
    re.compile(r"([가-힣A-Za-z]{2,14})\s*(?:이란|란|이라 함은|라 함은)\s+(.{2,80}?)(?:을|를)\s*말한다"),
    re.compile(r"([가-힣A-Za-z]{2,14})\s*(?:이란|란)\s+(.{2,80}?)(?:이다|입니다)"),
]

# 정의문에서 '무엇에 대고 하는 일인가' 를 뽑는다.
#
# 왜 필요한가. `세차하러 가는데 걸어서 5분 차로 10분이면 차를 타야 하나` 에
# 답하려면 '세차의 대상이 차' 라는 것을 알아야 한다. 그 한 줄이 없으면 엔진은
# 시간만 비교해서 걸어가라고 하거나(틀림) 미지를 낸다(못 함). 지금까지는
# 사람이 그래프에 손으로 적는 수밖에 없었다.
#
# 유(類)와 다른 자리다. 유는 문장 끝에 오고 대상은 그 앞 목적어 자리에 온다.
#
#     세차는 자동차를 씻는 일이다
#            └대상┘      └유┘
#
# 잰 것 (한국어 위키백과 45,760개 중 유가 동작류인 627개):
#     대상이 뽑힌 것 186개(30%) · 표본 12개 눈으로 봐서 대략 8할이 맞았다
#     우상숭배->우상 · 할례->포피 · 제설->얼음 · 적분->넓이 · 식분증->배설물
#
# 안 되는 것으로 확인된 길: **한자 공유**. `주차(駐車)` 와 `자동차(自動車)` 가
# 車 를 공유하니 이어보려 했는데 정밀도가 5~10% 였다. 한자 한 글자가 너무
# 모호하고(行 = 다니다/은행) 한국 인명의 끝 글자가 아무거나 다 걸린다
# (`발아(發芽) -> 芽 -> 오승아`). 게다가 세차·독서는 위키에 한자 풀이가 없다.
# 이 한 덩어리 정규식은 위키 문체(`…씻는 일이다`)만 받았다. 표준국어대사전
# 정의문은 서술어 없이 명사로 끝나고(`…감는 것.`), 관형형이 `-는` 이 아니라
# `-ㄴ/-은` 이며(`…만든 것`), 동작이 목적어에서 떨어져 있다
# (`흙을 떠서 던지는 일`). 셋 중 하나만 어긋나도 안 걸려서, 유가 동작류인
# 사전 정의문 2,539개에서 대상이 **1개**(0.0%) 나왔다.
#
# 그래서 한 덩어리를 자리별로 쪼갠다. 아래 `대상뽑기` 가 세 자리를 따로 본다.
_object = re.compile(r"^(?P<대상>[가-힣]{1,12})(?:을|를)$")
# 유 바로 앞 관형형이 그 정의문의 동작이다.
_adnominal = re.compile(r"^(?P<줄기>[가-힣]{1,8}?)(?:하|되)?(?:는|은)$")


def _strip_adnominal(phrase):
    """관형형 어미를 뗀 줄기. 못 떼면 None.

    과거 관형형은 어미가 낱글자로 서지 않는다 — `만든`·`나타낸` 의 ㄴ 은
    받침으로 앞 글자에 붙어 있어 `[가-힣]` 로 자르면 안 보인다. 사전
    정의문은 `…만든 것.`·`…나타낸 것.` 처럼 이 꼴이 흔해서, 받침을 안
    보면 유 앞자리를 통째로 놓친다."""
    # 한글이 아닌 글자가 섞이면 관형형이 아니다. `10월` 의 ㄹ 을 떼서
    # '10워' 라는 동작이 나왔다(개천절·초파일).
    if not phrase or not re.fullmatch(r"[가-힣]{2,10}", phrase):
        return None
    m = _adnominal.match(phrase)
    if m:
        return m.group("줄기") or None
    import hangul
    if hangul.batchim(phrase) not in ("ㄴ", "ㄹ"):
        return None
    stem = hangul.strip_batchim(phrase)
    stem = re.sub(r"(?:하|되)$", "", stem) or stem
    return stem or None
# 목적어 바로 뒤 낱말이 용언이면 그것이 대상을 직접 부리는 동작이다.
# **`-는` 과 이음씨끝만** 받는다. `-은/-ㄴ/-인` 은 한국어에서 그림씨 자리라
# `개념을 구체적인 …` 의 '구체적인', `몸을 건강한 …` 의 '건강한' 이 동작으로
# 새어 들어왔다. 그 둘을 막으면 표본 25개 중 오류가 6개에서 2개로 준다.
_predicate = re.compile(r"^(?P<줄기>[가-힣]{1,8}?)(?:하|되)?"
                    r"(?:는|거나|어서|아서|여서|해서|하여|고|며|면서|어|아|여|게)$")
# 유가 이 말들이면 그 낱말은 사물이 아니라 동작이다. 동작이라야 '대상' 이 있다.
action_kinds = ("행위", "일", "작업", "활동", "것", "과정", "절차", "운동", "놀이", "경기")
# 자리만 채우는 빈 이름들. 대상이 '것'·'수'·'위' 면 그래프가 `것이 있어야
# 한다` 가 되어 아무것도 제약하지 못한다.
_TARGET_DROP = {"목적", "경우", "방법", "사람", "때문", "위해", "이것", "그것", "등",
           "것", "수", "데", "바", "점", "위", "때", "안", "속", "앞", "뒤", "곳", "중",
           "이", "그", "저", "것들", "이것들", "그것들"}
# 동작 자리에 설 수 없는 줄기. 사전 정의문은 `…다듬음. 또는 그런 일.` 처럼
# 꼬리를 다는데, 유 앞 관형형이 그 '그런' 이라 동작이 죄다 '그러' 로 나왔다
# (표본 30개 중 3개). 지시어는 무엇을 하는지 말하지 않는다.
_ACTION_DROP = {"그러", "이러", "저러", "어떠", "하", "되", "있", "없", "같"}
# '~를 말한다/의미한다' 는 유가 문장 끝이 아니라 '를' 앞에 있다.
# '음계는 …음의 집합을 말한다' 의 유는 '말한' 이 아니라 '집합' 이다.
# 이 갈래를 안 두면 위키 45,760개에서 7,200개가 동사 조각으로 샜다.
_KEEP_MARK_RE = re.compile(r"([가-힣A-Za-z]{1,12})\s*(?:을|를)\s*"
                     r"(?:말한|의미한|가리킨|뜻한|일컫는|이르는|부르는|지칭한)다?\s*$")
# 계사. 과거형(였다)도 받는다 — '성직자였다' 의 유는 '성직자' 다.
# 탐욕 매칭이 '이' 를 먹지 않게 `이다` 를 먼저 본다(안 그러면 '정치인이다'
# 에서 '정치인이' 가 나온다. 위키에서 1,660번 겪었다).
_GENUS_RE = [re.compile(r"([가-힣]{1,10}?)\s*이다\s*$"),
           re.compile(r"([가-힣]{1,10}?)\s*였다\s*$"),
           re.compile(r"([가-힣]{1,10}?)\s*(?:이며|이고)\s*$"),
           re.compile(r"([가-힣]{1,10}?)\s*다\s*$"),
           # 사전 문체는 서술어 없이 명사로 끝난다 — '…묶어 놓은 것.',
           # '…둘레나 끝부분.'. 위 넷은 전부 '~다' 를 기다리므로 표준국어
           # 대사전 정의문의 67.5% 에서 유를 못 뽑았다. 그런데 그 끝 낱말이
           # 것·사람·일·곳·모양이라, 못 뽑은 것이 아니라 안 본 것이었다.
           #
           # 관형형 어미(-은/는/ㄴ/을/ㄹ) 뒤에 오는 명사만 유로 본다.
           # 그 자리가 한국어 정의문에서 유가 서는 자리다. 조사가 붙은
           # 명사('물건의')는 유가 아니라 딸린 말이므로 걸리지 않는다.
           re.compile(r"(?:[은는을를]|[ㄴ-힣])\s+([가-힣]{1,10})\s*[.\s]*$")]
# 유를 말하지 않는 문장. 상태·진행·용도는 '무엇인가' 에 답하지 않는다.
# '~하고 있다'(1,050개) · '~뜻으로 쓰인다'(344개) 가 여기 걸린다.
_not_genus = re.compile(r"(?:하고|되어|어져|아져|지고|알려져|가지고)\s*있다\s*$"
                    r"|쓰인다\s*$|불린다\s*$|여겨진다\s*$|한다\s*$|된다\s*$")
# 접미사로 거르면 안 된다. '정치인'·'군인'·'시인' 이 통째로 죽는다.
# 지시 동사는 위에서 따로 받으므로 여기서는 상태 동사와 계사 찌꺼기만 막는다.
_genus_chunk = re.compile(r"^(있|없|같|많|적|크|작|이)$")
_digits_only = re.compile(r"^[0-9]+$")


def extract_kind(definition):
    """정의문의 유(類). '…씻는 일이다' -> '일', '…집합을 말한다' -> '집합'.

    유가 왜 중요한가. 유는 그 자체로 낱말이라 제 유를 또 갖는다
    (`합주 -> 연주 -> 일`). 그 사슬을 따라가면 뿌리 몇 개로 모이므로,
    뿌리에 한 번 적은 것이 낱말 수천 개에 걸린다. 낱말마다 적는 대신
    유마다 적는 것이 이 함수를 쓰는 이유다.

    한국어 위키백과 45,760개로 잰 것:

        파편 뿌리로 흘러간 낱말   33% -> 3%
        상위 200개 성한 뿌리가    46% -> 64% 를 덮는다

    유를 못 뽑으면 None 이다. 억지로 내지 않는다 — '~하고 있다' 같은
    문장은 그 낱말이 무엇인지를 말하지 않는다."""
    s = (definition or "").rstrip(". ")
    if not s:
        return None
    directive = _KEEP_MARK_RE.search(s)
    if _not_genus.search(s):
        # 유를 말하지 않는 문장이다. 다만 '~를 말한다' 꼴은 살린다.
        return directive.group(1) if directive else None
    if directive:
        return directive.group(1)
    for t in _GENUS_RE:
        m = t.search(s)
        if m and m.group(1):
            after = m.group(1)
            if _genus_chunk.match(after) or _digits_only.match(after):
                return None
            return after
    return None


def extract_target(definition):
    """정의문 -> (대상, 동작). 동작을 정의하는 문장이 아니면 None.

    '세차는 자동차를 씻는 일이다' -> ('자동차', '씻')

    이것이 목적이 수단을 제약하는 관계다. 세차를 하려면 자동차가 그 자리에
    있어야 하므로, 걸어서 가면 목적 자체가 무너진다. 시간 비교는 미끼다.

    자리를 셋으로 나눠서 본다. 통째로 된 정규식 하나로는 위키 문체밖에
    못 받았다(`_목적어` 위 주석).

        가래질은  가래로 흙을        떠서   던지는  일
                        └대상┘      └동작┘  └끝동작┘ └유┘

    동작은 목적어 바로 뒤를 먼저 본다 — 대상을 직접 부리는 것이 거기 있다.
    거기가 용언이 아니면(`가치를 돈으로 나타낸 것` 의 '돈으로') 유 앞
    관형형으로 물러선다.

    표준국어대사전 56,555 표제로 잰 것:

        유가 동작류      2,539 (4.5%)
        대상 뽑힘        1,135 (동작류의 44.7%)   <- 고치기 전 1개(0.0%)
        그래프까지          718 (표제의 1.27%)

    표본 40개를 눈으로 봐서 대략 6할이 쓸 만했다. 남은 오류는 거의
    `유가 '것'` 갈래다 — `기포는 …모양을 이룬 것`, `교과는 …나누어 놓은
    것` 처럼 사물인데 동작류를 통과한다. 품사 표지 없이는 여기가 바닥이다."""
    if extract_kind(definition) not in action_kinds:
        return None
    chunk = (definition or "").rstrip(". ").split()
    if len(chunk) < 3:
        return None
    pos = [i for i, w in enumerate(chunk[:-1]) if _object.match(w)]
    if not pos:
        return None
    i = pos[-1]                          # 동작에 가장 가까운 목적어
    target = _object.match(chunk[i]).group("대상")
    if target in _TARGET_DROP:
        return None
    action = _strip_adnominal(chunk[-2])        # 유 바로 앞
    if i + 1 < len(chunk) - 1:
        beside = _predicate.match(chunk[i + 1])
        if beside:
            action = beside.group("줄기")
    # 종결형(`꾸몄다`)은 관형형이 아니다. 받침 벗기기가 우연히 만들어 낸다.
    # `하던` 의 ㄴ 을 떼면 '하더' 가 된다 — 회상 어미지 줄기가 아니다.
    if not action or action in _ACTION_DROP or action.endswith(("다", "더")):
        return None
    if action == target:                      # '늘어놓을 때 … 늘어놓는 것'
        return None
    return target, action


_genus_drop = re.compile(r"\([^)]*\)|[「」<>《》\[\]]")
_split_genus = re.compile(r"[ㆍ·,]")


def extract_genus(trunk):
    """정의문 몸통에서 유(類)만 뽑는다. 'A 또는 B' 는 둘 다.

    '"노면전차"란 …도로에서 궤도를 이용하여 운행되는 차를 말한다' 에서
    정의가 말하는 것은 '차' 하나다. 몸통의 개념을 전부 이으면
    `노면전차 -정의-> 이용` 이 생긴다 — 좁은 '같은조문' 이지 정의가 아니다.

    실제로 법지식 739개 중 노드당 정의 엣지가 하나뿐인 것이 3개였다.
    `소장` 에 23개가 붙어 형제자매·입자·비속이 다 정의라고 나왔다.

    한국어 정의문은 유가 맨 끝에 온다. 그 자리만 본다."""
    trunk = _genus_drop.sub(" ", trunk or "").strip()
    chunk = trunk.split()
    if not chunk:
        return set()
    emitted = set(_split_genus.split(chunk[-1]))
    # '도로 또는 차로를 말한다' 는 유가 둘이다.
    if len(chunk) >= 3 and chunk[-2] in ("또는", "및", "이나", "나", "와", "과"):
        emitted |= set(_split_genus.split(chunk[-3]))
    return {w.strip() for w in emitted if w.strip()}


def extract_concept_net(picks, pos, alone, max_tail=6):
    """개념 사이의 상위-하위 관계를 자동으로 찾는다.

    두 가지 신호만 쓴다. 둘 다 검증 가능하다.

    1) 한국어 복합명사는 머리가 뒤에 온다. '멸치육수' 는 육수의 일종이고
       '방위행위의과잉' 은 과잉의 일종이다. 뒷부분이 그 자체로 개념이면
       접미 관계가 곧 상위 관계다. 사전도 모델도 필요 없다.
    2) 법령 제2조 같은 정의 조항: 'X 란 ... 을 말한다'.

    임베딩 유사도는 쓰지 않는다 — 비슷한 것과 상위인 것은 다르다.
    '김치찌개' 와 '된장찌개' 는 비슷하지만 어느 쪽도 다른 쪽의 상위가 아니다."""
    concept_edge, seen = [], set()
    freq = {w: len(pos[w]) for w in picks}

    for a in picks:
        if len(a) < 4:
            continue
        # 긴 꼬리부터 본다. '신주인수권부사채' 의 머리는 '채' 가 아니라 '사채' 다.
        for tail in range(min(len(a) - 1, 2 + max_tail), 1, -1):
            b = a[-tail:]
            if b == a or b not in picks or (a, b) in seen:
                continue
            # 진짜 상위어는 홀로도 쓰인다. '육수' 는 그 자체로 나오지만
            # '법시행당시' 는 '헌법시행당시' 안에서만 나온다 — 개념이 아니라 조각이다.
            # 빈도로 재면 둘이 같은 자리에만 나올 때 구별이 안 된다.
            # 근거는 둘 중 하나면 된다.
            #   홀로 쓰인 적이 있다  -> 그 자체로 개념이다
            #   더 자주 나온다        -> 상위어답게 넓게 쓰인다
            # 둘 다 아니면 '헌법시행당시' 속 '법시행당시' 같은 조각이다.
            if b not in alone and freq[b] <= freq[a]:
                continue
            seen.add((a, b))
            concept_edge.append([a, "상위", b])
            break
    return concept_edge


def extract_definitions(files, picks):
    """정의 조항에서 'X 는 Y 를 말한다' 를 뽑는다."""
    emitted, seen = [], set()
    for f in files:
        doc = doc_name(f)
        first_passage, doc_intro = None, None
        for src, body in split_passage(f):
            if first_passage is None:
                first_passage = src
            # 법의 정의는 조문 안에 없고 제1조(목적)에 있다. 다만 그 앞에
            # '제1조 제1장 총칙' 같은 편·장 표시가 먼저 나오므로 제목이 있는 것을 고른다.
            if doc_intro is None and "(" in src and re.search(r"제\s*1\s*조", src):
                doc_intro = (src, body)
            if "말한다" not in body and "이란" not in body:
                continue
            for pat in _DEFINITION_RE:
                for m in pat.finditer(body):
                    head = m.group(1).strip()
                    # 유가 조사·접미사를 달고 있으면 개념뽑기가 떼 준다. 다만
                    # 개념뽑기는 조각도 함께 낸다('자율주행시스템' -> 자율·주행·
                    # 시스템). 조각은 유가 아니므로 가장 긴 것만 받는다.
                    genus = extract_genus(m.group(2))
                    tail = set(genus)
                    for w in genus:
                        split_ = extract_concepts(w)
                        if split_:
                            tail.add(max(split_, key=len))
                    if head not in picks:
                        continue
                    for b in tail:
                        if b in picks and b != head and (head, b) not in seen:
                            seen.add((head, b))
                            emitted.append([head, "정의", b])
    return emitted


_sentence_end = re.compile(r"(?<=다)\.\s+|(?<=다)\.$|\n")


@lru_cache(maxsize=8192)
def _split_sentences(body):
    """문장으로 자르되 괄호 안에서는 자르지 않는다.

    법령은 '제공(공유를 포함한다. 이하 같다)' 처럼 괄호 안에 문장을 넣는다.
    거기서 자르면 '제공(공유를 포함한다' 라는 반토막이 발췌로 남는다."""
    emitted = []
    for chunk in _sentence_end.split(body):
        chunk = " ".join((chunk or "").split())
        if not chunk:
            continue
        if emitted and emitted[-1].count("(") > emitted[-1].count(")"):
            emitted[-1] += ". " + chunk
        else:
            emitted.append(chunk)
    return emitted


def extract_excerpt(phrase, body, max_n=190):
    """그 개념이 나오는 문장들을 원문에서 그대로 가져온다.

    하나만 저장하면 안 된다. 같은 개념이 여러 대목에 다른 정보로 나오기 때문이다 —
    '두부' 는 자기 절에서 '콩을 갈아 응고시킨 것' 이지만 김치찌개 절에서는
    '마지막에 넣어야 부서지지 않는다' 이다. '언제 넣어?' 에 정의를 주면 답이 아니다.
    고르는 일은 질문을 본 뒤에 한다."""
    sentences = _split_sentences(body)
    matched = [x for x in sentences if phrase in x] or sentences[:1]
    emitted = []
    for x in matched:
        if len(x) > max_n:
            # 자를 자리는 마지막 쉼표나 띄어쓰기. 낱말 중간에서 끊지 않는다.
            cut = x[:max_n]
            cut = cut[:max(cut.rfind(", "), cut.rfind(" "))] or cut
            x = cut.rstrip(" ,") + "…"
        elif not x.endswith((".", "다", "요", "함", "음", "…")):
            x += "."
        emitted.append(x)
    return emitted


# 벌칙·금액 조문은 문서 맨 뒤에 몰려 있다. 대목을 앞에서부터 담으면 절대 들어오지
# 않는다 — 저작권은 64개 대목에 나오고 벌칙은 제136조다. 그래서 '얼마를 처벌하나'
# 를 말하는 문장은 순서와 무관하게 한 줄씩 따로 챙긴다.
# 여기 표지는 지식.py 의 뜻표지(처벌/금액)와 짝이다. 한쪽만 고치면 안 된다.
kind_marker = (("징역", "벌금", "과태료", "처한다", "구류", "몰수", "처벌한다"),
            ("만원", "원 이하", "원 이상", "100분의", "배 이하"))


def _kind_sentence(phrase, order, collection_body, already, scan_max=40):
    """그 개념에 대해 '어떻게 처벌하나' '얼마인가' 를 말하는 문장을 찾아 온다.

    그 개념의 이름이 든 문장만 받는다. 이름 없이 표지만 보면 아무 조문의
    '500만원 이하' 나 끌고 온다 — 실제로 음주운전에 교통안전교육기관 과태료가
    붙었다. 그래서 벌을 정한 줄이 각 호로 나뉘어 이름을 안 부르면 못 찾는다.
    저작권법 벌칙(제136조)이 그 경우다 — '저작재산권' 이라고만 쓴다."""
    emitted, seen = [], list(already)
    for marker in kind_marker:
        for src in order[:scan_max]:
            picks = next((x for x in extract_excerpt(phrase, collection_body.get(src, ""))
                         if phrase in x and any(t in x for t in marker) and x not in seen), None)
            if picks:
                emitted.append({"글": picks, "곳": src, "꼴": tag_form(picks)})
                seen.append(picks)
                break

    # 벌칙 조문은 머리에서 형을 정하고 각 호에서 무엇을 벌하는지 적는다.
    # '5년 이하의 징역' 이 든 줄에는 '저작권' 이 없다 — 위에서는 못 찾는다.
    # 제목이 벌칙인 조문에 한해, 그 조문이 이 개념을 다루면(그래서 차례에 있다)
    # 머리 문장을 받는다. 조문 이름이 답에 함께 나가므로 확인할 수 있다.
    if not any(any(t in x["글"] for t in kind_marker[0]) for x in emitted + [{"글": y} for y in already]):
        # 벌칙은 문서 맨 뒤다. 여기서는 끝까지 훑는다 — 제목만 보므로 싸다.
        for src in order:
            if not re.search(r"\((?:벌칙|과태료)[^)]*\)$", src):
                continue
            picks = next((x for x in _split_sentences(collection_body.get(src, ""))
                         if any(t in x for t in kind_marker[0]) and x not in seen), None)
            if picks:
                _short = picks[:190].rstrip() + ("…" if len(picks) > 190 else "")
                emitted.append({"글": _short, "꼴": tag_form(_short),
                            "곳": src})
                break
    return emitted


# 발췌의 꼴. 지을 때 한 번 매기고 대화 때는 읽기만 한다.
#
# 한 개념에 문장이 여럿 붙어도 지금까지는 전부 같은 종류였다 — "이 낱말이
# 나온 문장". 종류로 안 갈려 있으니 골라 쓸 수가 없어서, `임계값이 뭐야` 와
# `임계값 어떻게 정해` 가 같은 답을 냈다. 실제로 168물음에서 같은 답이 여러
# 물음에 나온 경우가 11건이었다.
#
# 사람이 라벨한 문장은 그대로 보존한다. 새 문장의 꼴은 설치한 분류 부품이
# 맡으며, 부품이 없을 때는 근거 없이 유형을 단정하지 않고 `진술`로 둔다.
_person_form = {}


def read_excerpt_form(path):
    """사람이 판단한 발췌의 꼴. 앞 50자를 열쇠로 맞춘다.

    수동 라벨은 언어와 분류 부품을 바꾸어도 변하지 않는 기준 자료다. 새 문장
    분류는 ``NAI_PASSAGE_BACKEND``로 고른 부품이 담당한다."""
    global _person_form
    _person_form = {}
    if not path or not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    for form, sentences in (d.get("꼴") or {}).items():
        parts = [x for x in form.split(",") if x]
        for head in sentences:
            _person_form[head] = parts
    return len(_person_form)


def tag_form(txt, backend=None):
    """문장 하나의 꼴. 여럿 걸릴 수 있다 — 한 문장이 이유이면서 실측일 수 있다.

    사람이 적어 둔 것이 있으면 그것을 쓴다. 새 문장은 교체 가능한 분류
    부품에 맡기며, 기본 부품은 추측 대신 '진술'을 보존한다."""
    if _person_form:
        head = txt[:50]
        parts = _person_form.get(head)
        if parts:
            return list(parts)
    parts = excerpt_classifier(backend).classify(txt)
    return [x for x in parts if isinstance(x, str) and x] or ["진술"]


def _gather_excerpts(phrase, seen_place, def_at, collection_body, max_passage=8):
    """그 개념이 나온 대목들에서 문장을 모은다. 정의처를 앞에 둔다.

    4대목까지만 담았더니 '저작권 침해하면 처벌받아?' 에 벌칙 조문이 후보에도
    없었다 — 저작권은 64개 대목에 나오고 벌칙은 맨 뒤(제136조)다. 정의 조문들이
    앞자리를 다 차지한다. 고르는 일은 질문을 보고 하므로 후보는 넉넉해야 한다.

    넉넉해도 느려지지 않는다. 질문할 때 표지로 8개까지 추린 뒤에 인코딩한다 —
    비싼 것은 후보를 들고 있는 것이 아니라 인코딩이다."""
    order = list(def_at or []) + [c for c in dict.fromkeys(seen_place)
                                 if c not in set(def_at or [])]
    emitted = []
    for src in order[:max_passage]:
        for sentence in extract_excerpt(phrase, collection_body.get(src, ""))[:2]:
            if sentence and sentence not in [x["글"] for x in emitted]:
                emitted.append({"글": sentence, "곳": src, "꼴": tag_form(sentence)})
    return emitted + _kind_sentence(phrase, order, collection_body, [x["글"] for x in emitted])


def read_synonym(path):
    """노드마다 사람이 쓸 만한 표현을 적어 둔 파일. 없으면 빈 것.

    인코더는 동의어를 못 한다 — '해고' 와 '면직' 은 자모가 안 겹쳐 0 이다.
    그렇다고 이 코퍼스에서 분포로 배울 수도 없다. 문단 536개에서 '거짓말'
    과 '환각' 이 같이 나온 문단은 1개, '자료' 와 '캐시' 는 0개다. 개념쌍의
    15.8% 만 한 번이라도 같이 나오고 그 중앙값이 1회다 — 셀 것이 없으면
    추정할 것도 없다. 큰 코퍼스에서 배운 모델을 오프라인 선생으로 써 보려
    했지만 낱말 하나만 주면 벡터가 무너졌고('고갈' 과 '네임' 이 1.000)
    문장을 줘도 구절↔개념은 대조군과 안 갈렸다.

    그래서 이 자리는 사람이 채운다. 런타임은 이 파일을 안 읽는다 — 지은
    그래프 안에 표현으로 들어가 있고, 대화는 계속 문자 인코더로 돈다."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return {k: list(v) for k, v in d.items()
            if not k.startswith("_") and isinstance(v, list)}


def read_relation(path):
    """사람이 판단해서 적은 관계. 없으면 빈 것.

    원문에서 셀 수 있는 관계는 '같이 나왔다'(같은조문)와 '여기서 설명된다'
    (설명함) 둘뿐이다. 둘 다 "관련 있다" 는 말의 다른 표현이지 무엇을
    주장하지 않는다. 그래서 자동으로 뽑은 문서그래프는 엣지가 1만 개인데
    답에 실린 것이 168물음 중 6번, 경로를 탄 것이 0번이었다.

    정의문을 캐서 뜻을 실어 보려 했지만 이 코퍼스에 정의문이 없다 —
    '라고 한다' 2건, '즉/다시 말해' 0건, 괄호 별칭은 전부 표와 코드
    조각이었다. **관계는 세어서 나오는 것이 아니라 판단해서 나온다.**
    그 판단을 사람이 적는 자리가 이 파일이다."""
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    emitted = []
    for line in d.get("관계", []):
        if isinstance(line, list) and len(line) == 3 and all(line):
            emitted.append([str(line[0]), str(line[1]), str(line[2])])
    return emitted


def build(files, min_n=2, edge_min=2, synonym=None, relation=None):
    pos = defaultdict(list)
    by_article = []
    defs = defaultdict(list)          # 개념 -> 그것을 제목으로 단 조문들
    collection_body = {}
    alone = set()                      # 원문에 그 말이 홀로(앞뒤가 한글이 아니게) 나온 적 있는 개념
    vocab = set()                      # 코퍼스가 본 말 전부. 노드 고르기 전이다
    for f in files:
        doc = doc_name(f)
        first_passage, doc_intro = None, None
        for src, body in split_passage(f):
            if first_passage is None:
                first_passage = src
            # 법의 정의는 조문 안에 없고 제1조(목적)에 있다. 다만 그 앞에
            # '제1조 제1장 총칙' 같은 편·장 표시가 먼저 나오므로 제목이 있는 것을 고른다.
            if doc_intro is None and "(" in src and re.search(r"제\s*1\s*조", src):
                doc_intro = (src, body)
            phrases = extract_concepts(body)
            title_before_sub = title_concept(src)
            # 어휘는 노드가 아니다. 아래 교집합은 '무엇을 개념으로 세울까' 를
            # 고르는 규칙이라 제목에만 있는 말을 버린다 — '매니저' 는 제목에만
            # 나오고 '그래프' 는 본문에도 나와서 교집합이 안 비고, 그래서
            # '매니저' 가 사라진다. 코퍼스가 그 말을 본 것은 사실이므로
            # 거르기 전에 담는다.
            vocab |= phrases | title_before_sub
            title = title_before_sub & phrases or title_before_sub
            phrases |= title
            by_article.append((src, phrases, title))
            collection_body[src] = body
            for w in phrases:
                if w in alone:
                    continue
                if re.search(r"(?<![가-힣])%s(?![가-힣])"
                             % re.escape(w), body):
                    alone.add(w)
            for w in phrases:
                pos[w].append(src)
            for w in title:
                defs[w].append(src)
        # 법은 자기 이름을 거의 안 쓴다 — '상법' 원문에 '상법' 이 1회뿐이다.
        # 문서 이름은 물어볼 수 있는 대상이므로 개념으로 등록한다.
        if first_passage and 2 <= len(doc) <= 20:
            intro_at = doc_intro[0] if doc_intro else first_passage
            pos[doc].append(intro_at)
            defs[doc].append(intro_at)
            by_article[-1][1].add(doc)
            by_article[-1][2].add(doc)      # 제목 취급 — 한 번만 나와도 남는다

    # 제목으로 쓰인 개념은 한 번만 나와도 남긴다. 제목은 그 자체로 정의다 —
    # 해설서에서 '## 과잉방위' 한 절만 있어도 그것은 버릴 개념이 아니다.
    title_whole = {w for _, _, title in by_article for w in title}
    picks = {w for w, v in pos.items() if len(v) >= min_n} | (title_whole & set(pos))
    doc_count = {w: len({_doc(c) for c in pos[w]}) for w in picks}
    # 개념을 고르는 문은 아래 `주제감` 에서 한 번 더 좁힌다. 무게를 재려면
    # 문서수가 먼저 있어야 해서 여기서 못 한다.

    pair = Counter()
    explain_pair = Counter()
    for _, phrases, title in by_article:
        for main in sorted(title & picks):
            for sub in sorted((phrases - title) & picks):
                explain_pair[(main, sub)] += 1
        together = sorted((phrases - title) & picks)
        if len(together) > 60:              # 조문 하나가 그래프를 지배하지 않게
            together = together[:60]
        for i in range(len(together)):
            for j in range(i + 1, len(together)):
                pair[(together[i], together[j])] += 1

    # Mne 의 explained(인쇄 + 발화) 에 해당하는 신호: 특정 법에 몰려 있는가.
    # 14개 법에 다 나오는 '청구' 는 맞는 말이지만 정보가 없다.
    total_doc = len({_doc(c) for v in pos.values() for c in v})
    import math

    def score(w):
        freq = len(pos[w])
        spread = math.log(total_doc / max(doc_count[w], 1) + 1)   # 한 문서에 몰릴수록 높다
        length = 1.0 + 0.12 * max(len(w) - 2, 0)           # 복합어를 조금 우대
        return round(freq * spread * length, 1)

    node = {}
    meta = {}
    for w in picks:
        node[w] = [w]
        by_law = Counter(_doc(c) for c in pos[w])
        repr_law = by_law.most_common(1)[0][0]
        repr_article = next(c for c in pos[w] if c.startswith(repr_law))
        meta[w] = {"community": repr_law,
                   "file": repr_article, "loc": None, "type": "법률개념",
                   "무게": score(w), "빈도": len(pos[w]), "문서수": doc_count[w],
                   "정의처": sorted(set(defs.get(w, [])))[:4],
                   "발췌": _gather_excerpts(w, pos[w], defs.get(w), collection_body),
                   "출처": [c for c, _ in Counter(pos[w]).most_common(6)],
                   "법별": by_law.most_common(4)}
    # 가르친 표현을 붙인다. 두 군데에 같이 넣어야 한다 — 말 예시만 넣으면
    # `_모르는말` 이 그 표현의 낱말을 모른다고 먼저 거절한다. 실제로 '임계값'
    # 에 'threshold' 를 붙였는데도 어휘에 없어서 미지였다.
    teaching = 0
    for name, forms in (synonym or {}).items():
        if name not in node:
            continue
        node[name] = list(dict.fromkeys(list(node[name]) + [t for t in forms if t]))
        for t in forms:
            vocab.update(extract_concepts(t))
            vocab.update(w for w in re.findall(r"[A-Za-z]{2,}", t))
        teaching += 1
    if teaching:
        print("가르친 노드 %d개" % teaching)

    # 주제가 될 수 없는 말을 노드에서 뺀다. **어휘에서는 안 뺀다** —
    # 노드와 어휘는 원래 따로다(노드 1,209 / 어휘 3,060). 그래서 빼도
    # `_모르는말` 이 그 말을 모른다고 하지 않는다. 주인공이 못 될 뿐
    # 조연으로는 남는다.
    #
    # 잣대는 무게이고 문턱은 10이다. 제목으로 쓰인 적이 있으면(정의처) 무게가
    # 낮아도 남긴다 — 제목은 그 자체로 정의다.
    #
    # 재보니 정확도는 안 변하고(안 65/96 그대로) **코퍼스 밖 물음이 새는
    # 것이 9/62 -> 5/62 로 준다.** '오늘 서울 날씨' 가 `오늘` 로, '저녁 뭐
    # 먹지' 가 `저녁` 으로 답하던 것이 사라진다. 문턱을 12 위로 올리면
    # 진짜 개념까지 잘려 정확도가 61/96 으로 떨어진다.
    topic_thresh = float(os.environ.get("KG_TOPIC_MIN", "10"))
    # 사람이 표현을 가르쳐 넣은 노드는 안 자른다. 가르쳤다는 것 자체가
    # '이건 주제다' 라는 선언이다. 안 지키면 `캐시`·`개념망`·`오타` 처럼
    # 방금 가르친 것이 다음 줄에서 잘려나간다 — 실제로 그랬다.
    # 관계를 적어 준 노드도 지킨다. 관계의 한쪽 끝이 잘리면 그 관계가
    # 통째로 없어진다 — 실제로 주제문턱이 정의엣지 17개를 5개로 깎았다.
    keep = set(synonym or {}) | {x for a, _r, b in (relation or []) for x in (a, b)}
    drop = {w for w in picks
            if w not in keep
            and score(w) < topic_thresh and not (defs.get(w) or w in title_whole)}
    if drop:
        picks = picks - drop
        node = {w: v for w, v in node.items() if w in picks}
        meta = {w: v for w, v in meta.items() if w in picks}
        print("주제가 되기엔 가벼운 말 %d개를 노드에서 뺐다 (어휘에는 남는다)" % len(drop))

    edge = [[a, "설명함", b] for (a, b), w in explain_pair.most_common() if w >= 1]
    edge += [[a, "같은조문", b] for (a, b), w in pair.most_common() if w >= edge_min]
    # 쌍은 노드를 걸러내기 전에 세어 두었다. 없어진 노드를 가리키는 엣지가
    # 남으면 이웃 지도와 잇는길 이 없는 곳을 가리킨다.
    edge = [e for e in edge if e[0] in picks and e[2] in picks]
    # 사람이 적은 관계는 **엣지에도** 넣는다. 개념망(개념엣지)은 상위-하위를
    # 담는 곳이라 잇는길 이 안 본다. 경로를 타려면 엣지에 있어야 한다.
    edge = [e for e in (relation or []) if e[0] in picks and e[2] in picks] + edge
    human_relation = [e for e in (relation or []) if e[0] in picks and e[2] in picks]
    if relation:
        print("사람이 적은 관계 %d개 중 %d개를 얹었다" % (len(relation), len(human_relation)))
    concept_edge = [e for e in extract_concept_net(picks, pos, alone) + extract_definitions(files, picks)
                if e[0] in picks and e[2] in picks] + human_relation
    # 자동으로 뽑은 것도 **엣지에** 넣는다. 위 주석은 사람이 적은 관계에만
    # 걸려 있었고, 그래서 법지식 7,183노드에서 상위 3,053 · 정의 827이 전부
    # 개념엣지에 갇혀 _인접·잇는길이 한 번도 못 봤다. 관계말 경로에 닿는
    # 노드가 0개였던 것이 이 한 줄이 없어서다.
    has = {tuple(e) for e in edge}
    edge = [list(e) for e in concept_edge if tuple(e) not in has] + edge
    return {"역할": "안내", "목표": None, "설명그래프": True,
            "개념엣지": concept_edge,
            "임계값": {"A_MIN": 0.45, "OK_MIN": 0.58},
            "노드": node, "메타": meta, "엣지": edge, "무관층": {},
            # 코퍼스가 본 말 전부. 노드는 `최소` 로 걸러지고 발췌는 대목마다
            # 하나씩만 남아서, 둘 중 어느 것도 '이 코퍼스가 아는 말' 의 목록이
            # 못 된다 — 한 번만 나온 '매니저' 를 모른다고 하면 멀쩡한 물음이
            # 거절된다.
            "어휘": sorted(vocab),
            "조문수": len(by_article)}


def _selfcheck():
    """개념을 붙이는 규칙 두 가지가 살아 있는지."""
    has_case = extract_concepts("저작권을 침해한 자는 음주운전 방지장치를 부착한다")
    assert "저작권" in has_case, has_case          # 접미사(권)에서 끊기지 않는다
    assert "음주운전" in has_case, has_case        # 붙어 있는 것은 붙인다
    assert "권" not in has_case                # 접미사 혼자는 개념이 아니다
    assert not any(len(w) > 8 for w in has_case), has_case   # 공백을 넘어 붙이지 않는다
    assert extract_concepts("정당방위 규정") == {"정당방위"}

    # 유(類)는 문장 끝, 대상은 그 앞 목적어 자리.
    assert extract_kind("세차는 자동차를 씻는 일이다") == "일"
    # '정치인이다' 에서 '정치인이' 가 나오면 안 된다 — 탐욕 매칭 함정
    assert extract_kind("김구는 정치인이다") == "정치인"
    # '~를 말한다' 는 유가 끝이 아니라 '를' 앞에 있다. 이걸 안 보면
    # 위키 45,760개에서 7,200개가 '말한'·'의미한' 으로 샌다.
    assert extract_kind("음계는 음높이 순서로 된 음의 집합을 말한다") == "집합"
    assert extract_kind("가수는 목소리로 음악을 부르는 사람을 말한다") == "사람"
    assert extract_kind("기술은 공학과 관련하여 다양한 뜻을 의미한다") == "뜻"
    # 과거 계사도 유를 낸다
    assert extract_kind("정명조는 대한민국의 성직자였다") == "성직자"
    # 한 글자 유는 진짜다. '진위면은 …에 있는 면이다' 를 죽이면 안 된다.
    assert extract_kind("진위면은 경기도 평택시에 있는 면이다") == "면"
    assert extract_kind("어의리는 대한민국의 리이다") == "리"
    # 접미사로 거르면 '정치인'·'군인'·'시인' 이 통째로 죽는다
    for phrase in ("군인", "시인", "법조인", "기업인"):
        assert extract_kind("아무개는 대한민국의 %s이다" % phrase) == phrase, phrase
    # 유를 말하지 않는 문장에서는 억지로 내지 않는다
    assert extract_kind("악어는 파충류의 총칭으로 오래전에 진화한 것으로 알려져 있다") is None
    assert extract_kind("기술은 과학, 공학과 관련하여 다양한 뜻으로 쓰인다") is None
    assert extract_kind("수소의 원자 번호는 1이다") is None
    assert extract_target("세차는 자동차를 씻는 일이다") == ("자동차", "씻")
    assert extract_target("등산은 산을 오르는 것이다") == ("산", "오르")
    assert extract_target("독서는 책을 읽는 행위이다") == ("책", "읽")
    # 동작이 아닌 것에는 대상이 없다. 사물 정의에 억지로 붙이지 않는다.
    assert extract_target("자동차는 스스로 움직이는 차이다") is None
    assert extract_target("서울은 대한민국의 수도이다") is None
    # 사전 문체. 서술어 없이 명사로 끝나고 관형형이 과거(`-ㄴ`)다.
    assert extract_target("가격은 물건의 가치를 돈으로 나타낸 것.") == ("가치", "나타내")
    # 동작이 목적어에서 떨어져 있다 — 유 앞 관형형으로 물러선다.
    assert extract_target("가래질은 흙을 떠서 던지는 일.") == ("흙", "던지")
    # 표제어 없이 뜻풀이만 줘도 뽑힌다. 일괄 처리는 이 꼴로 넣는다.
    assert extract_target("강이나 호수에서 물고기를 잡는 일.") == ("물고기", "잡")
    # 지시어는 동작이 아니다. `또는 그런 일.` 꼬리에서 '그러' 가 샜다.
    assert extract_target("퇴고는 글을 고치고 다듬음. 또는 그런 일.") is None
    # 한글이 아닌 글자가 섞인 자리는 관형형이 아니다. '10월' -> '10워'.
    assert extract_target("개천절은 고조선을 건국한 날을 기념하는 국경일. 10월 3일이다.") is None
    # 그림씨는 동작이 아니다. `-은/-ㄴ/-인` 자리를 곁에서 안 받는 이유다.
    assert extract_target("건강관리는 몸을 건강한 상태로 유지하는 일.")[1] != "건강한"
    print("selfcheck ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _selfcheck()
        sys.exit(0)
    min_n = int(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 2
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    # 폴더를 여럿 받는다. 스스로 배우는 회로가 원래 코퍼스에 받아온 글을
    # 얹어서 다시 지어야 하기 때문이다 — 따로 지으면 두 그래프가 되고,
    # 그러면 배운 것이 원래 알던 것과 한자리에서 겨루지 못한다.
    folders = argv or [os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data/법지식")]
    folder = folders[0]
    out_edges = (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv
            else os.path.join(folder, "지식그래프.json"))
    file = sorted(f for d in folders
                  for f in glob.glob(os.path.join(d, "*.txt"))
                  + glob.glob(os.path.join(d, "*.md")))
    # 폴더 설명서는 지식이 아니다. README 가 코퍼스에 섞이면 그 안의 예시가
    # 개념의 정의처로 잡힌다 — 실제로 README 가 '정당방위' 를 가로챘다.
    file = [f for f in file
            if not os.path.basename(f).lower().startswith(("readme", "_", "."))]
    if not file:
        print("%s 안에 .txt 나 .md 가 없습니다." % ", ".join(folders))
        sys.exit(1)
    synonym_dir = (sys.argv[sys.argv.index("--동의어") + 1] if "--동의어" in sys.argv
                else os.path.join(folder, "_동의어.json"))
    form_dir = (sys.argv[sys.argv.index("--발췌꼴") + 1] if "--발췌꼴" in sys.argv
            else os.path.join(folder, "_발췌꼴.json"))
    _n = read_excerpt_form(form_dir)
    if _n:
        print("사람이 판단한 발췌 꼴 %d개를 읽었다" % _n)
    relation_dir = (sys.argv[sys.argv.index("--관계") + 1] if "--관계" in sys.argv
              else os.path.join(folder, "_관계.json"))
    g = build(file, min_n=min_n, synonym=read_synonym(synonym_dir), relation=read_relation(relation_dir))
    json.dump(g, open(out_edges, "w", encoding="utf-8"), ensure_ascii=False)
    print("문서 %d개 · 대목 %d개" % (len(file), g["조문수"]))
    reward = sum(1 for e in g["개념엣지"] if e[1] == "상위")
    print("개념 %d개 · 엣지 %d개 · 개념망 %d개(상위 %d · 정의 %d) -> %s"
          % (len(g["노드"]), len(g["엣지"]), len(g["개념엣지"]), reward,
             len(g["개념엣지"]) - reward, out_edges))
    top = sorted(g["메타"].items(), key=lambda kv: -kv[1]["무게"])[:12]
    print("\n가장 많이 나오는 개념:")
    for w, m in top:
        print("  %7.1f  %-14s  %3d회 · 문서 %d개  %s"
              % (m["무게"], w, m["빈도"], m["문서수"], m["출처"][0]))
