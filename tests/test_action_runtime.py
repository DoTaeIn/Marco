"""The learned-action executor is a shared semantic path, not a verb table."""

from marco.reasoning.actions import SCHEMA, execute
from marco.reasoning.context import ReasoningContext
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


KG = "graphs/graph_일상추론.kg"


def _rule(text):
    context = ReasoningContext()
    parser = context._parser()
    declared = parser.parse(text, partial=True)["정의"][0]
    rule = context._rule(parser, declared, {})
    return parser, {**rule, "프로그램": {**rule["프로그램"], "definition_version": 0}}


def test_natural_definition_compiles_to_a_versioned_role_program():
    parser, rule = _rule("나누다는 상대에게 구슬의 절반을 주는 것이다.")
    program = rule["프로그램"]
    assert program["schema"] == SCHEMA
    assert program["action"] == "나누"
    assert program["definition_version"] == 0
    assert program["signature"]["open_roles"] == {"giver": "은", "taker": "에게"}
    assert program["steps"] == [
        {"op": "lookup", "into": "basis", "missing_reason": "basis",
         "subject": ["$giver", "$item"], "predicate": "count"},
        {"op": "compute", "into": "n", "operator": "/", "left": "$basis", "right": "2"},
        {"op": "emit", "triples": [
            [["$giver", "$item"], "count_remove", "$n"],
            [["$taker", "$item"], "count_add", "$n"],
        ]},
    ]
    # The language pack, rather than this test or runtime, declares the word
    # '절반' and its operation.
    assert parser.quantities["절반"]["연산"] == "/"


def test_same_program_binds_roles_reads_state_and_calculates_for_new_values():
    parser, rule = _rule("나누다는 상대에게 구슬의 절반을 주는 것이다.")
    for initial, expected in ((8, "4"), (10, "5")):
        result = execute(
            rule["프로그램"], {"은": "민수", "에게": "지연"},
            prior_facts=[{"triple": ["민수 구슬", "count", str(initial)], "evidence": {}}],
            quantities=parser.quantities, mutable_predicates=parser.data["mutable_predicates"],
            numeric_updates=parser.data["numeric_updates"],
        )
        assert result["reason"] is None
        assert result["bindings"] == {"basis": str(initial), "n": expected}
        assert result["facts"] == [["민수 구슬", "count_remove", expected],
                                   ["지연 구슬", "count_add", expected]]


def test_natural_relative_quantity_lookup_uses_the_declared_source_role():
    definition = "나누다는 내가 상대의 구슬 절반을 사람에게 주는 것이다."
    for source_amount, expected in ((8, ("16개입니다.", "7개입니다.")),
                                    (10, ("15개입니다.", "8개입니다."))):
        context = ReasoningContext()
        for said in (definition,
                     "민수 구슬은 20개 있다. 지연 구슬은 %d개 있다. 수진 구슬은 3개 있다." % source_amount,
                     "민수가 지연의 구슬을 수진에게 나눴다."):
            assert context.turn(said, KG)["status"] == "observed"
        assert context.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == expected[0]
        assert context.turn("지금 수진 구슬은 몇 개야?", KG)["answer"] == expected[1]


def test_missing_or_conflicting_roles_never_emit_a_partial_state_change():
    parser, rule = _rule("베풀다는 상대에게 구슬 2개를 주는 것이다.")
    missing = execute(rule["프로그램"], {"에게": "지연"}, quantities=parser.quantities,
                      mutable_predicates=parser.data["mutable_predicates"],
                      numeric_updates=parser.data["numeric_updates"])
    assert missing["facts"] == []
    assert missing["missing"] == {"giver": "은"}

    _parser, fixed = _rule("숨기다는 물건을 서랍으로 옮기는 것이다.")
    conflict = execute(fixed["프로그램"], {"은": "하린", "을": "열쇠", "으로": "금고"},
                       quantities=parser.quantities, mutable_predicates=parser.data["mutable_predicates"],
                       numeric_updates=parser.data["numeric_updates"])
    assert conflict["facts"] == []
    assert conflict["conflicts"]


