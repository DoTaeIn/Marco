"""Why, said: the why chain of an output as a language-free meaning, and that meaning composed.

Goal W4 (``docs/ko/2026-09-24-realizer-r4-goal.md``), answering request L1-2.
Design note principle 6: the explanation of an answer is a projection of its why
chain, not a separate truth. ``chain_meaning`` reads only the chain
(``marco.trace.why.Graph.chain``, along ``parent_ids``) and the withdrawals of the
events it supersedes; it composes nothing. ``say_why`` hands the meaning to the
realizer (``marco.language.realizer``), which plans it (``meaning.json``:
``act: explain``, ``kind: chain`` or ``chain_hold``), says it in the language asked
for, and checks every clause as it checks any reply.

    chain_meaning(graph, output_id) -> dict      the meaning, no language in it
    explain(source, event_id, language) -> (text, report)
    say_why(ledger_path, event_id, language) -> text
    last_explainable(source, conversation)       the output a bare "why" asks about (request W4-1)

``chain_meaning`` uses the standard library only; ``explain`` and ``say_why``
import the realizer when called.
"""
from marco.trace.why import Graph

# The output statuses that end in a hold (marco/trace/from_turn.py: output_status).
HELD = ("hold", "refused", "error", "unknown")
LANGUAGES = {"ko": "styles/한국어.json", "en": "styles/english.json"}
# The check an engine explanation passes (reasoning_context.ReasoningContext._explain_last).
EXPLAINED = "explained_recorded_transitions"
STEMS = {"한국어": "ko", "english": "en", "korean": "ko"}


def _graph(source):
    return source if isinstance(source, Graph) else Graph(source)


def _whole(value):
    """An integer value as an integer; a value that is no whole number stays as it is."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if number.is_integer() and value.strip().lstrip("-").isdigit() else value
    return value


def _is_whole(*values):
    """Every number given is a whole number (or absent): the check reads digits only."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return False
        if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
            return False
    return True


def output_of(graph, event_id):
    """The ``output_created`` event ``event_id`` names, or the output of the trace it belongs to."""
    event = graph.get(event_id)
    if event["kind"] == "output_created":
        return event
    outputs = [e for e in graph.events if e["trace_id"] == event["trace_id"] and e["kind"] == "output_created"]
    if not outputs:
        raise KeyError("trace %s of %s has no output" % (event["trace_id"], event_id))
    return outputs[-1]


class _Turns:
    """The input of each trace: its turn and its words."""

    def __init__(self, graph):
        self.by_trace = {e["trace_id"]: e for e in graph.events if e["kind"] == "input_received"}

    def input(self, event):
        return self.by_trace.get(event["trace_id"])

    def turn(self, event):
        found = self.input(event)
        return (found or {}).get("payload", {}).get("turn")


def _said(event):
    return {"turn": event["payload"].get("turn"), "said": str(event["payload"].get("text") or "").strip(),
            "event": event["event_id"]}


