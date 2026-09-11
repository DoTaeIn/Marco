# -*- coding: utf-8 -*-
"""대화 말은 그래프에서, 요청 말끝은 활용에서 온다는 것을 고정한다."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import graph_dialogue
import input_understanding
from language_components import load_language_pack


class RequestEndingTest(unittest.TestCase):
    """말끝은 적힌 것이 아니라 만들어진 것이다."""

    def setUp(self):
        self.pack = load_language_pack()
        # 라우터 없이도 요청은 풀린다. 대화 갈래만 라우터를 쓴다.
        self.backend = graph_dialogue.GraphDialogueBackend(router=lambda text: (None, 0.0, []))

    def test_one_action_reaches_every_declared_ending(self):
        for text in ("그거 요약해줘", "그거 요약해 주세요", "그거 요약해 줄래",
                     "그거 요약해 주실래요", "그거 요약해요", "그거 요약 좀",
                     "그거 요약 부탁해", "그거 요약하세요"):
            with self.subTest(text=text):
                parsed = self.backend.parse(text, self.pack)
                self.assertIsNotNone(parsed, text)
                self.assertEqual(parsed["intent"], "request.summary")

    def test_a_new_ending_needs_no_new_template(self):
        """어미를 하나 빼면 모든 동작이 함께 그 꼴을 잃는다 — 곱해져 있다는 뜻이다."""
        pack = dict(self.pack)
        conversation = dict(pack["conversation"])
        request = dict(conversation["request"])
        request["auxiliary_endings"] = [e for e in request["auxiliary_endings"]
                                        if e != "request_polite"]
        conversation["request"], pack["conversation"] = request, conversation
        backend = graph_dialogue.GraphDialogueBackend(router=lambda text: (None, 0.0, []))
        for stem in ("요약", "설명", "비교"):
            self.assertIsNone(backend.parse("그거 %s해 주세요" % stem, pack))
            self.assertIsNotNone(backend.parse("그거 %s해줘" % stem, pack))

    def test_korean_numeral_counts_the_same_as_a_digit(self):
        for text, want in (("회의록 3줄로 요약해줘", "3"), ("회의록 세 줄로 요약해줘", "3")):
            parsed = self.backend.parse(text, self.pack)
            self.assertEqual(parsed["slots"]["count"], want, text)
            self.assertEqual(parsed["modifiers"]["count_unit"], "줄")
            self.assertEqual(parsed["slots"]["target"], "회의록")

    def test_a_format_word_needs_the_instrumental_particle(self):
        """'표로 비교' 는 꼴이고 '표 설명' 은 대상이다."""
        self.assertEqual(self.backend.parse("보고서 표로 비교해줘", self.pack)["modifiers"]["format"],
                         ["table"])
        explained = self.backend.parse("이 표 설명해 주세요", self.pack)
        self.assertEqual(explained["modifiers"].get("format", []), [])
        self.assertEqual(explained["slots"]["target"], "이 표")


class GraphDialogueTest(unittest.TestCase):
    """인사말의 별칭은 언어팩이 아니라 .kg 에 있다."""

    def setUp(self):
        self.pack = load_language_pack()

    def test_aliases_come_from_the_graph_not_the_language_pack(self):
        self.assertNotIn("phrases", self.pack["conversation"])
        backend = graph_dialogue.GraphDialogueBackend(
            router=lambda text: ("graphs/graph_대화예절.kg", 1.0, []),
            loader=lambda path: "GRAPH",
            judge=lambda graph, text: ("인정", "안녕하세요, 반가워요"))
        parsed = backend.parse("안녕", self.pack)
        self.assertEqual(parsed["intent"], "dialogue")
        self.assertEqual(parsed["reply_text"], "안녕하세요, 반가워요")

    def test_the_reply_is_the_graph_sentence(self):
        spoken = input_understanding.dialogue_reply(
            "안녕", backend=graph_dialogue.GraphDialogueBackend(
                router=lambda text: ("graphs/graph_대화예절.kg", 1.0, []),
                loader=lambda path: "GRAPH",
                judge=lambda graph, text: ("인정", "안녕하세요, 반가워요")))
        self.assertEqual(spoken, "안녕하세요, 반가워요")

    def test_a_graph_that_did_not_win_routing_is_not_dialogue(self):
        """한 그래프에만 물으면 긴 문장 안의 짧은 말이 걸린다. 라우터가 막는다."""
        backend = graph_dialogue.GraphDialogueBackend(
            router=lambda text: ("graphs/graph_네트워크_기초.kg", 0.9, []),
            loader=lambda path: "GRAPH",
            judge=lambda graph, text: ("인정", "응, 알겠어"))
        self.assertIsNone(backend.parse("DNS는 이름을 주소로 바꿔 준다", self.pack))

    def test_without_a_router_no_dialogue_is_claimed(self):
        """확인하지 못한 것을 인정하지 않는다."""
        def broken(text):
            raise RuntimeError("색인 없음")
        backend = graph_dialogue.GraphDialogueBackend(
            router=broken, loader=lambda path: "GRAPH",
            judge=lambda graph, text: ("인정", "안녕하세요, 반가워요"))
        self.assertIsNone(backend.parse("안녕", self.pack))


if __name__ == "__main__":
    unittest.main()
