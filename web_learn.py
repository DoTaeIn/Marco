# -*- coding: utf-8 -*-
"""열린 웹에서 주워온 지식을 논증 그래프에 얹는다.

위키백과만 쓰면 "권위 있는 출처 한 곳"에 기댄다. 열린 웹은 그 제한이 없는
대신 아무 글이나 들어온다. 그래서 이 파일은 네 가지를 지킨다.

1. 주워온 문장은 원본 .kg 에 쓰지 않는다. 옆의 .수집.jsonl 에만 쌓는다.
   사람이 쓴 뼈대와 기계가 주워온 살이 한 파일에 섞이면 되돌릴 수가 없다.
   .학습.jsonl / .미지.log 와 같은 자리, 같은 규칙이다.
2. 출처 없는 문장은 넣지 않는다. 노드마다 출처가 붙고, engine 은 판정이
   인정/B1 일 때 그 출처를 답에 같이 내보낸다. 주워온 지식일수록 근거가
   남아야 한다.
3. 같은 주제를 말하는 출처가 여럿이면 증명 엣지가 그 수만큼 붙는다.
   교차검증은 따로 만든 장치가 아니라 원래 쓰던 논증 구조 그대로다.
4. 문장은 만들지 않는다. 주워온 문장을 그대로 노드의 예시로 두고,
   대답할 때 engine.문장() 이 사용자 말투에 가장 가까운 예시를 고른다.
   고르는 것이지 생성이 아니다 — 그래서 환각도 주입 표면도 늘지 않는다.

인코더는 KG_ENCODER=문자 를 기본으로 둔다. 토큰을 쓰지 않는다.
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

os.environ.setdefault("KG_ENCODER", "문자")   # 토큰 없는 인코더가 이 파일의 기본값이다

import engine as eng
from encoder import _vec


# ── 살균 ────────────────────────────────────────────────────────────────
# 진짜 손상은 개행·태그·제어문자다. 한 줄로 뭉개지 않으면 .kg 로 내보낼 때
# 줄이 갈라지고, 태그가 남으면 그게 그대로 임베딩에 들어간다.
#
# '|' 와 '#' 은 .kg 의 구분자·주석이라 예전 방식(원본 .kg 에 직접 주입)에서는
# 문장을 조용히 쪼개고 잘랐다. 여기서는 텍스트를 JSON 에 담으므로 그 위험이
# 구조적으로 사라진다 — 문자를 바꿔서 막는 것보다 이게 낫다. 원문을 훼손하지
# 않기 때문이다. .kg 로 내보낼 때만 kg안전=True 로 막는다.
_제어 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_태그 = re.compile(r"<[^>]+>")


def 살균(글, 최대=700, kg안전=False):
    """주워온 문자열을 노드 예시로 쓸 수 있는 한 줄로 만든다."""
    # 태그는 공백이 아니라 빈 문자열로 지운다. 검색 스니펫은 질의어를 굵게
    # 표시하는데, <b>가</b>격은 처럼 낱말 중간에 걸리면 공백 치환이 낱말을 쪼갠다.
    글 = html.unescape(_태그.sub("", 글 or ""))
    글 = _제어.sub(" ", 글)
    글 = re.sub(r"\s+", " ", 글).strip().strip('"').strip()
    if kg안전:
        # .kg 한 줄로 나갈 때만. 뜻을 해치지 않는 최소 치환.
        글 = 글.replace("|", "／").replace("#", "＃")
    return 글[:최대].strip()


def kg줄(이름, 문장들, 출처=None):
    """노드 하나를 .kg 한 줄로. 내보내기용이며 평소 경로에는 쓰이지 않는다."""
    머리 = 이름 + ("@" + 출처 if 출처 else "")
    return '%s: %s' % (머리, " | ".join('"%s"' % 살균(s, kg안전=True) for s in 문장들))


# ── 검색 ────────────────────────────────────────────────────────────────
_링크 = re.compile(r"href=\"(https?://[^\"]+)\"[^>]*class='result-link'", re.I)
_스니펫 = re.compile(r"class='result-snippet'[^>]*>(.*?)</td>", re.DOTALL | re.I)


def 검색(질의, 개수=10, 최소길이=40):
    """열린 웹 검색. (출처, 본문) 목록을 돌려준다.

    스니펫을 하나만 쓰면 그 블로그 한 곳이 곧 진실이 된다. 여러 개를 받아야
    교차검증이 가능해지므로 기본값을 10 으로 둔다."""
    req = urllib.request.Request(
        "https://lite.duckduckgo.com/lite/",
        data=urllib.parse.urlencode({"q": 질의}).encode("utf-8"),
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        본문 = r.read().decode("utf-8", "replace")

    링크 = [urllib.parse.urlparse(u).netloc for u in _링크.findall(본문)]
    조각 = [살균(s) for s in _스니펫.findall(본문)]
    out, 본것 = [], set()
    for i, 글 in enumerate(조각):
        if len(글) < 최소길이 or 글 in 본것:
            continue                       # 너무 짧은 것은 근거가 못 된다
        본것.add(글)
        out.append((링크[i] if i < len(링크) else "출처미상", 글))
        if len(out) >= 개수:
            break
    return out


# ── 옆파일 ──────────────────────────────────────────────────────────────
def 수집경로(kg경로):
    return os.path.splitext(kg경로)[0] + ".수집.jsonl"


_질문틀 = ("{주제} 알려줘", "{주제} 설명해줘", "{주제} 만드는 법",
           "{주제} 순서대로 알려줘", "{주제}가 뭐야")
# 사람이 쓴 틀이다. 주제 낱말만 갈아 끼우며, 문장을 지어내지 않는다.


def 배우기(kg경로, 주제, 질의=None, 개수=10):
    """웹에서 주워 옆파일에 쌓는다. 원본 .kg 는 건드리지 않는다."""
    질의 = 질의 or 주제
    찾은 = 검색(질의, 개수=개수)
    if not 찾은:
        return []
    경로 = 수집경로(kg경로)
    이미 = {r["본문"] for r in 수집읽기(경로)}
    새것 = []
    when = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(경로, "a", encoding="utf-8") as f:
        for 출처, 글 in 찾은:
            if 글 in 이미:
                continue
            기록 = {"주제": 주제, "질의": 질의, "출처": 출처, "본문": 글,
                    "질문표현": [t.format(주제=주제) for t in _질문틀] + [질의],
                    "수집시각": when}
            f.write(json.dumps(기록, ensure_ascii=False) + "\n")
            새것.append(기록)
    return 새것


def 수집읽기(경로):
    out = []
    if 경로 and os.path.exists(경로):
        for 줄 in open(경로, encoding="utf-8"):
            줄 = 줄.strip()
            if not 줄:
                continue
            try:
                d = json.loads(줄)
                if d.get("주제") and d.get("본문"):
                    out.append(d)
            except ValueError:
                pass
    return out


def 얹기(g, 기록들):
    """수집 기록을 그래프에 붙인다. 노드 이름은 전부 접두사로 표시해 둔다 —
    어느 것이 기계가 주워온 것인지 그래프만 보고도 알 수 있어야 한다."""
    주제별 = {}
    for r in 기록들:
        주제별.setdefault(r["주제"], []).append(r)

    for 주제, rs in 주제별.items():
        주장 = "지식_" + 주제
        본문들 = []
        for r in rs:
            if r["본문"] not in 본문들:
                본문들.append(r["본문"])
        # 예시가 여럿인 것이 곧 말투 재료다. engine.문장() 이 사용자 발화에
        # 가장 가까운 것을 고른다.
        g["공통층"][주장] = 본문들

        도메인 = sorted({r["출처"] for r in rs})
        g.setdefault("출처", {})[주장] = "웹 %d곳 · %s%s" % (
            len(도메인), ", ".join(도메인[:2]), " 외" if len(도메인) > 2 else "")


        # 출처 하나가 증거 하나. 같은 주장을 가리키는 증명 엣지가 출처 수만큼
        # 생긴다 = 교차검증. 출처가 하나뿐이면 엣지도 하나뿐이라 그 사실이
        # 그래프에 그대로 남는다.
        for i, r in enumerate(rs, 1):
            n = "출처_%s_%d" % (주제, i)
            g["사례층"][n] = [r["본문"]]
            g["출처"][n] = r["출처"]
            g["엣지"].append([n, "증명", 주장])

        g["엣지"].append([주장, "충족", g["목표"]])
    return g


def 불러오기(kg경로):
    """engine.load() 를 그대로 쓰되 파싱 직후에 수집분을 얹는다.

    load() 뒤쪽(학습 덧칠·검증·관련개념·벡터)을 여기로 복사하면 engine 이
    바뀔 때 조용히 어긋난다. 파싱 함수만 잠깐 감싸서 나머지를 전부 물려받는다."""
    원래 = eng.kg읽기
    기록 = 수집읽기(수집경로(kg경로))

    def 덧칠(경로):
        return 얹기(원래(경로), 기록)

    eng.kg읽기 = 덧칠
    try:
        return eng.load(kg경로)
    finally:
        eng.kg읽기 = 원래


def 묻다(g, 말):
    """→ (아는 주제인가, 답).

    답을 두 벡터로 나눠 만든다. 하나로는 안 된다:

      · 어느 주제인가 — 주제 낱말이 살아 있어야 갈린다. 지우면 남는 것이
        "재료 알려줘" 뿐이라 주제끼리 구분이 사라진다(실제로 김치찌개 질문에
        까르보나라 발췌가 나왔다). 발화 그대로 잰다 —
        측정 6/6, 1위 0.27~0.50 vs 2위 0.17~0.28.
      · 어느 발췌인가(말투) — 주제 낱말이 빠져야 갈린다. 남기면 주제를
        아홉 번 되풀이하는 발췌가 어떤 질문에도 이겨 말투 선택이 죽는다.
        주제를 뺀 나머지로 잰다.

    judge() 는 기준 벡터를 하나만 쓰므로 둘을 동시에 만족시킬 수 없다.
    그래서 판정 대신 그래프의 대사와 engine.문장() 으로 직접 조립한다.
    문장은 여전히 만들지 않는다 — 고르기만 한다.

    모르는 주제에 대고 억지로 대답하지 않는다. '무관하다'가 아니라
    '아직 모른다'로 답한다."""
    주제들 = sorted((n[len("지식_"):] for n in g.get("공통층", {}) if n.startswith("지식_")),
                    key=len, reverse=True)
    걸린주제 = next((t for t in 주제들 if t and t in 말), None)
    if not 걸린주제:
        모름 = ((g.get("공통층") or {}).get("상태_지식부족")
                or (g.get("무관층") or {}).get("_타죄명:상태_지식부족")
                or ["아직 그 내용을 모릅니다"])
        return False, 모름[0]

    후보 = [n for n in g["공통층"] if n.startswith("지식_")]
    주장, _ = eng.match(말, 후보, g)
    나머지 = 말.replace(걸린주제, " ").strip() or 말
    발췌 = eng.문장(g, 주장, _vec(나머지))

    말틀 = g["대사"].get("인정_말", "{말}")
    줄 = [말틀.format(말=발췌, ev="", claim=주장, bad="", 반격말="")]
    출처 = (g.get("출처") or {}).get(주장)
    if 출처 and g["대사"].get("출처"):
        줄.append(g["대사"]["출처"].format(출처=출처, claim=주장))
    return True, " ".join(줄)


# ── CLI ─────────────────────────────────────────────────────────────────
def _쓰임():
    print(__doc__.strip())
    print("""
