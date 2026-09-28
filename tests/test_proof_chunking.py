from proof_chunking import evaluate, invalidate, propose
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


KG = "graphs/graph_일상추론.kg"


def _rules():
    return [
        {"id": "r1", "version": 1, "body": [["?x", "a", "?y"]], "head": ["?x", "b", "?y"]},
        {"id": "r2", "version": 1, "body": [["?x", "b", "?y"]], "head": ["?x", "c", "?y"]},
        {"id": "r3", "version": 1, "body": [["?x", "c", "?y"]], "head": ["?x", "d", "?y"]},
    ]


def test_shortcut_reduces_real_rule_scans_but_keeps_the_original_proof_chain():
    rules, facts, target = _rules(), [{"triple": ["n", "a", "m"], "evidence": {}}], ("n", "d", "m")
    shortcut = propose(rules, ["r1", "r2", "r3"])
    assert shortcut is not None
    shortcut["active"] = True
    result = evaluate(facts, rules, shortcut, target)
    assert result["used"] and target in result["facts"]
    assert result["accelerated_metrics"]["rule_scans"] < result["original_metrics"]["rule_scans"]
    # Validation runs both closures; only repeated use may claim the saving.
    assert result["total_metrics"]["rule_scans"] > result["original_metrics"]["rule_scans"]
    repeated = evaluate(facts, rules, shortcut, target)
    assert repeated["total_metrics"]["rule_scans"] < repeated["original_metrics"]["rule_scans"]
    assert [row["id"] for row in result["shortcut"]["source"]] == ["r1", "r2", "r3"]


def test_shortcut_keeps_intermediate_facts_and_an_independent_branch():
    rules, facts = _rules(), [{"triple": ["n", "a", "m"], "evidence": {}}]
    rules.append({"id": "branch", "version": 1, "body": [["?x", "b", "?y"]],
                  "head": ["?x", "independent", "?y"]})
    shortcut = propose(rules, ["r1", "r2", "r3"]); shortcut["active"] = True
    result = evaluate(facts, rules, shortcut, ("n", "d", "m"))
    assert result["used"]
    assert {("n", "b", "m"), ("n", "c", "m"), ("n", "d", "m"),
            ("n", "independent", "m")} <= set(result["facts"])


def test_changed_rule_or_counterexample_disables_shortcut_and_returns_to_original_path():
    rules, facts, target = _rules(), [{"triple": ["n", "a", "m"], "evidence": {}}], ("n", "d", "m")
    shortcut = propose(rules, ["r1", "r2", "r3"]); shortcut["active"] = True
    changed = [dict(row) for row in rules]; changed[1]["version"] = 2
    assert not evaluate(facts, changed, shortcut, target)["used"]
    invalidate(shortcut, "counterexample")
    result = evaluate(facts, rules, shortcut, target)
    assert not result["used"] and target in result["facts"]
    assert result["shortcut"]["invalidation_reason"] == "counterexample"


def test_validated_shortcut_is_available_to_the_parser_common_rule_selector(tmp_path):
    from alma.runtime import AlmaRuntime
    from relational_semantics import RelationalParser

    rules = _rules()[:2]
    facts = [{"triple": ["n", "a", "m"], "evidence": {}}]
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.turn("첫째 독립 관찰이다.", KG)
    first_observation = runtime.snapshot()["event_index"][-1]["id"]
    runtime.turn("둘째 독립 관찰이다.", KG)
    second_observation = runtime.snapshot()["event_index"][-1]["id"]
    proposal = runtime.propose_proof_shortcut(rules, ["r1", "r2"], observation_id=first_observation)
    runtime.propose_proof_shortcut(rules, ["r1", "r2"], observation_id=second_observation)
    runtime.activate_proof_shortcut(proposal["id"])
    runtime.run_proof_shortcut(proposal["id"], facts, rules, ["n", "c", "m"])
    parser = RelationalParser()
    parser.data = {"rules": rules, "mutable_predicates": [], "numeric_updates": {}}
    parser.rule_selector = runtime._shortcut_rules_for_facts
    selected = parser._inference_rules(facts)
    assert {row["id"] for row in selected} == {"r1", proposal["rules"][1]["id"]}
    changed_facts = [{"triple": ["other", "a", "m"], "evidence": {}}]
    assert {row["id"] for row in parser._inference_rules(changed_facts)} == {"r1", "r2"}
