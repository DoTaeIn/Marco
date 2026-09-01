# -*- coding: utf-8 -*-
"""유리상자 — 물어보고, 그 답이 어떻게 나왔는지 그래프 위에서 본다.

    python 보기/유리상자.py                    # 정당방위 그래프로
    python 보기/유리상자.py 그래프/graph_의료.kg

블랙박스가 아니라는 말은 증명해야 하는 주장이다. 그래서 이 화면은 답만
내지 않고 그래프 두 벌을 나란히 켠다.

  지식그래프 — 이번 발화가 어느 노드에 얼마로 붙었나. 노드마다 코사인
               유사도가 밝기가 되고, 목표까지 밟은 엣지에 불이 들어온다.
  대화그래프 — 지금까지 쌓인 것. 어느 요건이 어느 증거로 확보됐고 어디가
               자책으로 무너졌나. 판이 진행될수록 자란다.

엔진은 한 줄도 고치지 않는다. engine 의 함수와 engine.세션 을 그대로 쓰고
여기서는 중간값을 받아 적을 뿐이다. 판정도 대답도 세션이 낸 것을 그대로
쓴다 — 화면이 따로 셈하면 화면과 엔진이 갈라져서, 보여주는 것이 곧 거짓이 된다.
"""
import io, json, os, sys
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine                                    # noqa: E402
from 인코더 import _vec, 조각내기                  # noqa: E402

_여기 = os.path.dirname(os.path.abspath(__file__))


def 점수(본문, 후보, g):
    """노드마다 조각 중 가장 잘 붙은 점수. match() 와 같은 셈이되 순위를 남긴다.

    match() 는 이긴 하나만 돌려준다. 감춰진 2등과의 마진이 이 시스템에서는
    판정만큼 중요한 정보다 — 마진이 좁으면 그 답은 믿을 것이 못 된다."""
    조각들 = list(조각내기(본문)) or [본문]
    벡 = [_vec(c) for c in 조각들]
    난것 = [(n, max(float((g["vec"][n] @ v).max()) for v in 벡))
            for n in 후보 if n in g["vec"]]
    난것.sort(key=lambda x: -x[1])
    return 난것


def 길찾기(g, 시작, 끝):
    """시작에서 끝까지 전진 관계(증명·충족)만 밟는 최단 경로. -> [[출발,관계,도착]]

    부정 엣지는 타지 않는다. 타면 결론을 무너뜨리는 노드가 근거처럼 보인다."""
    if 시작 is None or 시작 == 끝:
        return []
    앞, 큐 = {시작: None}, deque([시작])
    while 큐:
        여기 = 큐.popleft()
        for 관계, 다음 in g["adj"].get(여기, []):
            if 관계 not in engine.POS or 다음 in 앞:
                continue
            앞[다음] = (여기, 관계)
            if 다음 == 끝:
                길, 마디 = [], 끝
                while 앞[마디]:
                    이전, 관계2 = 앞[마디]
                    길.append([이전, 관계2, 마디])
                    마디 = 이전
                return list(reversed(길))
            큐.append(다음)
    return []


# ─────────────────────────── 터 ───────────────────────────
# 세션을 들고 간다. 상태 없이 judge() 만 부르면 대화그래프에 그릴 것이 없다 —
# 무엇이 쌓였는지가 곧 대화이기 때문이다.

_G = {"그래프": None, "세션": None, "경로": None}


def 얼개(g):
    """그래프의 뼈대. 배치는 화면이 힘으로 잡으므로 좌표는 안 보낸다."""
    층 = {}
    for 이름 in g["증거"]:
        층[이름] = "증거"
    for 이름 in g["사례층"]:
        층.setdefault(이름, "사례")
    for 이름 in g["공통층"]:
        층.setdefault(이름, "개념")
    요건 = set(engine.요건(g))
    마디 = [{"이름": n, "층": ("요건" if n in 요건 else t)} for n, t in 층.items()]
    return {"마디": 마디, "엣지": [list(e) for e in g["엣지"]],
            "목표": g["목표"], "요건": sorted(요건),
            "임계값": g["임계값"], "역할": g["역할"],
            "증거": list(g["증거"]),
            "그래프": os.path.basename(_G["경로"] or "")}


