# -*- coding: utf-8 -*-
"""텍스트 폴더 -> 개념 지식 그래프. 주제를 가리지 않는다.

Mnemosyne 의 concept_graph 와 같은 모양이다.
  노드 = 개념 하나당 하나
  엣지 = 검증 가능한 사실 둘뿐
        설명함   — 그 대목의 제목이 이 개념이고 본문에 저 개념이 나온다
        같은조문 — 한 대목에 함께 나왔다
'A 가 B 를 함의한다' 를 지어내지 않는다. 그건 해석이지 사실이 아니다.

    python 짓기.py 자료/법지식              # 폴더 안 .txt/.md 전부
    python 짓기.py 내메모 --out 내.json
    python 짓기.py 자료/법지식 --min 3     # 3개 대목 이상 등장한 개념만

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

버릴말 = {
    "경우", "때문", "정도", "가지", "대한", "통해", "위해", "다음", "이하", "이상",
    "다만", "전항", "본항", "규정", "적용", "제외", "포함", "사항", "내용", "부분",
    "여부", "관련", "기타", "그것", "이것", "자기", "타인", "해당", "각호", "동항",
    "전단", "후단", "본문", "단서", "조항", "항목", "이때", "당시", "이후", "이전",
    "일부", "전부", "이러", "저러", "무엇", "사람", "사용", "필요", "결과", "상태",
    # 개정 이력 표기 — 법 내용이 아니다
    "개정", "신설", "전문개정", "조신설", "본조신설", "전문", "시행", "삭제",
    "일부개정", "법률", "부칙", "공포", "종전", "구법", "개정법", "타법개정",
}
_개정표기 = re.compile(r"<[^>]{0,80}(?:개정|신설|삭제)[^>]{0,80}>")
_부칙시작 = re.compile(r"^\s*부\s*칙")
조머리 = re.compile(r"^제\s*(\d+)\s*조(?:의\s*\d+)?\s*(?:\(([^)]*)\))?")
マ = None
마크다운머리 = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)


def _문서(출처):
    """'형법 제21조(정당방위)' / '요리 / 김치찌개(김치찌개)' -> 문서 이름."""
    return re.split(r" 제\d|  ?/ |  ?문단\d", 출처)[0].strip()


def 문서이름(경로):
    이름 = os.path.splitext(os.path.basename(경로))[0]
    이름 = re.sub(r"^법령_", "", 이름)
    이름 = re.sub(r"_?\(대한민국,?_?제\d+호\)$", "", 이름)
    return 이름.replace("_", " ").strip()


# 법제처 원문에는 계산식 이미지와 표 그림이 그대로 섞여 있다. 지식이 아니라
# 인쇄물의 흔적이다 — 개념으로도 뽑히고 발췌에도 딸려 나온다.
_찌꺼기 = re.compile(r"<[^>]*>|https?://\S+|[┌┐└┘├┤┬┴┼─│┃━]+")


def _씻기(글):
    return " ".join(_찌꺼기.sub(" ", 글).split())


def 대목쪼개기(경로):
    """문서를 '대목' 단위로 나눈다. Mne 의 슬라이드에 해당하는 단위다.

    법령이면 조문, 마크다운이면 절, 그 외에는 문단. 주제를 가리지 않으려면
    나누는 기준부터 주제를 안 가려야 한다."""
    본 = open(경로, encoding="utf-8").read()
    if len(조머리.findall(본)) >= 3 or re.search(r"^제\s*\d+\s*조", 본, re.M):
        덩어리 = 조문쪼개기(경로)
    elif len(마크다운머리.findall(본)) >= 2:
        덩어리 = 절쪼개기(경로, 본)
    else:
        덩어리 = 문단쪼개기(경로, 본)
    return [(출처, _씻기(본문)) for 출처, 본문 in 덩어리]


def 절쪼개기(경로, 본):
    이름, 덩어리, 현재, 제목 = 문서이름(경로), [], [], None
    for 줄 in 본.splitlines():
        m = 마크다운머리.match(줄.strip())
        if m:
            if 현재 and 제목:
                덩어리.append(("%s / %s(%s)" % (이름, 제목, 제목), " ".join(현재)))
            제목, 현재 = m.group(2), []
        elif 줄.strip():
            현재.append(줄.strip())
    if 현재 and 제목:
        덩어리.append(("%s / %s(%s)" % (이름, 제목, 제목), " ".join(현재)))
    return 덩어리


def 문단쪼개기(경로, 본, 최소=40):
    이름 = 문서이름(경로)
    덩어리 = []
    for i, 조각 in enumerate(re.split(r"\n\s*\n", 본), 1):
        조각 = " ".join(조각.split())
        if len(조각) >= 최소:
            머리 = 조각[:24].strip()
            덩어리.append(("%s 문단%d(%s)" % (이름, i, 머리), 조각))
    return 덩어리


def 조문쪼개기(경로):
    """법령 텍스트를 조문 단위로."""
    이름 = 문서이름(경로)
    덩어리, 현재, 제목 = [], [], None
    번호 = None
    for 줄 in open(경로, encoding="utf-8"):
        줄 = 줄.strip()
        if not 줄 or 줄.startswith("#"):
            continue
        if _부칙시작.match(줄):
            번호 = None                 # 부칙부터는 담지 않는다
            continue
        줄 = _개정표기.sub(" ", 줄)
        if not 줄.strip():
            continue
        m = 조머리.match(줄)
        if m:
            if 현재 and 번호:
                덩어리.append(("%s 제%s조%s" % (이름, 번호, "(%s)" % 제목 if 제목 else ""),
                             " ".join(현재)))
            번호, 제목, 현재 = m.group(1), m.group(2), [줄]
        elif 번호:
            현재.append(줄)
    if 현재 and 번호:
        덩어리.append(("%s 제%s조%s" % (이름, 번호, "(%s)" % 제목 if 제목 else ""),
                     " ".join(현재)))
    return 덩어리


_kiwi = None


def 개념뽑기(문장):
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
    말들, 붙임 = set(), []
    끝 = -1

    def 담기():
        if 붙임:
            말들.add("".join(f for f, _ in 붙임))
            말들.update(f for f, 홀로 in 붙임 if 홀로 and len(f) >= 2)
        붙임.clear()

    for t in _kiwi.tokenize(문장):
        명사 = t.tag in ("NNG", "NNP", "SL")
        꼬리 = t.tag == "XSN" and bool(붙임)
        if not (명사 or 꼬리):
            담기()
            continue
        if 붙임 and t.start != 끝:
            담기()
            if not 명사:                      # 붙을 데가 없어진 접미사는 버린다
                continue
        붙임.append((t.form, 명사))
        끝 = t.start + t.len
    담기()
    return {w for w in 말들 if 2 <= len(w) <= 12 and w not in 버릴말 and not w.isdigit()}


_제목괄호 = re.compile(r"\(([^)]*)\)\s*$")


def 제목개념(출처):
    """'형법 제21조(정당방위)' -> {'정당방위'}.

    조문 제목은 그 조문의 주제다. 대칭적인 '같은조문' 보다 훨씬 많은 것을 말해준다 —
    무엇이 어디서 정의되는지, 그 조문이 무엇을 다루는지."""
    m = _제목괄호.search(출처)
    if not m:
        return set()
    말 = m.group(1)
    나옴 = set()
    for 조각 in re.split(r"[,·]|등의|에 관한|의 ", 말):
        조각 = 조각.strip()
        if 2 <= len(조각) <= 14 and 조각 not in 버릴말:
            나옴.add(조각)
    나옴 |= 개념뽑기(말)
    return {w for w in 나옴 if 2 <= len(w) <= 14 and w not in 버릴말}


_정의패턴 = [
    re.compile(r"[\"'“]?([가-힣A-Za-z]{2,14})[\"'”]?\s*(?:이란|란|이라 함은|라 함은|은|는)\s+(.{2,80}?)(?:을|를)\s*말한다"),
    re.compile(r"([가-힣A-Za-z]{2,14})\s*(?:이란|란)\s+(.{2,80}?)(?:이다|입니다)"),
]


def 개념망뽑기(고름, 자리, 홀로, 최대꼬리=6):
    """개념 사이의 상위-하위 관계를 자동으로 찾는다.

    두 가지 신호만 쓴다. 둘 다 검증 가능하다.

    1) 한국어 복합명사는 머리가 뒤에 온다. '멸치육수' 는 육수의 일종이고
       '방위행위의과잉' 은 과잉의 일종이다. 뒷부분이 그 자체로 개념이면
       접미 관계가 곧 상위 관계다. 사전도 모델도 필요 없다.
    2) 법령 제2조 같은 정의 조항: 'X 란 ... 을 말한다'.

    임베딩 유사도는 쓰지 않는다 — 비슷한 것과 상위인 것은 다르다.
    '김치찌개' 와 '된장찌개' 는 비슷하지만 어느 쪽도 다른 쪽의 상위가 아니다."""
    개념엣지, 본것 = [], set()
    빈도 = {w: len(자리[w]) for w in 고름}

    for a in 고름:
        if len(a) < 4:
            continue
        # 긴 꼬리부터 본다. '신주인수권부사채' 의 머리는 '채' 가 아니라 '사채' 다.
        for 꼬리 in range(min(len(a) - 1, 2 + 최대꼬리), 1, -1):
            b = a[-꼬리:]
            if b == a or b not in 고름 or (a, b) in 본것:
                continue
            # 진짜 상위어는 홀로도 쓰인다. '육수' 는 그 자체로 나오지만
            # '법시행당시' 는 '헌법시행당시' 안에서만 나온다 — 개념이 아니라 조각이다.
            # 빈도로 재면 둘이 같은 자리에만 나올 때 구별이 안 된다.
            # 근거는 둘 중 하나면 된다.
            #   홀로 쓰인 적이 있다  -> 그 자체로 개념이다
            #   더 자주 나온다        -> 상위어답게 넓게 쓰인다
            # 둘 다 아니면 '헌법시행당시' 속 '법시행당시' 같은 조각이다.
            if b not in 홀로 and 빈도[b] <= 빈도[a]:
                continue
            본것.add((a, b))
            개념엣지.append([a, "상위", b])
            break
    return 개념엣지


def 정의문뽑기(파일들, 고름):
    """정의 조항에서 'X 는 Y 를 말한다' 를 뽑는다."""
    나옴, 본것 = [], set()
    for f in 파일들:
        문서 = 문서이름(f)
        첫대목, 문서소개 = None, None
        for 출처, 본문 in 대목쪼개기(f):
            if 첫대목 is None:
                첫대목 = 출처
            # 법의 정의는 조문 안에 없고 제1조(목적)에 있다. 다만 그 앞에
            # '제1조 제1장 총칙' 같은 편·장 표시가 먼저 나오므로 제목이 있는 것을 고른다.
            if 문서소개 is None and "(" in 출처 and re.search(r"제\s*1\s*조", 출처):
                문서소개 = (출처, 본문)
            if "말한다" not in 본문 and "이란" not in 본문:
                continue
            for pat in _정의패턴:
                for m in pat.finditer(본문):
                    머리 = m.group(1).strip()
                    꼬리 = 개념뽑기(m.group(2))
                    if 머리 not in 고름:
                        continue
                    for b in 꼬리:
                        if b in 고름 and b != 머리 and (머리, b) not in 본것:
                            본것.add((머리, b))
                            나옴.append([머리, "정의", b])
    return 나옴


_문장끝 = re.compile(r"(?<=다)\.\s+|(?<=다)\.$|\n")


@lru_cache(maxsize=8192)
def _문장나누기(본문):
    """문장으로 자르되 괄호 안에서는 자르지 않는다.

    법령은 '제공(공유를 포함한다. 이하 같다)' 처럼 괄호 안에 문장을 넣는다.
    거기서 자르면 '제공(공유를 포함한다' 라는 반토막이 발췌로 남는다."""
    나옴 = []
    for 조각 in _문장끝.split(본문):
        조각 = " ".join((조각 or "").split())
        if not 조각:
            continue
        if 나옴 and 나옴[-1].count("(") > 나옴[-1].count(")"):
            나옴[-1] += ". " + 조각
        else:
            나옴.append(조각)
    return 나옴


def 발췌뽑기(말, 본문, 최대=190):
    """그 개념이 나오는 문장들을 원문에서 그대로 가져온다.

    하나만 저장하면 안 된다. 같은 개념이 여러 대목에 다른 정보로 나오기 때문이다 —
    '두부' 는 자기 절에서 '콩을 갈아 응고시킨 것' 이지만 김치찌개 절에서는
    '마지막에 넣어야 부서지지 않는다' 이다. '언제 넣어?' 에 정의를 주면 답이 아니다.
    고르는 일은 질문을 본 뒤에 한다."""
    문장들 = _문장나누기(본문)
    맞음 = [x for x in 문장들 if 말 in x] or 문장들[:1]
    나옴 = []
    for x in 맞음:
        if len(x) > 최대:
            # 자를 자리는 마지막 쉼표나 띄어쓰기. 낱말 중간에서 끊지 않는다.
            자름 = x[:최대]
            자름 = 자름[:max(자름.rfind(", "), 자름.rfind(" "))] or 자름
            x = 자름.rstrip(" ,") + "…"
        elif not x.endswith((".", "다", "요", "함", "음", "…")):
            x += "."
        나옴.append(x)
    return 나옴


# 벌칙·금액 조문은 문서 맨 뒤에 몰려 있다. 대목을 앞에서부터 담으면 절대 들어오지
# 않는다 — 저작권은 64개 대목에 나오고 벌칙은 제136조다. 그래서 '얼마를 처벌하나'
# 를 말하는 문장은 순서와 무관하게 한 줄씩 따로 챙긴다.
# 여기 표지는 지식.py 의 뜻표지(처벌/금액)와 짝이다. 한쪽만 고치면 안 된다.
갈래표지 = (("징역", "벌금", "과태료", "처한다", "구류", "몰수", "처벌한다"),
            ("만원", "원 이하", "원 이상", "100분의", "배 이하"))


def _갈래문장(말, 차례, 본문모음, 이미, 최대훑기=40):
    """그 개념에 대해 '어떻게 처벌하나' '얼마인가' 를 말하는 문장을 찾아 온다.

    그 개념의 이름이 든 문장만 받는다. 이름 없이 표지만 보면 아무 조문의
    '500만원 이하' 나 끌고 온다 — 실제로 음주운전에 교통안전교육기관 과태료가
    붙었다. 그래서 벌을 정한 줄이 각 호로 나뉘어 이름을 안 부르면 못 찾는다.
    저작권법 벌칙(제136조)이 그 경우다 — '저작재산권' 이라고만 쓴다."""
    나옴, 본것 = [], list(이미)
    for 표지 in 갈래표지:
        for 출처 in 차례[:최대훑기]:
            고름 = next((x for x in 발췌뽑기(말, 본문모음.get(출처, ""))
                         if 말 in x and any(t in x for t in 표지) and x not in 본것), None)
            if 고름:
                나옴.append({"글": 고름, "곳": 출처})
                본것.append(고름)
                break

    # 벌칙 조문은 머리에서 형을 정하고 각 호에서 무엇을 벌하는지 적는다.
    # '5년 이하의 징역' 이 든 줄에는 '저작권' 이 없다 — 위에서는 못 찾는다.
    # 제목이 벌칙인 조문에 한해, 그 조문이 이 개념을 다루면(그래서 차례에 있다)
    # 머리 문장을 받는다. 조문 이름이 답에 함께 나가므로 확인할 수 있다.
    if not any(any(t in x["글"] for t in 갈래표지[0]) for x in 나옴 + [{"글": y} for y in 이미]):
        # 벌칙은 문서 맨 뒤다. 여기서는 끝까지 훑는다 — 제목만 보므로 싸다.
        for 출처 in 차례:
            if not re.search(r"\((?:벌칙|과태료)[^)]*\)$", 출처):
                continue
            고름 = next((x for x in _문장나누기(본문모음.get(출처, ""))
                         if any(t in x for t in 갈래표지[0]) and x not in 본것), None)
            if 고름:
                나옴.append({"글": 고름[:190].rstrip() + ("…" if len(고름) > 190 else ""),
                            "곳": 출처})
                break
    return 나옴


def _발췌모으기(말, 나온곳, 정의처, 본문모음, 최대대목=8):
    """그 개념이 나온 대목들에서 문장을 모은다. 정의처를 앞에 둔다.

    4대목까지만 담았더니 '저작권 침해하면 처벌받아?' 에 벌칙 조문이 후보에도
    없었다 — 저작권은 64개 대목에 나오고 벌칙은 맨 뒤(제136조)다. 정의 조문들이
    앞자리를 다 차지한다. 고르는 일은 질문을 보고 하므로 후보는 넉넉해야 한다.

    넉넉해도 느려지지 않는다. 질문할 때 표지로 8개까지 추린 뒤에 인코딩한다 —
    비싼 것은 후보를 들고 있는 것이 아니라 인코딩이다."""
    차례 = list(정의처 or []) + [c for c in dict.fromkeys(나온곳)
                                 if c not in set(정의처 or [])]
    나옴 = []
    for 출처 in 차례[:최대대목]:
        for 문장 in 발췌뽑기(말, 본문모음.get(출처, ""))[:2]:
            if 문장 and 문장 not in [x["글"] for x in 나옴]:
                나옴.append({"글": 문장, "곳": 출처})
    return 나옴 + _갈래문장(말, 차례, 본문모음, [x["글"] for x in 나옴])


def 짓기(파일들, 최소=2, 엣지최소=2):
    자리 = defaultdict(list)
    조문별 = []
    정의 = defaultdict(list)          # 개념 -> 그것을 제목으로 단 조문들
    본문모음 = {}
    홀로 = set()                      # 원문에 그 말이 홀로(앞뒤가 한글이 아니게) 나온 적 있는 개념
    for f in 파일들:
        문서 = 문서이름(f)
        첫대목, 문서소개 = None, None
        for 출처, 본문 in 대목쪼개기(f):
            if 첫대목 is None:
                첫대목 = 출처
            # 법의 정의는 조문 안에 없고 제1조(목적)에 있다. 다만 그 앞에
            # '제1조 제1장 총칙' 같은 편·장 표시가 먼저 나오므로 제목이 있는 것을 고른다.
            if 문서소개 is None and "(" in 출처 and re.search(r"제\s*1\s*조", 출처):
                문서소개 = (출처, 본문)
            말들 = 개념뽑기(본문)
            제목 = 제목개념(출처) & 말들 or 제목개념(출처)
            말들 |= 제목
            조문별.append((출처, 말들, 제목))
            본문모음[출처] = 본문
            for w in 말들:
                if w in 홀로:
                    continue
                if re.search(r"(?<![가-힣])%s(?![가-힣])"
                             % re.escape(w), 본문):
                    홀로.add(w)
            for w in 말들:
                자리[w].append(출처)
            for w in 제목:
                정의[w].append(출처)
        # 법은 자기 이름을 거의 안 쓴다 — '상법' 원문에 '상법' 이 1회뿐이다.
        # 문서 이름은 물어볼 수 있는 대상이므로 개념으로 등록한다.
        if 첫대목 and 2 <= len(문서) <= 20:
            소개처 = 문서소개[0] if 문서소개 else 첫대목
            자리[문서].append(소개처)
            정의[문서].append(소개처)
            조문별[-1][1].add(문서)
            조문별[-1][2].add(문서)      # 제목 취급 — 한 번만 나와도 남는다

    # 제목으로 쓰인 개념은 한 번만 나와도 남긴다. 제목은 그 자체로 정의다 —
    # 해설서에서 '## 과잉방위' 한 절만 있어도 그것은 버릴 개념이 아니다.
    제목전체 = {w for _, _, 제목 in 조문별 for w in 제목}
    고름 = {w for w, v in 자리.items() if len(v) >= 최소} | (제목전체 & set(자리))
    문서수 = {w: len({_문서(c) for c in 자리[w]}) for w in 고름}

    쌍 = Counter()
    설명쌍 = Counter()
    for _, 말들, 제목 in 조문별:
        for 주 in sorted(제목 & 고름):
            for 부 in sorted((말들 - 제목) & 고름):
                설명쌍[(주, 부)] += 1
        같이 = sorted((말들 - 제목) & 고름)
        if len(같이) > 60:              # 조문 하나가 그래프를 지배하지 않게
            같이 = 같이[:60]
        for i in range(len(같이)):
            for j in range(i + 1, len(같이)):
                쌍[(같이[i], 같이[j])] += 1

    # Mne 의 explained(인쇄 + 발화) 에 해당하는 신호: 특정 법에 몰려 있는가.
    # 14개 법에 다 나오는 '청구' 는 맞는 말이지만 정보가 없다.
    총문서 = len({_문서(c) for v in 자리.values() for c in v})
    import math

    def 점수(w):
        빈도 = len(자리[w])
        퍼짐 = math.log(총문서 / max(문서수[w], 1) + 1)   # 한 문서에 몰릴수록 높다
        길이 = 1.0 + 0.12 * max(len(w) - 2, 0)           # 복합어를 조금 우대
        return round(빈도 * 퍼짐 * 길이, 1)

    노드 = {}
    메타 = {}
    for w in 고름:
        노드[w] = [w]
        법별 = Counter(_문서(c) for c in 자리[w])
        대표법 = 법별.most_common(1)[0][0]
        대표조 = next(c for c in 자리[w] if c.startswith(대표법))
        메타[w] = {"community": 대표법,
                   "file": 대표조, "loc": None, "type": "법률개념",
                   "무게": 점수(w), "빈도": len(자리[w]), "문서수": 문서수[w],
                   "정의처": sorted(set(정의.get(w, [])))[:4],
                   "발췌": _발췌모으기(w, 자리[w], 정의.get(w), 본문모음),
                   "출처": [c for c, _ in Counter(자리[w]).most_common(6)],
                   "법별": 법별.most_common(4)}
    엣지 = [[a, "설명함", b] for (a, b), w in 설명쌍.most_common() if w >= 1]
    엣지 += [[a, "같은조문", b] for (a, b), w in 쌍.most_common() if w >= 엣지최소]
    개념엣지 = 개념망뽑기(고름, 자리, 홀로) + 정의문뽑기(파일들, 고름)
    return {"역할": "안내", "목표": None, "설명그래프": True,
            "개념엣지": 개념엣지,
            "임계값": {"A_MIN": 0.45, "OK_MIN": 0.58},
            "노드": 노드, "메타": 메타, "엣지": 엣지, "무관층": {},
            "조문수": len(조문별)}


def _자가검사():
    """개념을 붙이는 규칙 두 가지가 살아 있는지."""
    있다 = 개념뽑기("저작권을 침해한 자는 음주운전 방지장치를 부착한다")
    assert "저작권" in 있다, 있다          # 접미사(권)에서 끊기지 않는다
    assert "음주운전" in 있다, 있다        # 붙어 있는 것은 붙인다
    assert "권" not in 있다                # 접미사 혼자는 개념이 아니다
    assert not any(len(w) > 8 for w in 있다), 있다   # 공백을 넘어 붙이지 않는다
    assert 개념뽑기("정당방위 규정") == {"정당방위"}
    print("selfcheck ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _자가검사()
        sys.exit(0)
    최소 = int(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 2
    인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
    폴더 = 인자[0] if 인자 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "자료/법지식")
    나감 = (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv
            else os.path.join(폴더, "지식그래프.json"))
    파일 = sorted(glob.glob(os.path.join(폴더, "*.txt"))
                  + glob.glob(os.path.join(폴더, "*.md")))
    # 폴더 설명서는 지식이 아니다. README 가 코퍼스에 섞이면 그 안의 예시가
    # 개념의 정의처로 잡힌다 — 실제로 README 가 '정당방위' 를 가로챘다.
    파일 = [f for f in 파일
            if not os.path.basename(f).lower().startswith(("readme", "_", "."))]
    if not 파일:
        print("%s 안에 .txt 나 .md 가 없습니다." % 폴더)
        sys.exit(1)
    g = 짓기(파일, 최소=최소)
    json.dump(g, open(나감, "w", encoding="utf-8"), ensure_ascii=False)
    print("문서 %d개 · 대목 %d개" % (len(파일), g["조문수"]))
    상 = sum(1 for e in g["개념엣지"] if e[1] == "상위")
    print("개념 %d개 · 엣지 %d개 · 개념망 %d개(상위 %d · 정의 %d) -> %s"
          % (len(g["노드"]), len(g["엣지"]), len(g["개념엣지"]), 상,
             len(g["개념엣지"]) - 상, 나감))
    상위 = sorted(g["메타"].items(), key=lambda kv: -kv[1]["무게"])[:12]
    print("\n가장 많이 나오는 개념:")
    for w, m in 상위:
        print("  %7.1f  %-14s  %3d회 · 문서 %d개  %s"
              % (m["무게"], w, m["빈도"], m["문서수"], m["출처"][0]))
