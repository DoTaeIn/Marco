"""Finite positive Horn-rule joins with replayable provenance, no text matching."""


def variable(term):
    return isinstance(term, str) and term.startswith("?")


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
            previous = current.get((subject, target))
            if previous is None:
                raise ValueError("missing_initial_quantity")
            if not isinstance(value, str) or not value.isdecimal():
                raise ValueError("invalid_quantity_delta")
            before = int(previous["triple"][2])
            after = before + int(value) * update["factor"]
            if type(after) is not int or after < 0:
                raise ValueError("invalid_quantity_result")
            changes.append({"operation": "quantity_update", "subject": subject,
                            "predicate": target, "before": before, "after": after,
                            "delta": int(value) * update["factor"], "evidence": item["evidence"]})
            current[(subject, target)] = {**previous, "triple": [subject, target, str(after)], "evidence": item["evidence"]}
            continue
        if predicate in numeric_targets and (not isinstance(value, str) or not value.isdecimal()):
            raise ValueError("invalid_initial_quantity")
        if predicate not in mutable_predicates:
            stable.append(item)
            continue
        key = (subject, predicate)
        previous = current.get(key)
        if previous and previous.get("scope") != item.get("scope"):
            raise ValueError("ambiguous_property_scope")
        changes.append({"operation": "state_update", "subject": subject, "predicate": predicate,
                        "before": previous["triple"][2] if previous else None,
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


def closure(facts, rules, limit=2048):
    """Rules are range-restricted: conclusions cannot invent new entities."""
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
