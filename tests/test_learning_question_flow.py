# -*- coding: utf-8 -*-
"""자연어 질문이 자가학습 주제와 overlay 수명으로 이어지는지 검사한다."""
import tempfile
import unittest
from pathlib import Path

import marco.storage.kgpack as kgpack
import marco.knowledge.ingest.web as web_learn
from marco.storage.conversations import ConversationStore
from goal_runtime import GoalRuntime
from views.kgpack_ui import AppState
from unittest.mock import patch
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


class LearningQuestionFlowTests(unittest.TestCase):
    def test_research_sends_only_the_needed_topic_and_reports_evidence_status(self):
        question = "내가 어제 멀미가 심했는데 어떤 약을 먹으면 좋을까?"
        hits = [{"url": "https://a.example/motion", "도메인": "a.example"},
                {"url": "https://b.example/motion", "도메인": "b.example"}]
        with patch("marco.knowledge.ingest.web.question_word", return_value="멀미"), \
             patch("marco.knowledge.ingest.web.search", return_value=hits) as search, \
             patch("marco.knowledge.ingest.web.read_source", side_effect=[
                 ("A", ["멀미는 이동 중 생길 수 있는 증상이다."]),
                 ("B", ["멀미가 계속되면 의료 전문가와 상담할 수 있다."]),
             ]):
            research = GoalRuntime(".").research(question)
        search.assert_called_once_with("멀미", count=5)
        self.assertEqual(research["query"], question)
        self.assertEqual(research["search_terms"], "멀미")
        self.assertTrue(research["verified"])
        self.assertEqual(research["diagnosis"], "external_evidence_found")
        self.assertEqual(research["need"], {"kind": "external_fact", "topic": "멀미", "resolved": True})

    def test_research_keeps_missing_external_evidence_distinct(self):
        with patch("marco.knowledge.ingest.web.question_word", return_value="없는주제"), \
             patch("marco.knowledge.ingest.web.search", return_value=[]):
            research = GoalRuntime(".").research("없는주제를 알려줘")
        self.assertFalse(research["verified"])
        self.assertEqual(research["diagnosis"], "external_evidence_missing")
        self.assertFalse(research["need"]["resolved"])

    def test_two_related_sources_without_the_requested_role_are_not_a_solution(self):
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with patch("marco.knowledge.ingest.web.search", return_value=hits), \
             patch("marco.knowledge.ingest.web.read_source", side_effect=[
                 ("A", ["광합성은 빛에너지를 이용하여 유기물을 합성하는 과정이다."]),
                 ("B", ["광합성은 식물의 중요한 생명 활동 중 하나이다."]),
             ]):
            research = GoalRuntime(".").research(question)
        self.assertFalse(research["verified"])
        self.assertEqual(research["diagnosis"], "external_evidence_incomplete")
        self.assertEqual({key: research["coverage"][key] for key in
                          ("required", "covered", "missing", "resolved")},
                         {"required": ["location"], "covered": [],
                          "missing": ["location"], "resolved": False})

    def test_two_sources_that_fill_the_requested_location_are_verified(self):
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with patch("marco.knowledge.ingest.web.search", return_value=hits), \
             patch("marco.knowledge.ingest.web.read_source", side_effect=[
                 ("A", ["광합성은 식물 세포의 엽록체에서 일어난다."]),
                 ("B", ["광합성은 엽록체 안에서 빛을 이용해 진행된다."]),
             ]):
            research = GoalRuntime(".").research(question)
        self.assertTrue(research["verified"])
        self.assertEqual(research["diagnosis"], "external_evidence_found")
        self.assertEqual(research["coverage"]["covered"], ["location"])

    def test_role_question_scans_past_the_intro_but_keeps_only_matching_sentences_as_answer_material(self):
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with patch("marco.knowledge.ingest.web.search", return_value=hits), \
             patch("marco.knowledge.ingest.web.read_source", side_effect=[
                 ("A", ["광합성은 생명 활동이다.", "광합성은 빛을 쓴다.", "광합성은 중요하다.",
                        "광합성은 엽록체에서 일어난다."]),
                 ("B", ["광합성은 식물이 한다.", "광합성은 에너지를 만든다.", "광합성은 널리 알려졌다.",
                        "광합성은 엽록체 안에서 진행된다."]),
             ]):
            research = GoalRuntime(".").research(question)
        self.assertTrue(research["verified"])
        self.assertEqual(research["sources"][0]["sentences"], ["광합성은 엽록체에서 일어난다."])
        self.assertEqual(research["sources"][1]["sentences"], ["광합성은 엽록체 안에서 진행된다."])

    def test_location_marker_on_a_different_action_is_not_an_occurrence_answer(self):
        """`학교에서 배운다`는 광합성이 일어나는 장소라는 근거가 아니다."""
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with patch("marco.knowledge.ingest.web.search", return_value=hits), \
             patch("marco.knowledge.ingest.web.read_source", side_effect=[
                 ("A", ["광합성은 학교에서 배운다."]),
                 ("B", ["광합성은 교실에서 공부한다."]),
             ]):
            research = GoalRuntime(".").research(question)
        self.assertFalse(research["verified"])
        self.assertEqual(research["diagnosis"], "external_evidence_incomplete")
        self.assertEqual(research["coverage"]["supports"]["location"], [])

    def test_location_and_occurrence_from_different_clauses_are_not_joined(self):
        """한 문장이어도 광합성의 위치와 경기의 발생을 합치지 않는다."""
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with patch("marco.knowledge.ingest.web.search", return_value=hits), \
             patch("marco.knowledge.ingest.web.read_source", side_effect=[
                 ("A", ["광합성은 학교에서 배우며 운동장에서 경기가 일어난다."]),
                 ("B", ["광합성은 교실에서 배우며 마당에서 행사가 진행된다."]),
             ]):
            research = GoalRuntime(".").research(question)
        self.assertFalse(research["verified"])
        self.assertEqual(research["diagnosis"], "external_evidence_incomplete")
        self.assertEqual(research["coverage"]["supports"]["location"], [])

    def test_topic_mentioned_as_part_of_a_compound_subject_is_not_its_own_location_evidence(self):
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with patch("marco.knowledge.ingest.web.search", return_value=hits), \
             patch("marco.knowledge.ingest.web.read_source", side_effect=[
                 ("A", ["광합성과 세포 호흡은 서로 다른 세포 구획에서 일어난다."]),
                 ("B", ["광합성과 세포 호흡은 서로 다른 세포 구획에서 진행된다."]),
             ]):
            research = GoalRuntime(".").research(question)
        self.assertFalse(research["verified"])
        self.assertEqual(research["coverage"]["supports"]["location"], [])

    def test_conflicting_relation_values_are_not_promoted_to_one_answer(self):
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with patch("marco.knowledge.ingest.web.search", return_value=hits), \
             patch("marco.knowledge.ingest.web.read_source", side_effect=[
                 ("A", ["광합성은 엽록체에서 일어난다."]),
                 ("B", ["광합성은 미토콘드리아에서 일어난다."]),
             ]):
            research = GoalRuntime(".").research(question)
        self.assertFalse(research["verified"])
        self.assertEqual(research["diagnosis"], "external_evidence_incomplete")
        self.assertEqual({row["domain"] for row in research["coverage"]["conflicts"]["location"]},
                         {"a.example", "b.example"})

    def test_topic_and_role_must_be_in_the_same_sentence_of_each_source(self):
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with patch("marco.knowledge.ingest.web.search", return_value=hits), \
             patch("marco.knowledge.ingest.web.read_source", side_effect=[
                 ("A", ["광합성은 식물의 중요한 생명 활동이다.", "엽록체 안에서 빛을 이용한다."]),
                 ("B", ["광합성은 엽록체에서 일어난다."]),
             ]):
            research = GoalRuntime(".").research(question)
        self.assertFalse(research["verified"])
        self.assertEqual(research["diagnosis"], "external_evidence_incomplete")
        self.assertEqual(research["coverage"]["missing"], ["location"])
        self.assertEqual(research["coverage"]["supports"]["location"][0]["domain"], "b.example")

    def test_negated_role_evidence_is_a_conflict_not_a_verified_location(self):
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with patch("marco.knowledge.ingest.web.search", return_value=hits), \
             patch("marco.knowledge.ingest.web.read_source", side_effect=[
                 ("A", ["광합성은 엽록체에서 일어난다."]),
                 ("B", ["광합성은 엽록체에서 일어나지 않는다."]),
             ]):
            research = GoalRuntime(".").research(question)
        self.assertFalse(research["verified"])
        self.assertEqual(research["diagnosis"], "external_evidence_incomplete")
        assert research["coverage"]["conflicts"]["location"] == [{
            "domain": "b.example", "url": "https://b.example/photosynthesis",
            "sentences": ["광합성은 엽록체에서 일어나지 않는다."]}]

    def test_actual_ui_does_not_offer_learning_when_sources_miss_the_requested_role(self):
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pack = root / "sample.kgpack"
            kgpack.write_pack(pack, [Path("graphs/graph_자가학습.kg")] + kgpack.model_files(Path(".")), root=Path("."))
            app = AppState(pack, overlay_root=root / "overlay")
            with patch("marco.knowledge.ingest.web.search", return_value=hits), \
                 patch("marco.knowledge.ingest.web.read_source", side_effect=[
                     ("A", ["광합성은 빛에너지를 이용하여 유기물을 합성하는 과정이다."]),
                     ("B", ["광합성은 식물의 중요한 생명 활동 중 하나이다."]),
                 ]):
                result = app.turn(question, "location_evidence")
        self.assertEqual(result["phase"], "research")
        self.assertEqual(result["research"]["diagnosis"], "external_evidence_incomplete")
        self.assertFalse(result["plan"]["actions"])

    def test_actual_ui_does_not_offer_learning_for_conflicting_relation_values(self):
        question = "광합성은 어디에서 일어나?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pack = root / "sample.kgpack"
            kgpack.write_pack(pack, [Path("graphs/graph_자가학습.kg")] + kgpack.model_files(Path(".")), root=Path("."))
            app = AppState(pack, overlay_root=root / "overlay")
            with patch("marco.knowledge.ingest.web.search", return_value=hits), \
                 patch("marco.knowledge.ingest.web.read_source", side_effect=[
                     ("A", ["광합성은 엽록체에서 일어난다."]),
                     ("B", ["광합성은 미토콘드리아에서 일어난다."]),
                 ]):
                result = app.turn(question, "conflicting_location")
        self.assertEqual(result["phase"], "research")
        self.assertEqual(result["research"]["diagnosis"], "external_evidence_incomplete")
        self.assertFalse(result["plan"]["actions"])

    def test_natural_question_extracts_its_content_topic(self):
        graph = web_learn.load("graphs/graph_자가학습.kg")
        topic, aliases = web_learn.extract_topic(
            graph, "멀미가 좀 심하게 나는데 어떤 약을 먹으면 좋을까?"
        )
        self.assertEqual(topic, "멀미")
        self.assertIn("멀미", aliases)

    def test_colloquial_recommendation_request_extracts_content_topic(self):
        graph = web_learn.load("graphs/graph_자가학습.kg")
        topic, aliases = web_learn.extract_topic(graph, "멀미가 심한데 약 추천해 줘")
        self.assertEqual(topic, "멀미")
        self.assertIn("멀미", aliases)

    def test_plain_statement_is_not_mistaken_for_a_learning_question(self):
        graph = web_learn.load("graphs/graph_자가학습.kg")
        self.assertEqual(web_learn.extract_topic(graph, "오늘 멀미가 심하다"), (None, []))

    def test_question_detection_follows_language_style_data(self):
        # 코드에 '요청끝'이라는 표현이 없어도, 언어 데이터가 선언하면 학습
        # 질문으로 인식한다. 반대로 선언 밖의 문장은 평서문으로 남는다.
        style = {"학습질문종결": ["요청끝"], "학습주제제외": [], "질문틀": [], "떼는조사": []}
        with patch("marco.knowledge.ingest.web._read_dialect", return_value=style):
            self.assertEqual(web_learn.extract_topic({}, "사과 요청끝")[0], "사과")
            self.assertEqual(web_learn.extract_topic({}, "사과 요청아님"), (None, []))

    def test_learning_plan_freezes_the_extracted_topic(self):
        question = "멀미가 좀 심하게 나는데 어떤 약을 먹으면 좋을까?"
        research = {"query": question, "sources": [{"domain": "a"}, {"domain": "b"}], "verified": True}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "graph_자가학습.kg"
            target.write_text(Path("graphs/graph_자가학습.kg").read_text(encoding="utf-8"), encoding="utf-8")
            runtime = GoalRuntime(root)
            plan = runtime.plan_learning(question, research, "risk", target)
            self.assertEqual(plan["actions"][0]["payload"]["topic"], "멀미")
            runtime.remember("session_123", plan)
            with patch("marco.knowledge.ingest.web.save_verified_knowledge", return_value=[{"주제": "멀미"}]) as learn:
                outcome = runtime.approve("session_123", plan["plan_id"], plan["plan_hash"], [plan["actions"][0]["id"]])
            self.assertEqual(outcome["executed"][0]["status"], "done")
            self.assertEqual(learn.call_args.args[1], "멀미")

    def test_approved_sources_are_saved_without_a_second_search(self):
        question = "멀미가 좀 심하게 나는데 어떤 약을 먹으면 좋을까?"
        sources = [
            {"url": "https://a.example/motion", "domain": "a.example", "title": "A", "sentences": ["멀미는 이동 중 생길 수 있는 불편한 증상이다."]},
            {"url": "https://b.example/motion", "domain": "b.example", "title": "B", "sentences": ["멀미가 심하면 안전한 곳에서 쉬는 것이 도움이 될 수 있다."]},
        ]
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "graph_자가학습.kg"
            target.write_text(Path("graphs/graph_자가학습.kg").read_text(encoding="utf-8"), encoding="utf-8")
            saved = web_learn.save_verified_knowledge(target, "멀미", question, sources)
            records = web_learn.read_collected(web_learn.collect_path(target))
            learned_graph = web_learn.load(target)
            known, answer = web_learn.ask(learned_graph, question)
        self.assertEqual(len(saved), 2)
        self.assertEqual({record["URL"] for record in records}, {source["url"] for source in sources})
        self.assertTrue(known)
        self.assertTrue(any(sentence in answer for source in sources for sentence in source["sentences"]))

    def test_actual_ui_turn_plans_and_approves_the_reported_motion_sickness_question(self):
        """입력 분류부터 승인 저장까지의 실제 앱 경로를 네트워크 없이 재현한다."""
        question = "멀미가 좀 심하게 나는데 어떤 약을 먹으면 좋을까?"
        sources = [
            {"url": "https://a.example/motion", "domain": "a.example", "title": "A",
             "sentences": ["멀미가 심할 때는 안전한 곳에서 잠시 쉬는 것이 도움이 될 수 있다."]},
            {"url": "https://b.example/motion", "domain": "b.example", "title": "B",
             "sentences": ["멀미 증상이 계속되면 의료 전문가와 상담하는 것이 도움이 될 수 있다."]},
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pack = root / "sample.kgpack"
            kgpack.write_pack(pack, [Path("graphs/graph_자가학습.kg")] + kgpack.model_files(Path(".")), root=Path("."))
            app = AppState(pack, overlay_root=root / "overlay")
            research = {"query": question, "sources": sources, "verified": True}
            with patch.object(app.goals, "research", return_value=research):
                result = app.turn(question, "session_12345")
            plan = result["plan"]
            self.assertEqual(result["phase"], "research")
            self.assertEqual(plan["actions"][0]["payload"]["topic"], "멀미")
            action = plan["actions"][0]
            approved = app.approve_goal("session_12345", plan["plan_id"], plan["plan_hash"], [action["id"]])
            self.assertEqual(approved["executed"][0]["status"], "done")
            records = web_learn.read_collected(web_learn.collect_path(plan["graph_path"]))
            self.assertEqual({record["URL"] for record in records}, {source["url"] for source in sources})

    def test_one_new_topic_survives_state_dialogue_research_approval_and_pack_restart(self):
        """상태 대화가 뒤의 조사 요청을 오염시키지 않고, 승인 근거가 새 팩까지 간다."""
        question = "광합성은 어떻게 에너지를 만들지?"
        hits = [{"url": "https://a.example/photosynthesis", "도메인": "a.example"},
                {"url": "https://b.example/photosynthesis", "도메인": "b.example"}]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_pack, exported = root / "source.kgpack", root / "exported.kgpack"
            kgpack.write_pack(source_pack, [Path("graphs/graph_자가학습.kg")] + kgpack.model_files(Path(".")), root=Path("."))
            app = AppState(source_pack, overlay_root=root / "overlay")
            # 앞선 수량 대화는 실제 상태 계산으로 끝나고, 아래 조사 주제와 섞이지 않는다.
            state = app.turn("사과는 5개 있다. 사과 1개를 꺼냈다. 지금 사과는 몇 개야?", "new_topic_flow")
            with patch("marco.knowledge.ingest.web.search", return_value=hits), \
                 patch("marco.knowledge.ingest.web.read_source", side_effect=[
                     ("A", ["광합성은 빛 에너지를 화학 에너지로 전환한다."]),
                     ("B", ["광합성은 식물이 이산화탄소로 유기물을 만드는 과정이다."]),
                 ]):
                researched = app.turn(question, "new_topic_flow")
            action = researched["plan"]["actions"][0]
            approved = app.approve_goal("new_topic_flow", researched["plan"]["plan_id"],
                                        researched["plan"]["plan_hash"], [action["id"]])
            app.export_pack(exported)
            fresh = AppState(exported, overlay_root=root / "fresh-overlay")
            with patch.object(fresh.goals, "research", side_effect=AssertionError("exported evidence must answer locally")):
                reused = fresh.turn("광합성 요약해줘", "fresh_topic_flow")

        self.assertEqual(state["answer"]["answer"], "4개입니다.")
        self.assertEqual(researched["phase"], "research")
        self.assertEqual(researched["research"]["diagnosis"], "external_evidence_found")
        self.assertEqual(approved["executed"][0]["status"], "done")
        self.assertEqual(reused["phase"], "answer")
        self.assertEqual({row["source"] for row in reused["answer"]["composition"]["selected"]},
                         {"https://a.example/photosynthesis", "https://b.example/photosynthesis"})

    def test_definition_correction_research_and_both_restart_paths_stay_separate(self):
        """교정 대화는 복원하고, 승인한 외부 근거만 새 팩으로 옮긴다."""
        question = "광합성은 어떻게 에너지를 만들지?"
        sources = [
            {"url": "https://a.example/photosynthesis", "domain": "a.example", "title": "A",
             "sentences": ["광합성은 빛 에너지를 화학 에너지로 전환한다."]},
            {"url": "https://b.example/photosynthesis", "domain": "b.example", "title": "B",
             "sentences": ["광합성은 식물이 이산화탄소로 유기물을 만드는 과정이다."]},
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_pack, exported = root / "source.kgpack", root / "exported.kgpack"
            kgpack.write_pack(source_pack, [Path("graphs/graph_일상추론.kg"),
                                             Path("graphs/graph_자가학습.kg")]
                              + kgpack.model_files(Path(".")), root=Path("."))
            app = AppState(source_pack, overlay_root=root / "overlay")
            app.conversations = ConversationStore(root / "conversations.json")
            chat = app.conversations.create_chat()["id"]
            for text in (
                "공책은 서랍에 있었다.",
                "보관하다는 물건을 가방으로 옮기는 것이다.",
                "하린이 공책을 보관했다.",
                "정정: 보관하다는 물건을 가방으로 옮기는 것이다. => 보관하다는 물건을 상자로 옮기는 것이다.",
            ):
                app.turn(text, "combined_flow", conversation_id=chat)
            corrected = app.turn("지금 공책은 어디에 있어?", "combined_flow", conversation_id=chat)
            research = {"query": question, "sources": sources, "verified": True,
                        "diagnosis": "external_evidence_found"}
            with patch.object(app.goals, "research", return_value=research):
                researched = app.turn(question, "combined_flow", conversation_id=chat)
            action = researched["plan"]["actions"][0]
            approved = app.approve_goal("combined_flow", researched["plan"]["plan_id"],
                                        researched["plan"]["plan_hash"], [action["id"]],
                                        conversation_id=chat)
            app.export_pack(exported)

            restarted = AppState(source_pack, overlay_root=root / "overlay")
            restarted.conversations = ConversationStore(root / "conversations.json")
            restored = restarted.turn("지금 공책은 어디에 있어?", "combined_restart", conversation_id=chat)
            fresh = AppState(exported, overlay_root=root / "fresh-overlay")
            with patch.object(fresh.goals, "research", side_effect=AssertionError("exported evidence must answer locally")):
                reused = fresh.turn("광합성 요약해줘", "fresh_topic_flow")

        self.assertEqual(corrected["answer"]["answer"], "상자에 있습니다.")
        self.assertEqual(researched["phase"], "research")
        self.assertEqual(approved["executed"][0]["status"], "done")
        self.assertEqual(restored["answer"]["answer"], "상자에 있습니다.")
        self.assertEqual(reused["phase"], "answer")
        self.assertEqual({row["source"] for row in reused["answer"]["composition"]["selected"]},
                         {"https://a.example/photosynthesis", "https://b.example/photosynthesis"})

    def test_actual_ui_turn_answers_a_verified_linear_equation_without_research(self):
        """계산 가능한 식은 웹 근거나 학습 승인으로 내려가지 않는다."""
        question = "3x + 1 = 7이래. x는 얼마야?"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pack = root / "sample.kgpack"
            kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
            app = AppState(pack, overlay_root=root / "overlay")
            with patch.object(app.goals, "research") as research:
                result = app.turn(question, "session_equation")

        self.assertEqual(result["phase"], "answer")
        self.assertEqual(result["answer"]["answer"], "2입니다.")
        self.assertEqual(result["answer"]["trace"]["mode"], "situation")
        research.assert_not_called()

    def test_approved_learning_does_not_turn_a_truncated_source_excerpt_into_fact(self):
        question = "멀미가 심한데 어떻게 해야 해?"
        sources = [
            {"url": "https://a.example/motion", "domain": "a.example", "title": "A",
             "sentences": ["멀미가 심할 때는 안전한 곳에서 잠시 쉬는 것이 도움이 될 수 있다."]},
            {"url": "https://b.example/motion", "domain": "b.example", "title": "B",
             "sentences": ["멀미가 심할 때 물을 조금씩 마시면"]},
        ]
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "graph_자가학습.kg"
            target.write_text(Path("graphs/graph_자가학습.kg").read_text(encoding="utf-8"), encoding="utf-8")
            saved = web_learn.save_verified_knowledge(target, "멀미", question, sources)
            records = web_learn.read_collected(web_learn.collect_path(target))

        # 서로 다른 두 출처가 모두 완결 문장을 제공하지 않아 새 주제를 만들지 않는다.
        self.assertEqual(saved, [])
        self.assertEqual(records, [])

    def test_learning_plan_does_not_offer_action_for_a_statement(self):
        question = "오늘 멀미가 심하다"
        research = {"query": question, "sources": [{"domain": "a"}, {"domain": "b"}], "verified": True}
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "graph_자가학습.kg"
            target.write_text(Path("graphs/graph_자가학습.kg").read_text(encoding="utf-8"), encoding="utf-8")
            plan = GoalRuntime(temp).plan_learning(question, research, "risk", target)
        self.assertFalse(plan["actions"])
        self.assertTrue(plan["unsupported"])

    def test_materializing_recreates_a_missing_approval_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pack = root / "sample.kgpack"
            kgpack.write_pack(pack, [Path("graphs/graph_자가학습.kg")] + kgpack.model_files(Path(".")), root=Path("."))
            app = AppState(pack, overlay_root=root / "overlay")
            path = app._materialize("graphs/graph_자가학습.kg")
            path.unlink()
            self.assertEqual(app._materialize("graphs/graph_자가학습.kg"), path)
            self.assertEqual(path.read_bytes(), app.data["graphs/graph_자가학습.kg"])

    def test_materializing_graph_also_materializes_its_includes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            graphs = root / "graphs"
            graphs.mkdir()
            base = graphs / "base.kg"
            main = graphs / "main.kg"
            base.write_text("역할: 바탕\n목표: 바탕끝\n[개념]\n바탕끝: \"바탕\"\n", encoding="utf-8")
            main.write_text(
                "포함: base.kg\n역할: 본체\n목표: 끝\n전진관계: 이어짐\n"
                "근거관계: 이어짐\n[개념]\n끝: \"끝\"\n"
                "[대사]\nB2: 범위 밖입니다.\nB2_강등: 범위 밖입니다.\nA: 확인합니다.\n"
                "근거없음: 근거가 없습니다.\n인정: 맞습니다.\n인정_반격: 다만 예외가 있습니다.\n"
                "C: 근거가 부족합니다.\nB1: 근거를 알려 주세요.\n"
                "[논증]\n바탕끝 -이어짐-> 끝\n",
                encoding="utf-8",
            )
            pack = root / "sample.kgpack"
            kgpack.write_pack(pack, [base, main], root=root)
            app = AppState(pack, overlay_root=root / "overlay")
            path = app._materialize("graphs/main.kg")
            self.assertTrue((path.parent / "base.kg").is_file())
            # 엔진은 포함 파일을 선택한 그래프 기준의 상대 경로로 다시 연다.
            # 파일 존재만 확인하면 이전의 실제 크래시를 놓치므로, UI 활성화까지
            # 통과시켜 공통층이 합쳐졌는지 확인한다.
            app._activate("graphs/main.kg")
            self.assertIn("바탕끝", app.graph["공통층"])


if __name__ == "__main__":
    unittest.main()
