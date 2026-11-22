# -*- coding: utf-8 -*-
"""The existing search, used unchanged, and the provenance it carries back.

These are the tests that stand in for the questions a reader would actually
ask: who did it, what was checked, who said so, which of two readings is meant.
The query shapes here are deliberately plain triples — compiling a natural
question into one is the question owner's work, not the core's.
"""
from marco.reasoning import relation_hypotheses

from experiments.graph_language_repair.core import matches, project_rows, search_rows
from experiments.graph_language_repair.tests.controls import CONTROLS
from experiments.graph_language_repair.tests.helpers import reading


def _values(document, triple):
    return sorted(binding.get("?x") for binding, _, _ in matches(document, triple))


def test_the_search_helper_is_the_repository_one():
    import experiments.graph_language_repair.core.search as transport
    assert transport._evaluate_world.__module__ == relation_hypotheses.__name__


def test_every_control_projects_into_the_search_without_a_gap():
    for name in CONTROLS:
        document = reading(name)
        world = search_rows(document, ["?s", "?p", "?o"])
        assert world["complete"] is True, name
        assert len(world["facts"]) >= 1, name


def test_projected_facts_keep_the_shape_the_helper_accepts():
    facts, sources = project_rows(reading("active_transfer"))
    assert len(facts) == len(sources)
    for fact in facts:
        assert sorted(fact) == ["id", "modality", "polarity", "triple"]
        assert all(isinstance(atom, str) for atom in fact["triple"])


def test_a_role_question_binds_the_value_with_its_span_and_scope():
    document = reading("active_transfer")
    found = matches(document, ["event:0", "actor", "?x"])
    assert len(found) == 1
    binding, refs, triple = found[0]
    assert binding["?x"] == "김민수"
    assert refs and refs[0]["spans"]
    start, end = refs[0]["spans"][0]
    assert document["text"][start:end] == "김민수"
    assert refs[0]["claim"] == "claim:0"
    assert refs[0]["scope_kind"] == "direct_text"


def test_an_event_question_can_leave_the_event_open():
    document = reading("continuation_same_event")
    found = matches(document, ["?e", "destination", "?x"])
    assert {binding["?e"] for binding, _, _ in found} == {"event:0", "event:1"}


def test_a_checker_question_reaches_the_actor_and_the_object():
    document = reading("multiword_checker")
    assert _values(document, ["?e", "checking_actor", "?x"]) == ["생산 라인 책임자"]
    assert _values(document, ["?e", "checking_object", "?x"]) == ["그 전달"]
    assert _values(document, ["event:0", "verified_by", "?x"]) == ["event:1"]
    assert _values(document, ["?e", "checking_outcome", "?x"]) == ["unstated"]
    assert _values(document, ["?e", "checking_occurred", "?x"]) == ["occurred"]


def test_a_source_question_reaches_the_reporter_through_rows():
    document = reading("report_suffix")
    claims = _values(document, ["event:0", "in_claim", "?x"])
    assert claims == ["claim:1"]
    assert _values(document, ["claim:1", "scope_kind", "?x"]) == ["reported_claim"]
    assert _values(document, ["claim:1", "reporter", "?x"]) == ["경찰"]


def test_a_question_can_exclude_reported_material_by_scope():
    document = reading("report_then_check")
    found = matches(document, ["?e", "object", "?x"])
    assert found
    direct = [binding for binding, refs, _ in found
              if all(ref["scope_kind"] == "direct_text" for ref in refs)]
    assert direct == [], "the only transfer in this control is reported"
    reported = [binding for binding, refs, _ in found
                if any(ref["scope_kind"] == "reported_claim" for ref in refs)]
    assert len(reported) == 1


def test_a_verification_question_holds_when_only_an_object_matches():
    document = reading("report_then_check")
    assert _values(document, ["event:0", "verified_by", "?x"]) == []
    assert _values(document, ["event:0", "verified_by_candidate", "?x"]) == ["event:1"]


