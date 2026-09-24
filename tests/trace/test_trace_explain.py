"""W4.1, W4.3: why, said from the trace graph (``marco/trace/explain.py``).

The fixed seven-step dialogue is recorded in both languages, as ``tests/trace/test_trace_turns.py``
records it (the gate's player through ``AppState.turn``). Each output's why chain becomes a
language-free meaning (``chain_meaning``), and the realizer composes it in either language
(``explain``, ``say_why``, ``python -m marco.trace why <ledger> <event_id> --say ko|en``).
The answer after the restart rests on turns 1, 2, 5 and 9: the two statements, the correction,
the question.
"""
import json

import pytest

from marco.language.realizer import last_report
from marco.trace import drive, from_turn
from marco.trace.__main__ import main
from marco.trace.explain import chain_meaning, explain, say_why
from marco.trace.ledger import Ledger
from marco.trace.why import Graph

LANGUAGES = ("en", "ko")
PACKS = {"en": "styles/english.json", "ko": "styles/한국어.json"}
TAKER = {"en": "Jiyeon apples", "ko": "지연 사과"}


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    folder = tmp_path_factory.mktemp("trace-explain")
    out = {}
    for code in LANGUAGES:
        book = Ledger(folder, "seven-%s" % code)
        drive.record([drive.seven_step(code)], book)
        out[code] = book
    return out


def _outputs(book):
    return [e for e in book.events if e["kind"] == "output_created"]


def _inputs(book):
    return {e["payload"]["turn"]: e for e in book.events if e["kind"] == "input_received"}


def _frames(report):
    return [p["frame"] for p in report["trace"]["meaning"]]


def _strings(node, out):
    if isinstance(node, dict):
        for value in node.values():
            _strings(value, out)
    elif isinstance(node, list):
        for value in node:
            _strings(value, out)
    elif isinstance(node, str):
        out.append(node)
    return out


# ---------------------------------------------------------------------------
# W4.1 chain -> meaning
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", LANGUAGES)
def test_the_answer_after_the_restart_rests_on_turns_1_2_5_and_9(recorded, code):
    book = recorded[code]
    graph, said = Graph(book), _inputs(book)
    output = _outputs(book)[8]
    assert output["payload"]["turn"] == 9 and said[9]["payload"].get("restart") is True
    meaning = chain_meaning(graph, output["event_id"])
    assert (meaning["act"], meaning["kind"], meaning["status"]) == ("explain", "chain", "answered")
    assert meaning["turns"] == [1, 2, 5, 9]
    assert [(s["turn"], s["said"]) for s in meaning["statements"]] == [
        (1, said[1]["payload"]["text"]), (2, said[2]["payload"]["text"])]
    assert (meaning["asked"]["turn"], meaning["asked"]["said"]) == (9, said[9]["payload"]["text"])
    assert meaning["fact"] == [TAKER[code], "count", 3] and meaning["conclusion"] == "fact"
    assert [(c["subject"], c["before"], c["after"], c["operation"]) for c in meaning["changes"]] == [
        (TAKER[code], None, 2, "state_update"), (TAKER[code], 2, 3, "quantity_update")]
    correction, = meaning["corrections"]
    assert (correction["turn"], correction["by"], correction["said"]) == (2, 5, said[5]["payload"]["text"])
    reading, change = meaning["withdrawn"]
    assert (reading["what"], reading["reason"], reading["turn"], reading["by"]) == ("observation", "corrected", 2, 5)
    assert reading["superseded_by"] == correction["event"]
    assert (change["what"], change["reason"], change["before"], change["after"]) == (
        "change", "recomputed_after_correction", 2, 4)
    assert change["superseded_by"] == meaning["changes"][1]["event"]
    chain = {e["event_id"] for e in graph.chain(output["event_id"])}
    for entry in meaning["withdrawn"]:
        # the withdrawal is found through the chain event that supersedes what it withdrew
        assert entry["superseded_by"] in chain and entry["withdrawn"] not in chain
        assert book.get(entry["event"])["kind"] == "conclusion_withdrawn"
    assert meaning["withdrawn_in_chain"] == 0 and meaning["rules"] == []


@pytest.mark.parametrize("code", LANGUAGES)
def test_the_meaning_holds_the_users_words_and_no_sentence_of_a_reply(recorded, code):
    book = recorded[code]
    graph, inputs = Graph(book), {e["payload"]["text"] for e in _inputs(book).values()}
    # and the state keys the ledger itself records (a holder and a thing: "Jiyeon apples")
    inputs |= {e["subject"] for e in book.events if e.get("subject")}
    for output in _outputs(book):
        meaning = chain_meaning(graph, output["event_id"])
        phrases = [s for s in _strings(meaning, []) if " " in s.strip() and len(s) >= 12]
        if meaning["kind"] == "chain":
            assert output["payload"]["text"] not in _strings(meaning, [])
            assert set(phrases) <= inputs, set(phrases) - inputs
        else:
            # a held reply's own words are kept, to be quoted when its reason has no frame
            assert set(phrases) <= inputs | {output["payload"]["text"]}


def test_any_event_of_a_trace_names_that_traces_output(recorded):
    book = recorded["en"]
    graph = Graph(book)
    output = _outputs(book)[8]
    question = _inputs(book)[9]
    assert chain_meaning(graph, question["event_id"]) == chain_meaning(graph, output["event_id"])


