# -*- coding: utf-8 -*-
import unittest

from npc import NPC, World, _demo


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
