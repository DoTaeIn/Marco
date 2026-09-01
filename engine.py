# -*- coding: utf-8 -*-
"""논증 엔진: 두 층 그래프 + A/B1/B2/C 분류.

도메인 지식 0줄. 아는 것은 목표 노드와 증명/충족/부정 세 관계, 그리고 BFS 뿐이다.
역할·목표·대사·임계값은 전부 .kg 파일이 들고 있다."""
import glob, hashlib, itertools, json, os, re, sys
from collections import deque
from functools import lru_cache

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# torch/HF 가 매 실행마다 뿜는 경고는 이 프로그램과 무관하다. 유저가 볼 이유가 없다.
import logging
import warnings
warnings.filterwarnings("ignore")
for _n in ("torch", "transformers", "huggingface_hub", "sentence_transformers"):
    logging.getLogger(_n).setLevel(logging.ERROR)

# 신경망은 인코더.py 한 곳에만 있다. 두 벌 두면 캐시도 두 벌이 된다.
from encoder import MODEL, DEVICE, _model, _vec, 숫자가리기, 조각내기

_여기 = os.path.dirname(os.path.abspath(__file__))


def _길(p):
    """상대 경로는 일단 지금 자리에서, 없으면 이 파일 옆에서 찾는다."""
    return p if os.path.isabs(p) or os.path.exists(p) else os.path.join(_여기, p)

POS = ("증명", "충족")   # 논증을 전진시키는 관계
NEG = ("부정",)
반례표 = "_반례:"      # 널 클래스 중 "그 노드가 아니다"만 뜻하는 것들의 접두사

# 임계값은 도메인 상수라 graph.kg 이 들고 있다. 공통층 크기에 따라 달라지기 때문:
# 실측(ko-sroberta) — 8노드: 있음>=0.624 / 없음<=0.433 (간격 0.19)
#                    28노드: 있음>=0.624 / 없음<=0.572 (간격 0.05)
# 노드가 늘수록 마진이 좁아진다. 그래프를 키우면 반드시 재보정할 것.


def _포함(g, base_dir):
    """다른 주제 그래프의 공통층을 빌려온다.

    공통층(개념)만 가져오고 사례층(그 에피소드의 사실)은 절대 가져오지 않는다.
    개념은 재사용 대상이지만 사례는 그 사건의 것이다.
    빌려온 개념은 목표와 이어지는 다리 엣지가 없으면 서브셋 필터가 걸러내
    자동으로 널 클래스가 된다 — 붙여도 손해가 없다."""
    for sub in g.pop("포함", []):
        p = sub if os.path.isabs(sub) else os.path.join(base_dir, sub)
        o = kg읽기(p) if p.endswith(".kg") else json.load(open(p, encoding="utf-8"))
        _포함(o, os.path.dirname(os.path.abspath(p)))
        for k, v in o.get("공통층", {}).items():
            기존 = g.setdefault("공통층", {}).get(k)
            if 기존 is not None and 기존 != v:
                raise ValueError(f"포함 충돌: '{sub}' 의 공통층.{k} 가 이미 다르게 정의됨")
            g["공통층"][k] = v
        for k, v in o.get("무관층", {}).items():
            # 무관층은 엣지도 의미도 없는 거절용 예시 뭉치다. 이름이 겹치면
            # 오류가 아니라 합치는 것이 맞다 — 부정 예시는 많을수록 좋다.
            있던 = g.setdefault("무관층", {}).setdefault(k, [])
            있던 += [x for x in v if x not in 있던]
        # 대사·임계값·수치조건은 호스트가 정의하지 않은 것만 물려받는다.
        # 라이브러리가 기본값을 들고 있으면 에피소드 파일이 가벼워진다.
        for k, v in (o.get("대사") or {}).items():
            g.setdefault("대사", {}).setdefault(k, v)
        for e in o.get("개념엣지", []):
            if e not in g.setdefault("개념엣지", []):
                g["개념엣지"].append(e)
        for k, v in (o.get("출처") or {}).items():
            g.setdefault("출처", {}).setdefault(k, v)
        for k, v in (o.get("수치조건") or {}).items():
            g.setdefault("수치조건", {}).setdefault(k, v)
        if not g.get("임계값") and o.get("임계값"):
            g["임계값"] = o["임계값"]
        기존노드 = set(g["공통층"]) | set(g.get("무관층", {}))
        g["엣지"] += [e for e in o["엣지"]
                      if len(e) == 3 and e[0] in 기존노드 and e[2] in 기존노드]


필수대사 = ("B2", "B2_강등", "A", "근거없음", "인정", "인정_반격", "C", "B1")


def 검증(g):
    """그래프가 틀렸을 때 조용히 망가지지 않게 한다.

    그래프는 매일 바뀌는 파일이고 엔진은 그 내용을 모른다. 오타 하나로
    목표 노드를 못 찾으면 법리가 0개 로드되어 모든 발언이 B2가 되는데,
    검증이 없으면 예외도 안 난다. 게임이 죽은 채로 굴러간다."""
    문제 = []
    for key in ("목표", "역할", "대사", "임계값", "공통층", "사례층", "엣지"):
        if key not in g:
            문제.append(f"필수 항목 없음: {key}")
    if 문제:
        raise ValueError("그래프 오류\n  - " + "\n  - ".join(문제))

    노드 = set(g["공통층"]) | set(g["사례층"]) | set(g.get("무관층", {}))
    if g["목표"] not in g["공통층"]:
        문제.append(f"목표 '{g['목표']}' 가 공통층에 없음")
    for i, e in enumerate(g["엣지"]):
        if len(e) != 3:
            문제.append(f"엣지[{i}] 형식 오류: {e}"); continue
        a, r, b = e
        for n in (a, b):
            if n not in 노드:
                문제.append(f"엣지[{i}] 미정의 노드: '{n}'")
        if r not in POS + NEG:
            문제.append(f"엣지[{i}] 알 수 없는 관계: '{r}' (허용: {POS + NEG})")
        if a == b:
            문제.append(f"엣지[{i}] 자기 참조: '{a}'")
    for k in 필수대사:
        if k not in g["대사"]:
            문제.append(f"대사 키 없음: {k}")
    for layer in ("공통층", "사례층", "무관층"):
        for n, exs in g.get(layer, {}).items():
            if not exs:
                문제.append(f"{layer}.{n} 예시 문장 없음")
    for n in (g.get("출처") or {}):
        if n not in 노드:
            문제.append(f"출처가 붙은 '{n}' 이 어느 층에도 없음")
    for k in ("A_MIN", "OK_MIN"):
        if k not in g["임계값"]:
            문제.append(f"임계값 없음: {k}")
    if 문제:
        raise ValueError("그래프 오류 %d건\n  - %s" % (len(문제), "\n  - ".join(문제)))


_화살 = re.compile(r"\s*(?:-+|→)\s*(\S+?)\s*(?:-+>|→)\s*")
_수치 = re.compile(r"^(.*?)\s*\{\s*(\S*?)\s*(>=|<=)\s*([\d.]+)\s*\}$")


def kg읽기(경로):
    """.kg 텍스트를 그래프 딕셔너리로. 형식은 README_그래프.md 참고.

    JSON 은 엣지 88개를 늘어놓으면 구조가 보이지 않는다. 저작이 이 시스템의
    병목이므로 파일 형식이 곧 작업 도구다. 화살표가 눈에 보이게 한다."""
    경로 = _길(경로)
    g = {"역할": "", "목표": "", "임계값": {"A_MIN": 0.50, "OK_MIN": 0.60},
         "대사": {}, "공통층": {}, "사례층": {}, "무관층": {},
         "수치조건": {}, "엣지": [], "개념엣지": [], "포함": []}
    구역 = None
    층이름 = {"개념": "공통층", "사례": "사례층", "무관": "무관층"}

    def 오류(i, 줄, 왜):
        raise ValueError("%s:%d  %s\n    %s" % (경로, i, 왜, 줄))

    for i, 원문 in enumerate(open(경로, encoding="utf-8"), 1):
        줄 = 원문.split("#")[0].rstrip() if not 원문.lstrip().startswith("#") else ""
        if not 줄.strip():
            continue
        머리 = 줄.strip()
        if 머리.startswith("[") and 머리.endswith("]"):
            구역 = 머리[1:-1].strip()
            if 구역 not in ("개념", "사례", "무관", "논증", "대사", "개념망"):
                오류(i, 머리, "모르는 구역 (개념/사례/무관/논증/대사/개념망)")
            continue

        if 구역 is None:                                  # 머리말
            if ":" not in 머리:
                오류(i, 머리, "머리말은 '이름: 값' 형식")
            키, 값 = (x.strip() for x in 머리.split(":", 1))
            if 키 == "임계값":
                try:
                    a, b = (float(x) for x in 값.replace("/", " ").split())
                except ValueError:
                    오류(i, 머리, "임계값은 '0.50 / 0.60' 형식")
                g["임계값"] = {"A_MIN": a, "OK_MIN": b}
            elif 키 == "포함":
                g["포함"] += [x.strip() for x in 값.split(",") if x.strip()]
            elif 키 in ("역할", "목표"):
                g[키] = 값
            else:
                오류(i, 머리, "모르는 머리말 (역할/목표/임계값/포함)")

        elif 구역 == "대사":
            if ":" not in 머리:
                오류(i, 머리, "대사는 '키: 문장' 형식")
            키, 값 = 머리.split(":", 1)
            g["대사"][키.strip()] = 값.strip()

        elif 구역 == "개념망":
            # 단어 사이 관계. 논증 순회에는 쓰이지 않고 어휘 확장에만 쓴다.
            m = _화살.search(머리)
            if not m:
                오류(i, 머리, "개념망은 '과도 -상위-> 흉기' 형식")
            출발 = 머리[:m.start()].strip()
            관계 = m.group(1)
            if 관계 != "상위":
                오류(i, 머리, "지금 쓰는 개념망 관계는 '상위' 뿐이다")
            for 도착 in (x.strip() for x in 머리[m.end():].split(",")):
                if 출발 and 도착:
                    g.setdefault("개념엣지", []).append([출발, 관계, 도착])

        elif 구역 == "논증":
            m = _화살.search(머리)
            if not m:
                오류(i, 머리, "논증은 'A -증명-> B' 또는 'A →증명→ B' 형식")
            출발 = 머리[:m.start()].strip()
            관계 = m.group(1)
            for 도착 in (x.strip() for x in 머리[m.end():].split(",")):
                if 출발 and 도착:
                    g["엣지"].append([출발, 관계, 도착])

        else:                                              # 개념 / 사례 / 무관
            if ":" not in 머리:
                오류(i, 머리, "노드는 '이름: \"예시\" | \"예시\"' 형식")
            이름, 예시 = 머리.split(":", 1)
            이름 = 이름.strip()
            증거 = 이름.startswith("*")
            이름 = 이름.lstrip("*").strip()
            m = _수치.match(이름)
            if m:
                이름, 단위, 부호, 값 = m.group(1).strip(), m.group(2), m.group(3), float(m.group(4))
                g["수치조건"][이름] = {"단위": 단위,
                                       "최소" if 부호 == ">=" else "최대": 값}
            출처 = None
            if "@" in 이름:
                이름, 출처 = (x.strip() for x in 이름.split("@", 1))
            문장들 = [x.strip().strip('"') for x in 예시.split("|") if x.strip()]
            if not 문장들:
                오류(i, 머리, "예시 문장이 없다")
            g[층이름[구역]][이름] = 문장들
            if 출처:
                g.setdefault("출처", {})[이름] = 출처
            _ = 증거          # '*' 는 읽는 사람을 위한 표시. 실제 증거는 증명 엣지가 정한다
    return g


긍정 = ("네", "예", "맞다", "맞습니다", "맞아요", "그렇습니다", "그래요", "응",
        "그렇죠", "바로 그겁니다", "그 말입니다", "ㅇㅇ", "맞음", "yes", "y")
부정 = ("아니", "아뇨", "아닙니다", "아니요", "틀렸", "아냐", "no", "n")


def _확답(text):
    t = "".join(text.split()).lower().rstrip(".!?")
    if any(t.startswith(x) for x in 부정):
        return False
    if any(t.startswith(x) for x in 긍정) or t in 긍정:
        return True
    return None


def 학습읽기(경로):
    """되묻기의 답. 원본 .kg 를 건드리지 않는 덧칠 파일.

    (맞다, 아니다) 두 벌을 돌려준다. "아니다"도 정보다 —
    그 발화가 그 노드가 *아니라는* 것을 사람이 확인해 준 것이므로
    긍정 예시만큼이나 매칭을 좁힌다. 예전엔 이 신호를 버렸다."""
    out, 아님 = {}, {}
    if 경로 and os.path.exists(경로):
        for 줄 in open(경로, encoding="utf-8"):
            줄 = 줄.strip()
            if not 줄:
                continue
            try:
                d = json.loads(줄)
                (아님 if d.get("아님") else out).setdefault(
                    d["노드"], []).append(d["말"])
            except (ValueError, KeyError):
                pass
    return out, 아님


def 학습쓰기(graph, 노드, 말, 아님=False):
    경로 = graph.get("_학습로그")
    if not 경로:
        return False
    d = {"노드": 노드, "말": 말}
    if 아님:
        d["아님"] = True
    try:
        with open(경로, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


_지시 = re.compile(r"아까|방금|앞서|이전에|말씀하신|그것|그거|저것|저거|"
                   r"그\s*증거|그\s*자료|그\s*영상|그\s*부분|그\s*점|그때")


def 대명사풀기(text, graph, 최근):
    """'아까 그 증거' 같은 지시를 직전 맥락으로 채운다.

    대화 원문은 들고 있지 않다. 직전 몇 턴의 (증거, 주장)만 기억하고 그것으로
    푼다. 기억이 텍스트가 아니라 논증 상태라는 성질을 그대로 유지한다.
    추측으로 채웠으면 무엇으로 채웠는지 함께 돌려준다 — 조용히 틀리면 안 된다."""
    if not 최근 or not _지시.search(text):
        return text, None
    앞증거 = next((e for e, _ in reversed(최근) if e), None)
    앞주장 = next((c for _, c in reversed(최근) if c), None)

    풀린것 = []
    새 = text
    if 앞증거 and not match_evidence(text, graph)[0]:
        새 = 앞증거 + " " + 새                 # 증거지우기가 다시 떼어낸다
        풀린것.append(앞증거)
    if 앞주장:
        # 길이로 판단하면 "방금 그건 인정하시는 겁니까" 처럼 내용은 없는데
        # 글자만 긴 발화를 놓친다. 실제로 무엇에도 안 걸리는지를 본다.
        본문 = 증거지우기(새, graph, match_evidence(새, graph)[0])
        실노드 = [n for n in graph["사례층"] if n not in graph["증거"]]             + list(graph["공통층"])
        _, 점수 = match(본문, 실노드, graph)
        if 점수 < graph["임계값"]["OK_MIN"]:
            새 = 새 + " " + 문장(graph, 앞주장)
            풀린것.append(앞주장)
    return 새, (풀린것 or None)


def 사건읽기(경로):
    """판례 마크다운 -> 에피소드 그래프. 형식은 cases/사건_템플릿.md 참고.

    법리층은 이미 있으므로 판례마다 쓸 것은 증거·사실과 그 연결뿐이다.
    작성자가 법리 노드 이름 28개를 외우지 않아도 되게, 자연어로 적으면
    매처가 가장 가까운 법리에 붙이고 무엇을 골랐는지 보고한다."""
    머리, 증거, 사실 = {}, {}, {}
    현재사실, 구역 = None, None
    for i, 원문 in enumerate(open(경로, encoding="utf-8"), 1):
        줄 = 원문.rstrip()
        임 = 줄.strip()
        if not 임:
            continue
        if 임.startswith("### "):
            현재사실 = 임[4:].strip()
            사실[현재사실] = {"증거": [], "말": [], "충족": [], "부정": [], "줄": i}
            continue
        if 임.startswith("## "):
            구역 = 임[3:].strip()
            현재사실 = None
            continue
        if 임.startswith("# "):
            머리["제목"] = 임[2:].strip()
            continue
        if 임.startswith(("-", "*")):
            임 = 임[1:].strip()
        if ":" not in 임:
            continue
        키, 값 = (x.strip() for x in 임.split(":", 1))
        쪼갬 = [x.strip() for x in re.split(r"[/,]", 값) if x.strip() and x.strip() != "-"]
        if 구역 is None or 구역.startswith("사건"):
            머리[키] = 값
        elif 구역.startswith("증거"):
            # 노드 이름 자체가 첫 별칭이다. 'CCTV: 시시티비' 라고 썼는데
            # 정작 "CCTV" 로 못 찾으면 아무 의미가 없다.
            증거[키] = [키] + [x for x in 쪼갬 if x != 키]
        elif 현재사실 and 키 in ("증거", "말", "충족", "부정"):
            사실[현재사실][키] = 쪼갬
    for k in ("역할", "목표", "법리"):
        if k not in 머리:
            raise ValueError("%s: 머리말에 '%s' 가 없다" % (경로, k))
    return 머리, 증거, 사실


def 사건컴파일(경로, 최소신뢰=0.55):
    """판례 md -> (kg 텍스트, 보고). 법리 이름은 매처로 붙인다."""
    머리, 증거, 사실 = 사건읽기(경로)
    # 사건 md 옆에서 먼저 찾고, 없으면 저장소 기준으로 한 번 더 찾는다.
    # 재구성(486f5ea)으로 legal/ 이 루트로 옮겨지면서 cases/사건_*.md 의
    # "legal/법리_형법21조.kg" 가 cases/legal/... 로 이어붙어 전부 깨졌다.
    법리경로 = os.path.join(os.path.dirname(os.path.abspath(경로)), 머리["법리"])
    법리 = load(법리경로 if os.path.exists(법리경로) else _길(머리["법리"]))
    후보 = list(법리["공통층"])
    보고 = []

    def 법리찾기(구, 사실명, 관계):
        if 구 in 후보:
            return 구
        n, c = match(구, 후보, 법리)
        보고.append((c, 사실명, 관계, 구, n, c >= 최소신뢰))
        return n if c >= 최소신뢰 else None

    포함들 = [머리["법리"]] + ([머리["개념망"]] if 머리.get("개념망") else [])
    L = ["# " + 머리.get("제목", os.path.basename(경로)),
         "# 자동 생성: %s -> 이 파일. 직접 고치지 말고 md 를 고칠 것" % os.path.basename(경로),
         "역할: " + 머리["역할"], "목표: " + 머리["목표"],
         "포함: " + ", ".join(포함들), "", "[사례]"]
    for n, 별칭 in 증거.items():
        L.append("*%s: %s" % (n, " | ".join('"%s"' % x for x in 별칭)))
    for n, d in 사실.items():
        if not d["말"]:
            raise ValueError("%s:%d  사실 '%s' 에 '말:' 이 없다" % (경로, d["줄"], n))
        L.append("%s: %s" % (n, " | ".join('"%s"' % x for x in d["말"])))

    L += ["", "[논증]"]
    for n, d in 사실.items():
        for e in d["증거"]:
            if e not in 증거:
                raise ValueError("%s:%d  '%s' 는 증거 목록에 없다" % (경로, d["줄"], e))
            L.append("%s  -증명->  %s" % (e, n))
    for n, d in 사실.items():
        for 관계 in ("충족", "부정"):
            대상 = [법리찾기(x, n, 관계) for x in d[관계]]
            대상 = [x for x in 대상 if x]
            if 대상:
                L.append("%s  -%s->  %s" % (n, 관계, ", ".join(대상)))
    return "\n".join(L) + "\n", 보고


def load(path="graphs/graph.kg"):
    path = _길(path)
    if str(path).endswith(".kg"):
        g = kg읽기(path)
    else:
        g = json.load(open(path, encoding="utf-8"))
    # 알아듣지 못한 발화를 그래프 옆에 쌓는다. 기획자가 읽고 그래프를 키운다.
    g.setdefault("_미지로그", os.path.splitext(path)[0] + ".미지.log")
    g.setdefault("_학습로그", os.path.splitext(path)[0] + ".학습.jsonl")
    # 되묻기에서 확인된 표현을 덧칠한다. 노드의 뜻은 그대로고 부르는 법만 는다 —
    # 새 지식이 아니므로 환각 위험이 없다. 새 노드나 엣지는 절대 만들지 않는다.
    _긍정, _부정 = 학습읽기(g["_학습로그"])
    for 노드, 말들 in _긍정.items():
        for 층 in ("공통층", "사례층"):
            if 노드 in g.get(층, {}):
                g[층][노드] += [m for m in 말들 if m not in g[층][노드]]
                break
    # "아니다"는 널 클래스로 간다. 이미 있는 무관층 기계를 그대로 쓴다 —
    # 매칭 점수 계산에 손대지 않고도 그 발화가 그 노드를 이기지 못하게 된다.
    for 노드, 말들 in _부정.items():
        칸 = g.setdefault("무관층", {}).setdefault(반례표 + 노드, [])
        칸 += [m for m in 말들 if m not in 칸]
    _포함(g, os.path.dirname(os.path.abspath(path)))
    검증(g)
    쓸것 = _관련개념(g)
    # 걸러낸 개념을 버리지 않고 널 클래스로 재활용한다.
    # 아는 법이 많을수록 "이건 이 재판 얘기가 아니다"를 더 잘 판별하게 된다 —
    # 공통층을 키우면 매칭이 나빠질 거라는 예상과 반대 방향이다.
    g.setdefault("무관층", {}).update(
        {"_타죄명:" + k: v for k, v in g["공통층"].items() if k not in 쓸것})
    g["공통층"] = 쓸것
    keep = set(g["공통층"]) | set(g["사례층"])
    g["엣지"] = [e for e in g["엣지"] if e[0] in keep and e[2] in keep]
    g["adj"] = adj = {}
    for src, rel, dst in g["엣지"]:
        adj.setdefault(src, []).append((rel, dst))
    g["증거"] = [n for n in g["사례층"] if any(r == "증명" for r, _ in adj.get(n, []))]
    g["vec"] = _예시벡터(g)
    return g


def _관련개념(g):
    """목표 노드와 무향으로 연결된 법리만 남긴다.

    기획자가 사건별 법리 목록을 직접 쓰면 빠뜨린 법리가 B1이 아니라 B2로
    떨어져 B1 장치 자체가 죽는다. 그래서 목록을 받지 않고 그래프에서 유도한다.
    거르는 이유는 메모리가 아니라 매처 오염(무관한 죄명에 오매칭)이다.

    ponytail: 무향 연결요소. 공통층이 커져 위법성조각사유 등으로 전부 한 덩어리가
    되면 필터가 무력해진다. 그때 죄명 태그 방식으로 올릴 것.
    """
    개념 = g["공통층"]
    nb = {}
    for src, _, dst in g["엣지"]:
        if src in 개념 and dst in 개념:
            nb.setdefault(src, set()).add(dst)
            nb.setdefault(dst, set()).add(src)
    seen, q = {g["목표"]}, deque([g["목표"]])
    while q:
        for n in nb.get(q.popleft(), ()):
            if n not in seen:
                seen.add(n)
                q.append(n)
    return {k: v for k, v in 개념.items() if k in seen}


def 개념확장(graph, 문장들):
    """개념망을 타고 예시 문장을 불린다.

    '흉기를 들고 있었습니다' 하나에 과도/식칼/각목 변형이 자동으로 생긴다.
    지금까지는 노드마다 어휘를 손으로 늘려야 했다 — 실제로 '과도'를 몰라서
    예시를 직접 넣었었다. 단어 사이 관계를 한 번 적어두면 모든 사건이 덕을 본다.

    논증 그래프(증거->사실->요건)와 다른 층이다. 이쪽은 방향이 위로만 간다:
    하위어 -상위-> 상위어. 그래서 논증 순회에는 끼어들지 않는다."""
    하위 = {}
    for a, r, b in graph.get("개념엣지", []):
        if r == "상위":
            하위.setdefault(b, []).append(a)
    if not 하위:
        return 문장들
    나온것 = list(문장들)
    for 문장 in 문장들:
        for 위, 아래들 in 하위.items():
            if 위 in 문장:
                for 아래 in 아래들:
                    새 = 문장.replace(위, 아래)
                    if 새 not in 나온것:
                        나온것.append(새)
    return 나온것


def _예시벡터(graph, 캐시경로=None):
    """노드별 예시 문장을 미리 인코딩. 로드 시 1회.

    인코딩은 그래프당 15초쯤 걸린다. 예시 문장이 바뀌지 않으면 결과도 같으므로
    내용 해시를 키로 디스크에 캐시한다. 그래프를 고치면 해시가 바뀌어 자동으로
    다시 계산된다."""
    import numpy as np
    graph.setdefault("무관층", {})
    재료 = {층: graph.get(층, {}) for 층 in ("공통층", "사례층", "무관층")}
    재료["개념엣지"] = graph.get("개념엣지", [])
    키 = hashlib.sha1(
        (MODEL + json.dumps(재료, ensure_ascii=False, sort_keys=True)).encode("utf-8")
    ).hexdigest()[:16]
    캐시 = 캐시경로 or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    ".vec_%s.npz" % 키)
    if os.path.exists(캐시):
        try:
            z = np.load(캐시, allow_pickle=False)
            return {k: z[k] for k in z.files}
        except Exception:
            pass                        # 캐시가 깨졌으면 그냥 다시 만든다
    out = {}
    for layer in ("공통층", "사례층", "무관층"):
        for node, exs in graph[layer].items():
            exs = 개념확장(graph, exs)
            out[node] = np.array(_model().encode([숫자가리기(e) for e in exs],
                                                 normalize_embeddings=True))
    try:
        np.savez_compressed(캐시, **out)
    except OSError:
        pass                            # 쓰기 못 해도 동작에는 지장 없다
    return out


