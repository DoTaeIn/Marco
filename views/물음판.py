# -*- coding: utf-8 -*-
"""물음판 — 사람이 직접 물어보고, 그 답이 맞았는지 표시한다.

    python views/물음판.py                       # 문서그래프로
    python views/물음판.py data/법지식/지식그래프.json
    python views/물음판.py 웹그래프.json 8766

왜 필요한가. 지금 채점기(explain.py --score)는 원문을 정답지로 쓴다.
사람이 라벨을 안 달아도 되는 것이 장점인데, 질문을 정답에서 만들기
때문에 한계가 하나 있다 — 표면을 그대로 보는 방식이 구조적으로 이긴다.
문자 n-gram 인코더가 법지식에서 가림 91% 를 냈는데, 뜯어보니 가린
질문과 노드 이름의 유사도는 0.088 이고 원본 발췌와의 유사도가 0.921
이었다. 이해가 아니라 받은 문장을 도로 알아본 것이다.

그것과 진짜 이해를 가르려면 **원문에서 만들지 않은 질문**이 있어야
한다. 사람이 쓴 질문 말고는 방법이 없다. 이 화면은 그것을 모은다.

기록은 물음기록.jsonl 에 한 줄씩 쌓인다. 나중에 채점 자료가 된다.
엔진은 한 줄도 고치지 않는다 — explain.물어보기 가 낸 것을 그대로 적는다.
"""
import io, json, os, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

_여기 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_여기))
import explain  # noqa: E402

_G = {}
기록터 = os.path.join(os.path.dirname(_여기), "물음기록.jsonl")


def 묻기(질문, 쓴이="사람", 갈래=None, 기대=None):
    """쓴이를 같이 적는다.

    이 판의 값어치는 '원문에서 만들지 않은 질문' 에 있다. 기계가 쓴 질문은
    코퍼스를 이미 읽고 쓴 것이라 어휘가 샌다 — 사람 것과 같은 통에 넣되
    섞이지는 않게, 누가 썼는지를 줄마다 남긴다. 채점할 때 갈라 보라고.

    갈래·기대는 있으면 적는다. 코퍼스 밖 질문에 '미지' 를 기대한다고 미리
    적어두면 그 줄은 누가 썼든 잣대로 쓸 수 있다 — 답을 원문에서 베낄 수가
    없는 물음이기 때문이다."""
    시작 = time.time()
    뜻, 답, 주제 = explain.물어보기(_G["그래프"], 질문, _G.get("기억"))
    # 점수도 남긴다. 문턱을 다시 재는 것이 이 기록의 쓸모인데, 판정만 있고
    # 점수가 없으면 '어디서 잘라야 하나' 를 이 파일로 못 본다. 한 번 더
    # 가까운 노드를 부르는 값이지만 문자 인코더에서는 거의 공짜다.
    try:
        _n, 점수 = explain._가까운노드(_G["그래프"], 질문)
    except Exception:
        _n, 점수 = None, None
    줄 = {"질문": 질문, "판정": 뜻, "답": 답 or "", "주제": 주제,
          "점수": round(float(점수), 4) if 점수 is not None else None,
          "최고노드": _n,
          "밀리초": round(1000 * (time.time() - 시작)),
          "그래프": _G["이름"], "인코더": explain.MODEL,
          "쓴이": 쓴이,
          "때": time.strftime("%Y-%m-%d %H:%M:%S")}
    if 갈래:
        줄["갈래"] = 갈래
    if 기대:
        줄["기대"] = 기대
        # 기대를 적어 둔 줄은 사람이 눈으로 안 봐도 채점된다.
        줄["표"] = "맞음" if 뜻 == 기대 else "틀림"
        줄["표한이"] = "기대"
    return 줄


def 적기(줄):
    """한 줄씩 덧붙인다. 통째로 다시 쓰지 않으니 중간에 꺼도 남는다."""
    with io.open(기록터, "a", encoding="utf-8") as f:
        f.write(json.dumps(줄, ensure_ascii=False) + "\n")