def test_a_verification_question_returns_nothing_for_a_reported_check():
    document = reading("reported_check_only")
    assert _values(document, ["event:0", "verified_by", "?x"]) == []
    assert _values(document, ["event:0", "verified_by_candidate", "?x"]) == []


def test_a_completed_role_answers_with_both_spans():
    document = reading("continuation_generic_reference")
    found = matches(document, ["event:0", "destination", "?x"])
    assert len(found) == 1
    binding, refs, _ = found[0]
    assert binding["?x"] == "이수진"
    assert refs[0]["proof"], "a completed role answers with its proof"
    assert len(refs[0]["spans"]) == 2


def test_an_identity_question_reaches_the_entity_of_a_pointing_mention():
    document = reading("continuation_same_event")
    pointing = [item for item in document["mentions"] if item["surface"] == "그 부품"][0]
    entity = _values(document, [pointing["id"], "mention_of", "?x"])
    assert len(entity) == 1
    names = _values(document, [entity[0], "name", "?x"])
    assert "부품" in names and "그 부품" in names


def test_a_rule_can_be_passed_through_to_the_existing_engine():
    """Transport, not a new search: a Horn rule still runs in the old engine."""
    document = reading("named_event_reference")
    rule = {"id": "rule:control", "version": 1,
            "head": ["?e", "has_verification", "yes"],
            "body": [["?e", "verified_by", "?c"]]}
    world = search_rows(document, ["event:0", "has_verification", "yes"], rules=[rule])
    assert world["matches"]
    assert world["complete"] is True


def test_the_search_is_given_only_rows_and_provenance():
    document = reading("active_transfer")
    facts, sources = project_rows(document)
    assert len(facts) == len(document["rows"])
    for source in sources:
        assert set(source) >= {"row", "spans", "claim", "scope_kind", "layer"}


LONG_DOCUMENT = (
    "경찰에 따르면 김민수가 부품을 이수진에게 전달했다. 그 부품은 창고로 전달되었다. "
    "생산 라인 책임자가 그 전달을 확인했다. 박지훈이 서류를 이수진에게 전달했다. "
    "검사관이 서류를 확인하지 않았다. 회사 발표에 따르면 부품이 김민수에게서 전달되었다."
)


def test_a_long_document_reports_the_search_limit_instead_of_hiding_it():
    """The engine's fact limit belongs to the engine and is reported, not papered over."""
    from experiments.graph_language_repair.core import read_text
    document = read_text(LONG_DOCUMENT)
    assert len(document["rows"]) > 64
    world = search_rows(document, ["?s", "?p", "?o"])
    assert world["complete"] is False
    assert world["reason"] == "graph_limit"


def test_an_incomplete_world_does_not_hand_back_an_exact_answer():
    """No exact answer out of truncated evidence; the reason is carried."""
    from experiments.graph_language_repair.core import IncompleteSearch, read_text
    document = read_text(LONG_DOCUMENT)
    try:
        matches(document, ["?e", "?p", "?x"])
    except IncompleteSearch as error:
        assert error.reason == "graph_limit"
        assert error.world["complete"] is False
    else:
        raise AssertionError("an incomplete world must not authorise an exact answer")
    opted_in = matches(document, ["?e", "?p", "?x"], require_complete=False)
    assert opted_in, "a caller may still opt in and take responsibility"


def test_identical_triples_become_one_fact_with_every_source_kept():
    """A9: repeated copies of one triple must not reach the engine as rivals."""
    from experiments.graph_language_repair.core import read_text
    document = read_text("김민수가 부품을 전달했다. 김민수가 서류를 전달했다.")
    facts, sources = project_rows(document)
    assert len(facts) < len(document["rows"])
    keys = [(tuple(fact["triple"]), fact["polarity"]) for fact in facts]
    assert len(keys) == len(set(keys)), "no triple is projected twice"
    merged = [source for source in sources if len(source["rows"]) > 1]
    assert merged, "the control must exercise merging"
    for source in merged:
        assert len(source["spans"]) >= len(source["rows"]), "every source span is kept"
        assert source["claims"] and source["readings"]
    assert search_rows(document, ["?s", "?p", "?o"])["complete"] is True


