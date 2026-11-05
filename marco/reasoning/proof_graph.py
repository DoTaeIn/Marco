import hashlib
import json

from marco.reasoning import inference
from marco.reasoning.graph_contract import SCHEMA as FRAME_SCHEMA, validate_frame
from marco.reasoning.graph_vm import validate_value

SCHEMA = 'marco-reasoning-proof-v1'
_DONE = ('proved', 'unresolved', 'contradicted', 'conflict')
_CUT = ('bundle_id_limit', 'proof_or_search_limit', 'graph_limit',
        'closure_incomplete', 'record_graph_limit', 'compact_id_collision')
_RECORD = {'schema', 'facts_sha256', 'rules_sha256', 'target', 'limits',
           'status', 'complete', 'reason', 'frame'}
_ASSERTED = {'kind', 'conclusion', 'fact_id', 'bindings', 'parents'}
_DERIVED = {'kind', 'conclusion', 'rule', 'rule_version', 'bindings', 'parents'}
_SELECT_ERRORS = (KeyError, IndexError, TypeError, AttributeError, RecursionError)


class _Overflow(Exception):
    pass


def _c(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _h(value):
    return hashlib.sha256(_c(value).encode('utf-8')).hexdigest()


def _text(v, n):
    return type(v) is str and 0 < len(v) <= n


def _triple(t, ground=False):
    return (type(t) is list and len(t) == 3
            and all(_text(x, 128) and not (ground and x[0] == '?') for x in t))


def _limits(limit, proof_limit, search_limit):
    out = {}
    for name, cap, value in (('limit', 32, limit), ('proof_limit', 4, proof_limit),
                             ('search_limit', 1024, search_limit)):
        if type(value) is not int or not 1 <= value <= cap:
            raise ValueError('invalid_limit')
        out[name] = value
    return out


def _inputs(facts, rules, target):
    facts, rules, target = validate_value(facts), validate_value(rules), validate_value(target)
    if (type(facts) is not list or len(facts) > 32 or type(rules) is not list
            or len(rules) > 16 or not _triple(target, True)):
        raise ValueError('invalid_input')
    ids = set()
    for f in facts:
        if (type(f) is not dict or not {'id', 'triple', 'evidence'} <= f.keys()
                or not f.keys() <= {'id', 'triple', 'evidence', 'polarity', 'modality'}
                or not _text(f['id'], 64) or f['id'] in ids
                or not _triple(f['triple'], True)
                or type(f.get('polarity', True)) is not bool
                or f.get('modality', 'asserted') not in ('asserted', 'planned', 'conditional')):
            raise ValueError('invalid_fact')
        ids.add(f['id'])
    ids = set()
    for r in rules:
        if (type(r) is not dict or r.keys() != {'id', 'version', 'body', 'head'}
                or not _text(r['id'], 64) or r['id'] in ids
                or not (type(r['version']) is int or _text(r['version'], 32))
                or type(r['body']) is not list or not 1 <= len(r['body']) <= 3
                or not all(_triple(p) for p in r['body']) or not _triple(r['head'])):
            raise ValueError('invalid_rule')
        ids.add(r['id'])
    return facts, rules, target


def _neg(f):
    return f.get('polarity', True) is False and f.get('modality', 'asserted') == 'asserted'


def _witness(facts, target):
    neg = any(_neg(f) and f['triple'] == target for f in facts)
    pos = any(f.get('polarity', True) is True and f.get('modality', 'asserted') == 'asserted'
              and f['triple'] == target for f in facts)
    return neg, pos


def _unsafe_ids(rules):
    ids = []
    for r in rules:
        seen = {t for p in r['body'] for t in p}
        if any(inference.variable(t) and t not in seen for t in r['head']):
            ids.append(r['id'])
    return ids


def _unsafe(rules):
    return bool(_unsafe_ids(rules))


def _close(facts, rules, lim):
    return inference.closure_with_provenance(
        facts, rules, limit=lim['limit'], proof_limit=lim['proof_limit'],
        search_limit=lim['search_limit'], max_bundle_id_bytes=512, compact_ids=True)


def _frame(ft, rt, query, proofs):
    kinds = {i: v['kind'] for i, v in proofs}
    nodes = [{'id': 'query', 'type': 'type:query', 'scope': 'scope:proof', 'value': query}]
    edges = []
    for nid, v in proofs:
        nodes.append({'id': nid, 'type': 'type:proof', 'scope': 'scope:proof', 'value': v})
        for n, p in enumerate(v['parents']):
            ev = ['span:rules'] + (['span:facts'] if kinds.get(p) == 'asserted' else [])
            edges.append({'id': 'edge:%s:%d' % (nid, n), 'source': p,
                          'relation': 'premise:%d' % n, 'target': nid,
                          'scope': 'scope:proof', 'evidence': ev})
    if query['root'] is not None:
        edges.append({'id': 'edge:root', 'source': query['root'], 'relation': 'root',
                      'target': 'query', 'scope': 'scope:proof',
                      'evidence': ['span:facts', 'span:rules']})
    packets = [] if ft is None else [('facts', ft), ('rules', rt)]
    return {'schema': FRAME_SCHEMA, 'nodes': nodes, 'edges': edges,
            'sources': [{'id': 'source:' + k, 'text': t,
                         'sha256': hashlib.sha256(t.encode('utf-8')).hexdigest()}
                        for k, t in packets],
            'spans': [{'id': 'span:' + k, 'source': 'source:' + k, 'start': 0, 'end': len(t)}
                      for k, t in packets]}


def _record(ctx, status, reason, root=None, proofs=()):
    facts, rules, target, lim = ctx
    ft, rt = _c(facts), _c(rules)
    q = {'target': target, 'status': status, 'reason': reason, 'root': root,
         'failed_rules': _unsafe_ids(rules) if status == 'invalid' else []}
    try:
        frame = validate_frame(_frame(ft, rt, q, list(proofs)))
    except ValueError:
        status, reason = 'incomplete', 'record_graph_limit'
        q = {'target': target, 'status': status, 'reason': reason, 'root': None, 'failed_rules': []}
        frame = validate_frame(_frame(None, None, q, []))
    return {'schema': SCHEMA, 'facts_sha256': _h(facts), 'rules_sha256': _h(rules),
            'target': target, 'limits': lim, 'status': status,
            'complete': status in _DONE, 'reason': reason, 'frame': frame}


def _select(result, target):
    rows = result['proof_bundles'].get(target) or []
    if not rows or type(rows[0]) is not dict or rows[0].get('conclusion') != list(target):
        raise _Overflow()
    roots, order = _select_ids(result, [rows[0].get('id')])
    return roots[0], order


def _select_ids(result, starts):
    # Exact named supports only: never substitutes another proof of the same conclusion.
    bundles = result['proof_bundles']
    index = {}
    for group in bundles.values():
        for b in group:
            if type(b) is not dict or type(b.get('id')) is not str:
                raise _Overflow()
            if index.setdefault(b['id'], b) is not b and _c(index[b['id']]) != _c(b):
                raise _Overflow()
    seen, order, memo, active = {}, [], {}, set()

    def walk(b):
        bid = b['id']
        if bid in memo:
            return memo[bid]
        ids = b.get('premise_fact_ids')
        if (bid in active or b.get('valid') is not True
                or not _triple(b.get('conclusion'), True)
                or type(ids) is not list or not ids):
            raise _Overflow()
        active.add(bid)
        if b.get('kind') == 'asserted':
            if len(ids) != 1 or type(ids[0]) is not str:
                raise _Overflow()
            value = {'kind': 'asserted', 'conclusion': list(b['conclusion']),
                     'fact_id': ids[0], 'bindings': {}, 'parents': []}
        elif b.get('kind') == 'derived':
            if any(type(p) is not str or p not in index for p in ids):
                raise _Overflow()
            parents = [walk(index[p]) for p in ids]
            value = {'kind': 'derived', 'conclusion': list(b['conclusion']),
                     'rule': b['rule'], 'rule_version': b['rule_version'],
                     'bindings': dict(b['bindings']), 'parents': parents}
        else:
            raise _Overflow()
        nid = 'proof:' + _h(value)
        if nid in seen and _c(seen[nid]) != _c(value):
            raise _Overflow()
        if nid not in seen:
            seen[nid] = value
            order.append((nid, value))
            if len(order) > 16:
                raise _Overflow()
        active.discard(bid)
        memo[bid] = nid
        return nid

    roots = []
    for sid in starts:
        if type(sid) is not str or sid not in index:
            raise _Overflow()
        roots.append(walk(index[sid]))
    return roots, order


def build_proof_graph(facts, rules, target, *, limit=32, proof_limit=4, search_limit=256):
    facts, rules, target = _inputs(facts, rules, target)
    lim = _limits(limit, proof_limit, search_limit)
    ctx = (facts, rules, target, lim)
    if _unsafe(rules):
        return _record(ctx, 'invalid', 'unsafe_rule')
    result = _close(facts, rules, lim)
    if not result['complete']:
        why = result.get('reason')
        return _record(ctx, 'incomplete', why if why in _CUT else 'closure_incomplete')
    neg, pos = _witness(facts, target)
    if neg:
        return _record(ctx, 'conflict' if pos else 'contradicted', None)
    if tuple(target) not in result['facts']:
        return _record(ctx, 'unresolved', None)
    try:
        root, proofs = _select(result, tuple(target))
    except (_Overflow,) + _SELECT_ERRORS:
        return _record(ctx, 'incomplete', 'record_graph_limit')
    return _record(ctx, 'proved', None, root, proofs)


def _node_ok(v, byfact, byrule, nodes, denied):
    c = v['conclusion']
    if tuple(c) in denied:
        return False
    if v.get('kind') == 'asserted':
        fid = v.get('fact_id')
        f = byfact.get(fid) if type(fid) is str else None
        return (v.keys() == _ASSERTED and f is not None and f['triple'] == c
                and f.get('polarity', True) is True
                and f.get('modality', 'asserted') == 'asserted'
                and v['bindings'] == {} and v['parents'] == [])
    if v.get('kind') != 'derived' or v.keys() != _DERIVED:
        return False
    r = byrule.get(v['rule']) if type(v['rule']) is str else None
    ps = v['parents']
    if (r is None or type(v['rule_version']) is not type(r['version'])
            or v['rule_version'] != r['version'] or type(ps) is not list
            or len(ps) != len(r['body']) or type(v['bindings']) is not dict
            or not all(type(p) is str and p in nodes for p in ps)):
        return False
    b = {}
    for pattern, p in zip(r['body'], ps):
        b = inference.bind(pattern, nodes[p]['conclusion'], b)
        if b is None:
            return False
    head = [b[t] if inference.variable(t) else t for t in r['head']]
    return b == v['bindings'] and head == c


def _post(root, nodes):
    out, state = [], {}

    def go(n):
        if state.get(n) == 1:
            raise ValueError('cycle')
        if state.get(n) == 2:
            return
        state[n] = 1
        for p in nodes[n]['parents']:
            go(p)
        state[n] = 2
        out.append(n)

    go(root)
    return out


def verify_proof_graph(record, facts, rules, target):
    facts, rules, target = _inputs(facts, rules, target)

    def out(valid, verified, reason):
        return {'valid': valid, 'conclusion_verified': verified, 'reason': reason}

    def bad(code):
        return out(False, False, code)

    try:
        record = validate_value(record)
    except ValueError:
        return bad('malformed_record')
    if type(record) is not dict or record.keys() != _RECORD or record['schema'] != SCHEMA:
        return bad('malformed_record')
    lim = record['limits']
    try:
        if type(lim) is not dict or lim.keys() != {'limit', 'proof_limit', 'search_limit'}:
            raise ValueError('limits')
        _limits(**lim)
    except ValueError:
        return bad('malformed_limits')
    ft, rt = _c(facts), _c(rules)
    status, reason = record['status'], record['reason']
    if type(status) is not str or (reason is not None and type(reason) is not str):
        return bad('malformed_record')
    if record['facts_sha256'] != _h(facts) or record['rules_sha256'] != _h(rules):
        return bad('hash_mismatch')
    if record['target'] != target:
        return bad('target_mismatch')
    if (status not in _DONE + ('invalid', 'incomplete') or type(record['complete']) is not bool
            or record['complete'] != (status in _DONE)
            or reason not in {'invalid': ('unsafe_rule',), 'incomplete': _CUT}.get(status, (None,))):
        return bad('malformed_record')
    try:
        frame = validate_frame(record['frame'])
    except ValueError:
        return bad('malformed_frame')

    def same(other):
        return _c(other) == _c(frame)

    def query(root=None):
        return {'target': target, 'status': status, 'reason': reason, 'root': root,
         'failed_rules': _unsafe_ids(rules) if status == 'invalid' else []}

    base = _frame(ft, rt, query(), [])
    unsafe = _unsafe(rules)
    if status == 'invalid':
        return bad('unsafe_rule') if unsafe and same(base) else bad('tampered')
    if unsafe:
        return bad('tampered')
    if status == 'incomplete':
        if same(base) or same(_frame(None, None, query(), [])):
            return bad('incomplete')
        return bad('tampered')
    neg, pos = _witness(facts, target)
    if status in ('contradicted', 'conflict'):
        if not neg or pos != (status == 'conflict') or not same(base):
            return bad('witness_mismatch')
        return out(True, False, status)
    if status == 'unresolved':
        if neg or not same(base):
            return bad('tampered')
        again = _close(facts, rules, lim)
        if not again['complete']:
            return bad('incomplete')
        if tuple(target) in again['facts']:
            return bad('absence_refuted')
        return out(True, False, 'unresolved')
    qs = [n for n in frame['nodes'] if n['id'] == 'query']
    nodes = {n['id']: n['value'] for n in frame['nodes'] if n['id'] != 'query'}
    root = qs[0]['value'].get('root') if len(qs) == 1 and type(qs[0]['value']) is dict else None
    if (type(root) is not str or root not in nodes or not 1 <= len(nodes) <= 16
            or not all(type(v) is dict and _triple(v.get('conclusion'), True)
                       for v in nodes.values())):
        return bad('tampered')
    byfact = {f['id']: f for f in facts}
    byrule = {r['id']: r for r in rules}
    denied = {tuple(f['triple']) for f in facts if _neg(f)}
    for nid, v in nodes.items():
        if nid != 'proof:' + _h(v) or not _node_ok(v, byfact, byrule, nodes, denied):
            return bad('bad_node')
    if nodes[root]['conclusion'] != target:
        return bad('root_mismatch')
    try:
        order = _post(root, nodes)
    except (ValueError, KeyError, TypeError, RecursionError):
        return bad('cycle')
    if len(order) != len(nodes):
        return bad('unreferenced')
    if not same(_frame(ft, rt, query(root), [(n, nodes[n]) for n in order])):
        return bad('tampered')
    return out(True, True, 'proved')


def _route(rule_ids, rules):
    # Route is a bounded computation selection only; it never removes knowledge.
    try:
        ids = validate_value(rule_ids)
    except (ValueError, TypeError):
        raise ValueError('invalid_route')
    if type(ids) is not list or len(ids) > 16:
        raise ValueError('invalid_route')
    byid = {r['id']: r for r in rules}
    seen, out = set(), []
    for i in ids:
        if not _text(i, 64) or i in seen or i not in byid:
            raise ValueError('invalid_route')
        seen.add(i)
        out.append(byid[i])
    return out


def build_route_proof_graph(facts, rules, target, *, rule_ids, limit=32, proof_limit=4,
                            search_limit=256):
    facts, rules, target = _inputs(facts, rules, target)
    lim = _limits(limit, proof_limit, search_limit)
    selected = _route(rule_ids, rules)
    ctx = (facts, rules, target, lim)
    if _unsafe(rules):
        return _record(ctx, 'invalid', 'unsafe_rule')
    neg, pos = _witness(facts, target)
    if neg:
        return _record(ctx, 'conflict' if pos else 'contradicted', None)
    result = _close(facts, selected, lim)
    if not result['complete']:
        why = result.get('reason')
        return _record(ctx, 'incomplete', why if why in _CUT else 'closure_incomplete')
    if tuple(target) not in result['facts']:
        return _record(ctx, 'incomplete', 'closure_incomplete')
    try:
        root, proofs = _select(result, tuple(target))
    except (_Overflow,) + _SELECT_ERRORS:
        return _record(ctx, 'incomplete', 'record_graph_limit')
    return _record(ctx, 'proved', None, root, proofs)


_CX_SCHEMA = 'marco-rule-counterexample-v1'
_CX = {'id', 'schema', 'facts_sha256', 'rules_sha256', 'target', 'rule_ids', 'limits',
       'rule', 'rule_version', 'head', 'bindings', 'negative_fact_id', 'parents', 'proofs'}


def _close_capture(facts, rules, lim):
    return inference.closure_with_provenance(
        facts, rules, limit=lim['limit'], proof_limit=lim['proof_limit'],
        search_limit=lim['search_limit'], max_bundle_id_bytes=512, compact_ids=True,
        capture_rejections=True)


def _reviewed_record(ctx, result, routed, neg, pos):
    # Same status order as build_proof_graph (routed=False) or
    # build_route_proof_graph (routed=True), over the single closure result.
    target = ctx[2]
    if routed and neg:
        return _record(ctx, 'conflict' if pos else 'contradicted', None)
    if not result['complete']:
        why = result.get('reason')
        return _record(ctx, 'incomplete', why if why in _CUT else 'closure_incomplete')
    if neg:
        return _record(ctx, 'conflict' if pos else 'contradicted', None)
    if tuple(target) not in result['facts']:
        if routed:
            return _record(ctx, 'incomplete', 'closure_incomplete')
        return _record(ctx, 'unresolved', None)
    try:
        root, proofs = _select(result, tuple(target))
    except (_Overflow,) + _SELECT_ERRORS:
        return _record(ctx, 'incomplete', 'record_graph_limit')
    return _record(ctx, 'proved', None, root, proofs)


def _counterexample(result, row, facts, rules, target, rule_ids, lim):
    support = row['premise_fact_ids']
    if type(support) is not list:
        raise _Overflow()
    parents, order = _select_ids(result, list(support))
    body = {'schema': _CX_SCHEMA, 'facts_sha256': _h(facts), 'rules_sha256': _h(rules),
            'target': target, 'rule_ids': rule_ids, 'limits': lim,
            'rule': row['rule'], 'rule_version': row['rule_version'], 'head': row['head'],
            'bindings': row['bindings'], 'negative_fact_id': row['negative_fact_id'],
            'parents': parents, 'proofs': [{'id': n, 'value': v} for n, v in order]}
    return json.loads(_c(dict(body, id='counterexample:' + _h(body))))


def build_reviewed_route_proof_graph(facts, rules, target, *, rule_ids=None, limit=32,
                                     proof_limit=4, search_limit=256):
    facts, rules, target = _inputs(facts, rules, target)
    lim = _limits(limit, proof_limit, search_limit)
    selected = rules if rule_ids is None else _route(rule_ids, rules)
    ids = None if rule_ids is None else [r['id'] for r in selected]
    ctx = (facts, rules, target, lim)
    if _unsafe(rules):
        return {'record': _record(ctx, 'invalid', 'unsafe_rule'),
                'counterexamples': [], 'counterexamples_complete': False}
    neg, pos = _witness(facts, target)
    result = _close_capture(facts, selected, lim)
    record = _reviewed_record(ctx, result, rule_ids is not None, neg, pos)
    complete = result['complete'] is True and result.get('rejection_capture_complete') is True
    certs, seen = [], {}
    for row in result.get('rejected_derivations') or []:
        try:
            cert = _counterexample(result, row, facts, rules, target, ids, lim)
            body = _c({k: v for k, v in cert.items() if k != 'id'})
        except (_Overflow, ValueError) + _SELECT_ERRORS:
            complete = False
            continue
        if seen.setdefault(cert['id'], body) != body:
            complete = False
            continue
        if any(c['id'] == cert['id'] for c in certs):
            continue
        if not verify_rule_counterexample(cert, facts, rules, target)['valid']:
            complete = False
            continue
        certs.append(cert)
    return {'record': record, 'counterexamples': certs, 'counterexamples_complete': complete}


def verify_rule_counterexample(cert, facts, rules, target):
    facts, rules, target = _inputs(facts, rules, target)

    def bad(code):
        return {'valid': False, 'reason': code}

    try:
        cert = validate_value(cert)
    except (ValueError, TypeError, RecursionError):
        return bad('malformed_certificate')
    if type(cert) is not dict or cert.keys() != _CX or cert['schema'] != _CX_SCHEMA:
        return bad('malformed_certificate')
    if _unsafe(rules):
        return bad('unsafe_rule')
    try:
        expected = 'counterexample:' + _h({k: v for k, v in cert.items() if k != 'id'})
    except (TypeError, ValueError, RecursionError):
        return bad('malformed_certificate')
    if type(cert['id']) is not str or cert['id'] != expected:
        return bad('id_mismatch')
    if cert['facts_sha256'] != _h(facts) or cert['rules_sha256'] != _h(rules):
        return bad('hash_mismatch')
    if _c(cert['target']) != _c(target):
        return bad('target_mismatch')
    lim = cert['limits']
    try:
        if type(lim) is not dict or lim.keys() != {'limit', 'proof_limit', 'search_limit'}:
            raise ValueError('limits')
        _limits(**lim)
    except ValueError:
        return bad('malformed_limits')
    if cert['rule_ids'] is None:
        selected = rules
    else:
        try:
            selected = _route(cert['rule_ids'], rules)
        except ValueError:
            return bad('selection_mismatch')
    byrule = {r['id']: r for r in selected}
    rule = byrule.get(cert['rule']) if type(cert['rule']) is str else None
    if rule is None:
        return bad('rule_mismatch')
    if (type(cert['rule_version']) is not type(rule['version'])
            or cert['rule_version'] != rule['version']):
        return bad('version_mismatch')
    head, parents, proofs = cert['head'], cert['parents'], cert['proofs']
    if not _triple(head, True) or type(cert['bindings']) is not dict:
        return bad('malformed_certificate')
    if (type(proofs) is not list or not 1 <= len(proofs) <= 16
            or any(type(p) is not dict or p.keys() != {'id', 'value'} or type(p['id']) is not str
                   or type(p['value']) is not dict
                   or not _triple(p['value'].get('conclusion'), True) for p in proofs)):
        return bad('malformed_proofs')
    nodes = {p['id']: p['value'] for p in proofs}
    if len(nodes) != len(proofs):
        return bad('duplicate_node')
    byfact = {f['id']: f for f in facts}
    denied = {tuple(f['triple']) for f in facts if _neg(f)}
    try:
        for nid, v in nodes.items():
            if nid != 'proof:' + _h(v) or not _node_ok(v, byfact, byrule, nodes, denied):
                return bad('bad_node')
    except _SELECT_ERRORS + (ValueError,):
        return bad('bad_node')
    if (type(parents) is not list or len(parents) != len(rule['body'])
            or not all(type(p) is str and p in nodes for p in parents)):
        return bad('parent_mismatch')
    reached = set()
    try:
        for p in parents:
            reached.update(_post(p, nodes))
    except (ValueError, KeyError, TypeError, RecursionError):
        return bad('cycle')
    if reached != set(nodes):
        return bad('unreferenced')
    b = {}
    for pattern, p in zip(rule['body'], parents):
        b = inference.bind(pattern, nodes[p]['conclusion'], b)
        if b is None:
            return bad('binding_mismatch')
    if _c(b) != _c(cert['bindings']):
        return bad('binding_mismatch')
    if [b[t] if inference.variable(t) else t for t in rule['head']] != head:
        return bad('head_mismatch')
    nid = cert['negative_fact_id']
    witness = byfact.get(nid) if type(nid) is str else None
    if witness is None or not _neg(witness) or witness['triple'] != head:
        return bad('negative_witness')
    return {'valid': True, 'reason': 'counterexample_verified'}


def build_available_proof_graph(facts, rules, target, *, limit=32, proof_limit=4,
                                search_limit=256):
    facts, rules, target = _inputs(facts, rules, target)
    lim = _limits(limit, proof_limit, search_limit)
    ctx = (facts, rules, target, lim)
    if _unsafe(rules):
        return {'record': _record(ctx, 'invalid', 'unsafe_rule'), 'available_record': None,
                'search_complete': False, 'search_reason': 'unsafe_rule'}
    result = _close(facts, rules, lim)
    neg, pos = _witness(facts, target)
    record = _reviewed_record(ctx, result, False, neg, pos)
    complete = result['complete'] is True
    why = result.get('reason')
    why = why[:64] if type(why) is str else None
    available = None
    if (record['status'] == 'incomplete' and not complete and not neg
            and tuple(target) in result.get('facts', ())):
        try:
            root, proofs = _select(result, tuple(target))
            cand = _record(ctx, 'proved', None, root, proofs)
            v = verify_proof_graph(cand, facts, rules, target)
            if (cand['status'] == 'proved' and v['valid'] is True
                    and v['conclusion_verified'] is True):
                available = cand
        except (_Overflow, ValueError) + _SELECT_ERRORS:
            available = None
    return {'record': record, 'available_record': available,
            'search_complete': complete, 'search_reason': why}
