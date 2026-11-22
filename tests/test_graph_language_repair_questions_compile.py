# -*- coding: utf-8 -*-
"""Public, self-authored controls for experiments/graph_language_repair/questions/compile.py.

No private case text, golds or prior author scripts are used here. These
sentences are written fresh for this experiment.
"""
from experiments.graph_language_repair.questions.compile import compile_question, slot_value


def test_source_question_multiword_actor_and_object():
    plan = compile_question("김민수 박사가 그 오래된 유물을 보고했다고 누가 말했나요?")
    assert plan["intent"] == "source_question"
    assert plan["unresolved"] == []
    assert slot_value(plan["slots"], "subject") == ("김민수 박사", "ok")
    assert slot_value(plan["slots"], "object") == ("그 오래된 유물", "ok")


def test_verification_question_word_order_independent():
    a = compile_question("국립 박물관 수석 연구원이 오래된 유물을 확인했나요?")
    b = compile_question("오래된 유물을 국립 박물관 수석 연구원이 확인했나요?")
    assert a["intent"] == b["intent"] == "verification_question"
    assert slot_value(a["slots"], "subject") == slot_value(b["slots"], "subject") == ("국립 박물관 수석 연구원", "ok")
    assert slot_value(a["slots"], "object") == slot_value(b["slots"], "object") == ("오래된 유물", "ok")
    assert a["unresolved"] == b["unresolved"] == []


def test_occurrence_question_distinguished_from_source_and_verification():
    occurrence = compile_question("그 사건이 실제로 일어났나요?")
    source = compile_question("그 사건을 누가 보고했나요?")
    verification = compile_question("김민수가 그 사건을 확인했나요?")
    assert {occurrence["intent"], source["intent"], verification["intent"]} == {
        "occurrence_question", "source_question", "verification_question"}


def test_verification_cue_recognized_but_target_not_silently_dropped():
    """A verification cue with only an actor present must not be answered as
    if the missing object were irrelevant -- it must be reported unresolved."""
    plan = compile_question("수석 연구원이 확인했나요?")
    assert plan["intent"] == "verification_question"
    assert plan["unresolved"]
    assert plan["unresolved"][0]["reason"] == "missing_argument"
    assert plan["unresolved"][0]["missing"] == ["object"]


def test_two_subjects_are_reported_ambiguous_not_silently_overwritten():
    """A second subject-marked phrase must not vanish into the first slot."""
    plan = compile_question("김민수가 박지훈이 그 유물을 확인했나요?")
    assert len(plan["slots"]["subject"]) == 2
    assert plan["intent"] == "verification_question"
    assert plan["unresolved"]
    problem = plan["unresolved"][0]
    assert problem["reason"] == "ambiguous_argument"
    assert problem["function"] == "subject"
    assert set(problem["candidates"]) == {"김민수", "박지훈"}


def test_who_word_tail_is_not_mistaken_for_a_second_subject_marker():
    """'누가' ends in the subject particle '가' but is one interrogative
    word, not a second subject-marked noun phrase."""
    plan = compile_question("김민수 박사가 그 오래된 유물을 보고했다고 누가 말했나요?")
    assert plan["slots"]["subject"] == [{"text": "김민수 박사", "span": [0, 6]}]


def test_event_role_question_who_moved_it():
    plan = compile_question("그 유물을 누가 전달했나요?")
    assert plan["intent"] == "event_role_question"
    assert plan["asked_predicate"] == "actor"
    assert slot_value(plan["slots"], "object") == ("그 유물", "ok")
    assert plan["required_action"] == "action:transfer"
    assert plan["unresolved"] == []


def test_event_role_question_origin():
    plan = compile_question("그 그림은 어디서 전달되었나요?")
    assert plan["intent"] == "event_role_question"
    assert plan["asked_predicate"] == "origin"
    assert slot_value(plan["slots"], "topic") == ("그 그림", "ok")
    assert plan["required_action"] == "action:transfer"


def test_event_role_question_with_unrecognized_action_is_disclosed():
    """AUDITOR.md review 8 item 2: a loan is not a declared action
    anywhere in the system; the question must not fall back to answering
    from whichever action happens to be in the document."""
    plan = compile_question("그 책을 누구에게 대여했나요?")
    assert plan["intent"] == "event_role_question"
    assert plan["required_action"].startswith("action:observed:")
    assert plan["required_action"] != "action:transfer"
    assert not plan["unresolved"]


def test_event_role_question_with_ambiguous_action_is_disclosed():
    """A question naming two different declared actions at once must not
    silently pick one."""
    plan = compile_question("그 책을 누구에게 인계 접수했나요?")
    assert plan["intent"] is None
    assert plan["unresolved"][0]["reason"] == "ambiguous_action"
    assert set(plan["unresolved"][0]["candidates"]) == {"action:transfer", "action:receive"}


def test_event_role_question_with_conflicting_asked_roles_is_disclosed():
    """Two role-interrogatives asking for different predicates must not be
    resolved by picking whichever one happens to be scanned first."""
    plan = compile_question("누가 언제 그 유물을 옮겼나요?")
    assert plan["intent"] is None
    assert plan["unresolved"][0]["reason"] == "ambiguous_role_question"
    assert set(plan["unresolved"][0]["candidates"]) == {"actor", "time"}


def test_who_checked_reinterprets_as_a_checking_role_question():
    """'누가 X를 확인했나요?' asks for checking_actor, not an incomplete
    verification_question missing its subject (CORE-SECOND-AUDIT A7)."""
    plan = compile_question("부품을 누가 확인했나요?")
    assert plan["intent"] == "checking_role_question"
    assert plan["asked_predicate"] == "checking_actor"
    assert plan["anchor_predicate"] == "checking_object"
    assert plan["anchor_value"] == "부품"
    assert plan["unresolved"] == []


