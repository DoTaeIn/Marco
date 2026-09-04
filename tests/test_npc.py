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
        # 시험은 tests/ 에 있고 그래프는 저장소 뿌리에 있다
        본 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
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


class 소문테스트(unittest.TestCase):
    """들은 것은 근거가 되지 못한다. 신뢰가 있어야 근거가 된다."""

    def setUp(self):
        self.터 = tempfile.mkdtemp()
        # 시험은 tests/ 에 있고 그래프는 저장소 뿌리에 있다
        본 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "graphs", "npc_대장장이.kg")
        self.길 = {}
        for 누구 in ("갑", "을", "병"):
            self.길[누구] = os.path.join(self.터, 누구 + ".kg")
            shutil.copy(본, self.길[누구])
        self.w = World(겪음지도={"help": ("내놓음", "고칠물건있음")}, 소문신뢰=20)
        for 누구 in ("갑", "을", "병"):
            self.w.add(NPC(누구, 누구, graph_path=self.길[누구], location="광장"))
        self.w.add(NPC("톰", "톰"))
        self.w.add(NPC("제리", "제리"))
        # 갑만 본다
        self.w._record(Event(1, "톰", "help", "제리", None, None, {}),
                       self.w.npcs["갑"])
        self.마디 = "겪음_톰_help_제리"

    def tearDown(self):
        shutil.rmtree(self.터, ignore_errors=True)

    def test_본것과_들은것이_출처로_갈린다(self):
        self.w.전하다("갑", "을")
        self.assertEqual(self.w.npcs["갑"].아는것()[self.마디]["출처"], "본 것")
        self.assertEqual(self.w.npcs["을"].아는것()[self.마디]["출처"], "갑한테 들음")

    def test_안믿으면_노드만_오고_엣지는_안온다(self):
        import engine
        self.w.전하다("갑", "을")                    # 신뢰 0
        을 = engine.load(self.길["을"])
        self.assertIn(self.마디, 을["사례층"])        # 그 일이 있었다는 것은 안다
        self.assertNotIn(self.마디, 을["증거"])       # 근거로는 못 쓴다

    def test_믿으면_근거까지_온다(self):
        import engine
        self.w.npcs["병"].relation_to("갑").change(trust=40)
        사건 = self.w.전하다("갑", "병")
        self.assertTrue(사건.effects["근거로받음"])
        병 = engine.load(self.길["병"])
        self.assertIn(self.마디, 병["증거"])

    def test_거짓말은_막지_않고_출처에_적는다(self):
        """세계는 거짓을 검열하지 않는다. 누구한테 들었는지만 남긴다."""
        self.w.npcs["병"].relation_to("을").change(trust=50)
        없는일 = "겪음_톰_threaten_제리"
        사건 = self.w.전하다("을", "병", 없는일, 말=["톰이 제리를 위협했다"])
        self.assertTrue(사건.effects["지어냄"])
        self.assertEqual(self.w.npcs["병"].아는것()[없는일]["출처"], "을한테 들음")
        # 믿는 사이여도 지어낸 것에는 근거가 안 붙는다
        self.assertFalse(사건.effects["근거로받음"])

    def test_이미_본_것은_들어도_출처가_안_바뀐다(self):
        self.w.전하다("갑", "을")
        self.w.npcs["을"].relation_to("갑").change(trust=50)
        self.w.전하다("갑", "을")
        self.assertEqual(self.w.npcs["을"].아는것()[self.마디]["출처"], "갑한테 들음")
        # 갑 본인은 남이 말해줘도 여전히 '본 것'
        self.w.전하다("을", "갑")
        self.assertEqual(self.w.npcs["갑"].아는것()[self.마디]["출처"], "본 것")

    def test_모르는_것은_전할_수_없다(self):
        self.assertIsNone(self.w.전하다("을", "병"))