def test_merging_keeps_a_projection_inside_the_engine_support_limit():
    """A9 directly: many copies of one triple would otherwise be support_limit."""
    from marco.reasoning import relation_hypotheses
    document = reading("active_transfer")
    template = [row for row in document["rows"] if row["layer"] == "content"][0]
    copies = []
    for index in range(relation_hypotheses._SUPPORT_LIMIT * 4):
        copy = dict(template)
        copy["id"] = "row:copy%d" % index
        copy["reading"] = "reading:%d" % index
        copies.append(copy)
    facts, sources = project_rows(document, rows=copies)
    assert len(facts) == 1, "every copy is one fact"
    assert len(sources[0]["rows"]) == len(copies), "every copy is kept as a source"
    world = search_rows(document, list(template["triple"]), rows=copies)
    assert world["complete"] is True
    assert world["reason"] is None


def test_a_denial_is_never_merged_into_its_assertion():
    from experiments.graph_language_repair.core import read_text
    document = read_text("김과장이 부품을 전달했다. 검사관이 부품을 확인하지 않았다.")
    facts, _ = project_rows(document)
    polarities = {}
    for fact in facts:
        polarities.setdefault(tuple(fact["triple"]), set()).add(fact["polarity"])
    assert any(len(value) == 1 for value in polarities.values())
    negative = [fact for fact in facts if fact["polarity"] is False]
    assert negative, "the negated action must survive as its own fact"


def test_support_refs_come_from_the_proof_bundles():
    """Review 7: evidence is resolved through premise_fact_ids, not a string prefix."""
    from experiments.graph_language_repair.core import read_text
    document = read_text("가람이 책을 나래에게 전달했다.")
    world = search_rows(document, ["event:0", "actor", "?x"])
    support = world["matches"][0]["support_ids"][0]
    bundles = [bundle for group in world["proof_bundles"]
               for bundle in group["bundles"] if bundle["id"] == support]
    assert bundles and bundles[0]["premise_fact_ids"]
    binding, refs, _ = matches(document, ["event:0", "actor", "?x"])[0]
    premises = {item["premise_id"] for item in world["fact_sources"]
                if item["source_ref"] in refs}
    assert premises == set(bundles[0]["premise_fact_ids"])


def test_search_rows_always_reports_completeness_and_never_raises():
    """A9 / review 7: an engine limit is reported, not raised and not hidden."""
    from experiments.graph_language_repair.core import read_text
    for document in (reading("active_transfer"), read_text(LONG_DOCUMENT)):
        world = search_rows(document, ["?s", "?p", "?o"])
        assert "complete" in world and "reason" in world
        assert world["assembled"] is True
        assert isinstance(world["complete"], bool)


def test_a_narrowed_projection_of_a_long_document_is_complete():
    from experiments.graph_language_repair.core import read_text, select_rows
    document = read_text(LONG_DOCUMENT)
    rows = select_rows(document, predicates={"actor", "object", "destination", "origin"})
    assert 0 < len(rows) <= 64
    world = search_rows(document, ["?e", "actor", "?x"], rows=rows)
    assert world["complete"] is True
    found = matches(document, ["?e", "actor", "?x"], rows=rows)
    assert {binding["?x"] for binding, _, _ in found} == {"김민수", "박지훈"}
    assert len(found) == len({binding["?e"] for binding, _, _ in found})


def test_a_narrowed_projection_can_select_by_scope():
    from experiments.graph_language_repair.core import read_text, select_rows
    document = read_text(LONG_DOCUMENT)
    reported = select_rows(document, scope_kinds={"reported_claim", "attribution"},
                           layers={"content"})
    assert reported
    for row in reported:
        assert row["claim"] != "claim:0"
    direct = select_rows(document, scope_kinds={"direct_text"}, layers={"content"})
    for row in direct:
        assert row["claim"] == "claim:0"


def test_selection_filters_rows_and_invents_nothing():
    from experiments.graph_language_repair.core import select_rows
    document = reading("active_transfer")
    assert select_rows(document) == document["rows"]
    assert select_rows(document, subjects={"event:0"}) == [
        row for row in document["rows"] if row["triple"][0] == "event:0"]
    assert select_rows(document, predicates={"nothing_declared"}) == []


