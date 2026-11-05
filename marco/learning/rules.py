"""Supervised rule induction from aligned, corrected proof examples.

Examples supply premises and a justified conclusion, not a handwritten rule.
This learns a hypothesis; a finite validation gate is not proof of universal truth.
"""
import hashlib
import json

from marco.reasoning.inference import closure, current_facts


def validate_example(example):
    triples = example.get("premises", []) + [example.get("conclusion")]
    if not example.get("premises") or len(triples) > 33:
        raise ValueError("invalid_proof_size")
    for triple in triples:
        if (not isinstance(triple, list) or len(triple) != 3 or
                any(not isinstance(x, str) or not x or x.startswith("?") for x in triple)):
            raise ValueError("expected_ground_triples")


def entities(examples):
    return {t[i] for e in examples for t in e["premises"] + [e["conclusion"]] for i in (0, 2)}


def induce(examples):
    if len(examples) < 2:
        raise ValueError("need_multiple_corrected_proofs")
    for example in examples:
        validate_example(example)
    size = len(examples[0]["premises"])
    if any(len(e["premises"]) != size for e in examples):
        raise ValueError("unaligned_proofs")
    columns, patterns = {}, []
    for position in range(size + 1):
        triples = [(e["premises"] + [e["conclusion"]])[position] for e in examples]
        if len({t[1] for t in triples}) != 1:
            raise ValueError("unaligned_predicates")
        pattern = []
        for index in range(3):
            values = tuple(t[index] for t in triples)
            if len(set(values)) == 1:
                pattern.append(values[0])
            else:
                if values not in columns:
                    columns[values] = "?v%d" % len(columns)
                pattern.append(columns[values])
        patterns.append(pattern)
    if not columns:
        raise ValueError("no_generalization")
    body, head = patterns[:-1], patterns[-1]
    bound = {x for p in body for x in p if x.startswith("?")}
    if any(x.startswith("?") and x not in bound for x in head):
        raise ValueError("unbound_conclusion")
    payload = {"body": body, "head": head}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return {"id": "learned-" + digest, **payload}


def entails(model, example):
    facts = [{"triple": t, "evidence": {"example": example.get("id"), "index": i}}
             for i, t in enumerate(example["premises"])]
    facts, _ = current_facts(facts, model.get("mutable_predicates", []), model.get("numeric_updates", {}))
    return tuple(example["conclusion"]) in closure(facts, model["rules"])


def propose(model, corrections, validation):
    """Do not mutate a model or read evaluation labels during candidate induction."""
    candidate = induce(corrections)
    if not validation or {e.get("expected") for e in validation} != {True, False}:
        raise ValueError("need_positive_and_negative_validation")
    for example in validation:
        validate_example(example)
        if type(example.get("expected")) is not bool:
            raise ValueError("expected_boolean_label")
    if entities(corrections) & entities(validation):
        raise ValueError("training_validation_entity_overlap")
    existing = model["rules"]
    updated = dict(model, rules=existing + [candidate])
    rows = []
    for example in validation:
        before, after = entails(model, example), entails(updated, example)
        rows.append({"id": example.get("id"), "expected": example["expected"],
                     "before": before, "after": after})
    accepted = (all(entails(updated, e) for e in corrections)
                and all(r["after"] == r["expected"] for r in rows)
                and any(r["before"] != r["expected"] for r in rows)
                and not any(r["before"] == r["expected"] and r["after"] != r["expected"] for r in rows))
    return {"accepted": accepted, "candidate": candidate, "validation": rows,
            "reason": "validated_transfer" if accepted else "no_improvement_or_validation_failure",
            "supervision": "aligned corrected proofs; finite positive and negative validation"}


# V72 append-only: pure bounded supervised rule experience admission/falsification gate.
# Reuses unchanged induce/propose and native closure/current_facts. No I/O, no mutation.

import unicodedata as _xr_unicodedata

_XR_ADMISSION_SCHEMA = 'marco-rule-experience-admission-v1'
_XR_FALSIFY_SCHEMA = 'marco-rule-experience-falsification-v1'
_XR_SUPERVISION = 'aligned corrected proofs; finite positive and negative validation'
_XR_FALSIFY_SUPERVISION = 'fresh explicit negative corrected proof; finite falsification'
_XR_ACCEPT = 'validated_transfer'
_XR_REJECT = 'no_improvement_or_validation_failure'
_XR_MAX_BASE = 2
_XR_MAX_BODY = 2
_XR_MAX_VARS = 4
_XR_LIMIT = 64
_XR_DEPTH = 16
_XR_ITEMS = 4096
_XR_BYTES = 32768
_XR_MIN_EX = 2
_XR_MAX_EX = 8
_XR_VAR_HEAD = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_'
_XR_VAR_TAIL = _XR_VAR_HEAD + '0123456789'


def _xr_fail(code):
    raise ValueError(code)


