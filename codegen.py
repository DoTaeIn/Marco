# -*- coding: utf-8 -*-
"""언어중립 알고리즘을 언어별 말투로 찍어내고, 실제로 돌려서 채점한다.

이 파일이 하는 일은 설명.py 가 경로를 한국어나 영어로 뽑는 것과 **같은
연산**이다. 내용(알고리즘)과 표현(문법)을 갈라두면 표현은 갈아끼우면 된다.
styles/한국어.json 이 있는 자리에 styles/코드/python.json 이 있을 뿐이다.

고르기가 아니라 짓기다. 자료에 없던 조합도 나온다 — 이진검색은 러스트로
쓴 적이 없어도 러스트 말투만 있으면 뽑힌다.

그리고 이 도메인에는 **검증자가 공짜다.** 돌려보면 맞았는지 알 수 있다.
문장은 사람이 봐줘야 하지만 코드는 아니다. 창작 루프를 여기서 먼저 만드는
이유가 그것이다.
"""
import copy
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile

여기 = os.path.dirname(os.path.abspath(__file__))


def _길(p):
    return p if os.path.isabs(p) else os.path.join(여기, p)


def 말투읽기(언어):
    return json.load(io.open(_길("styles/코드/%s.json" % 언어), encoding="utf-8"))


def 말투들():
    return sorted(x[:-5] for x in os.listdir(_길("styles/코드"))
                  if x.endswith(".json"))


def 알고읽기(경로):
    return json.load(io.open(_길(경로), encoding="utf-8"))


_조사짝 = {"을": ("을", "를"), "이": ("이", "가"), "은": ("은", "는"),
           "와": ("과", "와"), "으로": ("으로", "로")}
_표 = re.compile(r"\{~(을|이|은|와|으로)\}")


def _받침(글, 자리):
    """조사 앞 글자에 받침이 있나. 닫는 괄호와 빈칸은 건너뛴다 —
    'target(정수)' 뒤에 붙는 조사는 '수' 를 보고 골라야 한다."""
    i = 자리 - 1
    while i >= 0 and 글[i] in ") ]\"'":
        i -= 1
    if i < 0:
        return True
    c = 글[i]
    if "가" <= c <= "힣":
        return (ord(c) - 0xAC00) % 28 != 0
    if c.isdigit():
        return c in "01367"          # 영 일 삼 육 칠 팔 에 받침이 있다
    return c.lower() not in "aeiouy"  # 로마자는 소리로 가른다


def _조사맞춤(글):
    """{~을} 같은 자리를 앞 글자에 맞춰 을/를로 굳힌다."""
    while True:
        m = _표.search(글)
        if not m:
            return 글
        있, 없 = _조사짝[m.group(1)]
        골 = 있 if _받침(글, m.start()) else 없
        글 = 글[:m.start()] + 골 + 글[m.end():]


def _틀변형(틀):
    """읽을 때는 둘 다 받는다. 사람은 '정수를' 이라 쓰고 틀은 '정수을'
    이라 적혀 있어도 같은 말이다."""
    m = _표.search(틀)
    if not m:
        return [틀]
    난 = []
    for 골 in _조사짝[m.group(1)]:
        난 += _틀변형(틀[:m.start()] + 골 + 틀[m.end():])
    return 난


def _채움(틀, **칸):
    """{이름} 같은 자리를 채운다. str.format 을 안 쓰는 이유는 틀 안에
    중괄호가 있기 때문이다 — 자바와 JS 의 블록이 그것이다."""
    for k, v in 칸.items():
        틀 = 틀.replace("{%s}" % k, v)
    return 틀


def _들여(글, 말투, 겹=1):
    칸 = 말투["들여쓰기"] * 겹
    return "\n".join(칸 + 줄 if 줄.strip() else 줄 for 줄 in 글.split("\n"))


def _인자사이(말투):
    return 말투.get("인자사이") or 말투["입력사이"]


def 식내기(말투, 식):
    """식을 낸다. 잎(이름·수)은 값 그대로, 나머지는 재귀."""
    꼴 = 식[0]
    if 꼴 == "부름":
        # 부르는 자리의 구분자는 선언하는 자리와 다를 수 있다. 파워셸이
        # 그렇다 — 선언은 f($a, $b) 인데 부르기는 f $a $b 이고, 식 안에서는
        # 괄호로 싸야 한다. C 계열만 보면 안 보이던 가정이었다.
        인자 = _인자사이(말투).join(식내기(말투, x) for x in 식[2:])
        return _채움(말투.get("호출식") or 말투["호출"], 이름=식[1], 인자=인자)
    틀 = 말투["식"].get(꼴)
    if 틀 is None:
        raise KeyError("%s 말투에 식 '%s' 이(가) 없다" % (말투["이름"], 꼴))
    if 꼴 in ("이름", "수"):
        조각 = [str(식[1])]
    else:
        조각 = [식내기(말투, x) for x in 식[1:]]
    for i, c in enumerate(조각):
        틀 = 틀.replace("{%d}" % i, c)
    return 틀


