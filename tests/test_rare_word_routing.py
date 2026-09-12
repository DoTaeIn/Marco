# -*- coding: utf-8 -*-
"""몇 그래프에만 나오는 낱말은 그 자체로 센 증거다."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import engine


def index(lines_by_graph):
    return {"공통층": dict(lines_by_graph)}


class RareWordTableTest(unittest.TestCase):
    def test_only_words_in_few_graphs_are_kept(self):
        ix = index({"a.kg": ["하구 생태는 강과 바다가 만나는 곳이다"],
                    "b.kg": ["생태는 생물과 환경의 관계다"],
                    "c.kg": ["생태 발자국을 줄이는 방법"]})
        rare = engine._rare_words(ix)
        self.assertIn("하구", rare)                 # 한 그래프에만
        self.assertEqual(rare["하구"], frozenset({"a.kg"}))
        # 조사를 떼고 세므로 '생태는' 과 '생태' 가 한 낱말이다. 셋에 나오니 빠진다.
        self.assertNotIn("생태", rare)

    def test_the_table_is_built_once_and_kept_on_the_index(self):
        ix = index({"a.kg": ["하구 생태"]})
        first = engine._rare_words(ix)
        self.assertIs(engine._rare_words(ix), first)
        self.assertIs(ix["드문말"], first)

    def test_a_one_letter_word_is_not_counted(self):
        """한 글자는 너무 많은 말에 들어 있어 증거가 못 된다."""
        ix = index({"a.kg": ["물 이 그 저"]})
        self.assertEqual([w for w in engine._rare_words(ix) if len(w) < 2], [])


class RareWordRankingTest(unittest.TestCase):
    """드문 낱말은 순위에만 들어간다. 돌려주는 점수와 문턱은 안 건드린다."""

    def test_the_bonus_is_capped(self):
        self.assertEqual(engine._RARE_CAP, 3)
        self.assertGreater(engine._RARE_WEIGHT, 0)
        self.assertEqual(engine._RARE_MAX_GRAPHS, 2)

    def test_a_rare_word_lifts_the_graph_that_holds_it(self):
        ix = index({"바른.kg": ["하구 생태는 강과 바다가 만나는 곳이다",
                              "기수역에는 민물과 바닷물이 섞인다"],
                    "틀린.kg": ["생태를 설명해 줘", "설명해 주는 일"]})
        rare = engine._rare_words(ix)
        self.assertIn("하구", rare)
        # 드문 낱말을 가진 쪽만 가산을 받는다
        held = [rare[w] for w in ("하구",)]
        self.assertEqual(sum("바른.kg" in h for h in held), 1)
        self.assertEqual(sum("틀린.kg" in h for h in held), 0)


if __name__ == "__main__":
    unittest.main()


class ParticleFoldingTest(unittest.TestCase):
    """같은 낱말의 여러 꼴을 한 낱말로 센다."""

    def test_a_trailing_particle_is_folded_away(self):
        import hangul
        self.assertEqual(hangul.drop_particle("생태는"), "생태")
        self.assertEqual(hangul.drop_particle("기수역에서"), "기수역")

    def test_a_short_stem_is_left_alone(self):
        """'사과' 의 '과' 를 떼면 '사' 가 된다. 한 글자는 조사와 못 가른다."""
        import hangul
        self.assertEqual(hangul.drop_particle("사과"), "사과")
        self.assertEqual(hangul.drop_particle("강과"), "강과")

    def test_both_forms_reach_the_table(self):
        got = engine._bare_words("하구 생태는 강과")
        self.assertIn("생태", got)
        self.assertIn("생태는", got)
        self.assertIn("강과", got)      # 안 떼진 것은 그대로
