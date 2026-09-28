# -*- coding: utf-8 -*-
"""틀을 손으로 적지 않고 사례에서 꺼내는가.

낱말이 공짜인 것은 이미 봤다. 여기서 보는 것은 **짜임**이다. 뜻풀이의 몸통은
보통 문장이므로, 앞자리를 지운 사례에 맞춰 읽고 빈자리는 사건이 같은 조사로
채운다. 그래서 새 짜임마다 틀을 더하지 않는다.
"""
import pathlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from marco.language.frames import induce, read_event, split_particle
from relational_semantics import RelationalParser
from marco.reasoning.context import ReasoningContext
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default

KG = "graphs/graph_일상추론.kg"


def 대화(turns):
    context = ReasoningContext()
    result = None
    for text in turns:
        result = context.turn(text, KG)
    return result


def 답(turns):
    return (대화(turns) or {}).get("answer") or ""


class BodyTest(unittest.TestCase):
    """몸통은 보통 문장이다. 아는 문장꼴이면 뜻이 따라온다."""

    def setUp(self):
        self.parser = RelationalParser()

    def test_a_body_written_as_a_sentence_we_know_carries_its_meaning(self):
        got = induce(self.parser, "물건을 상자로 옮기는")
        self.assertEqual(got["뜻"]["triple"], ["$item", "location", "$place"])
        self.assertEqual(got["값"], {"item": "물건", "place": "상자"})

    def test_the_slot_the_body_leaves_out_becomes_the_place_the_event_fills(self):
        """빠진 자리가 곧 역할이다. 역할 이름을 따로 선언하지 않는다."""
        self.assertEqual(list(induce(self.parser, "물건을 상자로 옮기는")["빈자리"]), ["actor"])

    def test_a_quantity_body_is_induced_the_same_way(self):
        """자리 옮김만 되는 것이 아니다. 수량도 같은 길로 나온다."""
        for body, predicate in (("구슬 3개를 넣는", "count_add"),
                                ("구슬 두 개를 꺼내는", "count_remove")):
            got = induce(self.parser, body)
            self.assertEqual(got["뜻"]["triple"][1], predicate, body)

    def test_a_two_sided_body_yields_two_facts(self):
        """주고받기는 한 문장이 둘을 말한다. 주는 쪽이 줄고 받는 쪽이 는다."""
        got = induce(self.parser, "상대에게 구슬 2개를 주는")
        self.assertEqual([row[1] for row in got["뜻"]["triples"]],
                         ["count_remove", "count_add"])

    def test_a_body_whose_verb_has_no_sentence_example_is_refused(self):
        """못 읽는 까닭은 틀이 없어서가 아니라 **그 움직임을 모르기 때문**이다.

        `가져오다` 는 어느 사례에도 없다. 틀 탓으로 돌리면 고칠 자리를 놓친다.
        """
        self.assertIsNone(induce(self.parser, "상대에게서 구슬 2개를 가져오는"))

    def test_word_order_does_not_decide_whether_we_can_read_it(self):
        """한국어는 조사가 자리를 짚는다. 덩이 순서는 뜻을 안 바꾼다.

        반례마다 예문을 더하지 않는다 — 덩이를 다시 늘어놓아 한 번에 푼다.
        """
        for body in ("상대에게 구슬 2개를 주는", "구슬 2개를 상대에게 주는"):
            got = induce(self.parser, body)
            self.assertEqual(got["값"]["taker"], "상대", body)
            self.assertEqual(got["값"]["n"], "2", body)
        for body in ("물건을 상자로 옮기는", "상자로 물건을 옮기는"):
            got = induce(self.parser, body)
            self.assertEqual((got["값"]["item"], got["값"]["place"]), ("물건", "상자"), body)

    def test_a_name_that_ends_in_a_particle_letter_is_still_a_name(self):
        """`사과` 의 `과` 는 조사가 아니라 이름의 끝 글자다.

        조사는 앞말에 붙고 뒤는 띄운다. 띄어쓰기를 안 넘었으면 안 떼어 본다.
        """
        for item in ("사과", "모과", "송과"):
            got = induce(self.parser, "상대에게 %s 2개를 주는" % item)
            self.assertIsNotNone(got, item)
            self.assertEqual(got["값"]["item"], item, item)

    def test_a_cut_that_swallows_a_marked_word_into_a_name_is_refused(self):
        """`하루가 연필` 을 한 이름으로 삼키면 자름이 틀린 것이다."""
        got = induce(self.parser, "하루가 연필을 상자로 옮기는")
        self.assertEqual(got["값"]["item"], "연필")


class ManyFactsTest(unittest.TestCase):
    """한 문장이 사실 하나라는 법은 없다."""

    def test_one_sentence_moves_both_sides(self):
        기준 = ["민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
              "민수가 지연에게 구슬 2개를 줬다."]
        self.assertIn("6개", 답(기준 + ["지금 민수 구슬은 몇 개야?"]))
        self.assertIn("5개", 답(기준 + ["지금 지연 구슬은 몇 개야?"]))

    def test_a_name_written_in_pieces_becomes_one_name(self):
        facts = RelationalParser().parse("하루가 모래에게 구슬 3개를 줬다", partial=True)["facts"]
        self.assertEqual([f["triple"] for f in facts],
                         [["하루 구슬", "count_remove", "3"],
                          ["모래 구슬", "count_add", "3"]])

    def test_a_correction_may_still_state_only_one_fact(self):
        """고쳐 주는 말은 사실 하나다. 사용자가 두 값을 한꺼번에 흔들지 않는다."""
        parser = RelationalParser()
        with self.assertRaises(ValueError):
            parser.learn({"text": "하루가 모래에게 구슬 4개를 건넸다",
                          "slots": {"giver": "하루", "taker": "모래",
                                    "item": "구슬", "n": "4"},
                          "meaning": {"triples": [[["$giver", "$item"], "count_remove", "$n"]]}})


class MovementTest(unittest.TestCase):
    """막는 것은 틀이 아니라 **움직임**이다. 움직임 하나가 짜임 여럿을 연다."""

    def test_learning_one_ordinary_sentence_opens_compositions_that_use_it(self):
        parser = RelationalParser()
        self.assertIsNone(induce(parser, "구슬 4개를 더는"))
        parser.learn({"text": "구슬 4개를 덜었다", "slots": {"item": "구슬", "n": "4"},
                      "inflection": {"stem": "덜", "kind": "regular",
                                     "tense": "past", "ending": "plain"},
                      "meaning": {"triple": ["$item", "count_remove", "$n"]}})
        # 뜻풀이 틀을 더한 것이 아니다. 보통 문장 하나를 더했을 뿐이다.
        got = induce(parser, "구슬 두 개를 더는")
        self.assertEqual(got["뜻"]["triple"][1], "count_remove")
        self.assertEqual(got["값"]["n"], "2")

    def test_a_new_example_never_leaves_a_stale_induced_frame_behind(self):
        parser = RelationalParser()
        ReasoningContext._rule(parser, {"verb": "치우", "몸통": "물건을 상자로 옮기는"})
        self.assertTrue(parser.induced_frames)
        parser.learn({"text": "구슬 4개를 덜었다", "slots": {"item": "구슬", "n": "4"},
                      "inflection": {"stem": "덜", "kind": "regular",
                                     "tense": "past", "ending": "plain"},
                      "meaning": {"triple": ["$item", "count_remove", "$n"]}})
        self.assertFalse(parser.induced_frames)


