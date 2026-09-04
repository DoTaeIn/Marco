# -*- coding: utf-8 -*-
"""통합 턴에서 유사 KG 답변이 산술/미지를 오염시키지 않는지 검증한다."""
from pathlib import Path
import tempfile
import unittest

from views.kgpack_ui import 앱상태
from views.kgpack_ui import 질문대목
from semantic_parser import CallableBackend, SemanticParser


def _span(text, literal):
    at = text.index(literal)
    return {"start": at, "end": at + len(literal), "text": literal}


def _semantic_candidate(text):
    if "1 더하기 1" not in text:
        return {"intent": "question", "entities": [], "quantities": [], "relations": [], "query": None}
    return {"intent": "question", "entities": [], "quantities": [],
            "relations": [{"type": "arithmetic", "args": {"operator": "+", "left": 1, "right": 1},
                           "evidence": _span(text, "더하기")}],
            "query": {"kind": "value", "target": "더하기", "evidence": _span(text, "더하기")}}


class TurnRoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # NAI.kgpack 은 생성물이라 .gitignore 에 있다. 새로 클론한 곳에는 없다.
        # 없다고 시험이 깨지면 안 된다 — 만드는 법을 알려주고 건너뛴다.
        묶음 = Path(__file__).resolve().parent.parent / "NAI.kgpack"
        if not 묶음.is_file():
            raise unittest.SkipTest(
                "NAI.kgpack 이 없다. `python kgpack.py --pack NAI.kgpack --root .` 로 만든다")
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = 앱상태(묶음, overlay_root=cls.temp.name)
        cls.app.semantic_parser = SemanticParser(CallableBackend(_semantic_candidate))

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def turn(self, text):
        return self.app.turn(text, "routing-test-session")

    def test_exact_arithmetic_bypasses_kg_similarity(self):
        result = self.turn("1 더하기 1은 얼마야?")
        self.assertEqual(result["phase"], "answer")
        self.assertEqual(result["answer"]["answer"], "2입니다.")
        self.assertEqual(result["answer"]["trace"]["mode"], "situation")
        self.assertEqual(result["answer"]["info"]["routed_graph"], "graphs/graph_일상추론.kg")
        self.assertTrue(result["answer"]["semantic_parse"]["accepted"])
        self.assertEqual(result["answer"]["reasoning"]["operator"], "arithmetic")

    def test_only_explicitly_approved_semantic_parse_is_saved(self):
        result = self.turn("1 더하기 1은 얼마야?")
        answer = result["answer"]
        saved = self.app.save_semantic_correction("routing-test-session", "1 더하기 1은 얼마야?",
                                                   answer["semantic_parse"], answer["verification"])
        self.assertTrue(saved["saved"])
        self.assertTrue(Path(saved["path"]).read_text(encoding="utf-8").strip())

    def test_narrative_context_is_one_question_not_many_kg_queries(self):
        text = "배가 떠 있습니다. 수면이 오릅니다. 사다리는 몇 칸 남나요?"
        self.assertEqual(질문대목(text), [text])

    def test_one_question_activates_only_one_kg_candidate(self):
        result = self.turn("완전히 낯선 주제는 무엇인가요?")
        selected = ((result.get("answer", {}).get("trace") or {}).get("route") or {}).get("selected_all", [])
        self.assertLessEqual(len(selected), 1)

    def test_unknown_never_forces_auto_learning_graph(self):
        self.app.goals.research = lambda text: {"query": text, "sources": [], "verified": False}
        result = self.turn("바람의 기분은 몇 점일까?")
        self.assertEqual(result["phase"], "research")
        self.assertEqual(result["answer"]["trace"]["verdict"], "미지")
        self.assertFalse((result["answer"]["trace"].get("route") or {}).get("fallback"))
        self.assertIsNone(result["answer"]["info"]["routed_graph"])

    def test_greeting_does_not_start_web_research(self):
        result = self.turn("안녕")
        self.assertEqual(result["phase"], "answer")
        self.assertEqual(result["answer"]["trace"]["mode"], "dialogue")
        self.assertIsNone(result["answer"]["info"]["routed_graph"])

    def test_unknown_learning_target_is_not_answer_fallback(self):
        self.app.goals.research = lambda text: {"query": text, "verified": True,
                                                "sources": [{"domain": "a.example"}, {"domain": "b.example"}]}
        # 의미 유사도 자체가 없는 매니저 상태로 만들어, 이 검증을 기존 KG
        # 어휘나 인코더 점수에 의존시키지 않는다.
        saved_index = self.app.manager_index
        self.app.manager_index = {"공통층": {}}
        try:
            result = self.turn("완전히 새로운 주제")
        finally:
            self.app.manager_index = saved_index
        self.assertEqual(result["phase"], "research")
        self.assertEqual(result["answer"]["trace"]["verdict"], "미지")
        self.assertTrue(any(action["kind"] == "knowledge.learn" for action in result["plan"]["actions"]))
        self.assertTrue(result["plan"]["graph_path"].endswith("graph_자가학습.kg"))

    def test_fixed_kg_requires_exact_evidence_not_semantic_similarity(self):
        self.app.select("graphs/graph_AGI_최소지식.kg")
        result = self.app.ask("1 더하기 1은 얼마야?", allow_learning=False)
        self.assertFalse(result["known"])
        self.assertEqual(result["trace"]["verdict"], "근거불충분")
        self.app.select("__kg_manager__")


if __name__ == "__main__":
    unittest.main()
