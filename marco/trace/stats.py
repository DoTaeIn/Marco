"""Failure statistics over a ledger (design note §23, goal L1.5).

Per turn (one ``input_received`` and the events of its trace):

* the ``output_created`` status: answered, recorded, hold, refused, dialogue, error;
* for a hold, its reason and where the reason came from;
* for a statement, whether a ``state_changed`` followed (the record rate);
* from the trace graph, gate condition 3 per answered turn: an answer whose why
  chain reaches no statement and no cited source, and an answer whose chain
  passes through an event withdrawn before it was said.

Denominators are ``bench/dialogue_gate.py``'s (``score``): the gate number is
over turns labelled ``answerable``; ``record`` and ``hold`` are turns whose
expected act is record or hold; ``ambiguous``, ``unsupported``, ``correction``
and ``why`` are labels. A ledger records a turn's label and act when the
dialogue file has them; without them only the ``all`` row exists and a
statement turn is one the engine recorded (gate status ``observed``).

Only the standard library.
"""
from collections import Counter

from marco.trace.schema import OUTPUT_STATUSES
from marco.trace.why import Graph

GROUPS = (
    ("answerable", lambda t: t["label"] == "answerable"),
    ("record", lambda t: t["act"] == "record"),
    ("hold", lambda t: t["act"] == "hold"),
    ("ambiguous", lambda t: t["label"] == "ambiguous"),
    ("unsupported", lambda t: t["label"] == "unsupported"),
    ("correction", lambda t: t["label"] == "correction"),
    ("why", lambda t: t["label"] == "why"),
)
HELD = ("hold", "refused")


def turns(source):
    """One row per ``input_received``, in ledger order."""
    graph = Graph(source)
    rows, current = [], {}
    for event in graph.events:
        kind, payload = event["kind"], event["payload"]
        if kind == "input_received":
            row = {"trace_id": event["trace_id"], "conversation": payload.get("conversation"),
                   "turn": payload.get("turn"), "label": payload.get("label"), "act": payload.get("act"),
                   "input": event["event_id"], "status": None, "gate_status": None, "reason": None,
                   "reason_source": None, "state_changed": 0, "superseded": 0, "output": None,
                   "statement_inputs": None, "cited_sources": None, "withdrawn_used": None}
            rows.append(row)
            current[event["trace_id"]] = row
            continue
        row = current.get(event["trace_id"])
        if row is None:
            continue
        if kind == "state_changed":
            row["state_changed"] += 1
            row["superseded"] += bool(event.get("supersedes"))
        elif kind == "hold":
            row["reason"], row["reason_source"] = payload.get("reason"), payload.get("reason_source")
        elif kind == "output_created":
            row["status"], row["gate_status"], row["output"] = event["status"], payload.get("gate_status"), \
                event["event_id"]
            if event["status"] == "answered":
                chain = graph.chain(event["event_id"])
                row["statement_inputs"] = sum(e["kind"] == "input_received" and e["event_id"] != row["input"]
                                              for e in chain)
                row["cited_sources"] = sum(e["kind"] == "evidence_found" for e in chain)
                row["withdrawn_used"] = len(graph.withdrawn_in_chain(event["event_id"]))
    return rows


def _outputs(rows):
    counts = Counter(r["status"] or "none" for r in rows)
    out = {"n": len(rows)}
    out.update({status: counts.get(status, 0) for status in OUTPUT_STATUSES})
    if counts.get("none"):
        out["no_output"] = counts["none"]
    return out


def table(source):
    rows = turns(source)
    labelled = any(r["label"] for r in rows)
    groups = [(name, [r for r in rows if keep(r)]) for name, keep in GROUPS] if labelled else []
    groups.append(("all", rows))
    statements = [r for r in rows if r["act"] == "record"] if labelled else \
        [r for r in rows if r["gate_status"] == "observed"]
    recorded = [r for r in statements if r["state_changed"]]
    answered = [r for r in rows if r["status"] == "answered"]
    reasons = {}
    for name, members in groups:
        if name in ("answerable", "all"):
            reasons[name] = dict(Counter(r["reason"] for r in members if r["status"] in HELD).most_common())
    sources = dict(Counter(r["reason_source"] for r in rows if r["status"] in HELD).most_common())
    return {
        "turns": len(rows),
        "conversations": len({r["conversation"] for r in rows}),
        "labelled": labelled,
        "outputs": {name: _outputs(members) for name, members in groups},
        "holds_by_reason": reasons,
        "hold_reason_sources": sources,
        "record": {"denominator": "turns whose expected act is record" if labelled
                   else "turns the engine recorded (gate status observed)",
                   "n": len(statements), "with_state_changed": len(recorded),
                   "rate": round(len(recorded) / len(statements), 4) if statements else None},
        "graph_checks": {"answered": len(answered),
                         "no_statement_or_source": sum(1 for r in answered
                                                       if not r["statement_inputs"] and not r["cited_sources"]),
                         "withdrawn_evidence_used": sum(1 for r in answered if r["withdrawn_used"])},
    }


def format_table(result):
    columns = list(OUTPUT_STATUSES)
    out = ["turns %d  conversations %d  %s" % (result["turns"], result["conversations"],
                                               "labelled (gate denominators)" if result["labelled"]
                                               else "unlabelled"), "",
           "%-12s %5s " % ("output by", "N") + " ".join("%9s" % c for c in columns)]
    for name, row in result["outputs"].items():
        out.append("%-12s %5d " % (name, row["n"]) + " ".join("%9d" % row[c] for c in columns))
    for name, counts in result["holds_by_reason"].items():
        total = sum(counts.values())
        out += ["", "holds by reason, %s (%d)" % (name, total)]
        for reason, count in counts.items():
            out.append("  %-34s %4d  %5.1f%%" % (reason, count, 100.0 * count / total if total else 0))
    out += ["", "hold reason taken from: " + ", ".join("%s %d" % kv for kv in result["hold_reason_sources"].items())]
    record = result["record"]
    out += ["", "record rate: %d/%d statement turns followed by state_changed%s (%s)" % (
        record["with_state_changed"], record["n"],
        " = %.1f%%" % (100 * record["rate"]) if record["rate"] is not None else "", record["denominator"])]
    checks = result["graph_checks"]
    out += ["graph checks over %d answered: no statement or source in the why chain %d, "
            "withdrawn evidence used %d" % (checks["answered"], checks["no_statement_or_source"],
                                            checks["withdrawn_evidence_used"])]
    return "\n".join(out)