def 셈():
    """지금까지 쌓인 것. 표시된 것만 센다 — 안 본 것은 모르는 것이다.

    사람이 쓴 것을 따로 센다. 기계가 쓴 질문을 섞어 쌓을 수 있게 했으니
    합계만 보면 이 판의 값어치를 제가 부풀려 보고하게 된다."""
    맞 = 틀 = 전체 = 사람 = 사람맞 = 사람틀 = 0
    if os.path.exists(기록터):
        for 줄 in io.open(기록터, encoding="utf-8"):
            try:
                d = json.loads(줄)
            except ValueError:
                continue
            전체 += 1
            표 = d.get("표")
            맞 += 표 == "맞음"
            틀 += 표 == "틀림"
            if d.get("쓴이", "사람") == "사람":
                사람 += 1
                사람맞 += 표 == "맞음"
                사람틀 += 표 == "틀림"
    return {"전체": 전체, "맞음": 맞, "틀림": 틀, "안봄": 전체 - 맞 - 틀,
            "사람": 사람, "사람맞음": 사람맞, "사람틀림": 사람틀}


class 손(BaseHTTPRequestHandler):
    """경로만 영어다. http.server 는 요청 경로를 latin-1 로 디코드해서 주므로
    한글 경로는 퍼센트 인코딩과 겹쳐 두 층을 되돌려야 한다. 유리상자가
    /state · /ask 를 쓴 이유가 이것이고, 여기서도 그렇게 한다."""

    def log_message(self, *a):
        pass

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
            쪽 = io.open(os.path.join(_여기, "물음판.html"), encoding="utf-8").read()
            return self._보내기(쪽, "text/html")
        if self.path == "/info":
            g = _G["그래프"]
            return self._json({"이름": _G["이름"], "노드": len(g["노드"]),
                               "엣지": len(g["엣지"]),
                               "어휘": len(g.get("어휘") or ()),
                               "인코더": explain.MODEL, "셈": 셈()})
        self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        몸 = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/ask":
            질문 = (몸.get("질문") or "").strip()
            if not 질문:
                return self._json({"탈": "빈 질문"})
            try:
                답 = 묻기(질문, (몸.get("쓴이") or "사람").strip()[:32],
                          (몸.get("갈래") or None), (몸.get("기대") or None))
            except Exception as e:
                import traceback
                traceback.print_exc()
                return self._json({"탈": "%s: %s" % (type(e).__name__, e)})
            적기(답)
            답["셈"] = 셈()
            return self._json(답)
        if self.path == "/mark":
            # 표시는 마지막 줄에만 붙인다. 사람이 방금 본 것에 답하는 것이라
            # 그 이상 거슬러 고칠 일이 없다.
            표 = 몸.get("표")
            if 표 not in ("맞음", "틀림"):
                return self._json({"탈": "표가 이상하다"})
            줄들 = []
            if os.path.exists(기록터):
                줄들 = io.open(기록터, encoding="utf-8").read().splitlines()
            if not 줄들:
                return self._json({"탈": "적힌 것이 없다"})
            마지막 = json.loads(줄들[-1])
            마지막["표"] = 표
            줄들[-1] = json.dumps(마지막, ensure_ascii=False)
            io.open(기록터, "w", encoding="utf-8", newline="\n").write(
                "\n".join(줄들) + "\n")
            return self._json({"됐다": True, "셈": 셈()})
        self.send_error(404)


def 띄우기(경로="문서그래프.json", 문=8766):
    _G["이름"] = os.path.basename(경로)
    print("그래프 읽는 중 …", 경로)
    _G["그래프"] = explain.열기(explain._길(경로))
    _G["기억"] = explain.대화기억()
    g = _G["그래프"]
    print("  노드 %d · 엣지 %d · 어휘 %d · 인코더 %s"
          % (len(g["노드"]), len(g["엣지"]), len(g.get("어휘") or ()),
             explain.MODEL))
    print("  기록: %s" % 기록터)
    터 = HTTPServer(("127.0.0.1", 문), 손)
    print("\n  http://127.0.0.1:%d  — 열어서 물어보십시오. Ctrl+C 로 끝냅니다.\n" % 문)
    try:
        터.serve_forever()
    except KeyboardInterrupt:
        print("\n끝냅니다. %s" % 셈())


if __name__ == "__main__":
    인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
    띄우기(인자[0] if 인자 else "문서그래프.json",
           int(인자[1]) if len(인자) > 1 else 8766)