def 문내기(말투, 문):
    """한 문장. 블록을 안는 문은 몸을 한 겹 들여 안에 박는다."""
    꼴 = 문[0]
    if 꼴 == "선언":
        _, 이름, 형, 식 = 문
        return _채움(말투["선언"], 이름=이름, 형=말투["형"][형],
                     식=식내기(말투, 식))
    if 꼴 == "대입":
        return _채움(말투["대입"], 이름=문[1], 식=식내기(말투, 문[2]))
    if 꼴 == "색인대입":
        return _채움(말투["색인대입"], 열=식내기(말투, 문[1]),
                     자리=식내기(말투, 문[2]), 식=식내기(말투, 문[3]))
    if 꼴 == "반환":
        return _채움(말투["반환"], 식=식내기(말투, 문[1]))
    if 꼴 == "반복":
        return _채움(말투["반복"], 조건=식내기(말투, 문[1]),
                     몸=몸내기(말투, 문[2]))
    if 꼴 == "분기":
        아니면 = 문[3] if len(문) > 3 else []
        if 아니면:
            return _채움(말투["분기아니면"], 조건=식내기(말투, 문[1]),
                         몸=몸내기(말투, 문[2]), 아니면=몸내기(말투, 아니면))
        return _채움(말투["분기"], 조건=식내기(말투, 문[1]),
                     몸=몸내기(말투, 문[2]))
    raise KeyError("모르는 문 '%s'" % 꼴)


def 몸내기(말투, 문들):
    return "\n".join(_들여(문내기(말투, f), 말투) for f in 문들)


def _값내기(말투, v):
    if isinstance(v, list):
        항목 = ", ".join(_값내기(말투, x) for x in v)
        return _채움(말투["열"], 항목=항목)
    return str(v)


def 짓기(알고, 말투):
    """알고리즘 하나를 그 언어의 소스 한 벌로."""
    입력 = 말투["입력사이"].join(
        _채움(말투["입력항"], 이름=n, 형=말투["형"][t]) for n, t in 알고["입력"])
    함수 = _채움(말투["함수"], 이름=알고["이름"], 입력=입력,
                 반환형=말투["형"][알고["반환형"]], 몸=몸내기(말투, 알고["몸"]))
    시험 = []
    for c in 알고.get("시험", ()):
        인자 = _인자사이(말투).join(_값내기(말투, v) for v in c["인자"])
        호출 = _채움(말투["호출"], 이름=알고["이름"], 인자=인자)
        # 열은 언어마다 찍는 꼴이 달라(파이썬 [1, 2] · JS [1,2] · 자바 주소)
        # 그대로는 견줄 수 없다. 쉼표로 이은 한 줄로 맞춘다.
        틀 = (말투["열시험줄"] if 알고["반환형"] == "정수열"
              else 말투["시험줄"])
        시험.append(_채움(틀, 호출=호출))
    함수 = _조사맞춤(함수)
    시험 = [_조사맞춤(x) for x in 시험]
    깊 = 말투.get("겉들여쓰기", 0)
    시깊 = 말투.get("시험들여쓰기", 0)
    return _채움(말투["겉"],
                 함수들=_들여(함수, 말투, 깊) if 깊 else 함수,
                 시험=_들여("\n".join(시험), 말투, 시깊) if 시깊
                 else "\n".join(시험))


def 돌리기(알고, 언어, 남길=None):
    """찍어서 실제로 돌리고 기댓값과 견준다. 검증자는 실행이다."""
    말투 = 말투읽기(언어)
    소스 = 짓기(알고, 말투)
    터 = 남길 or tempfile.mkdtemp(prefix="kgbuild_")   # 한글 경로는 자바가 깨먹는다
    이름 = 말투.get("파일이름") or 알고["이름"]
    경로 = os.path.join(터, "%s.%s" % (이름, 말투["확장자"]))
    io.open(경로, "w", encoding="utf-8").write(소스)
    명령 = [x.replace("{파일}", 경로) for x in 말투["실행"]]
    try:
        p = subprocess.run(명령, capture_output=True, text=True, timeout=60)
    except Exception as e:                      # 실행기가 없을 수 있다
        return {"언어": 언어, "소스": 소스, "탈": str(e), "맞": 0,
                "전체": len(알고.get("시험", ()))}
    if p.returncode != 0:
        return {"언어": 언어, "소스": 소스, "탈": (p.stderr or "")[:400],
                "맞": 0, "전체": len(알고.get("시험", ()))}
    난것 = [x.strip() for x in p.stdout.strip().split("\n") if x.strip()]
    기대 = [str(c["기대"]) for c in 알고.get("시험", ())]
    맞 = sum(1 for a, b in zip(난것, 기대) if a == b)
    return {"언어": 언어, "소스": 소스, "탈": None, "맞": 맞, "전체": len(기대),
            "난것": 난것, "기대": 기대}


