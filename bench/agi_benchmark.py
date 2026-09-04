# -*- coding: utf-8 -*-
"""최소 AGI 지식 그래프의 공개형 문제·정답 확인기.

    KG_ENCODER=문자 python agi_benchmark.py
"""
import engine
from test_agi_minimum_knowledge import CASES, GRAPH


def run():
    graph = engine.load(GRAPH)
    passed = 0
    for index, (question, (expected_evidence, expected_concept, expected_text)) in enumerate(CASES.items(), 1):
        evidence, score = engine.match_evidence(question, graph)
        session = engine.세션(graph)
        tag, answer, _ = session.말하기(question)
        concept = session.계획.get("주장")
        ok = (evidence == expected_evidence and concept == expected_concept
              and tag == "인정" and expected_text in answer)
        passed += ok
        print("[%02d] %s" % (index, "정답" if ok else "오답"))
        print("  문제: %s" % question)
        print("  기대: %s → %s" % (expected_evidence, expected_concept))
        print("  결과: %s → %s (%.3f)" % (evidence, concept, score))
        print("  답변: %s" % answer)
    print("\n점수: %d/%d" % (passed, len(CASES)))
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(run())
