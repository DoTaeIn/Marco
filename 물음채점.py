# -*- coding: utf-8 -*-
"""물음기록을 지금 그래프로 다시 풀어 갈래별로 채점한다.

    KG_ENCODER=문자 python 물음채점.py [--쓴이 딴AI]

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


def 채점(그래프="문서그래프.json", 쓴이=None):
    g = explain.열기(explain._길(그래프))
    갈래 = defaultdict(lambda: [0, 0])
    안맞 = 안총 = 밖맞 = 밖총 = 샌 = 0
    for 줄 in io.open("물음기록.jsonl", encoding="utf-8"):
        줄 = 줄.strip()
        if not 줄:
            continue
        d = json.loads(줄)
        if 쓴이 and d.get("쓴이") != 쓴이:
            continue
        뜻, _답, 주제 = explain.물어보기(g, d["질문"])
        if d.get("기대"):
            ok = 뜻 == d["기대"]
            밖맞 += ok
            밖총 += 1
            샌 += 뜻 == "설명"
        elif d.get("기대주제"):
            ok = 주제 in d["기대주제"]
            안맞 += ok
            안총 += 1
        else:
            continue
        갈래[d.get("갈래", "?")][0] += ok
        갈래[d.get("갈래", "?")][1] += 1
    return 갈래, (안맞, 안총), (밖맞, 밖총, 샌)


if __name__ == "__main__":
    쓴이 = (sys.argv[sys.argv.index("--쓴이") + 1] if "--쓴이" in sys.argv else None)
    갈래, 안, 밖 = 채점(쓴이=쓴이)
    print("%-12s %7s %6s" % ("갈래", "적중", "개수"))
    for k in sorted(갈래, key=lambda x: (not x.startswith(("의도", "안")), x)):
        a, b = 갈래[k]
        if b:
            print("%-12s %5.0f%% %6d" % (k, 100 * a / b, b))
    print()
    print("코퍼스 안 %d/%d (%.0f%%) · 밖 %d/%d (%.0f%%) · 실제로 답해버린 밖 %d개"
          % (안[0], 안[1], 100 * 안[0] / max(안[1], 1),
             밖[0], 밖[1], 100 * 밖[0] / max(밖[1], 1), 밖[2]))