def chain_meaning(graph, output_id):
    """The language-free meaning of an output's why chain (request L1-2 item 1 and 2).

    ``act: explain``; ``kind: chain`` for an output that answered, recorded or said
    anything else, ``kind: chain_hold`` for a held one. Roles, each from the chain's
    own events, in ledger order:

    * ``fact`` / ``facts``: what the output concluded (``conclusion_created.payload.fact``);
      an explanation's conclusion is the last value of each state it rests on;
    * ``changes``: each ``state_changed`` on a state (subject, field, before, after,
      delta, operation type, the rule ids its operator names, what it supersedes);
    * ``statements``: the inputs the chain rests on, by turn, quoting
      ``input_received.payload.text`` (not the output's own turn, not a correction);
    * ``corrections``: each correction of a statement's reading (the corrected turn,
      the correcting turn and its words);
    * ``withdrawn``: each ``conclusion_withdrawn`` of an event the chain supersedes,
      with its ``superseded_by`` and what it had said;
    * ``rules``: the rule ids the chain's operators name (``operation.rules``);
    * ``asked`` (answered) or ``held`` (held): the output's own turn and words;
    * a hold's ``reason``, ``missing`` (as the hold event recorded it), ``statement``
      (the input ``missing.said`` names, by turn and words) and ``reply`` (what was said).
    """
    graph = _graph(graph)
    output = output_of(graph, output_id)
    chain = graph.chain(output["event_id"])
    in_chain = {e["event_id"] for e in chain}
    turns = _Turns(graph)
    own = turns.input(output)
    trace = output["trace_id"]

    changes, corrections, correction_inputs, statement_inputs, rules = [], [], set(), [], []
    for event in chain:
        kind, payload = event["kind"], event["payload"]
        if kind == "rule_applied":
            for rule in (event.get("operation") or {}).get("rules") or ():
                if rule not in rules:
                    rules.append(rule)
        if kind == "observation_created":
            statement_inputs.extend(p for p in event["parent_ids"] if graph.get(p)["kind"] == "input_received")
        if kind != "state_changed":
            continue
        if payload.get("field") == "observation":
            cause = graph.get(payload["cause"]) if payload.get("cause") in graph.position else None
            corrected = [graph.get(p) for p in event["parent_ids"] if graph.get(p)["kind"] == "input_received"
                         and p != payload.get("cause")]
            statement_inputs.extend(e["event_id"] for e in corrected)
            if cause is not None and cause["kind"] == "input_received":
                correction_inputs.add(cause["event_id"])
            corrections.append({
                "event": event["event_id"], "index": payload.get("index"),
                "turn": corrected[0]["payload"].get("turn") if corrected else None,
                "corrected": str(corrected[0]["payload"].get("text") or "").strip() if corrected else None,
                "by": cause["payload"].get("turn") if cause is not None and cause["kind"] == "input_received" else None,
                "said": str(cause["payload"].get("text") or "").strip()
                if cause is not None and cause["kind"] == "input_received" else None,
                "supersedes": event.get("supersedes")})
            continue
        makers = [graph.get(p) for p in event["parent_ids"] if graph.get(p)["kind"] == "rule_applied"]
        row = {"event": event["event_id"], "turn": turns.turn(event), "subject": event.get("subject"),
               "field": payload.get("field"), "before": _whole(payload.get("before")),
               "after": _whole(payload.get("after")), "operation": (event.get("operation") or {}).get("type"),
               "rules": [r for m in makers for r in (m.get("operation") or {}).get("rules") or ()],
               "observation": payload.get("observation"), "supersedes": event.get("supersedes")}
        if payload.get("delta") is not None:
            row["delta"] = _whole(payload["delta"])
        cause = graph.get(payload["cause"]) if payload.get("cause") in graph.position else None
        if cause is not None and cause["kind"] == "input_received":
            statement_inputs.append(cause["event_id"])
        row["whole"] = _is_whole(row["before"], row["after"])
        changes.append(row)

    withdrawn = []
    for event in chain:
        old = event.get("supersedes")
        if not old or old not in graph.withdrawn:
            continue
        gone = graph.get(graph.withdrawn[old])
        before = graph.get(old)
        entry = {"event": gone["event_id"], "withdrawn": old, "superseded_by": gone["payload"].get("superseded_by"),
                 "reason": gone["payload"].get("reason"), "turn": turns.turn(before), "by": turns.turn(event)}
        if before["kind"] == "observation_created" or before["payload"].get("field") == "observation":
            entry["what"] = "observation"
            entry["index"] = before["payload"].get("index")
        elif before["kind"] == "state_changed":
            entry.update({"what": "change", "subject": before.get("subject"), "field": before["payload"].get("field"),
                          "before": _whole(before["payload"].get("before")),
                          "after": _whole(before["payload"].get("after"))})
            entry["whole"] = _is_whole(entry["before"], entry["after"])
        else:
            entry["what"] = before["kind"]
        withdrawn.append(entry)

    # The statements, by turn, each once: not the output's own turn, not a correction.
    seen, statements = set(), []
    for event in chain:
        if event["kind"] != "input_received" or event["event_id"] in seen:
            continue
        if event["event_id"] in correction_inputs or (own is not None and event["event_id"] == own["event_id"]):
            continue
        if event["event_id"] in statement_inputs:
            seen.add(event["event_id"])
            statements.append(_said(event))

    facts = [{"subject": e["payload"]["fact"][0], "relation": e["payload"]["fact"][1],
              "value": _whole(e["payload"]["fact"][2])}
             for e in chain if e["kind"] == "conclusion_created" and e["trace_id"] == trace
             and isinstance(e["payload"].get("fact"), list) and len(e["payload"]["fact"]) == 3]
    conclusion = "fact" if facts else None
    explains = [e for e in chain if e["kind"] == "conclusion_created" and e["trace_id"] == trace
                and not e["payload"].get("fact")]
    if not facts and explains:
        # An explanation concludes the state it explains: the last value of each state it rests on.
        last = {}
        for row in changes:
            last[(row["subject"], row["field"])] = row
        facts = [{"subject": row["subject"], "relation": row["field"], "value": row["after"]}
                 for row in last.values() if row["whole"] and row["after"] is not None]
        conclusion = "state"

    status = output["status"]
    hold = next((e for e in chain if e["kind"] == "hold" and e["trace_id"] == trace), None)
    held = status in HELD or hold is not None
    inputs = [e for e in chain if e["kind"] == "input_received"]
    meaning = {"act": "explain", "kind": "chain_hold" if held else "chain",
               "output": output["event_id"], "status": status,
               "conversation": output["payload"].get("conversation"),
               "conversation_language": (output.get("runtime") or {}).get("pack"),
               "turn": output["payload"].get("turn"),
               "turns": sorted({e["payload"].get("turn") for e in inputs if e["payload"].get("turn") is not None}),
               "statements": statements, "changes": changes, "corrections": corrections, "withdrawn": withdrawn,
               "rules": rules, "facts": facts, "fact": [facts[-1]["subject"], facts[-1]["relation"],
                                                         facts[-1]["value"]] if facts else None,
               "conclusion": conclusion,
               "withdrawn_in_chain": len(graph.withdrawn_in_chain(output["event_id"]))}
    if own is not None:
        if held:
            meaning["held"] = _said(own)
        elif status == "answered":
            meaning["asked"] = _said(own)
        elif own["event_id"] in in_chain and own["event_id"] not in correction_inputs \
                and not any(s["event"] == own["event_id"] for s in statements):
            # A recorded statement: its own words are what was recorded.
            meaning["statements"].append(_said(own))
    if held:
        meaning["reason"] = (hold or {}).get("payload", {}).get("reason") or (
            "execution_error" if status == "error" else "unknown")
        meaning["missing"] = dict((hold or {}).get("payload", {}).get("missing") or {})
        said = meaning["missing"].get("said")
        if isinstance(said, str) and said in graph.position and graph.get(said)["kind"] == "input_received":
            meaning["statement"] = dict(_said(graph.get(said)), own=bool(own) and said == own["event_id"])
        meaning["reply"] = {"turn": output["payload"].get("turn"),
                            "said": str(output["payload"].get("text") or "").strip()}
    return meaning