class EventTest(unittest.TestCase):
    """사건은 조사로 자리를 짚는다. 모르는 낱말은 넘겨짚지 않는다."""

    def setUp(self):
        self.parser = RelationalParser()
        self.parts, self.groups = self.parser.case_particles, self.parser.slot_particles
        self.negation = self.parser.negation

    def test_a_longer_particle_is_read_before_a_shorter_one_it_contains(self):
        self.assertEqual(split_particle("지연에게서", self.parts, self.groups), ("지연", "에게서"))
        self.assertEqual(split_particle("지연에게", self.parts, self.groups), ("지연", "에게"))

    def test_particles_that_share_a_slot_share_one_name(self):
        """`로` 와 `으로` 는 한 자리다. 몸통이 `상자로` 라도 사건의 `학교로` 와 만난다."""
        self.assertEqual(split_particle("상자로", self.parts, self.groups)[1],
                         split_particle("책상으로", self.parts, self.groups)[1])

    def test_the_shape_is_read_without_knowing_the_word(self):
        """뜻을 몰라도 꼴은 안다. 그래야 **무엇을** 모르는지 짚어 줄 수 있다."""
        got = read_event("민수가 지연에게 베풀었다", self.parts, self.groups, self.negation)
        self.assertEqual(got["verb"], "베풀었다")
        self.assertEqual(got["자리"], {"은": "민수", "에게": "지연"})

    def test_what_did_not_happen_is_read_the_same_way(self):
        """부정도 낱말마다 틀을 안 적는다. 잇는 말과 보조 어간 한 줄이면 된다."""
        for tail in ("않았다", "않았어요", "않는다"):
            got = read_event("민수는 지연에게 베풀지 %s" % tail,
                             self.parts, self.groups, self.negation)
            self.assertEqual((got["verb"], got["polarity"]), ("베풀", False), tail)

    def test_a_chunk_may_span_several_words(self):
        """`사과 상자를` 은 한 자리다. 어디서 끊을지는 뜻풀이가 고른다."""
        got = read_event("하루가 사과 상자를 치웠다", self.parts, self.groups, self.negation)
        self.assertIn({"은": "하루", "을": "사과 상자"}, got["자리후보"])
        self.assertIn({"은": "하루", "와": "사", "을": "상자"}, got["자리후보"])

    def test_a_word_with_no_particle_anywhere_is_not_an_event(self):
        self.assertIsNone(read_event("치웠다", self.parts, self.groups, self.negation))
        self.assertIsNotNone(read_event("하루가 담았다", self.parts, self.groups, self.negation))

    def test_the_same_slot_twice_is_not_read(self):
        """한 자리를 두 번 짚는 자름은 내주지 않는다."""
        got = read_event("하루가 민수가 치웠다", self.parts, self.groups, self.negation)
        for 후보 in got["자리후보"]:
            self.assertEqual(len(후보), len(set(후보)))
            self.assertNotEqual(sorted(후보.values()), ["민수", "하루"])


class ConventionTest(unittest.TestCase):
    """`자리말` 은 **지금 지원하는 초기 규약**이다. 반례마다 늘리는 칸이 아니다."""

    초기규약 = ["누구", "대상", "무엇", "물건", "물체", "사람", "상대", "어떤것", "그것",
             "나", "내", "자신", "자기"]

    def test_the_placeholder_list_is_a_stated_convention(self):
        parser = RelationalParser()
        self.assertEqual(sorted(parser.placeholders), sorted(self.초기규약))

    def test_words_for_one_and_the_same_placeholder_share_a_slot(self):
        """`나` 와 `내` 는 한 가리킴이다. 묶어 적으면 두 절에서 같은 자리가 된다."""
        parser = RelationalParser()
        self.assertEqual(parser.placeholders["나"], parser.placeholders["내"])
        self.assertNotEqual(parser.placeholders["나"], parser.placeholders["상대"])

    def test_a_word_outside_the_convention_is_read_as_a_value(self):
        """규약 밖 낱말은 값으로 읽고, 어긋나면 고르지 않고 묻는다."""
        got = induce(RelationalParser(), "연장을 상자로 옮기는")
        self.assertEqual(got["채울자리"], {})
        self.assertEqual(got["값"]["item"], "연장")


class LongNameTest(unittest.TestCase):
    """이름이 여러 낱말일 수 있다. 어디서 끊을지는 뜻풀이가 고른다."""

    def test_a_definition_may_name_a_place_in_several_words(self):
        self.assertIn("사과 상자", 답(["치우다는 물건을 사과 상자로 옮기는 것이다.",
                                   "연필은 책상에 있었다.", "하루가 연필을 치웠다.",
                                   "지금 연필은 어디에 있어?"]))

    def test_an_event_may_name_a_thing_in_several_words(self):
        """`사과 상자를` 을 [사][상자] 로 끊으면 성한 이름이 사라진다."""
        self.assertIn("상자에 있습니다", 답(["치우다는 물건을 상자로 옮기는 것이다.",
                                       "사과 상자는 책상에 있었다.",
                                       "하루가 사과 상자를 치웠다.",
                                       "지금 사과 상자는 어디에 있어?"]))

    def test_an_argument_the_definition_has_no_place_for_stops_it(self):
        """`단추 4개를 담았다` 는 구슬 이야기가 아니다. 아는 이름이면 안 넘긴다."""
        answer = 답(["담다는 구슬 3개를 넣는 것이다.", "단추는 5개 있다.",
                    "하루가 단추 4개를 담았다.", "지금 단추는 몇 개야?"])
        self.assertNotIn("개입니다", answer)

    def test_a_doer_the_definition_never_mentions_is_fine(self):
        """누가 했는지는 뜻풀이가 안 써도 그만이다. 여기까지 막으면 과교정이다."""
        self.assertIn("8개", 답(["담다는 구슬 3개를 넣는 것이다.", "구슬은 5개 있다.",
                               "하루가 담았다.", "지금 구슬은 몇 개야?"]))