@pytest.mark.parametrize("code", LANGUAGES)
def test_an_explanation_rests_on_the_rules_its_operator_named_and_concludes_the_state(recorded, code):
    book = recorded[code]
    output = _outputs(book)[5]                       # "Why did that happen?"
    meaning = chain_meaning(Graph(book), output["event_id"])
    assert meaning["rules"] == ["count_remove", "count_add"]
    assert meaning["turns"] == [1, 2, 5, 6] and meaning["conclusion"] == "state"
    assert sorted((f["subject"], f["value"]) for f in meaning["facts"]) == sorted(
        [(TAKER[code], 3), ({"en": "Minsu apples", "ko": "민수 사과"}[code], 4)])
    _text, report = explain(book, output["event_id"], code)
    assert _frames(report).count("rule") == 2


@pytest.mark.parametrize("code", LANGUAGES)
def test_held_outputs_are_explained_from_their_hold(recorded, code):
    book = recorded[code]
    graph, outputs = Graph(book), _outputs(book)
    refused = chain_meaning(graph, outputs[3]["event_id"])
    assert (refused["kind"], refused["status"], refused["reason"]) == ("chain_hold", "refused", "premise_missing")
    assert set(refused["missing"]) == {"subject", "relation"} and refused["held"]["turn"] == 4
    asked = chain_meaning(graph, outputs[6]["event_id"])
    assert (asked["kind"], asked["status"], asked["reason"]) == ("chain_hold", "hold", "which_referent")
    assert len(asked["missing"]["candidates"]) == 2
    for output, reason_frame in ((outputs[3], "known"), (outputs[6], "chain_which")):
        for language in LANGUAGES:
            _text, report = explain(book, output["event_id"], language)
            assert _frames(report) == ["chain_held", reason_frame]


def test_a_hold_waiting_on_an_unread_statement_names_that_statements_turn(tmp_path):
    book = Ledger(tmp_path, "unread")
    unread = "Wren lent Pell a ladle."

    def held(meaning, reason):
        return {"status": "unresolved", "operator": "relational_graph", "answer": "?", "transitions": [],
                "verification": {"checks": [{"ok": False, "reason": reason}], "sources": [PACKS["en"]]},
                "meaning": meaning}
    from_turn.record_turn(book, book.new_trace_id(), unread, held(
        {"act": "hold", "reason": "input_understanding_failed", "said": unread}, "input_understanding_failed"),
        None, conversation="c", pack=PACKS["en"])
    summary = from_turn.record_turn(book, book.new_trace_id(), "How many ladles does Pell have?", held(
        {"act": "hold", "reason": "unread_event", "said": unread}, "unread_event"),
        None, conversation="c", pack=PACKS["en"])
    meaning = chain_meaning(Graph(book), summary["output"])
    assert meaning["kind"] == "chain_hold" and meaning["reason"] == "unread_event"
    assert (meaning["statement"]["turn"], meaning["statement"]["said"], meaning["statement"]["own"]) == (
        1, unread, False)
    text, report = explain(book, summary["output"], "en")
    assert report["realized"] and not report["held"]
    assert text == ('I held my answer to "How many ladles does Pell have?" at turn 2. '
                    'I could not read "Wren lent Pell a ladle." at turn 1.')
    text, _report = explain(book, summary["output"], "ko")
    assert text.endswith('1번째 말 "Wren lent Pell a ladle."를 읽지 못했습니다.')


# ---------------------------------------------------------------------------
# W4.2 through the realizer, W4.3 entry points
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", LANGUAGES)
def test_every_output_is_explained_composed_and_checked_in_both_languages(recorded, code):
    book = recorded[code]
    graph = Graph(book)
    for output in _outputs(book):
        for language in LANGUAGES:
            text, report = explain(graph, output["event_id"], language)
            assert report["realized"] and not report["held"], (output["payload"]["turn"], language)
            assert last_report()["realized"] is True and last_report()["text"] == text
            assert text and text != output["payload"]["text"]
            clauses = [c for c in report["clauses"] if not c.get("omitted")]
            assert clauses and all(c["attempts"][-1]["check"]["ok"] for c in clauses)
            assert report["language"] == {"en": "english", "ko": "한국어"}[language]


@pytest.mark.parametrize("code", LANGUAGES)
def test_the_answer_after_the_restart_is_said_with_its_turns(recorded, code):
    book = recorded[code]
    output, said = _outputs(book)[8], _inputs(book)
    english, report = explain(book, output["event_id"], "en")
    for turn in (1, 2, 5, 9):
        assert "turn %d" % turn in english
        assert '"%s"' % said[turn]["payload"]["text"] in english
    assert _frames(report) == ["chain_statement", "chain_statement", "count", "count_change",
                               "reading_corrected", "change_withdrawn", "chain_asked", "count"]
    assert english.endswith("So Jiyeon has 3 apples.")
    korean, _report = explain(book, output["event_id"], "ko")
    for turn in (1, 2, 5, 9):
        assert "%d번째 말" % turn in korean
        assert '"%s"' % said[turn]["payload"]["text"] in korean
    assert korean.endswith("그래서 %s는 3개입니다." % {"en": "Jiyeon 사과", "ko": "지연 사과"}[code])


def test_the_command_line_and_say_why_print_the_composed_explanation(recorded, capsys):
    book = recorded["en"]
    output = _outputs(book)[8]["event_id"]
    for language in LANGUAGES:
        assert main(["why", str(book.path), output, "--say", language]) == 0
        printed = capsys.readouterr().out
        assert printed == say_why(book.path, output, language) + "\n"
        assert printed.strip() == explain(book.path, output, language)[0]
    # without --say the command prints the inputs as before
    assert main(["why", str(book.path), output]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 4


def test_the_explanation_is_json_safe_and_small(recorded):
    book = recorded["ko"]
    graph = Graph(book)
    for output in _outputs(book):
        meaning = chain_meaning(graph, output["event_id"])
        assert json.loads(json.dumps(meaning, ensure_ascii=False)) == meaning
        assert len(json.dumps(meaning, ensure_ascii=False).encode("utf-8")) < 8000
