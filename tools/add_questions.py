# -*- coding: utf-8 -*-
"""딴 AI가 만든 물음 묶음을 한 번에 넣는다.

    python add_questions.py 새물음.json [--쓴이 딴AI]

kgpack_ui 가 8766 에 떠 있어야 한다(views/kgpack_ui.py). 예전에는
views/물음판.py 에 넣었는데, 화면을 kgpack_ui 하나로 모으면서 그 판을
지우고 물음 기록도 이쪽으로 옮겼다.

줄마다 쓴이가 남으므로 사람이 쓴 것과 섞이지 않는다 — 기계가 쓴 질문은
코퍼스를 이미 읽고 쓴 것이라 어휘가 새서, 같은 통에 넣되 갈라 세야 한다.
"""
import json, sys, urllib.error, urllib.request

URL = "http://127.0.0.1:8766/api/ask"


def add(line, author):
    trunk = {"question": (line.get("질문") or "").strip(), "writer": author}
    if line.get("기대"):
        trunk["기대"] = line["기대"]
    req = urllib.request.Request(URL, json.dumps(trunk).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def attach_expected_topic(log_dir, table):
    """화면은 기대주제를 모르므로, 넣은 뒤 파일에 적어 채점되게 한다."""
    lines = []
    for line in open(log_dir, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        topic = table.get(d["질문"])
        if topic and "표" not in d:
            d["기대주제"] = topic
            d["표"] = "맞음" if d.get("주제") in topic else "틀림"
            d["표한이"] = "기대주제"
        lines.append(d)
    with open(log_dir, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    author = (sys.argv[sys.argv.index("--쓴이") + 1] if "--쓴이" in sys.argv else "딴AI")
    if not argv:
        print(__doc__)
        sys.exit(1)
    group = json.load(open(argv[0], encoding="utf-8"))
    if isinstance(group, dict):
        group = group.get("물음") or group.get("questions") or []
    table, put = {}, 0
    for line in group:
        q = (line.get("질문") or "").strip()
        if not q:
            continue
        try:
            add(line, author)
        except urllib.error.URLError as e:
            print("kgpack_ui 가 안 떠 있는 것 같습니다 (%s)" % e)
            sys.exit(1)
        if line.get("기대주제"):
            table[q] = list(line["기대주제"])
        put += 1
    print("넣은 물음 %d개 (쓴이 %s)" % (put, author))
    if table:
        attach_expected_topic("물음기록.jsonl", table)
        print("기대주제로 채점한 물음 %d개" % len(table))
