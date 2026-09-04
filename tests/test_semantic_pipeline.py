# -*- coding: utf-8 -*-
import unittest
from pathlib import Path

from semantic_parser import CallableBackend, SemanticParser, validate
import state_engine


# 시험은 tests/ 에 있고 그래프는 저장소 뿌리에 있다
KG = Path(__file__).resolve().parent.parent / "graphs" / "graph_일상추론.kg"


def evidence(text, literal):
    start = text.index(literal)
    return {"start": start, "end": start + len(literal), "text": literal}


def candidate(text, relation, args, query_literal, quantities=()):
    return {"intent": "question", "entities": [],
            "quantities": [{"id": "q%d" % i, "value": value, "unit": unit,
                            "evidence": evidence(text, literal)}
                           for i, (value, unit, literal) in enumerate(quantities)],
            "relations": [{"type": relation, "args": args,
                           "evidence": evidence(text, query_literal)}],
            "query": {"kind": "value", "target": query_literal,
                      "evidence": evidence(text, query_literal)}, "uncertainties": []}


class SemanticPipelineTest(unittest.TestCase):
    def parse(self, text, relation, args, query, quantities=()):
        raw = candidate(text, relation, args, query, quantities)
        return SemanticParser(CallableBackend(lambda _text: raw)).parse(text)

    def test_model_candidate_requires_exact_source_span(self):
        text = "1 더하기 1은 얼마야?"
        raw = candidate(text, "arithmetic", {"operator": "+", "left": 1, "right": 1}, "더하기")
        raw["relations"][0]["evidence"]["end"] += 1
        parsed = validate(text, raw, model_id="test")
        self.assertFalse(parsed["accepted"])
        self.assertTrue(any(x["reason"] == "evidence_not_exact" for x in parsed["rejected"]))

    def test_generic_operators_use_state_json_not_problem_words(self):
        cases = [
            ("1 더하기 1은 얼마야?", "arithmetic", {"operator": "+", "left": 1, "right": 1}, "더하기", "2입니다."),
            ("작업 하나는 1시간이고 열 작업을 동시에 독립적으로 끝낸다면?", "parallel_completion", {"duration": 1, "unit": "시간", "simultaneous": True, "independent": True}, "동시에", "1시간입니다."),
            ("예전에 나이 차가 3살이고 내가 70살이면 동생은 몇 살인가?", "age_difference", {"later_age": 70, "age_difference": 3}, "나이", "67살입니다."),
            ("경기에서 2등 선수를 추월했다면 내 등수는?", "rank_overtake", {"overtaken_rank": 2}, "추월", "2등입니다."),
            ("떠 있는 물체에 고정된 사다리의 수면 위 5칸은 함께 움직이면?", "co_moving_reference", {"visible_count": 5, "same_reference_frame": True}, "함께", "5칸입니다."),
        ]
        for text, relation, args, marker, expected in cases:
            with self.subTest(relation=relation):
                parsed = self.parse(text, relation, args, marker)
                out = state_engine.evaluate(parsed, KG)
                self.assertEqual(out["status"], "answered")
                self.assertEqual(out["answer"], expected)
                self.assertEqual(out["operator"], relation)

    def test_kg_grounded_indivisible_and_unitary_premise(self):
        text = "임신출산 하나에 9개월이 걸리고 한 아이만 낳는다면?"
        parsed = self.parse(text, "indivisible_process", {"process": "임신출산", "duration": 9, "unit": "개월", "single_output": True}, "임신출산")
        self.assertEqual(state_engine.evaluate(parsed, KG)["answer"], "9개월입니다.")
        text = "반쪽짜리 구멍을 파는 전제는 가능한가?"
        parsed = self.parse(text, "unitary_concept", {"concept": "구멍", "fractional_premise": True}, "구멍")
        self.assertEqual(state_engine.evaluate(parsed, KG)["status"], "premise_invalid")

    def test_unsupported_relation_is_unknown_not_a_guess(self):
        text = "바람의 기분은 몇 점일까?"
        parsed = validate(text, {"intent": "question", "relations": [], "query": None}, model_id="test")
        out = state_engine.evaluate(parsed, KG)
        self.assertEqual(out["status"], "unknown")
        self.assertEqual(out["verification"]["reason"], "semantic_parse_not_certified")


if __name__ == "__main__":
    unittest.main()
