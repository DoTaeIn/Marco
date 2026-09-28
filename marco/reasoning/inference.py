"""Finite positive Horn-rule joins with replayable provenance, no text matching.

``closure`` is intentionally the small legacy projection used by the binary
KG.  ``closure_with_provenance`` adds an event/fact-id based proof ledger on
top of the same joins.  Keeping the two entry points separate means callers
that only need a binary fact do not accidentally depend on a particular proof
selection, while an explanation can retain *all* independent supports.
"""
from copy import deepcopy
from itertools import product


def variable(term):
    return isinstance(term, str) and term.startswith("?")


def leading_word_referent(subject, predicate, current):
    """The single known subject that ``subject`` names by its leading words.

    ``지연`` names ``지연 사과`` when that is the only ``지연 …`` holding
    ``predicate``. None when there is no such subject or more than one; the
    caller then fails exactly as it would without the declared ellipsis.
    """
    if not isinstance(subject, str) or not subject:
        return subject
    words = subject.split()
    keys = current if isinstance(current, dict) else {}
    candidates = sorted({s for s, p in keys if p == predicate and isinstance(s, str)
                         and s.split()[:len(words)] == words and len(s.split()) > len(words)})
    return candidates[0] if len(candidates) == 1 else subject


def current_facts(facts, mutable_predicates, numeric_updates=None):
    """Project ordered observations for declared single-valued properties.

    This is narrative-order state, not a temporal-language interpreter. Each
    replacement keeps both observations in its trace, while Horn closure sees
    only the final value, so obsolete locations cannot produce new conclusions.
    """
    numeric_updates = numeric_updates or {}
    numeric_targets = {spec["target"] for spec in numeric_updates.values()}
    stable, current, changes = [], {}, []
    for item in facts:
        modality = item.get("modality", "asserted")
        if modality not in {"asserted", "planned", "conditional"}:
            raise ValueError("invalid_fact_modality")
        if type(item.get("polarity", True)) is not bool:
            raise ValueError("invalid_fact_polarity")
        if modality != "asserted":
            changes.append({"operation": "nonactual_observation", "modality": modality,
                            "fact": item["triple"], "evidence": item["evidence"]})
            continue
        if not item.get("polarity", True):
            # Explicit denial constrains inference; it does not perform an event
            # or establish its converse. Preserve the original signed evidence.
            stable.append(item)
            continue
        subject, predicate, value = item["triple"]
        update = numeric_updates.get(predicate)
        if update:
            target = update["target"]
            if subject is None:
                candidates = [s for s, p in current if p == target]
                if len(candidates) != 1:
                    raise ValueError("ambiguous_quantity_subject")
                subject = candidates[0]
            resolved_from = None
            if (subject, target) not in current and item.get("resolve") == "leading_words":
                subject, resolved_from = leading_word_referent(subject, target, current), subject
            previous = current.get((subject, target))
            if not isinstance(value, str) or not value.isdecimal():
                raise ValueError("invalid_quantity_delta")
            delta = int(value) * update["factor"]
            if previous is None or previous.get("at_least") is not None:
                # A holder whose count was never said. Something added to it happened, and the holder
                # now has at least that much, but its count stays not known (count_unknown, the same
                # state as "has some"): neither zero nor the amount added. Taking away needs a known
                # count, or at least that much known to be there; otherwise it cannot be checked.
                at_least = (previous or {}).get("at_least", 0) + delta
                if at_least < 0:
                    raise ValueError("missing_initial_quantity")
                changes.append({"operation": "quantity_update", "subject": subject, "predicate": target,
                                "before": None, "after": None, "delta": delta, "evidence": item["evidence"],
                                **({"resolved_from": resolved_from} if resolved_from else {})})
                current[(subject, target)] = {**item, "triple": [subject, "count_unknown", "some"],
                                              "at_least": at_least}
                continue
            before = int(previous["triple"][2])
            after = before + delta
            if type(after) is not int or after < 0:
                raise ValueError("invalid_quantity_result")
            changes.append({"operation": "quantity_update", "subject": subject,
                            "predicate": target, "before": before, "after": after,
                            "delta": delta, "evidence": item["evidence"],
                            **({"resolved_from": resolved_from} if resolved_from else {})})
            current[(subject, target)] = {**previous, "triple": [subject, target, str(after)], "evidence": item["evidence"]}
            continue
        if predicate in numeric_targets and (not isinstance(value, str) or not value.isdecimal()):
            raise ValueError("invalid_initial_quantity")
        if predicate not in mutable_predicates:
            stable.append(item)
            continue
        # 생략된 상태 대상은 수량에만 있는 현상이 아니다. 위치·상태처럼
        # 선언된 단일값 관계도 앞 문맥에 같은 관계의 대상이 정확히 하나일 때만
        # 잇는다. 여러 후보면 최근 것을 고르지 않고 실행을 거부한다.
        if subject is None:
            candidates = [s for s, p in current if p == predicate]
            if len(candidates) != 1:
                raise ValueError("ambiguous_state_subject")
            subject = candidates[0]
            # 문맥으로 메운 것은 실행 때만의 지역 변수가 아니다. 이후 질의와
            # 근거 그래프도 같은 대상의 상태를 보아야 하므로, 원문 근거는 남긴
            # 채 확정 사실의 주어만 채운 꼴로 보관한다.
            item = {**item, "triple": [subject, predicate, value]}
        key = (subject, predicate)
        previous = current.get(key)
        if previous and previous.get("scope") != item.get("scope"):
            raise ValueError("ambiguous_property_scope")
        changes.append({"operation": "state_update", "subject": subject, "predicate": predicate,
                        # A count said after an unknown one is the count now, not a start to add to.
                        "before": previous["triple"][2] if previous and "at_least" not in previous else None,
                        "after": value, "evidence": item["evidence"]})
        current[key] = item
    return stable + list(current.values()), changes