class ConstantTest(unittest.TestCase):
    """빈 자리를 채우는 것과 뜻을 바꾸는 것은 다른 일이다.

        물건을 상자로 옮기는   ->  [$item, location, $place]
                                   ^^^^^ 임자 = 이 동사가 다루는 것
                                              ^^^^^^ 값 = 뜻풀이가 정한 것
    """

    치 = "치우다는 물건을 상자로 옮기는 것이다."
    있 = "연필은 책상에 있었다."

    def test_the_basis_is_the_word_not_the_shape(self):
        """`물건` 과 `상자` 는 문장에서 똑같이 생겼다. 갈리는 것은 낱말의 성질이다."""
        parser = RelationalParser()
        got = induce(parser, "물건을 상자로 옮기는")
        self.assertEqual(sorted(got["채울자리"]), ["item"])
        self.assertEqual(got["값"]["place"], "상자")
        # 뜻풀이가 적은 값이 임자 자리에 있어도 자리말이 아니면 값이다.
        준 = induce(parser, "상대에게 구슬 2개를 주는")
        self.assertEqual(sorted(준["채울자리"]), ["taker"])
        self.assertEqual(준["값"]["item"], "구슬")

    def test_a_slot_the_definition_talks_about_is_filled_by_the_event(self):
        self.assertIn("상자", 답([self.치, self.있, "하루가 연필을 치웠다.",
                                "지금 연필은 어디에 있어?"]))

    def test_a_placeholder_the_event_never_fills_is_asked_about(self):
        """`하루가 치웠다` 는 무엇을 치웠는지 안 말했다. `물건` 을 그대로 쓰면 안 된다."""
        answer = 답([self.치, self.있, "하루가 치웠다.", "지금 연필은 어디에 있어?"])
        self.assertNotIn("상자에 있습니다", answer)

    def test_a_value_the_definition_fixed_is_not_quietly_replaced(self):
        answer = 답([self.치, self.있, "하루가 연필을 학교로 치웠다."])
        self.assertIn("상자", answer)
        self.assertIn("학교", answer)          # 둘을 나란히 보이고 고르지 않는다

    def test_a_conflicting_event_never_lets_a_value_stand(self):
        answer = 답([self.치, self.있, "하루가 연필을 학교로 치웠다.",
                    "지금 연필은 어디에 있어?"])
        self.assertNotIn("에 있습니다", answer)

    def test_saying_the_same_value_is_not_a_conflict(self):
        self.assertIn("상자", 답([self.치, self.있, "하루가 연필을 상자로 치웠다.",
                                "지금 연필은 어디에 있어?"]))

    def test_a_quantity_the_definition_fixed_stays_fixed(self):
        """`구슬 2개` 의 `2` 도 `구슬` 도 뜻풀이가 정한 값이다."""
        self.assertIn("6개", 답(["베풀다는 상대에게 구슬 2개를 주는 것이다.",
                               "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
                               "민수가 지연에게 베풀었다.", "지금 민수 구슬은 몇 개야?"]))


class QuestionTest(unittest.TestCase):
    """묻는 것은 하는 것이 아니다."""

    뜻 = "베풀다는 상대에게 구슬 2개를 주는 것이다."
    기준 = ["민수 구슬은 8개 있다.", "지연 구슬은 3개 있다."]

    def test_asking_whether_it_happened_does_not_make_it_happen(self):
        for asked in ("민수가 지연에게 베풉니까?", "민수가 지연에게 베풉니까",
                      "민수가 지연에게 베풀었습니까", "민수가 지연에게 베풀었나요?"):
            answer = 답([self.뜻] + self.기준 + [asked, "지금 민수 구슬은 몇 개야?"])
            self.assertIn("8개", answer, asked)

    def test_a_statement_style_that_shares_an_ending_is_still_an_event(self):
        """`베풀었어요` 는 묻기도 하고 말하기도 한다. 묻기 전용 꼬리라야 물음이다."""
        for said in ("민수가 지연에게 베풀었어요.", "민수가 지연에게 베풀었다."):
            self.assertIn("6개", 답([self.뜻] + self.기준 + [said, "지금 민수 구슬은 몇 개야?"]), said)

    def test_a_question_is_not_kept_as_something_we_failed_to_read(self):
        """묻는 말은 못 읽은 사건이 아니다. 뒤 물음을 막으면 안 된다."""
        answer = 답([self.뜻] + self.기준 + ["민수가 지연에게 베풉니까", "지금 지연 구슬은 몇 개야?"])
        self.assertIn("3개", answer)


class UnfilledRoleTest(unittest.TestCase):
    """채우지 못한 자리와 아무 일도 없었던 것은 다르다."""

    뜻 = "베풀다는 상대에게 구슬 2개를 주는 것이다."
    기준 = ["민수 구슬은 8개 있다.", "지연 구슬은 3개 있다."]

    def test_a_missing_role_is_said_out_loud_not_swallowed(self):
        """되묻는 말은 사람 말이어야 짧은 답을 부른다."""
        answer = 답([self.뜻] + self.기준 + ["지연에게 베풀었다."])
        self.assertIn("지연에게 베풀었다", answer)
        self.assertIn("누가 했나요", answer)