def _xr_canon(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


def _xr_sha(value):
    try:
        return hashlib.sha256(_xr_canon(value).encode('utf-8')).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError):
        _xr_fail('invalid_input')


def _xr_detach(value, code):
    count = [0]

    def walk(v, depth):
        if depth > _XR_DEPTH:
            _xr_fail(code)
        count[0] += 1
        if count[0] > _XR_ITEMS:
            _xr_fail(code)
        t = type(v)
        if v is None or t is bool or t is int or t is str:
            return v
        if t is list:
            return [walk(x, depth + 1) for x in v]
        if t is dict:
            out = {}
            for k, x in v.items():
                if type(k) is not str:
                    _xr_fail(code)
                out[k] = walk(x, depth + 1)
            return out
        _xr_fail(code)

    try:
        detached = walk(value, 0)
    except RecursionError:
        _xr_fail(code)
    try:
        size = len(_xr_canon(detached).encode('utf-8'))
    except (TypeError, ValueError, UnicodeEncodeError):
        _xr_fail(code)
    if size > _XR_BYTES:
        _xr_fail(code)
    return detached


def _xr_clean_text(text, limit, code):
    if type(text) is not str or not text or text != text.strip() or len(text) > limit:
        _xr_fail(code)
    for c in text:
        cat = _xr_unicodedata.category(c)
        if cat[0] == 'C' or cat in ('Zl', 'Zp'):
            _xr_fail(code)
    try:
        text.encode('utf-8')
    except UnicodeEncodeError:
        _xr_fail(code)
    return text


def _xr_term(term, code):
    _xr_clean_text(term, 128, code)
    if '$' in term or '?' in term:
        _xr_fail(code)
    return term


def _xr_id(value, code):
    return _xr_clean_text(value, 64, code)


def _xr_ground(triple, code):
    if type(triple) is not list or len(triple) != 3:
        _xr_fail(code)
    return [_xr_term(t, code) for t in triple]


def _xr_example(example, labelled, code):
    keys = {'id', 'premises', 'conclusion', 'expected'} if labelled else {
        'id', 'premises', 'conclusion'}
    if type(example) is not dict or set(example) != keys:
        _xr_fail(code)
    eid = _xr_id(example['id'], code)
    premises = example['premises']
    if type(premises) is not list or not 1 <= len(premises) <= 2:
        _xr_fail(code)
    ps = [_xr_ground(p, code) for p in premises]
    if len({tuple(p) for p in ps}) != len(ps):
        _xr_fail(code)
    conclusion = _xr_ground(example['conclusion'], code)
    if tuple(conclusion) in {tuple(p) for p in ps}:
        _xr_fail(code)
    out = {'id': eid, 'premises': ps, 'conclusion': conclusion}
    if labelled:
        if type(example['expected']) is not bool:
            _xr_fail(code)
        out['expected'] = example['expected']
    return out


def _xr_rule_term(term, names, code):
    if type(term) is not str:
        _xr_fail(code)
    if term.startswith('?'):
        if (not 2 <= len(term) <= 16 or term[1] not in _XR_VAR_HEAD
                or any(c not in _XR_VAR_TAIL for c in term[2:])):
            _xr_fail(code)
        names.add(term)
        return term
    return _xr_term(term, code)


def _xr_pattern(pattern, names, code):
    if type(pattern) is not list or len(pattern) != 3:
        _xr_fail(code)
    s = _xr_rule_term(pattern[0], names, code)
    p = _xr_term(pattern[1], code)
    o = _xr_rule_term(pattern[2], names, code)
    return [s, p, o]


def _xr_rule(rule, code):
    if type(rule) is not dict or set(rule) != {'id', 'body', 'head'}:
        _xr_fail(code)
    rid = _xr_id(rule['id'], code)
    body = rule['body']
    if type(body) is not list or not 1 <= len(body) <= _XR_MAX_BODY:
        _xr_fail(code)
    body_vars, head_vars = set(), set()
    nbody = [_xr_pattern(p, body_vars, code) for p in body]
    head = _xr_pattern(rule['head'], head_vars, code)
    if not head_vars <= body_vars or len(body_vars | head_vars) > _XR_MAX_VARS:
        _xr_fail(code)
    return {'id': rid, 'body': nbody, 'head': head}


def _xr_base_rules(base_rules):
    rs = _xr_detach(base_rules, 'invalid_base_rules')
    if type(rs) is not list or len(rs) > _XR_MAX_BASE:
        _xr_fail('invalid_base_rules')
    out = [_xr_rule(r, 'invalid_base_rules') for r in rs]
    if len({r['id'] for r in out}) != len(out):
        _xr_fail('invalid_base_rules')
    return out