def 재기(알고, 언어들):
    셈 = []
    for 언 in 언어들:
        r = 돌리기(알고, 언)
        셈.append(r)
        표 = "O" if r["탈"] is None and r["맞"] == r["전체"] else "X"
        print("  %s %-12s %d/%d %s"
              % (표, 언, r["맞"], r["전체"],
                 ("← " + r["탈"].strip().split("\n")[0][:90]) if r["탈"] else ""))
    return 셈


def 회귀(폴더="algorithms", 언어들=None):
    """있는 알고리즘 전부를 있는 언어 전부로 찍어 돌린다.

    N개 알고리즘 x M개 언어 = N*M 벌이고, 사람이 쓴 것은 N + M 벌뿐이다.
    나머지는 이 파일이 지었다. 자료에 없던 조합도 돈다 — 그것이 고르기와
    짓기의 차이다."""
    if 언어들 is None:
        언어들 = [x for x in 말투들() if not 말투읽기(x).get("산문")]
    산, 전 = 0, 0
    for f in sorted(os.listdir(_길(폴더))):
        if not f.endswith(".json"):
            continue
        알고 = 알고읽기(os.path.join(폴더, f))
        print("%s — %s" % (알고["이름"], 알고.get("설명", "")))
        for r in 재기(알고, list(언어들)):
            전 += 1
            산 += (r["탈"] is None and r["맞"] == r["전체"])
        print()
    print("돌아가는 벌 %d/%d (%.0f%%)" % (산, 전, 100.0 * 산 / max(전, 1)))
    return 산, 전


def _자체검사():
    """찍기만 보는 검사. 실행기가 없는 데서도 돈다."""
    알 = 알고읽기("algorithms/이진검색.json")
    파 = 짓기(알, 말투읽기("python"))
    assert "def binary_search(a, target):" in 파, 파
    assert "(lo + hi) // 2" in 파, 파
    자 = 짓기(알, 말투읽기("java"))
    assert "static int binary_search(int[] a, int target)" in 자, 자
    assert "(lo + hi) / 2" in 자 and "//" not in 자, 자
    피 = 짓기(알, 말투읽기("powershell"))
    assert "$lo -le $hi" in 피, 피
    # 같은 내용이 말투만 갈려 나온다 - 한국어/영어와 같은 연산이다.
    for 글 in (파, 자, 피):
        assert 글.count("return") >= 2, 글
    지 = 짓기(알고읽기("algorithms/최대공약수.json"), 말투읽기("powershell"))
    assert "(gcd $b ($a % $b))" in 지, 지    # 부르는 자리 구분자가 다르다
    # 왕복 - 찍은 산문을 도로 뜯으면 처음 설계도가 그대로 나와야 한다
    한 = 말투읽기("한국어")
    뜯 = 알고뜯기(한, 짓기(알, 한))
    for k in ("이름", "입력", "반환형", "몸"):
        assert 뜯[k] == 알[k], (k, 뜯[k])
    print("selfcheck ok")


# ── 거꾸로: 산문에서 설계도를 뜯어낸다 ──────────────────────────────
#
# 찍는 데 쓴 틀을 그대로 뒤집어 쓴다. 틀이 하나뿐이니 찍기와 읽기가 어긋날
# 수 없다 — 어긋나면 왕복이 깨져서 바로 안다.
#
# 왕복이 곧 채점기다. 설계도 → 한국어 → 설계도 → 코드 → 실행 을 돌려
# 답이 그대로 맞으면 제대로 읽은 것이다. 사람이 봐줄 필요가 없다.


def _쪼개(틀):
    """틀을 글자 조각과 구멍으로 가른다. '({0}이 {1}과 같으)' 는
    ['(', '이 ', '과 같으)'] 와 ['0', '1'] 이 된다."""
    조각, 구멍, 남 = [], [], 틀
    while True:
        i = 남.find("{")
        if i < 0:
            조각.append(남)
            return 조각, 구멍
        j = 남.index("}", i)
        조각.append(남[:i])
        구멍.append(남[i + 1:j])
        남 = 남[j + 1:]


def _맞춰(틀, 글):
    if "{~" in 틀:
        for x in _틀변형(틀):
            m = _맞춰(x, 글)
            if m is not None:
                return m
        return None
    return _맞춰하나(틀, 글)


