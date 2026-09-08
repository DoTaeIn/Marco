# -*- coding: utf-8 -*-
"""자가학습이 무엇을 늘렸는지 눈으로 본다.

    python views/자람.py              # http://127.0.0.1:8766
    python views/자람.py 9000

`자가저작.py --한바퀴` 가 돌 때마다 자가학습기록.jsonl 에 한 줄이 쌓인다.
이 화면은 그 줄들을 읽어서 보여준다 — 바퀴마다 노드와 엣지가 몇 개 늘었고,
어떤 그래프가 들어왔고, 무엇이 관문에서 걸렸는가.

돌면서 봐도 된다. 화면이 2초마다 다시 읽으므로, 다른 터미널에서 한 바퀴를
돌리면 여기서 자라는 것이 보인다.

엔진을 건드리지 않는다. 기록 파일만 읽는다 — 화면이 따로 셈하면 화면과
엔진이 갈라져서, 보여주는 것이 곧 거짓이 된다.

관문에서 걸린 것을 같이 보여주는 이유. 늘어난 것만 세면 이 고리가 스스로를
속인다. 이 고리가 하는 일의 절반은 짓는 것이 아니라 버리는 것이라, 버린
것이 안 보이면 무엇을 하고 있는지 알 수 없다.
"""
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

_여기 = os.path.dirname(os.path.abspath(__file__))
_뿌리 = os.path.dirname(_여기)
sys.path.insert(0, _뿌리)
os.environ.setdefault("KG_ENCODER", "문자")

import 자가저작                                   # noqa: E402


def 지금():
    """기록 + 지금 그래프가 몇 개인가. -> 화면이 그릴 것 전부"""
    바퀴 = 자가저작.바퀴읽기(200)
    쌓임, 노드누적, 엣지누적 = [], 0, 0
    for x in 바퀴:
        노드누적 += x.get("노드", 0)
        엣지누적 += x.get("엣지", 0)
        쌓임.append({"때": x.get("때"), "노드누적": 노드누적, "엣지누적": 엣지누적})
    import glob
    그래프수 = len(glob.glob(os.path.join(_뿌리, "graphs", "*.kg")))
    본데까지, 표제수, 버린말 = 자가저작.진도읽기()
    return {"바퀴": 바퀴, "쌓임": 쌓임, "그래프수": 그래프수,
            "진도": {"본데까지": 본데까지, "표제수": 표제수, "버린말": len(버린말)},
            "합": {"노드": 노드누적, "엣지": 엣지누적,
                   "들임": sum(x.get("들임", 0) for x in 바퀴),
                   "버림": sum(x.get("버림", 0) for x in 바퀴)}}


class 손(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _보내기(self, 몸, 형="application/json"):
        덩이 = 몸 if isinstance(몸, bytes) else 몸.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "%s; charset=utf-8" % 형)
        self.send_header("Content-Length", str(len(덩이)))
        self.end_headers()
        self.wfile.write(덩이)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            쪽 = io.open(os.path.join(_여기, "자람.html"), encoding="utf-8").read()
            return self._보내기(쪽, "text/html")
        if self.path == "/자람":
            return self._보내기(json.dumps(지금(), ensure_ascii=False))
        self.send_error(404)


def 띄우기(문=8766):
    print("기록: %s" % 자가저작.바퀴기록)
    칸 = 지금()
    print("  바퀴 %d개 · 들인 그래프 %d개 · 노드 +%d · 엣지 +%d"
          % (len(칸["바퀴"]), 칸["합"]["들임"], 칸["합"]["노드"], 칸["합"]["엣지"]))
    터 = HTTPServer(("127.0.0.1", 문), 손)
    print("\n  http://127.0.0.1:%d  — Ctrl+C 로 끝냅니다.\n" % 문)
    try:
        터.serve_forever()
    except KeyboardInterrupt:
        print("끝.")


def _자가검사():
    칸 = 지금()
    assert set(칸) == {"바퀴", "쌓임", "그래프수", "진도", "합"}, list(칸)
    # 쌓임은 누적이라 줄어들면 안 된다.
    앞 = -1
    for x in 칸["쌓임"]:
        assert x["노드누적"] >= 앞, x
        앞 = x["노드누적"]
    assert os.path.exists(os.path.join(_여기, "자람.html")), "화면 파일이 없다"
    print("자가검사 ok")


if __name__ == "__main__":
    if "--자가검사" in sys.argv:
        _자가검사()
    else:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        띄우기(int(인자[0]) if 인자 else 8766)
