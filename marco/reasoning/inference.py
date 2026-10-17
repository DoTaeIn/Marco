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
                            search_limit=None, max_bundle_id_bytes=None):
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
    cap = max_bundle_id_bytes
    if cap is not None and (type(cap) is not int or cap < 1):
        raise ValueError("invalid_bundle_id_limit")
    id_limited = False
    if cap is not None:
        # Opt-in only: exact native string types must be established before any
        # hashing/equality/startswith touches fact or rule terms.
        _check_native_id_material(facts, rules)

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
        if cap is None:
            fact_id = str(item.get("id") or (item.get("evidence") or {}).get("fact_id")
                          or "fact:%d" % index)
            support_id = None
        else:
            try:
                fact_id, support_id = _bounded_support_id(item, index, cap)
            except _BundleIdLimit:
                return {"facts": known, "proof_bundles": bundles, "complete": False,
                        "reason": "bundle_id_limit", "searches": searches}
        known.setdefault(fact, {"fact": list(fact), "evidence": deepcopy(item.get("evidence") or {})})
        bundles.setdefault(fact, []).append({"id": ("support:%s" % fact_id
                                                    if support_id is None else support_id),
                                             "kind": "asserted",
                                             "conclusion": list(fact),
                                             "premise_fact_ids": [fact_id],
                                             "rule": None, "rule_version": None,
                                             "bindings": {}, "valid": True})
    if len(known) > limit:
        return {"facts": known, "proof_bundles": bundles, "complete": False,
                "reason": "graph_limit", "searches": searches}

    def add_bundle(head, rule, bindings, parents):
        nonlocal id_limited
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
        if cap is None:
            rows = bundles.setdefault(head, [])
        else:
            # Opt-in: never create an empty proof row before a bounded
            # support has actually been admitted.
            rows = bundles.get(head, [])
        combinations = product(*premise_options) if premise_options else [()]
        for selected in combinations:
            premise_ids = [bundle["id"] for bundle in selected]
            if cap is None:
                bundle_id = "derive:%s:%s:%s" % (
                    rule_id, version, json_key([list(head), sorted(bindings.items()), premise_ids]))
            else:
                try:
                    bundle_id = _bounded_derived_id(rule_id, version, head, bindings, premise_ids, cap)
                except _BundleIdLimit:
                    id_limited = True
                    return False
            bundle = {"id": bundle_id,
                      "kind": "derived", "conclusion": list(head),
                      "premise_fact_ids": premise_ids, "rule": rule_id,
                      "rule_version": version, "bindings": dict(bindings), "valid": True}
            if any(row["id"] == bundle["id"] for row in rows):
                continue
            if len(rows) >= proof_limit:
                return False
            rows.append(bundle)
            if cap is not None:
                bundles[head] = rows
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
                new_head = head not in known
                if new_head:
                    if len(known) >= limit:
                        complete = False
                        break
                    if cap is None:
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
                admitted = add_bundle(head, rule, bindings, parents)
                if cap is not None and new_head and bundles.get(head):
                    # Opt-in: the head is admitted only after its first
                    # bounded support has been staged.
                    known[head] = {"fact": list(head), "rule": rule["id"],
                                   "parents": [list(row) for row in parents]}
                    changed = True
                if not admitted:
                    complete = False
                    break
                if len(bundles.get(head, [])) > previous_bundle_count:
                    changed = True
            if not complete:
                break
    return {"facts": known, "proof_bundles": bundles, "complete": complete,
            "reason": None if complete else (
                "bundle_id_limit" if id_limited else "proof_or_search_limit"),
            "searches": searches}


def json_key(value):
    """Small stable representation used solely in provenance identifiers."""
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class _BundleIdLimit(Exception):
    """The next provenance ID fragment would exceed the requested byte cap."""


_NATIVE_SCALARS = (type(None), bool, int, float, str, list, dict, tuple)


def _invalid_id_input():
    return ValueError("invalid_bundle_id_input")


def _native_truth(value):
    # Only exact builtin types: never run a custom __bool__.
    if type(value) not in _NATIVE_SCALARS:
        raise _invalid_id_input()
    return bool(value)


class _IdBuffer:
    """Append-only ID text whose UTF-8 size never exceeds ``left``."""

    def __init__(self, cap):
        self.left, self.parts = cap, []

    def put(self, text, escape=False):
        if type(text) is not str:
            raise _invalid_id_input()
        import json
        for start in range(0, len(text), 64):
            piece = text[start:start + 64]
            if escape:
                piece = json.dumps(piece, ensure_ascii=False)[1:-1]
            try:
                size = len(piece.encode("utf-8"))
            except UnicodeEncodeError:
                raise _invalid_id_input() from None
            if size > self.left:
                raise _BundleIdLimit()
            self.left -= size
            self.parts.append(piece)

    def put_json_str(self, text):
        self.put('"')
        self.put(text, True)
        self.put('"')

    def put_json_list(self, values):
        self.put("[")
        for position, value in enumerate(values):
            if position:
                self.put(",")
            self.put_json_str(value)
        self.put("]")

    def put_version(self, version):
        if type(version) is int:
            # Exact fit test before any decimal text exists: the native decimal
            # form (sign plus digits) fits iff abs(version) < 10 ** digits where
            # digits is the byte budget after a negative sign.  The cheap
            # bit_length bound settles values far below the boundary; only
            # the narrow ambiguous band pays for the exact power comparison,
            # whose size is bounded by the value itself, never by self.left.
            digits = self.left - (1 if version < 0 else 0)
            if digits < 1:
                raise _BundleIdLimit()  # no room for even one digit
            magnitude = -version if version < 0 else version
            if magnitude.bit_length() > 3 * digits and magnitude >= 10 ** digits:
                raise _BundleIdLimit()  # decimal text could not fit; do not build it
        self.put("%s" % version)

    def text(self):
        return "".join(self.parts)