def _맞춰하나(틀, 글):
    """글을 틀에 맞춰 구멍의 내용을 뽑는다. 없으면 None.

    괄호 깊이를 센다. 안 세면 '((a의 mid번째)이 target과 같으)' 에서
    안쪽 괄호의 글자가 바깥 틀의 글자로 잘못 걸린다."""
    조각, 구멍 = _쪼개(틀)
    if not 글.startswith(조각[0]):
        return None
    자리, 값 = len(조각[0]), []
    for k in range(1, len(조각)):
        찾을 = 조각[k]
        깊이, 여기, 찾음 = 0, 자리, -1
        while 여기 < len(글):
            # 맞춰본 뒤에 깊이를 옮긴다. 먼저 옮기면 여는 괄호로 시작하는
            # 조각('(' 하나짜리)이 제 자리에서 안 걸린다.
            if 깊이 == 0 and 찾을 and 글.startswith(찾을, 여기):
                찾음 = 여기
                break
            c = 글[여기]
            if c == "(":
                깊이 += 1
            elif c == ")":
                깊이 -= 1
                if 깊이 < 0:
                    return None
            여기 += 1
        if 찾을 == "":                      # 마지막 조각이 비면 끝까지
            찾음 = len(글)
        if 찾음 < 0 or 찾음 <= 자리:
            return None
        값.append(글[자리:찾음])
        자리 = 찾음 + len(찾을)
    if 자리 != len(글):
        return None
    return dict(zip(구멍, 값)) if 구멍 else {}


def 식뜯기(말투, 글):
    """산문 한 토막을 식으로. 잎이 아니면 반드시 괄호로 싸여 있다."""
    글 = 글.strip()
    if not 글.startswith("("):
        try:
            return ["수", int(글)]
        except ValueError:
            return ["이름", 글]
    부름틀 = 말투.get("호출식")
    if 부름틀:
        m = _맞춰(부름틀, 글)
        if m and "이름" in m:
            인자 = _깊이나누기(m["인자"], _인자사이(말투))
            return ["부름", m["이름"]] + [식뜯기(말투, x) for x in 인자]
    for 꼴, 틀 in 말투["식"].items():
        if 꼴 in ("이름", "수"):
            continue
        m = _맞춰(틀, 글)
        if m is not None:
            차례 = sorted(m, key=int)
            return [꼴] + [식뜯기(말투, m[k]) for k in 차례]
    raise ValueError("못 읽는 식: %s" % 글)


def _깊이나누기(글, 사이):
    """괄호 밖에서만 가른다."""
    깊이, 자리, 난 = 0, 0, []
    i = 0
    while i < len(글):
        c = 글[i]
        if c == "(":
            깊이 += 1
        elif c == ")":
            깊이 -= 1
        if 깊이 == 0 and 글.startswith(사이, i):
            난.append(글[자리:i])
            i += len(사이)
            자리 = i
            continue
        i += 1
    난.append(글[자리:])
    return [x for x in 난 if x.strip()]


def _벗기(줄들, 칸):
    return [x[len(칸):] if x.startswith(칸) else x for x in 줄들]


def 몸뜯기(말투, 줄들):
    """들여쓰기로 블록을 가른다. 찍을 때 쓴 그 들여쓰기다."""
    칸 = 말투["들여쓰기"]
    몸, i = [], 0
    while i < len(줄들):
        줄 = 줄들[i]
        if not 줄.strip():
            i += 1
            continue
        속 = []
        j = i + 1
        while j < len(줄들) and (줄들[j].startswith(칸) or not 줄들[j].strip()):
            속.append(줄들[j])
            j += 1
        속 = _벗기(속, 칸)

        머리 = 말투["반복"].split("\n")[0]
        m = _맞춰(머리, 줄)
        if m is not None:
            몸.append(["반복", 식뜯기(말투, m["조건"]), 몸뜯기(말투, 속)])
            i = j
            continue
        머리 = 말투["분기"].split("\n")[0]
        m = _맞춰(머리, 줄)
        if m is not None:
            그럼 = 몸뜯기(말투, 속)
            아니면 = []
            가름 = 말투["분기아니면"].split("\n")[2]
            if j < len(줄들) and 줄들[j].strip() == 가름.strip():
                k = j + 1
                안 = []
                while k < len(줄들) and (줄들[k].startswith(칸)
                                         or not 줄들[k].strip()):
                    안.append(줄들[k])
                    k += 1
                아니면 = 몸뜯기(말투, _벗기(안, 칸))
                j = k
            몸.append(["분기", 식뜯기(말투, m["조건"]), 그럼, 아니면])
            i = j
            continue
        for 꼴 in ("선언", "색인대입", "대입", "반환"):   # 좁은 틀을 먼저
            m = _맞춰(말투[꼴], 줄)
            if m is None:
                continue
            if 꼴 == "선언":
                몸.append(["선언", m["이름"], "정수", 식뜯기(말투, m["식"])])
            elif 꼴 == "대입":
                몸.append(["대입", m["이름"], 식뜯기(말투, m["식"])])
            elif 꼴 == "색인대입":
                몸.append(["색인대입", 식뜯기(말투, m["열"]),
                           식뜯기(말투, m["자리"]), 식뜯기(말투, m["식"])])
            else:
                몸.append(["반환", 식뜯기(말투, m["식"])])
            break
        else:
            raise ValueError("못 읽는 줄: %s" % 줄)
        i += 1
    return 몸