사용법
  python web_learn.py --배우다 <주제> [--질의 "검색어"] [--개수 10]
  python web_learn.py --묻다   <말>
  python web_learn.py --보기
  python web_learn.py --check

  --그래프 <경로>   기본 graphs/graph_자가학습.kg""")


def _주():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        return _쓰임()

    def 값(이름, 기본=None):
        return argv[argv.index(이름) + 1] if 이름 in argv and argv.index(이름) + 1 < len(argv) else 기본

    kg = 값("--그래프", "graphs/graph_자가학습.kg")

    if "--check" in argv:
        return _자체검사(kg)

    if "--보기" in argv:
        기록 = 수집읽기(수집경로(kg))
        주제별 = {}
        for r in 기록:
            주제별.setdefault(r["주제"], []).append(r)
        print("수집 파일: %s  (기록 %d개, 주제 %d개)" % (수집경로(kg), len(기록), len(주제별)))
        for 주제, rs in 주제별.items():
            print("\n[%s] 출처 %d곳" % (주제, len({r["출처"] for r in rs})))
            for r in rs:
                print("   · %-24s %s" % (r["출처"][:24], r["본문"][:56]))
        return

    if "--배우다" in argv:
        주제 = 값("--배우다")
        질의 = 값("--질의", 주제)
        새것 = 배우기(kg, 주제, 질의, int(값("--개수", "10")))
        print("'%s' 검색 → 새로 %d건 수집 (옆파일: %s)" % (질의, len(새것), 수집경로(kg)))
        for r in 새것:
            print("   · %-24s %s" % (r["출처"][:24], r["본문"][:56]))
        if not 새것:
            print("   (이미 갖고 있는 내용이거나 검색 결과가 없다)")
        return

    if "--묻다" in argv:
        g = 불러오기(kg)
        말 = 값("--묻다")
        아는가, 답 = 묻다(g, 말)
        if not 아는가:
            # 파이썬에 하드코딩하지 않고, 모델(그래프)에 정의된 표지들을 찾아 질문에서 지운다.
            # *물음_지식요청 등 요청을 뜻하는 사례들의 예시를 지우면 주제만 남는다.
            표지들 = []
            for n, 예시들 in g.get("사례층", {}).items():
                if n.startswith("물음_"):
                    표지들.extend(예시들)
            
            추출주제 = 말
            for 표지 in sorted(표지들, key=len, reverse=True):
                if 표지 in 추출주제:
                    추출주제 = 추출주제.replace(표지, "").strip()
            
            if 추출주제 and 추출주제 != 말:
                print(f"[자동학습] 그래프 표지를 이용해 '{추출주제}' 주제를 추출했습니다. 스스로 배웁니다...")
                배우기(kg, 추출주제, 말, int(값("--개수", "10")))
                g = 불러오기(kg)
                아는가, 답 = 묻다(g, 말)
                
        print(답)
        if not 아는가:
            print("   (배우려면: python web_learn.py --배우다 <주제>)")
        return

    _쓰임()


def _자체검사(kg):
    문제 = []
    t = "재료 준비 | 조리 # 완성\n두 번째 줄"
    s = 살균(t, kg안전=True)
    if "\n" in s or "|" in s or "#" in s:
        문제.append("살균이 개행/구분자를 남긴다: %r" % s)
    if 살균("<b>가</b>격은 3000원 # 별도")[:2] != "가격":
        문제.append("태그 제거 실패")
    g = 불러오기(kg)
    if not g.get("공통층"):
        문제.append("그래프가 비었다")
    for n in (g.get("출처") or {}):
        if n not in g["공통층"] and n not in g["사례층"] and n not in g.get("무관층", {}):
            문제.append("출처가 붙은 '%s' 이 어느 층에도 없다" % n)
    print("자체검사: %s" % ("통과" if not 문제 else "%d건 실패" % len(문제)))
    for x in 문제:
        print("   - " + x)
    return 1 if 문제 else 0


if __name__ == "__main__":
    sys.exit(_주() or 0)