def test_learned_hypothesis_uses_the_action_program_without_writing_real_state():
    context = ReasoningContext()
    for said in ("나누다는 상대에게 구슬의 절반을 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다."):
        assert context.turn(said, KG)["status"] == "observed"

    projected = context.turn("만약 민수가 지연에게 나눴으면 지금 민수 구슬은 몇 개야?", KG)
    assert projected["answer"] == "4개입니다."
    action = next(step for step in projected["transitions"]
                  if step.get("operation") == "hypothetical_action")
    assert action["event"]["schema"] == "nai-action-event-v1"
    assert action["event"]["definition_version"] == 0
    assert action["bindings"] == {"basis": "8", "n": "4"}
    assert context.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."


def test_actual_learned_effect_keeps_the_same_event_envelope_as_a_hypothesis():
    context = ReasoningContext()
    for said in ("나누다는 상대에게 구슬의 절반을 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
                 "민수가 지연에게 나눴다."):
        context.turn(said, KG)
    facts, _definitions, _pending, _read = context._cached_replay(
        context._parser(), context.observations, context.fills)
    emitted = next(fact for fact in facts if fact["triple"] == ["민수 구슬", "count_remove", "4"])
    event = emitted["evidence"]["action_event"]
    assert event["schema"] == "nai-action-event-v1"
    assert event["action"] == "나누"
    assert event["definition_version"] == 0
    assert event["polarity"] is True and event["modality"] == "asserted"
    assert event["roles"] == {"은": "민수", "에게": "지연"}

    restored = ReasoningContext()
    restored.restore(context.snapshot())
    restored_facts, _definitions, _pending, _read = restored._cached_replay(
        restored._parser(), restored.observations, restored.fills)
    restored_event = next(fact for fact in restored_facts
                          if fact["triple"] == ["민수 구슬", "count_remove", "4"])["evidence"]["action_event"]
    assert restored_event["id"] == event["id"]
    assert restored_event["definition_version"] == event["definition_version"]


def test_quantity_location_and_social_hypotheses_share_temporary_event_contracts():
    cases = [
        (("베풀다는 상대에게 구슬 2개를 주는 것이다.",
          "민수 구슬은 8개 있다. 지연 구슬은 3개 있다."),
         "만약 민수가 지연에게 베풀었으면 지금 지연 구슬은 몇 개야?",
         "지금 지연 구슬은 몇 개야?", "5개입니다.", "3개입니다.", "Quantity"),
        (("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.", "하린은 서랍에 있었다."),
         "만약 하린이 공책을 모았으면 지금 공책은 어디에 있어?",
         "지금 공책은 어디에 있어?", "서랍에 있습니다.", None, "Location"),
        (("약속하다는 내가 상대에게 약속을 만드는 것이다.",),
         "만약 민수가 지연에게 약속했으면 민수와 지연의 약속 상태가 어때?",
         "민수와 지연의 약속 상태가 어때?", "active입니다.", None, "Social"),
    ]
    for setup, question, actual_question, expected, actual, domain in cases:
        context = ReasoningContext()
        for said in setup:
            context.turn(said, KG)
        projected = context.turn(question, KG)
        event = next(step["event"] for step in projected["transitions"]
                     if step.get("operation") == "hypothetical_action")
        assert projected["answer"] == expected
        assert event["schema"] == "nai-action-event-v1"
        assert event["modality"] == "hypothetical"
        assert event["program"]["domain"] == domain
        actual_result = context.turn(actual_question, KG)
        if actual:
            assert actual_result["answer"] == actual
        else:
            assert actual_result["status"] == "unresolved"


def test_natural_composition_preserves_a_typed_learned_action_call_edge():
    context = ReasoningContext()
    context.turn("베풀다는 상대에게 구슬 2개를 주는 것이다.", KG)
    context.turn("맞바꾸다는 내가 상대에게 베풀고, 상대가 나에게 단추 한 개를 주는 것이다.", KG)
    _facts, definitions, _pending, _read = context._cached_replay(
        context._parser(), context.observations, context.fills)
    calls = definitions["맞바꾸"]["프로그램"]["calls"]
    assert calls and calls[0]["action"] == "베풀"
    assert calls[0]["definition_version"] == 0
    assert isinstance(calls[0]["role_slots"], dict) and isinstance(calls[0]["values"], dict)
    step = definitions["맞바꾸"]["프로그램"]["steps"][0]
    assert step["op"] == "call" and step["action"] == "베풀"
    assert step["definition_version"] == 0