def 알고뜯기(말투, 글):
    """산문 한 벌을 설계도로.

    '시험: [5] -> 120' 줄은 따로 걷는다. 무엇을 하는지는 산문이
    말하지만 무엇이 맞는지는 말하지 않는다 — 그건 채점기의 몫이다."""
    줄들, 시험 = [], []
    for 줄 in 글.rstrip().split(chr(10)):
        if 줄.strip().startswith("시험:"):
            왼, _, 오 = 줄.split(":", 1)[1].partition("->")
            오 = 오.strip()
            시험.append({"인자": json.loads(왼.strip()),
                         "기대": json.loads(오)
                         if 오[:1] in "-0123456789[" else 오})
        else:
            줄들.append(줄)
    while 줄들 and not 줄들[-1].strip():
        줄들.pop()
    머리 = 말투["함수"].split("\n")[0]
    m = _맞춰(머리, 줄들[0].strip())
    if m is None:
        raise ValueError("머리를 못 읽는다: %s" % 줄들[0])
    거꾸로형 = {v: k for k, v in 말투["형"].items()}
    입력 = []
    for t in _깊이나누기(m["입력"], 말투["입력사이"]):
        s = _맞춰(말투["입력항"], t.strip())
        if s is None:
            raise ValueError("입력을 못 읽는다: %s" % t)
        입력.append([s["이름"], 거꾸로형.get(s["형"], s["형"])])
    알고 = {"이름": m["이름"], "입력": 입력,
            "반환형": 거꾸로형.get(m["반환형"], m["반환형"]),
            "몸": 몸뜯기(말투, _벗기(줄들[1:], 말투["들여쓰기"])),
            "시험": 시험}
    # 산문에는 변수의 형이 안 적힌다. 길이·색인을 받는 이름은 열이다.
    열이름 = set(n for n, t in 입력 if t == "정수열")
    _형채우기(알고["몸"], 열이름)
    return 알고


def _형채우기(몸, 열이름):
    for 문 in 몸:
        if 문[0] == "선언":
            문[2] = "정수열" if (문[3][0] == "이름"
                                 and 문[3][1] in 열이름) else "정수"
        for x in 문:
            if isinstance(x, list) and x and isinstance(x[0], list):
                _형채우기(x, 열이름)


def 산문회귀(폴더="algorithms/산문", 언어="한국어"):
    """사람이 손으로 쓴 한국어를 그대로 코드로 만들어 돌린다.

    왕복과 다르다. 왕복은 제가 찍은 산문을 도로 읽는 것이라 문체가 제
    것이다. 여기 든 글은 사람이 쓴 것이고 조사도 사람 마음대로다 —
    '정수를' 이라 써도 틀에는 '정수을' 이라 적혀 있다."""
    말투 = 말투읽기(언어)
    쓸언어 = [x for x in 말투들()
              if x != 언어 and not 말투읽기(x).get("산문")]
    산, 벌 = 0, 0
    터 = _길(폴더)
    if not os.path.isdir(터):
        return 0, 0
    for f in sorted(os.listdir(터)):
        if not f.endswith(".txt"):
            continue
        글 = io.open(os.path.join(터, f), encoding="utf-8").read()
        try:
            알고 = 알고뜯기(말투, 글)
        except Exception as e:
            print("  X %-20s 못 읽음 — %s" % (f, e))
            벌 += len(쓸언어)
            continue
        print("%s ← %s" % (알고["이름"], f))
        for r in 재기(알고, 쓸언어):
            벌 += 1
            산 += (r["탈"] is None and r["맞"] == r["전체"])
        print()
    print("  사람이 쓴 한국어에서 도는 벌 %d/%d" % (산, 벌))
    return 산, 벌


