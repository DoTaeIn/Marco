# -*- coding: utf-8 -*-
"""라우터 순위가 아니라 근거가 그래프를 고른다."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import engine


class VerdictOrderTest(unittest.TestCase):
    def test_a_grounded_verdict_outranks_an_ungrounded_one(self):
        self.assertGreater(engine._verdict_rank("인정"), engine._verdict_rank("목표주장"))
        self.assertGreater(engine._verdict_rank("목표주장"), engine._verdict_rank("근거없음"))
        self.assertGreater(engine._verdict_rank("근거없음"), engine._verdict_rank("B2"))

    def test_an_unknown_verdict_sits_below_every_declared_one(self):
        """모르는 판정을 근거로 세지 않는다. B2 는 '상관없다' 라는 정보라 그보다 위다."""
        self.assertEqual(engine._verdict_rank("듣도보도못한판정"), 0)
        for verdict in engine._VERDICT_ORDER:
            self.assertGreater(engine._verdict_rank(verdict), 0, verdict)


class StrongerCandidateTest(unittest.TestCase):
    """라우터가 1등으로 준 것보다 더 확실히 답하는 후보가 있으면 그쪽을 쓴다."""

    def _session(self, verdict, line):
        class Fake:
            def __init__(self): self.verdict = verdict
            def reply(self, _q): return line
        return Fake()

    def test_a_later_candidate_with_a_stronger_verdict_wins(self):
        cand = [("graphs/a.kg", 0.80), ("graphs/b.kg", 0.78)]
        made = {"graphs/b.kg": self._session("인정", "b 가 답함")}
        with patch.object(engine, "load_graph", side_effect=lambda n: n), \
             patch.object(engine, "Session", side_effect=lambda g: made[g]):
            got = engine._stronger_candidate("물음", cand, "graphs/a.kg", "목표주장")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "graphs/b.kg")
        self.assertEqual(got[2], "b 가 답함")

    def test_a_weaker_candidate_never_displaces_the_router_pick(self):
        cand = [("graphs/a.kg", 0.80), ("graphs/b.kg", 0.78)]
        made = {"graphs/b.kg": self._session("목표주장", "b")}
        with patch.object(engine, "load_graph", side_effect=lambda n: n), \
             patch.object(engine, "Session", side_effect=lambda g: made[g]):
            self.assertIsNone(engine._stronger_candidate("물음", cand, "graphs/a.kg", "인정"))

    def test_a_candidate_without_evidence_is_not_considered(self):
        """근거가 안 선 그래프는 순위가 높아도 답을 가져가지 못한다."""
        cand = [("graphs/a.kg", 0.80), ("graphs/b.kg", 0.79)]
        made = {"graphs/b.kg": self._session("근거없음", "b")}
        with patch.object(engine, "load_graph", side_effect=lambda n: n), \
             patch.object(engine, "Session", side_effect=lambda g: made[g]):
            self.assertIsNone(engine._stronger_candidate("물음", cand, "graphs/a.kg", "목표주장"))

    def test_candidates_under_the_routing_threshold_are_not_opened(self):
        """문턱 아래 후보까지 열면 밖 물음이 어딘가에 걸린다."""
        cand = [("graphs/a.kg", 0.80), ("graphs/b.kg", engine.route_thresh - 0.01)]
        opened = []
        def spy(name):
            opened.append(name)
            return name
        with patch.object(engine, "load_graph", side_effect=spy), \
             patch.object(engine, "Session", side_effect=AssertionError("열면 안 된다")):
            self.assertIsNone(engine._stronger_candidate("물음", cand, "graphs/a.kg", "인정"))
        self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()
