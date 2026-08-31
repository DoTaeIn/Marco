# -*- coding: utf-8 -*-
"""언어중립 알고리즘을 언어별 말투로 찍어내고, 실제로 돌려서 채점한다.

이 파일이 하는 일은 설명.py 가 경로를 한국어나 영어로 뽑는 것과 **같은
연산**이다. 내용(알고리즘)과 표현(문법)을 갈라두면 표현은 갈아끼우면 된다.
말투/한국어.json 이 있는 자리에 말투/코드/python.json 이 있을 뿐이다.

고르기가 아니라 짓기다. 자료에 없던 조합도 나온다 — 이진검색은 러스트로
쓴 적이 없어도 러스트 말투만 있으면 뽑힌다.

그리고 이 도메인에는 **검증자가 공짜다.** 돌려보면 맞았는지 알 수 있다.
문장은 사람이 봐줘야 하지만 코드는 아니다. 창작 루프를 여기서 먼저 만드는
이유가 그것이다.
"""
import io
import json
import os
import subprocess
import sys
import tempfile

여기 = os.path.dirname(os.path.abspath(__file__))


def _길(p):
    return p if os.path.isabs(p) else os.path.join(여기, p)


def 말투읽기(언어):
    return json.load(io.open(_길("말투/코드/%s.json" % 언어), encoding="utf-8"))


def 알고읽기(경로):
    return json.load(io.open(_길(경로), encoding="utf-8"))


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


def 회귀(폴더="알고리즘", 언어들=None):
    """있는 알고리즘 전부를 있는 언어 전부로 찍어 돌린다.

    N개 알고리즘 x M개 언어 = N*M 벌이고, 사람이 쓴 것은 N + M 벌뿐이다.
    나머지는 이 파일이 지었다. 자료에 없던 조합도 돈다 — 그것이 고르기와
    짓기의 차이다."""
    if 언어들 is None:
        언어들 = sorted(x[:-5] for x in os.listdir(_길("말투/코드"))
                        if x.endswith(".json"))
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
    알 = 알고읽기("알고리즘/이진검색.json")
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
    지 = 짓기(알고읽기("알고리즘/최대공약수.json"), 말투읽기("powershell"))
    assert "(gcd $b ($a % $b))" in 지, 지    # 부르는 자리 구분자가 다르다
    print("selfcheck ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _자체검사()
        sys.exit(0)
    인자 = [x for x in sys.argv[1:] if not x.startswith("--")]
    if "--regress" in sys.argv:
        산, 전 = 회귀()
        sys.exit(0 if 산 == 전 else 1)
    언어들 = 인자[1:] or ["python", "javascript", "java"]
    알고 = 알고읽기(인자[0] if 인자 else "알고리즘/이진검색.json")
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