def last_explainable(source, conversation, before=None):
    """The output a bare "why" asks about, from the ledger alone: the latest ``output_created``
    of ``conversation`` (before the event ``before``, if given) whose trace concluded a fact or
    corrected a statement's reading. An explanation's own output is not one (a "why" after a
    "why" explains the same answer), nor is a hold. None when the conversation has none: the
    engine's own explanation is then the fallback (request ``docs/requests/W4-1.md``)."""
    graph = _graph(source)
    end = graph.position[before] if before is not None else len(graph.events)
    facts, corrected, explained = set(), set(), set()
    for event in graph.events[:end]:
        if event["kind"] == "conclusion_created" and isinstance(event["payload"].get("fact"), list):
            facts.add(event["trace_id"])
        elif event["kind"] == "state_changed" and event["payload"].get("field") == "observation":
            corrected.add(event["trace_id"])
        elif event["kind"] == "hypothesis_verified" and any(
                check.get("reason") == EXPLAINED for check in event["payload"].get("checks") or ()):
            explained.add(event["trace_id"])
    for event in reversed(graph.events[:end]):
        if event["kind"] != "output_created" or event["payload"].get("conversation") != conversation:
            continue
        if event["trace_id"] in explained:
            continue
        if (event["trace_id"] in facts and event["status"] == "answered") or event["trace_id"] in corrected:
            return event["event_id"]
    return None


def _target(language):
    """``ko`` / ``en`` / a stem / a pack path -> the pack path the realizer speaks."""
    text = str(language)
    code = STEMS.get(text, text)
    if code in LANGUAGES:
        return LANGUAGES[code]
    return text


def explain(source, event_id, language):
    """``(text, report)``: the why chain of ``event_id``'s output, composed in ``language``
    (``ko``, ``en``, or a pack path) by the default realizer. The report is the realizer's
    (``marco.language.realizer.last_report()`` returns it too)."""
    from marco.language.realizer import default_realizer
    graph = _graph(source)
    meaning = chain_meaning(graph, event_id)
    target = _target(language)
    said_in = meaning.get("conversation_language") or target
    result = {"status": "unresolved" if meaning["kind"] == "chain_hold" else "answered", "answer": None,
              "transitions": [],
              "meaning": dict(meaning, conversation_language=said_in, answer_language=target)}
    text, report = default_realizer().realize_with_report(result, result["status"], target)
    return text, report


def say_why(ledger_path, event_id, language):
    """The composed explanation of why ``event_id``'s output was said (``ko`` or ``en``)."""
    text, _report = explain(ledger_path, event_id, language)
    return text
