# -*- coding: utf-8 -*-
"""물음기록을 지금 그래프로 다시 풀어 갈래별로 채점한다.

    KG_ENCODER=문자 python grade_questions.py [--쓴이 딴AI]

기록에 적힌 `기대주제`/`기대` 로 채점한다. 사람이 표시한 줄은 그것을 쓴다.
"""
import io
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("KG_ENCODER", "문자")
import explain  # noqa: E402


def grade(graph="문서그래프.json", author=None):
    g = explain.open_(explain._abs(graph))
    kind = defaultdict(lambda: [0, 0])
    hit_inside = inside_total = hit_outside = outside_total = leaked = 0
    for line in io.open("물음기록.jsonl", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if author and d.get("쓴이") != author:
            continue
        meaning, _ans, topic = explain.ask(g, d["질문"])
        if d.get("기대"):
            ok = meaning == d["기대"]
            hit_outside += ok
            outside_total += 1
            leaked += meaning == "설명"
        elif d.get("기대주제"):
            ok = topic in d["기대주제"]
            hit_inside += ok
            inside_total += 1
        else:
            continue
        kind[d.get("갈래", "?")][0] += ok
        kind[d.get("갈래", "?")][1] += 1
    return kind, (hit_inside, inside_total), (hit_outside, outside_total, leaked)


if __name__ == "__main__":
    author = (sys.argv[sys.argv.index("--쓴이") + 1] if "--쓴이" in sys.argv else None)
    kind, inside, outside = grade(author=author)
    print("%-12s %7s %6s" % ("갈래", "적중", "개수"))
    for k in sorted(kind, key=lambda x: (not x.startswith(("의도", "안")), x)):
        a, b = kind[k]
        if b:
            print("%-12s %5.0f%% %6d" % (k, 100 * a / b, b))
    print()
    print("코퍼스 안 %d/%d (%.0f%%) · 밖 %d/%d (%.0f%%) · 실제로 답해버린 밖 %d개"
          % (inside[0], inside[1], 100 * inside[0] / max(inside[1], 1),
             outside[0], outside[1], 100 * outside[0] / max(outside[1], 1), outside[2]))
