# -*- coding: utf-8 -*-
"""무거운 문장 인코더 없이 공통 대화 계약을 검증한다."""
import sys
import types
import unittest


class CommonConversationTest(unittest.TestCase):
    def setUp(self):
        self.old_engine = sys.modules.get("engine")
        self.old_explain = sys.modules.get("explain")
        engine = types.ModuleType("engine")
        engine.POS = ("증명", "충족")
        engine.전진들 = lambda g: tuple(g.get("전진관계") or engine.POS)
        engine.load = lambda _: {"목표": "끝", "adj": {"사실": [("증명", "근거")], "근거": [("충족", "끝")]}}

        class Session:
            회차 = 0
            계획 = {}
            def __init__(self, graph): self.graph = graph
            def 말하기(self, text):
                self.회차 += 1; self.계획 = {"주장": "사실"}
                return "인정", "그래프 근거로 답합니다.", None
            def 결과(self): return None
            def 현황(self): return ".끝"
        engine.세션 = Session

        explain = types.ModuleType("explain")
        explain.열기 = lambda _: {"노드": {"정의": ["정의"]}}
        class Memory:
            def __init__(self): self.turn = 0; self.items = []
            def 한턴(self, topics, question, topic): self.turn += 1; self.items.append((topics, question, topic))
            def 뜨거운(self): return [x[2] for x in self.items if x[2]][-5:]
        explain.대화기억 = Memory
        explain.물어보기 = lambda _g, text, memory: ("이유", "그래프의 근거입니다.", "정의")
        sys.modules["engine"] = engine
        sys.modules["explain"] = explain
        import nai
        self.nai = nai

    def tearDown(self):
        for name, old in (("engine", self.old_engine), ("explain", self.old_explain)):
            if old is None: sys.modules.pop(name, None)
            else: sys.modules[name] = old

    def test_game_exposes_forward_path(self):
        conversation = self.nai.Conversation("example.kg")
        answer = conversation.reply("사실입니다")
        self.assertEqual((answer.intent, answer.topic), ("인정", "사실"))
        self.assertEqual(answer.path, ["사실", "근거", "끝"])

    def test_game_hides_untrusted_topic(self):
        conversation = self.nai.Conversation("example.kg")
        conversation._session.말하기 = lambda _text: ("미지", "모르겠습니다.", None)
        conversation._session.계획 = {"주장": "사실"}
        answer = conversation.reply("알 수 없는 말")
        self.assertIsNone(answer.topic)
        self.assertEqual(answer.path, [])

    def test_guide_updates_context_after_every_reply(self):
        conversation = self.nai.Conversation("docs.json")
        answer = conversation.reply("왜 그래?")
        self.assertEqual((answer.intent, answer.topic), ("이유", "정의"))
        self.assertEqual(conversation.state()["active_topics"], ["정의"])


if __name__ == "__main__":
    unittest.main()