class ShortReplyTest(unittest.TestCase):
    """되물었으면 **짧은 답**으로 이어져야 한다."""

    뜻 = "베풀다는 상대에게 구슬 2개를 주는 것이다."
    기준 = ["민수 구슬은 8개 있다.", "지연 구슬은 3개 있다."]

    def test_a_bare_name_continues_the_event_we_asked_about(self):
        for reply in ("민수야", "민수", "민수가"):
            self.assertIn("6개", 답([self.뜻] + self.기준 + ["지연에게 베풀었다.", reply,
                                                        "지금 민수 구슬은 몇 개야?"]), reply)

    def test_the_held_question_is_answered_as_soon_as_the_slot_is_filled(self):
        self.assertIn("6개", 답([self.뜻] + self.기준 + ["지연에게 베풀었다.",
                                                    "지금 민수 구슬은 몇 개야?", "민수야"]))

    def test_a_name_this_conversation_never_heard_is_not_guessed_at(self):
        answer = 답([self.뜻] + self.기준 + ["지연에게 베풀었다.", "하루야",
                                        "지금 민수 구슬은 몇 개야?"])
        self.assertNotIn("개입니다", answer)

    def test_an_answer_that_turns_the_meaning_around_is_not_taken_as_the_name(self):
        """이름이 들어 있는지만 보면 `민수 아냐` 도 민수로 읽는다.

        덧붙은 말이 뜻을 뒤집는데 그것을 안 본 것이다. 반례 문구를 막는 목록을
        두는 것이 아니라 **받아들일 꼴**을 정해 둔다 — 이름 한 낱말에 아는 꼬리.
        """
        for reply in ("민수 아냐", "민수 아니야", "민수?", "민수 말고 가람이야"):
            answer = 답([self.뜻] + self.기준 + ["지연에게 베풀었다.", reply,
                                            "지금 민수 구슬은 몇 개야?"])
            self.assertNotIn("6개입니다", answer, reply)

    def test_a_name_that_merely_contains_a_known_one_is_a_different_name(self):
        answer = 답([self.뜻] + self.기준 + ["지연에게 베풀었다.", "김민수야",
                                        "지금 민수 구슬은 몇 개야?"])
        self.assertNotIn("6개입니다", answer)

    def test_the_forms_we_do_accept_still_work(self):
        for reply in ("민수야", "민수", "민수가", "민수입니다", "민수요"):
            self.assertIn("6개", 답([self.뜻] + self.기준 + ["지연에게 베풀었다.", reply,
                                                       "지금 민수 구슬은 몇 개야?"]), reply)

    def test_a_held_question_survives_a_restart(self):
        """갈무리에서 빠지면 복원 뒤 같은 것을 또 묻게 만든다."""
        context = ReasoningContext()
        for text in [self.뜻] + self.기준 + ["지연에게 베풀었다.", "지금 민수 구슬은 몇 개야?"]:
            context.turn(text, KG)
        restored = ReasoningContext()
        restored.restore(context.snapshot())
        self.assertIn("6개", restored.turn("민수야", KG)["answer"])

    def test_two_mends_in_one_message_each_go_to_their_own_event(self):
        answer = 답([self.뜻] + self.기준 + ["가람 구슬은 5개 있다.",
                                        "지연에게 베풀었다. 가람에게 베풀었다.",
                                        "민수가 지연에게 베풀었다. 민수가 가람에게 베풀었다.",
                                        "지금 민수 구슬은 몇 개야?"])
        self.assertIn("4개", answer)

    def test_two_open_events_are_confirmed_rather_than_guessed(self):
        """임의로 첫 사건에 붙이지 않는다."""
        answer = 답([self.뜻] + self.기준 + ["가람 구슬은 5개 있다.",
                                        "지연에게 베풀었다.", "가람에게 베풀었다.", "민수야"])
        self.assertIn("어느", answer)
        self.assertIn("지연", answer)
        self.assertIn("가람", answer)

    def test_a_missing_role_never_lets_the_old_value_stand(self):
        """이것을 안 하면 해석 실패가 "변화 없음" 으로 둔갑한다."""
        for asked in ("지금 민수 구슬은 몇 개야?", "지금 지연 구슬은 몇 개야?"):
            answer = 답([self.뜻] + self.기준 + ["지연에게 베풀었다.", asked])
            self.assertNotIn("개입니다", answer, asked)

    def test_filling_the_slot_afterwards_carries_on(self):
        self.assertIn("6개", 답([self.뜻] + self.기준 + ["지연에게 베풀었다.",
                                                   "민수가 지연에게 베풀었다.",
                                                   "지금 민수 구슬은 몇 개야?"]))

    def test_the_completed_event_keeps_the_meaning_it_had_when_it_happened(self):
        """보완은 **원래 자리에** 놓는다. 나중 차례로 옮기면 뒤에 바뀐 뜻으로 풀린다.

            뜻(2) / 사건(자리 빔) / 뜻(4) / 자리 채움 / 물음  ->  6개.  4가 아니다
        """
        answer = 답([self.뜻] + self.기준 + ["지연에게 베풀었다.",
                                        "베풀다는 상대에게 구슬 4개를 주는 것이다.",
                                        "민수가 지연에게 베풀었다.",
                                        "지금 민수 구슬은 몇 개야?"])
        self.assertIn("6개", answer)
        self.assertNotIn("4개", answer)

    def test_nothing_is_joined_unless_we_asked_for_it(self):
        """되묻지 않았으면 안 잇는다. 같은 동사에 자리가 겹친다는 것만으로는 모자라다."""
        from relational_semantics import RelationalParser
        context = ReasoningContext()
        for text in [self.뜻] + self.기준 + ["지연에게 베풀었다."]:
            context.turn(text, KG)
        self.assertTrue(context._live())
        context.asked = []                        # 되물은 기억을 지운다
        parser = RelationalParser()
        verbs = context._known_verbs(parser, context.observations)
        current = parser.parse("민수가 지연에게 베풀었다.", partial=True, events=True, verbs=verbs)
        self.assertIsNone(context._completion(parser, current, verbs, context._live()))

    def test_the_reply_says_which_event_it_went_into(self):
        result = 대화([self.뜻] + self.기준 + ["지연에게 베풀었다.", "민수가 지연에게 베풀었다."])
        self.assertIn("앞서 여쭌 자리", result["answer"])

    def test_a_completion_carrying_its_own_question_is_still_answered(self):
        self.assertIn("6개", 답([self.뜻] + self.기준 + ["지연에게 베풀었다.",
                                                   "민수가 지연에게 베풀었다. 지금 민수 구슬은 몇 개야?"]))

    def test_filling_in_replaces_the_event_not_the_whole_message(self):
        """메시지를 통째로 바꾸면 같이 있던 사실까지 지워진다."""
        answer = 답([self.뜻, "지연 구슬은 3개 있다.",
                    "민수 구슬은 8개 있다. 지연에게 베풀었다.",
                    "민수가 지연에게 베풀었다.", "지금 민수 구슬은 몇 개야?"])
        self.assertIn("6개", answer)

    def test_what_was_written_first_is_applied_first(self):
        """한 말 안에서도 적힌 차례를 지킨다. 사건이 처음 수량보다 앞서면 막힌다."""
        answer = 답([self.뜻, "지연 구슬은 3개 있다.",
                    "민수 구슬은 8개 있다. 민수가 지연에게 베풀었다.",
                    "지금 민수 구슬은 몇 개야?"])
        self.assertIn("6개", answer)

    def test_every_event_we_asked_about_is_remembered(self):
        """되물어 둔 것이 여럿이면 하나씩 채울 수 있어야 한다."""
        기준 = ["민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.", "가람 구슬은 5개 있다."]
        turns = [self.뜻] + 기준 + ["지연에게 베풀었다.", "민수에게 베풀었다.",
                                 "가람이 민수에게 베풀었다."]
        # 아직 하나가 남아 있으므로 확정하지 않는다.
        self.assertNotIn("개입니다", 답(turns + ["지금 민수 구슬은 몇 개야?"]))
        # 남은 하나까지 채우면 둘 다 제자리에서 풀린다. 8 - 2 + 2 = 8.
        self.assertIn("8개", 답(turns + ["민수가 지연에게 베풀었다.",
                                       "지금 민수 구슬은 몇 개야?"]))

    def test_a_different_event_does_not_count_as_filling_it_in(self):
        """채운 자리끼리 어긋나면 고쳐 말한 것이 아니라 딴 일이다."""
        answer = 답([self.뜻] + self.기준 + ["가람에게 베풀었다.",
                                        "민수가 지연에게 베풀었다.",
                                        "지금 민수 구슬은 몇 개야?"])
        self.assertNotIn("개입니다", answer)

    def test_a_value_the_event_could_not_touch_is_still_answered(self):
        answer = 답([self.뜻] + self.기준 + ["단추는 5개 있다.", "지연에게 베풀었다.",
                                        "지금 단추는 몇 개야?"])
        self.assertIn("5개", answer)