def 상태(s):
    """세션에 쌓인 것. 이것이 대화그래프의 내용이다."""
    확보 = s.확보()
    return {"확보": {요건: 증거 for 요건, 증거 in 확보.items()},
            "자책": sorted(s.자책),
            "인정한주장": sorted(s.인정한주장),
            "인내심": s.인내심, "회차": s.회차,
            "결과": s.결과(),
            "배운것": [list(x) for x in s.배운것]}


def 자취(질문):
    """발화 하나가 답이 되기까지 지나간 자리를 전부 적는다."""
    g, s = _G["그래프"], _G["세션"]

    # 1. 증거를 가리켰나. 증거 이름은 근거 표지이지 주장이 아니라 본문에서 지운다.
    증거, 증거점 = engine.match_evidence(질문, g)
    본문 = engine.증거지우기(질문, g, 증거)

    # 2. 주장 후보 = 이 사건의 사실 + 법리 개념. 널 클래스는 따로 겨룬다.
    풀 = [n for n in g["사례층"] if n not in g["증거"]] + list(g["공통층"])
    주장순위 = 점수(본문, 풀, g)
    널순위 = 점수(본문, list(g.get("무관층", {})), g)

    # 3. 답과 판정은 세션이 낸 것을 그대로 쓴다. 여기서 상태도 함께 나아간다.
    답 = s.대답(질문)

    이긴것 = 주장순위[0][0] if 주장순위 else None
    return {
        "질문": 질문, "본문": 본문, "조각": list(조각내기(본문)) or [본문],
        "증거": {"이름": 증거, "점수": round(증거점, 3)},
        "주장순위": [[n, round(v, 3)] for n, v in 주장순위],
        "널순위": [[n, round(v, 3)] for n, v in 널순위[:5]],
        "이긴것": 이긴것,
        "마진": round(주장순위[0][1] - 주장순위[1][1], 3) if len(주장순위) > 1 else None,
        "판정": s.판정, "답": 답,
        "경로": 길찾기(g, 증거 or 이긴것, g["목표"]),
        "상태": 상태(s),
    }


class 손(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass                                     # 요청마다 찍히면 시끄럽다

    def _보내기(self, 몸, 형="application/json"):
        덩이 = 몸 if isinstance(몸, bytes) else 몸.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "%s; charset=utf-8" % 형)
        self.send_header("Content-Length", str(len(덩이)))
        self.end_headers()
        self.wfile.write(덩이)

    def _json(self, o):
        self._보내기(json.dumps(o, ensure_ascii=False))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            쪽 = io.open(os.path.join(_여기, "유리상자.html"), encoding="utf-8").read()
            return self._보내기(쪽, "text/html")
        if self.path == "/state":
            난것 = 얼개(_G["그래프"])
            난것["상태"] = 상태(_G["세션"])
            return self._json(난것)
        if self.path == "/reset":
            _G["세션"] = engine.세션(_G["그래프"])
            return self._json({"됐다": True, "상태": 상태(_G["세션"])})
        self.send_error(404)

    def do_POST(self):
        if self.path != "/ask":
            return self.send_error(404)
        n = int(self.headers.get("Content-Length") or 0)
        질문 = (json.loads(self.rfile.read(n) or b"{}").get("질문") or "").strip()
        if not 질문:
            return self._json({"탈": "빈 질문"})
        try:
            return self._json(자취(질문))
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._json({"탈": "%s: %s" % (type(e).__name__, e)})


def 띄우기(kg="그래프/graph.kg", 문=8765):
    _G["경로"] = kg if os.path.isabs(kg) else os.path.join(
        os.path.dirname(_여기), kg)
    print("그래프 읽는 중 …", kg)
    _G["그래프"] = engine.load(_G["경로"])
    _G["세션"] = engine.세션(_G["그래프"])
    g = _G["그래프"]
    print("  개념 %d · 사실 %d · 널 %d · 엣지 %d · 목표 %s · 요건 %d"
          % (len(g["공통층"]), len(g["사례층"]), len(g.get("무관층", {})),
             len(g["엣지"]), g["목표"], len(engine.요건(g))))
    터 = HTTPServer(("127.0.0.1", 문), 손)
    print("\n  http://127.0.0.1:%d  — 열어서 물어보십시오. Ctrl+C 로 끝냅니다.\n" % 문)
    try:
        터.serve_forever()
    except KeyboardInterrupt:
        print("끝.")


if __name__ == "__main__":
    인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
    띄우기(인자[0] if 인자 else "그래프/graph.kg",
           int(인자[1]) if len(인자) > 1 else 8765)
