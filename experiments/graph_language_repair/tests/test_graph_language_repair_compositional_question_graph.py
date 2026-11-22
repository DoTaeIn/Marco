"""Public compositional question graph compiler pilot tests."""
from experiments.graph_language_repair.questions.compositional import compile_question_graph


def _alt(text):
    return compile_question_graph(text)["program"]["alternatives"][0]


def test_unknown_np_case_selects_grammatical_function_without_head_whitelist():
    a = _alt("어떤 상자를 전달했나요?")
    b = _alt("무슨 제품을 나톱했나요?")
    assert ["?event", "object", "?answer"] in a["patterns"]
    assert ["?event", "object", "?answer"] in b["patterns"]
    assert a["coverage"] == b["coverage"] == "partial"
    assert "unknown_descriptor" in {x["reason"] for x in b["unresolved"]}
    assert "unknown_predicate_meaning" in {x["reason"] for x in b["unresolved"]}
    assert b["unresolved"][0]["surface"] == "무슨 제품"


def test_voice_maps_case_to_different_frame_role():
    active = _alt("어떤 상자를 전달했나요?")
    passive = _alt("어떤 상자가 전달되었나요?")
    assert ["?event", "object", "?answer"] in active["patterns"]
    assert ["?event", "object", "?answer"] in passive["patterns"]
    assert ["?event", "polarity", "true"] in passive["patterns"]
    assert len(passive["patterns"]) > 0
    assert not any(p[1] == "voice" for p in passive["patterns"])


def test_who_is_structural_role_question_not_personhood_proof():
    alt = _alt("누가 종이를 전달했나요?")
    assert ["?event", "actor", "?answer"] in alt["patterns"]
    assert alt["type_status"] == "unknown"
    assert any(x["reason"] == "unknown_wh_type" for x in alt["unresolved"])


def test_negative_question_keeps_negative_polarity_as_explicit_constraint():
    alt = _alt("어떤 상자를 전달하지 않았나요?")
    assert ["?event", "polarity", "false"] in alt["patterns"]
    assert alt["coverage"] == "partial"


def test_request_scope_is_preserved_as_unparsed_not_dropped():
    result = compile_question_graph("어떤 상자를 전달해 주세요?")
    assert result["program"]["alternatives"] == []
    assert result["diagnostics"][0]["reason"] == "unsupported_request_scope"
    assert result["unconsumed"][0]["surface"] == "어떤 상자를 전달해 주세요?"


def test_open_heads_and_case_cross_product_preserves_role_and_unknown_surface():
    cases = [("어떤 수송체", "를", "object"),
             ("무슨 도구", "를", "object"),
             ("어느 구조물", "이", "actor")]
    for head, particle, role in cases:
        result = compile_question_graph(head + particle + " 전달했나요?")
        alternatives = result["program"]["alternatives"]
        assert alternatives
        assert any(["?event", role, "?answer"] in alt["patterns"] for alt in alternatives)
        assert any(any(x.get("surface", "").startswith(head) for x in alt["unresolved"])
                   for alt in alternatives)


def test_multiple_predicates_and_quoted_scope_remain_partial_candidates():
    result = compile_question_graph('“누가 종이를 전달했나요?”라고 묻나요?')
    assert result["program"]["alternatives"]
    assert all(alt["coverage"] == "partial" for alt in result["program"]["alternatives"])
    assert any(x["reason"] == "unsupported_embedded_scope"
               for alt in result["program"]["alternatives"] for x in alt["unresolved"])


def test_temporal_wh_and_ambiguous_locative_keep_explicit_role_candidates():
    when = _alt("언제 전달했나요?")
    assert ["?event", "time", "?answer"] in when["patterns"]
    where = compile_question_graph("어디에서 전달했나요?")["program"]["alternatives"]
    roles = {p[1] for alt in where for p in alt["patterns"] if p[0] == "?event" and p[2] == "?answer"}
    assert roles == {"origin", "place"}
    assert len(where) == 2