def bind(pattern, fact, bindings):
    if len(pattern) != len(fact):
        return None
    result = dict(bindings)
    for term, value in zip(pattern, fact):
        if variable(term):
            if term in result and result[term] != value:
                return None
            result[term] = value
        elif term != value:
            return None
    return result


def closure(facts, rules, limit=2048, metrics=None):
    """Rules are range-restricted: conclusions cannot invent new entities.

    ``metrics`` is optional and records real rule scans/join candidates for
    benchmark comparison.  It never changes proof selection or inference.
    """
    if metrics is not None:
        metrics.clear(); metrics.update({"rule_scans": 0, "join_attempts": 0})
    forbidden = {tuple(item["triple"]) for item in facts
                 if item.get("modality", "asserted") == "asserted" and item.get("polarity") is False}
    known = {tuple(item["triple"]): {"fact": list(item["triple"]), "evidence": item["evidence"]}
             for item in facts if item.get("polarity", True)
             and item.get("modality", "asserted") == "asserted"
             and tuple(item["triple"]) not in forbidden}
    if len(known) > limit:
        raise ValueError("graph_limit")
    for rule in rules:
        grounded = {x for pattern in rule["body"] for x in pattern if variable(x)}
        if not rule["body"] or any(variable(x) and x not in grounded for x in rule["head"]):
            raise ValueError("unsafe_rule")
    changed = True
    while changed:
        changed = False
        snapshot = list(known)
        # Buckets preserve snapshot insertion order, hence the selected proof
        # remains stable. Bound subjects/objects are as useful as predicates.
        indexes = [{}, {}, {}]
        for fact in snapshot:
            for position, value in enumerate(fact):
                indexes[position].setdefault(value, []).append(fact)
        for rule in rules:
            if metrics is not None:
                metrics["rule_scans"] += 1
            counts = [0] * len(rule["body"])

            def matches(depth, bindings, parents):
                if depth == len(rule["body"]):
                    yield bindings, parents
                    return
                pattern = rule["body"][depth]
                buckets = []
                for position, term in enumerate(pattern):
                    if not variable(term) or term in bindings:
                        value = bindings[term] if variable(term) else term
                        buckets.append(indexes[position].get(value, []))
                candidates = min(buckets, key=len) if buckets else snapshot
                for fact in candidates:
                    if metrics is not None:
                        metrics["join_attempts"] += 1
                    merged = bind(pattern, fact, bindings)
                    if merged is not None:
                        counts[depth] += 1
                        if counts[depth] > limit * 4:
                            raise ValueError("join_limit")
                        yield from matches(depth + 1, merged, parents + [list(fact)])

            for bindings, parents in matches(0, {}, []):
                head = tuple(bindings[x] if variable(x) else x for x in rule["head"])
                if head not in known and head not in forbidden:
                    if len(known) >= limit:
                        raise ValueError("graph_limit")
                    known[head] = {"fact": list(head), "rule": rule["id"], "parents": parents}
                    changed = True
    return known


def proof(known, target):
    result, seen = [], set()

    def visit(fact):
        key = tuple(fact)
        if key in seen:
            return
        seen.add(key)
        record = known[key]
        for parent in record.get("parents", []):
            visit(parent)
        result.append(record)

    visit(target)
    return result