class ConversationTest(unittest.TestCase):
    """실제 대화에서 한 바퀴 도는가."""

    def test_a_composition_nobody_declared_is_answered(self):
        self.assertIn("상자", 답(["치우다는 물건을 상자로 옮기는 것이다.",
                                "연필은 책상에 있었다.",
                                "하루가 연필을 치웠어요.",
                                "지금 연필은 어디에 있어?"]))

    def test_the_same_path_works_for_a_different_composition(self):
        """한 문항에 맞춘 것이 아니다. 낱말도 자리도 바꿔 본다."""
        self.assertIn("서랍", 답(["숨기다는 물건을 서랍으로 옮기는 것이다.",
                                "구슬은 책상에 있었다.",
                                "민수가 구슬을 숨겼다.",
                                "지금 구슬은 어디에 있어?"]))

    def test_a_quantity_composition_runs_the_same_way(self):
        self.assertIn("8개", 답(["담다는 구슬 3개를 넣는 것이다.", "구슬은 5개 있다.",
                               "하루가 담았다.", "지금 구슬은 몇 개야?"]))

    def test_the_event_fills_the_slot_the_body_left_open(self):
        self.assertIn("상자", 답(["치우다는 물건을 상자로 옮기는 것이다.",
                                "연필은 책상에 있었다.",
                                "하루가 연필을 치웠다.",
                                "지금 연필은 어디에 있어?"]))

    def test_without_the_explanation_the_same_event_is_not_assumed(self):
        answer = 답(["연필은 책상에 있었다.", "하루가 연필을 치웠다.",
                    "지금 연필은 어디에 있어?"])
        self.assertNotIn("상자", answer)
        self.assertIn("치웠다", answer)          # 무엇을 못 읽었는지 짚어 준다

    def test_a_sentence_shaped_like_an_event_never_becomes_a_value(self):
        """꼴을 읽는 것은 뜻을 안다는 말이 아니다. 잡담은 값을 안 흔든다."""
        answer = 답(["날씨가 좋다.", "민수 구슬은 8개 있다.", "지금 민수 구슬은 몇 개야?"])
        self.assertIn("8개", answer)

    def test_a_word_used_as_an_event_is_named_even_before_it_is_explained(self):
        answer = 답(["민수 구슬은 8개 있다.", "민수가 지연에게 베풀었다."])
        self.assertIn("베풀었다", answer)

    def test_what_did_not_happen_changes_nothing_for_an_induced_word_too(self):
        """부정은 선언된 틀에만 있던 것이었다. 이제 유도된 말에도 선다."""
        self.assertIn("책상", 답(["치우다는 물건을 상자로 옮기는 것이다.",
                                "연필은 책상에 있었다.",
                                "하루가 연필을 치우지 않았다.",
                                "지금 연필은 어디에 있어?"]))

    def test_an_explanation_we_could_not_read_says_so_instead_of_blaming_the_word(self):
        """방금 설명한 사람에게 "그 말을 모른다" 고 하면 틀린 말이다."""
        answer = 답(["빼앗다는 상대에게서 구슬 2개를 가져오는 것이다."])
        self.assertIn("상대에게서 구슬 2개를 가져오는", answer)

    def test_no_definition_frame_is_declared_anywhere(self):
        """뜻풀이 틀은 이제 한 칸도 안 적혀 있다. 겉틀 하나가 전부다."""
        frames = [e for e in RelationalParser().data["examples"] if "define" in e["meaning"]]
        self.assertEqual(len(frames), 1)
        self.assertEqual(set(frames[0]["meaning"]["define"]), {"verb", "몸통"})

    def test_both_sides_of_a_giving_move_without_a_frame_for_it(self):
        turns = ["베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.",
                 "민수가 지연에게 베풀었다."]
        self.assertIn("6개", 답(turns + ["지금 민수 구슬은 몇 개야?"]))
        self.assertIn("5개", 답(turns + ["지금 지연 구슬은 몇 개야?"]))


if __name__ == "__main__":
    unittest.main()


class AskLedgerTest(unittest.TestCase):
    """되묻기는 **어느 사건의 어느 역할을 어떤 값으로** 로 적힌다. 원문은 안 고친다."""

    뜻 = "베풀다는 상대에게 구슬 2개를 주는 것이다."
    기준 = ["민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.", "가람 구슬은 5개 있다."]

    def test_the_same_shaped_event_can_be_filled_again_and_again(self):
        """앞서 푼 물음이 끼어들면 뒤엣것이 미해결로 남는다."""
        answer = 답([self.뜻] + self.기준 + ["지연에게 베풀었다.", "민수야",
                                        "지연에게 베풀었다.", "가람이야",
                                        "지금 지연 구슬은 몇 개야?"])
        self.assertIn("7개", answer)               # 3 + 2 + 2

    def test_an_answer_naming_a_different_role_is_confirmed_not_forced(self):
        """`민수에게` 는 받는이를 말한 것이지 누가 했는지를 말한 것이 아니다."""
        result = 대화([self.뜻] + self.기준 + ["지연에게 베풀었다.", "민수에게"])
        self.assertIn("여쭌 자리에 대한 답이 아닌", result["answer"])
        self.assertNotIn("6개", 답([self.뜻] + self.기준 + ["지연에게 베풀었다.", "민수에게",
                                                     "지금 민수 구슬은 몇 개야?"]))

    def test_an_unusable_answer_is_not_left_blocking_the_value(self):
        """되묻기에 대한 답과 상태를 바꾸는 사건은 다르다."""
        context = ReasoningContext()
        for text in [self.뜻] + self.기준 + ["지연에게 베풀었다.", "민수 아냐", "가람이야"]:
            context.turn(text, KG)
        self.assertEqual([x["text"] for x in context.unread], [])
        self.assertIn("8개", context.turn("지금 민수 구슬은 몇 개야?", KG)["answer"])
        self.assertIn("3개", context.turn("지금 가람 구슬은 몇 개야?", KG)["answer"])

    def test_the_original_wording_is_never_rewritten(self):
        context = ReasoningContext()
        for text in [self.뜻] + self.기준 + ["지연에게 베풀었다.", "민수야"]:
            context.turn(text, KG)
        self.assertIn("지연에게 베풀었다.", context.observations)
        self.assertEqual([f["역할"] for f in context.fills], ["은"])
        self.assertEqual([f["값"] for f in context.fills], ["민수"])

    def test_open_and_settled_asks_survive_a_restart(self):
        context = ReasoningContext()
        for text in [self.뜻] + self.기준 + ["지연에게 베풀었다.", "민수야",
                                         "가람에게 베풀었다."]:
            context.turn(text, KG)
        restored = ReasoningContext()
        restored.restore(context.snapshot())
        self.assertEqual(len(restored._live()), 1)          # 가람 쪽만 남았다
        self.assertEqual(len(restored.asked), 2)            # 푼 것도 기억한다
        restored.turn("민수야", KG)                          # 남은 물음에만 붙는다
        self.assertIn("4개", restored.turn("지금 민수 구슬은 몇 개야?", KG)["answer"])


class ConflictScopeTest(unittest.TestCase):
    """어긋난 값이 **어디까지** 미치는지는 우리가 고르지 않는다."""

    바탕 = ["치우다는 물건을 상자로 옮기는 것이다.", "연필은 책상에 있었다.",
          "지우개는 책상에 있었다."]
    어긋남 = "하루가 연필을 학교로 치웠다."
    뒤 = ["하루가 지우개를 치웠다.", "지금 지우개는 어디에 있어?"]

    def 물음(self, *대답):
        return 답(self.바탕 + [self.어긋남] + list(대답) + ["지금 연필은 어디에 있어?"])

    def test_this_time_only_leaves_the_definition_alone(self):
        self.assertIn("학교", self.물음("이번만"))
        self.assertIn("상자", 답(self.바탕 + [self.어긋남, "이번만"] + self.뒤))

    def test_from_now_on_changes_what_comes_after(self):
        self.assertIn("학교", self.물음("앞으로"))
        self.assertIn("학교", 답(self.바탕 + [self.어긋남, "앞으로"] + self.뒤))

    def test_a_correction_asks_what_is_being_corrected(self):
        result = 대화(self.바탕 + [self.어긋남, "정정"])
        self.assertIn("무엇을 정정", result["answer"])
        self.assertIn("학교", self.물음("정정", "설명"))
        self.assertIn("상자", 답(self.바탕 + [self.어긋남, "정정", "사건"] + self.뒤))

    def test_an_answer_outside_the_convention_asks_again(self):
        """넘겨짚어 과거를 통째로 바꾸지 않는다."""
        answer = self.물음("글쎄")
        self.assertNotIn("에 있습니다", answer)


