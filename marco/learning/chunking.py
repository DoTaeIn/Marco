"""Conservative, evidence-preserving shortcut rules for repeated Horn paths."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import time

from graph_inference import closure


SCHEMA = "alma-proof-shortcut-v1"


def _fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def propose(rules, chain_ids):
    """Compose an exact unary Horn path without dropping its original proof.

    The narrow exact-pattern requirement is intentional: alpha-renaming or
    multi-premise joins need a real unifier and must remain on the original
    path rather than becoming an unsound performance shortcut.
    """
    by_id = {row.get("id"): row for row in rules}
    chain = [by_id.get(item) for item in chain_ids]
    if len(chain) < 2 or any(not isinstance(row, dict) for row in chain):
        return None
    if any(len(row.get("body") or []) != 1 for row in chain):
        return None
    if any(chain[index]["head"] != chain[index + 1]["body"][0]
           for index in range(len(chain) - 1)):
        return None
    source = [{"id": row["id"], "version": row.get("version", row.get("rule_version")),
               "body": row["body"], "head": row["head"]} for row in chain]
    shortcut_id = "shortcut:" + _fingerprint(source)[:20]
    # Retain every prefix fact.  A downstream rule may consume ``b`` or ``c``
    # even when this shortcut was proposed for ``d``.
    rules = [deepcopy(chain[0])]
    rules += [{"id": "%s:prefix:%d" % (shortcut_id, index), "version": 1,
               "body": deepcopy(chain[0]["body"]), "head": deepcopy(row["head"])}
              for index, row in enumerate(chain[1:], start=2)]
    return {"schema": SCHEMA, "id": shortcut_id, "source": source, "rules": rules,
            "active": False, "uses": 0, "validated_contexts": [], "created_at": time.time()}


def applicable(shortcut, rules):
    by_id = {row.get("id"): row for row in rules}
    if not (isinstance(shortcut, dict) and shortcut.get("schema") == SCHEMA and shortcut.get("active")):
        return False
    for source in shortcut.get("source", []):
        current = by_id.get(source["id"])
        if (not current
                or current.get("version", current.get("rule_version")) != source["version"]
                or current.get("body") != source["body"] or current.get("head") != source["head"]):
            return False
    return True


def _metrics_sum(*rows):
    return {key: sum(row.get(key, 0) for row in rows) for key in {key for row in rows for key in row}}


def evaluate(facts, rules, shortcut, target=None):
    """Validate once, then run an equivalent prefix-preserving shortcut alone."""
    original_metrics, accelerated_metrics = {}, {}
    used = applicable(shortcut, rules)
    source_ids = {row["id"] for row in (shortcut.get("source") or [])}
    active_rules = ([row for row in rules if row.get("id") not in source_ids] + shortcut.get("rules", [])
                    if used else rules)
    context_id = _fingerprint(facts)
    cached = next((row for row in shortcut.get("validated_contexts", [])
                   if row.get("facts_sha256") == context_id), None)
    if used and cached:
        accelerated = closure(facts, active_rules, metrics=accelerated_metrics)
        original_metrics = deepcopy(cached["original_metrics"])
        validation_metrics = None
    else:
        original = closure(facts, rules, metrics=original_metrics)
        accelerated = closure(facts, active_rules, metrics=accelerated_metrics)
        validation_metrics = _metrics_sum(original_metrics, accelerated_metrics)
        if not used or set(original) != set(accelerated):
            used, accelerated = False, original
        elif used:
            shortcut.setdefault("validated_contexts", []).append({
                "facts_sha256": context_id, "original_metrics": deepcopy(original_metrics),
                "validated_at": time.time()})
    if used:
        shortcut["uses"] = int(shortcut.get("uses", 0)) + 1
    return {"facts": accelerated, "used": used, "shortcut": deepcopy(shortcut),
            "original_metrics": original_metrics, "accelerated_metrics": accelerated_metrics,
            "total_metrics": validation_metrics or deepcopy(accelerated_metrics),
            "validation_metrics": validation_metrics,
            "original_rule_ids": [row.get("id") for row in rules]}


def invalidate(shortcut, reason):
    """Persist an explicit counterexample/rollback without discarding proof."""
    shortcut["active"] = False
    shortcut["invalidated_at"] = time.time()
    shortcut["invalidation_reason"] = str(reason)
    return shortcut