def closure_with_provenance(facts, rules, *, limit=2048, proof_limit=32,
                            search_limit=None):
    """Return binary-KG closure plus replayable, bounded proof bundles.

    A bundle identifies its premise fact ids, rule version and variable
    bindings.  Distinct joins producing the same conclusion remain distinct.
    Only facts available at the start of an iteration can justify a new fact;
    consequently a newly derived cycle cannot make a conclusion support
    itself.  Limits are reported as ``complete=False`` rather than presented
    as an exhaustive search.

    This is deliberately an in-memory companion to the existing Binary KG,
    not a hypergraph database.
    """
    search_limit = search_limit if search_limit is not None else limit * 8
    if limit < 1 or proof_limit < 1 or search_limit < 1:
        raise ValueError("invalid_provenance_limit")

    forbidden = {tuple(item["triple"]) for item in facts
                 if item.get("modality", "asserted") == "asserted"
                 and item.get("polarity") is False}
    known, bundles, searches = {}, {}, 0
    for index, item in enumerate(facts):
        if (not item.get("polarity", True)
                or item.get("modality", "asserted") != "asserted"):
            continue
        fact = tuple(item["triple"])
        if fact in forbidden:
            continue
        fact_id = str(item.get("id") or (item.get("evidence") or {}).get("fact_id")
                      or "fact:%d" % index)
        known.setdefault(fact, {"fact": list(fact), "evidence": deepcopy(item.get("evidence") or {})})
        bundles.setdefault(fact, []).append({"id": "support:%s" % fact_id,
                                             "kind": "asserted",
                                             "conclusion": list(fact),
                                             "premise_fact_ids": [fact_id],
                                             "rule": None, "rule_version": None,
                                             "bindings": {}, "valid": True})
    if len(known) > limit:
        return {"facts": known, "proof_bundles": bundles, "complete": False,
                "reason": "graph_limit", "searches": searches}

    def add_bundle(head, rule, bindings, parents):
        # One conclusion can have alternate proofs for an intermediate
        # premise.  Store their cartesian combinations as separate bundles;
        # flattening them into one list would falsely claim they were jointly
        # required and would make later invalidation imprecise.
        premise_options = []
        for parent in parents:
            parent_bundles = bundles.get(parent, [])
            # A derived parent may have several proofs.  We preserve each
            # distinct support path but cap the combinatorial expansion.
            if not parent_bundles:
                return False
            premise_options.append(parent_bundles[:proof_limit])
        rule_id = rule.get("id")
        version = rule.get("version", rule.get("rule_version"))
        rows = bundles.setdefault(head, [])
        combinations = product(*premise_options) if premise_options else [()]
        for selected in combinations:
            premise_ids = [bundle["id"] for bundle in selected]
            bundle = {"id": "derive:%s:%s:%s" %
                      (rule_id, version, json_key([list(head), sorted(bindings.items()), premise_ids])),
                      "kind": "derived", "conclusion": list(head),
                      "premise_fact_ids": premise_ids, "rule": rule_id,
                      "rule_version": version, "bindings": dict(bindings), "valid": True}
            if any(row["id"] == bundle["id"] for row in rows):
                continue
            if len(rows) >= proof_limit:
                return False
            rows.append(bundle)
        return True

    # A deterministic JSON-free key keeps the public record serialisable even
    # when bindings contain non-ASCII entity names.
    def invalid_rule(rule):
        grounded = {x for pattern in rule["body"] for x in pattern if variable(x)}
        return (not rule["body"] or
                any(variable(x) and x not in grounded for x in rule["head"]))

    if any(invalid_rule(rule) for rule in rules):
        raise ValueError("unsafe_rule")
    complete, changed = True, True
    while changed and complete:
        changed = False
        snapshot = list(known)
        indexes = [{}, {}, {}]
        for fact in snapshot:
            for position, value in enumerate(fact):
                indexes[position].setdefault(value, []).append(fact)
        for rule in rules:
            def matches(depth, bindings, parents):
                nonlocal searches, complete
                if depth == len(rule["body"]):
                    yield bindings, parents
                    return
                pattern = rule["body"][depth]
                buckets = []
                for position, term in enumerate(pattern):
                    if not variable(term) or term in bindings:
                        value = bindings[term] if variable(term) else term
                        buckets.append(indexes[position].get(value, []))
                candidates = min(buckets, key=len) if buckets else snapshot
                for fact in candidates:
                    searches += 1
                    if searches > search_limit:
                        complete = False
                        return
                    merged = bind(pattern, fact, bindings)
                    if merged is not None:
                        yield from matches(depth + 1, merged, parents + [fact])

            for bindings, parents in matches(0, {}, []):
                if not complete:
                    break
                head = tuple(bindings[x] if variable(x) else x for x in rule["head"])
                if head in forbidden:
                    continue
                if head not in known:
                    if len(known) >= limit:
                        complete = False
                        break
                    known[head] = {"fact": list(head), "rule": rule["id"],
                                   "parents": [list(row) for row in parents]}
                    changed = True
                # Existing facts can acquire another proof.  That is itself
                # a fixed-point change: an already-derived dependent may need
                # to be revisited so the new support path reaches it.  The
                # former code only repeated for a *new fact*, making bundle
                # propagation depend on rule order (x gained proof #2 after
                # x→z had already run).
                previous_bundle_count = len(bundles.get(head, []))
                if not add_bundle(head, rule, bindings, parents):
                    complete = False
                    break
                if len(bundles.get(head, [])) > previous_bundle_count:
                    changed = True
            if not complete:
                break
    return {"facts": known, "proof_bundles": bundles, "complete": complete,
            "reason": None if complete else "proof_or_search_limit", "searches": searches}


def json_key(value):
    """Small stable representation used solely in provenance identifiers."""
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