class CompositionTest(unittest.TestCase):
    """설명이 **동작의 조합 자체**를 만든다. 맞교환 전용 규칙은 없다."""

    몸통 = "내가 상대에게 구슬 두 개를 주고, 상대가 나에게 단추 한 개를 주는"
    바탕 = ["서우 구슬은 10개 있다.", "서우 단추는 1개 있다.",
          "도아 구슬은 2개 있다.", "도아 단추는 5개 있다."]

    def 대화들(self, 몸통, 물음):
        return 답(["맞교환하다는 %s 것이다." % 몸통] + self.바탕
                 + ["서우가 도아에게 맞교환했다.", 물음])

    def test_two_transfers_are_linked_from_one_explanation(self):
        self.assertIn("8개", self.대화들(self.몸통, "지금 서우 구슬은 몇 개야?"))
        self.assertIn("4개", self.대화들(self.몸통, "지금 도아 구슬은 몇 개야?"))

    def test_the_second_transfer_runs_the_other_way(self):
        """뒷절에서 주는이와 받는이가 뒤집힌다. 따로 적지 않아도 나온다."""
        self.assertIn("2개", self.대화들(self.몸통, "지금 서우 단추는 몇 개야?"))
        self.assertIn("4개", self.대화들(self.몸통, "지금 도아 단추는 몇 개야?"))

    def test_it_applies_to_people_and_things_never_seen(self):
        """서우·도아·단추는 뜻풀이에도 예문에도 없다."""
        self.assertIn("8개", self.대화들(self.몸통, "지금 서우 구슬은 몇 개야?"))

    def test_changing_the_direction_changes_the_result(self):
        뒤집음 = "상대가 나에게 구슬 두 개를 주고, 내가 상대에게 단추 한 개를 주는"
        self.assertIn("12개", self.대화들(뒤집음, "지금 서우 구슬은 몇 개야?"))

    def test_changing_the_quantity_changes_the_result(self):
        바꿈 = "내가 상대에게 구슬 다섯 개를 주고, 상대가 나에게 단추 세 개를 주는"
        self.assertIn("5개", self.대화들(바꿈, "지금 서우 구슬은 몇 개야?"))
        self.assertIn("4개", self.대화들(바꿈, "지금 서우 단추는 몇 개야?"))

    def test_a_clause_ending_in_a_connective_is_read(self):
        """`-고` 로 끝나는 절도 되돌려 읽는다. 꼬리마다 따로 적지 않는다."""
        parser = RelationalParser()
        self.assertIsNotNone(induce(parser, "내가 상대에게 구슬 두 개를 주고"))

    def test_nothing_about_this_verb_is_declared_anywhere(self):
        """`맞교환` 전용 규칙을 더하면 실험 취지에서 벗어난다."""
        pack = pathlib.Path(ROOT / "styles/한국어.json").read_text(encoding="utf-8")
        self.assertNotIn("맞교환", pack)


class ReuseTest(unittest.TestCase):
    """대화에서 **배운 동작**이 다른 설명의 재료가 된다. 동사별 처리는 없다."""

    베풀 = "베풀다는 상대에게 구슬 2개를 주는 것이다."
    바탕 = ["서우 구슬은 10개 있다.", "서우 단추는 1개 있다.",
          "도아 구슬은 2개 있다.", "도아 단추는 5개 있다."]
    맞바꾸 = "맞바꾸다는 내가 상대에게 베풀고, 상대가 나에게 단추 한 개를 주는 것이다."

    def test_a_move_learned_here_can_be_material_for_another_explanation(self):
        turns = [self.베풀, self.맞바꾸] + self.바탕 + ["서우가 도아에게 맞바꿨다."]
        self.assertIn("8개", 답(turns + ["지금 서우 구슬은 몇 개야?"]))
        self.assertIn("4개", 답(turns + ["지금 도아 구슬은 몇 개야?"]))

    def test_the_roles_still_turn_around_in_the_second_clause(self):
        turns = [self.베풀, self.맞바꾸] + self.바탕 + ["서우가 도아에게 맞바꿨다."]
        self.assertIn("2개", 답(turns + ["지금 서우 단추는 몇 개야?"]))
        self.assertIn("4개", 답(turns + ["지금 도아 단추는 몇 개야?"]))

    def test_two_learned_moves_can_be_joined(self):
        turns = [self.베풀, "건네다는 상대에게 단추 1개를 주는 것이다.",
                 "주고받다는 내가 상대에게 베풀고, 상대가 나에게 건네는 것이다."]
        turns += self.바탕 + ["서우가 도아에게 주고받았다."]
        self.assertIn("8개", 답(turns + ["지금 서우 구슬은 몇 개야?"]))
        self.assertIn("2개", 답(turns + ["지금 서우 단추는 몇 개야?"]))

    def test_the_same_structure_carries_a_move_that_is_not_about_quantity(self):
        """구슬은 소재다. 자리 옮김에서도 같은 학습·조합 구조가 선다."""
        turns = ["치우다는 물건을 상자로 옮기는 것이다.",
                 "정리하다는 내가 물건을 치우고, 상자를 책상으로 옮기는 것이다.",
                 "연필은 서랍에 있었다.", "하루가 연필을 정리했다."]
        self.assertIn("상자", 답(turns + ["지금 연필은 어디에 있어?"]))
        self.assertIn("책상", 답(turns + ["지금 상자는 어디에 있어?"]))

    def test_a_later_redefinition_does_not_reach_back(self):
        """옛 사건은 **그때의 뜻**으로 남는다. 재료로 쓴 동작도 마찬가지다."""
        answer = 답([self.베풀, self.맞바꾸] + self.바탕
                   + ["서우가 도아에게 맞바꿨다.",
                      "베풀다는 상대에게 구슬 5개를 주는 것이다.",
                      "지금 서우 구슬은 몇 개야?"])
        self.assertIn("8개", answer)
        self.assertNotIn("5개", answer)

    def test_a_word_explained_with_itself_is_refused(self):
        self.assertIn("못 읽겠습니다", 답(["뒤집다는 내가 상대에게 뒤집는 것이다."]))

    def test_a_chain_of_places_keeps_its_own_constants(self):
        """`상자` 는 앞절의 도착지이자 뒷절의 옮길 것이다. 사건 값과 안 부딪친다."""
        turns = ["옮겨쌓다는 물건을 상자로 옮기고, 상자를 책상으로 옮기는 것이다.",
                 "연필은 서랍에 있었다.", "하루가 연필을 옮겨쌓았다."]
        self.assertIn("상자", 답(turns + ["지금 연필은 어디에 있어?"]))
        self.assertIn("책상", 답(turns + ["지금 상자는 어디에 있어?"]))

    def test_two_placeholders_the_event_cannot_tell_apart_are_refused(self):
        """자리말 둘에 조사가 하나면 사건이 못 가른다. 겹쳐 쓰면 어긋난 사실이 는다."""
        parser = RelationalParser()
        self.assertIsNone(induce(parser, "물건을 책상으로 옮기고, 물체를 상자로 옮기는"))