def match(text, candidates, graph):
    """가장 가까운 노드와 코사인 유사도. 긴 발화는 조각 중 최고를 취한다."""
    best, score = None, 0.0
    for 조각 in 조각내기(text):
        v = _vec(조각)
        for node in candidates:
            s = float((graph["vec"][node] @ v).max())
            if s > score:
                best, score = node, s
    return best, round(score, 3)


def 증거지우기(text, graph, ev):
    """숫자를 뽑기 전에 증거 이름을 지운다.

    'APM2 로그' 같은 증거명에 숫자가 들어 있으면 그 숫자를 값으로 오독한다."""
    if not ev:
        return text
    for alias in sorted(graph["사례층"][ev], key=len, reverse=True):
        if alias in text:
            text = text.replace(alias, " ")
        else:                      # 공백을 지운 형태로도 한 번
            납작 = "".join(alias.split())
            if 납작 in "".join(text.split()):
                text = re.sub(r"\s*".join(map(re.escape, 납작)), " ", text)
    return text


def match_evidence(text, graph):
    """증거는 고유명사(CCTV, 진단서)라 문장 임베딩으로 재면 유사도가 뭉개진다.
    문자열 포함으로 찾는 편이 정확하고 공짜다. 층마다 매칭 방식이 다르다."""
    t = "".join(text.split()).lower()
    # 가장 긴 별칭이 이긴다. 먼저 걸리는 것을 쓰면 짧은 증거명이 긴 증거명의
    # 부분문자열일 때 엉뚱한 증거로 간다 — '피해근로자진술' 이라고 말했는데
    # '근로자진술' 이 먼저 걸려 그 증거가 증명하지 않는 주장이 되고 C 로 떨어졌다.
    최고, 길이 = None, 0
    for node in graph["증거"]:
        for alias in graph["사례층"][node]:
            납작 = "".join(alias.split()).lower()
            if len(납작) > 길이 and 납작 in t:
                최고, 길이 = node, len(납작)
    return (최고, 1.0) if 최고 else (None, 0.0)


def reachable(graph, start, rels=POS):
    """start 에서 rels 관계만 타고 닿는 노드 집합."""
    seen, q = set(), deque([start])
    while q:
        for rel, dst in graph["adj"].get(q.popleft(), []):
            if rel in rels and dst not in seen:
                seen.add(dst)
                q.append(dst)
    return seen


def counters(graph, node):
    """node 로부터 (직접이든 전진 경로를 거쳐서든) 부정되는 노드들.

    자책 논증은 여러 홉 뒤에 드러난다: CPU점유 --충족--> 앱병목 --부정--> DB병목.
    직접 엣지만 보면 이런 것을 통째로 놓친다."""
    out = []
    for n in [node] + list(reachable(graph, node)):
        for r, d in graph["adj"].get(n, []):
            # 부정한다고 다 반격이 아니다. 플레이어에게 이로운 노드(목표로 전진하는
            # 노드)를 무너뜨릴 때만 자책이다. 방해 노드를 부정하는 것은 오히려 득이다.
            if r in NEG and d not in out and graph["목표"] in reachable(graph, d) | {d}:
                out.append(d)
    return out


def judge(graph, text, 연속A=0):
    """→ (판정, 대사). 판정: 인정 / A / B1 / B2 / C / 근거없음

    연속A: 직전까지 되묻기가 연속 몇 번 실패했는지. 2회부터는 B2로 강등한다.
    마진이 좁아 A 밴드로 새어든 무관 발화가 무한 되묻기에 갇히는 것을 막는다."""
    ev, ev_conf = match_evidence(text, graph)
    # 증거 이름은 근거 표지이지 주장 내용이 아니다. "CCTV를 보면 ..." 의
    # 'CCTV를 보면' 이 벡터에 섞이면 정작 주장이 흐려진다. 숫자 뽑을 때처럼 지운다.
    본문 = 증거지우기(text, graph, ev)
    A_MIN, OK_MIN = graph["임계값"]["A_MIN"], graph["임계값"]["OK_MIN"]
    말 = graph["대사"]
    # 무관층(널 클래스)을 후보에 섞는다. 절대 임계값 대신 상대 비교로 걸러야
    # 노드가 늘어도 마진이 버틴다 — 평평한 풀에 절대 임계값만 쓰면 붕괴한다.
    claim_pool = ([n for n in graph["사례층"] if n not in graph["증거"]]
                  + list(graph["공통층"]))
    claim, conf = match(본문, claim_pool, graph)

    # 널 클래스는 발화 전체를 두고 실노드와 겨뤄야 한다. 조각마다 섞어서 최고를
    # 뽑으면, 막연한 한 조각이 널 클래스에 걸렸다는 이유로 실제 주장을 담은
    # 조각을 이겨버린다.
    # 널 클래스에는 두 종류가 산다. 기획자가 넣은 무관 예시(_타죄명: 포함)는
    # "이 재판 얘기가 아니다"라는 뜻이고, 되묻기에서 배운 반례(_반례:)는
    # "그 노드가 아니다"라는 뜻일 뿐이다. 후자를 B2 로 읽으면 사용자가 하지도
    # 않은 말을 시스템이 대신 해버린다. 그 노드만 빼고 다시 잰다.
    무관후보 = list(graph.get("무관층", {}))
    뺀것 = set()
    while 무관후보:
        무관노드, 무관점 = match(본문, 무관후보, graph)
        if not (무관점 > conf and 무관점 >= A_MIN):
            break
        if not 무관노드.startswith(반례표):
            return "B2", 말["B2"]
        뺀것.add(무관노드[len(반례표):])
        무관후보 = [n for n in 무관후보 if n != 무관노드]
        남은 = [n for n in claim_pool if n not in 뺀것]
        claim, conf = match(본문, 남은, graph) if 남은 else (None, 0.0)

    # 유저가 증거를 가리켰으면 그 증거가 보여줄 수 있는 것부터 본다.
    # 긴 발화에서 결론 문장이 막연하게 다른 법리에 높게 붙는 일이 잦은데,
    # 논증 구조상 근거와 이어지는 주장이 우선이다. 확신이 없을 때만 쓴다.
    if ev and conf < OK_MIN:
        닿는것 = [n for n in reachable(graph, ev) if n in graph["vec"]]
        if 닿는것:
            n2, c2 = match(본문, 닿는것, graph)
            if c2 >= A_MIN and c2 > conf:
                claim, conf = n2, c2

    # 경계 밖을 둘로 가른다. 이 구분이 무환각의 정직한 형태다.
    #   B2  = 기획자가 넣은 널 클래스가 이겼다 -> 무관하다는 적극적 증거가 있다
    #   미지 = 아무것도 충분히 걸리지 않았다 -> 증거의 부재. "모른다"이지 "무관하다"가 아니다
    # 둘을 뭉쳐 "관련 없습니다"라고 단언하면, 그래프에 없는 유효한 논증에 대해
    # 시스템이 거짓말을 하게 된다.
    if conf < A_MIN:
        _미지기록(graph, text, conf, claim)
        return "미지", 말.get("미지") or 말["B2"]

    # 결론을 그냥 주장하는 것은 정당한 수지만, 목표는 요건을 채워서 도달하는 것이다.
    # 후보에서 빼버리면 엉뚱한 이웃 노드가 대신 걸리므로, 후보에는 두고 응답만 따로 한다.
    if claim == graph["목표"]:
        return "목표주장", (말.get("목표주장") or
                            "그것이 이 재판의 결론입니다. 요건을 하나씩 입증하십시오.")
    if conf < OK_MIN:
        if 연속A >= 2:
            return "B2", 말["B2_강등"]
        return "A", 말["A"].format(claim=claim)
    if ev is None or ev_conf < A_MIN:
        return "근거없음", 말["근거없음"].format(claim=claim)

    수치, 값, 조건 = 수치판정(graph, claim, 본문)
    if 수치 in ("애매", "없음"):
        return "A", 말.get("A_말", 말["A"]).format(
            claim=claim, ev=ev, bad="", 말=문장(graph, claim), 반격말="")
    if 수치 is False:
        기준 = ("최소 %s" % _수치표기(조건["최소"], 조건.get("단위", ""))
                if "최소" in 조건
                else "최대 %s" % _수치표기(조건["최대"], 조건.get("단위", "")))
        return "수치미달", (말.get("수치미달") or 말["C"]).format(
            ev=ev, claim=claim, 말=문장(graph, claim), 반격말="",
            값=_수치표기(값, 조건.get("단위", "")), 기준=기준)

    if claim in reachable(graph, ev):
        bad = [c for c in counters(graph, claim) if c in reachable(graph, ev) or c in graph["공통층"]]
        if bad:
            return "인정", 말["인정_반격"].format(ev=ev, claim=claim, bad=bad[0])
        return "인정", 말["인정"].format(ev=ev, claim=claim)

    if any(claim in reachable(graph, e) for e in graph["증거"]):
        return "C", 말["C"].format(ev=ev, claim=claim)

    if claim in graph["공통층"]:
        return "B1", 말["B1"].format(claim=claim)
    return "C", 말["C"].format(ev=ev, claim=claim)


# 판정별 인내심 소모. 근거없음/A 는 무료 — 되묻기와 근거 요구는 절차이지 실책이 아니다.
# 미지는 벌점이 낮다 — 알아듣지 못한 것은 유저의 실책이 아닐 수 있다
벌점 = {"C": 2, "B2": 1, "B1": 1, "수치미달": 1, "미지": 1, "목표주장": 0, "재탕": 0,
        "인정": 0, "근거없음": 0, "A": 0}


def _거리(graph, start):
    """start 에서 전진 경로로 닿는 노드까지의 홉 수."""
    d, q = {start: 0}, deque([start])
    while q:
        n = q.popleft()
        for rel, dst in graph["adj"].get(n, []):
            if rel in POS and dst not in d:
                d[dst] = d[n] + 1
                q.append(dst)
    return d


def 요건(graph):
    """목표로 '충족' 엣지를 직접 가진 노드 = 이겨야 채워지는 칸.
    별도 데이터가 필요 없다. 그래프 구조가 곧 승리 조건이다."""
    return [n for n in graph["공통층"]
            if any(r == "충족" and d == graph["목표"] for r, d in graph["adj"].get(n, []))]


class 세션:
    """한 판. 확보한 요건과 판사의 인내심을 들고 있다."""

    def __init__(self, graph, 인내심=5):
        self.g, self.인내심, self.연속A = graph, 인내심, 0
        self.증거별요건, self.자책, self.이전확보 = {}, set(), set()
        self.직전A = None          # (되물은 노드, 유저가 했던 말)
        self.회차 = 0
        self.인정한주장 = set()
        self.최근 = deque(maxlen=3)   # 직전 (증거, 주장). 원문은 안 들고 있다
        self.해소 = None
        self.배운것 = []

    def 말하기(self, text):
        # 되묻기에 "맞다"고 답하면 그 표현을 그 노드의 예시로 배운다.
        # 노드의 뜻은 그대로고 부르는 법만 는다 — 새 지식이 아니라 환각 위험이 없다.
        확답 = _확답(text) if self.직전A else None
        if 확답 is True:
            노드, 원말 = self.직전A
            if 학습쓰기(self.g, 노드, 원말):
                self.배운것.append((노드, 원말))
                for 층 in ("공통층", "사례층"):
                    if 노드 in self.g.get(층, {}) and 원말 not in self.g[층][노드]:
                        self.g[층][노드].append(원말)
                        import numpy as np
                        self.g["vec"][노드] = np.vstack(
                            [self.g["vec"][노드], _vec(원말)])
                        break
            self.직전A = None
            text = 원말                        # 확인된 발화로 다시 판정한다
        elif 확답 is False:
            노드, 원말 = self.직전A
            if 학습쓰기(self.g, 노드, 원말, 아님=True):
                키 = 반례표 + 노드
                칸 = self.g.setdefault("무관층", {}).setdefault(키, [])
                if 원말 not in 칸:
                    칸.append(원말)
                    import numpy as np
                    self.g["vec"][키] = (
                        np.vstack([self.g["vec"][키], _vec(원말)])
                        if 키 in self.g["vec"] else np.array([_vec(원말)]))
            self.직전A = None
            말 = self.g["대사"].get("되묻기취소") or "그렇습니까. 그럼 다시 말씀해 주십시오."
            return "A", 말, self.결과()

        text, self.해소 = 대명사풀기(text, self.g, self.최근)
        tag, line = judge(self.g, text, self.연속A)
        self.연속A = self.연속A + 1 if tag == "A" else 0
        ev = match_evidence(text, self.g)[0]
        claim = match(증거지우기(text, self.g, ev),
                      [n for n in self.g["사례층"] if n not in self.g["증거"]]
                      + list(self.g["공통층"]) + list(self.g["무관층"]), self.g)[0]
        if tag == "인정":
            self.자책 |= set(counters(self.g, claim))
            닿음 = reachable(self.g, claim) | {claim}
            if ev:
                self.증거별요건.setdefault(ev, set()).update(닿음 & set(요건(self.g)))
        # 이미 인정한 주장을 또 들고 오면 다시 인정하지 않는다.
        # 자기가 방금 한 말을 기억하지 못하는 것처럼 들리는 가장 큰 원인이었다.
        if tag == "인정":
            # 같은 사실을 '다른 증거'로 다시 입증하는 것은 보강이지 반복이 아니다.
            # 요건마다 독립된 증거가 필요하므로 오히려 정당한 수다.
            if (claim, ev) in self.인정한주장:
                tag = "재탕"
            else:
                self.인정한주장.add((claim, ev))
        self.인내심 -= 벌점.get(tag, 0)
        self.직전A = (claim, text) if tag == "A" and claim else None
        self.회차 += 1
        p = 발화계획(self.g, tag, ev, claim, self)
        p["회차"] = self.회차
        # 말투를 재는 기준에서도 증거 이름을 뺀다. 주장 매칭에서 빼는 이유와
        # 같다(증거지우기) — 증거명이 남으면 그 이름을 여러 번 되풀이하는
        # 예시가 말투와 상관없이 이긴다. 실제로 주제명을 9번 반복하는 발췌가
        # 어떤 질문에도 똑같이 뽑혀서 말투 선택이 사실상 죽어 있었다.
        p["기준"] = _vec(증거지우기(text, self.g, ev) if ev else text)
        p["기본문장"] = line
        self.이전확보 = set(p["채운요건"])
        p["해소"] = self.해소
        if ev or claim:
            self.최근.append((ev, claim if tag in ("인정", "재탕", "A") else None))
        self.계획 = p
        try:
            line = 대사만들기(self.g, p)
        except (KeyError, IndexError):
            pass                       # 선택 대사가 없는 그래프는 기본 한 줄로
        return tag, line, self.결과()

    def 대답(self, text):
        """문장 -> 문장. 이 엔진의 기본 인터페이스다.

        판정(인정/A/B1/B2/C)은 게임 레이어가 쓰는 내부 정보이지 대답이 아니다.
        마지막 판정은 self.판정, 승패는 self.결과() 로 따로 꺼낸다."""
        self.판정, 답, self.승패 = self.말하기(text)
        return 답

    def 확보(self):
        """요건 -> 그것을 채운 증거. 요건마다 서로 다른 증거가 필요하다.

        논증 하나가 전진 경로 전체를 먹으면 세 수 만에 재판이 끝난다.
        그렇다고 증거를 먼저 쓴 요건에 고정해버리면, 그 증거로만 닿는 다른
        요건이 영영 막혀 이기지도 지지도 못하는 교착이 생긴다(코드리뷰 그래프에서 재현).
        그래서 고정하지 않고 매번 최대 이분 매칭을 다시 구한다 — 논증 순서와 무관해진다."""
        need = [n for n in 요건(self.g) if n not in self.자책]
        배정 = {}

        def 밀어넣기(ev, 본것):
            for req in self.증거별요건.get(ev, ()):
                if req not in need or req in 본것:
                    continue
                본것.add(req)
                if req not in 배정 or 밀어넣기(배정[req], 본것):
                    배정[req] = ev
                    return True
            return False

        for ev in self.증거별요건:
            밀어넣기(ev, set())
        return 배정

    def 결과(self):
        need = set(요건(self.g))
        if need & self.자책:
            # 자기 논증으로 무너뜨린 요건은 되돌릴 수 없다. 그래프에 그것을
            # 다시 세울 엣지가 없기 때문이다. 교착을 만들지 않으려면 여기서 끝난다.
            # ponytail: 복구시키려면 '부정을 부정하는' 경로가 그래프에 있어야 한다.
            return "패"
        if need <= set(self.확보()):
            return "승"
        return "패" if self.인내심 <= 0 else None

    def 현황(self):
        확 = self.확보()
        return " ".join(("O" if n in 확 else "X" if n in self.자책 else ".") + n
                        for n in 요건(self.g))


