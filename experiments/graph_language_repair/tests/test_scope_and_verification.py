# -*- coding: utf-8 -*-
"""Attribution, verification, and the line between them.

Repairs under test: inherited attribution after attachment, which the saved
diagnosis says was never established, and the checker route that reached
object binding zero times (CORE-STATUS F5, F7, F8).
"""
from experiments.graph_language_repair.core import read_text
from experiments.graph_language_repair.tests.controls import CONTROLS
from experiments.graph_language_repair.tests.helpers import (claim_of, claims_of_kind,
                                                             events, hypotheses, reading,
                                                             role_values, rows)


def _content_rows(document, event):
    return [row for row in document["rows"]
            if row["layer"] == "content" and row["triple"][0] == event]


def test_every_row_has_a_claim_and_a_span():
    """C4 across the control set."""
    for name in CONTROLS:
        document = reading(name)
        known = {claim["id"] for claim in document["claims"]}
        for row in document["rows"]:
            assert row["claim"] in known, (name, row)
            assert row["spans"], (name, row)


def test_a_prefix_report_frame_scopes_the_clause_and_names_the_reporter():
    document = reading("report_prefix")
    reported = claims_of_kind(document, "reported_claim")
    assert len(reported) == 1
    assert reported[0]["reporter"] == "경찰"
    assert reported[0]["reporter_mention"]
    assert events(document)[0]["claim"] == reported[0]["id"]
    for row in _content_rows(document, "event:0"):
        assert row["claim"] == reported[0]["id"]
        assert row["scope_kind"] == "reported_claim"


def test_a_suffix_report_frame_keeps_the_reporter_out_of_the_inner_clause():
    """F6: a reported subject span used to reach back into the attribution prefix."""
    document = reading("report_suffix")
    reported = claims_of_kind(document, "reported_claim")[0]
    assert reported["reporter"] == "경찰"
    actor = [item for item in document["roles"] if item["role"] == "actor"][0]
    assert actor["value"] == "김민수"
    assert actor["value_span"][0] > reported["reporter_span"][1]


def test_a_speech_noun_in_the_reporter_makes_it_an_attribution():
    document = reading("attribution_speech_noun")
    assert [claim["kind"] for claim in document["claims"]] == ["direct_text", "attribution"]
    assert claims_of_kind(document, "attribution")[0]["reporter"] == "회사 발표"


def test_a_report_is_never_attributed_to_the_direct_scope():
    """C5: the evidence attaches to the claim it was stated in."""
    document = reading("report_prefix")
    for row in _content_rows(document, "event:0"):
        assert row["claim"] != "claim:0"


def test_meta_rows_stay_in_the_direct_scope():
    document = reading("report_prefix")
    for row in document["rows"]:
        if row["layer"] == "meta":
            assert row["claim"] == "claim:0"


def test_a_reported_check_verifies_nothing():
    document = reading("reported_check_only")
    assert rows(document, predicate="verified_by") == []
    assert rows(document, predicate="verified_by_candidate") == []
    rejected = hypotheses(document, "verification", "rejected")
    assert rejected
    assert any("forbidden_source_scope" in reason for reason in rejected[0]["blocked_by"])


def test_a_direct_check_sharing_only_the_object_stays_a_candidate():
    document = reading("report_then_check")
    assert rows(document, predicate="verified_by") == []
    assert rows(document, "event:0", "verified_by_candidate", "event:1")
    assert hypotheses(document, "verification", "candidate")


def test_a_later_check_does_not_turn_a_report_into_truth():
    document = reading("report_then_check")
    reported = claims_of_kind(document, "reported_claim")[0]
    for row in _content_rows(document, "event:0"):
        assert row["claim"] == reported["id"]
    assert claim_of(document, reported["id"])["kind"] == "reported_claim"


def test_a_named_event_reference_accepts_the_verification():
    document = reading("named_event_reference")
    accepted = hypotheses(document, "verification", "accepted")
    assert len(accepted) == 1
    assert rows(document, "event:0", "verified_by", "event:1")
    assert rows(document, "event:1", "checks", "event:0")


def test_a_checking_event_binds_a_multiword_actor_and_its_object():
    document = reading("multiword_checker")
    assert role_values(document, "event:1", "checking_actor") == ["생산 라인 책임자"]
    assert role_values(document, "event:1", "checking_object") == ["그 전달"]
    assert hypotheses(document, "verification", "accepted")


def test_a_negated_check_did_not_happen_and_verifies_nothing():
    """A1/A3: a check the text negates is a hold, not a negative result."""
    document = reading("negative_check")
    occurred = rows(document, "event:1", "checking_occurred")
    assert [row["triple"][2] for row in occurred] == ["not_performed"]
    assert occurred[0]["polarity"] is True, "the occurrence must be queryable"
    outcome = rows(document, "event:1", "checking_outcome")
    assert [row["triple"][2] for row in outcome] == ["unstated"]
    assert "denied" not in {row["triple"][2] for row in outcome}
    assert rows(document, "event:0", "verified_by", "event:1") == []
    assert rows(document, "event:0", "verified_by_candidate", "event:1") == []
    rejected = hypotheses(document, "verification", "rejected")
    assert rejected
    assert any(reason.startswith("check_did_not_occur")
               for reason in rejected[0]["blocked_by"])