def test_report_frame_phrase_does_not_corrupt_the_subject():
    """'X에 따르면' frames the whole question; it must not be absorbed into
    the following subject span (AUDITOR.md review 6)."""
    plan = compile_question("보고서에 따르면 김과장이 무엇을 전달했나요?")
    assert plan["slots"]["subject"] == [{"text": "김과장", "span": [9, 12]}]


def test_unrecognized_question_is_disclosed_not_guessed():
    plan = compile_question("오늘 날씨가 어떤가요?")
    assert plan["intent"] is None
    assert plan["unresolved"][0]["reason"] == "no_recognized_cue"


def test_phase3_composed_relative_identity_and_request_matrix():
    # Cross product of independent closed grammatical components with open
    # predicates; no item-specific target names or actions in the grammar.
    from experiments.graph_language_repair.questions.compile import compile_question
    for verb in ('색인', '분류', '보관'):
        for head in ('사람', '이'):
            for tail in ('누구였는가', '누구지', '누구인가요', '누구인지 알려줘', '누구인지 궁금하다'):
                plan = compile_question(f'도면을 {verb}한 {head}은 {tail}?')
                # 이는 takes 는, unlike 사람은.
                if head == '이':
                    plan = compile_question(f'도면을 {verb}한 이는 {tail}?')
                assert plan['intent'] == 'event_role_question', plan
                assert plan['asked_predicate'] == 'actor' and not plan['unresolved']
                assert plan['question_graph']['identity']
        plan = compile_question(f'미린이 {verb}한 물건은 무엇이었나?')
        assert plan['asked_predicate'] == 'object' and not plan['unresolved']
        nominal = compile_question(f'도면은 누가 {verb}한 거야?')
        assert nominal['asked_predicate'] == 'actor' and not nominal['unresolved']
        assert nominal['question_graph']['nominal_wrapper'] == '거야'


def test_phase3_nonconsumed_scope_and_property_are_not_answered_as_identity():
    from experiments.graph_language_repair.questions.compile import compile_question
    from experiments.graph_language_repair.questions.select import execute_plan
    from experiments.graph_language_repair.core import read_text
    reading = read_text('미린이 도면을 색인했다.')
    for question in ('도면을 색인한 사람이 누구인지 알려줘 그리고 삭제해.',
                     '도면을 색인한 사람이 누구인지 몰래 알려줘.',
                     '도면을 색인한 사람은 어디였는가?',
                     '도면은 누가 색인한 거야 그리고 삭제해?'):
        plan = compile_question(question)
        assert execute_plan(plan, reading)['gate'] is not None, plan
    plan = compile_question('도면을 색인한 사람의 이름은?')
    assert plan['question_graph']['identity']['property'] == '의 이름'
    assert execute_plan(plan, reading)['gate'] == 'unresolved'


def test_phase3_identity_morpheme_composition_tense_mood_and_requests():
    from experiments.graph_language_repair.questions.compile import compile_question
    for verb in ('대조', '색인', '보관'):
        for copula, endings in [('였', ('나', '나요', '는가', '습니까', '는지')),
                                ('이었', ('나', '나요', '는가', '습니까', '는지')),
                                ('인', ('가', '가요', '지')),
                                ('일', ('까', '까요'))]:
            for ending in endings:
                suffix = ' 알려줘' if ending in ('지', '는지') else ''
                plan = compile_question(f'명세서를 {verb}한 사람은 누구{copula}{ending}{suffix}?')
                assert plan['intent'] == 'event_role_question' and not plan['unresolved'], plan
                assert plan['required_polarity'] == 'true'
                assert plan['question_graph']['identity']['copula'] == copula
        plan = compile_question(f'명세서를 {verb}하지 않은 사람은 누구였나요?')
        assert plan['required_polarity'] == 'false' and not plan['unresolved'], plan


def test_phase3_identity_tail_must_be_fully_consumed():
    from experiments.graph_language_repair.questions.compile import compile_question
    for tail in ('누구였나요 그리고 삭제해', '누구였는지 몰래 알려줘', '누구였더라도'):
        plan = compile_question('명세서를 대조한 사람은 ' + tail + '?')
        assert plan.get('unresolved') or not plan.get('intent'), plan


def test_relative_gap_ownership_preserves_competing_roles_and_constraints():
    from experiments.graph_language_repair.questions.compile import compile_question
    for verb in ('묶', '대조하', '색인하'):
        ending = '은' if verb == '묶' else 'ㄴ'
        # Korean syllable completion for the two productive 하 forms.
        relative = verb + ending if verb == '묶' else verb[:-1] + '한'
        for prefix in ('다솔이 ', '다솔이 민수를 '):
            plan = compile_question(prefix + relative + ' 사람은 누구야?')
            assert plan['unresolved'][0]['reason'] == 'unresolved_relative_gap', plan
            assert plan['slots']['subject'][0]['text'] == '다솔'
            assert 'actor' in plan['question_graph']['relative_gap']['occupied_roles']
        actor = compile_question('문서를 ' + relative + ' 사람은 누구야?')
        assert not actor['unresolved'] and actor['asked_predicate'] == 'actor', actor
        obj = compile_question('다솔이 ' + relative + ' 물건은 무엇이었나?')
        assert not obj['unresolved'] and obj['asked_predicate'] == 'object', obj
    for question in ('묶은 사람은 누구야?', '다솔에 의해 색인된 사람은 누구야?',
                     '도면이 색인된 사람은 누구야?', '다솔이 도면을 색인한 물건은 무엇이야?',
                     '다솔이라는 사람이 도면을 색인한 사람은 누구야?'):
        plan = compile_question(question)
        assert plan.get('unresolved') or not plan.get('intent'), plan