def test_natural_composed_call_uses_its_saved_version_in_actual_and_hypothetical_execution():
    """A later definition cannot silently rewrite an earlier composed action."""
    setup = ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
             "맞바꾸다는 내가 상대에게 베풀고, 상대가 나에게 단추 한 개를 주는 것이다.",
             "베풀다는 상대에게 구슬 3개를 주는 것이다.",
             "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 민수 단추는 1개 있다. 지연 단추는 4개 있다.")
    actual = ReasoningContext()
    for said in setup:
        actual.turn(said, KG)
    actual.turn("민수가 지연에게 맞바꿨다.", KG)
    assert actual.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "6개입니다."

    assumed = ReasoningContext()
    for said in setup:
        assumed.turn(said, KG)
    projected = assumed.turn("만약 민수가 지연에게 맞바꿨으면 지금 민수 구슬은 몇 개야?", KG)
    assert projected["answer"] == "6개입니다."
    assert assumed.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."

    # An incomplete outer call may still have changed the caller's quantity.
    # Its nested effect must therefore block the old value rather than vanish
    # from the uncertainty footprint.
    incomplete = ReasoningContext()
    for said in setup:
        incomplete.turn(said, KG)
    assert incomplete.turn("지연에게 맞바꿨다.", KG)["status"] == "unresolved"
    assert incomplete.turn("지금 민수 구슬은 몇 개야?", KG)["status"] == "unresolved"


def test_correcting_a_referenced_definition_rebuilds_the_dependent_composed_action():
    context = ReasoningContext()
    for said in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "맞바꾸다는 내가 상대에게 베풀고, 상대가 나에게 단추 한 개를 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 민수 단추는 1개 있다. 지연 단추는 4개 있다.",
                 "민수가 지연에게 맞바꿨다."):
        context.turn(said, KG)
    assert context.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "6개입니다."
    changed = context.turn(
        "정정: 베풀다는 상대에게 구슬 2개를 주는 것이다. => 베풀다는 상대에게 구슬 4개를 주는 것이다.", KG)
    assert changed["status"] == "observed"
    assert context.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "4개입니다."


def test_negative_or_planned_completion_cannot_promote_an_open_event_to_actual():
    for completion in ("민수가 지연에게 베풀지 않았다.", "민수가 지연에게 베풀 예정이다."):
        context = ReasoningContext()
        for said in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                     "민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
                     "지연에게 베풀었다."):
            context.turn(said, KG)
        context.turn(completion, KG)
        result = context.turn("지금 민수 구슬은 몇 개야?", KG)
        assert result["status"] == "unresolved"
        assert result["answer"] != "6개입니다."


