# -*- coding: utf-8 -*-
"""딴 AI가 만든 표현 묶음을 `_동의어.json` 에 합친다.

    python add_synonyms.py 새동의어.json [--파일 docs/ko/_동의어.json]

이미 있던 표현은 지우지 않고 더한다. 그래프에 없는 노드와, 다른 노드가 이미
쓰는 표현은 버린다 — 표현이 겹치면 노드 경쟁이 심해져 오히려 나빠진다.
"""
import json
import os
import sys

default = "docs/ko/_동의어.json"


def merge(orig, fresh, node_present=None):
    """-> (합친 것, 더한 개수, 버린 것)"""
    whole_text = {k: list(v) for k, v in orig.items() if not k.startswith("_")}
    owner = {}
    for n, forms in whole_text.items():
        for t in forms:
            owner.setdefault(t.strip(), n)
    added, dropped = 0, []
    for n, forms in fresh.items():
        if n.startswith("_") or not isinstance(forms, list):
            continue
        if node_present is not None and n not in node_present:
            dropped.append((n, "그래프에 없는 노드"))
            continue
        slot = whole_text.setdefault(n, [n])
        for t in forms:
            t = str(t).strip()
            if not t or t in slot:
                continue
            holder = owner.get(t)
            if holder and holder != n:
                dropped.append((t, "이미 %s 의 표현" % holder))
                continue
            slot.append(t)
            owner[t] = n
            added += 1
    return whole_text, added, dropped


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    workdir = (sys.argv[sys.argv.index("--파일") + 1] if "--파일" in sys.argv else default)
    if not argv:
        print(__doc__)
        sys.exit(1)
    fresh = json.load(open(argv[0], encoding="utf-8"))
    orig = json.load(open(workdir, encoding="utf-8")) if os.path.exists(workdir) else {}
    explain = orig.get("_설명")
    node = None
    if os.path.exists("문서그래프.json"):
        node = set(json.load(open("문서그래프.json", encoding="utf-8"))["노드"])
    whole_text, added, dropped = merge(orig, fresh, node)
    out_edges = {"_설명": explain} if explain else {}
    out_edges.update({k: whole_text[k] for k in sorted(whole_text)})
    json.dump(out_edges, open(workdir, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("표현 %d개를 더했다 (노드 %d개) -> %s" % (added, len(whole_text), workdir))
    if dropped:
        print("버린 것 %d개:" % len(dropped))
        for t, why in dropped[:12]:
            print("   %-16s %s" % (t, why))