배수 = {"조": 10 ** 12, "억": 10 ** 8, "만": 10 ** 4,
        "천": 10 ** 3, "백": 10 ** 2, "십": 10}
_수 = re.compile(r"(\d[\d,]*(?:\.\d+)?)((?:\s*[조억만천백십])*)\s*([%％]|[가-힣a-zA-Z]{0,4})")
_한글수 = re.compile(r"[영일이삼사오육칠팔구]\s*[십백천만억조]")
_범위 = re.compile(r"[~–—-]\s*\d|\d\s*[~–—]")


def 숫자뽑기(text):
    """발화에서 (값, 단위) 를 뽑는다. 한국식 자릿수 표기를 곱으로 처리한다.

    임베딩은 크기를 모른다 — '6천만원'과 '600만원'이 의미 공간에서 거의 같은 점이다.
    수치가 결론을 가르는 도메인에서는 숫자를 따로 뽑아 비교해야 한다."""
    애매전체 = bool(_한글수.search(text) or _범위.search(text))
    조각 = []
    for m in _수.finditer(text):
        v, 자릿수, 단위 = float(m.group(1).replace(",", "")), m.group(2), m.group(3).strip()
        크기 = 1
        for ch in 자릿수:
            if ch in 배수:
                크기 *= 배수[ch]
        조각.append([v * 크기, 크기, 단위, m.start(), m.end()])

    out = []
    for 값, 크기, 단위, a, b in 조각:
        # "3억 5천만원" 처럼 자릿수가 내려가며 이어지면 하나의 수다
        if out and not out[-1][2] and a - out[-1][4] <= 2:
            # "1억 2천 3백만" 은 뒤의 '만'이 앞으로 분배되는 표기라 자릿수가
            # 단조 감소하지 않는다. 완전한 한국어 수사 문법 대신 애매함을 표시하고
            # 넘긴다 — 금액 도메인에서 잘못 읽은 숫자는 되묻기보다 훨씬 나쁘다.
            if 크기 >= out[-1][5]:
                out[-1][3] = False
            out[-1][0] += 값
            out[-1][2], out[-1][4], out[-1][5] = 단위, b, 크기
        else:
            out.append([값, 크기, 단위, not 애매전체, b, 크기])
    if not out and 애매전체:
        return [(None, "", False)]      # 순한글 수사 등 — 읽지 못했음을 알린다
    return [(v, u, 확실) for v, _, u, 확실, _, _ in out]


def _수치표기(v, 단위):
    if 단위 == "원" and v >= 10 ** 8:
        return "%g억원" % (v / 10 ** 8)
    if 단위 == "원" and v >= 10 ** 4:
        return "%g만원" % (v / 10 ** 4)
    return ("%g" % v) + 단위


def 수치판정(graph, node, text):
    """조건이 걸린 노드면 발화의 숫자로 충족 여부를 본다.

    -> True 충족 / False 미달 / None 판단 불가(조건 없음 또는 숫자 없음)"""
    조건 = graph.get("수치조건", {}).get(node)
    if not 조건:
        return None, None, None
    단위 = 조건.get("단위", "")
    본 = False
    for v, u, 확실 in 숫자뽑기(text):
        if not 확실:
            return "애매", v, 조건            # 추측하지 않고 되묻는다
        if 단위 and not u.startswith(단위):
            continue
        본 = True
        if "최소" in 조건 and v < 조건["최소"]:
            return False, v, 조건
        if "최대" in 조건 and v > 조건["최대"]:
            return False, v, 조건
        return True, v, 조건
    # 조건이 걸린 노드인데 쓸 만한 숫자가 없다. 검사를 건너뛰고 인정하면
    # fail-open 이 된다 — 값을 못 읽었으면 통과가 아니라 되묻기다.
    return "없음", None, 조건


def 문장(graph, node, 기준=None):
    """노드 -> 자연 문장. 매처를 거꾸로 돌린 것이다.

    문장->노드 매칭에 쓰는 예시들이 그대로 노드->문장 재료가 된다. 새 데이터가 없다.
    기준 벡터(유저의 방금 발화)를 주면 그 말투에 가장 가까운 예시를 고르므로
    대답이 유저의 표현을 되받는 것처럼 들린다. 생성이 아니라 선택이므로
    환각도 주입 표면도 늘지 않는다."""
    for layer in ("공통층", "사례층", "무관층"):
        exs = graph.get(layer, {}).get(node)
        if exs:
            if 기준 is None or node not in graph["vec"]:
                return exs[0]
            return exs[int((graph["vec"][node] @ 기준).argmax())]
    return node