def test_structured_lookup_compute_condition_and_call_use_one_bounded_executor():
    def program(name, roles, steps):
        return {"schema": SCHEMA, "action": name, "definition_version": 1,
                "definition_evidence": {}, "references": {},
                "signature": {"role_slots": {}, "open_roles": roles, "fixed_values": {}},
                "calls": [], "steps": steps}

    # The first action finds a location instead of accepting a hard-coded
    # destination, then passes that value to its emitted effect.
    relocate = program("따라놓", {"item": "을", "other": "은"}, [
        {"op": "lookup", "into": "place", "subject": "$item", "predicate": "location"},
        {"op": "emit", "triples": [["$other", "location", "$place"]]},
    ])
    found = execute(relocate, {"을": "공책", "은": "연필"}, prior_facts=[
        {"triple": ["공책", "location", "서랍"], "evidence": {}}])
    assert found["facts"] == [["연필", "location", "서랍"]]
    assert found["bindings"] == {"place": "서랍"}

    # Calls reuse another program's role contract.  No action name is known by
    # the executor; only the supplied registry connects them.
    store = program("보관", {"item": "을", "place": "으로"}, [
        {"op": "emit", "triples": [["$item", "location", "$place"]]},
    ])
    prepare = program("준비", {"item": "을", "place": "으로"}, [
        {"op": "call", "action": "보관", "roles": {"을": "$item", "으로": "$place"}},
    ])
    called = execute(prepare, {"을": "공책", "으로": "가방"}, programs={"보관": store, "준비": prepare})
    assert called["facts"] == [["공책", "location", "가방"]]
    stale_prepare = {**prepare, "steps": [{"op": "call", "action": "보관",
                                              "definition_version": 9,
                                              "roles": {"을": "$item", "으로": "$place"}}]}
    unavailable = execute(stale_prepare, {"을": "공책", "으로": "가방"},
                          programs={"보관@1": store})
    assert unavailable["facts"] == [] and unavailable["reason"] == "unknown_call"
    extra = execute(store, {"을": "공책", "으로": "가방", "에게": "지연"})
    assert extra["facts"] == [] and extra["leftover"] == {"에게": "지연"}

    guarded = program("조건동작", {"item": "을"}, [
        {"op": "when", "fact": ["$item", "location", "서랍"]},
        {"op": "compute", "into": "n", "operator": "/", "left": "8", "right": "2"},
        {"op": "emit", "triples": [["$item", "count_add", "$n"]]},
    ])
    held = execute(guarded, {"을": "공책"}, prior_facts=[])
    assert held["facts"] == [] and held["reason"] == "condition_unknown"
    assert held["need"] == {"kind": "condition", "fact": ["공책", "location", "서랍"]}
    false = execute(guarded, {"을": "공책"}, prior_facts=[
        {"triple": ["공책", "location", "책상"], "evidence": {}}])
    assert false["facts"] == [] and false["reason"] == "condition_false"
    assert false["need"] is None

    # State reads use the effects of earlier program steps.  This is the
    # same ordered executor used by a learned multi-clause action, not a
    # separate location special case.
    ordered = program("차례", {"item": "을", "other": "은"}, [
        {"op": "emit", "triples": [["$item", "location", "서랍"]]},
        {"op": "lookup", "into": "place", "subject": "$item", "predicate": "location"},
        {"op": "emit", "triples": [["$other", "location", "$place"]]},
    ])
    ordered_result = execute(ordered, {"을": "공책", "은": "연필"})
    assert ordered_result["facts"] == [["공책", "location", "서랍"],
                                       ["연필", "location", "서랍"]]

    legacy_expression = program("옛수량", {"item": "을"}, [
        {"op": "emit", "triples": [["$item", "count_remove", "절반"]]},
    ])
    runtime_parser = ReasoningContext()._parser()
    rejected = execute(legacy_expression, {"을": "민수 구슬"}, quantities=runtime_parser.quantities,
                       prior_facts=[{"triple": ["민수 구슬", "count", "8"], "evidence": {}}],
                       mutable_predicates=runtime_parser.data["mutable_predicates"],
                       numeric_updates=runtime_parser.data["numeric_updates"])
    assert rejected["facts"] == [] and rejected["reason"] == "undeclared_state_value"

    loop = program("순환", {}, [{"op": "call", "action": "순환", "roles": {}}])
    limited = execute(loop, {}, programs={"순환": loop}, limit=2)
    assert limited["facts"] == [] and limited["reason"] == "call_limit"


