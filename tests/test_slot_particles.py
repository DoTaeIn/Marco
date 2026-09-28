# -*- coding: utf-8 -*-
"""한 자리를 채우는 조사는 글자가 아니라 무리다.

예문마다 조사를 박아 두면 조사 하나가 바뀔 때마다 예문을 또 써야 한다.
`구슬은 18개 있다` 와 `단추는 18개 있다` 는 조사만 다른 같은 틀이었다.
"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from language_components import (decode_language_pack, load_reasoning_language,
                                 _validate_slot_particles)
from relational_semantics import RelationalParser
from marco.reasoning.context import ReasoningContext
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default

KG = "graphs/graph_일상추론.kg"


def reads(parser, text):
    got = parser.parse(text, partial=True)
    return bool(got and (got["facts"] or got["query"]))


class DeclarationTest(unittest.TestCase):
    def test_both_language_paths_expose_the_same_declaration(self):
        """한 길에만 실리면 그 길에서만 조용히 없는 기능이 된다."""
        import json
        raw = json.loads((ROOT / "styles/한국어.json").read_text(encoding="utf-8"))
        packed = decode_language_pack(raw, str(ROOT / "styles/한국어.json"))["slot_particles"]
        self.assertEqual(packed, load_reasoning_language()["slot_particles"])
        self.assertIn({"은", "는", "이", "가"}, [set(group) for group in packed])

    def test_a_language_without_the_section_simply_has_none(self):
        self.assertEqual(load_reasoning_language("english")["slot_particles"], [])

    def test_one_particle_may_not_sit_in_two_groups(self):
        """두 무리에 있으면 어느 자리인지 정해지지 않는다."""
        with self.assertRaises(ValueError):
            _validate_slot_particles([["은", "는"], ["는", "이"]])
        with self.assertRaises(ValueError):
            _validate_slot_particles([["은"]])


class ReadingTest(unittest.TestCase):
    def setUp(self):
        self.parser = RelationalParser()

    def test_the_subject_particle_is_a_slot_not_a_letter(self):
        for item in ("구슬", "단추", "사과", "돌"):
            for particle in ("은", "는", "이", "가"):
                text = "%s%s 18개 있다" % (item, particle)
                self.assertTrue(reads(self.parser, text), text)

    def test_a_group_is_never_crossed(self):
        """'을/를' 을 '이/가' 와 묶으면 한 일과 당한 일이 뒤집힌다."""
        moved = self.parser.parse("하루가 연필을 책상으로 옮겼다", partial=True)
        self.assertEqual(moved["facts"][0]["triple"], ["연필", "location", "책상"])
        # 목적격 자리에 주격 조사를 넣은 말은 그 틀로 읽히지 않는다.
        self.assertFalse(reads(self.parser, "하루가 연필이 책상으로 옮겼다"))

    def test_a_particle_letter_that_is_not_a_particle_stays_a_letter(self):
        """`이다` 의 `이` 는 잡음씨다. 조사로 읽으면 이름이 잘못 잘린다."""
        self.assertEqual(self.parser.parse("하루는 도린이다", partial=True)["facts"][0]["triple"],
                         ["하루", "isa", "도린"])
        learned = self.parser.learn({"text": "하루의 키는 모래를 넘지 않는다",
                                     "slots": {"a": "하루", "b": "모래"},
                                     "meaning": {"triple": ["$a", "taller", "$b"], "polarity": False}})
        self.assertTrue(learned)

    def test_a_group_yields_one_template_per_particle_not_one_alternation(self):
        """무리를 정규식 하나로 합치면 첫 일치 하나만 남아 자름이 굳는다.

        `작은 지도는 큰 서랍에 있었다` 는 자름이 둘이다. 둘 다 내주고 어느
        쪽이 옳은지는 개체 증거가 정한다.
        """
        example = {"text": "연필은 상자에 있었다", "slots": {"item": "연필", "place": "상자"},
                   "meaning": {"triple": ["$item", "location", "$place"]}}
        patterns, _ = RelationalParser.compile(example, None, self.parser.slot_particles)
        self.assertEqual(len(patterns), 8)        # 조사 넷 × 짧게 잡기/길게 잡기
        for text, item in (("작은 지도는 큰 서랍에 있었다", "작은 지도"),   # 꾸밈말 은, 조사 는
                           ("작은 공책은 큰 서랍에 있었다", "작은 공책")):  # 둘 다 은
            cut = [p.fullmatch(text).groupdict() for p in patterns if p.fullmatch(text)]
            self.assertIn({"item": item, "place": "큰 서랍"}, cut)
            self.assertEqual(len(self.parser._clause_meanings(text)), 2)

    def test_the_question_decides_which_cut_was_meant(self):
        got = self.parser.parse("작은 지도는 큰 서랍에 있었다. 지금 작은 지도는 어디에 있어?")
        self.assertEqual(got["facts"][0]["triple"], ["작은 지도", "location", "큰 서랍"])
        # 같은 문장을 주격 조사로 써도 같은 자름에 이른다.
        got = self.parser.parse("작은 지도가 큰 서랍에 있었다. 지금 작은 지도는 어디에 있어?")
        self.assertEqual(got["facts"][0]["triple"], ["작은 지도", "location", "큰 서랍"])


class ThroughTheAppTest(unittest.TestCase):
    def test_the_same_count_survives_either_subject_particle(self):
        for particle in ("은", "이"):
            context = ReasoningContext()
            context.turn("구슬%s 18개 있다." % particle, KG)
            context.turn("구슬 3개를 꺼냈다.", KG)
            self.assertEqual(context.turn("지금 구슬은 몇 개야?", KG)["answer"], "15개입니다.")

    def test_two_objects_with_different_particles_stay_apart(self):
        context = ReasoningContext()
        context.turn("공책은 서랍에 있었다.", KG)
        context.turn("지도가 가방에 있었다.", KG)
        context.turn("서우가 공책을 창고로 옮겼다.", KG)
        self.assertEqual(context.turn("지금 공책은 어디에 있어?", KG)["answer"], "창고에 있습니다.")
        self.assertEqual(context.turn("지금 지도는 어디에 있어?", KG)["answer"], "가방에 있습니다.")


if __name__ == "__main__":
    unittest.main()


class UnreadEventTest(unittest.TestCase):
    """못 읽은 사건 뒤에 과거 상태를 현재처럼 확정하지 않는다."""

    def hold(self, middle):
        context = ReasoningContext()
        context.turn("구슬은 18개 있다.", KG)
        context.turn(middle, KG)
        return context.turn("지금 구슬은 몇 개야?", KG)

    def test_an_event_we_could_not_read_blocks_the_stale_value(self):
        for middle in ("구슬 3개를 더 넣었다.", "구슬 3개를 뺐다.", "구슬 3개를 주었다."):
            got = self.hold(middle)
            self.assertEqual(got["status"], "unresolved", middle)
            self.assertIn(middle.rstrip("."), got["answer"])

    def test_it_blocks_only_what_the_unread_words_name(self):
        self.assertEqual(self.hold("단추 이야기는 재밌다.")["answer"], "18개입니다.")

    def test_a_question_is_not_an_event(self):
        """묻는 말은 아무 상태도 안 바꾼다. 못 읽었어도 막지 않는다."""
        self.assertEqual(self.hold("만약 구슬을 전부 없애면 어떻게 될까?")["answer"], "18개입니다.")

    def test_a_readable_event_is_unaffected(self):
        self.assertEqual(self.hold("구슬 3개를 꺼냈다.")["answer"], "15개입니다.")

    def test_a_new_observation_that_pins_the_value_releases_the_block(self):
        """목록을 손으로 지우는 건 해소가 아니다. 새 관찰로 실제로 풀려야 한다."""
        context = ReasoningContext()
        context.turn("구슬은 18개 있다.", KG)
        context.turn("구슬 3개를 더 넣었다.", KG)
        self.assertEqual(context.turn("지금 구슬은 몇 개야?", KG)["status"], "unresolved")
        context.turn("구슬은 21개 있다.", KG)
        self.assertEqual(context.turn("지금 구슬은 몇 개야?", KG)["answer"], "21개입니다.")
        # 기록은 남는다. 지워서 푸는 게 아니라 **나중에 못 박힌 값**이 이긴다.
        self.assertEqual([x["text"] for x in context.unread], ["구슬 3개를 더 넣었다."])

    def test_an_event_with_no_subject_still_blocks_a_number_question(self):
        """이름을 안 불렀다고 없던 일이 아니다. 이건 과잉 보류가 아니라 틀린 단정을 막는 것이다."""
        got = self.hold("3개를 더 넣었다.")
        self.assertEqual(got["status"], "unresolved")

    def test_an_event_and_a_question_in_one_message_are_told_apart(self):
        """메시지가 물음표로 끝난다고 앞의 사건까지 물음이 아니다."""
        context = ReasoningContext()
        context.turn("구슬은 18개 있다.", KG)
        # 앞 사건은 선언된 규칙에서 편집 하나(`더` 건너뛰기) 밖이라, 이 턴은 그
        # 부분을 짚어 보류한다 — KG 로 조용히 넘기지 않는다. 중요한 건 그다음이다 —
        # 앞의 사건이 기록에 남아야 한다.
        held = context.turn("구슬 3개를 더 넣었다. 지금 구슬은 몇 개야?", KG)
        self.assertEqual(held["status"], "unresolved")
        self.assertIn("'더' 건너뛰기", held["answer"])
        self.assertEqual([x["text"] for x in context.unread], ["구슬 3개를 더 넣었다."])
        self.assertEqual(context.turn("지금 구슬은 몇 개야?", KG)["status"], "unresolved")

    def test_an_old_snapshot_without_the_field_still_loads(self):
        context = ReasoningContext()
        context.restore({"schema": "reasoning-context-v2", "observations": ["구슬은 18개 있다."],
                         "corrections": []})
        self.assertEqual(context.unread, [])
        context.turn("구슬 3개를 뺐다.", KG)
        self.assertEqual([x["text"] for x in context.snapshot()["unread"]], ["구슬 3개를 뺐다."])


class ReleaseConditionTest(unittest.TestCase):
    """미해석은 **나중에 같은 대상의 같은 속성을 못 박은 관찰**로만 풀린다."""

    def after(self, *middle):
        context = ReasoningContext()
        context.turn("구슬은 18개 있다.", KG)
        context.turn("구슬 3개를 더 넣었다.", KG)
        for text in middle:
            context.turn(text, KG)
        return context.turn("지금 구슬은 몇 개야?", KG)

    def test_an_observation_about_another_thing_does_not_release(self):
        self.assertEqual(self.after("단추는 5개 있다.")["status"], "unresolved")

    def test_another_delta_does_not_pin_the_total(self):
        """증감은 값을 흔드는 것이지 못 박는 것이 아니다. 17개라고 단정하면 안 된다."""
        got = self.after("구슬 1개를 꺼냈다.")
        self.assertEqual(got["status"], "unresolved")
        self.assertNotIn("17", got["answer"])

    def test_only_a_later_absolute_observation_of_the_same_thing_releases(self):
        self.assertEqual(self.after("구슬은 21개 있다.")["answer"], "21개입니다.")

    def test_an_earlier_observation_never_releases_a_later_gap(self):
        self.assertEqual(self.after()["status"], "unresolved")

    def test_a_korean_numeral_event_blocks_just_like_a_digit_one(self):
        """`세 개를 더 넣었다` 도 수를 담은 사건이다. 아라비아 숫자만 보면 놓친다."""
        context = ReasoningContext()
        context.turn("구슬은 18개 있다.", KG)
        context.turn("세 개를 더 넣었다.", KG)
        self.assertEqual(context.turn("지금 구슬은 몇 개야?", KG)["status"], "unresolved")

    def test_a_readable_korean_numeral_event_is_not_blocked(self):
        """읽을 수 있는 사건까지 막으면 그건 과잉 보류다."""
        context = ReasoningContext()
        context.turn("구슬은 18개 있다.", KG)
        context.turn("다섯 개를 꺼냈다.", KG)
        self.assertEqual(context.turn("지금 구슬은 몇 개야?", KG)["answer"], "13개입니다.")