def test_direct_query_is_invariant_under_unrelated_document_extension():
    from experiments.graph_language_repair.core import read_text
    first = "세린이 도면을 분류했다."
    long_text = first + " 나린이 부품을 조립했다. 하린이 서류를 보관했다. 다린이 안내문을 배포했다. 예린이 장부를 정리했다."
    isolated, longer = read_text(first), read_text(long_text)
    query = ["?event", "actor", "세린"]
    small, large = search_rows(isolated, query), search_rows(longer, query)
    assert len(longer["rows"]) > 64 and longer["limits"]["complete"] is True
    assert small["complete"] is True and large["complete"] is True
    assert [item["triple"] for item in small["matches"]] == [item["triple"] for item in large["matches"]]
    projection = large["projection"]
    assert projection["kind"] == "direct_query" and projection["all_matching_rows_included"]
    assert not projection["whole_reading_included"] and projection["projected_rows"] < projection["input_rows"]


def test_direct_projection_keeps_denials_and_all_rival_sources():
    from experiments.graph_language_repair.core import read_text
    denied = read_text("가람이 책을 받지 않았다.")
    action = denied["events"][0]["action"]
    world = search_rows(denied, ["?event", "action", action])
    assert world["complete"] is True
    assert any(source["original_fact"]["polarity"] is False for source in world["fact_sources"])
    rivals = read_text("서진이 전화로 소식을 전달했다.")
    world = search_rows(rivals, ["?event", "actor", "서진"])
    assert len(world["matches"]) == 2
    refs = [item["source_ref"] for item in world["fact_sources"]]
    assert {ref["reading"] for ref in refs} == {item["id"] for item in rivals["readings"]}


def test_direct_projection_preserves_completion_proof_and_external_dependencies():
    document = reading("continuation_generic_reference")
    found = matches(document, ["event:0", "destination", "?x"])
    ref = found[0][1][0]
    proof = next(item for item in document["proofs"] if item["id"] == ref["proof"])
    row_ids = {item["id"] for item in document["rows"]}
    assert set(ref["depends_on"]) <= row_ids and len(ref["spans"]) == 2
    assert proof["kind"] == "role_completion" and set(proof["rows"]) <= row_ids


def test_rule_queries_use_full_input_and_can_derive_across_predicates():
    document = reading("named_event_reference")
    rule = {"id": "rule:cross_predicate", "version": 1,
            "head": ["?e", "has_verification", "yes"],
            "body": [["?e", "verified_by", "?c"]]}
    world = search_rows(document, ["event:0", "has_verification", "yes"], rules=[rule])
    assert world["complete"] is True and world["matches"]
    assert world["projection"]["kind"] == "full_input"
    assert world["projection"]["input_rows"] == world["projection"]["projected_rows"]
    assert not world["projection"]["all_matching_rows_included"]


def test_too_many_relevant_facts_still_reports_native_limit():
    document = {"rows": [{"id": "row:%d" % i, "triple": ["event:%d" % i, "actor", "same"],
                          "polarity": True, "claim": "claim:0", "spans": [[0, 1]]}
                         for i in range(65)], "limits": {"complete": True}}
    world = search_rows(document, ["?e", "actor", "same"])
    assert world["complete"] is False and world["reason"] == "graph_limit"
    assert world["projection"]["projected_facts"] == 65


def test_direct_projection_resolves_inherited_scope_proof_from_full_reading():
    document = reading("inherited_attribution")
    found = matches(document, ["?event", "inherited_scope", "?claim"])
    assert found
    source = found[0][1][0]
    proof = next(item for item in document["proofs"] if item["id"] == source["proof"])
    assert proof["kind"] == "scope_inheritance" and len(proof["spans"]) == 2
    assert source["row"] in proof["rows"]
    world = search_rows(document, ["?event", "inherited_scope", "?claim"])
    assert world["complete"] is True and not world["projection"]["whole_reading_included"]