def test_the_negated_action_keeps_its_own_polarity_channel():
    document = reading("negative_check")
    action = rows(document, "event:1", "action", "action:check")
    assert action and action[0]["polarity"] is False
    assert [row["triple"][2] for row in rows(document, "event:1", "polarity")] == ["false"]


def test_a_bare_positive_check_states_no_result():
    """The coordinator's qualification: 확인했다 says a check happened, not what it found."""
    document = reading("named_event_reference")
    assert [row["triple"][2] for row in rows(document, "event:1", "checking_occurred")] \
        == ["occurred"]
    assert [row["triple"][2] for row in rows(document, "event:1", "checking_outcome")] \
        == ["unstated"]
    assert rows(document, "event:0", "verified_by", "event:1"), "occurrence still attaches"
    assert [row["triple"][2] for row in rows(document, "event:0", "independent_result")] \
        == ["unstated"]


def test_a_declared_result_form_is_what_makes_a_result():
    positive = read_text("김과장이 부품을 전달했다. 검사관이 그 전달을 사실로 확인했다.")
    negative = read_text("김과장이 부품을 전달했다. 검사관이 그 전달을 허위로 확인했다.")
    assert [row["triple"][2] for row in rows(positive, "event:1", "checking_outcome")] \
        == ["confirmed"]
    assert [row["triple"][2] for row in rows(negative, "event:1", "checking_outcome")] \
        == ["denied"]
    assert [row["triple"][2] for row in rows(positive, "event:0", "independent_result")] \
        == ["confirmed"]
    assert [row["triple"][2] for row in rows(negative, "event:0", "independent_result")] \
        == ["denied"]
    for document in (positive, negative):
        assert [row["triple"][2] for row in rows(document, "event:1", "checking_occurred")] \
            == ["occurred"]


def test_a_direct_check_may_target_an_event_introduced_in_a_report():
    """An explicit direct result can support a reported target while preserving scope."""
    document = read_text("보고서에 따르면 김과장이 부품을 전달했다. 검사관이 그 전달을 사실로 확인했다.")
    reported = claims_of_kind(document, "attribution")[0]
    assert rows(document, "event:0", "action", "action:transfer")[0]["claim"] == reported["id"]
    assert rows(document, "event:0", "verified_by", "event:1"), "the check is not banned"
    assert [row["triple"][2] for row in rows(document, "event:1", "checks_target_scope")] \
        == ["attribution"]
    assert [row["triple"][2] for row in rows(document, "event:0", "independent_result")] \
        == ["confirmed"], "a directly stated result is independent of target introduction"
    assert [row["triple"][2] for row in rows(document, "event:1", "checking_outcome")] \
        == ["confirmed"], "what the check itself found is still recorded"
    accepted = hypotheses(document, "verification", "accepted")[0]
    assert not accepted["blocked_by"]
    assert accepted["target_scope"] == "attribution"


def test_the_target_scope_of_a_direct_target_is_recorded_too():
    document = reading("named_event_reference")
    assert [row["triple"][2] for row in rows(document, "event:1", "checks_target_scope")] \
        == ["direct_text"]


def test_with_no_checking_action_there_is_no_verification_row():
    document = reading("no_check_at_all")
    assert rows(document, predicate="checking_outcome") == []
    assert rows(document, predicate="checking_occurred") == []
    assert rows(document, predicate="verified_by") == []
    assert rows(document, predicate="verified_by_candidate") == []
    assert hypotheses(document, "verification") == []


def test_a_checking_clause_gets_its_own_verification_eligible_claim():
    document = reading("multiword_actor")
    kinds = [claim["kind"] for claim in document["claims"]]
    assert "checking_action" in kinds
    checking = claims_of_kind(document, "checking_action")[0]
    assert checking["inherits_from"] == "claim:0"
    assert events(document)[0]["claim"] == checking["id"]


def test_an_accepted_link_makes_the_continuation_inherit_the_reported_claim():
    """C5 plus C7: the attribution travels, the report is not promoted."""
    document = reading("inherited_attribution")
    reported = claims_of_kind(document, "reported_claim")[0]
    second = [event for event in document["events"] if event["id"] == "event:1"][0]
    assert second["claim"] == "claim:0", "where it was stated is kept"
    assert second["inherited_claim"] == reported["id"]
    for row in _content_rows(document, "event:1"):
        assert row["claim"] == reported["id"]
    inherited = rows(document, "event:1", "inherited_scope", reported["id"])
    assert inherited and inherited[0]["proof"]
    proof = [item for item in document["proofs"] if item["id"] == inherited[0]["proof"]][0]
    assert proof["kind"] == "scope_inheritance"
    assert len(proof["spans"]) == 2


