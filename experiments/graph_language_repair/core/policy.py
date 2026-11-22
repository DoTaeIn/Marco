# -*- coding: utf-8 -*-
"""Generic rule evaluation over declared evidence.

A policy record lists evidence kinds, each naming a comparator, and rules made
of ``all_of`` / ``any_of`` label lists.  This module runs the comparators, then
applies the rules.  It contains no cue, no threshold and no language.

One guard is enforced here rather than in data: a rule can never accept on
labels that the same policy lists as ``insufficient_alone``.  That is the
clause the saved diagnosis is explicit about — object identity alone may not
license a merge (CONTRACT C1).
"""
from experiments.graph_language_repair.core import comparators


def evidence_present(context, evidence_records, left, right):
    """Labels of the evidence kinds that hold between two nodes."""
    present, detail = set(), []
    for record in evidence_records:
        name = record.get("comparator")
        if not name:
            continue
        if comparators.run(name, context, left, right, record.get("comparator_args")):
            label = record.get("label", record["key"])
            present.add(label)
            detail.append({"kind": label, "policy": record["key"],
                           "comparator": name,
                           "sufficiency": record.get("sufficiency", "supporting")})
    return present, detail


def _rule_holds(rule, labels):
    for label in rule.get("all_of", ()):
        if label not in labels:
            return False
    any_of = rule.get("any_of", ())
    if any_of and not (set(any_of) & labels):
        return False
    return bool(rule.get("all_of") or any_of)


def _rule_labels(rule):
    return set(rule.get("all_of", ())) | set(rule.get("any_of", ()))


def decide(policy, labels):
    """``(status, rule_id, blocked_by)`` for the labels that hold.

    ``status`` is ``"rejected"``, ``"accepted"``, ``"candidate"`` or ``None``.
    """
    insufficient = set(policy.get("insufficient_alone", ()))
    blocked = []
    for rule in policy.get("reject_rules", ()):
        if _rule_holds(rule, labels):
            return "rejected", rule.get("id"), [rule.get("id")]
    for rule in policy.get("accept_rules", ()):
        if not _rule_holds(rule, labels):
            continue
        used = _rule_labels(rule) & labels
        if used and used <= insufficient:
            blocked.append("insufficient_alone:%s" % ",".join(sorted(used)))
            continue
        return "accepted", rule.get("id"), blocked
    for rule in policy.get("candidate_rules", ()):
        if _rule_holds(rule, labels):
            supporting = labels & insufficient
            if supporting and not blocked:
                blocked.append("insufficient_alone:%s" % ",".join(sorted(sorted(supporting))))
            return "candidate", rule.get("id"), blocked
    return None, None, blocked


def ambiguity_records(policy, labels):
    found = []
    for rule in policy.get("ambiguity_rules", ()):
        if _rule_holds(rule, labels):
            found.append(rule)
    return found