def 왕복(폴더="algorithms", 언어="한국어"):
    """설계도 → 산문 → 설계도. 그리고 뜯어낸 것으로 코드를 찍어 돌린다.

    앞의 견줌이 읽기가 맞았는지 보고, 뒤의 실행이 그 읽은 것이 진짜 도는
    물건인지 본다. 둘 다 사람 없이 매겨진다."""
    말투 = 말투읽기(언어)
    같, 전, 산, 벌 = 0, 0, 0, 0
    쓸언어 = [x for x in 말투들()
              if x != 언어 and not 말투읽기(x).get("산문")]
    for f in sorted(os.listdir(_길(폴더))):
        if not f.endswith(".json"):
            continue
        원 = 알고읽기(os.path.join(폴더, f))
        산문 = 짓기(원, 말투)
        전 += 1
        try:
            뜯 = 알고뜯기(말투, 산문)
        except Exception as e:
            print("  X %-14s 못 읽음 — %s" % (원["이름"], e))
            continue
        꼭 = ["이름", "입력", "반환형", "몸"]
        맞 = all(뜯[k] == 원[k] for k in 꼭)
        같 += 맞
        print("  %s %-14s 왕복 %s" % ("O" if 맞 else "X", 원["이름"],
                                      "같음" if 맞 else "다름"))
        if not 맞:
            for k in 꼭:
                if 뜯[k] != 원[k]:
                    print("      %s: %s" % (k, json.dumps(뜯[k],
                                                          ensure_ascii=False)[:160]))
            continue
        뜯["시험"] = 원.get("시험", [])       # 시험은 산문에 안 적힌다
        for r in 재기(뜯, 쓸언어):
            벌 += 1
            산 += (r["탈"] is None and r["맞"] == r["전체"])
    print()
    print("  왕복 같음 %d/%d · 뜯은 설계도로 찍어 도는 벌 %d/%d"
          % (같, 전, 산, 벌))
    return 같, 전, 산, 벌


# ── 생각: 머릿속으로 셈하고, 틀리면 고쳐서 다시 ────────────────────
#
# 토큰 기반 AI 의 생각은 토큰 하나씩 고르며 되풀이하는 것이다. 우리의
# 생각은 이 단계들을 오가며 되풀이하는 것이다. 다른 점은 뒤지는 자리다 —
# 토큰 공간은 5만 차원이고 설계도 공간은 작고 구조가 있다.
#
# 뒤지려면 빨라야 한다. 매번 파이썬을 띄우면 한 번에 50ms 라 생각을 몇 번
# 못 한다. 그래서 설계도를 머릿속에서 바로 셈한다. 답이 나오면 그때 진짜
# 언어로 찍어 돌려 확인한다 — 머릿속 셈이 틀렸을 수도 있으니.


class _돌아옴(Exception):
    def __init__(self, 값):
        self.값 = 값


def 셈하기(알고, 인자, 벽=200000):
    """설계도를 그 자리에서 셈한다. 벽은 무한 되풀이를 끊는다."""
    남 = [벽]

    def 식(e, 방):
        꼴 = e[0]
        if 꼴 == "이름":
            return 방[e[1]]
        if 꼴 == "수":
            return e[1]
        if 꼴 == "부름":
            return 셈하기(알고, [식(x, 방) for x in e[2:]], 남[0])
        a = 식(e[1], 방)
        if 꼴 == "길이":
            return len(a)
        b = 식(e[2], 방)
        if 꼴 == "색인":
            return a[b]
        if 꼴 == "더하기":
            return a + b
        if 꼴 == "빼기":
            return a - b
        if 꼴 == "곱하기":
            return a * b
        if 꼴 == "몫":
            return a // b
        if 꼴 == "나머지":
            return a % b
        if 꼴 == "==":
            return a == b
        if 꼴 == "<":
            return a < b
        if 꼴 == "<=":
            return a <= b
        if 꼴 == ">":
            return a > b
        raise KeyError(꼴)

    def 몸(문들, 방):
        for f in 문들:
            남[0] -= 1
            if 남[0] <= 0:
                raise TimeoutError("벽")
            꼴 = f[0]
            if 꼴 in ("선언", "대입"):
                방[f[1]] = 식(f[-1], 방)
            elif 꼴 == "색인대입":
                식(f[1], 방)[식(f[2], 방)] = 식(f[3], 방)
            elif 꼴 == "반환":
                raise _돌아옴(식(f[1], 방))
            elif 꼴 == "반복":
                while 식(f[1], 방):
                    남[0] -= 1
                    if 남[0] <= 0:
                        raise TimeoutError("벽")
                    몸(f[2], 방)
            elif 꼴 == "분기":
                몸(f[2] if 식(f[1], 방) else (f[3] if len(f) > 3 else []), 방)
            else:
                raise KeyError(꼴)

    방 = {n: (list(v) if isinstance(v, list) else v)
          for (n, _t), v in zip(알고["입력"], 인자)}
    try:
        몸(알고["몸"], 방)
    except _돌아옴 as r:
        return r.값
    return None