def _xr_payload(payload):
    p = _xr_detach(payload, 'invalid_payload')
    if type(p) is not dict or set(p) != {'corrections', 'validation'}:
        _xr_fail('invalid_payload')
    corr, val = p['corrections'], p['validation']
    if (type(corr) is not list or type(val) is not list
            or not _XR_MIN_EX <= len(corr) <= _XR_MAX_EX
            or not _XR_MIN_EX <= len(val) <= _XR_MAX_EX):
        _xr_fail('invalid_payload')
    cs = [_xr_example(e, False, 'invalid_payload') for e in corr]
    vs = [_xr_example(e, True, 'invalid_payload') for e in val]
    ids = [e['id'] for e in cs + vs]
    if len(set(ids)) != len(ids):
        _xr_fail('invalid_payload')
    if {e['expected'] for e in vs} != {True, False}:
        _xr_fail('need_positive_and_negative_validation')
    if entities(cs) & entities(vs):
        _xr_fail('training_validation_entity_overlap')
    return {'corrections': cs, 'validation': vs}


def _xr_native(example, rules):
    facts = [{'triple': list(t), 'evidence': {'example': example['id'], 'index': i}}
             for i, t in enumerate(example['premises'])]
    facts, _ = current_facts(facts, [], {})
    try:
        known = closure(facts, [dict(r) for r in rules], limit=_XR_LIMIT)
    except ValueError as exc:
        if str(exc) in ('graph_limit', 'join_limit'):
            _xr_fail('capacity')
        raise
    except RecursionError:
        _xr_fail('capacity')
    return tuple(example['conclusion']) in known


def _xr_admit(base_rules, payload):
    base = _xr_base_rules(base_rules)
    p = _xr_payload(payload)
    corr, val = p['corrections'], p['validation']
    sizes = {len(e['premises']) for e in corr}
    if len(sizes) != 1:
        _xr_fail('unaligned_proofs')
    induced = induce(_xr_detach(corr, 'invalid_payload'))
    candidate = _xr_rule(_xr_detach(induced, 'invalid_candidate'), 'invalid_candidate')
    if _xr_canon(candidate) != _xr_canon(induced):
        _xr_fail('invalid_candidate')
    if candidate['id'] in {r['id'] for r in base}:
        _xr_fail('candidate_id_collision')
    updated = base + [candidate]
    for e in corr + val:
        _xr_native(e, base)
        _xr_native(e, updated)
    result = propose({'rules': _xr_detach(base, 'invalid_base_rules')},
                     _xr_detach(corr, 'invalid_payload'), _xr_detach(val, 'invalid_payload'))
    if _xr_canon(result.get('candidate')) != _xr_canon(candidate):
        _xr_fail('candidate_mismatch')
    accepted = result.get('accepted')
    if type(accepted) is not bool:
        _xr_fail('invalid_admission')
    rows = []
    for r in result.get('validation'):
        row = {'id': r['id'], 'expected': r['expected'], 'before': r['before'],
               'after': r['after']}
        if (type(row['id']) is not str or type(row['expected']) is not bool
                or type(row['before']) is not bool or type(row['after']) is not bool):
            _xr_fail('invalid_admission')
        rows.append(row)
    report = {'schema': _XR_ADMISSION_SCHEMA, 'accepted': accepted,
              'reason': _XR_ACCEPT if accepted else _XR_REJECT,
              'base_rules_sha256': _xr_sha(base), 'payload_sha256': _xr_sha(p),
              'candidate_sha256': _xr_sha(candidate), 'candidate': candidate,
              'validation': rows, 'supervision': _XR_SUPERVISION}
    return base, p, candidate, _xr_detach(report, 'invalid_admission')


def propose_experience_rule(base_rules, payload):
    """Closed bounded admission report; finite supervised gate, not universal truth."""
    return _xr_admit(base_rules, payload)[3]


def falsify_experience_rule(base_rules, payload, candidate, negative_example):
    """Closed falsification report from a fresh explicit negative corrected proof."""
    base, p, generated, report = _xr_admit(base_rules, payload)
    if report['accepted'] is not True:
        _xr_fail('candidate_not_accepted')
    supplied = _xr_detach(candidate, 'invalid_candidate')
    if _xr_canon(supplied) != _xr_canon(generated):
        _xr_fail('candidate_mismatch')
    negative = _xr_example(_xr_detach(negative_example, 'invalid_negative'), True,
                           'invalid_negative')
    if negative['expected'] is not False:
        _xr_fail('invalid_negative')
    if entities([negative]) & entities(p['corrections'] + p['validation']):
        _xr_fail('negative_entity_overlap')
    before = _xr_native(negative, base)
    after = _xr_native(negative, base + [generated])
    withdraw = (before is False) and (after is True)
    out = {'schema': _XR_FALSIFY_SCHEMA, 'withdraw': withdraw,
           'reason': 'attributed_counterexample' if withdraw else 'not_attributed_counterexample',
           'base_rules_sha256': _xr_sha(base), 'payload_sha256': _xr_sha(p),
           'candidate_sha256': _xr_sha(generated), 'negative_sha256': _xr_sha(negative),
           'before': before, 'after': after, 'supervision': _XR_FALSIFY_SUPERVISION}
    return _xr_detach(out, 'invalid_report')
