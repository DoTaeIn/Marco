# -*- coding: utf-8 -*-
"""위키백과에서 글을 받아 자료/ 에 넣는다. 검색은 답하는 도구가 아니라 자료를 늘리는 도구다.

    python 위키.py 정당방위 명예훼손        # 받아서 자료/웹/ 에 저장
    python 위키.py --찾기 저작권             # 무엇이 있는지 먼저 본다

받은 글은 그래프에 바로 들어가지 않는다. 자료/ 에 놓이고, 거기서부터는
기존 흐름 그대로다 — 짓기.py 로 그래프를 만들거나 engine.py --mine 으로
노드 후보를 뽑고 사람이 확인한다.

이 순서를 지키는 이유는 하나다. 검색 결과는 근거가 아니라 남의 주장이다.
그것을 곧바로 답으로 내보내면 이 엔진이 파는 유일한 것(모든 답에 영수증)이
무너진다. 자료로 들어와 사람이 확인하고 그래프가 되어야 근거가 된다.

키가 필요 없다. 법제처 API 와 달리 위키백과는 열려 있다.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

밖 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "자료", "웹")
헤더 = {"User-Agent": "Objection/0.1 (knowledge graph authoring; contact via github)"}
API = "https://ko.wikipedia.org/w/api.php?"


def _부르기(**인자):
    인자.setdefault("format", "json")
    url = API + urllib.parse.urlencode(인자, encoding="utf-8")
    req = urllib.request.Request(url, headers=헤더)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def 찾기(말, 수=8):
    """-> [{제목, 단어수}]"""
    r = _부르기(action="query", list="search", srsearch=말, srlimit=수)
    return [{"제목": x["title"], "단어수": x.get("wordcount", 0)}
            for x in r.get("query", {}).get("search", [])]


def 받기(제목):
    """문서 하나의 본문. 위키 문법을 걷어낸 평문."""
    r = _부르기(action="query", prop="extracts", titles=제목,
                explaintext=1, exsectionformat="plain", redirects=1)
    쪽 = list(r.get("query", {}).get("pages", {}).values())
    if not 쪽 or "extract" not in 쪽[0]:
        return None
    본문 = 쪽[0]["extract"]
    본문 = re.sub(r"\n{3,}", "\n\n", 본문).strip()
    return 본문 or None


def 저장(제목, 본문):
    os.makedirs(밖, exist_ok=True)
    안전 = re.sub(r'[\\/:*?"<>|]', "", 제목).replace(" ", "_")
    경로 = os.path.join(밖, "위키_%s.txt" % 안전)
    with open(경로, "w", encoding="utf-8") as f:
        f.write("# 출처: 위키백과 「%s」 (https://ko.wikipedia.org/wiki/%s)\n"
                % (제목, urllib.parse.quote(제목.replace(" ", "_"))))
        f.write("# 받은 날: %s\n\n" % time.strftime("%Y-%m-%d"))
        f.write(본문 + "\n")
    return 경로


if __name__ == "__main__":
    인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--찾기" in sys.argv:
        if not 인자:
            print("사용법: python 위키.py --찾기 <말>")
            sys.exit(1)
        for x in 찾기(인자[0]):
            print("  %-34s %5d 단어" % (x["제목"], x["단어수"]))
        sys.exit(0)

    if not 인자:
        print(__doc__)
        sys.exit(1)
    for 말 in 인자:
        try:
            후보 = 찾기(말, 1)
            if not 후보:
                print("?  %-16s 찾지 못했다" % 말)
                continue
            제목 = 후보[0]["제목"]
            본문 = 받기(제목)
            if not 본문:
                print("?  %-16s 본문이 비었다 (%s)" % (말, 제목))
                continue
            경로 = 저장(제목, 본문)
            print("OK %-16s -> %s  (%d자)" % (말, 경로, len(본문)))
        except Exception as e:
            print("X  %-16s %s: %s" % (말, type(e).__name__, e))
        time.sleep(0.4)
    print()
    print("자료로 들어갔을 뿐 그래프가 된 것은 아니다. 다음 중 하나를 한다:")
    print("  python 짓기.py 자료/웹 --out 웹그래프.json")
    print("  python engine.py --mine <그래프.kg> 자료/웹/위키_....txt")