def _execute(document, question):
    from experiments.graph_language_repair.core import read_text
    from experiments.graph_language_repair.questions.query_graph import execute_query_graph

    compiled = compile_question_graph(question)
    result = execute_query_graph(read_text(document), compiled["program"])
    return compiled, result


def _bindings(result):
    return [match["bindings"] for alt in result.get("alternatives", [])
            for match in alt.get("matches", [])]


def test_explicit_nonasked_argument_constraints_block_wrong_actor_and_object():
    q_actor = "미린이 무엇을 봉인했어?"
    compiled, right = _execute("미린이 장부를 봉인했다.", q_actor)
    _, wrong_actor = _execute("다솔이 장부를 봉인했다.", q_actor)
    assert ["?event", "actor", "미린"] in compiled["program"]["alternatives"][0]["patterns"]
    assert {"?answer": "장부"} in _bindings(right)
    assert _bindings(wrong_actor) == []

    q_object = "누가 도면을 봉인했어?"
    compiled, wrong_object = _execute("미린이 장부를 봉인했다.", q_object)
    assert ["?event", "object", "도면"] in compiled["program"]["alternatives"][0]["patterns"]
    assert _bindings(wrong_object) == []


def test_unknown_head_variable_still_keeps_known_actor_constraint():
    compiled, result = _execute("미린이 장부를 봉인했다.", "미린이 어떤 서류를 봉인했어?")
    alt = compiled["program"]["alternatives"][0]
    assert ["?event", "actor", "미린"] in alt["patterns"]
    assert ["?event", "object", "?answer"] in alt["patterns"]
    assert alt["coverage"] == "partial" and alt["type_status"] == "unknown"
    assert {"?answer": "장부"} in _bindings(result)
    assert result["status"] == "hold"


def test_question_voice_maps_role_without_requiring_matching_world_voice():
    compiled, result = _execute("미린에 의해 장부가 봉인되었다.", "누가 장부를 봉인했어?")
    alt = compiled["program"]["alternatives"][0]
    assert ["?event", "actor", "?answer"] in alt["patterns"]
    assert not any(pattern[1] == "voice" for pattern in alt["patterns"])
    assert {"?answer": "미린"} in _bindings(result)


def test_explicit_negative_question_constrains_polarity():
    question = "미린이 무엇을 봉인하지 않았나요?"
    compiled, negative = _execute("미린이 장부를 봉인하지 않았다.", question)
    _, positive = _execute("미린이 장부를 봉인했다.", question)
    assert ["?event", "polarity", "false"] in compiled["program"]["alternatives"][0]["patterns"]
    assert {"?answer": "장부"} in _bindings(negative)
    assert _bindings(positive) == []


def test_scope_variable_preserves_reported_claims_and_source_attribution():
    compiled, result = _execute("민지가 미린이 장부를 봉인했다고 보고했다.", "미린이 무엇을 봉인했어?")
    alt = compiled["program"]["alternatives"][0]
    assert ["?claim", "scope_kind", "?scope"] in alt["patterns"]
    assert {"?answer": "장부"} in _bindings(result)
    assert any("reported_claim" in source.get("scope_kinds", [])
               for alt in result["alternatives"] for match in alt["matches"]
               for source in match["source_refs"])


def test_quoted_and_multiple_predicate_questions_keep_partial_readings():
    quote_text = "“미린이 무엇을 봉인했어?”라고 물었나요?"
    quoted = compile_question_graph(quote_text)
    assert quoted["program"]["alternatives"]
    assert all(alt["coverage"] == "partial" for alt in quoted["program"]["alternatives"])
    assert any(item["reason"] == "unsupported_embedded_scope"
               for alt in quoted["program"]["alternatives"] for item in alt["unresolved"])
    _, quote_evidence = _execute("미린이 장부를 봉인했다고 말했다.", quote_text)
    assert quote_evidence["status"] == "hold"
    assert quote_evidence["alternatives"]

    multiple_text = "미린이 무엇을 봉인하고 누가 도면을 봉인했나요?"
    multiple = compile_question_graph(multiple_text)
    assert len(multiple["predicate_analyses"]) >= 2
    assert multiple["program"]["alternatives"]
    assert all(alt["coverage"] == "partial" for alt in multiple["program"]["alternatives"])
    _, multiple_evidence = _execute("미린이 장부를 봉인했다. 미린이 도면을 봉인했다.", multiple_text)
    assert multiple_evidence["status"] == "hold"
    assert any(_bindings(multiple_evidence))


