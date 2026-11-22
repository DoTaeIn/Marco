"""Actual-core controls for complete search and provenance transport."""
from experiments.graph_language_repair.core import search_rows


def test_incomplete_world_with_one_match_does_not_authorize_an_exact_answer(
    read_text, compile_question, execute_plan
):
    reading = read_text("가람이 책을 나래에게 전달했다.")
    plan = compile_question("가람이 무엇을 전달했나요?")

    def incomplete(doc, query, *args, **kwargs):
        world = search_rows(doc, query, *args, **kwargs)
        world["complete"] = False
        world["reason"] = "support_limit"
        return world

    result = execute_plan(plan, reading, search_rows=incomplete)
    assert result.get("gate") == "incomplete_search", (
        "an actual native-search world with complete=False must not authorize "
        "an exact answer; got %r" % (result,)
    )

    complete = execute_plan(plan, reading, search_rows=search_rows)
    assert complete.get("gate") is None and complete.get("value") == "책", (
        "the actual complete native world is the positive contrast; got %r" % (complete,)
    )


def test_actual_native_support_references_resolve_to_reading_rows(read_text, compile_question, execute_plan):
    reading = read_text("가람이 책을 나래에게 전달했다.")
    plan = compile_question("가람이 무엇을 전달했나요?")
    result = execute_plan(plan, reading, search_rows=search_rows)
    assert result.get("gate") is None
    candidates = result.get("candidates") or []
    assert candidates and candidates[0].get("source_refs"), (
        "the selected native support must retain its actual source references; "
        "got %r" % (candidates,)
    )
    row_ids = {row["id"] for row in reading["rows"]}
    cited = {row_id for ref in candidates[0]["source_refs"]
             for row_id in (ref.get("rows") or ([ref["row"]] if ref.get("row") else []))}
    assert cited and cited <= row_ids
    assert candidates[0]["polarities"] == {True}


def test_search_rows_error_degrades_to_a_gate_not_a_crash(read_text, compile_question, execute_plan):
    reading = read_text("가람이 책을 나래에게 전달했다.")
    plan = compile_question("가람이 무엇을 전달했나요?")

    def exploding_search_rows(reading_, triple):
        raise LookupError("stub: engine support_limit exceeded")

    result = execute_plan(plan, reading, search_rows=exploding_search_rows)
    assert result.get("gate") is not None
    assert result.get("value") is None

    normal = execute_plan(plan, reading, search_rows=search_rows)
    assert normal.get("gate") is None and normal.get("value") == "책"
