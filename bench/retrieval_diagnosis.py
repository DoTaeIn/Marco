"""Diagnose frozen retrieval failures without changing their correctness labels.

Graph proximity is diagnostic evidence only: an argument edge is not equivalence.
Run with KG_ENCODER=문자 python bench/retrieval_diagnosis.py --output PATH.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def classify(expected, selected, edges):
    if selected == expected:
        return "exact", 0
    adjacency = defaultdict(set)
    for source, relation, target in edges:
        if {source, target} == {expected, selected}:
            if relation == "설명함":
                return "explanation_neighbor", 1
        adjacency[source].add(target)
        adjacency[target].add(source)
    if selected in adjacency[expected]:
        return "argument_neighbor", 1
    queue = deque([(expected, 0)])
    seen = {expected}
    while queue:
        node, distance = queue.popleft()
        for neighbor in adjacency[node] - seen:
            if neighbor == selected:
                return "connected_elsewhere", distance + 1
            seen.add(neighbor)
            queue.append((neighbor, distance + 1))
    return "disconnected", None


def run():
    import engine
    import yardstick

    frozen = Path(yardstick.frozen_dir)
    before = frozen.read_bytes()
    dataset = json.loads(before)
    rows = []
    for group, strip in (("대조", False), ("안", True)):
        grouped = defaultdict(list)
        for case in dataset[group]:
            grouped[case["그래프"]].append(case)
        for path, cases in sorted(grouped.items()):
            graph_rows = []
            try:
                graph = copy.deepcopy(engine.read_kg(str(ROOT / path)))
                if strip:
                    drop = {case["물음"] for case in cases}
                    for layer in ("공통층", "사례층"):
                        for node, phrases in list(graph.get(layer, {}).items()):
                            graph[layer][node] = [p for p in phrases if p not in drop]
                candidates = [node for layer in ("공통층", "사례층")
                              for node, phrases in graph.get(layer, {}).items() if phrases]
                # Unlike the legacy yardstick, empty aliases cannot retain the
                # held-out question. Surface missing candidates as errors.
                graph["vec"] = engine._example_vecs(graph)
                for case in cases:
                    row = {"group": group, "graph": path, "question": case["물음"],
                           "expected": case["노드"]}
                    if case["노드"] not in candidates:
                        row.update(category="missing_candidate", distance=None)
                    else:
                        selected, score = engine.match(case["물음"], candidates, graph)
                        category, distance = classify(case["노드"], selected, graph.get("엣지", []))
                        row.update(selected=selected, score=score, category=category,
                                   distance=distance,
                                   expected_score=engine.match(case["물음"], [case["노드"]], graph)[1],
                                   expected_aliases=[p for layer in ("공통층", "사례층")
                                                     for p in graph.get(layer, {}).get(case["노드"], [])],
                                   selected_aliases=[p for layer in ("공통층", "사례층")
                                                     for p in graph.get(layer, {}).get(selected, [])])
                    graph_rows.append(row)
            except Exception as exc:
                graph_rows = [{"group": group, "graph": path, "question": case["물음"],
                             "expected": case["노드"], "category": "runtime_error",
                             "error": f"{type(exc).__name__}: {exc}"} for case in cases]
            rows.extend(graph_rows)
    if frozen.read_bytes() != before:
        raise RuntimeError("Frozen dataset changed during evaluation")
    return {"schema": "retrieval-diagnosis-v1", "encoder": engine.MODEL,
            "dataset_sha256": hashlib.sha256(before).hexdigest(),
            "scope": "oracle graph node selection; proximity is not answer correctness",
            "counts": {group: dict(Counter(row["category"] for row in rows if row["group"] == group))
                       for group in ("대조", "안")}, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2))