def test_public_rival_events_retain_all_open_head_candidates():
    _, result = _execute("미린이 장부를 봉인했다. 미린이 도면을 봉인했다.",
                         "미린이 어떤 물건을 봉인했어?")
    assert {"?answer": "장부"} in _bindings(result)
    assert {"?answer": "도면"} in _bindings(result)
    assert result["status"] == "hold"


def test_compositional_copular_identity_question_matches_existing_graph_rows():
    compiled, result = _execute("이것은 금고이다.", "이것은 무엇인가요?")
    alt = compiled["program"]["alternatives"][0]
    assert ["?event", "action_type", "action:identify"] in alt["patterns"]
    assert ["?event", "item", "이것"] in alt["patterns"]
    assert ["?event", "identity_value", "?answer"] in alt["patterns"]
    assert {"?answer": "금고"} in _bindings(result)
    assert result["status"] == "hold"


def test_compositional_copular_wh_subject_constrains_identity_value():
    compiled = compile_question_graph("누가 담당자입니까?")
    alt = compiled["program"]["alternatives"][0]
    assert ["?event", "item", "?answer"] in alt["patterns"]
    assert ["?event", "identity_value", "담당자"] in alt["patterns"]
    assert alt["coverage"] == "partial" and alt["type_status"] == "unknown"


def test_attached_case_composes_open_wh_root_and_atomic_nominative_is_preserved():
    object_question = compile_question_graph("무엇을 봉인했어?")
    object_slot = next(slot for slot in object_question["argument_spans"] if slot["kind"] == "wh")
    assert object_slot["surface"] == "무엇을"
    assert object_slot["classes"] == ["accusative"]
    assert ["?event", "object", "?answer"] in object_question["program"]["alternatives"][0]["patterns"]

    subject_question = compile_question_graph("누가 봉인했어?")
    subject_slot = next(slot for slot in subject_question["argument_spans"] if slot["kind"] == "wh")
    assert subject_slot["surface"] == "누가"
    assert subject_slot["span"] == [0, 2]
    assert subject_slot["classes"] == ["nominative"]
    assert ["?event", "actor", "?answer"] in subject_question["program"]["alternatives"][0]["patterns"]


def test_relative_gap_candidates_exclude_every_occupied_role():
    result = compile_question_graph("미린이 봉인한 것은 무엇인가?")
    alternatives = result["program"]["alternatives"]
    assert alternatives
    assert all(["?event", "actor", "미린"] in alt["patterns"] for alt in alternatives)
    asked_roles = {p[1] for alt in alternatives for p in alt["patterns"]
                   if p[0] == "?event" and p[2] == "?answer"}
    assert "actor" not in asked_roles
    assert "object" in asked_roles
    assert all(any(item["reason"] == "relative_valency_unknown" for item in alt["unresolved"])
               for alt in alternatives)


def test_identity_request_scope_is_parsed_but_remains_unresolved():
    result = compile_question_graph("이것은 무엇인지 알려줘")
    assert result["program"]["alternatives"]
    alt = result["program"]["alternatives"][0]
    assert any(item["reason"] == "embedded_request_scope" for item in alt["unresolved"])
    assert any(item.get("reason") == "embedded_request_scope" for item in result["unconsumed"])