class ReadingContestTest(unittest.TestCase):
    """넓은 사례 틀과 배운 동작은 **겨뤄서** 정한다. 먼저 보는 쪽이 이기면 안 된다."""

    보관 = ["보관하다는 물건을 가방으로 옮기는 것이다.",
          "준비하다는 내가 물건을 보관하고, 가방을 창고로 옮기는 것이다.",
          "공책은 책상에 있었다.", "하린이 공책을 준비했다."]

    def test_a_learned_move_is_not_shoved_aside_by_a_broad_frame(self):
        """`내가 물건을 보관하고` 가 통째로 한 이름으로 삼켜져 맞던 자리다.

        `보관하` 처럼 넓은 사례 틀에 걸리는 낱말이라야 이 결함이 드러난다 —
        안 걸리는 낱말로는 고치기 전에도 통과한다.
        """
        self.assertIn("가방", 답(self.보관 + ["지금 공책은 어디에 있어?"]))
        self.assertIn("창고", 답(self.보관 + ["지금 가방은 어디에 있어?"]))

    def test_an_unread_change_never_confirms_the_old_value(self):
        self.assertNotIn("책상", 답(self.보관 + ["지금 공책은 어디에 있어?"]))

    def test_a_word_the_broad_frame_never_grabs_still_works(self):
        """과교정을 막는 짝. 고치기 전에도 서던 꼴이다."""
        turns = ["담그다는 물건을 항아리로 옮기는 것이다.",
                 "재우다는 내가 물건을 담그고, 항아리를 광으로 옮기는 것이다.",
                 "무는 마당에 있었다.", "소리가 무를 재웠다."]
        self.assertIn("항아리", 답(turns + ["지금 무는 어디에 있어?"]))


class LearnedCallCheckTest(unittest.TestCase):
    """배운 동작을 부를 때도 빈 역할·고정값 충돌·남는 인수를 본다."""

    def test_a_value_the_definition_already_fixed_is_not_silently_dropped(self):
        """`금고로` 를 버리고 뜻풀이의 `서랍` 을 쓰면 안 된다."""
        answer = 답(["숨기다는 물건을 서랍으로 옮기는 것이다.",
                    "감추다는 내가 물건을 금고로 숨기고, 서랍을 벽으로 옮기는 것이다."])
        self.assertIn("못 읽겠습니다", answer)

    def test_the_same_shape_without_the_clash_still_works(self):
        """막는 쪽으로만 기울면 과교정이다."""
        turns = ["숨기다는 물건을 서랍으로 옮기는 것이다.",
                 "감추다는 내가 물건을 숨기고, 서랍을 벽으로 옮기는 것이다.",
                 "열쇠는 책상에 있었다.", "소리가 열쇠를 감췄다."]
        self.assertIn("서랍", 답(turns + ["지금 열쇠는 어디에 있어?"]))
        self.assertIn("벽", 답(turns + ["지금 서랍은 어디에 있어?"]))

    def test_an_unusable_explanation_does_not_let_the_old_value_stand(self):
        answer = 답(["숨기다는 물건을 서랍으로 옮기는 것이다.",
                    "감추다는 내가 물건을 금고로 숨기고, 서랍을 벽으로 옮기는 것이다.",
                    "열쇠는 책상에 있었다.", "소리가 열쇠를 감췄다.",
                    "지금 열쇠는 어디에 있어?"])
        self.assertNotIn("책상에 있습니다", answer)


class StateMeasureTest(unittest.TestCase):
    """양이 글자 그대로의 수가 아닐 때 **지금 상태를 보고 잰다.**"""

    뜻 = "나누다는 상대에게 구슬의 절반을 주는 것이다."

    def 물음(self, 민수, 지연, 묻기):
        return 답([self.뜻, "민수 구슬은 %d개 있다." % 민수, "지연 구슬은 %d개 있다." % 지연,
                  "민수가 지연에게 나눴다.", 묻기])

    def test_the_same_definition_reads_the_state_it_finds(self):
        """같은 정의가 다른 초기 상태에서 다른 올바른 값을 낸다."""
        self.assertIn("4개", self.물음(8, 3, "지금 민수 구슬은 몇 개야?"))
        self.assertIn("5개", self.물음(10, 3, "지금 민수 구슬은 몇 개야?"))

    def test_the_measured_amount_reaches_the_other_side(self):
        """던 만큼 는다. 두 쪽을 따로 재면 어긋난다."""
        self.assertIn("7개", self.물음(8, 3, "지금 지연 구슬은 몇 개야?"))
        self.assertIn("8개", self.물음(10, 3, "지금 지연 구슬은 몇 개야?"))

    def test_an_amount_that_does_not_divide_is_not_invented(self):
        """쪼갤 수 있는지는 우리가 정할 일이 아니다."""
        answer = self.물음(7, 3, "지금 민수 구슬은 몇 개야?")
        self.assertNotIn("개입니다", answer)
        self.assertIn("나누어떨어지지", answer)

    def test_an_unknown_basis_is_shown_as_missing(self):
        answer = 답([self.뜻, "지연 구슬은 3개 있다.", "민수가 지연에게 나눴다.",
                    "지금 지연 구슬은 몇 개야?"])
        self.assertNotIn("개입니다", answer)
        self.assertIn("기준", answer)

    def test_a_value_that_event_could_not_touch_is_still_answered(self):
        """막는 쪽으로만 기울면 과교정이다."""
        self.assertIn("5개", 답([self.뜻, "민수 구슬은 7개 있다.", "단추는 5개 있다.",
                               "민수가 지연에게 나눴다.", "지금 단추는 몇 개야?"]))

    def test_a_measured_amount_works_inside_a_composition(self):
        """계산된 양을 가진 절이 다른 절과 엮인다."""
        turns = ["나눠주다는 상대에게 구슬의 절반을 주고, 상대가 나에게 단추 한 개를 주는 것이다.",
                 "민수 구슬은 8개 있다.", "민수 단추는 1개 있다.",
                 "지연 구슬은 2개 있다.", "지연 단추는 5개 있다.",
                 "민수가 지연에게 나눠줬다."]
        self.assertIn("4개", 답(turns + ["지금 민수 구슬은 몇 개야?"]))
        self.assertIn("6개", 답(turns + ["지금 지연 구슬은 몇 개야?"]))
        self.assertIn("2개", 답(turns + ["지금 민수 단추는 몇 개야?"]))

    def test_a_place_found_in_one_clause_is_used_by_the_next(self):
        """수량 밖에서도 앞 절이 찾은 것이 뒤 절로 이어진다."""
        turns = ["옮겨쌓다는 물건을 상자로 옮기고, 상자를 책상으로 옮기는 것이다.",
                 "연필은 서랍에 있었다.", "하루가 연필을 옮겨쌓았다."]
        self.assertIn("상자", 답(turns + ["지금 연필은 어디에 있어?"]))
        self.assertIn("책상", 답(turns + ["지금 상자는 어디에 있어?"]))


