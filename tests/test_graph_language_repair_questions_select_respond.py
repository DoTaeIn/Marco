# -*- coding: utf-8 -*-
"""Public, self-authored controls for questions/select.py and questions/respond.py.

These build a hand-written fixture world in the exact shape CONTRACT.md
section 0/6 documents for ``core.search_rows`` (itself a thin, unchanged
transport onto ``marco.reasoning.relation_hypotheses._evaluate_world``), so
the question/answer side is tested against the real interface shape without
needing experiments/graph_language_repair/core to exist yet. No private
case text, golds or prior author scripts are used.
"""
from experiments.graph_language_repair.questions.compile import compile_question
from experiments.graph_language_repair.questions.select import execute_plan
from experiments.graph_language_repair.questions import respond


def _fixture_search_rows(rows):
    """rows: list of (subject, predicate, object, source_ref, premise_id[, polarity]).

    Mirrors ``_evaluate_world``'s match shape (``triple``, ``bindings``,
    ``support_ids``) and ``fact_sources`` (``premise_id``, ``source_ref``,
    ``original_fact``) closely enough to drive every hop shape used in
    graphs/questions/plans.json: one '?'-asked position at the subject or
    the object, or a fully-ground existence check (no '?' at all -- real
    ``bind()`` returns ``{}`` on a match there, it is not unsupported).
    ``polarity`` defaults to ``True`` (an ordinary positive assertion) when
    omitted.
    """
    def search_rows(reading, triple):
        subject, predicate, obj = triple
        matches, fact_sources = [], []
        for row in rows:
            row_subject, row_predicate, row_object, source_ref, premise_id = row[:5]
            polarity = row[5] if len(row) > 5 else True
            if row_predicate != predicate:
                continue
            if subject[:1] == "?":
                if row_object != obj:
                    continue
                bindings = {subject: row_subject}
            elif obj[:1] == "?":
                if row_subject != subject:
                    continue
                bindings = {obj: row_object}
            elif row_subject == subject and row_object == obj:
                bindings = {}
            else:
                continue
            matches.append({"triple": [row_subject, row_predicate, row_object],
                             "bindings": bindings, "support_ids": [premise_id]})
            fact_sources.append({"premise_id": premise_id, "source_ref": source_ref,
                                   "original_fact": {"polarity": polarity}})
        return {"matches": matches, "facts": [], "proof_bundles": [], "fact_sources": fact_sources,
                "rules": [], "complete": True, "reason": None, "searches": 0}
    return search_rows


def test_source_question_identifies_reporter_from_attribution_claim():
    rows = [
        ("event:0", "object", "그 유물", {"row": "row:0", "claim": "claim:1", "scope_kind": "attribution"}, "p0"),
        ("event:0", "in_claim", "claim:1", {"row": "row:1", "claim": "claim:1", "scope_kind": "attribution"}, "p1"),
        ("claim:1", "reporter", "김민수", {"row": "row:2", "claim": "claim:1", "scope_kind": "attribution"}, "p2"),
    ]
    plan = compile_question("그 유물을 누가 보고했나요?")
    result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows(rows))
    assert result["gate"] is None
    assert result["value"] == "김민수"
    text = respond.render(result, plan)
    assert "김민수가" in text
    assert "보고했다고" in text


def test_occurrence_question_direct_text_never_claims_independent_confirmation():
    rows = [
        ("event:0", "actor", "그 사건", {"row": "row:0", "claim": "claim:0", "scope_kind": "direct_text"}, "p0"),
        ("event:0", "in_claim", "claim:0", {"row": "row:1", "claim": "claim:0", "scope_kind": "direct_text"}, "p1"),
        ("claim:0", "scope_kind", "direct_text", {"row": "row:2", "claim": "claim:0", "scope_kind": "direct_text"}, "p2"),
    ]
    plan = compile_question("그 사건이 실제로 일어났나요?")
    result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows(rows))
    assert result["case"] == "scope_kind"
    assert result["value"] == "direct_text"
    text = respond.render(result, plan)
    assert "확인됩니다" not in text  # no claim of independent verification, textual assertion only
    assert "서술되어" in text
    assert "독립적인" in text  # explicit disclaimer that this is not independent confirmation


