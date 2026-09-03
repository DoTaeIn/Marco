# -*- coding: utf-8 -*-
import os
import json
import shutil
import tempfile
import unittest

from npc import NPC, World, Event, _demo


class NPCRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.world = World(state={"market_open": False})
        self.mina = self.world.add(NPC("mina", "미나", location="광장", goals=["빵 판매"] ))
        self.jun = self.world.add(NPC("jun", "준", location="광장"))

    def test_interaction_changes_both_relationships_and_world(self):
        event = self.world.interact("mina", "jun", "help", topic="상자 운반",
                                    effects={"world": {"market_open": True}})
        self.assertEqual(event.kind, "help")
        self.assertEqual(self.mina.relation_to("jun").trust, 6)
        self.assertEqual(self.jun.relation_to("mina").affinity, 8)
        self.assertTrue(self.world.state["market_open"])
        self.assertEqual(len(self.jun.memories), 1)

    def test_named_lovers_relationship_survives_save(self):
        self.world.set_relationship("mina", "jun", "lover", affinity=90, trust=85)
        restored = World.restore(self.world.snapshot())
        relation = restored.npcs["mina"].relation_to("jun")
        self.assertEqual((relation.kind, relation.affinity, relation.trust), ("lover", 90, 85))

    def test_tick_causes_colocated_npcs_to_act(self):
        events = self.world.tick()
        self.assertEqual([event.kind for event in events], ["talk", "talk"])
        self.assertEqual(self.world.tick_count, 1)

    def test_snapshot_round_trip_keeps_social_state(self):
        self.world.interact("mina", "jun", "share", effects={"world": {"rumor": "비"}})
        restored = World.restore(self.world.snapshot())
        self.assertEqual(restored.state["rumor"], "비")
        self.assertEqual(restored.npcs["mina"].relation_to("jun").trust, 4)
        self.assertEqual(restored.events[-1].kind, "share")

    def test_graph_dialogue_is_connected_lazily(self):
        class Reply:
            text, topic, intent, path = "빵은 남쪽 가게에 있습니다.", "빵", "인정", ["빵"]
        class Chat:
            def reply(self, text): return Reply()
        world = World(conversation_factory=lambda path: Chat())
        world.add(NPC("guide", "안내인", graph_path="town.kg"))
        event = world.speak("guide", "빵은 어디에 있지?")
        self.assertEqual((event.text, event.topic, event.effects["intent"]),
                         (Reply.text, "빵", "인정"))

    def test_demo_creates_shared_result(self):
        world = _demo()
        self.assertTrue(world.state["market_open"])
        self.assertGreaterEqual(len(world.events), 3)


if __name__ == "__main__":
    unittest.main()


class 겪음테스트(unittest.TestCase):
    """목격한 NPC 만 그래프가 자란다."""

    def setUp(self):
        self.터 = tempfile.mkdtemp()
        본 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "graphs", "npc_대장장이.kg")
        self.갑길 = os.path.join(self.터, "갑.kg")
        self.을길 = os.path.join(self.터, "을.kg")
        for 길 in (self.갑길, self.을길):
            shutil.copy(본, 길)

    def tearDown(self):
        shutil.rmtree(self.터, ignore_errors=True)

    def _세계(self):
        w = World(겪음지도={"help": ("내놓음", "고칠물건있음")})
        w.add(NPC("갑", "갑", graph_path=self.갑길, location="광장"))
        w.add(NPC("을", "을", graph_path=self.을길, location="집"))
        w.add(NPC("톰", "톰", location="광장"))
        w.add(NPC("제리", "제리", location="광장"))
        return w

    def test_목격자만_겪음을_남긴다(self):
        w = self._세계()
        w._record(Event(1, "톰", "help", "제리", None, None, {}), w.npcs["갑"])
        갑겪 = os.path.splitext(self.갑길)[0] + ".겪음.jsonl"
        을겪 = os.path.splitext(self.을길)[0] + ".겪음.jsonl"
        self.assertTrue(os.path.exists(갑겪))
        self.assertFalse(os.path.exists(을겪))
        줄들 = [json.loads(x) for x in open(갑겪, encoding="utf-8") if x.strip()]
        self.assertEqual(줄들[0]["말"], ["톰이 제리를 도왔다"])   # 조사가 맞아야 증거로 걸린다
        self.assertEqual(줄들[1]["엣지"][1], "내놓음")

    def test_그래프가_실제로_자란다(self):
        import engine
        전 = engine.load(self.갑길)
        전노드, 전엣지 = len(전["사례층"]), len(전["엣지"])
        w = self._세계()
        w._record(Event(1, "톰", "help", "제리", None, None, {}), w.npcs["갑"])
        후 = engine.load(self.갑길)
        self.assertEqual(len(후["사례층"]), 전노드 + 1)
        self.assertEqual(len(후["엣지"]), 전엣지 + 1)
        self.assertIn("겪음_톰_help_제리", 후["증거"])
        # 못 본 쪽은 그대로다
        을 = engine.load(self.을길)
        self.assertEqual(len(을["사례층"]), 전노드)

    def test_얹을수없는_겪음은_조용히_버린다(self):
        """겪음은 언제나 신뢰할 수 없는 입력이다. 게임이 안 뜨면 안 된다."""
        import engine
        겪 = os.path.splitext(self.갑길)[0] + ".겪음.jsonl"
        with open(겪, "w", encoding="utf-8") as f:
            f.write(json.dumps({"엣지": ["없는놈", "내놓음", "고칠물건있음"]},
                               ensure_ascii=False) + "\n")
            f.write(json.dumps({"엣지": ["부러진검", "없는관계", "삯을치름"]},
                               ensure_ascii=False) + "\n")
            f.write("{망가진 줄\n")
        g = engine.load(self.갑길)             # 예외가 나면 안 된다
        이유 = [x[2] for x in g["_겪음버림"]]
        self.assertIn("모르는 노드", 이유)
        self.assertIn("이 그래프에 없는 관계", 이유)