def test_app_dialogue_uses_the_same_hypothetical_action_execution(tmp_path):
    """Natural language reaches the program through the public app entry."""
    from pathlib import Path
    import kgpack
    from views.kgpack_ui import AppState

    pack = tmp_path / "action-runtime.kgpack"
    kgpack.write_pack(pack, [Path(KG)] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    session = "action_runtime_dialogue"
    for said in ("나누다는 상대에게 구슬의 절반을 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다."):
        assert app.turn(said, session)["phase"] == "answer"
    projected = app.turn("만약 민수가 지연에게 나눴으면 지금 지연 구슬은 몇 개야?", session)
    assert projected["answer"]["answer"] == "7개입니다."
    actual = app.turn("지금 지연 구슬은 몇 개야?", session)
    assert actual["answer"]["answer"] == "3개입니다."


def test_app_dialogue_executes_a_naturally_composed_versioned_call_in_a_hypothesis(tmp_path):
    """The public app path does not replace learned calls with a JSON-only route."""
    from pathlib import Path
    import kgpack
    from views.kgpack_ui import AppState

    pack = tmp_path / "composed-action-runtime.kgpack"
    kgpack.write_pack(pack, [Path(KG)] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    session = "composed_action_runtime_dialogue"
    for said in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "맞바꾸다는 내가 상대에게 베풀고, 상대가 나에게 단추 한 개를 주는 것이다.",
                 "베풀다는 상대에게 구슬 3개를 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 민수 단추는 1개 있다. 지연 단추는 4개 있다."):
        assert app.turn(said, session)["phase"] == "answer"
    projected = app.turn("만약 민수가 지연에게 맞바꿨으면 지금 민수 구슬은 몇 개야?", session)
    assert projected["answer"]["answer"] == "6개입니다."
    assert app.turn("지금 민수 구슬은 몇 개야?", session)["answer"]["answer"] == "8개입니다."


def test_pack_declared_location_lookup_reuses_one_natural_definition_in_real_and_hypothetical_worlds():
    """A location is a state value, not a quantity-only special case."""
    definition = "모으다는 내가 있는 곳으로 물건을 옮기는 것이다."
    context = ReasoningContext()
    for said in (definition, "하린은 서랍에 있었다.", "도윤은 창고에 있었다.",
                 "하린이 공책을 모았다.", "도윤이 연필을 모았다."):
        context.turn(said, KG)
    assert context.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."
    assert context.turn("지금 연필은 어디에 있어?", KG)["answer"] == "창고에 있습니다."

    projected = ReasoningContext()
    for said in (definition, "하린은 서랍에 있었다."):
        projected.turn(said, KG)
    assumed = projected.turn("만약 하린이 공책을 모았으면 지금 공책은 어디에 있어?", KG)
    assert assumed["answer"] == "서랍에 있습니다."
    assert projected.turn("지금 공책은 어디에 있어?", KG)["status"] == "unresolved"

    missing = ReasoningContext()
    for said in ("공책은 책상에 있었다.", definition, "하린이 공책을 모았다."):
        outcome = missing.turn(said, KG)
    assert outcome["status"] == "unresolved"
    assert "현재 위치나 값" in outcome["answer"]
    unresolved = missing.turn("지금 공책은 어디에 있어?", KG)
    assert unresolved["status"] == "unresolved"
    assert unresolved["answer"] != "책상에 있습니다."


def test_role_completion_resumes_the_same_lookup_program_instead_of_a_second_path():
    """A short answer fills only the event role; the original program still reads state."""
    context = ReasoningContext()
    for said in ("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.",
                 "하린은 서랍에 있었다."):
        assert context.turn(said, KG)["status"] == "observed"
    asked = context.turn("공책을 모았다.", KG)
    assert asked["status"] == "unresolved"
    assert "누가" in asked["answer"]
    resumed = context.turn("하린이 모았다.", KG)
    assert resumed["status"] == "observed"
    assert context.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."


def test_role_then_state_completion_advances_one_event_through_the_same_executor():
    """Settling one question opens the action's next declared input need."""
    context = ReasoningContext()
    context.turn("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.", KG)
    asked = context.turn("공책을 모았다.", KG)
    assert "누가" in asked["answer"]
    still_needed = context.turn("하린이 모았다.", KG)
    assert still_needed["status"] == "unresolved"
    assert context.asked[-1]["종류"] == "조회"
    assert context.asked[-1]["필요"] == {
        "kind": "lookup", "into": "place", "subject": "하린",
        "predicate": "location", "candidates": [],
    }
    context.turn("하린은 서랍에 있었다.", KG)
    assert context.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."


def test_app_dialogue_naturally_compiles_and_executes_location_lookup(tmp_path):
    from pathlib import Path
    import kgpack
    from views.kgpack_ui import AppState

    pack = tmp_path / "location-program.kgpack"
    kgpack.write_pack(pack, [Path(KG)] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    session = "location_program_dialogue"
    for said in ("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.",
                 "하린은 서랍에 있었다.", "하린이 공책을 모았다."):
        assert app.turn(said, session)["phase"] == "answer"
    assert app.turn("지금 공책은 어디에 있어?", session)["answer"]["answer"] == "서랍에 있습니다."


def test_app_dialogue_keeps_lookup_action_identity_through_completion_correction_and_reuse(tmp_path):
    """One public conversation exercises the full action-event lifecycle."""
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    session = "lookup_action_lifecycle"
    # Explanation -> an event with one missing role -> a short completion.
    for said in ("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.",
                 "하린은 서랍에 있었다."):
        app.turn(said, session, conversation_id=chat)
    asked = app.turn("공책을 모았다.", session, conversation_id=chat)
    assert asked["answer"]["trace"]["verdict"] == "조건부족"
    app.turn("하린이 모았다.", session, conversation_id=chat)
    assert app.turn("지금 공책은 어디에 있어?", session, conversation_id=chat)["answer"]["answer"] == "서랍에 있습니다."

    # Correcting a premise replays the same completed action.  A different
    # actor and item then reuse the definition without carrying state across.
    app.turn("정정: 하린은 서랍에 있었다. => 하린은 창고에 있었다.",
             session, conversation_id=chat)
    assert app.turn("지금 공책은 어디에 있어?", session, conversation_id=chat)["answer"]["answer"] == "창고에 있습니다."
    for said in ("도윤은 책상에 있었다.", "도윤이 연필을 모았다."):
        app.turn(said, session, conversation_id=chat)
    assert app.turn("지금 연필은 어디에 있어?", session, conversation_id=chat)["answer"]["answer"] == "책상에 있습니다."

    # The same saved dialogue then learns a distinct action and runs it in a
    # hypothetical world.  Its lookup/compute bindings must not leak into
    # the real quantities already stored in the conversation.
    for said in ("나누다는 상대에게 구슬의 절반을 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다."):
        app.turn(said, session, conversation_id=chat)
    assumed = app.turn("만약 민수가 지연에게 나눴으면 지금 민수 구슬은 몇 개야?",
                       session, conversation_id=chat)
    assert assumed["answer"]["answer"] == "4개입니다."
    assert app.turn("지금 민수 구슬은 몇 개야?", session,
                    conversation_id=chat)["answer"]["answer"] == "8개입니다."


def test_app_dialogue_resumes_a_state_lookup_after_the_requested_fact(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    session = "lookup_state_reply"
    for said in ("공책은 책상에 있었다.",
                 "모으다는 내가 있는 곳으로 물건을 옮기는 것이다."):
        app.turn(said, session, conversation_id=chat)
    asked = app.turn("하린이 공책을 모았다.", session, conversation_id=chat)
    assert asked["answer"]["trace"]["verdict"] == "조건부족"
    app.turn("하린은 서랍에 있었다.", session, conversation_id=chat)
    assert app.turn("지금 공책은 어디에 있어?", session, conversation_id=chat)["answer"]["answer"] == "서랍에 있습니다."


def test_pack_declared_selection_finds_one_matching_object_but_never_picks_from_many():
    definition = "담다는 서랍에 있는 물건을 창고로 옮기는 것이다."
    single = ReasoningContext()
    for said in ("공책은 서랍에 있었다.", definition, "하린이 담았다."):
        single.turn(said, KG)
    assert single.turn("지금 공책은 어디에 있어?", KG)["answer"] == "창고에 있습니다."

    multiple = ReasoningContext()
    for said in ("공책은 서랍에 있었다.", "연필은 서랍에 있었다.", definition, "하린이 담았다."):
        outcome = multiple.turn(said, KG)
    assert outcome["status"] == "unresolved"
    assert "후보가 여럿" in outcome["answer"]
    assert multiple.turn("지금 공책은 어디에 있어?", KG)["status"] == "unresolved"

    # Repeating the explicitly requested state fact selects that object for
    # this pending event only; the other candidate is never guessed.
    assert multiple.asked[-1]["필요"] == {"kind": "select", "into": "item",
                                        "predicate": "location", "value": "서랍",
                                        "candidates": ["공책", "연필"]}
    multiple.turn("공책은 서랍에 있었다.", KG)
    assert multiple.turn("지금 공책은 어디에 있어?", KG)["answer"] == "창고에 있습니다."
    assert multiple.turn("지금 연필은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."


def test_pack_declared_condition_distinguishes_false_from_unknown_and_runs_when_true():
    definition = "지키다는 내가 서랍에 있으면 물건을 창고로 옮기는 것이다."
    true_case = ReasoningContext()
    for said in ("하린은 서랍에 있었다.", definition, "하린이 공책을 지켰다."):
        true_case.turn(said, KG)
    assert true_case.turn("지금 공책은 어디에 있어?", KG)["answer"] == "창고에 있습니다."

    false_case = ReasoningContext()
    for said in ("하린은 책상에 있었다.", "공책은 서랍에 있었다.", definition):
        false_case.turn(said, KG)
    refused = false_case.turn("하린이 공책을 지켰다.", KG)
    assert refused["status"] == "unresolved"
    assert "실행하지 않았습니다" in refused["answer"]
    # False is known: it must not turn into an unmeasured event that blocks
    # the independently known old location.
    assert false_case.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."


def test_unknown_program_guard_blocks_the_old_value_without_claiming_false():
    context = ReasoningContext()
    for said in ("공책은 책상에 있었다.",
                 "지키다는 내가 서랍에 있으면 물건을 창고로 옮기는 것이다."):
        context.turn(said, KG)
    result = context.turn("하린이 공책을 지켰다.", KG)
    assert result["status"] == "unresolved"
    assert "재지 못했습니다" in result["answer"]
    assert context.turn("지금 공책은 어디에 있어?", KG)["status"] == "unresolved"


def test_requested_state_fact_resumes_only_its_lookup_or_guard_event():
    lookup = ReasoningContext()
    for said in ("공책은 책상에 있었다.",
                 "모으다는 내가 있는 곳으로 물건을 옮기는 것이다.",
                 "하린이 공책을 모았다."):
        lookup.turn(said, KG)
    assert lookup.asked[-1]["필요"] == {"kind": "lookup", "into": "place",
                                      "subject": "하린", "predicate": "location", "candidates": []}
    lookup.turn("도윤은 서랍에 있었다.", KG)
    assert lookup.turn("지금 공책은 어디에 있어?", KG)["status"] == "unresolved"
    lookup.turn("하린은 서랍에 있었다.", KG)
    assert lookup.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."

    guarded = ReasoningContext()
    for said in ("공책은 책상에 있었다.",
                 "지키다는 내가 서랍에 있으면 물건을 창고로 옮기는 것이다.",
                 "하린이 공책을 지켰다."):
        guarded.turn(said, KG)
    assert guarded.asked[-1]["필요"] == {"kind": "condition",
                                        "fact": ["하린", "location", "서랍"]}
    guarded.turn("하린은 서랍에 있었다.", KG)
    assert guarded.turn("지금 공책은 어디에 있어?", KG)["answer"] == "창고에 있습니다."


def test_hypothetical_role_reply_resumes_only_the_held_hypothesis():
    context = ReasoningContext()
    for said in ("나누다는 상대에게 구슬의 절반을 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다."):
        context.turn(said, KG)
    asked = context.turn("만약 지연에게 나눴으면 지금 민수 구슬은 몇 개야?", KG)
    assert asked["status"] == "unresolved"
    resumed = context.turn("민수야", KG)
    assert resumed["answer"] == "4개입니다."
    # The role fill is scoped to the question; no actual event is created.
    assert context.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."


def test_hypothetical_state_reply_resumes_the_held_program_without_creating_a_fact():
    """A requested hypothetical lookup is not promoted to the real timeline."""
    context = ReasoningContext()
    context.turn("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.", KG)
    asked = context.turn("만약 하린이 공책을 모았으면 지금 공책은 어디에 있어?", KG)
    assert asked["status"] == "unresolved"
    assert context.asked[-1]["가정사건"].startswith("hypothesis:")
    assert context.asked[-1]["필요"] == {
        "kind": "lookup", "into": "place", "subject": "하린",
        "predicate": "location", "candidates": [],
    }
    resumed = context.turn("하린은 서랍에 있었다.", KG)
    assert resumed["answer"] == "서랍에 있습니다."
    assert context.turn("지금 공책은 어디에 있어?", KG)["status"] == "unresolved"


def test_requested_state_fill_survives_snapshot_as_part_of_its_event_identity():
    context = ReasoningContext()
    for said in ("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.",
                 "하린이 공책을 모았다.", "하린은 서랍에 있었다."):
        context.turn(said, KG)
    fill = context.fills[-1]
    assert fill["변수"] == "place" and fill["사실"] == ["하린", "location", "서랍"]

    restored = ReasoningContext()
    restored.restore(context.snapshot())
    assert restored.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."


def test_context_referents_follow_their_role_not_the_last_question_subject_and_survive_restore():
    """`그가` and `그것` are event fills, not entity-name substitutions."""
    context = ReasoningContext()
    for said in ("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.",
                 "넣다는 내가 물건을 창고로 옮기는 것이다.",
                 "하린은 서랍에 있었다.", "도윤은 책상에 있었다.",
                 "하린이 공책을 모았다.", "도윤이 연필을 모았다."):
        context.turn(said, KG)
    # The query changes the generic query referent to 공책, but not the
    # actor-role referent.  `그가` still denotes the last actor, 도윤.
    assert context.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."
    context.turn("그가 메모를 모았다.", KG)
    assert context.turn("지금 메모는 어디에 있어?", KG)["answer"] == "책상에 있습니다."

    # The latest object role is 메모.  It is resolved as an item, while the
    # explicit actor remains 하린; no topic is silently merged.
    context.turn("하린이 그것을 넣었다.", KG)
    assert context.turn("지금 메모는 어디에 있어?", KG)["answer"] == "창고에 있습니다."
    event_fill = context.fills[-1]
    assert event_fill["역할"] == "을" and event_fill["값"] == "메모"
    assert event_fill["문맥"] is True

    restored = ReasoningContext()
    restored.restore(context.snapshot())
    restored.turn("그가 종이를 모았다.", KG)
    assert restored.turn("지금 종이는 어디에 있어?", KG)["answer"] == "서랍에 있습니다."


def test_app_dialogue_resolves_context_referents_as_saved_event_role_fills(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    session = "context_role_referents"
    for said in ("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.",
                 "넣다는 내가 물건을 창고로 옮기는 것이다.",
                 "하린은 서랍에 있었다.", "하린이 공책을 모았다.",
                 "그가 연필을 모았다.", "하린이 그것을 넣었다."):
        app.turn(said, session, conversation_id=chat)
    assert app.turn("지금 공책은 어디에 있어?", session,
                    conversation_id=chat)["answer"]["answer"] == "서랍에 있습니다."
    assert app.turn("지금 연필은 어디에 있어?", session,
                    conversation_id=chat)["answer"]["answer"] == "창고에 있습니다."


def test_app_plan_uses_a_learned_action_definition_without_reexecuting_an_event(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    session = "learned_action_plan"
    app.turn("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.", session,
             conversation_id=chat)
    planned = app.turn("모으 계획해줘", session, conversation_id=chat)
    composition = planned["answer"]["composition"]
    assert planned["answer"]["answer"] == (
        "1. 모으 동작을 적용한다: 모으다는 내가 있는 곳으로 물건을 옮기는 것이다 "
        "(필요 역할: 은, 을)")
    assert composition["selected"] == [{"text": planned["answer"]["answer"][3:],
                                        "source": "대화 정의 모으@0"}]
    # A plan names a definition and its missing inputs; it cannot add the
    # location effect that an actual event would have produced.
    context = app.reasoning_contexts["chat_" + chat]
    assert context.current_state() == []


def test_app_explanation_uses_executed_action_evidence_but_not_a_hypothesis(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    session = "executed_action_explanation"
    for said in ("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.",
                 "하린은 서랍에 있었다.", "하린이 공책을 모았다."):
        app.turn(said, session, conversation_id=chat)
    explained = app.turn("공책 설명해줘", session, conversation_id=chat)
    selected = explained["answer"]["composition"]["selected"]
    assert selected[0]["source"].startswith("대화 사건 ")
    assert "하린이 공책을 모았다 → 공책 — location — 서랍" in selected[0]["text"]

    projected = ReasoningContext()
    for said in ("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.",
                 "하린은 서랍에 있었다."):
        projected.turn(said, KG)
    projected.turn("만약 하린이 공책을 모았으면 지금 공책은 어디에 있어?", KG)
    assert projected.execution_evidence("공책") == []


def test_restarted_app_restores_learned_plan_and_execution_evidence(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    for said in ("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.",
                 "하린은 서랍에 있었다.", "하린이 공책을 모았다."):
        app.turn(said, "saved_learned_action", conversation_id=chat)

    restarted = create_app(tmp_path)
    planned = restarted.turn("모으 계획해줘", "new_saved_action", conversation_id=chat)
    assert planned["answer"]["composition"]["selected"][0]["source"] == "대화 정의 모으@0"
    explained = restarted.turn("공책 설명해줘", "new_saved_action", conversation_id=chat)
    assert explained["answer"]["composition"]["selected"][0]["source"].startswith("대화 사건 ")
