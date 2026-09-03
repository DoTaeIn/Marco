# -*- coding: utf-8 -*-
"""딴 AI가 만든 표현 묶음을 `_동의어.json` 에 합친다.

    python 동의어넣기.py 새동의어.json [--파일 docs/ko/_동의어.json]

이미 있던 표현은 지우지 않고 더한다. 그래프에 없는 노드와, 다른 노드가 이미
쓰는 표현은 버린다 — 표현이 겹치면 노드 경쟁이 심해져 오히려 나빠진다.
"""
import json
import os
import sys

기본 = "docs/ko/_동의어.json"


def 합치기(원본, 새것, 노드있음=None):
    """-> (합친 것, 더한 개수, 버린 것)"""
    본 = {k: list(v) for k, v in 원본.items() if not k.startswith("_")}
    임자 = {}
    for n, 표현들 in 본.items():
        for t in 표현들:
            임자.setdefault(t.strip(), n)
    더함, 버림 = 0, []
    for n, 표현들 in 새것.items():
        if n.startswith("_") or not isinstance(표현들, list):
            continue
        if 노드있음 is not None and n not in 노드있음:
            버림.append((n, "그래프에 없는 노드"))
            continue
        칸 = 본.setdefault(n, [n])
        for t in 표현들:
            t = str(t).strip()
            if not t or t in 칸:
                continue
            주인 = 임자.get(t)
            if 주인 and 주인 != n:
                버림.append((t, "이미 %s 의 표현" % 주인))
                continue
            칸.append(t)
            임자[t] = n
            더함 += 1
    return 본, 더함, 버림


if __name__ == "__main__":
    인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
    터 = (sys.argv[sys.argv.index("--파일") + 1] if "--파일" in sys.argv else 기본)
    if not 인자:
        print(__doc__)
        sys.exit(1)
    새것 = json.load(open(인자[0], encoding="utf-8"))
    원본 = json.load(open(터, encoding="utf-8")) if os.path.exists(터) else {}
    설명 = 원본.get("_설명")
    노드 = None
    if os.path.exists("문서그래프.json"):
        노드 = set(json.load(open("문서그래프.json", encoding="utf-8"))["노드"])
    본, 더함, 버림 = 합치기(원본, 새것, 노드)
    나감 = {"_설명": 설명} if 설명 else {}
    나감.update({k: 본[k] for k in sorted(본)})
    json.dump(나감, open(터, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("표현 %d개를 더했다 (노드 %d개) -> %s" % (더함, len(본), 터))
    if 버림:
        print("버린 것 %d개:" % len(버림))
        for t, 왜 in 버림[:12]:
            print("   %-16s %s" % (t, 왜))