def test_inheritance_never_runs_on_an_unaccepted_link():
    document = read_text("경찰에 따르면 부품이 이수진에게 전달되었다. 해당 항목은 박지훈에게 전달되었다.")
    assert hypotheses(document, "event_link", "accepted") == []
    assert rows(document, predicate="inherited_scope") == []
    for event in document["events"]:
        assert event["inherited_claim"] is None


def test_a_reported_claim_is_never_promoted_to_direct_text():
    document = reading("inherited_attribution")
    for claim in document["claims"]:
        if claim["kind"] == "direct_text":
            assert claim["inherits_from"] is None
    direct = [event for event in document["events"] if event["inherited_claim"]]
    assert direct, "the control must exercise inheritance"
    for event in direct:
        assert claim_of(document, event["inherited_claim"])["kind"] != "direct_text"


def test_the_reporter_is_reachable_as_rows_for_a_source_question():
    """F8: no ordered interrogative gate — the reporter is just rows."""
    document = reading("report_suffix")
    reported = claims_of_kind(document, "reported_claim")[0]
    assert rows(document, reported["id"], "reporter", "경찰")
    assert rows(document, reported["id"], "scope_kind", "reported_claim")
    assert rows(document, reported["id"], "frame", "frame:report_suffix")
    assert rows(document, "event:0", "in_claim", reported["id"])


def test_bound_results_preserve_conflict_and_genuine_instrument():
    conflict = read_text("감사팀이 그 전달을 사실로 허위로 확인했다.")
    event = conflict["events"][0]
    assert event["checking_result"] == "conflicting"
    assert {item["value"] for item in event["result_form_hits"]} == {"confirmed", "denied"}
    assert any(item["kind"] == "competing_result_forms" for item in conflict["contradictions"])
    instrument = read_text("감사팀이 기기로 그 전달을 확인했다.")
    assert any(role["role"] == "instrument" and role["value"] == "기기" for role in instrument["roles"])
    assert instrument["events"][0]["checking_result"] == "unstated"


def test_action_type_identifies_negated_action_without_asserting_occurrence():
    document = read_text("가람이 책을 받지 않았다.")
    event = document["events"][0]
    action = rows(document, event["id"], "action", event["action"])[0]
    kind = rows(document, event["id"], "action_type", event["action"])[0]
    assert action["polarity"] is False and kind["polarity"] is True
    assert kind["layer"] == "meta" and kind["spans"] == [event["action_span"]]


def test_result_row_spans_and_independent_result_proof_follow_actual_forms():
    for form, expected in (("사실로", "confirmed"), ("허위로", "denied"),
                           ("사실로 허위로", "conflicting"), ("", "unstated")):
        text = "서진이 부품을 전달했다. 감사팀이 그 전달을 " + (form + " " if form else "") + "확인했다."
        document = read_text(text)
        outcome = rows(document, "event:1", "checking_outcome")[0]
        assert outcome["triple"][2] == expected
        cited = {text[start:end] for start, end in outcome["spans"]}
        assert "확인했다" in cited
        for phrase in form.split():
            assert phrase in cited
        result = rows(document, "event:0", "independent_result")[0]
        assert result["triple"][2] == ("unstated" if expected == "conflicting" else expected)
        by_id = {row["id"]: row for row in document["rows"]}
        dependencies = [by_id[key] for key in result["depends_on"]]
        assert outcome["id"] in result["depends_on"]
        assert any(row["triple"][1] == "checks" for row in dependencies)
        assert any(row["triple"][1] == "action" and row["triple"][0] == "event:0" for row in dependencies)
        proof = next(proof for proof in document["proofs"] if proof["id"] == result["proof"])
        assert set(result["depends_on"]) <= set(proof["rows"])
        assert set(map(tuple, outcome["spans"])) <= set(map(tuple, result["spans"]))


def test_explicit_result_scope_is_preserved_for_reported_check_and_target():
    target = read_text("보고서에 따르면 서진이 부품을 전달했다. 감사팀이 그 전달을 사실로 확인했다.")
    target_outcome = rows(target, "event:1", "checking_outcome")[0]
    assert target_outcome["triple"][2] == "confirmed"
    assert rows(target, "event:0", "independent_result")[0]["triple"][2] == "confirmed"
    assert rows(target, "event:0", "action")[0]["claim"] != "claim:0"
    check = read_text("서진이 부품을 전달했다. 보고서에 따르면 감사팀이 그 전달을 사실로 확인했다.")
    check_outcome = rows(check, "event:1", "checking_outcome")[0]
    assert check_outcome["triple"][2] == "confirmed"
    assert check_outcome["claim"] != "claim:0"
    assert not rows(check, "event:0", "independent_result")