def test_occurrence_question_reported_claim_is_never_rendered_as_confirmed():
    rows = [
        ("event:0", "actor", "그 사건", {"row": "row:0", "claim": "claim:1", "scope_kind": "reported_claim"}, "p0"),
        ("event:0", "in_claim", "claim:1", {"row": "row:1", "claim": "claim:1", "scope_kind": "reported_claim"}, "p1"),
        ("claim:1", "scope_kind", "reported_claim", {"row": "row:2", "claim": "claim:1", "scope_kind": "reported_claim"}, "p2"),
        ("claim:1", "reporter", "김민수", {"row": "row:3", "claim": "claim:1", "scope_kind": "reported_claim"}, "p3"),
    ]
    plan = compile_question("그 사건이 실제로 일어났나요?")
    result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows(rows))
    assert result["value"] == "reported_claim"
    text = respond.render(result, plan)
    assert "확인됩니다" not in text
    assert "보류" in text
    assert "김민수가" in text  # explicit attribution, not a bare hold


def test_occurrence_question_prefers_independent_checking_outcome_over_scope_kind():
    rows = [
        ("event:0", "actor", "그 사건", {"row": "row:0", "claim": "claim:1", "scope_kind": "reported_claim"}, "p0"),
        ("event:0", "verified_by", "checking:0", {"row": "row:1", "claim": "claim:1", "scope_kind": "reported_claim"}, "p1"),
        ("checking:0", "checking_outcome", "confirmed", {"row": "row:2", "claim": "claim:1", "scope_kind": "checking_action"}, "p2"),
        ("event:0", "in_claim", "claim:1", {"row": "row:3", "claim": "claim:1", "scope_kind": "reported_claim"}, "p3"),
        ("claim:1", "scope_kind", "reported_claim", {"row": "row:4", "claim": "claim:1", "scope_kind": "reported_claim"}, "p4"),
    ]
    plan = compile_question("그 사건이 실제로 일어났나요?")
    result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows(rows))
    assert result["case"] == "checked_outcome"
    assert result["value"] == "confirmed"
    text = respond.render(result, plan)
    assert "독립적인 확인" in text


def test_verification_question_multiword_actor_and_object_confirmed():
    rows = [
        ("checking:0", "checking_actor", "국립 박물관 수석 연구원",
         {"row": "row:0", "claim": "claim:0", "scope_kind": "checking_action"}, "p0"),
        ("checking:0", "checking_object", "오래된 유물",
         {"row": "row:1", "claim": "claim:0", "scope_kind": "checking_action"}, "p1"),
        ("checking:0", "checking_outcome", "confirmed",
         {"row": "row:2", "claim": "claim:0", "scope_kind": "checking_action"}, "p2"),
    ]
    plan = compile_question("국립 박물관 수석 연구원이 오래된 유물을 확인했나요?")
    result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows(rows))
    assert result["value"] == "confirmed"
    text = respond.render(result, plan)
    assert "국립 박물관 수석 연구원이" in text
    assert "오래된 유물을" in text
    assert "맞음" in text


def test_verification_question_denied_is_a_genuine_negative_result_when_action_happened():
    rows = [
        ("checking:0", "checking_actor", "김민수", {"row": "row:0", "claim": "claim:0", "scope_kind": "checking_action"}, "p0"),
        ("checking:0", "checking_object", "그 유물", {"row": "row:1", "claim": "claim:0", "scope_kind": "checking_action"}, "p1"),
        ("checking:0", "checking_outcome", "denied", {"row": "row:2", "claim": "claim:0", "scope_kind": "checking_action"}, "p2", True),
    ]
    plan = compile_question("김민수가 그 유물을 확인했나요?")
    result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows(rows))
    assert result["value"] == "denied"
    text = respond.render(result, plan)
    assert "아님" in text