def _bounded_support_id(item, index, cap):
    fact_id = item.get("id")
    if not _native_truth(fact_id):
        evidence = item.get("evidence")
        if not _native_truth(evidence):
            evidence = {}
        if type(evidence) is not dict:
            raise _invalid_id_input()
        fact_id = evidence.get("fact_id")
        if not _native_truth(fact_id):
            fact_id = "fact:%d" % index
    if type(fact_id) is not str:
        raise _invalid_id_input()
    buffer = _IdBuffer(cap)
    buffer.put("support:")
    buffer.put(fact_id)
    return fact_id, buffer.text()


def _bounded_derived_id(rule_id, version, head, bindings, parent_ids, cap):
    import math
    if type(rule_id) is not str:
        raise _invalid_id_input()
    if type(version) not in (type(None), bool, int, float, str):
        raise _invalid_id_input()
    if type(version) is float and not math.isfinite(version):
        raise _invalid_id_input()
    head = list(head)
    pairs = list(bindings.items())
    for value in head + parent_ids + [x for pair in pairs for x in pair]:
        if type(value) is not str:
            raise _invalid_id_input()
    pairs.sort()
    buffer = _IdBuffer(cap)
    buffer.put("derive:")
    buffer.put(rule_id)
    buffer.put(":")
    if type(version) is str:
        buffer.put(version)
    else:
        buffer.put_version(version)
    buffer.put(":[")
    buffer.put_json_list(head)
    buffer.put(",[")
    for position, pair in enumerate(pairs):
        if position:
            buffer.put(",")
        buffer.put_json_list(pair)
    buffer.put("],")
    buffer.put_json_list(parent_ids)
    buffer.put("]")
    return buffer.text()


_NATIVE_VERSIONS = (type(None), bool, int, float, str)


def _check_native_text(text):
    # Bounded UTF-8 validity check: never encode the whole string at once.
    if type(text) is not str:
        raise _invalid_id_input()
    for start in range(0, len(text), 64):
        try:
            text[start:start + 64].encode("utf-8")
        except UnicodeEncodeError:
            raise _invalid_id_input() from None


def _check_native_terms(terms):
    # Exact native sequence of exact native strings; no custom hooks run.
    if type(terms) not in (list, tuple):
        raise _invalid_id_input()
    for term in terms:
        if type(term) is not str:
            raise _invalid_id_input()
        _check_native_text(term)


def _check_native_id_material(facts, rules):
    """Opt-in structural guard: ID material must be exact native types.

    Runs only when a bundle-ID cap is requested, before any hashing,
    ``variable``/``startswith``, equality or truthiness touches fact or rule
    terms.  Evidence/source metadata is not serialized ID material and is not
    constrained beyond the native id/evidence.fact_id fallback structure.
    """
    import math
    if type(facts) not in (list, tuple) or type(rules) not in (list, tuple):
        raise _invalid_id_input()
    for item in facts:
        if type(item) is not dict:
            raise _invalid_id_input()
        # Exact native str keys first: an exact dict can still hold keys with
        # custom __hash__/__eq__, which membership or .get would otherwise run.
        for key in item:
            if type(key) is not str:
                raise _invalid_id_input()
        if "triple" not in item:
            raise _invalid_id_input()
        _check_native_terms(item["triple"])
        if "modality" in item and type(item["modality"]) is not str:
            raise _invalid_id_input()
        if "polarity" in item and type(item["polarity"]) is not bool:
            raise _invalid_id_input()
        fact_id = item.get("id")
        if type(fact_id) not in _NATIVE_SCALARS:
            raise _invalid_id_input()
        if not fact_id:
            evidence = item.get("evidence")
            if type(evidence) not in _NATIVE_SCALARS:
                raise _invalid_id_input()
            if evidence:
                if type(evidence) is not dict:
                    raise _invalid_id_input()
                for key in evidence:
                    if type(key) is not str:
                        raise _invalid_id_input()
                fact_id = evidence.get("fact_id")
                if type(fact_id) not in _NATIVE_SCALARS:
                    raise _invalid_id_input()
        if fact_id:
            if type(fact_id) is not str:
                raise _invalid_id_input()
            _check_native_text(fact_id)
    for rule in rules:
        if type(rule) is not dict:
            raise _invalid_id_input()
        for key in rule:
            if type(key) is not str:
                raise _invalid_id_input()
        if "body" not in rule or "head" not in rule:
            raise _invalid_id_input()
        if type(rule.get("id")) is not str:
            raise _invalid_id_input()
        _check_native_text(rule["id"])
        body = rule["body"]
        if type(body) not in (list, tuple):
            raise _invalid_id_input()
        for pattern in body:
            _check_native_terms(pattern)
        _check_native_terms(rule["head"])
        version = rule["version"] if "version" in rule else rule.get("rule_version")
        if type(version) not in _NATIVE_VERSIONS:
            raise _invalid_id_input()
        if type(version) is float and not math.isfinite(version):
            raise _invalid_id_input()
        if type(version) is str:
            _check_native_text(version)
