"""Pure ephemeral bounded selected-query source validation work. No inference or persistence."""

import json

SCHEMA = 'bounded-query-work-v1'
SCOPE = 'selected_positive_query_source'
OPERATION = 'selected_query_validation'
BLOCKED_REASON = 'input_understanding_failed'
CAPACITY_REASON = 'capacity'
_STATUSES = ('pending', 'running', 'completed', 'blocked')
_KEYS = {'schema', 'validation_scope', 'budget', 'used', 'status', 'goal', 'nodes', 'edges',
         'blocked_reason', 'claim_refusal'}


def _detach(value, max_depth, max_items, max_bytes):
    budget = [0]

    def walk(v, depth):
        if depth > max_depth:
            raise ValueError('depth')
        budget[0] += 1
        if budget[0] > max_items:
            raise ValueError('items')
        t = type(v)
        if v is None or t is bool or t is int or t is str:
            return v
        if t is list:
            return [walk(x, depth + 1) for x in v]
        if t is dict:
            out = {}
            for k, x in v.items():
                if type(k) is not str:
                    raise ValueError('key')
                out[k] = walk(x, depth + 1)
            return out
        raise ValueError('type')

    detached = walk(value, 0)
    size = len(_canon(detached).encode('utf-8'))
    if size > max_bytes:
        raise ValueError('size')
    return detached


def _canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _is_hash(v):
    return type(v) is str and len(v) == 64 and set(v) <= set('0123456789abcdef')


def _check_ref(ref):
    if (type(ref) is not dict or set(ref) != {'index', 'annotation_sha256', 'source_ref_sha256'}
            or type(ref['index']) is not int or ref['index'] < 0
            or not _is_hash(ref['annotation_sha256']) or not _is_hash(ref['source_ref_sha256'])):
        raise ValueError('invalid evidence_ref')
    return ref


def _check_goal(goal):
    # Structural goal shape only; not source proof and not answer truth.
    goal = _detach(goal, 16, 1024, 16384)
    if type(goal) is not list or len(goal) != 1:
        raise ValueError('invalid goal')
    row = goal[0]
    if type(row) is not dict or set(row) != {'triple', 'render'}:
        raise ValueError('invalid goal')
    triple, render = row['triple'], row['render']
    if (type(triple) is not list or len(triple) != 3
            or not all(type(p) is str and p.strip() for p in triple)):
        raise ValueError('invalid goal')
    if (type(render) is not list or not render
            or not all(type(r) is str for r in render)):
        raise ValueError('invalid goal')
    return goal


def _build(goal, status, evidence, refusal):
    nodes = [{'id': 'goal0', 'kind': 'goal', 'status': 'pending'}]
    edges = []
    if status != 'pending':
        nodes.append({'id': 'op0', 'kind': 'operation', 'operation': OPERATION, 'status': status})
        edges.append({'source': 'goal0', 'target': 'op0', 'relation': 'requires'})
    if status == 'completed':
        nodes.append({'id': 'evidence0', 'kind': 'evidence', 'evidence_ref': evidence,
                      'attested_by': 'caller'})
        edges.append({'source': 'evidence0', 'target': 'op0', 'relation': 'supports'})
    if status != 'blocked':
        reason = None
    elif refusal == 'capacity':
        reason = CAPACITY_REASON
    else:
        reason = BLOCKED_REASON
    return {'schema': SCHEMA, 'validation_scope': SCOPE, 'budget': 1,
            'used': 0 if status == 'pending' else 1, 'status': status, 'goal': goal,
            'nodes': nodes, 'edges': edges,
            'blocked_reason': reason,
            'claim_refusal': refusal}


def _validate(work):
    w = _detach(work, 18, 1200, 32768)
    if type(w) is not dict or set(w) != _KEYS:
        raise ValueError('invalid work')
    status = w['status']
    if type(status) is not str or status not in _STATUSES:
        raise ValueError('invalid status')
    goal = _check_goal(w['goal'])
    refusal = w['claim_refusal']
    if refusal is not None and refusal != 'capacity':
        raise ValueError('invalid claim_refusal')
    if refusal == 'capacity' and status != 'blocked':
        raise ValueError('capacity refusal requires blocked status')
    evidence = None
    if status == 'completed':
        nodes = w['nodes']
        if type(nodes) is not list or len(nodes) != 3 or type(nodes[2]) is not dict:
            raise ValueError('invalid nodes')
        evidence = _check_ref(nodes[2].get('evidence_ref'))
    if _canon(_build(goal, status, evidence, refusal)) != _canon(w):
        raise ValueError('inconsistent work')
    return goal, status, evidence, refusal


def new_query_work(goalquerylist):
    goal = _check_goal(goalquerylist)
    return _build(goal, 'pending', None, None)


def claim_validation(work):
    goal, status, _evidence, _refusal = _validate(work)
    if status == 'pending':
        return _build(goal, 'running', None, None), True
    # Duplicate or over-budget claim: deny, block, never carry proof evidence.
    return _build(goal, 'blocked', None, 'capacity'), False


def finish_validation(work, accepted, evidence_ref, blocked_reason):
    if type(accepted) is not bool:
        raise ValueError('accepted must be bool')
    goal, status, _evidence, refusal = _validate(work)
    if status != 'running':
        raise ValueError('work is not running')
    if accepted:
        if blocked_reason is not None:
            raise ValueError('blocked_reason must be None')
        ref = _check_ref(_detach(evidence_ref, 4, 16, 1024))
        return _build(goal, 'completed', ref, refusal)
    if evidence_ref is not None or type(blocked_reason) is not str or blocked_reason != BLOCKED_REASON:
        raise ValueError('invalid blocked finish')
    return _build(goal, 'blocked', None, refusal)