def test_verification_question_negated_checking_action_is_not_read_as_a_negative_result():
    """A row carrying checking_outcome='denied' whose own polarity is False
    means the checking action itself was negated (CONTRACT.md C5), not that
    a performed check found the object false -- this must render as 'no
    check happened', not as a negative result."""
    rows = [
        ("checking:0", "checking_actor", "검사팀", {"row": "row:0", "claim": "claim:0", "scope_kind": "checking_action"}, "p0", True),
        ("checking:0", "checking_object", "창고 상태", {"row": "row:1", "claim": "claim:0", "scope_kind": "checking_action"}, "p1", True),
        ("checking:0", "checking_outcome", "denied", {"row": "row:2", "claim": "claim:0", "scope_kind": "checking_action"}, "p2", False),
    ]
    plan = compile_question("검사팀이 창고 상태를 확인했나요?")
    result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows(rows))
    assert result["raw_value"] == "denied"
    assert result["value"] == "action_not_performed"
    text = respond.render(result, plan)
    assert "확인한 사실 자체가 없는" in text
    assert "아님" not in text  # never stated as a negative result


def test_verification_question_missing_object_is_disclosed_not_executed():
    plan = compile_question("수석 연구원이 확인했나요?")
    assert plan["unresolved"]
    text = respond.render({"gate": "unresolved", "intent": plan["intent"]}, plan)
    assert "표현할 수 없습니다" in text
    assert "missing_argument" in text
    assert "object" in text


def test_verification_hold_renders_without_crashing_when_no_checking_row_found():
    """Regression: the hold template needs actor_phrase/object_phrase too;
    a gated result must not KeyError on a placeholder format() call."""
    plan = compile_question("검사팀이 창고 상태를 확인했나요?")
    result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows([]))
    assert result["gate"] == "no_answer_row"
    text = respond.render(result, plan)
    assert "확인할 수 없습니다" in text
    assert "검사팀이" in text
    assert "창고 상태를" in text


def test_event_role_question_who_moved_it():
    rows = [
        ("event:0", "object", "그 유물", {"row": "row:0", "claim": "claim:0", "scope_kind": "direct_text"}, "p0"),
        ("event:0", "actor", "김민수", {"row": "row:1", "claim": "claim:0", "scope_kind": "direct_text"}, "p1"),
        ("event:0", "action", "action:transfer", {"row": "row:2", "claim": "claim:0", "scope_kind": "direct_text"}, "p2"),
    ]
    plan = compile_question("그 유물을 누가 전달했나요?")
    result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows(rows))
    assert result["value"] == "김민수"
    text = respond.render(result, plan)
    assert "김민수입니다" in text


def test_event_role_question_two_constraints_must_bind_the_same_event():
    """AUDITOR.md review 8 item 1: a second explicit role constraint naming
    a different event must not be dropped in favor of the first."""
    rows = [
        ("event:0", "actor", "가람", {"row": "row:0", "claim": "claim:0", "scope_kind": "direct_text"}, "p0"),
        ("event:0", "object", "책", {"row": "row:1", "claim": "claim:0", "scope_kind": "direct_text"}, "p1"),
        ("event:0", "destination", "나래", {"row": "row:2", "claim": "claim:0", "scope_kind": "direct_text"}, "p2"),
        ("event:0", "action", "action:transfer", {"row": "row:3", "claim": "claim:0", "scope_kind": "direct_text"}, "p3"),
        ("event:1", "actor", "다온", {"row": "row:4", "claim": "claim:0", "scope_kind": "direct_text"}, "p4"),
        ("event:1", "object", "우산", {"row": "row:5", "claim": "claim:0", "scope_kind": "direct_text"}, "p5"),
        ("event:1", "destination", "소이", {"row": "row:6", "claim": "claim:0", "scope_kind": "direct_text"}, "p6"),
        ("event:1", "action", "action:transfer", {"row": "row:7", "claim": "claim:0", "scope_kind": "direct_text"}, "p7"),
    ]
    search_rows = _fixture_search_rows(rows)

    # Both constraints correctly name event:0.
    correct0 = execute_plan(compile_question("가람이 책을 누구에게 전달했나요?"), reading=None,
                              search_rows=search_rows)
    assert correct0["value"] == "나래"

    # Both constraints correctly name event:1 -- proves this isn't just
    # defaulting to "the first event" generally.
    correct1 = execute_plan(compile_question("다온이 우산을 누구에게 전달했나요?"), reading=None,
                              search_rows=search_rows)
    assert correct1["value"] == "소이"

    # Subject names event:0, object names event:1 -- no single event
    # satisfies both constraints.
    mismatched = execute_plan(compile_question("가람이 우산을 누구에게 전달했나요?"), reading=None,
                                search_rows=search_rows)
    assert mismatched["value"] not in ("나래", "소이")
    assert mismatched["gate"] == "conflicting_constraints"