def 머릿속점수(알고, 끊기=False):
    """머릿속으로만 채점한다. 실행기를 안 띄우니 1000배 빠르다.

    뒤질 때는 만점인지만 알면 되므로 첫 실패에서 끊는다. 후보 대부분은
    첫 시험에서 떨어지니 이것만으로 시험 수에 안 끌려간다."""
    맞 = 0
    for c in 알고.get("시험", ()):
        try:
            난 = 셈하기(알고, copy.deepcopy(c["인자"]))
        except Exception:
            if 끊기:
                return 맞
            continue
        기대 = c["기대"]
        if isinstance(난, list):
            난 = ", ".join(str(x) for x in 난)
        if str(난) != str(기대):
            if 끊기:
                return 맞
            continue
        맞 += 1
    return 맞


_바꿈 = {"<": ("<=",), "<=": ("<",), ">": ("<", "<="), "==": ("<", ">"),
         "더하기": ("빼기",), "빼기": ("더하기",)}


def _경로들(몸, 앞=()):
    """설계도 안의 모든 마디 자리. 여기가 고칠 수 있는 자리다."""
    for i, x in enumerate(몸):
        if not isinstance(x, list):
            continue
        yield 앞 + (i,)
        for p in _경로들(x, 앞 + (i,)):
            yield p


def _짚기(몸, 경로):
    x = 몸
    for i in 경로:
        x = x[i]
    return x


def 이웃(알고):
    """한 군데만 고친 설계도들. 흔한 잘못을 되돌리는 손질만 한다 —
    하나 차이(0/1), 부등호 갈아끼우기, 더하기/빼기 뒤집기."""
    for 경로 in list(_경로들(알고["몸"])):
        마디 = _짚기(알고["몸"], 경로)
        if not 마디 or not isinstance(마디[0], str):
            continue
        꼴 = 마디[0]
        고침 = []
        if 꼴 == "수" and isinstance(마디[1], int):
            고침 = [("수", 마디[1] + 1), ("수", 마디[1] - 1)]
        elif 꼴 in _바꿈:
            고침 = [(x, None) for x in _바꿈[꼴]]
        for 새꼴, 새값 in 고침:
            벌 = copy.deepcopy(알고)
            m = _짚기(벌["몸"], 경로)
            m[0] = 새꼴
            if 새값 is not None:
                m[1] = 새값
            yield 벌, "%s → %s%s" % (꼴, 새꼴,
                                     "" if 새값 is None else " %s" % 새값)


def 고치기(알고, 깊이=2, 벽=4000):
    """틀렸으면 고쳐서 다시. 이것이 이 엔진의 생각이다.

    채점기가 공짜라서 뒤질 수 있다. 사람한테 물어볼 필요가 없다.
    돌려주는 것은 (고친 설계도, 손질 자취) 이고, 못 고치면 (None, 시도수).
    """
    만점 = len(알고.get("시험", ()))
    if not 만점:
        return None, 0
    if 머릿속점수(알고, True) == 만점:
        return 알고, []
    본것 = {json.dumps(알고["몸"], ensure_ascii=False)}
    앞줄 = [(알고, [])]
    셈 = 0
    for _ in range(깊이):
        다음 = []
        for 후보, 자취 in 앞줄:
            for 벌, 말 in 이웃(후보):
                열쇠 = json.dumps(벌["몸"], ensure_ascii=False)
                if 열쇠 in 본것:
                    continue
                본것.add(열쇠)
                셈 += 1
                if 셈 > 벽:
                    return None, 셈
                if 머릿속점수(벌, True) == 만점:
                    return 벌, 자취 + [말]
                다음.append((벌, 자취 + [말]))
        앞줄 = 다음
    return None, 셈


def 부수기(알고, 몇, 난수):
    """일부러 망가뜨린다. 고치기를 재려면 고칠 것이 있어야 한다."""
    벌 = copy.deepcopy(알고)
    for _ in range(몇):
        후보 = list(이웃(벌))
        if not 후보:
            return None
        벌 = 난수.choice(후보)[0]
    만점 = len(알고.get("시험", ()))
    return 벌 if 머릿속점수(벌, True) < 만점 else None


