# -*- coding: utf-8 -*-
"""딴 AI가 만든 물음 묶음을 한 번에 넣는다.

    python 물음넣기.py 새물음.json [--쓴이 딴AI]

kgpack_ui 가 8766 에 떠 있어야 한다(views/kgpack_ui.py). 예전에는
views/물음판.py 에 넣었는데, 화면을 kgpack_ui 하나로 모으면서 그 판을
지우고 물음 기록도 이쪽으로 옮겼다.

줄마다 쓴이가 남으므로 사람이 쓴 것과 섞이지 않는다 — 기계가 쓴 질문은
코퍼스를 이미 읽고 쓴 것이라 어휘가 새서, 같은 통에 넣되 갈라 세야 한다.
"""
import json, sys, urllib.error, urllib.request

URL = "http://127.0.0.1:8766/api/ask"


def 넣기(줄, 쓴이):
    몸 = {"question": (줄.get("질문") or "").strip(), "writer": 쓴이}
    if 줄.get("기대"):
        몸["기대"] = 줄["기대"]
    req = urllib.request.Request(URL, json.dumps(몸).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def 기대주제붙이기(기록터, 표):
    """화면은 기대주제를 모르므로, 넣은 뒤 파일에 적어 채점되게 한다."""
    줄들 = []
    for 줄 in open(기록터, encoding="utf-8"):
        줄 = 줄.strip()
        if not 줄:
            continue
        d = json.loads(줄)
        주제 = 표.get(d["질문"])
        if 주제 and "표" not in d:
            d["기대주제"] = 주제
            d["표"] = "맞음" if d.get("주제") in 주제 else "틀림"
            d["표한이"] = "기대주제"
        줄들.append(d)
    with open(기록터, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(json.dumps(x, ensure_ascii=False) for x in 줄들) + "\n")


if __name__ == "__main__":
    인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
    쓴이 = (sys.argv[sys.argv.index("--쓴이") + 1] if "--쓴이" in sys.argv else "딴AI")
    if not 인자:
        print(__doc__)
        sys.exit(1)
    묶음 = json.load(open(인자[0], encoding="utf-8"))
    if isinstance(묶음, dict):
        묶음 = 묶음.get("물음") or 묶음.get("questions") or []
    표, 넣은 = {}, 0
    for 줄 in 묶음:
        q = (줄.get("질문") or "").strip()
        if not q:
            continue
        try:
            넣기(줄, 쓴이)
        except urllib.error.URLError as e:
            print("kgpack_ui 가 안 떠 있는 것 같습니다 (%s)" % e)
            sys.exit(1)
        if 줄.get("기대주제"):
            표[q] = list(줄["기대주제"])
        넣은 += 1
    print("넣은 물음 %d개 (쓴이 %s)" % (넣은, 쓴이))
    if 표:
        기대주제붙이기("물음기록.jsonl", 표)
        print("기대주제로 채점한 물음 %d개" % len(표))