def test_event_role_question_unrecognized_action_does_not_answer_from_an_unrelated_event():
    """AUDITOR.md review 8 item 2: a question naming an action the document
    never performed must not be answered from a different, real action."""
    rows = [
        ("event:0", "object", "책", {"row": "row:0", "claim": "claim:0", "scope_kind": "direct_text"}, "p0"),
        ("event:0", "destination", "나래", {"row": "row:1", "claim": "claim:0", "scope_kind": "direct_text"}, "p1"),
        ("event:0", "action", "action:transfer", {"row": "row:2", "claim": "claim:0", "scope_kind": "direct_text"}, "p2"),
    ]
    plan = compile_question("책을 누구에게 대여했나요?")
    assert plan["intent"] is None
    assert plan["unresolved"][0]["reason"] == "unrecognized_action"


def test_event_role_question_negated_event_discloses_rather_than_asserts():
    """AUDITOR.md review 8 item 3: a role value from a negated event must
    not render identically to the positive case."""
    rows = [
        ("event:0", "object", "책", {"row": "row:0", "claim": "claim:0", "scope_kind": "direct_text"}, "p0"),
        ("event:0", "actor", "가람", {"row": "row:1", "claim": "claim:0", "scope_kind": "direct_text"}, "p1"),
        ("event:0", "action", "action:transfer", {"row": "row:2", "claim": "claim:0", "scope_kind": "direct_text"}, "p2"),
        ("event:0", "polarity", "false", {"row": "row:3", "claim": "claim:0", "scope_kind": "direct_text"}, "p3"),
    ]
    search_rows = _fixture_search_rows(rows)
    plan = compile_question("가람이 무엇을 전달했나요?")
    result = execute_plan(plan, reading=None, search_rows=search_rows)
    assert result["value"] == "event_negated"
    assert result["raw_value"] == "책"
    text = respond.render(result, plan)
    assert "책" in text
    assert "일어나지 않았다고" in text

    positive_rows = rows[:3]
    positive_result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows(positive_rows))
    positive_text = respond.render(positive_result, plan)
    assert positive_text != text
    assert positive_text == "책입니다."


def test_occurrence_question_with_no_matching_event_is_a_hold_not_a_guess():
    plan = compile_question("아무도 모르는 사건이 실제로 일어났나요?")
    result = execute_plan(plan, reading=None, search_rows=_fixture_search_rows([]))
    assert result["gate"] == "no_event_match"
    text = respond.render(result, plan)
    assert "확인할 수 없습니다" in text


def test_live_negative_action_type_and_source_complement_are_preserved():
    from experiments.graph_language_repair.core import read_text
    def query(doc, question):
        plan = compile_question(question)
        result = execute_plan(plan, read_text(doc))
        return plan, result, respond.render(result, plan)
    _, wrong, _ = query('가람이 책을 받지 않았다.', '가람이 무엇을 전달했나요?')
    assert wrong['gate'] is not None
    _, same, text = query('가람이 책을 전달하지 않았다.', '가람이 무엇을 전달했나요?')
    assert same['value'] == 'event_negated' and '일어나지' in text
    _, good, _ = query('보고서에 따르면 가람이 책을 전달했다.', '가람이 책을 전달했다고 누가 보고했나요?')
    assert good['value'] == '보고서'
    for action in ('대여', '수령'):
        _, bad, _ = query('보고서에 따르면 가람이 책을 전달했다.', f'가람이 책을 {action}했다고 누가 보고했나요?')
        assert bad['gate'] is not None


