# -*- coding: utf-8 -*-
"""자연어 질문이 자가학습 주제와 overlay 수명으로 이어지는지 검사한다."""
import tempfile
import unittest
from pathlib import Path

import kgpack
import web_learn
from goal_runtime import GoalRuntime
from views.kgpack_ui import AppState
from unittest.mock import patch


class LearningQuestionFlowTests(unittest.TestCase):
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
        with patch("web_learn._read_dialect", return_value=style):
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
            with patch("web_learn.save_verified_knowledge", return_value=[{"주제": "멀미"}]) as learn:
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