class FillerTest(unittest.TestCase):
    """말머리 군말은 **읽기 후보를 하나 더** 두어 넘는다. 지우는 규칙이 아니다."""

    뜻 = "베풀다는 상대에게 구슬 2개를 주는 것이다."
    기준 = ["민수 구슬은 8개 있다.", "지연 구슬은 3개 있다."]

    def test_a_filler_in_front_of_an_event_does_not_break_it(self):
        for 머리 in ("음,", "저기요", "그러니까"):
            answer = 답([self.뜻] + self.기준 + ["%s 민수가 지연에게 베풀었다." % 머리,
                                            "지금 민수 구슬은 몇 개야?"])
            self.assertIn("6개", answer, 머리)

    def test_a_filler_in_front_of_a_question_does_not_break_it(self):
        for 머리 in ("그러니까", "혹시", "근데"):
            answer = 답([self.뜻] + self.기준 + ["민수가 지연에게 베풀었다.",
                                            "%s 지금 민수 구슬은 몇 개야?" % 머리])
            self.assertIn("6개", answer, 머리)

    def test_the_original_wording_is_still_what_we_keep(self):
        """원문은 그대로 남는다 — 읽기만 벗긴 꼴로 한다."""
        context = ReasoningContext()
        for text in [self.뜻] + self.기준 + ["음, 민수가 지연에게 베풀었다."]:
            context.turn(text, KG)
        self.assertIn("음, 민수가 지연에게 베풀었다.", context.observations)

    def test_an_utterance_that_is_only_a_filler_is_left_alone(self):
        """`글쎄요` 하나는 군말이 아니라 그 자체가 발화다."""
        answer = 답([self.뜻] + self.기준 + ["민수가 지연에게 베풀었다.", "글쎄요",
                                        "지금 민수 구슬은 몇 개야?"])
        self.assertIn("6개", answer)


class PointingTest(unittest.TestCase):
    """앞서 말한 것을 도로 가리키는 말. **고르지 않는다** — 여럿이면 묻는다."""

    뜻 = "베풀다는 상대에게 구슬 2개를 주는 것이다."
    기준 = ["민수 구슬은 8개 있다.", "지연 구슬은 3개 있다.", "민수가 지연에게 베풀었다."]

    def test_it_points_at_what_we_just_talked_about(self):
        self.assertIn("6개", 답([self.뜻] + self.기준 + ["지금 민수 구슬은 몇 개야?",
                                                   "지금 그것은 몇 개야?"]))

    def test_the_nearest_thing_asked_about_wins(self):
        self.assertIn("5개", 답([self.뜻] + self.기준 + ["지금 지연 구슬은 몇 개야?",
                                                   "지금 그 사람 구슬은 몇 개야?"]))

    def test_several_candidates_are_asked_about_not_guessed(self):
        answer = 답([self.뜻] + self.기준 + ["지금 그 사람 구슬은 몇 개야?"])
        self.assertNotIn("개입니다", answer)
        self.assertIn("민수 구슬", answer)
        self.assertIn("지연 구슬", answer)

    def test_with_nothing_to_point_at_it_says_so(self):
        answer = 답(["지금 그것은 몇 개야?"])
        self.assertNotIn("개입니다", answer)
        self.assertIn("찾지 못했습니다", answer)

    def test_a_plain_question_is_untouched(self):
        """가리킴말이 없는 물음까지 건드리면 과교정이다."""
        self.assertIn("6개", 답([self.뜻] + self.기준 + ["지금 민수 구슬은 몇 개야?"]))
        self.assertIn("5개", 답([self.뜻] + self.기준 + ["지금 지연 구슬은 몇 개야?"]))


class PlanTest(unittest.TestCase):
    """아직 안 일어난 일은 **사실이 아니다.** 기록만 되고 상태를 안 바꾼다."""

    뜻 = "베풀다는 상대에게 구슬 2개를 주는 것이다."
    기준 = ["민수 구슬은 8개 있다.", "지연 구슬은 3개 있다."]

    def test_a_plan_is_not_carried_out(self):
        turns = [self.뜻] + self.기준 + ["민수가 지연에게 베풀 예정이다."]
        self.assertIn("8개", 답(turns + ["지금 민수 구슬은 몇 개야?"]))
        self.assertIn("3개", 답(turns + ["지금 지연 구슬은 몇 개야?"]))

    def test_a_plan_is_still_written_down(self):
        """버리는 것이 아니다 — 계획으로 적어 둔다."""
        from relational_semantics import RelationalParser
        context = ReasoningContext()
        for text in [self.뜻] + self.기준 + ["민수가 지연에게 베풀 예정이다."]:
            context.turn(text, KG)
        parser = RelationalParser()
        facts, _d, _p, _r = context._replay(parser, context.observations, context.fills)
        계획 = [f for f in facts if f.get("modality") == "planned"]
        self.assertEqual(len(계획), 2)

    def test_the_same_verb_actually_done_still_runs(self):
        self.assertIn("6개", 답([self.뜻] + self.기준 + ["민수가 지연에게 베풀었다.",
                                                   "지금 민수 구슬은 몇 개야?"]))

    def test_a_plan_in_a_speech_style_we_declared(self):
        for 맺음 in ("예정이다", "예정입니다", "예정이야"):
            answer = 답([self.뜻] + self.기준 + ["민수가 지연에게 베풀 %s." % 맺음,
                                            "지금 민수 구슬은 몇 개야?"])
            self.assertIn("8개", answer, 맺음)

    def test_a_broad_frame_no_longer_swallows_the_plan(self):
        """전에는 `민수 isa 지연에게 베풀 예정` 이라는 **단정 사실**이 됐다."""
        from relational_semantics import RelationalParser
        context = ReasoningContext()
        for text in [self.뜻] + self.기준 + ["민수가 지연에게 베풀 예정이다."]:
            context.turn(text, KG)
        parser = RelationalParser()
        facts, _d, _p, _r = context._replay(parser, context.observations, context.fills)
        self.assertFalse([f for f in facts if f["triple"][1] == "isa"])


class ScopeWordTest(unittest.TestCase):
    """적어 둔 말과 **그대로 같을 때만** 받는다."""

    바탕 = ["치우다는 물건을 상자로 옮기는 것이다.", "연필은 책상에 있었다."]

    def test_a_negated_scope_word_is_not_executed_as_the_scope(self):
        """앞부분만 보면 `정정 아냐` 가 `정정` 으로 실행된다."""
        for 말 in ("정정 아냐", "바꾸지 마", "이번만은 아니야"):
            answer = 답(self.바탕 + ["하루가 연필을 학교로 치웠다.", 말,
                                  "지금 연필은 어디에 있어?"])
            self.assertNotIn("에 있습니다", answer, 말)


class ContradictionTest(unittest.TestCase):
    """앞말과 어긋나는 사건은 **안 일어난 일이 아니다.**"""

    def test_a_contradicting_event_does_not_confirm_the_old_value(self):
        answer = 답(["구슬은 3개 있다.", "구슬 8개를 꺼냈다.", "지금 구슬은 몇 개야?"])
        self.assertNotIn("3개입니다", answer)
        self.assertIn("구슬 8개를 꺼냈다", answer)

    def test_both_statements_are_kept(self):
        context = ReasoningContext()
        for text in ("구슬은 3개 있다.", "구슬 8개를 꺼냈다."):
            context.turn(text, KG)
        self.assertEqual(context.observations, ["구슬은 3개 있다."])
        self.assertEqual([x["text"] for x in context.unread], ["구슬 8개를 꺼냈다."])

    def test_arithmetic_that_does_hold_is_not_blocked(self):
        """성립하는 셈까지 막으면 과교정이다."""
        self.assertIn("5개", 답(["구슬은 8개 있다.", "구슬 3개를 꺼냈다.", "지금 구슬은 몇 개야?"]))