def 고침회귀(폴더="algorithms", 몇벌=8, 씨=7, 스스로시험=12):
    """망가뜨린 설계도를 혼자 고쳐내는가. 그리고 고친 것이 진짜로 도는가.

    두 가지를 갈라 센다.
      통과    시험을 다 맞히는 무언가를 찾았다.
      복구    그것이 원본과 글자 그대로 같다.
    둘이 크게 벌어지면 시험이 프로그램을 못 묶고 있다는 뜻이다. 사람이
    쓴 시험 셋으로는 통과 94%에 복구 56% 였다. 제가 지은 시험 열둘을
    보태면 복구가 75%로 오른다 - 시험은 사람 없이 늘릴 수 있다.
    """
    난수 = random.Random(씨)
    산, 똑, 전 = 0, 0, 0
    확인 = None
    for f in sorted(os.listdir(_길(폴더))):
        if not f.endswith(".json"):
            continue
        알고 = 알고읽기(os.path.join(폴더, f))
        if 스스로시험:
            지은 = 시험짓기(알고, 스스로시험)
            if len(지은) >= 5:
                알고 = dict(알고, 시험=알고.get("시험", []) + 지은)
        원 = json.dumps(알고["몸"], ensure_ascii=False)
        for 깊 in (1, 2):
            난 = 0
            for _ in range(몇벌 * 6):
                if 난 >= 몇벌:
                    break
                깨 = 부수기(알고, 깊, 난수)
                if 깨 is None:
                    continue
                난 += 1
                전 += 1
                고친, _자취 = 고치기(깨, 깊이=깊)
                if 고친 is None:
                    continue
                산 += 1
                똑 += (json.dumps(고친["몸"], ensure_ascii=False) == 원)
                if 확인 is None:
                    확인 = (알고, 고친)
    print("  망가뜨린 설계도 %d벌 → 통과 %d (%.0f%%) · 원본 복구 %d (%.0f%%)"
          % (전, 산, 100.0 * 산 / max(전, 1), 똑, 100.0 * 똑 / max(전, 1)))

    # 머릿속 셈이 맞았는지는 진짜로 돌려봐야 안다.
    돎 = 0
    if 확인:
        원알, 고친 = 확인
        고친 = dict(고친, 시험=원알.get("시험", [])[:3] or 원알["시험"][:3])
        쓸 = [x for x in 말투들() if not 말투읽기(x).get("산문")]
        print("  고친 설계도를 진짜 언어로 찍어 돌린다 (%s):" % 고친["이름"])
        for r in 재기(고친, 쓸):
            돎 += (r["탈"] is None and r["맞"] == r["전체"])
    return 산, 똑, 전, 돎


def 시험짓기(알고, 몇=20, 씨=3):
    """제가 제 시험을 짓는다. 아무 값이나 넣고 머릿속으로 돌린 답을 적는다.

    사람이 시험을 세 개밖에 안 써주면 그 셋만 통과하는 딴 프로그램이
    수두룩하다 — 고치기가 88% 통과하는데 원본 복구는 64% 였다. 시험은
    많을수록 프로그램을 좁게 묶는다. 그리고 이건 사람 없이 늘릴 수 있다."""
    난수 = random.Random(씨)
    난것 = []
    for _ in range(몇 * 4):
        if len(난것) >= 몇:
            break
        인자 = []
        for _n, t in 알고["입력"]:
            if t == "정수열":
                인자.append([난수.randint(-20, 20)
                             for _ in range(난수.randint(1, 7))])
            else:
                인자.append(난수.randint(0, 30))
        try:
            답 = 셈하기(알고, copy.deepcopy(인자), 20000)
        except Exception:
            continue
        if 답 is None:
            continue
        if isinstance(답, list):
            답 = ", ".join(str(x) for x in 답)
        난것.append({"인자": 인자, "기대": 답})
    return 난것


if __name__ == "__main__":
    if "--check" in sys.argv:
        _자체검사()
        sys.exit(0)
    인자 = [x for x in sys.argv[1:] if not x.startswith("--")]
    if "--고치기" in sys.argv:
        산, 똑, 전, 돎 = 고침회귀()
        sys.exit(0 if (전 and 산 and 돎) else 1)
    if "--산문" in sys.argv:
        산, 벌 = 산문회귀()
        sys.exit(0 if (벌 and 산 == 벌) else 1)
    if "--왕복" in sys.argv:
        같, 전, 산, 벌 = 왕복()
        sys.exit(0 if (같 == 전 and 산 == 벌) else 1)
    if "--읽기" in sys.argv:
        말투 = 말투읽기("한국어")
        글 = io.open(_길(인자[0]), encoding="utf-8").read()
        print(json.dumps(알고뜯기(말투, 글), ensure_ascii=False, indent=2))
        sys.exit(0)
    if "--regress" in sys.argv:
        산, 전 = 회귀()
        sys.exit(0 if 산 == 전 else 1)
    언어들 = 인자[1:] or ["python", "javascript", "java"]
    알고 = 알고읽기(인자[0] if 인자 else "algorithms/이진검색.json")
    if "--show" in sys.argv:
        for 언 in 언어들:
            print("=" * 60)
            print("# %s" % 언)
            print(짓기(알고, 말투읽기(언)))
        sys.exit(0)
    print("%s — %s" % (알고["이름"], 알고.get("설명", "")))
    셈 = 재기(알고, 언어들)
    산 = sum(1 for r in 셈 if r["탈"] is None and r["맞"] == r["전체"])
    print()
    print("  %d/%d 언어에서 돈다" % (산, len(셈)))