def test_live_conflict_attribution_and_relative_question():
    from experiments.graph_language_repair.core import read_text
    def text(doc, question):
        plan = compile_question(question)
        result = execute_plan(plan, read_text(doc))
        return result, respond.render(result, plan)
    result, answer = text('가람이 책을 전달했다. 가람이 책을 전달하지 않았다.', '가람이 무엇을 전달했나요?')
    assert result['value'] == 'event_conflict' and '충돌' in answer
    _, answer = text('보고서에 따르면 가람이 책을 전달했다.', '가람이 무엇을 전달했나요?')
    assert '보고서' in answer and '책' in answer
    _, answer = text('보고서에 따르면 박검사관이 그 전달을 확인했다.', '박검사관이 그 전달을 확인했나요?')
    assert '보고서' in answer and '명시되지' in answer
    result, _ = text('가람이 부품을 창고에서 확인했다.', '부품을 창고에서 확인한 사람은 누구인가요?')
    assert result['value'] == '가람'


def test_live_missing_or_null_completeness_cannot_authorize_answer():
    from experiments.graph_language_repair.core import read_text, search_rows
    reading = read_text('가람이 책을 전달했다.')
    plan = compile_question('가람이 무엇을 전달했나요?')
    for complete in (None, 'missing'):
        def incomplete(reading, triple):
            world = search_rows(reading, triple)
            if complete == 'missing':
                world.pop('complete', None)
            else:
                world['complete'] = None
            return world
        result = execute_plan(plan, reading, search_rows=incomplete)
        assert result['gate'] == 'incomplete_search'


def test_live_rival_without_requested_role_requires_hold():
    from experiments.graph_language_repair.core import read_text
    question = '서진이 소식을 어디로 전달했나요?'
    plan = compile_question(question)
    result = execute_plan(plan, read_text('서진이 전화로 소식을 전달했다.'))
    assert result['gate'] == 'ambiguous_reading'
    assert '확정할 수 없습니다' in respond.render(result, plan)
    plan = compile_question('서진이 소식을 누구에게 전달했나요?')
    result = execute_plan(plan, read_text('서진이 소식을 다온에게 전달했다.'))
    assert result['value'] == '다온'


def test_live_report_target_polarity_is_constrained():
    from experiments.graph_language_repair.core import read_text
    for statement, inquiry, expected in [
        ('은별이 문서를 전달했다', '은별이 문서를 전달했다고 누가 보고했나요?', True),
        ('은별이 문서를 전달하지 않았다', '은별이 문서를 전달하지 않았다고 누가 보고했나요?', True),
        ('은별이 문서를 전달했다', '은별이 문서를 전달하지 않았다고 누가 보고했나요?', False),
        ('은별이 문서를 전달하지 않았다', '은별이 문서를 전달했다고 누가 보고했나요?', False),
    ]:
        result = execute_plan(compile_question(inquiry), read_text('보고서에 따르면 ' + statement + '.'))
        assert (result['gate'] is None and result['value'] == '보고서') is expected


def test_live_result_contradiction_is_not_unstated():
    from experiments.graph_language_repair.core import read_text
    inquiry = '은별이 창고를 확인했나요?'
    for expression, expected in [('사실로 확인했다', 'confirmed'), ('허위로 확인했다', 'denied'),
                                 ('확인했다', 'unstated'), ('사실로 허위로 확인했다', 'conflicting')]:
        reading = read_text('은별이 창고를 ' + expression + '.')
        plan = compile_question(inquiry)
        result = execute_plan(plan, reading)
        assert result['value'] == expected
        if expected == 'conflicting':
            assert result['state']['result_conflicts']
            assert '상반된' in respond.render(result, plan)
            assert '명시되지' not in respond.render(result, plan)
    reading = read_text('보고서에 따르면 은별이 창고를 사실로 허위로 확인했다.')
    plan = compile_question(inquiry)
    result = execute_plan(plan, reading)
    assert result['value'] == 'conflicting'
    assert '보고서' in respond.render(result, plan) and '충돌' in respond.render(result, plan)
