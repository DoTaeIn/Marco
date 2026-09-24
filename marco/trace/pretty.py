"""The human projection of a ledger (design note §32): one line per event.

    time          tag  subject               summary

Pretty lines are not the record; the JSONL ledger is. Summaries are field
values put side by side, never a composed sentence.

Only the standard library.
"""
import time

from marco.trace.schema import KINDS

WIDTH = 60


def _clip(text, width=WIDTH):
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 1] + "…"


def _short(event_id):
    return event_id[-6:] if isinstance(event_id, str) else "-"


def _time(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts)) + ".%03d" % int((ts % 1) * 1000)


def _state(p):
    if p.get("field") == "observation":
        return "observation %s %s -> %s (cause %s)" % (p.get("index"), p["before"].get("sha256", "")[:8],
                                                       p["after"].get("sha256", "")[:8], _short(p.get("cause")))
    return "%s %s -> %s (cause %s)" % (p.get("field"), p.get("before"), p.get("after"), _short(p.get("cause")))


SUMMARY = {
    "input_received": lambda e, p: "turn %s %s" % (p.get("turn"), '"%s"' % _clip(p.get("text"), 48)),
    "observation_created": lambda e, p: "observation %s stored" % p.get("index"),
    "routing_selected": lambda e, p: "selected %s mode %s verdict %s" % (p.get("selected"), p.get("mode"),
                                                                         p.get("verdict")),
    "rule_applied": lambda e, p: "%s over %d statements, verdict %s" % (p.get("operator"), len(e["input_refs"]),
                                                                        p.get("verdict")),
    "state_changed": lambda e, p: _state(p) + (" supersedes %s" % _short(e.get("supersedes"))
                                               if e.get("supersedes") else ""),
    "conclusion_created": lambda e, p: " ".join(p["fact"]) if p.get("fact") else "%s %s" % (
        p.get("kind"), p.get("explains") or ""),
    "conclusion_withdrawn": lambda e, p: "withdrew %s (%s)%s" % (
        _short(p.get("withdrawn")), p.get("reason"),
        " superseded by %s" % _short(p["superseded_by"]) if p.get("superseded_by") else ""),
    "hypothesis_verified": lambda e, p: "%d checks ok" % len(p.get("checks") or []),
    "hypothesis_rejected": lambda e, p: "failed: %s" % ", ".join(
        str(c.get("reason")) for c in p.get("checks") or [] if not c.get("ok")),
    "contradiction_found": lambda e, p: "contradiction: %s" % ", ".join(
        str(c.get("reason")) for c in p.get("checks") or [] if not c.get("ok")),
    "evidence_found": lambda e, p: "source %s" % _clip(p.get("ref"), 48),
    "hold": lambda e, p: "%s %s%s" % (e["status"], p.get("reason"),
                                      " missing %s" % ",".join(sorted(p["missing"])) if p.get("missing") else ""),
    "output_created": lambda e, p: "%s %s %s" % (e["status"], "realized" if p.get("realized") else "not-realized",
                                                 '"%s"' % _clip(p.get("text"), 44)),
    "error": lambda e, p: "%s %s" % (p.get("problem"), _clip(p.get("message") or p.get("line") or "", 40)),
}


def line(event):
    kind = KINDS.get(event["kind"])
    tag = kind.tag if kind else "???"
    payload = event.get("payload") or {}
    summarize = SUMMARY.get(event["kind"])
    summary = summarize(event, payload) if summarize else _clip(", ".join(
        "%s=%s" % (k, v) for k, v in payload.items()))
    subject = event.get("subject") or "-"
    return "%s %-3s %-18s %s" % (_time(event["timestamp"]), tag, _clip(subject, 18), summary)


def lines(events, trace_id=None):
    return [line(e) for e in events if trace_id is None or e["trace_id"] == trace_id]