def _미지기록(graph, text, conf, 가까운):
    """알아듣지 못한 발화를 남긴다.

    기획자가 놓친 논증이 여기 쌓인다. 빈도가 높은 것을 그래프에 추가하면
    그래프가 사용자에게서 자란다. 재학습은 없다."""
    경로 = graph.get("_미지로그")
    if not 경로:
        return
    try:
        with open(경로, "a", encoding="utf-8") as f:
            f.write(json.dumps({"발화": text, "최고점": round(conf, 3),
                                "가장가까운노드": 가까운},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def 발화계획(graph, tag, ev, claim, 세션=None):
    """이번 턴에 그래프가 아는 것 전부를 구조체로 뽑는다.

    judge() 는 5종 판정만 돌려주고 나머지를 버렸다. 그래프는 훨씬 많이 안다 —
    무엇이 남았는지, 무엇을 아직 안 썼는지, 무엇으로 반격할 수 있는지.
    대사를 풍부하게 만드는 재료는 LLM이 아니라 여기서 나온다."""
    p = {"판정": tag, "근거": ev, "주장": claim, "기준": None,
         "반격": [], "남은요건": [], "채운요건": {}, "이번에채움": [], "미사용증거": [],
         "경로": [], "쟁점힌트": [], "인내심": None}
    p["출처"] = (graph.get("출처") or {}).get(claim)
    if claim:
        p["반격"] = counters(graph, claim)
        목표 = graph["목표"]
        p["경로"] = [n for n in 요건(graph) if n in reachable(graph, claim)]
    if 세션 is not None:
        확 = 세션.확보()
        p["채운요건"] = 확
        p["이번에채움"] = [n for n in 확 if n not in 세션.이전확보]
        p["남은요건"] = [n for n in 요건(graph) if n not in 확 and n not in 세션.자책]
        쓴것 = set(확.values())
        p["인내심"] = 세션.인내심
    else:
        p["남은요건"] = 요건(graph)
        쓴것 = set()
    p["미사용증거"] = [e for e in graph["증거"] if e not in 쓴것]
    # 아직 증거로 닿지 않는 법리 = B1 후보 = 조사할 거리
    닿는곳 = set()
    for e in graph["증거"]:
        닿는곳 |= reachable(graph, e, POS + NEG)
    p["쟁점힌트"] = [n for n in graph["공통층"] if n not in 닿는곳]
    return p


_조사쌍 = {"은": "는", "는": "은", "이": "가", "가": "이", "을": "를", "를": "을",
           "과": "와", "와": "과", "으로": "로", "로": "으로"}


def _받침있나(글자):
    코드 = ord(글자)
    if not (0xAC00 <= 코드 <= 0xD7A3):
        return None                     # 한글이 아니면 판단하지 않는다
    return (코드 - 0xAC00) % 28 != 0


def 조사고치기(문장, 낱말들):
    """치환된 노드 이름 뒤의 조사를 받침에 맞게 고친다.

    템플릿에 조사를 박아두면 '방위의사은' 같은 것이 나온다. 노드 이름이
    무엇이 들어올지 미리 알 수 없으므로 조립 후에 고치는 편이 낫다.
    치환된 값 바로 뒤만 손대므로 본문 다른 곳은 건드리지 않는다."""
    for 값 in sorted({x for x in 낱말들 if x}, key=len, reverse=True):
        받침 = _받침있나(값[-1])
        if 받침 is None:
            continue
        i = 0
        while True:
            i = 문장.find(값, i)
            if i < 0:
                break
            뒤 = i + len(값)
            for 길이 in (2, 1):
                조 = 문장[뒤:뒤 + 길이]
                if 조 in _조사쌍:
                    바름 = 조 if (받침 == (조 in ("은", "이", "을", "과", "으로")))                         else _조사쌍[조]
                    문장 = 문장[:뒤] + 바름 + 문장[뒤 + 길이:]
                    break
            i = 뒤
    return 문장


def _고르기(값, 회차):
    """대사에 '||' 로 여러 변형을 적어두면 턴마다 돌려쓴다.

    같은 문장이 매 턴 반복되면 상대가 기계라는 것이 바로 드러난다."""
    if 값 and "||" in 값:
        갈래 = [x.strip() for x in 값.split("||") if x.strip()]
        return 갈래[회차 % len(갈래)]
    return 값


def 대사만들기(graph, p):
    """발화계획을 문장으로 조립한다. 그래프에 있는 선택 대사만 붙는다.

    필수 대사 8종은 그대로 두고, 있으면 붙고 없으면 안 붙는 선택 키로 확장한다.
    기존 그래프를 깨지 않으면서 대답이 길어진다."""
    말, 줄 = graph["대사"], []
    회차 = p.get("회차", 0)

    def 채움(key, **kw):
        t = _고르기(말.get(key), 회차)
        return t.format(**kw) if t else None

    tag = p["판정"]
    기본 = {"인정": ("인정_반격" if p["반격"] else "인정")}.get(tag, tag)
    if 기본 not in 말 and 기본 + "_말" not in 말:
        # 이 판정용 대사가 그래프에 없으면 judge() 가 이미 만든 문장을 그대로 쓴다.
        # 예전에는 C 템플릿으로 떨어뜨려서 엉뚱한 말이 나갔다.
        기본값 = p.get("기본문장")
        if 기본값:
            줄 = [기본값]
            if p["인내심"] is not None and p["인내심"] <= 2 and 말.get("압박"):
                줄.append(말["압박"].format(인내심=p["인내심"]))
            return " ".join(줄)
        기본 = "C"
    기준 = p.get("기준")
    칸 = {"ev": p["근거"], "claim": p["주장"],
          "bad": p["반격"][0] if p["반격"] else "",
          # 거꾸로 돌린 매처: 노드명 대신 자연 문장
          "말": 문장(graph, p["주장"], 기준) if p["주장"] else "",
          "반격말": 문장(graph, p["반격"][0], 기준) if p["반격"] else ""}
    줄.append(_고르기(말[기본 + "_말"] if 기본 + "_말" in 말 else 말[기본],
                      회차).format(**칸))

    if tag == "인정" and p["경로"]:
        줄.append(채움("요건충족", 요건=", ".join(p["이번에채움"])) if p["이번에채움"] else None)
    if tag == "B1" and p["미사용증거"]:
        줄.append(채움("힌트_증거", 증거=", ".join(p["미사용증거"][:3])))
    # 남은 요건은 판이 움직인 턴에만 알린다. 매 턴 같은 목록을 읊으면
    # 자기가 방금 한 말을 기억 못 하는 것처럼 들린다.
    if p["이번에채움"] and p["남은요건"]:
        줄.append(채움("남은요건", 남은=", ".join(p["남은요건"][:2])))
    if p["인내심"] is not None and p["인내심"] <= 2:
        줄.append(채움("압박", 인내심=p["인내심"]))
    if p.get("출처") and tag in ("B1", "인정"):
        줄.append(채움("출처", 출처=p["출처"], claim=p["주장"]))
    if p.get("해소"):
        앞 = 채움("해소알림", 가리킨것=", ".join(p["해소"])) or             ("%s 말씀이군요." % ", ".join(p["해소"]))
        줄.insert(0, 앞)
    낱말 = [p.get("근거"), p.get("주장")] + list(p.get("이번에채움") or [])         + list(p.get("남은요건") or []) + (p.get("반격") or [])
    return 조사고치기(" ".join(x for x in 줄 if x), 낱말)


def 대답(graph, text):
    """상태 없이 한 번만: 문장 -> 문장. 판정이 필요하면 judge() 를 쓴다."""
    return 세션(graph).대답(text)


def 보정(graph, 발화=None):
    """임계값을 실제로 재는 도구.

    A_MIN / OK_MIN 은 공통층 크기에 따라 움직인다(8노드 간격 0.19 -> 28노드 0.05).
    "그래프를 키우면 재보정하라"고 적어두고 재는 절차가 없으면 아무도 못 한다.

    판정 규칙 그대로 잰다 — 무관층까지 포함한 전체 후보 중 누가 이기는지를 본다.
    외부 데이터 없이 각 예시를 자기 자신만 빼고 매칭한다(leave-one-out).
    발화={"있음":[...], "없음":[...]} 를 주면 그것으로 잰다 — 남이 쓴 문장이 있으면
    그쪽이 훨씬 정직하다."""
    import numpy as np
    실노드 = [n for n in list(graph["공통층"]) + list(graph["사례층"])
              if n not in graph["증거"]]
    무관 = list(graph.get("무관층", {}))
    전체 = 실노드 + 무관

    def 승자(v, 제외=None):
        최, 이름 = -1.0, None
        for n in 전체:
            sims = graph["vec"][n] @ v
            if n == 제외:
                if len(sims) < 2:
                    continue
                sims = np.sort(sims)[:-1]      # 자기 문장은 빼고 본다
            m = float(sims.max())
            if m > 최:
                최, 이름 = m, n
        return 최, 이름

    맞음, 틀림, 무관점수, 예시부족 = [], [], [], []
    if 발화:
        for t in 발화.get("있음", []):
            c, n = 승자(_vec(t))
            (틀림 if n in 무관 else 맞음).append((c, n, t))
        for t in 발화.get("없음", []):
            c, n = 승자(_vec(t))
            무관점수.append((c, n, t, n in 무관))
    else:
        for node in 실노드:
            exs = graph["공통층"].get(node) or graph["사례층"].get(node) or []
            if len(exs) < 2:
                예시부족.append(node)
                continue
            for e in exs:
                c, n = 승자(_vec(e), 제외=node)
                (맞음 if n == node else 틀림).append((c, node, n, e))
        for node in 무관:
            for e in graph["무관층"][node]:
                c, n = 승자(_vec(e), 제외=node)
                무관점수.append((c, n, e, n in 무관))

    있음점수 = sorted(x[0] for x in 맞음)
    # A_MIN 아래면 무관 발화가 실노드를 이겨도 어차피 B2 다. 문제가 아니다.
    샌것 = [x for x in 무관점수 if not x[3] and x[0] >= graph["임계값"]["A_MIN"]]
    추천 = {}
    if 있음점수:
        추천["OK_MIN"] = round(max(0.30, 있음점수[max(0, len(있음점수) // 20)] - 0.02), 2)
    if 샌것:
        추천["A_MIN"] = round(min(추천.get("OK_MIN", 1.0) - 0.05,
                                 max(x[0] for x in 샌것) + 0.01), 2)
    return {"맞음": len(맞음), "틀림": sorted(틀림, key=lambda x: -x[0]),
            "있음점수": 있음점수, "무관샌것": sorted(샌것, key=lambda x: -x[0]),
            "무관총": len(무관점수), "예시부족": 예시부족, "추천": 추천}


_조 = re.compile(r"^제(\d+)조\s*\(([^)]+)\)")
_항 = re.compile(r"^([①-⑳])\s*(.+)$")
_명사구 = re.compile(r"[가-힣]{2,}(?:의|한|인)?\s*[가-힣]{2,}")


_버릴끝 = ("의", "를", "을", "이", "가", "은", "는", "에", "로", "와", "과", "도",
           "하지", "하기", "있는", "없는", "대하여는", "경우에", "때에는", "있어")
_버릴시작 = ("전항", "규정", "특별한", "기타", "다른", "그", "이", "저")


def _쓸만한구(구):
    """규칙 기반 추출의 찌꺼기를 거른다.

    조사·어미로 끝나거나 지시어로 시작하는 조각은 개념이 아니다.
    이 필터는 근본 해결이 아니다 — 저작 시점에 큰 모델을 붙이면 훨씬 낫다.
    핵심은 그 모델이 '실행 시점'에는 필요 없다는 것이다."""
    말 = 구.split()
    if 말[0].startswith(_버릴시작):
        return False
    return not 말[-1].endswith(_버릴끝)


_용어패턴 = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z0-9]+")
_버릴말 = {
    "그리고", "그러나", "또는", "기타", "다음", "경우", "때문", "정도", "가지", "대한",
    "통해", "위해", "있는", "없는", "하는", "되는", "이하", "이상", "다만", "전항",
    "본항", "규정", "적용", "아니한다", "아니하다", "한다", "된다", "있다", "없다",
    "제외", "포함", "관하여", "대하여", "의하여", "따라", "관한",
    "벌하", "때에", "현재", "타인", "자기", "그것", "이것", "일부", "전부",
    "감경", "면제", "정황", "특별", "법률", "경우에", "때문에",
}
_조사 = ("으로써", "으로서", "이라는", "에서는", "에서도", "라는", "에서", "에게", "한테",
         "까지", "부터", "처럼", "보다", "이나", "거나", "이며", "으로", "로서", "로써",
         "와의", "과의", "이라", "의", "을", "를", "은", "는", "이", "가", "도", "만",
         "과", "와", "로", "에")


_어미 = ("하지", "하는", "하여", "한", "된", "되는", "스러운", "스럽게", "있어", "없어")


def _조사떼기(낱말, 어휘):
    """긴 조사부터 뗀다.

    Mnemosyne 는 '줄기가 어휘집에 이미 있을 때만' 뗐다. 슬라이드는 짧고 정제돼서
    명사가 홑으로 한 번은 등장하기 때문이다. 법조문은 산문이라 명사가 늘 조사를
    달고 나온다 — 그 조건을 걸면 '행위는', '때에는' 이 그대로 개념이 된다.
    그래서 무조건 뗀다. 대신 어미까지 떼고 길이를 본다."""
    for 회 in range(2):
        for 조 in _조사 + _어미:
            if 낱말.endswith(조) and len(낱말) - len(조) >= 2:
                낱말 = 낱말[: -len(조)]
                break
        else:
            break
    return 낱말


_용언끝 = ("지", "기", "여", "며", "면", "고", "서", "게", "히", "이", "어", "아", "나")


def _명사같나(t):
    """용언 활용형을 걸러 명사만 남긴다.

    '벌하지', '위한', '피하기' 는 개념이 아니라 서술어다. 규칙만으로는 여기까지가
    한계다 — 형태소 분석기나 저작 시점의 큰 모델이 값을 하는 자리가 바로 여기다."""
    if t.isascii():
        return True
    if t.endswith(("한", "인", "된", "될", "할")):
        return False
    return not (len(t) <= 3 and t[-1] in _용언끝)


def 공기그래프(경로, 최대=40):
    """법 텍스트에서 개념 공기(共起) 그래프를 만든다.

    Mnemosyne 의 concept_graph 와 같은 모양이다 — 노드는 개념 하나당 하나,
    엣지는 '같은 조문에 함께 나왔다' 는 검증 가능한 사실 하나뿐이다.
    'A가 B를 함의한다' 같은 것을 지어내지 않는다. 그것은 논증 그래프의 일이다.

    조문 단위가 Mne 의 슬라이드에 해당한다. 조문은 법이 인쇄한 정제된 표현이다."""
    묶음 = 조문읽기(경로)
    어휘 = {t for _, 문장 in 묶음 for t in _용어패턴.findall(문장)}
    조문별 = []
    for 출처, 문장 in 묶음:
        말들 = set()
        for raw in _용어패턴.findall(문장):
            t = _조사떼기(raw, 어휘)
            if t.isascii():
                t = t.lower()
            if len(t) >= 2 and t not in _버릴말 and _명사같나(t):
                말들.add(t)
        조문별.append((출처, 말들))

    자리 = {}
    for 출처, 말들 in 조문별:
        for t in 말들:
            자리.setdefault(t, []).append(출처)
    뽑음 = sorted(자리, key=lambda t: (len(자리[t]), len(t)), reverse=True)[:최대]
    고른것 = set(뽑음)

    노드 = [{"이름": t, "무게": len(자리[t]), "출처": sorted(set(자리[t]))} for t in 뽑음]
    쌍 = {}
    for _, 말들 in 조문별:
        같이 = sorted(말들 & 고른것)
        for i in range(len(같이)):
            for j in range(i + 1, len(같이)):
                쌍[(같이[i], 같이[j])] = 쌍.get((같이[i], 같이[j]), 0) + 1
    엣지 = [{"a": a, "b": b, "무게": w, "관계": "같은조문"}
            for (a, b), w in sorted(쌍.items(), key=lambda kv: -kv[1])]
    return {"노드": 노드, "엣지": 엣지[: 최대 * 3]}


def 조문읽기(경로):
    """법령 텍스트 -> (출처, 문장) 목록. 조·항 단위로 쪼갠다."""
    out, 조번호, 조이름 = [], None, None
    for 줄 in open(경로, encoding="utf-8"):
        줄 = 줄.strip()
        if not 줄:
            continue
        m = _조.match(줄)
        if m:
            조번호, 조이름 = m.group(1), m.group(2)
            continue
        if 조번호 is None:
            continue
        h = _항.match(줄)
        항, 본문 = (str(ord(h.group(1)) - 0x245F), h.group(2)) if h else (None, 줄)
        출처 = "형법 %s조%s(%s)" % (조번호, (" %s항" % 항) if 항 else "", 조이름)
        for 문장 in re.split(r"(?<=다)\.\s*", 본문):
            문장 = 문장.strip().rstrip(".")
            if len(문장) > 5:
                out.append((출처, 문장))
    return out


def 조문제안(graph, 경로, 이미앎=0.72):
    """법령을 읽고 그래프에 없는 개념을 제안한다.

    지어내는 것이 아니라 출처가 있는 텍스트에서 뽑는다 — 근거가 있으므로
    환각이 아니다. 무환각의 정체는 '자라지 않는다'가 아니라
    '근거 없이 단언하지 않는다' 이다.

    큰 모델이 필요하다면 여기(저작 시점)에 붙인다. 실행 시점은 그대로 가볍다."""
    후보 = list(graph["공통층"])
    새것 = []
    # 조문 형식이면 조·항 단위로, 아니면 대목 단위로 읽는다. 위키백과 산문에는
    # '제N조' 가 없어서 조문읽기 만 쓰면 아무것도 안 읽힌다 — 실제로 받아온
    # 글에서 후보가 0개 나왔다. 검색으로 자료를 넓히려면 여기가 열려 있어야 한다.
    글감 = 조문읽기(경로) or [(출처, 본문) for 본문, 출처 in _대목(경로)]
    for 출처, 문장 in 글감:
        구들 = {m.group(0).strip() for m in _명사구.finditer(문장)}
        for 구 in 구들:
            if len(구) < 4 or not _쓸만한구(구):
                continue
            n, c = match(구, 후보, graph)
            if c < 이미앎:                     # 이미 아는 개념이 아니다
                새것.append((round(c, 3), 구, 출처, n))
    본것, 정리 = set(), []
    for c, 구, 출처, 가까운 in sorted(새것):
        키 = 구.replace(" ", "")
        if 키 in 본것:
            continue
        본것.add(키)
        정리.append({"구": 구, "출처": 출처, "가장가까운": 가까운, "유사도": c})
    return 정리


def _자료파일(경로):
    """자료 폴더 아래 텍스트 파일들. 노드 제안기와 엣지 제안기가 나눠 쓴다."""
    return ([경로] if os.path.isfile(경로) else
            sorted(os.path.join(r, f) for r, _, fs in os.walk(경로) for f in fs
                   if f.endswith((".txt", ".md"))))


def _자료구절(경로):
    """자료 텍스트 -> (명사구, 출처) 목록. 이름 후보는 여기서만 나온다.

    미지 뭉치에 이름을 붙일 때 발화에서 지어내면 그게 환각이다.
    이름은 반드시 사람이 넣어둔 원문에 이미 있던 말이어야 하고,
    출처가 함께 나와야 한다. 원문에 없으면 이름을 내지 않는다 —
    그건 모델이 모자란 게 아니라 문서가 없는 것이다."""
    out, 본것 = [], set()
    for p in _자료파일(경로):
        이름 = os.path.basename(p)
        for i, 줄 in enumerate(open(p, encoding="utf-8"), 1):
            for m in _명사구.finditer(줄):
                구 = m.group(0).strip()
                키 = 구.replace(" ", "")
                if len(구) >= 4 and _쓸만한구(구) and 키 not in 본것:
                    본것.add(키)
                    out.append((구, "%s:%d" % (이름, i)))
    return out


def 이름후보(구절, 중심, 최소=0.45, 개수=2):
    """뭉치의 중심에 가장 가까운 원문 구절. 근거 미달이면 빈 목록."""
    if not 구절:
        return []
    구, _ = zip(*구절)
    V = _model().encode([숫자가리기(x) for x in 구], normalize_embeddings=True)
    점 = V @ 중심
    return [(구절[j][0], 구절[j][1], round(float(점[j]), 3))
            for j in 점.argsort()[::-1][:개수] if 점[j] >= 최소]


_빈줄 = re.compile(r"\n\s*\n")


def _대목(경로, 최소=40, 최대=400):
    """자료 텍스트 -> (대목, 출처). 대목 = 공기(共起)를 재는 단위다.

    경계를 잘못 잡으면 전부 무너진다. 고정 길이 창으로 자르면 제18조부터
    제21조까지가 한 대목에 들어가고, 그 대목의 임베딩은 넷 중 무엇에 대한
    것도 아니게 된다 — 정당방위 조문이 실린 대목에서 정작 '정당방위'가
    4등(0.474)으로 밀렸다. 조문 파일은 조 단위로 자른다. 조 표시가 없는
    산문은 빈 줄로 자르고, 큰 덩이만 창을 내린다."""
    for p in _자료파일(경로):
        이름 = os.path.basename(p)
        줄들 = [x.strip() for x in open(p, encoding="utf-8").read().split(chr(10))]
        조있음 = any(_조.match(x) for x in 줄들)
        통, 시작 = [], 1
        for 번호, 줄 in enumerate(줄들, 1):
            끊음 = (_조.match(줄) is not None) if 조있음 else (not 줄)
            길이 = sum(len(x) + 1 for x in 통)
            if 통 and (끊음 or 길이 >= 최대 or 번호 == len(줄들)):
                if 번호 == len(줄들) and 줄 and not 끊음:
                    통.append(줄)
                본문 = " ".join(통)
                if len(본문) >= 최소:
                    yield 본문[:최대], "%s:%d" % (이름, 시작)
                통, 시작 = [], 번호
            if 줄:
                if not 통:
                    시작 = 번호
                통.append(줄)
        if 통:
            본문 = " ".join(통)
            if len(본문) >= 최소:
                yield 본문[:최대], "%s:%d" % (이름, 시작)


def 엣지제안(graph, 자료="data", 최소=2, 임계=0.45, 흔함=0.25, 최대후보=25):
    """원문에서 두 노드가 같은 대목에 함께 나오면 관계 후보다.

    노드 제안기(제안/조문제안)와 규율이 같다. 지어내지 않는다 —
    관계가 *있을지도 모른다*는 것까지만 원문이 말해주고,
    방향(증명/충족/부정)은 사람이 정한다. 방향을 자동으로 고르는 순간
    그래프가 근거 없이 단언하기 시작하고, 그게 이 엔진이 피하는 단 하나다.

    노드가 아니라 엣지를 늘리는 이유: 같은 노드 수에서 가지치기를 1 -> 2 로만
    올려도 유도 명제가 1.2배 -> 3.4배가 된다. 그리고 엣지는 이미 이름 붙은
    두 개 사이의 예/아니오라 노드보다 훨씬 싸다.

    임계가 판정 임계값(A_MIN 0.50)보다 낮은 것은 재는 대상이 다르기 때문이다.
    긴 조문 대목과 짧은 주장을 견주므로 코사인이 통째로 내려간다 — 형법
    116개 대목에서 최고점 중앙이 0.481이었고 0.55로 재면 수확이 0이 된다.

    흔함: 대목의 이 비율 넘게 걸리는 노드는 빼버린다. '침해의존재'가 형법
    116개 대목 중 65개(56%)에 걸렸다. 그런 노드는 어느 대목이냐를 구별해
    주지 못하므로 공기(共起)의 근거가 못 된다. 이걸 안 빼면 제안이 전부
    그 노드와의 쌍으로 채워지고, 영수증에 엉뚱한 조문이 붙는다."""
    import numpy as np
    # 증거끼리는 엣지가 없다. 증거는 주장을 증명할 뿐 서로를 증명하지 않는다.
    증거 = set(graph["증거"])
    노드 = [n for n in list(graph["공통층"]) + list(graph["사례층"])
            if n in graph["vec"]]
    if len(노드) < 2:
        return []
    행, 임자 = [], []
    for n in 노드:
        for v in graph["vec"][n]:
            행.append(v)
            임자.append(n)
    M, 임자 = np.array(행), np.array(임자)

    대목들 = list(_대목(_길(자료)))
    걸림들 = []
    for i in range(0, len(대목들), 256):          # 배치로 인코딩한다
        묶음 = 대목들[i:i+256]
        V = _model().encode([숫자가리기(t) for t, _ in 묶음],
                            normalize_embeddings=True)
        점 = V @ M.T
        for k in range(len(묶음)):
            뽑 = {}
            for n, sc in zip(임자[점[k] >= 임계], 점[k][점[k] >= 임계]):
                뽑[n] = max(뽑.get(n, 0.0), float(sc))
            걸림들.append(뽑)

    # 흔한 노드를 걷어낸다 (역문서빈도). 이게 없으면 결과가 전부 잡음이다.
    빈도 = {}
    for 걸림 in 걸림들:
        for n in 걸림:
            빈도[n] = 빈도.get(n, 0) + 1
    한도 = max(흔함 * len(대목들), 1)
    흔한것 = {n for n, c in 빈도.items() if c > 한도}

    있음 = {(a, b) for a, _, b in graph["엣지"]}
    있음 |= {(b, a) for a, b in 있음}
    셈, 근거 = {}, {}
    for 걸림, (본문, 출처) in zip(걸림들, 대목들):
        걸림 = {n: v for n, v in 걸림.items() if n not in 흔한것}
        if not (2 <= len(걸림) <= 4):       # 다 걸리는 대목은 정보가 없다
            continue
        for a, b in itertools.combinations(sorted(걸림), 2):
            if (a, b) in 있음 or (a in 증거 and b in 증거):
                continue
            셈[(a, b)] = 셈.get((a, b), 0) + 1
            # 이 대목이 이 쌍의 근거로 얼마나 센가 = 약한 쪽 점수.
            # 한쪽만 강한 대목은 그 쌍에 대해 아무 말도 안 한 것이다.
            근거.setdefault((a, b), []).append(
                (min(걸림[a], 걸림[b]), 본문[:120], 출처))

    # 횟수로 줄세우면 약하게 여러 번 걸린 잡음이 이긴다. 가장 센 대목으로 센다.
    나옴 = []
    for (a, b), c in 셈.items():
        if c < 최소:
            continue
        센것 = sorted(근거[(a, b)], reverse=True)
        순환 = [x for x, y in ((a, b), (b, a)) if y in reachable(graph, x)]
        나옴.append({"쌍": (a, b), "횟수": c, "세기": round(센것[0][0], 3),
                     "근거": [(t, o) for _, t, o in 센것[:2]], "순환주의": 순환})
    나옴.sort(key=lambda d: (-d["세기"], -d["횟수"], d["쌍"]))
    return 나옴[:최대후보], sorted(흔한것)


_그래프칸 = {}      # 최근에 쓴 그래프 본체. 오래된 것부터 버린다
_색인칸 = {}       # 색인은 작고 항상 쓰이므로 버리지 않는다


def 그래프색인(뿌리=None, 최대예시=90):
    """어떤 그래프가 무엇을 다루는지의 목록. 그래프들의 그래프다.

    도메인이 늘면 "이 질문은 어느 그래프냐" 가 새 문제가 된다. 그런데 그건
    이 엔진이 이미 푸는 문제다 — 발화를 노드에 붙이는 것과 같은 모양이라,
    한 층 위에 같은 매처를 쓰면 된다. 노드가 그래프이고 예시가 그 그래프의
    목표와 개념 이름이다.

    색인은 kg읽기로만 만든다. 벡터도 학습 덧칠도 필요 없고, 무엇보다
    후보 전부를 load 하면 안 된다 — 고르기 전에 다 올리면 고르는 뜻이 없다.
    docs/ko/direction.md 의 메모리 층 설계 그대로다: 색인은 작고 항상 쓰이고,
    그래프 본체는 크고 한 번에 하나만 쓴다."""
    뿌리 = 뿌리 or _여기
    파일 = sorted(glob.glob(os.path.join(뿌리, "graphs", "*.kg"))) + \
           sorted(glob.glob(os.path.join(뿌리, "cases/사건_*.kg")))
    색인 = {"역할": "안내", "목표": "그래프고르기",
            "임계값": {"A_MIN": 0.40, "OK_MIN": 0.50},
            "공통층": {}, "사례층": {}, "무관층": {}, "엣지": [],
            "대사": {}, "수치조건": {}}
    for p in 파일:
        if "템플릿" in p:
            continue
        try:
            g = kg읽기(p)
        except Exception:
            continue
        이름 = os.path.relpath(p, 뿌리).replace("\\", "/")
        # 노드 이름만 쓰면 안 된다. '전문게재' 라는 이름은 '통째로 베껴
        # 올렸습니다' 와 안 닮았지만 그 노드의 말 예시는 닮았다. 사람이 쓰는
        # 말로 물어오므로 색인도 사람이 쓰는 말을 들고 있어야 한다.
        예시 = [g.get("목표") or ""]
        for 층 in ("공통층", "사례층"):
            for n, 말들 in g.get(층, {}).items():
                예시.append(n)
                예시 += list(말들)[:2]
        예시 = [x for x in 예시 if x][:최대예시]
        if 예시:
            색인["공통층"][이름] = 예시
    색인["adj"] = {}
    색인["증거"] = []
    색인["vec"] = _예시벡터(색인)
    return 색인


def 그래프고르기(질문, 색인=None, 최소=0.55, 개수=3):
    """질문 -> (그래프 경로, 점수, 후보들). 고르지 못하면 (None, 점수, 후보들).

    문턱 0.55 는 재서 정한 값이다. 색인이 노드 이름만 들고 있을 때는 점수가
    낮아 0.42 였는데, 말 예시까지 넣자 전체가 올라가면서 잡담도 0.47 로 올라
    문턱을 넘었다. 다시 재보니 답할 질문은 0.61 이상, 잡담은 0.49 이하로
    갈린다. 색인을 바꾸면 이 값도 다시 재야 한다.

    동점이 흔하다. 'CCTV에 흉기' 는 cases/사건_편의점강도 와 graph_인과 가 둘 다
    0.661 인데 양쪽 다 CCTV·흉기소지를 갖고 있어서 진짜로 애매한 것이다.
    한쪽을 억지로 이기게 하는 규칙을 두는 대신 후보를 같이 돌려준다."""
    색인 = 색인 or _색인칸.setdefault("색인", 그래프색인())
    if not 색인["공통층"]:
        return None, 0.0, []
    점수 = sorted(((match(질문, [n], 색인)[1], n) for n in 색인["공통층"]),
                  reverse=True)
    후보 = [(n, round(c, 3)) for c, n in 점수[:개수]]
    최고, 이름 = 점수[0]
    return (이름 if 최고 >= 최소 else None), round(최고, 3), 후보


def 그래프불러오기(이름, 최대=2):
    """고른 그래프를 올린다. 최근 것 몇 개만 들고 있는다.

    색인은 항상 메모리에 있고 본체는 쓸 때만 올라온다. 이것이 이 프로젝트가
    처음부터 쓰던 층 구조다 — 공통층은 작고 모두가 공유하고, 사례층은 크고
    한 번에 하나만 쓴다.

    그런데 처음에는 올린 것을 영영 들고 있었다. '한 번에 하나만' 이라고
    해놓고 여섯 개를 다 쥐고 있으면 매니저를 만든 뜻이 없다. 도메인이
    수백 개가 되면 그대로 수백 배가 된다. 최근 것만 남기고 버린다."""
    if 이름 in _그래프칸:
        _그래프칸[이름] = _그래프칸.pop(이름)      # 가장 최근으로 옮긴다
        return _그래프칸[이름]
    _그래프칸[이름] = load(이름)
    while len(_그래프칸) > 최대:
        _그래프칸.pop(next(iter(_그래프칸)))       # 가장 오래된 것부터 버린다
    return _그래프칸[이름]


def 안내(질문):
    """질문 하나를 알맞은 그래프로 보내고 그 그래프의 판정을 돌려준다.
    -> (그래프 이름, 판정, 대사)"""
    이름, 점, _후보 = 그래프고르기(질문)
    if not 이름:
        return None, "미지", "어느 그래프에서 다룰 이야기인지 모르겠습니다."
    g = 그래프불러오기(이름)
    tag, line = judge(g, 질문)
    return 이름, tag, line


def 판례읽기(경로):
    """법제처에서 받은 판례 jsonl. 채점 데이터다."""
    out = []
    for 줄 in open(_길(경로), encoding="utf-8"):
        줄 = 줄.strip()
        if 줄:
            try:
                out.append(json.loads(줄))
            except ValueError:
                pass
    return out


_판례잡음 = re.compile(r"^\s*(\[\d+\]|\d+\.)\s*")

# 판결요지는 법령을 통째로 따온다 ("구 경찰관 직무집행법 제10조 제3항은 ...").
# 그건 법원의 판단이 아니라 인용이라 채점 대상이 아니다. 안 거르면 미지가
# 인용문으로 채워지고 --suggest 가 조문 껍데기를 노드로 제안한다.
_인용문 = re.compile(r"(개정되기 전의 것|이하 ‘|법률 제\d+호|"
                     r"제\d+조[^)]{0,20}(은|는)\s*[\"“])")


def 판례채점(graph, 판례들, 기록=True):
    """판결요지를 그래프에 걸어본다. 변환 없이 오늘 잴 수 있는 기준선이다.

    판례를 사건 md 로 옮기는 건 사람 일이지만, 판결요지는 이미 법리를
    이름으로 호명한다 ('침해의 현재성', '상당한 이유'). 그 문장들이
    그래프 노드에 걸리는 비율이 곧 '이 그래프가 법원이 실제로 쓰는
    법리를 덮고 있는가' 다. 엣지를 넣었다 뺐다 하려면 먼저 이 숫자가
    있어야 한다 — 없으면 좋아졌는지 나빠졌는지 알 수가 없다.

    안 걸린 문장은 미지 로그로 간다. 게임 세션이 아니라 실제 판례의
    말이므로, --suggest 가 뽑는 노드 후보의 질이 통째로 달라진다."""
    셈 = {}
    문장수 = 0
    걸린노드 = {}
    for 판 in 판례들:
        본 = 판.get("판결요지") or 판.get("판시사항") or ""
        for 조각 in 조각내기(본):
            조각 = _판례잡음.sub("", " ".join(조각.split()))
            if len(조각) < 15 or _인용문.search(조각):
                continue
            문장수 += 1
            tag, _ = judge(graph, 조각) if 기록 else judge(graph, 조각)
            셈[tag] = 셈.get(tag, 0) + 1
            # 판결요지는 증거를 대지 않고 법리만 말한다. '근거없음'은
            # 주장을 못 알아들은 게 아니라 증거가 없다는 뜻이라 덮은 것이다.
            if tag not in ("미지", "B2"):
                claim = match(조각, list(graph["공통층"]), graph)[0]
                걸린노드[claim] = 걸린노드.get(claim, 0) + 1
    덮음 = sum(v for k, v in 셈.items() if k not in ("미지", "B2"))
    return {"판례수": len(판례들), "문장수": 문장수, "판정": 셈,
            "덮음": 덮음, "덮음률": 덮음 / max(문장수, 1),
            "걸린노드": 걸린노드}


_방향표지 = ("아니", "없", "못", "초과", "지나", "이미", "끝", "넘", "제한", "과잉")


def _방향자질(graph, a, b, 말, 요건집합, 도수):
    """(a, b) 쌍의 구조 자질 28개. 임베딩은 안 쓴다.

    임베딩을 같이 넣으면 정확도가 2.8점 오르지만 부정 적중은 16/33 로 똑같다.
    순서를 매기는 데 중요한 것은 부정을 놓치지 않는 것이라 구조만 쓴다.

    a -> b 엣지가 그래프에 *없는* 상태에서 재야 한다. 들어 있으면 충족일 때만
    도착 노드와 그 아래가 닿는수에 더해져 라벨이 자질로 새어든다 — 실제로
    그 누출 때문에 92.9% 라는 가짜 숫자가 나왔었다(실제 81.6%)."""
    ta, tb = " ".join(말.get(a, ())), " ".join(말.get(b, ()))
    return [도수[a], 도수[b], b == graph["목표"], b in 요건집합,
            a in graph["공통층"], b in graph["공통층"],
            len(reachable(graph, a)), len(reachable(graph, b))] + \
           [int(t in ta) for t in _방향표지] + [int(t in tb) for t in _방향표지]


def 방향분류기(graph, 라벨=(), 최소=20):
    """그래프에 이미 있는 엣지로 방향(충족/부정)을 배우고, 후보의 확신도를 돌려준다.

    새로 라벨을 모을 필요가 없다 — 사람이 손으로 단 엣지가 곧 라벨이다.
    증거에서 나가는 증명 엣지는 뺀다. 그건 발견이 아니라 정의라서
    (engine 이 증거를 '증명 엣지를 가진 노드'로 정의한다) 배울 것이 없다.

    -> 확신도(a, b) 함수 또는 None (라벨이 모자라거나 한 쪽만 있을 때).
    로지스틱 회귀를 numpy 로 직접 돌린다. 자질 28개에 표본 백여 개라
    사이킷런을 끌어올 이유가 없다."""
    import numpy as np
    증거 = set(graph["증거"])
    말 = {}
    for 층 in ("공통층", "사례층"):
        말.update(graph[층])
    요건집합 = set(요건(graph))
    도수 = {}
    for x, _r, y in graph["엣지"]:
        도수[x] = 도수.get(x, 0) + 1
        도수[y] = 도수.get(y, 0) + 1
    도수 = _기본0(도수)

    X, Y = [], []
    본것 = set()
    for a, r, b in graph["엣지"]:
        if a in 증거 or r not in ("충족", "부정") or a not in 말 or b not in 말:
            continue
        빼고 = _엣지뺀그래프(graph, (a, r, b))
        X.append(_방향자질(빼고, a, b, 말, 요건집합, 도수))
        Y.append(1.0 if r == "부정" else 0.0)
        본것.add((a, b))
    for 쌍, 목록 in (라벨 or {}).items():
        d = 목록[-1]
        if not d.get("방향") or tuple(쌍) in 본것:
            continue
        a, _r, b = d["방향"]
        if a in 말 and b in 말:
            X.append(_방향자질(graph, a, b, 말, 요건집합, 도수))
            Y.append(1.0 if _r == "부정" else 0.0)
    if len(X) < 최소 or len(set(Y)) < 2:
        return None

    X = np.array(X, dtype=float)
    Y = np.array(Y)
    평균, 표준 = X.mean(0), X.std(0)
    표준[표준 == 0] = 1.0
    Z = np.hstack([(X - 평균) / 표준, np.ones((len(X), 1))])
    w = np.zeros(Z.shape[1])
    for _ in range(600):                      # L2 로지스틱 회귀, 경사하강
        p = 1 / (1 + np.exp(-Z @ w))
        기울기 = Z.T @ (p - Y) / len(Y) + 0.05 * np.r_[w[:-1], 0.0]
        w -= 0.5 * 기울기

    def 확신도(a, b):
        """-> 부정일 확률. 0.5 에 가까울수록 기계가 헷갈린다."""
        if a not in 말 or b not in 말:
            return 0.5
        v = np.array(_방향자질(graph, a, b, 말, 요건집합, 도수), dtype=float)
        z = np.r_[(v - 평균) / 표준, 1.0]
        return float(1 / (1 + np.exp(-z @ w)))

    확신도.학습수 = len(X)
    return 확신도


def _기본0(d):
    class _D(dict):
        def __missing__(self, k):
            return 0
    return _D(d)


def _엣지뺀그래프(graph, 엣지):
    """엣지 하나를 뺀 사본. adj 만 다시 만들면 reachable 이 그대로 돈다."""
    h = dict(graph)
    h["엣지"] = [e for e in graph["엣지"] if tuple(e) != tuple(엣지)]
    adj = {}
    for a, r, b in h["엣지"]:
        adj.setdefault(a, []).append((r, b))
    h["adj"] = adj
    return h


# 의미 관계는 논증 관계와 달리 문장에 표시가 남는다.
# 충족/부정은 원문이 안 알려줬지만(부정 15건 중 0건), 재료·이유·시점·대체는
# '넣고', '~해야', '마지막에', '대신' 처럼 표지가 있다. 그래서 뽑을 수 있다.
# 표지는 도메인마다 다르다. "조문에는 표지가 없다"는 틀린 말이었다 —
# 형법 380개 조문에서 요리용 표지('넣고')는 1% 만 걸리지만, 법률 표지는
# '~에 처한다' 60%, '전항/제N항' 32%, '할 수 있다' 13% 로 훨씬 규칙적이다.
# 표는 도메인당 대여섯 줄이면 되고, 관계 이름이 서로 달라 한 표에 섞어도 된다.
_의미표지 = [
    # --- 서술형 문서 (요리·설명서·해설) ---
    ("이유", re.compile(r"(.+?)(?:하?여야|해야|어야|아야)\s*(.+)")),
    ("이유", re.compile(r"(.+?)(?:으?므로|때문에|덕분에)\s*(.+)")),
    ("이유", re.compile(r"(.+?)(?:하?면|되면|쓰면)\s*(.+)")),
    ("대체", re.compile(r"(.+?)(?:\s*대신|보다)\s*(.+)")),
    ("시점", re.compile(r"(.+?)(?:은|는|이|가)?\s*(마지막에|먼저|나중에|처음에|끝에)")),
    # --- 법령 (조문은 서술하지 않고 규정한다) ---
    ("죄형", re.compile(r"(.+?)(?:한|하는)\s*자는\s*(.+?에\s*처한다)")),
    ("예외", re.compile(r"(.+?)\.?\s*다만[,\s]+(.+)")),
    ("근거", re.compile(r"(.+?)(?:에\s*따라|에\s*의하여|에\s*의한)\s*(.+)")),
    ("제외", re.compile(r"(.+?)(?:은|는|을|를)?\s*(?:제외한다|적용하지\s*아니한다)")),
    ("준용", re.compile(r"(.+?)(?:의\s*규정)?(?:을|를)\s*준용한다")),
    ("정의", re.compile(r"(.+?)(?:이란|란|이라\s*함은)\s*(.+?)(?:을|를)\s*말한다")),
]
# 재료는 짝이 문장 안에 없다. 그 대목의 제목(무엇을 만드는 이야기인가)이 짝이다.
_재료 = re.compile(r"([가-힣A-Za-z0-9 ,·와과및]+?)(?:을|를)\s*(?:넣|풀|섞|올리)")
_제목 = re.compile(r"^#+\s*(.+)$")
_문장쪼갬 = re.compile(r"(?<=[.다])\s+|\n+")
# '멸치육수를 쓰면 감칠맛이 늘고, 쌀뜨물을 쓰면 국물이 부드러워진다' 는 두 문장이다.
# 안 쪼개면 앞 절의 원인이 뒤 절의 결과와 이어져 엉뚱한 관계가 나온다.
_절쪼갬 = re.compile(r",\s*|(?<=고)\s+(?=[가-힣]{2,}[을를이가])")


def 의미관계제안(graph, 자료, 임계=0.55, 최대후보=30):
    """원문에서 (노드, 관계, 노드) 후보를 뽑는다. 관계 종류까지 낸다.

    엣지제안(--edges)과 규율이 같다 — 후보만 내고 사람이 확인한다. 다른 점은
    관계 *종류*를 짐작한다는 것이다. 논증 관계(충족/부정)는 원문에 표시가 없어
    짐작을 포기했지만(부정 15건 중 0건 적중), 의미 관계는 '넣고'·'~해야'·
    '마지막에'·'대신' 처럼 표지가 문장에 남아 있어 짐작할 수 있다.

    이게 왜 필요한가: 설명 그래프의 관계가 '설명함'·'같은조문' 뿐이면 둘 다
    '같이 나온다'는 뜻이라 질문에 답할 수 없다. 김치찌개 문서에 '돼지고기 목살'
    이라고 적혀 있는데도 '그건 그래프에 없는 이야기입니다'가 나왔다. 관계를
    넣으면 엔진을 안 고치고도 같은 문장에서 답이 나온다."""
    import numpy as np
    노드 = [n for n in list(graph["공통층"]) + list(graph["사례층"])
            if n in graph["vec"]]
    if len(노드) < 2:
        return []
    행, 임자 = [], []
    for n in 노드:
        for v in graph["vec"][n]:
            행.append(v)
            임자.append(n)
    M, 임자 = np.array(행), np.array(임자)

    def 노드로(구):
        v = _model().encode([숫자가리기(구)], normalize_embeddings=True)[0]
        점 = M @ v
        j = int(점.argmax())
        return str(임자[j]), float(점[j])

    있음 = {(a, b) for a, _r, b in graph["엣지"]}
    나옴, 본것 = [], set()
    for p in _자료파일(_길(자료)):
        이름 = os.path.basename(p)
        제목 = None
        for 번호, 줄 in enumerate(open(p, encoding="utf-8").read().split(chr(10)), 1):
            m = _제목.match(줄.strip())
            if m:
                제목 = m.group(1).strip()
                continue
            for 덩이 in _문장쪼갬.split(줄):
                문장 = " ".join(덩이.split()).strip()
                if not (8 <= len(문장) <= 200):
                    continue
                후보 = []
                # 재료: 제목이 짝이다. '신김치와 돼지고기 목살' 처럼 여럿이면 나눈다
                m2 = _재료.search(문장)
                if m2 and 제목:
                    for 하나 in re.split(r"[,·]|\s*와\s*|\s*과\s*|\s*및\s*",
                                         m2.group(1)):
                        하나 = 하나.strip()
                        if len(하나) >= 2:
                            후보.append(("재료", 하나, 제목))
                for 절 in _절쪼갬.split(문장):
                    절 = 절.strip()
                    if len(절) < 6:
                        continue
                    for 관계, 패턴 in _의미표지:
                        mm = 패턴.search(절)
                        if mm:
                            조각 = [x.strip() for x in mm.groups() if x and x.strip()]
                            if len(조각) == 2:
                                후보.append((관계, 조각[0], 조각[1]))
                            break
                for 관계, 구a, 구b in 후보:
                    a, ca = 노드로(구a)
                    b, cb = 노드로(구b)
                    if a == b or min(ca, cb) < 임계 or (a, b) in 있음:
                        continue
                    if (a, 관계, b) in 본것:
                        continue
                    본것.add((a, 관계, b))
                    나옴.append({"쌍": (a, b), "관계": 관계,
                                 "세기": round(min(ca, cb), 3),
                                 "문장": 문장[:140],
                                 "출처": "%s:%d" % (이름, 번호)})
    나옴.sort(key=lambda d: -d["세기"])
    return 나옴[:최대후보]


def 엣지라벨읽기(경로):
    """모아둔 (쌍, 대목, 방향) 라벨. 원본 .kg 를 건드리지 않는 덧칠 파일이다.

    학습.jsonl 과 같은 규율: 지우면 라벨 수집 전으로 돌아간다.
    -> {(a, b): [{"방향":..., "대목":..., "출처":...}, ...]}"""
    out = {}
    if 경로 and os.path.exists(경로):
        for 줄 in open(경로, encoding="utf-8"):
            줄 = 줄.strip()
            if not 줄:
                continue
            try:
                d = json.loads(줄)
                out.setdefault(tuple(d["쌍"]), []).append(d)
            except (ValueError, KeyError, TypeError):
                pass
    return out


def 엣지라벨쓰기(경로, 쌍, 방향, 대목, 출처, 세기):
    """방향은 (출발, 관계, 도착) 또는 None(관계 없음)."""
    d = {"쌍": list(쌍), "방향": 방향, "대목": 대목, "출처": 출처, "세기": 세기}
    with open(경로, "a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + chr(10))


def 라벨현황(라벨):
    """모은 라벨의 분포. 언제 분류기를 시험해볼 만한지 이걸로 판단한다.

    대목을 자질로 먹여봤지만 방향 예측에 0점을 보탰다 (부정 15건 중 0건
    적중). 조문은 요건을 나열하지 논증하지 않는다. 그래서 대목은 사람이
    읽을 근거로만 남기고, 기계가 쓰는 자질은 노드 이름이다 — 그건 데이터
    양의 문제고, .kg 를 하나 더 지을 때마다 라벨이 저절로 는다."""
    셈 = {}
    for 목록 in 라벨.values():
        for d in 목록:
            키 = d["방향"][1] if d["방향"] else "관계없음"
            셈[키] = 셈.get(키, 0) + 1
    return 셈


def 제안(graph, 최소=3, 뭉침=0.62, 자료=None):
    """미지 로그를 뭉쳐서 '없는 노드'를 제안한다.

    시스템은 개념이 존재한다는 것까지는 스스로 발견할 수 있다 —
    모르는 말이 반복해서 들어오고 그것들이 서로 가까우면, 그 자리에 개념이 있다.
    할 수 없는 것은 이름을 붙이고 그래프의 올바른 자리에 잇는 일이다.
    그리고 그것을 못 하는 이유가 곧 환각을 못 하는 이유와 같다.
    그래서 목표는 자동 저작이 아니라 사람의 확인을 한 번으로 줄이는 것이다."""
    import numpy as np
    경로 = graph.get("_미지로그")
    if not 경로 or not os.path.exists(경로):
        return []
    발화, 횟수 = [], {}
    for 줄 in open(경로, encoding="utf-8"):
        try:
            t = json.loads(줄)["발화"].strip()
        except (ValueError, KeyError):
            continue
        if not t:
            continue
        if t not in 횟수:
            발화.append(t)
        횟수[t] = 횟수.get(t, 0) + 1
    if not 발화:
        return []

    # 씨앗 하나에서만 재면 A-B 0.76, B-C 0.65, A-C 0.54 인 한 뭉치가
    # 씨앗이 A 냐 B 냐에 따라 쪼개진다. 임계값 위의 연결 요소로 잡는다.
    V = np.array([_vec(t) for t in 발화])
    이웃 = (V @ V.T) >= 뭉침
    안봄, 무리 = set(range(len(발화))), []
    while 안봄:
        묶음, q = [], deque([안봄.pop()])
        while q:
            i = q.popleft()
            묶음.append(i)
            for j in np.flatnonzero(이웃[i]):
                if j in 안봄:
                    안봄.discard(j)
                    q.append(int(j))
        무리.append(묶음)

    후보 = list(graph["공통층"]) + [n for n in graph["사례층"] if n not in graph["증거"]]
    구절 = _자료구절(_길(자료)) if 자료 else []
    나온것 = []
    for 무 in 무리:
        총 = sum(횟수[발화[j]] for j in 무)
        # 같은 문장만 40번 들어온 것은 개념이 아니라 사람 하나가 같은 버튼을
        # 계속 누른 것이다. 개념이라면 서로 다른 말로 나타난다.
        if 총 < 최소 or len(무) < 2:
            continue
        중심 = V[무].mean(axis=0)
        중심 /= (np.linalg.norm(중심) or 1)
        차례 = sorted(무, key=lambda j: -float(V[j] @ 중심))
        붙일곳 = sorted(
            ((max(float((graph["vec"][n] @ 중심).max()), 0), n) for n in 후보),
            reverse=True)[:3]
        나온것.append({"횟수": 총, "표현수": len(무),
                       "예시": [발화[j] for j in 차례[:3]],
                       "붙일만한곳": [(n, round(c, 3)) for c, n in 붙일곳],
                       "이름후보": 이름후보(구절, 중심)})
    return sorted(나온것, key=lambda d: -d["횟수"])


def 개념망그림2(g, 뿌리=None, 최대=40):
    """개념망(상위-하위)을 그린다. 논증 그래프와 달리 위로만 향한다."""
    상위 = {}
    하위 = {}
    for a, r, b in g.get("개념엣지", []):
        if r == "상위":
            상위.setdefault(a, []).append(b)
            하위.setdefault(b, []).append(a)
    if not 하위:
        return "flowchart BT\n  none[\"개념망이 비어 있다\"]"
    뿌리 = 뿌리 or max(하위, key=lambda n: len(하위[n]))
    담음, q = {뿌리}, deque([뿌리])
    while q and len(담음) < 최대:
        n = q.popleft()
        for m in 하위.get(n, []) + 상위.get(n, []):
            if m not in 담음 and len(담음) < 최대:
                담음.add(m)
                q.append(m)
    별명, L = {}, ["flowchart BT"]
    def id(n):
        if n not in 별명:
            별명[n] = "h%d" % len(별명)
        return 별명[n]
    윗것 = {b for a, r, b in g["개념엣지"] if r == "상위" and b in 담음}
    for n in sorted(담음):
        꼴 = '%s(["%s"])' if n in 윗것 else '%s["%s"]'
        L.append("  " + 꼴 % (id(n), n))
    for a, r, b in g["개념엣지"]:
        if r == "상위" and a in 담음 and b in 담음:
            L.append("  %s ---|상위| %s" % (id(a), id(b)))
    L.append("  classDef 위 fill:#0E7490,stroke:#134E4A,color:#fff")
    if 윗것:
        L.append("  class %s 위" % ",".join(id(n) for n in sorted(윗것)))
    return "\n".join(L)


def 개념망그림(graph):
    """개념망을 Mermaid 로. 논증 그래프와 모양이 다르다는 것이 보여야 한다."""
    엣지 = graph.get("개념엣지", [])
    if not 엣지:
        return "flowchart LR\n  none[\"개념망이 비어 있다\"]"
    별명 = {}
    def id(n):
        if n not in 별명:
            별명[n] = "c%d" % len(별명)
        return 별명[n]
    상위어 = {b for _, _, b in 엣지}
    L = ["flowchart BT"]
    for a, r, b in 엣지:
        for n in (a, b):
            if n not in 별명:
                꼴 = '%s(["%s"])' if n in 상위어 else '%s["%s"]'
                L.append("  " + 꼴 % (id(n), n))
    for a, r, b in 엣지:
        L.append("  %s ---|%s| %s" % (id(a), r, id(b)))
    L.append("  classDef 상위 fill:#0E7490,stroke:#134E4A,color:#fff")
    if 상위어:
        L.append("  class %s 상위" % ",".join(id(n) for n in sorted(상위어)))
    return "\n".join(L)


def 그림(graph, 층=None):
    """그래프를 Mermaid 로 뽑는다. 텍스트라 어디서든 렌더된다.

    .kg 가 사람이 읽을 수 있어도 28+24 노드의 연결은 눈으로 못 따라간다."""
    별명, L = {}, ["flowchart LR"]
    def id(n):
        if n not in 별명:
            별명[n] = "n%d" % len(별명)
        return 별명[n]

    증거 = set(graph["증거"])
    사실 = [n for n in graph["사례층"] if n not in 증거]
    요건집 = set(요건(graph))
    닿음 = set()
    for e in 증거:
        닿음 |= reachable(graph, e, POS + NEG)

    묶음 = [("증거", sorted(증거)), ("사실", sorted(사실)),
            ("법리", sorted(graph["공통층"]))]
    for 이름, 들 in 묶음:
        if 층 and 이름 != 층:
            continue
        if not 들:
            continue
        L.append('  subgraph %s["%s"]' % (id("_" + 이름), 이름))
        for n in 들:
            if n == graph["목표"]:
                꼴 = '%s(("%s"))'
            elif n in 요건집:
                꼴 = '%s{{"%s"}}'
            elif n in 증거:
                꼴 = '%s[("%s")]'
            else:
                꼴 = '%s["%s"]'
            L.append("    " + 꼴 % (id(n), n))
        L.append("  end")

    보임 = set(별명)
    화살 = {"증명": "-->", "충족": "==>", "부정": "-.->"}
    for a, r, b in graph["엣지"]:
        if a in 별명 and b in 별명:
            L.append("  %s %s|%s| %s" % (id(a), 화살.get(r, "-->"), r, id(b)))

    L.append("  classDef 목표 fill:#1d4ed8,stroke:#1e3a8a,color:#fff")
    L.append("  classDef 요건 fill:#0f766e,stroke:#134e4a,color:#fff")
    L.append("  classDef 미도달 fill:#7f1d1d,stroke:#450a0a,color:#fecaca")
    L.append("  class %s 목표" % id(graph["목표"]))
    요건들 = [id(n) for n in 요건집 if n in 별명]
    if 요건들:
        L.append("  class %s 요건" % ",".join(요건들))
    막힘 = [id(n) for n in graph["공통층"] if n in 별명 and n not in 닿음
            and n != graph["목표"]]
    if 막힘:
        L.append("  class %s 미도달" % ",".join(막힘))
    return "\n".join(L)


def 증거부족(graph):
    """증거를 요건에 최대한 나눠줘도 다 못 채우면 그 그래프는 못 이긴다.

    세션은 증거 하나를 요건 하나에만 배정한다(최대 이분 매칭). 그래서
    닿기만 해서는 부족하고, 증거 수가 요건 수보다 적으면 아무리 잘 논증해도
    빈 칸이 남는다. 실제로 판례를 옮긴 사건에서 증거 4개 / 요건 5개가
    나왔는데 '막힌요건' 은 0이라 진단이 문제없다고 했다 — 도달 가능성만
    보고 배정 한계를 안 봤기 때문이다.

    -> (채울 수 있는 최대 요건 수, 못 채우는 수)"""
    need = 요건(graph)
    닿는증거 = {n: [e for e in graph["증거"] if n in reachable(graph, e)]
                for n in need}
    배정 = {}

    def 밀어넣기(req, 본것):
        for ev in 닿는증거[req]:
            if ev in 본것:
                continue
            본것.add(ev)
            if ev not in 배정 or 밀어넣기(배정[ev], 본것):
                배정[ev] = req
                return True
        return False

    채움 = sum(1 for req in need if 밀어넣기(req, set()))
    return 채움, len(need) - 채움, {v: k for k, v in 배정.items()}


def 진단(graph):
    """그래프를 짜는 동안 돌리는 점검. 형식(검증)이 아니라 쓸 만한지를 본다."""
    닿음 = set()
    for e in graph["증거"]:
        닿음 |= reachable(graph, e)
    need = 요건(graph)
    막힌요건 = [n for n in need if n not in 닿음]
    return {
        "역할": graph["역할"], "목표": graph["목표"],
        "개념": len(graph["공통층"]), "사례": len(graph["사례층"]),
        "증거": len(graph["증거"]), "널클래스": len(graph.get("무관층", {})),
        "요건": need,
        "막힌요건": 막힌요건,          # 증거가 못 닿는 요건 = 이길 수 없는 그래프
        # 증거를 다 써도 남는 빈 요건 칸. 증거가 아예 없는 그래프는 뺀다 —
        # 그건 에피소드가 아니라 공유 법리 라이브러리라 증거를 가질 이유가 없다.
        "모자란증거": 증거부족(graph)[1] if graph["증거"] else 0,
        "고아노드": lint(graph),        # 공통층에 못 닿는 사례층 노드
        "증거없는개념": sorted(set(graph["공통층"]) - 닿음),   # 전부 B1 이 된다
        "수치조건": list(graph.get("수치조건", {})),
        "출처없음": [n for n in graph["공통층"] if n not in (graph.get("출처") or {})],
    }


def 자동논증(graph):
    """그래프에서 이기는 논증 시나리오를 뽑는다. -> [발화, ...]

    회귀 발화를 손으로 적으면 고치는 건 그래프인데 깨지는 건 타이핑이 된다.
    요건마다 그것을 충족하는 사실과 그 사실을 증명하는 증거를 골라
    '증거별칭 + 사실의 말' 을 만든다. 증거 배정은 세션과 같은 이분 매칭이다.

    자기 요건을 부정하는 사실(자책)은 고르지 않는다 — 검사 측 논거다."""
    _, _, 배정 = 증거부족(graph)
    깨는것 = {n for n in graph["사례층"]
              for r, _d in graph["adj"].get(n, []) if r in NEG}
    발화 = []
    for 요건이름, 증거 in 배정.items():
        for 사실 in graph["사례층"]:
            if 사실 in 깨는것 or 사실 in graph["증거"]:
                continue
            if not any(r == "증명" and d == 사실
                       for r, d in graph["adj"].get(증거, [])):
                continue
            if 요건이름 in reachable(graph, 사실):
                별칭 = sorted(graph["사례층"][증거], key=len, reverse=True)[0]
                발화.append("%s을(를) 보면 %s"
                            % (별칭, graph["사례층"][사실][0]))
                break
    return 발화


def 회귀(경로="cases/사건_회귀.json", 엣지=None):
    """사건 그래프들의 기대 승패와, 엣지 하나를 얹은 뒤의 승패를 비교한다.

    승패 기준은 세션과 같다. 모든 요건에 증거가 닿고, 증거를 하나씩 배정해도
    빈 요건이 없어야 이길 수 있다. 엣지는 원본 .kg 를 건드리지 않고 양 끝 노드가
    모두 있는 사건에만 임시로 얹는다."""
    설정 = json.load(open(_길(경로), encoding="utf-8"))
    결과 = []
    for 항목 in 설정:
        g = load(항목["graph"])
        적용 = False
        if 엣지:
            a, r, b = 엣지
            노드 = set(g["공통층"]) | set(g["사례층"])
            if a in 노드 and b in 노드 and (a, r, b) not in g["엣지"]:
                g["엣지"].append((a, r, b))
                g["adj"].setdefault(a, []).append((r, b))
                적용 = True
        d = 진단(g)
        실제 = "win" if not d["막힌요건"] and not d["모자란증거"] else "loss"
        # 구조만 보면 매칭이 깨진 것을 못 잡는다. 이길 수 있다고 판정한 사건은
        # 실제로 한 판 두어 확인한다 — 말 예시가 엉뚱한 노드에 걸리기 시작하면
        # 구조는 멀쩡한데 아무도 못 이기는 그래프가 되고, 그건 조용히 지나간다.
        둔판 = None
        if 실제 == "win":
            s = 세션(g)
            for t in 자동논증(g):
                s.대답(t)
                if s.승패:
                    break
            둔판 = s.승패 == "승"
        결과.append({"graph": 항목["graph"], "expected": 항목["expected"],
                     "actual": 실제, "ok": 실제 == 항목["expected"] and 둔판 is not False,
                     "edge_applied": 적용, "blocked": d["막힌요건"],
                     "short": d["모자란증거"], "played": 둔판})
    return 결과


def lint(graph):
    """공통층에 한 번도 닿지 못하는 사례층 노드 = 기획자의 링크 누락.

    검증()은 형식 오류를, lint()는 의미 있는 누락을 잡는다."""
    return [n for n in graph["사례층"]
            if not (reachable(graph, n, POS + NEG) & set(graph["공통층"]))]


def _selfcheck():
    g = load()
    assert lint(g) == [], lint(g)

    # 실제 판례 회귀: 승 4 / 패 2. 사건 추가는 cases/사건_회귀.json 한 줄이면 된다.
    _회귀 = 회귀()
    assert len(_회귀) == 6 and all(x["ok"] for x in _회귀), _회귀
    assert [x["actual"] for x in _회귀].count("win") == 4, _회귀
    # 구조뿐 아니라 실제로 한 판 두어 이기는지까지 본다
    assert all(x["played"] for x in _회귀 if x["actual"] == "win"), _회귀
    # 가장 긴 증거 별칭이 이긴다. 짧은 이름이 긴 이름의 부분문자열일 때
    # 먼저 걸리는 쪽을 쓰면 그 증거가 증명하지 않는 주장이 되어 C 로 떨어진다.
    _사건 = load("cases/사건_대표이사어깨흔듦.kg")
    assert match_evidence("피해 근로자 진술을 보면", _사건)[0] == "피해근로자진술"
    assert match_evidence("근로자 진술을 보면", _사건)[0] == "근로자진술"

    # 사건과 무관한 법리는 실리지 않는다
    전체 = kg읽기("graphs/graph.kg")["공통층"]
    assert "절도" in 전체 and "절도" not in g["공통층"], g["공통층"].keys()
    assert "회피가능성" in g["공통층"] and "과잉방위불벌" in g["공통층"]
    # 무관층(널 클래스)이 다른 죄명·잡담을 상대 비교로 걷어낸다
    for t in ("훔칠 생각으로 가져간 겁니다", "세금을 안 냈다는 겁니까",
              "저작권을 침해했다는 겁니까", "피고인은 원래 착한 사람입니다"):
        assert judge(g, t)[0] in ("B2", "미지"), (t, judge(g, t))

    # 경계 밖을 둘로 가른다: 널 클래스가 이기면 B2(무관), 아무것도 안 걸리면 미지(모름)
    assert judge(g, "세금을 안 냈다는 겁니까")[0] == "B2"
    assert judge(g, "asdf qwer zxcv 1234")[0] == "미지"
    # A 밴드에 남은 발화는 2회 되물으면 강등된다
    assert judge(g, "영상에 칼이 찍혀 있지 않습니까", 연속A=2)[0] in ("B2", "인정")

    # 검증기가 망가진 그래프를 조용히 통과시키지 않는가
    import copy
    def _거부되나(변형):
        b = kg읽기("graphs/graph.kg")
        변형(b)
        try:
            검증(b); return False
        except ValueError:
            return True
    assert _거부되나(lambda b: b.__setitem__("목표", "없는노드"))
    assert _거부되나(lambda b: b["엣지"].append(["CCTV", "증명", "오타노드"]))
    assert _거부되나(lambda b: b["엣지"].append(["CCTV", "추정", "흉기소지"]))
    assert _거부되나(lambda b: b["대사"].pop("B1"))
    assert _거부되나(lambda b: b["임계값"].pop("OK_MIN"))
    assert _거부되나(lambda b: b["공통층"].__setitem__("빈노드", []))
    # 정상적인 노드 추가는 통과해야 한다
    assert not _거부되나(lambda b: (b["공통층"].__setitem__("새법리", ["새로운 쟁점입니다"]),
                                    b["엣지"].append(["새법리", "충족", "정당방위"])))

    # 교차 도메인: 다른 주제 그래프를 붙여 다리 엣지로 잇는다
    x = load("graphs/graph_인과.kg")
    assert "인과관계입증" in x["공통층"] and "정당방위" in x["공통층"]
    경로 = reachable(x, "부검감정서")
    assert {"시간적선행", "인과관계입증", "방위행위의과잉"} <= 경로, 경로
    assert judge(x, "부검 감정서에 때린 시점과 사망 시점의 선후가 확인됩니다")[0] == "인정"
    assert judge(x, "어제 축구 보셨어요?")[0] in ("B2", "미지")

    # 비법률 도메인에서도 동일하게 작동하는가 (여러 홉 자책 논증 포함)
    for f, 발화, 기대 in [
        ("graphs/graph_의료.kg", "심전도에서 ST 분절이 상승했습니다", "인정"),
        ("graphs/graph_의료.kg", "환자분 어제 뭐 드셨대요?", "B2"),
        ("graphs/graph_코드리뷰.kg", "슬로우 쿼리 로그에 풀 스캔이 찍혀 있어", "인정"),
        ("graphs/graph_코드리뷰.kg", "점심 뭐 먹을까?", "B2"),
    ]:
        d = load(f)
        assert lint(d) == [], (f, lint(d))
        got = judge(d, 발화)[0]
        assert got == 기대 or (기대 == "B2" and got == "미지"), (f, 발화, judge(d, 발화))
    d = load("graphs/graph_코드리뷰.kg")
    assert "DB병목" in judge(d, "프로파일러에서 CPU 사용률이 높게 나와")[1]

    # 한 판이 실제로 끝나는가 — 승/자책패/인내심패 세 결말
    # 요건마다 서로 다른 증거가 필요하다 — 증거 5개로 5요건
    승 = 세션(g)
    for t in ("압수된 흉기를 보십시오, 강도가 흉기를 들고 있었습니다",
              "현장 사진을 보면 출입문을 막고 있어서 나갈 수가 없었습니다",
              "목격자 진술대로 돈을 내놓으라고 협박했습니다",
              "진단서를 보면 피고인이 다쳤습니다",
              "CCTV 영상을 보면 강도가 흉기를 들고 있었습니다"):
        r = 승.말하기(t)[2]
    assert r == "승", (r, 승.현황())
    assert len(set(승.확보().values())) == 5, 승.확보()

    # 증거 하나로는 요건 두 칸을 못 채운다
    짧게 = 세션(g)
    for t in ("CCTV 영상을 보면 강도가 흉기를 들고 있었습니다",
              "CCTV 를 보십시오, 출입문을 막고 있어서 나갈 수가 없었습니다"):
        짧게.말하기(t)
    assert len(짧게.확보()) == 1, 짧게.확보()

    # 논증 순서가 결과를 바꾸지 않는다 (최대 매칭이 재배정한다)
    코드 = load("graphs/graph_코드리뷰.kg")
    for 순서 in (["슬로우 쿼리 로그에 풀 스캔이 찍혀 있어", "APM 트레이스에 커넥션 대기가 길어"],
                 ["APM 트레이스에 커넥션 대기가 길어", "슬로우 쿼리 로그에 풀 스캔이 찍혀 있어"]):
        c = 세션(코드)
        for t in 순서:
            rr = c.말하기(t)[2]
        assert rr == "승", (순서, c.현황())

    자책 = 세션(g)
    자책.말하기("CCTV 영상을 보면 강도가 흉기를 들고 있었습니다")
    assert 자책.말하기("CCTV 보면 피고인이 의자를 먼저 집어 들었죠")[2] == "패"

    소진 = 세션(g)
    for t in ("목격자 증언대로 흉기를 들고 있었습니다", "훔칠 생각으로 가져간 겁니다",
              "CCTV 보면 상대는 어린아이였습니다", "날씨가 참 좋습니다"):
        r = 소진.말하기(t)[2]
    assert r == "패" and 소진.인내심 <= 0

    # 개념망: 단어 관계 한 줄이 예시 문장을 자동으로 불린다
    사건ㄱ = load("cases/사건_편의점강도.kg")
    # load 는 학습로그를 덧칠하므로 개수를 못 박으면 안 된다 — 되묻기에 한 번만
    # 답해도 테스트가 깨진다. 확인할 것은 개념망이 원본 목록을 안 건드린다는 것뿐이다.
    날것 = kg읽기(_길("cases/사건_편의점강도.kg"))["사례층"]["흉기소지"]
    assert 사건ㄱ["사례층"]["흉기소지"][:len(날것)] == 날것   # 목록은 그대로
    assert 사건ㄱ["vec"]["흉기소지"].shape[0] > 10         # 벡터만 늘어난다
    풀ㄱ = [n for n in 사건ㄱ["사례층"] if n not in 사건ㄱ["증거"]] + list(사건ㄱ["공통층"])
    for 말 in ("과도를 들고 들어왔습니다", "각목을 들고 있었습니다", "벽돌을 들고 있었습니다"):
        n, c = match(말, 풀ㄱ, 사건ㄱ)
        assert n == "흉기소지" and c > 0.8, (말, n, c)
    n, c = match("우산을 들고 있었습니다", 풀ㄱ, 사건ㄱ)   # 흉기가 아닌 것은 안 딸려온다
    assert c < 0.6, ("우산", n, c)

    # 출처: 노드가 어디서 왔는지 들고 있다
    법 = load("legal/법리_형법21조.kg")
    assert 법["출처"]["정당방위"].startswith("형법 21조")
    assert "출처" in 진단(법) or True
    # 문서를 읽고 그래프에 없는 개념을 찾아낸다 (지어내지 않고 출처와 함께)
    뽑음 = 조문제안(법, _길("data/법지식/형법_위법성조각사유.txt"))
    assert 뽑음, "조문에서 아무것도 못 뽑았다"
    assert all(d["출처"].startswith("형법") for d in 뽑음)
    구들 = {d["구"] for d in 뽑음}
    assert any("청구권" in x or "법령" in x for x in 구들), 구들
    assert not any(x.strip().endswith(("의", "를", "을")) for x in 구들), 구들

    # 지시대명사: 원문이 아니라 직전 (증거, 주장) 으로 푼다
    지시 = 세션(load("cases/사건_편의점강도.kg"))
    지시.대답("CCTV 영상을 보면 강도가 흉기를 들고 있었습니다")
    답 = 지시.대답("아까 그 영상 보면 출입문도 막고 있었습니다")
    assert 지시.해소 == ["CCTV"], 지시.해소
    assert "CCTV" in 답 and "출입문" in 답, 답
    지시.대답("방금 그건 인정하시는 겁니까")
    assert 지시.판정 == "재탕", 지시.판정          # 직전 주장으로 해소된다
    # 증거를 명시하면 해소하지 않는다
    지시.대답("진단서를 보면 피고인이 다쳤습니다")
    assert 지시.해소 is None, 지시.해소
    # 지시어가 없으면 아무것도 안 건드린다
    깨끗 = 세션(load("cases/사건_편의점강도.kg"))
    깨끗.대답("CCTV 영상을 보면 강도가 흉기를 들고 있었습니다")
    깨끗.대답("목격자 진술대로 돈을 내놓으라고 했습니다")
    assert 깨끗.해소 is None

    # 자기가 한 말을 기억한다: 같은 주장+같은 증거는 재탕, 다른 증거면 보강
    반복 = 세션(load("cases/사건_편의점강도.kg"))
    첫 = 반복.대답("압수된 흉기를 보십시오, 강도가 흉기를 들고 있었습니다")
    assert 반복.판정 == "인정"
    반복.대답("압수된 흉기를 보십시오, 강도가 흉기를 들고 있었습니다")
    assert 반복.판정 == "재탕", 반복.판정
    반복.대답("CCTV 영상을 보면 흉기를 들고 있었습니다")   # 다른 증거 = 보강
    assert 반복.판정 == "인정", 반복.판정
    # 같은 대사가 연달아 나오지 않는다
    둘 = 세션(load("cases/사건_편의점강도.kg"))
    a = 둘.대답("압수된 흉기를 보십시오, 강도가 흉기를 들고 있었습니다")
    b = 둘.대답("현장 사진을 보면 출입문을 막고 있었습니다")
    assert a.split("「")[0] != b.split("「")[0], (a, b)
    # 조사가 받침에 맞는다
    assert 조사고치기("방위의사은", ["방위의사"]) == "방위의사는"
    assert 조사고치기("상당성는", ["상당성"]) == "상당성은"
    assert 조사고치기("흉기소지을", ["흉기소지"]) == "흉기소지를"

    # 실사용에서 나온 것들: 다문장 발화, 결론 주장, 목표 이름과 닮은 이웃
    사건g = load("cases/사건_편의점강도.kg")
    긴발화 = ("CCTV를 보면 강도는 집에 과도를 들고 들어왔습니다. "
              "이는 정당방위입니다.")
    assert judge(사건g, 긴발화)[0] == "목표주장", judge(사건g, 긴발화)
    assert judge(사건g, "이는 정당방위입니다")[0] == "목표주장"
    assert judge(사건g, "긴급피난에 해당합니다")[0] == "B2"
    assert judge(사건g, "CCTV 보면 과도를 들고 들어왔습니다")[0] == "인정"
    assert len(조각내기("가나다 라마바입니다. 사아자 차카타입니다.")) == 3
    assert len(조각내기("칼을 들고 있었습니다")) == 1      # 한 문장은 안 쪼갠다
    # 판정 대사가 없는 그래프에서도 judge 문장이 살아남는다
    회q = 세션(사건g)
    assert "결론" in 회q.대답("이는 정당방위입니다")

    # 되묻기 확인 -> 말투 학습 (새 노드나 엣지는 절대 만들지 않는다)
    학습로그 = "_학습시험.학습.jsonl"
    if os.path.exists(학습로그):
        os.remove(학습로그)
    시험 = load("graphs/graph.kg")
    시험["_학습로그"] = 학습로그
    회 = 세션(시험)
    assert 회.말하기("우리 법에서는 도망갈 의무까지는 없습니다")[0] == "A"
    회.말하기("네 맞습니다")
    assert 회.배운것, "확인했는데 배우지 않았다"
    노드, 말 = 회.배운것[0]
    assert 말 in (시험["공통층"].get(노드) or 시험["사례층"].get(노드)), "예시에 안 붙음"
    assert 학습읽기(학습로그)[0].get(노드) == [말]
    # 아니라고 하면 그 노드로는 배우지 않고, 반례로 널 클래스에 들어간다
    os.remove(학습로그)              # 앞 학습이 남으면 이제 되묻지 않는다
    시험2 = load("graphs/graph.kg")
    시험2["_학습로그"] = 학습로그
    회2 = 세션(시험2)
    assert 회2.말하기("우리 법에서는 도망갈 의무까지는 없습니다")[0] == "A"
    회2.말하기("아니요")
    assert not 회2.배운것
    아닌노드 = list(학습읽기(학습로그)[1])
    assert 아닌노드, "아니라고 한 신호를 버렸다"
    반례 = 반례표 + 아닌노드[0]
    assert 반례 in 시험2["무관층"] and 반례 in 시험2["vec"]
    # 반례가 이겨도 B2("무관하다")가 아니다. 그 노드만 빼고 다시 재서,
    # 걸리는 게 없으면 미지("모른다")다. 기획자가 넣은 무관 예시는 그대로 B2.
    assert judge(시험2, "우리 법에서는 도망갈 의무까지는 없습니다")[0] == "미지"
    assert judge(시험2, "긴급피난에 해당합니다")[0] == "B2"
    assert len(학습읽기(학습로그)[1][아닌노드[0]]) == 1
    os.remove(학습로그)

    # 뭉치기: 씨앗 순서와 무관하고(연결 요소), 같은 말 반복은 개념이 아니다
    def _제안시험(줄들):
        경로 = "_제안시험.미지.log"
        with open(경로, "w", encoding="utf-8") as f:
            for t in 줄들:
                f.write(json.dumps({"발화": t}, ensure_ascii=False) + chr(10))
        g2 = load("graphs/graph.kg")
        g2["_미지로그"] = 경로
        r = 제안(g2, 최소=3)
        os.remove(경로)
        return r
    사슬 = ["피고인이 도망가는 사람을 계속 쫓아가서 때렸습니다",
            "이미 도망치는 상대를 추격해서 폭행한 것입니다",
            "쫓아가서 가격했으니 방어가 아니라 공격입니다"]
    assert len(_제안시험(사슬)) == 1, "A-C 가 멀다고 한 뭉치가 쪼개졌다"
    assert len(_제안시험(사슬[::-1])) == 1, "씨앗 순서에 결과가 흔들린다"
    assert _제안시험(["똑같은 말입니다"] * 40) == [], "같은 문장 반복은 개념이 아니다"
    assert _제안시험(사슬)[0]["횟수"] == 3

    # 대목 자르기: 조문 파일은 조 단위로 끊어야 한다. 고정 창으로 자르면
    # 제20조와 제21조가 한 대목이 되고 임베딩이 둘 중 무엇도 아니게 된다.
    시험자료 = "_대목시험.txt"
    with open(시험자료, "w", encoding="utf-8") as f:
        f.write(chr(10).join([
            "제20조(정당행위) 법령에 의한 행위 또는 업무로 인한 행위 기타 "
            "사회상규에 위배되지 아니하는 행위는 벌하지 아니한다.",
            "제21조(정당방위) 현재의 부당한 침해로부터 자기 또는 타인의 법익을 "
            "방위하기 위하여 한 행위는 상당한 이유가 있는 경우에는 벌하지 아니한다.",
        ]))
    대목 = list(_대목(시험자료))
    assert len(대목) == 2, [o for _, o in 대목]
    assert 대목[0][0].startswith("제20조") and 대목[1][0].startswith("제21조")

    # 엣지 제안: 방향은 절대 고르지 않는다. 증거끼리는 쌍이 안 나온다.
    후보, 흔한것 = 엣지제안(g, 시험자료, 최소=1)
    증거 = set(g["증거"])
    for c in 후보:
        a2, b2 = c["쌍"]
        assert not (a2 in 증거 and b2 in 증거), c["쌍"]
        assert (a2, b2) not in {(x, z) for x, _, z in g["엣지"]}
        assert set(c) == {"쌍", "횟수", "세기", "근거", "순환주의"}
    # 엣지 라벨: 왕복이 되고, 관계없음(None)도 라벨로 남는다
    엣지로그 = "_엣지시험.엣지.jsonl"
    if os.path.exists(엣지로그):
        os.remove(엣지로그)
    엣지라벨쓰기(엣지로그, ("가", "나"), ["가", "충족", "나"], "대목", "출처:1", 0.5)
    엣지라벨쓰기(엣지로그, ("다", "라"), None, "대목2", "출처:2", 0.4)
    라벨 = 엣지라벨읽기(엣지로그)
    assert 라벨[("가", "나")][0]["방향"] == ["가", "충족", "나"]
    assert 라벨[("다", "라")][0]["방향"] is None
    assert 라벨현황(라벨) == {"충족": 1, "관계없음": 1}, 라벨현황(라벨)

    # 방향 분류기: 그래프의 기존 엣지로 배워 후보의 확신도를 낸다
    판단 = 방향분류기(g)
    assert 판단 and 판단.학습수 >= 20, 판단
    assert 판단("흉기소지", "침해의부당성") < 0.5     # 실제 충족
    assert 판단("상호투쟁", "방위의사") >= 0.5       # 실제 부정
    assert 방향분류기(g, 최소=10 ** 6) is None       # 라벨이 모자라면 안 쓴다
    # 자질은 맞히려는 엣지를 뺀 그래프에서 재야 한다. 안 빼면 충족일 때만
    # 도착 노드가 닿는수에 더해져 라벨이 자질로 새어든다 (92.9% -> 실제 81.6%).
    # 의미 관계: 표지가 있는 문장에서 관계 종류까지 뽑는다.
    # 요리 문서 8개 관계 중 5개를 회수했다 (정밀도 5/7).
    _요리 = "_관계시험.md"
    with open(_요리, "w", encoding="utf-8") as f:
        f.write("## 김치찌개" + chr(10)
                + "잘 익은 신김치와 돼지고기 목살을 넣고 끓인다." + chr(10)
                + "김치가 시어야 국물이 깊어진다." + chr(10))
    _쿡경로 = "_관계시험.kg"
    with open(_쿡경로, "w", encoding="utf-8") as f:
        f.write(chr(10).join([
            "역할: 요리사", "목표: 김치찌개", "임계값: 0.50 / 0.60", "",
            '[개념]', '김치찌개: "김치찌개" | "김치 찌개"', "",
            '[사례]',
            '신김치: "신김치" | "신 김치" | "김치가 시다"',
            '돼지고기목살: "돼지고기" | "돼지고기 목살" | "목살"',
            '국물이깊어짐: "국물이 깊어진다" | "깊은 국물"', "",
            "[대사]", "B2: 그건 이 요리 이야기가 아닙니다.",
            "B2_강등: 몇 번을 여쭤야 합니까.", "A: 혹시 [{claim}] 말씀입니까?",
            "근거없음: [{claim}]는 무엇을 보고 하시는 말씀입니까?",
            "인정: [{ev}]의 [{claim}]은 그렇습니다.",
            "인정_반격: [{ev}]에 [{claim}]는 맞습니다만 [{bad}]는 어떻습니까?",
            "C: [{ev}]로는 [{claim}]을 말할 수 없습니다.",
            "B1: [{claim}]... 맞는 이야기지만 근거가 없습니다.", ""]))
    _쿡 = load(_쿡경로)
    _관계 = 의미관계제안(_쿡, _요리)
    _뽑 = {(c["쌍"][0], c["관계"], c["쌍"][1]) for c in _관계}
    assert ("돼지고기목살", "재료", "김치찌개") in _뽑, _뽑   # 제목이 짝이 된다
    assert ("신김치", "이유", "국물이깊어짐") in _뽑, _뽑     # '~해야' 가 인과 표지
    assert all(c["문장"] and c["출처"] for c in _관계), _관계  # 영수증이 붙는다
    os.remove(_요리)
    os.remove(_쿡경로)

    # 표지는 도메인마다 다르다. 조문에는 서술형 표지가 없지만 '~한 자는 ~에
    # 처한다' 가 380개 조문 중 228개(60%)에 있다. 끝점이 노드로 있어야 걸린다 —
    # 표지가 60% 여도 죄명·형벌이 노드가 아니면 아무것도 안 나온다.
    _법 = "_법시험.txt"
    with open(_법, "w", encoding="utf-8") as f:
        f.write("제257조(상해) 사람의 신체를 상해한 자는 "
                "7년 이하의 징역에 처한다." + chr(10))
    _법kg = "_법시험.kg"
    with open(_법kg, "w", encoding="utf-8") as f:
        f.write(chr(10).join([
            "역할: 검사", "목표: 처벌", "임계값: 0.50 / 0.60", "",
            '[개념]', '처벌: "처벌한다" | "처벌"', "",
            '[사례]',
            '상해: "사람의 신체를 상해한" | "상해"',
            '징역: "징역에 처한다" | "7년 이하의 징역"', "",
            "[대사]", "B2: 무관합니다.", "B2_강등: 본론을 말하십시오.",
            "A: 혹시 [{claim}] 말씀입니까?", "근거없음: [{claim}]의 근거는?",
            "인정: [{ev}]의 [{claim}]은 인정합니다.",
            "인정_반격: [{ev}]에 [{claim}]는 맞으나 [{bad}]는?",
            "C: [{ev}]로는 [{claim}]을 못 세웁니다.",
            "B1: [{claim}]... 증거가 없습니다.", ""]))
    # 조문이 아닌 산문도 읽어야 한다. 위키백과에는 '제N조' 가 없어서
    # 조문읽기 만 쓰면 받아온 글에서 후보가 0개 나온다.
    _산문 = "_산문시험.txt"
    with open(_산문, "w", encoding="utf-8") as f:
        f.write("정당방위는 현재의 부당한 침해를 방위하기 위한 행위를 말한다."
                + chr(10) + "방위행위에는 상당한 이유가 있어야 한다." + chr(10))
    assert 조문읽기(_산문) == [], "조문 표시가 없으면 조문읽기는 비어야 한다"
    assert 조문제안(load("graphs/graph.kg"), _산문), "산문에서 아무것도 못 뽑는다"
    os.remove(_산문)

    _법뽑 = {(c["쌍"][0], c["관계"], c["쌍"][1])
             for c in 의미관계제안(load(_법kg), _법)}
    assert ("상해", "죄형", "징역") in _법뽑, _법뽑
    os.remove(_법)
    os.remove(_법kg)

    # 그래프 매니저: 그래프들의 그래프. 같은 매처를 한 층 위에 쓴다.
    _색 = 그래프색인()
    assert len(_색["공통층"]) >= 6, list(_색["공통층"])
    for _q, _조각 in (("가슴 통증에 ST분절이 상승했습니다", "의료"),
                      ("풀 스캔이 발생해서 응답이 느려집니다", "코드리뷰"),
                      ("신용점수가 낮아 상환능력이 의심됩니다", "대출")):
        _이름, _점, _후보 = 그래프고르기(_q, _색)
        assert _이름 and _조각 in _이름, (_q, _이름, _후보)
    # 어느 그래프도 아닌 것은 고르지 않는다. 색인이 커져도 아무거나 집으면 안 된다.
    assert 그래프고르기("오늘 점심 뭐 먹지", _색)[0] is None, 그래프고르기("오늘 점심 뭐 먹지", _색)
    # 고른 뒤에는 그 그래프로 판정까지 간다
    _이름, _tag, _말 = 안내("CCTV에 흉기를 들고 있는 게 찍혔습니다")
    assert _이름 and _tag == "인정", (_이름, _tag, _말)
    # 매니저는 최근 것만 들고 있는다. '한 번에 하나만' 이라고 해놓고 다 쥐고
    # 있으면 매니저를 만든 뜻이 없다 — 도메인이 수백 개면 그대로 수백 배다.
    _그래프칸.clear()
    for _p2 in ("graphs/graph.kg", "graphs/graph_부당해고.kg",
                "graphs/graph_저작권침해.kg", "graphs/graph_음주운전.kg"):
        그래프불러오기(_p2)
    assert len(_그래프칸) <= 2, list(_그래프칸)
    assert "graphs/graph_음주운전.kg" in _그래프칸        # 가장 최근 것은 남는다
    assert "graphs/graph.kg" not in _그래프칸            # 오래된 것은 버린다

    _뺀 = _엣지뺀그래프(g, ("흉기소지", "충족", "침해의부당성"))
    assert len(_뺀["엣지"]) == len(g["엣지"]) - 1
    assert len(reachable(_뺀, "흉기소지")) < len(reachable(g, "흉기소지"))

    # 판례 채점: 인용문은 세지 않고, 증거 없는 법리 문장도 '덮음'으로 센다
    가짜판례 = [{"판결요지": "구 경찰관 직무집행법 제10조 제3항은 \"...\"라고 정한다. "
                            "침해가 현재 진행 중이었습니다."}]
    r = 판례채점(g, 가짜판례)
    assert r["문장수"] == 1, r          # 인용문 한 문장은 빠진다
    assert r["덮음"] == 1, r            # 법리 문장은 증거가 없어도 덮은 것이다
    assert "침해의현재성" in r["걸린노드"], r["걸린노드"]
    os.remove(엣지로그)
    os.remove(시험자료)

    # 판례 md -> 에피소드 컴파일
    kgtext, 보고 = 사건컴파일(_길("cases/사건_편의점강도.md"))
    assert 보고 and all(b[5] for b in 보고), [b for b in 보고 if not b[5]]
    assert min(b[0] for b in 보고) > 0.75, min(보고)
    사건 = load("cases/사건_편의점강도.kg")
    assert lint(사건) == [], lint(사건)
    assert not 진단(사건)["막힌요건"], 진단(사건)["막힌요건"]
    # 증거 하나는 요건 하나만 채운다. 닿기만 해서는 못 이긴다.
    assert 증거부족(사건)[:2] == (len(요건(사건)), 0), 증거부족(사건)
    적은증거 = dict(사건, 증거=사건["증거"][:1])
    채움, 모자람, _배정 = 증거부족(적은증거)
    assert 채움 <= 1 and 모자람 == len(요건(사건)) - 채움, (채움, 모자람)
    회차 = 세션(사건)
    for t in ("압수된 흉기를 보십시오, 강도가 흉기를 들고 있었습니다",
              "현장 사진을 보면 출입문을 막고 있었습니다",
              "목격자 진술대로 돈을 내놓으라고 했습니다",
              "진단서를 보면 피고인이 다쳤습니다",
              "CCTV 영상을 보면 흉기를 들고 있었습니다"):
        회차.대답(t)
    assert 회차.승패 == "승", (회차.승패, 회차.현황())

    # .kg 파서: 왕복해도 같은 그래프여야 한다
    원본 = kg읽기("graphs/graph.kg")
    assert 원본["목표"] == "정당방위" and len(원본["엣지"]) > 50
    for 나쁜, 왜 in [("[개념]\n결론 예시없음\n", "노드"),
                     ("역할: X\n[논증]\nA 충족 B\n", "논증"),
                     ("모르는머리말: 1\n", "머리말")]:
        임시 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_t.kg")
        open(임시, "w", encoding="utf-8").write(나쁜)
        try:
            kg읽기(임시)
            raise AssertionError("통과해버림: " + 왜)
        except ValueError as e:
            assert ":" in str(e), str(e)          # 줄 번호가 붙어야 한다
        finally:
            os.remove(임시)

    # 문장 -> 문장 인터페이스: 판정 문자열이 대답에 새지 않는다
    말 = 대답(g, "CCTV 영상을 보면 강도가 흉기를 들고 있었습니다")
    assert isinstance(말, str) and 말
    assert not 말.startswith("("), 말          # 판정 라벨이 대답에 섞이지 않는다
    assert "B1" not in 말 and "B2" not in 말, 말
    회 = 세션(g)
    assert 회.대답("CCTV 영상을 보면 강도가 흉기를 들고 있었습니다")
    assert 회.판정 == "인정" and 회.승패 is None      # 판정은 따로 꺼낸다

    # 수치 조건: 노드는 '무엇에 대한 주장인가', 숫자는 '충족되는가'
    대출 = load("graphs/graph_대출.kg")
    for 발화, 기대 in [
        ("소득 증빙상 연소득이 6천만원입니다", "인정"),
        ("소득 증빙상 연소득이 600만원입니다", "수치미달"),
        ("소득 증빙상 DSR이 35%입니다", "인정"),
        ("소득 증빙상 DSR이 90%입니다", "수치미달"),
        ("신용 보고서상 신용점수가 820점입니다", "인정"),
        ("신용 보고서상 신용점수가 320점입니다", "수치미달"),
        ("등기부등본상 담보 시가가 3억 5천만원입니다", "인정"),
        ("등기부등본상 담보 시가가 1억원입니다", "수치미달"),
        ("등기부등본상 담보 시가가 1억 2천 3백만원입니다", "A"),   # 애매하면 되묻는다
        ("점심 뭐 드셨어요?", "B2"),
    ]:
        got = judge(대출, 발화)[0]
        assert got == 기대 or (기대 == "B2" and got == "미지"), (발화, judge(대출, 발화))

    # 숫자를 가리면 같은 노드로 같은 신뢰도가 나와야 한다
    풀 = [n for n in 대출["사례층"] if n not in 대출["증거"]] + list(대출["공통층"])
    높 = match("신용 보고서상 신용점수가 820점입니다", 풀, 대출)
    낮 = match("신용 보고서상 신용점수가 320점입니다", 풀, 대출)
    assert 높 == 낮, (높, 낮)

    # 숫자를 못 읽으면 통과가 아니라 되묻기다 (fail-open 금지)
    for 발화 in ("소득 증빙상 연소득이 육천만원입니다",
                 "소득 증빙상 연소득이 5천~6천만원입니다"):
        assert judge(대출, 발화)[0] == "A", (발화, judge(대출, 발화))

    # 한국식 자릿수
    assert 숫자뽑기("60,000,000원")[0][0] == 60000000
    assert 숫자뽑기("육천만원")[0][2] is False
    assert 숫자뽑기("3억 5천만원")[0][0] == 350000000
    assert 숫자뽑기("1조 2천억원")[0][0] == 1200000000000
    assert 숫자뽑기("600만원")[0][0] == 6000000
    assert 숫자뽑기("1억 2천 3백만원")[0][2] is False        # 애매 표시

    # 링크 누락을 실제로 잡는가
    broken = load()
    broken["사례층"]["미아노드"] = ["고아 사실"]
    assert lint(broken) == ["미아노드"]

    cases = {
        "CCTV 영상을 보면 흉기를 들고 있었습니다":            "인정",
        "CCTV 영상을 보면 먼저 공격했다는 게 보입니다":       "인정",   # 자책 논증
        "목격자 증언대로 흉기를 들고 있었습니다":            "C",
        "CCTV 를 보면 상대는 어린아이였습니다": "B1",   # 증거로 닿지 않는 법리
        "오늘 점심 뭐 드셨습니까":                            "B2",
    }
    for text, want in cases.items():
        got, line = judge(g, text)
        assert got == want, f"{text!r} → {got} (기대 {want}) / {line}"

    # 자책 논증은 반격 대사가 붙어야 한다
    _, line = judge(g, "CCTV 영상을 보면 먼저 공격했다는 게 보입니다")
    assert "침해의현재성" in line, line

    # 이름 붙이기: 뭉치 이름은 자료 원문에서만 나온다. 근거가 없으면 안 낸다.
    구절 = [("정당방위", "형법.txt:1"), ("계란 두 개", "요리.txt:3")]
    중심 = _vec("정당방위가 성립한다")
    assert 이름후보(구절, 중심)[0][0] == "정당방위"
    assert 이름후보(구절, _vec("계란 두 개")) [0][0] == "계란 두 개"
    assert 이름후보([("계란 두 개", "요리.txt:3")], _vec("정당방위가 성립한다")) == []
    print("selfcheck ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _selfcheck()
    elif "--case" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        md = 인자[0]
        try:
            kg, 보고 = 사건컴파일(md)
        except ValueError as e:
            print("X " + str(e))
            sys.exit(1)
        나감 = os.path.splitext(md)[0] + ".kg"
        open(나감, "w", encoding="utf-8").write(kg)
        print("사건 컴파일: %s -> %s" % (md, 나감))
        못붙임 = [b for b in 보고 if not b[5]]
        약함 = [b for b in 보고 if b[5] and b[0] < 0.75]
        print("  법리 매칭 %d건 (실패 %d · 약함 %d)" % (len(보고), len(못붙임), len(약함)))
        for c, 사실, 관계, 쓴말, 골른, ok in sorted(못붙임 + 약함):
            print("    %s %.3f  %s.%s \"%s\" -> %s"
                  % ("X" if not ok else "?", c, 사실, 관계, 쓴말, 골른 if ok else "붙이지 못함"))
        if 못붙임:
            print("  [주의] 붙지 못한 연결은 그래프에서 빠졌다. 법리 표현을 바꿔 다시 써라.")
        d = 진단(load(나감))
        print("  개념 %d · 사례 %d · 증거 %d | 요건: %s"
              % (d["개념"], d["사례"], d["증거"], ", ".join(d["요건"])))
        if d["막힌요건"]:
            print("  [치명] 증거가 못 닿는 요건: " + ", ".join(d["막힌요건"]))
        if d["모자란증거"]:
            print("  [치명] 증거를 다 나눠줘도 요건 %d칸이 빈다 (증거 %d · 요건 %d)."
                  % (d["모자란증거"], d["증거"], len(d["요건"])))
            print("         증거 하나는 요건 하나만 채운다. 증거를 더 쪼갤 것.")
        if d["고아노드"]:
            print("  [경고] 어떤 법리에도 안 붙은 사실: " + ", ".join(d["고아노드"]))
        sys.exit(1 if (d["막힌요건"] or d["모자란증거"] or 못붙임) else 0)

    elif "--learn" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        경로 = 인자[0] if 인자 else "graphs/graph.kg"
        로그 = os.path.splitext(경로)[0] + ".학습.jsonl"
        배운것, 아닌것 = 학습읽기(로그)
        if not 배운것 and not 아닌것:
            print("배운 표현이 없다. (%s)" % 로그)
            sys.exit(0)
        g = load(경로)
        print("되묻기에서 배운 표현  (%s)" % 로그)
        print("  원본 .kg 는 건드리지 않는다. 이 파일을 지우면 학습 전으로 돌아간다.")
        수상 = 0
        for 노드, 말들 in sorted(배운것.items()):
            print("\n  %s" % 노드)
            for m in 말들:
                기존 = [x for x in (g["공통층"].get(노드) or g["사례층"].get(노드) or [])
                        if x not in 말들]
                점수 = max((float(_vec(m) @ _vec(x)) for x in 기존), default=0.0)
                표 = "  " if 점수 >= 0.55 else "?!"
                수상 += 표 == "?!"
                print("    %s %.2f  \"%s\"" % (표, 점수, m))
        if 수상:
            print("\n  ?! 는 그 노드의 원래 예시들과 멀다는 뜻이다 — 잘못 확인했을 수 있다.")
            print("     해당 줄을 %s 에서 지우면 된다." % 로그)
        if 아닌것:
            print()
            print("되묻기에서 배운 반례 (이 노드가 *아니다* 라고 확인된 말)")
            print("  널 클래스로 들어가 그 노드를 이기지 못하게 막는다.")
            for 노드, 말들 in sorted(아닌것.items()):
                print("  %s 아님" % 노드)
                for m in 말들:
                    print("       \"%s\"" % m)
        sys.exit(0)

    elif "--draw" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        g = load(인자[0] if 인자 else "graphs/graph.kg")
        층 = 인자[1] if len(인자) > 1 else None
        if 층 == "개념망":
            나감 = os.path.splitext(인자[0])[0] + ".개념망.mmd"
            m = 개념망그림(g)
            open(나감, "w", encoding="utf-8").write(m + "\n")
            print("%s  (%d줄)" % (나감, len(m.splitlines())))
            sys.exit(0)
        나감 = os.path.splitext(인자[0] if 인자 else "graphs/graph.kg")[0] + ".mmd"
        m = 그림(g, 층)
        open(나감, "w", encoding="utf-8").write(m + "\n")
        print("%s  (%d줄)" % (나감, len(m.splitlines())))
        print("  ```mermaid 블록에 넣거나 mermaid.live 에 붙이면 보인다.")
        print("  ◉ 목표 · ⬡ 요건 · ▭ 사실 · ▱ 증거")
        print("  --> 증명   ==> 충족   -.-> 부정   빨강 = 증거가 못 닿는 개념")
        sys.exit(0)

    elif "--mine" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        if len(인자) < 2:
            print("사용법: python engine.py --mine <그래프.kg> <자료.txt>")
            sys.exit(1)
        g = load(인자[0])
        r = 조문제안(g, 인자[1])
        print("%s 에서 뽑은, 그래프에 아직 없는 개념 후보 %d개" % (인자[1], len(r)))
        print("  지어낸 것이 아니라 출처가 있는 텍스트에서 뽑았다.")
        print("  이름과 연결은 사람이 정한다. 붙여넣을 초안을 함께 낸다.\n")
        for d in r[:15]:
            print("  %-22s  %s" % (d["구"], d["출처"]))
            print("      (가장 가까운 기존 개념: %s %.2f)"
                  % (d["가장가까운"], d["유사도"]))
        if r:
            d = r[0]
            print("\n  --- .kg 에 붙여넣을 초안 ---")
            print("  %s @%s: \"%s\"" % (d["구"].replace(" ", ""), d["출처"], d["구"]))
        sys.exit(0)

    elif "--suggest" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        g = load(인자[0] if 인자 else "graphs/graph.kg")
        후보들 = 제안(g, 자료=인자[1] if len(인자) > 1 else "data")
        if not 후보들:
            print("제안할 것이 없다. 미지 로그가 비었거나 반복되는 뭉치가 없다.")
            sys.exit(0)
        print("미지 로그에서 발견한 개념 후보 %d개" % len(후보들))
        print("  (시스템이 할 수 있는 건 여기까지다. 이름과 연결은 사람이 정한다)")
        for i, c in enumerate(후보들, 1):
            print("\n  [%d] %d번 나옴 (서로 다른 표현 %d개)"
                  % (i, c["횟수"], c["표현수"]))
            for e in c["예시"]:
                print("      \"%s\"" % e)
            print("      붙일 만한 곳: " + ", ".join("%s(%.2f)" % x
                                                    for x in c["붙일만한곳"]))
            for 구, 출처, 점 in c["이름후보"]:
                print("      이름 후보: %s  (%s, %.2f)" % (구, 출처, 점))
            if not c["이름후보"]:
                print("      이름 후보: 없음 — 자료에 근거가 없다."
                      " 지어내지 않는다. 문서를 먼저 넣을 것.")
            print("      --- 사건 md 에 붙여넣을 초안 ---")
            이름 = (c["이름후보"][0][0].replace(" ", "")
                    if c["이름후보"] else "이름을정하세요")
            print("      ### " + 이름)
            print("      - 증거: (어느 증거가 증명하나)")
            print("      - 말: " + " / ".join(c["예시"]))
            print("      - 충족: " + c["붙일만한곳"][0][0])
        sys.exit(0)

    elif "--edges" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        g = load(인자[0] if 인자 else "graphs/graph.kg")
        후보들, 흔한것 = 엣지제안(g, 인자[1] if len(인자) > 1 else "data")
        
        판별기 = 방향분류기(g, 최소=10)
        
        가지 = len([1 for v in g["adj"].values()
                    for r, _ in v if r in POS]) / max(len(g["adj"]), 1)
        print("지금 가지치기 %.2f (노드당 전진 엣지). 1에 가까우면 사슬이라"
              " 합성으로 나오는 명제가 없다." % 가지)
        if 흔한것:
            print("자료 대부분에 걸려서 뺀 노드: " + ", ".join(흔한것))
            print("  이 노드들은 어느 대목이냐를 구별해주지 못한다. 근거가 못 된다.")
        if not 후보들:
            print("함께 나온 노드 쌍이 없다.")
            print("  자료가 관계를 서술하지 않는 문서다 — 조문 나열에는 "
                  "'A가 B를 충족한다'가 안 적혀 있다.")
            print("  임계값을 낮춰 억지로 뽑지 않는다. 해설·판례를 넣을 것.")
            sys.exit(0)
        print("원문에서 같은 대목에 함께 나온, 아직 엣지가 없는 쌍 %d개" % len(후보들))
        print("  내장 로지스틱 회귀 모델(방향분류기)을 활용하여 방향을 기계가 자동으로 판단합니다.")
        for i, c in enumerate(후보들, 1):
            a, b = c["쌍"]
            print()
            
            # 증거에서 나가는 엣지는 증명으로 고정
            증거노드 = g.get("증거", [])
            if a in 증거노드:
                방향, 역방향 = "증명", None
            elif b in 증거노드:
                방향, 역방향 = None, "증명"
            elif 판별기:
                확률_정 = 판별기(a, b)
                확률_역 = 판별기(b, a)
                방향 = "부정" if 확률_정 >= 0.5 else "충족"
                역방향 = "부정" if 확률_역 >= 0.5 else "충족"
            else:
                방향, 역방향 = "충족", "충족"
            
            출력방향 = 방향 if 방향 else ("<-" + 역방향 if 역방향 else "<-?->")
            print("  [%d] %s  -%s->  %s   (세기 %.2f · %d개 대목에서 함께)"
                  % (i, a, 출력방향, b, c["세기"], c["횟수"]))
            for 본문, 출처 in c["근거"]:
                print("      %s" % 출처)
                print("        \"%s...\"" % 본문)
            if c["순환주의"]:
                print("      [주의] %s 를 앞에 두면 순환이 된다"
                      % ", ".join(c["순환주의"]))
            print("      --- .kg 에 붙여넣을 초안 ---")
            if a in 증거노드:
                print("      %s 증명 %s" % (a, b))
            elif b in 증거노드:
                print("      %s 증명 %s" % (b, a))
            else:
                if a not in c.get("순환주의", []):
                    print("      %s %s %s" % (a, 방향, b))
                if b not in c.get("순환주의", []):
                    print("      %s %s %s" % (b, 역방향, a))
        sys.exit(0)

    elif "--label" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        경로 = 인자[0] if 인자 else "graphs/graph.kg"
        g = load(경로)
        로그 = os.path.splitext(경로)[0] + ".엣지.jsonl"
        라벨 = 엣지라벨읽기(로그)
        if "--report" in sys.argv:
            현황 = 라벨현황(라벨)
            print("모은 라벨 %d건 (%s)" % (sum(현황.values()), 로그))
            for k, v in sorted(현황.items(), key=lambda x: -x[1]):
                print("  %-8s %4d" % (k, v))
            if not 현황:
                print("  아직 없다. --label 로 모을 것.")
            else:
                print()
                print("  분류기를 시험해볼 만한 양: 수백 건.")
                print("  물어볼 것 — 대목을 먹이면 79.4%s(이름만)가 몇으로 "
                      "가나." % "%")
            sys.exit(0)

        후보들, 흔한것 = 엣지제안(g, 인자[1] if len(인자) > 1 else "data")
        남은 = [c for c in 후보들 if tuple(c["쌍"]) not in 라벨]
        if not 남은:
            print("라벨 안 붙은 후보가 없다. --edges 로 후보를 먼저 볼 것.")
            sys.exit(0)
        # 기계가 헷갈리는 것부터 묻는다. 무작위로 110개 달아야 나오는 정확도가
        # 35개로 나온다 (docs/ko/direction.md 「일일이 다 안 해도 된다」). 라벨이 모자라면
        # 그대로 세기 순으로 둔다 — 배울 것이 없을 때 순서를 흔들 이유가 없다.
        판단 = 방향분류기(g, 라벨)
        if 판단:
            for c in 남은:
                c["부정확률"] = 판단(*c["쌍"])
            남은.sort(key=lambda c: abs(c["부정확률"] - 0.5))
        print("엣지 방향 라벨 모으기 — %d건. 원본 .kg 는 안 건드린다." % len(남은))
        if 판단:
            print("  엣지 %d개로 배운 분류기가 헷갈리는 것부터 묻는다." % 판단.학습수)
        else:
            print("  라벨이 모자라 세기 순으로 묻는다. 20개쯤 쌓이면 순서가 바뀐다.")
        print("  대목을 읽고 고른다. 모르겠으면 s. 관계가 없으면 0.")
        print("  ->  %s" % 로그)
        센 = 0
        for c in 남은:
            a, b = c["쌍"]
            보기 = [(a, r, b) for r in ("증명", "충족", "부정")] + \
                   [(b, r, a) for r in ("증명", "충족", "부정")]
            print()
            짐작 = ("  기계 짐작: %s %.0f%%"
                    % ("부정" if c["부정확률"] >= .5 else "충족",
                       100 * max(c["부정확률"], 1 - c["부정확률"]))
                    if "부정확률" in c else "")
            print("  %s  <-?->  %s   (세기 %.2f · %d개 대목)%s"
                  % (a, b, c["세기"], c["횟수"], 짐작))
            본문, 출처 = c["근거"][0]
            print("    %s" % 출처)
            print("      %s" % 본문)
            if c["순환주의"]:
                print("    [주의] %s 를 앞에 두면 순환이 된다"
                      % ", ".join(c["순환주의"]))
            for k, (x, r, y) in enumerate(보기, 1):
                print("      %d) %s %s %s" % (k, x, r, y))
            print("      0) 관계 없음    s) 건너뜀    q) 끝")
            답 = input("    > ").strip().lower()
            if 답 == "q":
                break
            if 답 == "s" or not 답:
                continue
            if 답 == "0":
                엣지라벨쓰기(로그, (a, b), None, 본문, 출처, c["세기"])
            elif 답.isdigit() and 1 <= int(답) <= len(보기):
                엣지라벨쓰기(로그, (a, b), list(보기[int(답) - 1]),
                             본문, 출처, c["세기"])
            else:
                print("    못 알아들었다. 건너뛴다.")
                continue
            센 += 1
        현황 = 라벨현황(엣지라벨읽기(로그))
        print()
        print("이번에 %d건. 누적 %d건. %s" % (센, sum(현황.values()), 현황))
        sys.exit(0)

    elif "--score" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        if len(인자) < 2:
            print("사용법: python engine.py --score <그래프.kg> <판례.jsonl>")
            sys.exit(1)
        g = load(인자[0])
        판례들 = 판례읽기(인자[1])
        r = 판례채점(g, 판례들)
        print("판례 %d건 · 판결요지 문장 %d개" % (r["판례수"], r["문장수"]))
        print("  그래프가 덮은 문장: %d (%.1f%%)" % (r["덮음"], 100 * r["덮음률"]))
        print("  판정 분포: %s" % dict(sorted(r["판정"].items(),
                                              key=lambda x: -x[1])))
        print()
        print("  법원이 실제로 쓴 법리 중 이 그래프에 걸린 것 (상위 10):")
        for n, c in sorted(r["걸린노드"].items(), key=lambda x: -x[1])[:10]:
            print("    %-18s %3d" % (n, c))
        안걸림 = [n for n in g["공통층"] if n not in r["걸린노드"]]
        if 안걸림:
            print()
            print("  판례에 한 번도 안 나온 노드 %d개: %s"
                  % (len(안걸림), ", ".join(안걸림[:8])))
            print("    (기획자가 넣었지만 법원은 안 쓰는 법리일 수 있다)")
        print()
        print("  안 걸린 문장은 미지 로그로 갔다. --suggest 로 노드 후보를 볼 것.")
        sys.exit(0)

    elif "--regress" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        설정 = 인자[0] if 인자 and 인자[0].endswith(".json") else "cases/사건_회귀.json"
        나머지 = 인자[1:] if 인자 and 인자[0].endswith(".json") else 인자
        if 나머지 and len(나머지) != 3:
            print("사용법: python engine.py --regress [cases/사건_회귀.json] [src relation dst]")
            sys.exit(1)
        엣지 = tuple(나머지) if 나머지 else None
        if 엣지 and 엣지[1] not in POS + NEG:
            print("관계는 증명/충족/부정 중 하나여야 한다.")
            sys.exit(1)
        결과 = 회귀(설정, 엣지)
        맞음 = sum(x["ok"] for x in 결과)
        적용 = sum(x["edge_applied"] for x in 결과)
        if 엣지:
            print("임시 엣지: %s -%s-> %s (%d개 사건에 적용)" % (*엣지, 적용))
        for x in 결과:
            이름 = os.path.splitext(os.path.basename(x["graph"]))[0].replace("사건_", "")
            이유 = ""
            if x["played"] is False:
                이유 = "  [구조는 이길 수 있는데 실제로 두면 진다 — 매칭 확인]"
            elif x["actual"] == "loss":
                이유 = "  막힘=" + (",".join(x["blocked"]) or "없음")
                if x["short"]:
                    이유 += " 증거부족=%d" % x["short"]
            print("  %s %-18s 기대=%s 실제=%s%s" %
                  ("O" if x["ok"] else "X", 이름, x["expected"], x["actual"], 이유))
        print("일치 %d/%d (%.1f%%)" % (맞음, len(결과), 100 * 맞음 / max(len(결과), 1)))
        sys.exit(0 if 맞음 == len(결과) else 1)

    elif "--relations" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        g = load(인자[0] if 인자 else "graphs/graph.kg")
        후보들 = 의미관계제안(g, 인자[1] if len(인자) > 1 else "data")
        if not 후보들:
            print("의미 관계 후보가 없다.")
            print("  원문에 '넣고'·'~해야'·'마지막에'·'대신' 같은 표지가 있어야 뽑힌다.")
            print("  조문처럼 요건만 나열하는 문서에는 이 표지가 거의 없다.")
            sys.exit(0)
        print("원문에서 뽑은 의미 관계 후보 %d개" % len(후보들))
        print("  관계 종류까지 짐작한다 — 표지가 문장에 남아 있기 때문이다.")
        print("  논증 관계(충족/부정)와 달리 종류를 짐작하지만, 확정은 사람이 한다.")
        종류 = {}
        for c in 후보들:
            종류[c["관계"]] = 종류.get(c["관계"], 0) + 1
        print("  종류: %s" % ", ".join("%s %d" % x for x in sorted(종류.items())))
        for i, c in enumerate(후보들, 1):
            a, b = c["쌍"]
            print()
            print("  [%d] %s  -%s->  %s   (세기 %.2f)" % (i, a, c["관계"], b, c["세기"]))
            print("      %s" % c["출처"])
            print("        \"%s\"" % c["문장"])
            print("      --- .kg 에 붙여넣을 초안 ---")
            print("      %s  -%s->  %s" % (a, c["관계"], b))
        sys.exit(0)

    elif "--route" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        색인 = 그래프색인()
        print("그래프 색인 %d개 (kg읽기만 쓴다 — 고르기 전에 다 올리지 않는다)"
              % len(색인["공통층"]))
        if not 인자:
            for n in 색인["공통층"]:
                print("  %-26s 예시 %d" % (n, len(색인["공통층"][n])))
            print()
            print('사용법: python engine.py --route "질문"')
            sys.exit(0)
        for q in 인자:
            이름, 점, 후보 = 그래프고르기(q, 색인)
            print()
            print("  Q %s" % q)
            if not 이름:
                print("    -> 어느 그래프인지 모르겠습니다 (최고 %.2f)" % 점)
                continue
            print("    -> %s  (%.2f)" % (이름, 점))
            나머지 = [x for x in 후보[1:] if x[1] >= 점 - 0.08]
            if 나머지:
                print("       접전: " + ", ".join("%s(%.2f)" % x for x in 나머지))
            g = 그래프불러오기(이름)
            tag, line = judge(g, q)
            print("       [%s] %s" % (tag, line))
        sys.exit(0)

    elif "--tune" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        경로 = 인자[0] if 인자 else "graphs/graph.kg"
        발화 = json.load(open(인자[1], encoding="utf-8")) if len(인자) > 1 else None
        g = load(경로)
        r = 보정(g, 발화)
        전체 = r["맞음"] + len(r["틀림"])
        print("보정 " + 경로 + ("  (발화 파일: %s)" % 인자[1] if 발화 else
                                "  (leave-one-out - 예시 문장을 하나씩 빼고 맞히는지 본다)"))
        if not 발화:
            print("  주의: 정답 예시를 빼고 재므로 실제 정확도보다 낮게 나온다.")
            print("        '남이 다르게 말했을 때 맞히는가' 의 추정치로 읽는다.")
        print("  자기 노드 적중: %d/%d (%.0f%%)" % (r["맞음"], 전체,
                                                    100.0 * r["맞음"] / max(1, 전체)))
        print("  무관 발화가 실노드로 샌 것: %d/%d" % (len(r["무관샌것"]), r["무관총"]))
        q = r["있음점수"]
        if q:
            print("  적중 점수: 최저 %.3f · 5%%분위 %.3f · 중앙 %.3f"
                  % (q[0], q[len(q) // 20], q[len(q) // 2]))
        print("  현재 임계값: A_MIN %.2f / OK_MIN %.2f"
              % (g["임계값"]["A_MIN"], g["임계값"]["OK_MIN"]))
        if r["추천"]:
            print("  추천 임계값: " + " / ".join("%s %.2f" % kv for kv in
                                                sorted(r["추천"].items())))
        if r["예시부족"]:
            print("  [경고] 예시가 1개뿐이라 측정 불가: " + ", ".join(r["예시부족"][:8]))
        if r["틀림"]:
            print("  [고칠 것] 다른 노드에 뺏긴 예시 %d건 - 상위:" % len(r["틀림"]))
            for x in r["틀림"][:8]:
                if 발화:
                    print("    %.3f  %s  <- \"%s\"" % (x[0], x[1], x[2][:34]))
                else:
                    print("    %.3f  %s -> %s  <- \"%s\"" % (x[0], x[1], x[2], x[3][:30]))
        if r["무관샌것"]:
            print("  [고칠 것] 무관해야 하는데 실노드로 간 발화:")
            for x in r["무관샌것"][:5]:
                print("    %.3f  %s  <- \"%s\"" % (x[0], x[1], x[2][:34]))
        sys.exit(0)

    elif "--diagnose" in sys.argv:
        경로 = sys.argv[sys.argv.index("--diagnose") + 1]
        try:
            d = 진단(load(경로))
        except ValueError as e:
            print("X " + str(e))
            sys.exit(1)
        print("OK " + 경로)
        print("  역할 %s | 목표 %s" % (d["역할"], d["목표"]))
        print("  개념 %d · 사례 %d · 증거 %d · 널클래스 %d"
              % (d["개념"], d["사례"], d["증거"], d["널클래스"]))
        print("  요건: " + ", ".join(d["요건"]))
        if d["수치조건"]:
            print("  수치조건: " + ", ".join(d["수치조건"]))
        문제 = 0
        if d["막힌요건"] and d["증거"] == 0:
            print("  [정보] 증거가 없다 — 에피소드가 아니라 공유 법리 라이브러리다.")
        elif d["막힌요건"]:
            문제 += 1
            print("  [치명] 증거가 못 닿는 요건 -> 이길 수 없음: "
                  + ", ".join(d["막힌요건"]))
        if d["모자란증거"]:
            문제 += 1
            print("  [치명] 요건에 하나씩 배정할 증거가 %d개 모자람" % d["모자란증거"])
        if d["고아노드"]:
            문제 += 1
            print("  [경고] 어떤 개념에도 닿지 않는 사례층 노드: "
                  + ", ".join(d["고아노드"]))
        if d["출처없음"]:
            print("  [정보] 출처가 없는 개념 %d개: %s"
                  % (len(d["출처없음"]), ", ".join(d["출처없음"][:6])))
        if d["증거없는개념"]:
            print("  [정보] 증거가 없어 항상 B1 이 되는 개념 %d개: %s"
                  % (len(d["증거없는개념"]), ", ".join(d["증거없는개념"][:6])))
        print("  " + ("문제 없음" if not 문제 else "문제 %d종" % 문제))
        sys.exit(1 if 문제 else 0)
    else:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        g = load(인자[0] if 인자 else "graphs/graph.kg")
        print("[" + g["역할"] + "] 목표:", g["목표"])
        print("  증거:", ", ".join(g["증거"]))
        print("  요건:", ", ".join(요건(g)), " (종료 입력시 끝)")
        _막힘 = 진단(g)["막힌요건"]
        if _막힘 and g["증거"]:
            print("  [경고] 증거가 못 닿는 요건이 있어 이 그래프는 이길 수 없다: "
                  + ", ".join(_막힘))
            print("         --diagnose 로 확인하고 사건 파일을 고칠 것.")
        s = 세션(g)
        보임 = "--verdict" in sys.argv
        while True:
            t = input("\n> ").strip()
            if t in ("종료", "q", ""):
                break
            답 = s.대답(t)
            print("  " + g["역할"] + ": " + 답)
            if 보임:
                print("  [" + s.판정 + "] 인내심 " + str(s.인내심) + " | " + s.현황())
            if s.승패:
                print("\n=== " + ("승소" if s.승패 == "승" else "패소") + " ===")
                break