def test_quoted_world_candidate_keeps_quoted_scope_proof():
    compiled, result = _execute("“미린이 장부를 봉인했다.”", "미린이 무엇을 봉인했어?")
    assert ["?claim", "scope_kind", "?scope"] in compiled["program"]["alternatives"][0]["patterns"]
    assert result["status"] == "hold"
    assert {"?answer": "장부"} in _bindings(result)
    assert any("quoted_text" in source.get("scope_kinds", [])
               for alt in result["alternatives"] for match in alt["matches"]
               for source in match["source_refs"])


def test_unconsumed_question_material_forces_hold_even_when_graph_has_a_candidate():
    compiled, result = _execute("미린이 장부를 봉인했다.", "미린이 무엇을 봉인했어? 그리고 별도 조건")
    assert compiled["unconsumed"]
    assert all(alt["coverage"] == "partial" for alt in compiled["program"]["alternatives"])
    assert all(any(item["reason"] == "unparsed_question_material" for item in alt["unresolved"])
               for alt in compiled["program"]["alternatives"])
    assert result["status"] == "hold"


def test_restrictive_material_before_or_after_wh_determiner_is_preserved_as_hard_unknown():
    for question, surface in (("미린이 빨간 어떤 상자를 봉인했어?", "빨간 어떤 상자"),
                              ("미린이 어떤 빨간 상자를 봉인했어?", "어떤 빨간 상자")):
        compiled = compile_question_graph(question)
        alt = compiled["program"]["alternatives"][0]
        descriptor = next(item for item in alt["unresolved"]
                          if item["reason"] == "unknown_descriptor")
        assert descriptor["surface"] == surface
        assert descriptor["uncertainty_class"] == "hard"
        assert descriptor["confirmation"] == "conditional"
        assert descriptor["span"] == [4, 12]
        assert compiled["compiler_metadata"][0]["uncertainty_class"] == "hard"


def test_question_mark_prefixed_atoms_are_hard_held_without_mutation():
    for question in ("?x가 무엇을 봉인했어?", "“?x”가 무엇을 봉인했어?"):
        compiled = compile_question_graph(question)
        assert compiled["program"]["alternatives"] == []
        assert compiled["status"] == "unparsed"
        assert compiled["unconsumed"] == [{"span": [0, len(question)], "surface": question}]
        assert compiled["diagnostics"][0]["reason"] == "unsupported_literal_atom"
        assert compiled["diagnostics"][0]["uncertainty_class"] == "hard"


def test_relative_open_head_retains_recipient_candidate_without_claiming_valency():
    question = "미린이 책을 선물한 사람은 누구야?"
    compiled, result = _execute("미린이 책을 하린에게 선물했다.", question)
    assert any(["?event", "destination", "?answer"] in alt["patterns"]
               for alt in compiled["program"]["alternatives"])
    assert {"?answer": "하린"} in _bindings(result)
    assert all(any(item["reason"] == "relative_valency_unknown"
                   for item in alt["unresolved"])
               for alt in compiled["program"]["alternatives"])


def test_new_predicate_frame_uses_its_declared_question_role_mapping():
    compiled, result = _execute("미린이 장부를 확인했다.", "미린이 무엇을 확인했나요?")
    alt = compiled["program"]["alternatives"][0]
    assert ["?event", "action_type", "action:check"] in alt["patterns"]
    assert ["?event", "checking_actor", "미린"] in alt["patterns"]
    assert ["?event", "checking_object", "?answer"] in alt["patterns"]
    assert {"?answer": "장부"} in _bindings(result)


def test_two_wh_slots_project_independent_role_variables():
    compiled, result = _execute("미린이 장부를 봉인했다.", "누가 무엇을 봉인했어?")
    alt = compiled["program"]["alternatives"][0]
    assert ["?event", "actor", "?answer"] in alt["patterns"]
    assert ["?event", "object", "?answer2"] in alt["patterns"]
    assert alt["project"] == ["?answer", "?answer2"]
    assert {"?answer": "미린", "?answer2": "장부"} in _bindings(result)
