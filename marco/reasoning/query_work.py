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


_FR_SCHEMA = 'bounded-failure-response-work-v1'
_FR_SCOPE = 'failure_response_emission'
_FR_STATUSES = ('pending', 'running', 'completed', 'blocked')
_FR_KEYS = {'schema', 'scope', 'budget', 'used', 'goal_ref', 'evidence', 'uncertainty',
            'emission_status', 'claim_refusal', 'selected_action', 'nodes', 'edges'}


def _fr_goal_ref(goal_ref):
    # Structural only; the caller attests the goal reference.
    g = _detach(goal_ref, 20, 1400, 32768)
    if type(g) is not dict or set(g) != {'input_sha256', 'query'}:
        raise ValueError('invalid goal_ref')
    if not _is_hash(g['input_sha256']):
        raise ValueError('invalid goal_ref')
    query = g['query']
    if query is not None:
        query = _check_goal(query)
    return {'input_sha256': g['input_sha256'], 'query': query}


def _fr_evidence(evidence):
    # Closed tagged union; caller attests it. Structure and consistency only.
    ev = _detach(evidence, 20, 1400, 32768)
    if type(ev) is not dict or type(ev.get('scope')) is not str:
        raise ValueError('invalid evidence')
    scope = ev['scope']
    if scope == 'selected_reader_processing_failure':
        if (set(ev) != {'scope', 'outcome', 'authority_sha256'}
                or type(ev['outcome']) is not str or ev['outcome'] != 'exhausted'
                or not _is_hash(ev['authority_sha256'])):
            raise ValueError('invalid evidence')
        return ev, 'understanding_failure', 'emit_existing_gap'
    if scope == 'selected_binary_guard':
        if (set(ev) != {'scope', 'outcome', 'guard_ref', 'positive_support', 'negative_support'}
                or type(ev['outcome']) is not str
                or type(ev['positive_support']) is not bool
                or type(ev['negative_support']) is not bool):
            raise ValueError('invalid evidence')
        _check_ref(ev['guard_ref'])
        pos, neg = ev['positive_support'], ev['negative_support']
        if ev['outcome'] == 'missing_premise' and pos is False and neg is False:
            return ev, 'missing_premise', 'emit_existing_information_gap'
        if ev['outcome'] == 'conflicting_evidence' and pos is True and neg is True:
            return ev, 'conflicting_evidence', 'emit_existing_conflict'
    raise ValueError('unsupported evidence')


def _fr_build(goal_ref, evidence, uncertainty, action, status, refusal):
    nodes = [{'id': 'goal0', 'kind': 'goal', 'status': 'blocked'},
             {'id': 'evidence0', 'kind': 'evidence', 'evidence': evidence,
              'attested_by': 'caller'},
             {'id': 'gap0', 'kind': 'gap', 'uncertainty': uncertainty}]
    edges = [{'source': 'evidence0', 'target': 'gap0', 'relation': 'supports'},
             {'source': 'gap0', 'target': 'goal0', 'relation': 'blocks'}]
    claimed = status in ('running', 'completed')
    if claimed:
        nodes.append({'id': 'op0', 'kind': 'operation', 'action': action,
                      'emission_status': status})
        edges.append({'source': 'goal0', 'target': 'op0', 'relation': 'requires'})
    work = {'schema': _FR_SCHEMA, 'scope': _FR_SCOPE, 'budget': 1,
            'used': 0 if status == 'pending' else 1,
            'goal_ref': goal_ref, 'evidence': evidence, 'uncertainty': uncertainty,
            'emission_status': status, 'claim_refusal': refusal,
            'selected_action': action if claimed else None,
            'nodes': nodes, 'edges': edges}
    return _detach(work, 20, 1400, 32768)


def _fr_validate(work):
    w = _detach(work, 20, 1400, 32768)
    if type(w) is not dict or set(w) != _FR_KEYS:
        raise ValueError('invalid work')
    status = w['emission_status']
    if type(status) is not str or status not in _FR_STATUSES:
        raise ValueError('invalid status')
    refusal = w['claim_refusal']
    if refusal is not None and (type(refusal) is not str or refusal != 'capacity'):
        raise ValueError('invalid claim_refusal')
    if (refusal == 'capacity') != (status == 'blocked'):
        raise ValueError('inconsistent refusal')
    gr = _fr_goal_ref(w['goal_ref'])
    ev, unc, act = _fr_evidence(w['evidence'])
    expected = _fr_build(gr, ev, unc, act, status, refusal)
    if _canon(expected) != _canon(w):
        raise ValueError('inconsistent work')
    return gr, ev, unc, act, status


def new_thinking_work(goal_ref, evidence):
    gr = _fr_goal_ref(goal_ref)
    ev, unc, act = _fr_evidence(evidence)
    return _fr_build(gr, ev, unc, act, 'pending', None)


def choose_thinking_operation(work):
    gr, ev, unc, act, status = _fr_validate(work)
    if status == 'pending':
        return _fr_build(gr, ev, unc, act, 'running', None), act
    # Duplicate or over-budget claim: deny, block with capacity refusal, no action.
    return _fr_build(gr, ev, unc, act, 'blocked', 'capacity'), None


def finish_thinking_operation(work, action):
    gr, ev, unc, act, status = _fr_validate(work)
    if status != 'running':
        raise ValueError('work is not running')
    if type(action) is not str or action != act:
        raise ValueError('action mismatch')
    return _fr_build(gr, ev, unc, act, 'completed', None)


import hashlib as _sg_hashlib

from marco.reasoning.graph_vm import run as _sg_run, validate_program as _sg_validate_program

_SG_SCHEMA = 'marco-single-goal-work-v1'
_SG_KEYS = {'schema', 'goal', 'binding', 'program_sha256', 'phase', 'max_attempts', 'used',
            'attempts', 'nodes', 'edges', 'blocked_reason'}
_SG_PHASES = ('pending', 'attempting', 'awaiting_verification', 'verifying', 'waiting',
              'completed', 'blocked')
_SG_ATTEMPT_KEYS = {'number', 'state_sha256', 'result_sha256', 'status', 'proof_sha256',
                    'failure_code'}
_SG_ATTEMPT_STATUSES = ('pending', 'returned', 'verified', 'failed', 'interrupted')
_SG_FAILURES = ('unresolved', 'input_unread', 'proof_unavailable', 'unsupported')
_SG_REASONS = ('capacity', 'stale_binding', 'interrupted')
_SG_ACTIONS = ('attempt', 'verify', 'wait', 'stop')
_SG_MAX_ATTEMPTS = 2
_SG_MAX_BYTES = 32768
_SG_VM_BUDGET = 512
_SG_MAX_PROGRAM_NODES = 64
_SG_IN_FLIGHT = ('attempting', 'awaiting_verification', 'verifying')


def _sg_fail(code):
    raise ValueError(code)


def _sg_str(value, limit):
    return type(value) is str and value != '' and len(value) <= limit


def _sg_native_var(value):
    return (len(value) > 1 and value[0] == '?'
            and all(c.isascii() and (c.isalnum() or c == '_') for c in value[1:]))


def _sg_goal(goal):
    try:
        g = _detach(goal, 4, 16, _SG_MAX_BYTES)
    except ValueError:
        _sg_fail('invalid_goal')
    if type(g) is not dict or set(g) != {'text', 'query'}:
        _sg_fail('invalid_goal')
    text = g['text']
    if type(text) is not str or not text.strip() or len(text) > 4096:
        _sg_fail('invalid_goal')
    try:
        if len(text.encode('utf-8')) > 16384:
            _sg_fail('invalid_goal')
    except UnicodeEncodeError:
        _sg_fail('invalid_goal')
    query = g['query']
    if type(query) is not list or len(query) != 3 or not all(_sg_str(x, 1024) for x in query):
        _sg_fail('invalid_goal')
    if any('$' in x for x in query) or '?' in query[1]:
        _sg_fail('invalid_goal')
    variables = [x for x in (query[0], query[2]) if x.startswith('?')]
    if (len(variables) != 1 or not _sg_native_var(variables[0])
            or any('?' in x for x in (query[0], query[2]) if x != variables[0])):
        _sg_fail('invalid_goal')
    return {'text': text, 'query': [query[0], query[1], query[2]]}


def _sg_binding(binding):
    try:
        b = _detach(binding, 2, 8, 4096)
    except ValueError:
        _sg_fail('invalid_binding')
    if (type(b) is not dict or set(b) != {'conversation_id', 'model_sha256', 'memory_revision'}
            or not all(_sg_str(b[k], 256) for k in b)
            or not _is_hash(b['model_sha256'])
            or not b['memory_revision'].isascii() or not b['memory_revision'].isdigit()
            or b['memory_revision'] != str(int(b['memory_revision']))):
        _sg_fail('invalid_binding')
    return {'conversation_id': b['conversation_id'], 'model_sha256': b['model_sha256'],
            'memory_revision': b['memory_revision']}


def _sg_graph(phase, attempts):
    if phase == 'completed':
        goal_status = 'resolved'
    elif phase == 'blocked':
        goal_status = 'blocked'
    else:
        goal_status = 'open'
    nodes = [{'id': 'goal0', 'kind': 'goal', 'status': goal_status}]
    edges = []
    for a in attempts:
        n = a['number']
        aid = 'attempt%d' % n
        nodes.append({'id': aid, 'kind': 'attempt', 'number': n, 'status': a['status']})
        edges.append({'source': 'goal0', 'target': aid, 'relation': 'depends'})
        if a['status'] == 'verified':
            eid = 'evidence%d' % n
            nodes.append({'id': eid, 'kind': 'evidence', 'proof_sha256': a['proof_sha256'],
                          'attested_by': 'runtime'})
            edges.append({'source': eid, 'target': aid, 'relation': 'supports'})
        elif a['status'] == 'failed':
            fid = 'failure%d' % n
            nodes.append({'id': fid, 'kind': 'failure', 'failure_code': a['failure_code']})
            edges.append({'source': 'goal0', 'target': fid, 'relation': 'blocked_by'})
    return nodes, edges


def _sg_build(goal, binding, program_sha256, phase, attempts, reason):
    attempts = [dict(a) for a in attempts]
    nodes, edges = _sg_graph(phase, attempts)
    work = {'schema': _SG_SCHEMA, 'goal': goal, 'binding': binding,
            'program_sha256': program_sha256, 'phase': phase,
            'max_attempts': _SG_MAX_ATTEMPTS, 'used': len(attempts), 'attempts': attempts,
            'nodes': nodes, 'edges': edges, 'blocked_reason': reason}
    try:
        return _detach(work, 8, 600, _SG_MAX_BYTES)
    except ValueError:
        _sg_fail('invalid_work')


def _sg_check_attempt(a, number):
    if type(a) is not dict or set(a) != _SG_ATTEMPT_KEYS:
        _sg_fail('invalid_work')
    if type(a['number']) is not int or a['number'] != number or not _is_hash(a['state_sha256']):
        _sg_fail('invalid_work')
    st, r, p, f = a['status'], a['result_sha256'], a['proof_sha256'], a['failure_code']
    ok = ((st == 'pending' and r is None and p is None and f is None)
          or (st == 'returned' and _is_hash(r) and p is None and f is None)
          or (st == 'verified' and _is_hash(r) and _is_hash(p) and f is None)
          or (st == 'failed' and _is_hash(r) and p is None and type(f) is str
              and f in _SG_FAILURES)
          or (st == 'interrupted' and (r is None or _is_hash(r)) and p is None and f is None))
    if not ok:
        _sg_fail('invalid_work')


def _sg_validate(work):
    try:
        w = _detach(work, 8, 600, _SG_MAX_BYTES)
    except ValueError:
        _sg_fail('invalid_work')
    if type(w) is not dict or set(w) != _SG_KEYS or w['schema'] != _SG_SCHEMA:
        _sg_fail('invalid_work')
    goal = _sg_goal(w['goal'])
    binding = _sg_binding(w['binding'])
    if not _is_hash(w['program_sha256']):
        _sg_fail('invalid_work')
    phase = w['phase']
    if type(phase) is not str or phase not in _SG_PHASES:
        _sg_fail('invalid_work')
    if type(w['max_attempts']) is not int or w['max_attempts'] != _SG_MAX_ATTEMPTS:
        _sg_fail('invalid_work')
    attempts = w['attempts']
    if type(attempts) is not list or len(attempts) > _SG_MAX_ATTEMPTS:
        _sg_fail('invalid_work')
    for i, a in enumerate(attempts):
        _sg_check_attempt(a, i + 1)
    used = w['used']
    if type(used) is not int or used != len(attempts):
        _sg_fail('invalid_work')
    if len({a['state_sha256'] for a in attempts}) != len(attempts):
        _sg_fail('invalid_work')
    if not all(a['status'] == 'failed' for a in attempts[:-1]):
        _sg_fail('invalid_work')
    last = attempts[-1]['status'] if attempts else None
    reason = w['blocked_reason']
    if phase == 'blocked':
        if type(reason) is not str or reason not in _SG_REASONS:
            _sg_fail('invalid_work')
        if reason == 'capacity':
            ok = used == _SG_MAX_ATTEMPTS and last == 'failed'
        elif reason == 'interrupted':
            ok = last == 'interrupted'
        else:
            ok = last in (None, 'failed', 'verified', 'interrupted')
    else:
        ok = reason is None and (
            (phase == 'pending' and used == 0)
            or (phase == 'attempting' and last == 'pending')
            or (phase in ('awaiting_verification', 'verifying') and last == 'returned')
            or (phase == 'waiting' and used == 1 and last == 'failed')
            or (phase == 'completed' and last == 'verified'))
    if not ok:
        _sg_fail('invalid_work')
    rebuilt = _sg_build(goal, binding, w['program_sha256'], phase, attempts, reason)
    if _canon(rebuilt) != _canon(w):
        _sg_fail('invalid_work')
    return rebuilt


def _sg_program_sha256(program):
    try:
        return _sg_hashlib.sha256(_canon(program).encode('utf-8')).hexdigest()
    except (ValueError, TypeError):
        _sg_fail('invalid_program')


def _sg_program(work, program):
    try:
        normalized = _sg_validate_program(program)
    except ValueError:
        _sg_fail('invalid_program')
    if len(normalized['nodes']) > _SG_MAX_PROGRAM_NODES:
        _sg_fail('invalid_program')
    if _sg_program_sha256(normalized) != work['program_sha256']:
        _sg_fail('invalid_program')
    return normalized


def _sg_progress(progress):
    try:
        p = _detach(progress, 2, 8, 1024)
    except ValueError:
        _sg_fail('invalid_progress')
    if (type(p) is not dict or set(p) != {'state_sha256', 'relevant_new_positive', 'eligible'}
            or not _is_hash(p['state_sha256'])
            or type(p['relevant_new_positive']) is not bool or type(p['eligible']) is not bool):
        _sg_fail('invalid_progress')
    return p


def _sg_plan(w, program, progress):
    normalized = _sg_program(w, program)
    p = _sg_progress(progress)
    phase, used = w['phase'], w['used']
    inputs = {'phase': phase, 'used': used, 'eligible': p['eligible'],
              'relevant_new_positive': p['relevant_new_positive']}
    result = _sg_run(normalized, inputs, budget=_SG_VM_BUDGET)
    action = result['value'] if result['status'] == 'completed' else None
    if type(action) is not str or action not in _SG_ACTIONS:
        action = 'stop'
    # Host safety invariants; the program asset cannot weaken these.
    if phase in ('completed', 'blocked', 'attempting', 'verifying'):
        return 'stop', p
    if action == 'attempt':
        prior = {a['state_sha256'] for a in w['attempts']}
        allowed = p['eligible'] and used < _SG_MAX_ATTEMPTS and (
            (phase == 'pending' and used == 0)
            or (phase == 'waiting' and used == 1 and p['relevant_new_positive']
                and p['state_sha256'] not in prior))
        if not allowed:
            action = 'wait'
    elif action == 'verify' and phase != 'awaiting_verification':
        action = 'wait'
    return action, p


def new_goal_work(goal, binding, program_sha256):
    g = _sg_goal(goal)
    b = _sg_binding(binding)
    if not _is_hash(program_sha256):
        _sg_fail('invalid_program')
    return _sg_build(g, b, program_sha256, 'pending', [], None)


def validate_goal_work(work):
    return _sg_validate(work)


def plan_goal_operation(work, program, progress):
    w = _sg_validate(work)
    action, _p = _sg_plan(w, program, progress)
    return action


def claim_goal_operation(work, program, progress):
    w = _sg_validate(work)
    action, p = _sg_plan(w, program, progress)
    attempts = w['attempts']
    if action == 'attempt':
        attempts = attempts + [{'number': len(attempts) + 1, 'state_sha256': p['state_sha256'],
                                'result_sha256': None, 'status': 'pending',
                                'proof_sha256': None, 'failure_code': None}]
        return _sg_build(w['goal'], w['binding'], w['program_sha256'], 'attempting',
                         attempts, None), action
    if action == 'verify':
        return _sg_build(w['goal'], w['binding'], w['program_sha256'], 'verifying',
                         attempts, None), action
    return w, action


def record_goal_attempt(work, result_sha256):
    w = _sg_validate(work)
    if w['phase'] != 'attempting':
        _sg_fail('invalid_transition')
    if not _is_hash(result_sha256):
        _sg_fail('invalid_argument')
    attempts = [dict(a) for a in w['attempts']]
    attempts[-1]['result_sha256'] = result_sha256
    attempts[-1]['status'] = 'returned'
    return _sg_build(w['goal'], w['binding'], w['program_sha256'], 'awaiting_verification',
                     attempts, None)


def finish_goal_verification(work, verified, proof_sha256, failure_code):
    if type(verified) is not bool:
        _sg_fail('invalid_argument')
    w = _sg_validate(work)
    if w['phase'] != 'verifying':
        _sg_fail('invalid_transition')
    attempts = [dict(a) for a in w['attempts']]
    if verified:
        if not _is_hash(proof_sha256) or failure_code is not None:
            _sg_fail('invalid_argument')
        attempts[-1]['status'] = 'verified'
        attempts[-1]['proof_sha256'] = proof_sha256
        return _sg_build(w['goal'], w['binding'], w['program_sha256'], 'completed',
                         attempts, None)
    if (proof_sha256 is not None or type(failure_code) is not str
            or failure_code not in _SG_FAILURES):
        _sg_fail('invalid_argument')
    attempts[-1]['status'] = 'failed'
    attempts[-1]['failure_code'] = failure_code
    if len(attempts) < _SG_MAX_ATTEMPTS:
        return _sg_build(w['goal'], w['binding'], w['program_sha256'], 'waiting',
                         attempts, None)
    return _sg_build(w['goal'], w['binding'], w['program_sha256'], 'blocked',
                     attempts, 'capacity')


def recover_goal_work(work, *, binding=None, program_sha256=None):
    w = _sg_validate(work)
    stale = False
    if binding is not None:
        if _canon(_sg_binding(binding)) != _canon(w['binding']):
            stale = True
    if program_sha256 is not None:
        if not _is_hash(program_sha256):
            _sg_fail('invalid_program')
        if program_sha256 != w['program_sha256']:
            stale = True
    phase = w['phase']
    if phase == 'blocked':
        return w
    attempts = [dict(a) for a in w['attempts']]
    in_flight = phase in _SG_IN_FLIGHT
    if in_flight:
        attempts[-1]['status'] = 'interrupted'
    if stale:
        return _sg_build(w['goal'], w['binding'], w['program_sha256'], 'blocked',
                         attempts, 'stale_binding')
    if in_flight:
        return _sg_build(w['goal'], w['binding'], w['program_sha256'], 'blocked',
                         attempts, 'interrupted')
    return w


from marco.reasoning.inference import bind as _pg_bind, closure as _pg_closure

_PG_SCHEMA = 'marco-prerequisite-plan-v1'
_PG_SCOPES = {'authenticated_native_archive': 'caller_attested_native_archive',
              'validated_typed_diagnostic': 'typed_diagnostic_not_conversation_authority'}
_PG_OPERATIONS = ('attempt_original', 'wait_for_premise', 'stop')
_PG_MAX_BUDGET = 256
_PG_VM_BUDGET = 256
_PG_CLOSURE_LIMIT = 128
_PG_MAX_FACTS = 64
_PG_MAX_RULES = 2
_PG_MAX_DEPTH = 2
_PG_MAX_NODES = 24
_PG_MAX_EDGES = 32
_PG_MAX_MISSING = 4
_PG_MAX_BYTES = 32768
_PG_MAX_REV = 99999999999999999999


class _PgCapacity(Exception):
    """Planner work budget or structural cap exceeded; no conclusions exported."""


def _pg_detach(value, depth, items, size, code):
    try:
        return _detach(value, depth, items, size)
    except (ValueError, RecursionError):
        _sg_fail(code)


def _pg_term(value, code):
    if type(value) is not str or not value.strip() or len(value) > 256 or '$' in value:
        _sg_fail(code)
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        _sg_fail(code)
    return value


def _pg_ground(triple, code):
    if type(triple) is not list or len(triple) != 3:
        _sg_fail(code)
    for t in triple:
        _pg_term(t, code)
        if '?' in t:
            _sg_fail(code)
    return [triple[0], triple[1], triple[2]]


def _pg_query(query):
    q = _pg_detach(query, 2, 8, 2048, 'invalid_query')
    if type(q) is not list or len(q) != 3:
        _sg_fail('invalid_query')
    for t in q:
        _pg_term(t, 'invalid_query')
    if '?' in q[1]:
        _sg_fail('invalid_query')
    ends = [x for x in (q[0], q[2]) if x.startswith('?')]
    if len(ends) != 1 or not _sg_native_var(ends[0]):
        _sg_fail('invalid_query')
    other = q[2] if q[0] == ends[0] else q[0]
    if '?' in other:
        _sg_fail('invalid_query')
    return [q[0], q[1], q[2]]


def _pg_facts(facts):
    fs = _pg_detach(facts, 4, 600, 65536, 'invalid_facts')
    if type(fs) is not list or len(fs) > _PG_MAX_FACTS:
        _sg_fail('invalid_facts')
    out = []
    for row in fs:
        if (type(row) is not dict or set(row) != {'triple', 'polarity', 'source_sha256'}
                or type(row['polarity']) is not bool or not _is_hash(row['source_sha256'])):
            _sg_fail('invalid_facts')
        out.append({'triple': _pg_ground(row['triple'], 'invalid_facts'),
                    'polarity': row['polarity'], 'source_sha256': row['source_sha256']})
    return out


def _pg_obs(value):
    return (type(value) is str and 2 <= len(value) <= 64 and value[0] == 'o'
            and value[1] in '123456789' and all(c in '0123456789' for c in value[2:]))


def _pg_rules(rules):
    rs = _pg_detach(rules, 6, 200, 16384, 'invalid_rules')
    if type(rs) is not list or len(rs) > _PG_MAX_RULES:
        _sg_fail('invalid_rules')
    out, ids = [], set()
    akeys = {'observation_id', 'reading_revision', 'source_sha256',
             'guard_certificate_sha256', 'consequent_witness_sha256'}
    for row in rs:
        if type(row) is not dict or set(row) != {'rule_id', 'body', 'head', 'authority'}:
            _sg_fail('invalid_rules')
        rid, body, auth = row['rule_id'], row['body'], row['authority']
        if type(rid) is not str or rid == '' or len(rid) > 96 or rid in ids:
            _sg_fail('invalid_rules')
        if type(body) is not list or not 1 <= len(body) <= 2:
            _sg_fail('invalid_rules')
        body = [_pg_ground(p, 'invalid_rules') for p in body]
        head = _pg_ground(row['head'], 'invalid_rules')
        if type(auth) is not dict or set(auth) != akeys:
            _sg_fail('invalid_rules')
        rev, guards = auth['reading_revision'], auth['guard_certificate_sha256']
        if (not _pg_obs(auth['observation_id']) or type(rev) is not int
                or not 1 <= rev <= _PG_MAX_REV or not _is_hash(auth['source_sha256'])
                or not _is_hash(auth['consequent_witness_sha256'])
                or type(guards) is not list or len(guards) != len(body)
                or not all(_is_hash(g) for g in guards)
                or rid != auth['observation_id'] + '@' + str(rev)):
            _sg_fail('invalid_rules')
        ids.add(rid)
        out.append({'rule_id': rid, 'body': body, 'head': head,
                    'authority': {'observation_id': auth['observation_id'],
                                  'reading_revision': rev,
                                  'source_sha256': auth['source_sha256'],
                                  'guard_certificate_sha256': list(guards),
                                  'consequent_witness_sha256': auth['consequent_witness_sha256']}})
    return out


def _pg_program(program):
    try:
        normalized = _sg_validate_program(program)
    except ValueError:
        _sg_fail('invalid_program')
    if len(normalized['nodes']) > _SG_MAX_PROGRAM_NODES:
        _sg_fail('invalid_program')
    return normalized


def _pg_plan(q, fs, rs, budget, used):
    def charge(n=1):
        if used[0] + n > budget:
            raise _PgCapacity()
        used[0] += n

    empty = {'nodes': [], 'edges': [], 'missing': [], 'contradicted': [], 'conflicts': []}
    if budget == 0:
        raise _PgCapacity()
    targets = []
    for t in [f['triple'] for f in fs] + [r['head'] for r in rs]:
        charge()
        if _pg_bind(q, t, {}) is not None and t not in targets:
            targets.append(list(t))
    if len(targets) != 1:
        return dict(empty, target=None, status='ambiguous' if targets else 'unsupported')
    target = tuple(targets[0])
    pos, neg = {}, {}
    for f in fs:
        charge()
        side = pos if f['polarity'] else neg
        hs = side.setdefault(tuple(f['triple']), [])
        if f['source_sha256'] not in hs:
            hs.append(f['source_sha256'])
    adapted = [{'triple': list(f['triple']), 'polarity': f['polarity'], 'modality': 'asserted',
                'evidence': {'source_sha256': f['source_sha256']}} for f in fs]
    crules = [{'id': r['rule_id'], 'body': [list(p) for p in r['body']], 'head': list(r['head'])}
              for r in rs]
    metrics = {}
    try:
        known = _pg_closure(adapted, crules, limit=_PG_CLOSURE_LIMIT, metrics=metrics)
    except ValueError:
        raise _PgCapacity() from None
    charge(metrics.get('rule_scans', 0) + metrics.get('join_attempts', 0))
    nodes, edges, missing, contradicted, conflicts = [], [], [], [], []
    flags = set()

    def add(node):
        charge()
        if len(nodes) >= _PG_MAX_NODES:
            raise _PgCapacity()
        node = dict(node, id='n%d' % len(nodes))
        nodes.append(node)
        return node

    def link(source, target_id, relation):
        charge()
        if len(edges) >= _PG_MAX_EDGES:
            raise _PgCapacity()
        edges.append({'source': source, 'target': target_id, 'relation': relation})

    def expand(goal, depth, path):
        charge()
        node = add({'kind': 'goal' if depth == 0 else 'premise', 'triple': list(goal),
                    'status': None})
        gid = node['id']
        if goal in pos and goal in neg:
            status = 'conflict'
            flags.add('conflicting_evidence')
            if all(c['triple'] != list(goal) for c in conflicts):
                conflicts.append({'triple': list(goal), 'positive_sha256': list(pos[goal]),
                                  'negative_sha256': list(neg[goal])})
        elif goal in neg:
            status = 'contradicted'
            flags.add('contradicted')
            if all(c['triple'] != list(goal) for c in contradicted):
                contradicted.append({'triple': list(goal), 'negative_sha256': list(neg[goal])})
        elif goal in pos and goal in known:
            status = 'supported'
            ev = add({'kind': 'evidence', 'triple': list(goal), 'polarity': True,
                      'source_sha256': list(pos[goal]), 'attested_by': 'caller'})
            link(ev['id'], gid, 'supports')
        elif goal in path:
            status = 'cyclic'
            flags.add('cyclic')
        else:
            matching = []
            for r in rs:
                charge()
                if tuple(r['head']) == goal:
                    matching.append(r)
            if not matching:
                status = 'missing'
                flags.add('missing_premise')
                if list(goal) not in missing:
                    missing.append(list(goal))
                gap = add({'kind': 'gap', 'triple': list(goal), 'reason': 'missing_premise'})
                link(gap['id'], gid, 'blocks')
            elif len(matching) > 1:
                status = 'ambiguous'
                flags.add('ambiguous')
            elif depth >= _PG_MAX_DEPTH:
                raise _PgCapacity()
            else:
                r = matching[0]
                rn = add({'kind': 'rule', 'rule_id': r['rule_id'],
                          'authority': dict(r['authority'],
                                            guard_certificate_sha256=list(
                                                r['authority']['guard_certificate_sha256'])),
                          'attested_by': 'caller'})
                link(gid, rn['id'], 'requires')
                for p in r['body']:
                    pid = expand(tuple(p), depth + 1, path | {goal})
                    link(rn['id'], pid, 'requires')
                status = 'derived' if goal in known else 'blocked'
        node['status'] = status
        return gid

    expand(target, 0, frozenset())
    if len(missing) > _PG_MAX_MISSING:
        raise _PgCapacity()
    if 'conflicting_evidence' in flags:
        status = 'conflicting_evidence'
    elif 'contradicted' in flags:
        status = 'contradicted'
    elif 'cyclic' in flags:
        status = 'cyclic'
    elif 'ambiguous' in flags:
        status = 'ambiguous'
    elif 'missing_premise' in flags:
        status = 'missing_premise'
    elif target in known:
        status = 'ready'
    else:
        status = 'unsupported'
    return {'target': list(target), 'status': status, 'nodes': nodes, 'edges': edges,
            'missing': missing, 'contradicted': contradicted, 'conflicts': conflicts}


def _pg_select(normalized, status):
    result = _sg_run(normalized, {'status': status}, budget=_PG_VM_BUDGET)
    op = result['value'] if result['status'] == 'completed' else None
    # Host compatibility only rejects unsafe asset output; it never chooses an action.
    if (type(op) is not str or op not in _PG_OPERATIONS
            or (op == 'attempt_original' and status != 'ready')
            or (op == 'wait_for_premise' and status != 'missing_premise')):
        return 'stop'
    return op


def _pg_report(input_scope, q, body, used, budget, normalized, sha):
    return {'schema': _PG_SCHEMA, 'input_scope': input_scope,
            'authority_scope': _PG_SCOPES[input_scope], 'query': list(q),
            'target': body['target'], 'status': body['status'],
            'next_operation': _pg_select(normalized, body['status']),
            'nodes': body['nodes'], 'edges': body['edges'], 'missing': body['missing'],
            'contradicted': body['contradicted'], 'conflicts': body['conflicts'],
            'used': used, 'budget': budget, 'program_sha256': sha}


def plan_goal_prerequisites(query, facts, rules, program, *, budget=64,
                            input_scope='validated_typed_diagnostic'):
    if type(input_scope) is not str or input_scope not in _PG_SCOPES:
        _sg_fail('invalid_scope')
    if type(budget) is not int or not 0 <= budget <= _PG_MAX_BUDGET:
        _sg_fail('invalid_budget')
    q = _pg_query(query)
    fs = _pg_facts(facts)
    rs = _pg_rules(rules)
    normalized = _pg_program(program)
    sha = _sg_program_sha256(normalized)
    capacity = {'target': None, 'status': 'capacity', 'nodes': [], 'edges': [],
                'missing': [], 'contradicted': [], 'conflicts': []}
    used = [0]
    try:
        body = _pg_plan(q, fs, rs, budget, used)
    except _PgCapacity:
        body = capacity
    report = _pg_report(input_scope, q, body, used[0], budget, normalized, sha)
    if len(_canon(report).encode('utf-8')) > _PG_MAX_BYTES:
        report = _pg_report(input_scope, q, capacity, used[0], budget, normalized, sha)
    return _pg_detach(report, 12, 4096, _PG_MAX_BYTES, 'invalid_report')


# V69 append-only: pure prospective prerequisite wrapper and bounded evidence-solve control.
# No I/O, callbacks, Context, session or native truth here; caller attests every result.

_ES_SCHEMA = 'marco-bounded-evidence-solve-work-v1'
_ES_PLAN_SCHEMA = 'marco-prospective-prerequisite-plan-v1'
_ES_INPUT_SCOPE = 'prospective_selected_native_sources'
_ES_AUTH_SCOPE = 'prospectiveplanning_not_archived_or_actualtruth'
_ES_AUTH_KIND = 'prospective_selected_native_source'
_ES_KEYS = {'schema', 'goal', 'binding', 'packets', 'provider_id', 'program_sha256', 'status',
            'counters', 'pending', 'staged_source', 'staged_answer', 'history', 'nodes', 'edges',
            'blocked_reason'}
_ES_KINDS = ('lookup', 'admit_source', 'commit_rule', 'ask_original', 'verify')
_ES_ACTIONS = _ES_KINDS + ('wait', 'stop')
_ES_PLAN_STATUSES = ('ready', 'missing_premise', 'conflicting_evidence', 'contradicted',
                     'cyclic', 'ambiguous', 'unsupported', 'capacity')
_ES_REASONS = ('capacity', 'stale_binding', 'interrupted', 'no_progress')
_ES_FAILURES = ('unresolved', 'proof_unavailable', 'unsupported')
_ES_HIST_STATUS = {'lookup': ('found', 'missing'), 'admit_source': ('accepted', 'rejected'),
                   'commit_rule': ('accepted', 'rejected'), 'ask_original': ('returned',),
                   'verify': ('verified', 'failed')}
_ES_HIST_KEYS = {'operation_id', 'kind', 'target_sha256', 'status', 'proof_sha256',
                 'failure_code'}
_ES_PACKET_KEYS = {'source_id', 'source_text', 'source_sha256', 'body', 'head', 'authority'}
_ES_AUTH_KEYS = {'kind', 'source_id', 'source_sha256', 'guard_certificate_sha256',
                 'consequent_witness_sha256'}
_ES_STAGED_KEYS = {'request_id', 'triple', 'source_id', 'source_text', 'source_sha256'}
_ES_ACTION_KEYS = {'kind', 'operation_id', 'target'}
_ES_VIEW_KEYS = {'eligible', 'state_sha256', 'plan_status', 'missing', 'needed_rule_ids',
                 'available_rule_ids', 'native_target_ready'}
_ES_IDS = ('p1', 'p2')
_ES_MAX_EACH = 2
_ES_MAX_HISTORY = 10
_ES_MAX_NODES = 32
_ES_MAX_EDGES = 48
_ES_MAX_BYTES = 65536
_ES_STEPCAP = 24


def _es_sha(value):
    try:
        return _sg_hashlib.sha256(_canon(value).encode('utf-8')).hexdigest()
    except (ValueError, TypeError, UnicodeEncodeError):
        _sg_fail('invalid_work')


def _es_text_sha(text):
    return _sg_hashlib.sha256(text.encode('utf-8')).hexdigest()


def _es_text(text, code):
    if type(text) is not str or not text.strip() or len(text) > 4096:
        _sg_fail(code)
    try:
        if len(text.encode('utf-8')) > 16384:
            _sg_fail(code)
    except UnicodeEncodeError:
        _sg_fail(code)
    return text


def _es_short(value, limit, code):
    if type(value) is not str or not value.strip() or len(value) > limit:
        _sg_fail(code)
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        _sg_fail(code)
    return value


def _es_provider(provider_id):
    return _es_short(provider_id, 128, 'invalid_provider')


def _es_rule_parts(body, head, auth, rid, code):
    if type(body) is not list or not 1 <= len(body) <= 2:
        _sg_fail(code)
    body = [_pg_ground(p, code) for p in body]
    head = _pg_ground(head, code)
    if type(auth) is not dict or set(auth) != _ES_AUTH_KEYS:
        _sg_fail(code)
    guards = auth['guard_certificate_sha256']
    if (type(auth['kind']) is not str or auth['kind'] != _ES_AUTH_KIND
            or type(auth['source_id']) is not str or auth['source_id'] != rid
            or not _is_hash(auth['source_sha256'])
            or not _is_hash(auth['consequent_witness_sha256'])
            or type(guards) is not list or len(guards) != len(body)
            or not all(_is_hash(g) for g in guards)):
        _sg_fail(code)
    return body, head, {'kind': _ES_AUTH_KIND, 'source_id': rid,
                        'source_sha256': auth['source_sha256'],
                        'guard_certificate_sha256': list(guards),
                        'consequent_witness_sha256': auth['consequent_witness_sha256']}


def _es_rules(rules):
    rs = _pg_detach(rules, 6, 200, 16384, 'invalid_rules')
    if type(rs) is not list or len(rs) > len(_ES_IDS):
        _sg_fail('invalid_rules')
    out, shas = [], set()
    for i, row in enumerate(rs):
        if type(row) is not dict or set(row) != {'rule_id', 'body', 'head', 'authority'}:
            _sg_fail('invalid_rules')
        rid = _ES_IDS[i]
        if type(row['rule_id']) is not str or row['rule_id'] != rid:
            _sg_fail('invalid_rules')
        body, head, auth = _es_rule_parts(row['body'], row['head'], row['authority'], rid,
                                          'invalid_rules')
        if auth['source_sha256'] in shas:
            _sg_fail('invalid_rules')
        shas.add(auth['source_sha256'])
        out.append({'rule_id': rid, 'body': body, 'head': head, 'authority': auth})
    return out


def _es_packets(packets):
    code = 'invalid_packets'
    ps = _pg_detach(packets, 6, 200, 40960, code)
    if type(ps) is not list or len(ps) > len(_ES_IDS):
        _sg_fail(code)
    out, shas, norms = [], set(), set()
    for i, row in enumerate(ps):
        if type(row) is not dict or set(row) != _ES_PACKET_KEYS:
            _sg_fail(code)
        pid = _ES_IDS[i]
        if type(row['source_id']) is not str or row['source_id'] != pid:
            _sg_fail(code)
        text = _es_text(row['source_text'], code)
        sha = row['source_sha256']
        if not _is_hash(sha) or sha != _es_text_sha(text):
            _sg_fail(code)
        body, head, auth = _es_rule_parts(row['body'], row['head'], row['authority'], pid, code)
        norm = ' '.join(text.split())
        if auth['source_sha256'] != sha or sha in shas or norm in norms:
            _sg_fail(code)
        shas.add(sha)
        norms.add(norm)
        out.append({'source_id': pid, 'source_text': text, 'source_sha256': sha,
                    'body': body, 'head': head, 'authority': auth})
    return out


def _es_report(q, body, used, budget, normalized, sha):
    return {'schema': _ES_PLAN_SCHEMA, 'input_scope': _ES_INPUT_SCOPE,
            'authority_scope': _ES_AUTH_SCOPE, 'query': list(q),
            'target': body['target'], 'status': body['status'],
            'next_operation': _pg_select(normalized, body['status']),
            'nodes': body['nodes'], 'edges': body['edges'], 'missing': body['missing'],
            'contradicted': body['contradicted'], 'conflicts': body['conflicts'],
            'used': used, 'budget': budget, 'program_sha256': sha}


def plan_prospective_prerequisites(query, facts, rules, program, *, budget=64):
    if type(budget) is not int or not 0 <= budget <= _PG_MAX_BUDGET:
        _sg_fail('invalid_budget')
    q = _pg_query(query)
    fs = _pg_facts(facts)
    rs = _es_rules(rules)
    normalized = _pg_program(program)
    sha = _sg_program_sha256(normalized)
    capacity = {'target': None, 'status': 'capacity', 'nodes': [], 'edges': [],
                'missing': [], 'contradicted': [], 'conflicts': []}
    used = [0]
    try:
        body = _pg_plan(q, fs, rs, budget, used)
    except _PgCapacity:
        body = capacity
    report = _es_report(q, body, used[0], budget, normalized, sha)
    if len(_canon(report).encode('utf-8')) > _PG_MAX_BYTES:
        report = _es_report(q, capacity, used[0], budget, normalized, sha)
    return _pg_detach(report, 12, 4096, _PG_MAX_BYTES, 'invalid_report')


def _es_status(history, reason):
    if reason is not None:
        return 'blocked'
    if any(h['kind'] == 'verify' and h['status'] == 'verified' for h in history):
        return 'completed'
    if any(h['kind'] == 'verify' and h['status'] == 'failed' for h in history):
        return 'waiting'
    return 'ready'


def _es_graph(status, history, pending, staged_source, staged_answer):
    if status == 'completed':
        gs = 'resolved'
    elif status == 'blocked':
        gs = 'blocked'
    else:
        gs = 'open'
    nodes = [{'id': 'goal0', 'kind': 'goal', 'status': gs}]
    edges = []
    for i, h in enumerate(history):
        oid = 'op%d' % i
        nodes.append({'id': oid, 'kind': 'operation', 'operation': h['kind'],
                      'operation_id': h['operation_id'], 'status': h['status']})
        edges.append({'source': 'goal0', 'target': oid, 'relation': 'requires'})
        if h['proof_sha256'] is not None:
            pid = 'proof%d' % i
            nodes.append({'id': pid, 'kind': 'proof', 'proof_sha256': h['proof_sha256'],
                          'attested_by': 'runtime'})
            edges.append({'source': pid, 'target': oid, 'relation': 'supports'})
        elif h['status'] in ('missing', 'rejected', 'failed'):
            fid = 'failure%d' % i
            nodes.append({'id': fid, 'kind': 'failure', 'status': h['status'],
                          'failure_code': h['failure_code']})
            edges.append({'source': oid, 'target': fid, 'relation': 'produced'})
    if pending is not None:
        nodes.append({'id': 'pending0', 'kind': 'request' if pending['kind'] == 'lookup'
                      else 'operation', 'operation': pending['kind'],
                      'operation_id': pending['operation_id'], 'status': 'pending'})
        edges.append({'source': 'goal0', 'target': 'pending0', 'relation': 'requires'})
    if staged_source is not None:
        nodes.append({'id': 'source0', 'kind': 'source', 'role': 'staged_unadmitted_source',
                      'source_sha256': staged_source['source_sha256']})
        edges.append({'source': 'source0', 'target': 'goal0', 'relation': 'candidate_for'})
    if staged_answer is not None:
        nodes.append({'id': 'answer0', 'kind': 'source', 'role': 'staged_unverified_answer',
                      'result_sha256': staged_answer['result_sha256']})
        edges.append({'source': 'answer0', 'target': 'goal0', 'relation': 'candidate_for'})
    return nodes, edges


def _es_build(goal, binding, packets, provider_id, program_sha256, counters, pending,
              staged_source, staged_answer, history, reason):
    status = _es_status(history, reason)
    nodes, edges = _es_graph(status, history, pending, staged_source, staged_answer)
    if len(nodes) > _ES_MAX_NODES or len(edges) > _ES_MAX_EDGES:
        _sg_fail('invalid_work')
    work = {'schema': _ES_SCHEMA, 'goal': goal, 'binding': binding, 'packets': packets,
            'provider_id': provider_id, 'program_sha256': program_sha256, 'status': status,
            'counters': {k: counters[k] for k in _ES_KINDS}, 'pending': pending,
            'staged_source': staged_source, 'staged_answer': staged_answer,
            'history': history, 'nodes': nodes, 'edges': edges, 'blocked_reason': reason}
    return _pg_detach(work, 10, 4000, _ES_MAX_BYTES, 'invalid_work')


def _es_replay(goal, packets, counters, pending, staged_source, staged_answer, history,
               reason):
    bad = 'invalid_work'
    seen = {k: 0 for k in _ES_KINDS}
    lookups, commits = set(), set()
    pid_shas = {_es_sha(p['source_id']): p['source_id'] for p in packets}
    src = ans = done = False
    last_lookup = last_ask = None
    vfail = 0
    for h in history:
        if type(h) is not dict or set(h) != _ES_HIST_KEYS or done:
            _sg_fail(bad)
        k = h['kind']
        if type(k) is not str or k not in _ES_KINDS:
            _sg_fail(bad)
        seen[k] += 1
        if (type(h['operation_id']) is not str or h['operation_id'] != '%s%d' % (k, seen[k])
                or not _is_hash(h['target_sha256'])):
            _sg_fail(bad)
        st, pr, fc = h['status'], h['proof_sha256'], h['failure_code']
        if type(st) is not str or st not in _ES_HIST_STATUS[k]:
            _sg_fail(bad)
        if st in ('accepted', 'verified'):
            if not _is_hash(pr):
                _sg_fail(bad)
        elif pr is not None:
            _sg_fail(bad)
        if st == 'failed':
            if type(fc) is not str or fc not in _ES_FAILURES:
                _sg_fail(bad)
        elif fc is not None:
            _sg_fail(bad)
        t = h['target_sha256']
        if k == 'lookup':
            if src or t in lookups:
                _sg_fail(bad)
            lookups.add(t)
            last_lookup = h
            src = st == 'found'
        elif k == 'admit_source':
            if not src:
                _sg_fail(bad)
            src = False
        elif k == 'commit_rule':
            if t in commits or t not in pid_shas:
                _sg_fail(bad)
            commits.add(t)
        elif k == 'ask_original':
            if ans or t != _es_sha(goal['text']):
                _sg_fail(bad)
            ans = True
            last_ask = h
        else:
            if not ans:
                _sg_fail(bad)
            ans = False
            done = st == 'verified'
            if st == 'failed':
                vfail += 1
    if src:
        s = staged_source
        if type(s) is not dict or set(s) != _ES_STAGED_KEYS:
            _sg_fail(bad)
        triple = _pg_ground(s['triple'], bad)
        text = _es_text(s['source_text'], bad)
        _es_short(s['source_id'], 128, bad)
        if (s['request_id'] != last_lookup['operation_id']
                or _es_sha(triple) != last_lookup['target_sha256']
                or not _is_hash(s['source_sha256']) or s['source_sha256'] != _es_text_sha(text)):
            _sg_fail(bad)
    elif staged_source is not None:
        _sg_fail(bad)
    if ans:
        a = staged_answer
        if (type(a) is not dict or set(a) != {'operation_id', 'result_sha256'}
                or a['operation_id'] != last_ask['operation_id']
                or not _is_hash(a['result_sha256'])):
            _sg_fail(bad)
    elif staged_answer is not None:
        _sg_fail(bad)
    if pending is not None:
        if done or type(pending) is not dict or set(pending) != _ES_ACTION_KEYS:
            _sg_fail(bad)
        k = pending['kind']
        if type(k) is not str or k not in _ES_KINDS:
            _sg_fail(bad)
        seen[k] += 1
        if type(pending['operation_id']) is not str or pending['operation_id'] != '%s%d' % (k, seen[k]):
            _sg_fail(bad)
        t = pending['target']
        if k == 'lookup':
            if src or _es_sha(_pg_ground(t, bad)) in lookups:
                _sg_fail(bad)
        elif k == 'admit_source':
            if not src or _canon(t) != _canon(staged_source):
                _sg_fail(bad)
        elif k == 'commit_rule':
            if type(t) is not str or _es_sha(t) not in pid_shas or _es_sha(t) in commits:
                _sg_fail(bad)
        elif k == 'ask_original':
            if ans or type(t) is not str or t != goal['text']:
                _sg_fail(bad)
        else:
            if not ans or type(t) is not str or t != staged_answer['result_sha256']:
                _sg_fail(bad)
    if any(seen[k] != counters[k] or seen[k] > _ES_MAX_EACH for k in _ES_KINDS):
        _sg_fail(bad)
    if done and reason is not None:
        _sg_fail(bad)
    if (vfail >= _ES_MAX_EACH) != (reason == 'capacity'):
        _sg_fail(bad)
    if reason == 'capacity' and pending is not None:
        _sg_fail(bad)


def _es_validate(work):
    w = _pg_detach(work, 10, 4000, _ES_MAX_BYTES, 'invalid_work')
    if (type(w) is not dict or set(w) != _ES_KEYS or type(w['schema']) is not str
            or w['schema'] != _ES_SCHEMA):
        _sg_fail('invalid_work')
    goal = _sg_goal(w['goal'])
    _pg_query(goal['query'])
    binding = _sg_binding(w['binding'])
    packets = _es_packets(w['packets'])
    provider_id = _es_provider(w['provider_id'])
    if not _is_hash(w['program_sha256']):
        _sg_fail('invalid_work')
    counters = w['counters']
    if (type(counters) is not dict or set(counters) != set(_ES_KINDS)
            or not all(type(counters[k]) is int and 0 <= counters[k] <= _ES_MAX_EACH
                       for k in _ES_KINDS)):
        _sg_fail('invalid_work')
    history = w['history']
    if type(history) is not list or len(history) > _ES_MAX_HISTORY:
        _sg_fail('invalid_work')
    reason = w['blocked_reason']
    if reason is not None and (type(reason) is not str or reason not in _ES_REASONS):
        _sg_fail('invalid_work')
    _es_replay(goal, packets, counters, w['pending'], w['staged_source'], w['staged_answer'],
               history, reason)
    rebuilt = _es_build(goal, binding, packets, provider_id, w['program_sha256'], counters,
                        w['pending'], w['staged_source'], w['staged_answer'], history, reason)
    if _canon(rebuilt) != _canon(w):
        _sg_fail('invalid_work')
    return rebuilt


def _es_rebuild(w, counters, pending, staged_source, staged_answer, history, reason):
    return _es_validate(_es_build(w['goal'], w['binding'], w['packets'], w['provider_id'],
                                  w['program_sha256'], counters, pending, staged_source,
                                  staged_answer, history, reason))


def _es_view(view, packets):
    v = _pg_detach(view, 4, 200, 16384, 'invalid_view')
    if type(v) is not dict or set(v) != _ES_VIEW_KEYS:
        _sg_fail('invalid_view')
    if (type(v['eligible']) is not bool or type(v['native_target_ready']) is not bool
            or not _is_hash(v['state_sha256']) or type(v['plan_status']) is not str
            or v['plan_status'] not in _ES_PLAN_STATUSES):
        _sg_fail('invalid_view')
    missing = v['missing']
    if type(missing) is not list or len(missing) > _PG_MAX_MISSING:
        _sg_fail('invalid_view')
    ms = [_pg_ground(m, 'invalid_view') for m in missing]
    if len({_canon(m) for m in ms}) != len(ms):
        _sg_fail('invalid_view')
    pids = [p['source_id'] for p in packets]
    for ids in (v['needed_rule_ids'], v['available_rule_ids']):
        if (type(ids) is not list or not all(type(x) is str and x in pids for x in ids)
                or len(set(ids)) != len(ids)):
            _sg_fail('invalid_view')
    if not set(v['available_rule_ids']) <= set(v['needed_rule_ids']):
        _sg_fail('invalid_view')
    return {'eligible': v['eligible'], 'native_target_ready': v['native_target_ready'],
            'missing': ms, 'needed': list(v['needed_rule_ids']),
            'available': list(v['available_rule_ids'])}


def _es_decide(w, program, view):
    normalized = _sg_program(w, program)
    v = _es_view(view, w['packets'])
    c, hist = w['counters'], w['history']
    nid = len(hist) + (1 if w['pending'] is not None else 0)
    if w['status'] in ('completed', 'blocked'):
        return {'kind': 'stop', 'operation_id': 'stop%d' % nid, 'target': None}
    if w['pending'] is not None or nid >= _ES_STEPCAP:
        return {'kind': 'wait' if w['pending'] is not None else 'stop',
                'operation_id': 'hold%d' % nid, 'target': None}
    looked = {h['target_sha256'] for h in hist if h['kind'] == 'lookup'}
    tried = {h['target_sha256'] for h in hist if h['kind'] == 'commit_rule'}
    staged_src = w['staged_source'] is not None
    staged_ans = w['staged_answer'] is not None
    leaf = None
    if v['eligible'] and c['lookup'] < _ES_MAX_EACH and not staged_src:
        for m in v['missing']:
            if _es_sha(m) not in looked:
                leaf = m
                break
    rule = None
    if v['eligible'] and c['commit_rule'] < _ES_MAX_EACH:
        for pid in v['needed']:
            if pid in v['available'] and _es_sha(pid) not in tried:
                rule = pid
                break
    can_ask = (v['eligible'] and c['ask_original'] < _ES_MAX_EACH and not staged_ans
               and (c['ask_original'] == 0
                    or (c['ask_original'] == 1 and v['native_target_ready'])))
    can_verify = staged_ans and c['verify'] < _ES_MAX_EACH
    can_admit = v['eligible'] and staged_src and c['admit_source'] < _ES_MAX_EACH
    ready_ask = v['eligible'] and v['native_target_ready'] and can_ask and c['ask_original'] == 1
    terminal = (not v['eligible']) or (leaf is None and rule is None and not ready_ask
                                       and not staged_src and c['lookup'] >= _ES_MAX_EACH)
    inputs = {'staged_answer': staged_ans, 'asked': c['ask_original'],
              'staged_source': staged_src, 'eligible': v['eligible'],
              'target_ready': v['native_target_ready'], 'can_commit': rule is not None,
              'can_lookup': leaf is not None, 'terminal': terminal}
    result = _sg_run(normalized, inputs, budget=_SG_VM_BUDGET)
    kind = result['value'] if result['status'] == 'completed' else None
    if type(kind) is not str or kind not in _ES_ACTIONS:
        kind = 'stop'
    # Host bounds and deterministic target binding only; the graph chose the kind.
    target = None
    if kind == 'verify':
        if not can_verify:
            kind = 'stop'
        else:
            target = w['staged_answer']['result_sha256']
    elif kind == 'ask_original':
        if not can_ask:
            kind = 'stop'
        else:
            target = w['goal']['text']
    elif kind == 'admit_source':
        if not can_admit:
            kind = 'stop'
        else:
            target = dict(w['staged_source'])
    elif kind == 'commit_rule':
        if rule is None:
            kind = 'stop'
        else:
            target = rule
    elif kind == 'lookup':
        if leaf is None:
            kind = 'stop'
        else:
            target = list(leaf)
    if kind in _ES_KINDS:
        return {'kind': kind, 'operation_id': '%s%d' % (kind, c[kind] + 1), 'target': target}
    return {'kind': kind, 'operation_id': '%s%d' % (kind, nid), 'target': None}


def new_solve_work(goal, binding, packets, provider_id, program_sha256):
    g = _sg_goal(goal)
    _pg_query(g['query'])
    b = _sg_binding(binding)
    ps = _es_packets(packets)
    pid = _es_provider(provider_id)
    if not _is_hash(program_sha256):
        _sg_fail('invalid_program')
    zero = {k: 0 for k in _ES_KINDS}
    return _es_validate(_es_build(g, b, ps, pid, program_sha256, zero, None, None, None,
                                  [], None))


def validate_solve_work(work):
    return _es_validate(work)


def plan_solve_operation(work, program, view):
    w = _es_validate(work)
    return _pg_detach(_es_decide(w, program, view), 6, 64, 32768, 'invalid_action')


def claim_solve_operation(work, program, view):
    w = _es_validate(work)
    action = _pg_detach(_es_decide(w, program, view), 6, 64, 32768, 'invalid_action')
    kind = action['kind']
    if kind not in _ES_KINDS:
        if (w['status'] not in ('completed', 'blocked') and w['pending'] is None
                and w['staged_answer'] is None):
            w = _es_rebuild(w, w['counters'], None, w['staged_source'], None,
                             list(w['history']), 'no_progress')
        return w, action
    counters = dict(w['counters'])
    counters[kind] += 1
    pending = _pg_detach(action, 6, 64, 32768, 'invalid_action')
    nw = _es_rebuild(w, counters, pending, w['staged_source'], w['staged_answer'],
                     list(w['history']), None)
    return nw, action


def record_solve_result(work, result):
    w = _es_validate(work)
    p = w['pending']
    if p is None or w['status'] in ('completed', 'blocked'):
        _sg_fail('invalid_transition')
    r = _pg_detach(result, 3, 16, 32768, 'invalid_result')
    k = p['kind']
    if type(r) is not dict or type(r.get('kind')) is not str or r['kind'] != k:
        _sg_fail('invalid_result')
    entry = {'operation_id': p['operation_id'], 'kind': k,
             'target_sha256': _es_sha(p['target']), 'status': None, 'proof_sha256': None,
             'failure_code': None}
    staged_source, staged_answer, reason = w['staged_source'], w['staged_answer'], None
    if k == 'lookup':
        if set(r) != {'kind', 'status', 'source_text', 'source_id'}:
            _sg_fail('invalid_result')
        if r['status'] == 'found':
            text = _es_text(r['source_text'], 'invalid_result')
            sid = _es_short(r['source_id'], 128, 'invalid_result')
            staged_source = {'request_id': p['operation_id'], 'triple': list(p['target']),
                             'source_id': sid, 'source_text': text,
                             'source_sha256': _es_text_sha(text)}
            entry['status'] = 'found'
        elif r['status'] == 'missing' and r['source_text'] is None and r['source_id'] is None:
            entry['status'] = 'missing'
        else:
            _sg_fail('invalid_result')
    elif k in ('admit_source', 'commit_rule'):
        if set(r) != {'kind', 'accepted', 'proof_sha256'} or type(r['accepted']) is not bool:
            _sg_fail('invalid_result')
        if r['accepted']:
            if not _is_hash(r['proof_sha256']):
                _sg_fail('invalid_result')
            entry['status'] = 'accepted'
            entry['proof_sha256'] = r['proof_sha256']
        else:
            if r['proof_sha256'] is not None:
                _sg_fail('invalid_result')
            entry['status'] = 'rejected'
        if k == 'admit_source':
            staged_source = None
    elif k == 'ask_original':
        if set(r) != {'kind', 'result_sha256'} or not _is_hash(r['result_sha256']):
            _sg_fail('invalid_result')
        entry['status'] = 'returned'
        staged_answer = {'operation_id': p['operation_id'], 'result_sha256': r['result_sha256']}
    else:
        if (set(r) != {'kind', 'verified', 'proof_sha256', 'failure_code'}
                or type(r['verified']) is not bool):
            _sg_fail('invalid_result')
        if r['verified']:
            if not _is_hash(r['proof_sha256']) or r['failure_code'] is not None:
                _sg_fail('invalid_result')
            entry['status'] = 'verified'
            entry['proof_sha256'] = r['proof_sha256']
        else:
            fc = r['failure_code']
            if r['proof_sha256'] is not None or type(fc) is not str or fc not in _ES_FAILURES:
                _sg_fail('invalid_result')
            entry['status'] = 'failed'
            entry['failure_code'] = fc
            if w['counters']['verify'] >= _ES_MAX_EACH:
                reason = 'capacity'
        staged_answer = None
    return _es_rebuild(w, w['counters'], None, staged_source, staged_answer,
                       list(w['history']) + [entry], reason)


def recover_solve_work(work, *, binding, provider_id, program_sha256):
    w = _es_validate(work)
    b = _sg_binding(binding)
    pid = _es_provider(provider_id)
    if not _is_hash(program_sha256):
        _sg_fail('invalid_program')
    if w['status'] in ('blocked', 'completed'):
        return w
    if (_canon(b) != _canon(w['binding']) or pid != w['provider_id']
            or program_sha256 != w['program_sha256']):
        reason = 'stale_binding'
    elif w['pending'] is not None or w['staged_answer'] is not None:
        reason = 'interrupted'
    else:
        return w
    return _es_rebuild(w, w['counters'], w['pending'], w['staged_source'], w['staged_answer'],
                       list(w['history']), reason)


# V70 append-only: pure bounded alternative proof paths and path-control work.
# Enumeration is bounded control planning only; semantic matching/derivation reuses
# existing inference.bind/closure. No I/O, callbacks, Context or native truth here.

_AP_PLAN_SCHEMA = 'marco-alternative-proof-paths-v1'
_AP_SCHEMA = 'marco-bounded-alternative-path-work-v1'
_AP_INPUT_SCOPE = 'caller_attested_prospective_sources_not_native_truth'
_AP_PLAN_KEYS = {'schema', 'query', 'target', 'input_scope', 'facts_sha256', 'packets_sha256',
                 'status', 'paths', 'used', 'budget'}
_AP_PATH_KEYS = {'path_id', 'rule_ids', 'leaves', 'status'}
_AP_PLAN_STATUSES = ('paths', 'supported', 'ambiguous', 'unsupported', 'capacity')
_AP_PATH_STATUSES = ('ready', 'missing_premise', 'contradicted', 'conflicting_evidence',
                     'cyclic', 'capacity')
_AP_PRIORITY = ('conflicting_evidence', 'contradicted', 'cyclic', 'capacity', 'missing_premise')
_AP_IDS = ('p1', 'p2', 'p3')
_AP_PATH_IDS = ('path1', 'path2', 'path3')
_AP_KEYS = {'schema', 'goal', 'binding', 'packets', 'plan', 'program_sha256', 'status', 'used',
            'pending', 'history', 'blocked_reason', 'nodes', 'edges'}
_AP_HIST_KEYS = {'kind', 'operation_id', 'path_id', 'accepted', 'failure_code', 'proof_sha256'}
_AP_ACTION_KEYS = {'kind', 'operation_id', 'path_id'}
_AP_KINDS = ('verify_path', 'execute_path')
_AP_MAX = {'verify_path': 3, 'execute_path': 1}
_AP_VERIFY_FAILURES = ('missing_premise', 'contradicted', 'conflicting_evidence', 'cyclic',
                       'capacity', 'authority_unavailable')
_AP_REASONS = ('no_feasible_path', 'ambiguous', 'unsupported', 'native_execution_failed',
               'interrupted', 'stale_binding', 'invalid_state', 'capacity')
_AP_MAX_BUDGET = 256
_AP_MAX_ALTS = 3
_AP_MAX_RULES = 2
_AP_MAX_LEAVES = 4
_AP_MAX_HISTORY = 4
_AP_MAX_NODES = 48
_AP_MAX_EDGES = 64
_AP_MAX_BYTES = 98304
_AP_PLAN_BYTES = 32768


def _ap_packets(packets):
    code = 'invalid_packets'
    ps = _pg_detach(packets, 6, 300, 61440, code)
    if type(ps) is not list or len(ps) > len(_AP_IDS):
        _sg_fail(code)
    out, shas, norms = [], set(), set()
    for i, row in enumerate(ps):
        if type(row) is not dict or set(row) != _ES_PACKET_KEYS:
            _sg_fail(code)
        pid = _AP_IDS[i]
        if type(row['source_id']) is not str or row['source_id'] != pid:
            _sg_fail(code)
        text = _es_text(row['source_text'], code)
        sha = row['source_sha256']
        if not _is_hash(sha) or sha != _es_text_sha(text):
            _sg_fail(code)
        body, head, auth = _es_rule_parts(row['body'], row['head'], row['authority'], pid, code)
        norm = ' '.join(text.split())
        if auth['source_sha256'] != sha or sha in shas or norm in norms:
            _sg_fail(code)
        shas.add(sha)
        norms.add(norm)
        out.append({'source_id': pid, 'source_text': text, 'source_sha256': sha,
                    'body': body, 'head': head, 'authority': auth})
    return out


def _ap_flag_status(flags):
    for s in _AP_PRIORITY:
        if s in flags:
            return s
    return 'ready'


def _ap_plan_body(q, fs, ps, budget, used):
    def charge(n=1):
        if used[0] + n > budget:
            raise _PgCapacity()
        used[0] += n

    if budget == 0:
        raise _PgCapacity()
    pos, neg = set(), set()
    for f in fs:
        charge()
        (pos if f['polarity'] else neg).add(tuple(f['triple']))
    actual = []
    for f in fs:
        charge()
        t = tuple(f['triple'])
        if (f['polarity'] and t not in neg and t not in actual
                and _pg_bind(q, list(t), {}) is not None):
            actual.append(t)
    if len(actual) > 1:
        return None, 'ambiguous', []
    if len(actual) == 1:
        t = list(actual[0])
        return t, 'supported', [{'path_id': 'path1', 'rule_ids': [], 'leaves': [t],
                                 'status': 'ready'}]
    cands = []
    for t in [f['triple'] for f in fs] + [p['head'] for p in ps]:
        charge()
        if tuple(t) not in cands and _pg_bind(q, list(t), {}) is not None:
            cands.append(tuple(t))
    if len(cands) != 1:
        return None, ('ambiguous' if cands else 'unsupported'), []
    target = cands[0]

    def expand(goal, depth, onpath):
        charge()
        if goal in pos and goal in neg:
            return [([], [goal], {'conflicting_evidence'})]
        if goal in neg:
            return [([], [goal], {'contradicted'})]
        if depth > 0 and goal in pos:
            return [([], [goal], set())]
        if goal in onpath:
            return [([], [], {'cyclic'})]
        matching = []
        for p in ps:
            charge()
            if tuple(p['head']) == goal:
                matching.append(p)
        if not matching:
            return [([], [goal], {'missing_premise'})]
        if depth >= _PG_MAX_DEPTH:
            return [([], [goal], {'capacity'})]
        alts = []
        for p in matching:
            combos = [([], [], set())]
            for b in p['body']:
                sub = expand(tuple(b), depth + 1, onpath | {goal})
                nxt = []
                for c in combos:
                    for s in sub:
                        charge()
                        rids = c[0] + [x for x in s[0] if x not in c[0]]
                        leaves = c[1] + [x for x in s[1] if x not in c[1]]
                        nxt.append((rids, leaves, c[2] | s[2]))
                        if len(nxt) > _AP_MAX_ALTS:
                            raise _PgCapacity()
                combos = nxt
            for c in combos:
                charge()
                rids = c[0] + ([p['source_id']] if p['source_id'] not in c[0] else [])
                if len(rids) > _AP_MAX_RULES or len(c[1]) > _AP_MAX_LEAVES:
                    raise _PgCapacity()
                alts.append((rids, c[1], c[2]))
                if len(alts) > _AP_MAX_ALTS:
                    raise _PgCapacity()
        return alts

    alts = expand(target, 0, frozenset())
    if not alts or len(alts) > _AP_MAX_ALTS:
        raise _PgCapacity()
    adapted = [{'triple': list(f['triple']), 'polarity': f['polarity'], 'modality': 'asserted',
                'evidence': {'source_sha256': f['source_sha256']}} for f in fs]
    by_id = {p['source_id']: p for p in ps}
    paths = []
    for i, (rids, leaves, flags) in enumerate(alts):
        charge()
        status = _ap_flag_status(flags)
        if status == 'ready':
            # Per-path isolation: actual facts plus only this path's rule subset.
            crules = [{'id': r, 'body': [list(b) for b in by_id[r]['body']],
                       'head': list(by_id[r]['head'])} for r in rids]
            metrics = {}
            try:
                known = _pg_closure(adapted, crules, limit=_PG_CLOSURE_LIMIT, metrics=metrics)
            except ValueError:
                raise _PgCapacity() from None
            charge(metrics.get('rule_scans', 0) + metrics.get('join_attempts', 0))
            if target not in known:
                status = 'missing_premise'
        paths.append({'path_id': _AP_PATH_IDS[i], 'rule_ids': list(rids),
                      'leaves': [list(x) for x in leaves], 'status': status})
    return list(target), 'paths', paths


def plan_alternative_paths(query, facts, packets, *, budget=128):
    if type(budget) is not int or not 0 <= budget <= _AP_MAX_BUDGET:
        _sg_fail('invalid_budget')
    q = _pg_query(query)
    fs = _pg_facts(facts)
    ps = _ap_packets(packets)
    used = [0]
    try:
        target, status, paths = _ap_plan_body(q, fs, ps, budget, used)
    except _PgCapacity:
        target, status, paths = None, 'capacity', []
    plan = {'schema': _AP_PLAN_SCHEMA, 'query': list(q), 'target': target,
            'input_scope': _AP_INPUT_SCOPE, 'facts_sha256': _es_sha(fs),
            'packets_sha256': _es_sha(ps), 'status': status, 'paths': paths,
            'used': used[0], 'budget': budget}
    return _pg_detach(plan, 8, 2000, _AP_PLAN_BYTES, 'invalid_report')


def _ap_plan_check(plan, goal, packets):
    bad = 'invalid_plan'
    p = _pg_detach(plan, 8, 2000, _AP_PLAN_BYTES, bad)
    if (type(p) is not dict or set(p) != _AP_PLAN_KEYS or p['schema'] != _AP_PLAN_SCHEMA
            or p['input_scope'] != _AP_INPUT_SCOPE):
        _sg_fail(bad)
    q = _pg_query(p['query'])
    if (q != goal['query'] or p['packets_sha256'] != _es_sha(packets)
            or not _is_hash(p['facts_sha256'])):
        _sg_fail(bad)
    b, u = p['budget'], p['used']
    if (type(b) is not int or type(u) is not int or not 0 <= u <= b <= _AP_MAX_BUDGET):
        _sg_fail(bad)
    status, paths = p['status'], p['paths']
    if type(status) is not str or status not in _AP_PLAN_STATUSES or type(paths) is not list:
        _sg_fail(bad)
    pids = [k['source_id'] for k in packets]
    if status in ('paths', 'supported'):
        target = _pg_ground(p['target'], bad)
        if _pg_bind(q, target, {}) is None or not 1 <= len(paths) <= _AP_MAX_ALTS:
            _sg_fail(bad)
        for i, row in enumerate(paths):
            if (type(row) is not dict or set(row) != _AP_PATH_KEYS
                    or row['path_id'] != _AP_PATH_IDS[i]):
                _sg_fail(bad)
            rids, leaves, st = row['rule_ids'], row['leaves'], row['status']
            if (type(rids) is not list or len(rids) > _AP_MAX_RULES
                    or not all(type(x) is str and x in pids for x in rids)
                    or len(set(rids)) != len(rids)):
                _sg_fail(bad)
            if type(leaves) is not list or len(leaves) > _AP_MAX_LEAVES:
                _sg_fail(bad)
            ls = [_pg_ground(x, bad) for x in leaves]
            if len({_canon(x) for x in ls}) != len(ls):
                _sg_fail(bad)
            if type(st) is not str or st not in _AP_PATH_STATUSES:
                _sg_fail(bad)
        if status == 'supported':
            r = paths[0]
            if (len(paths) != 1 or r['rule_ids'] != [] or r['leaves'] != [target]
                    or r['status'] != 'ready'):
                _sg_fail(bad)
    elif p['target'] is not None or paths != []:
        _sg_fail(bad)
    return p


def _ap_replay(plan, history, pending, reason):
    bad = 'invalid_work'
    paths = {p['path_id']: p for p in plan['paths']}
    used = {k: 0 for k in _AP_KINDS}
    tried, verified = set(), set()
    executed = [None]

    def step(row):
        k = row['kind']
        if type(k) is not str or k not in _AP_KINDS or executed[0] is not None:
            _sg_fail(bad)
        used[k] += 1
        oid, pid = row['operation_id'], row['path_id']
        if (used[k] > _AP_MAX[k] or type(oid) is not str or oid != '%s%d' % (k, used[k])
                or type(pid) is not str or pid not in paths):
            _sg_fail(bad)
        if k == 'verify_path' and pid in tried:
            _sg_fail(bad)
        if k == 'execute_path' and pid not in verified:
            _sg_fail(bad)
        return k, pid

    if type(history) is not list or len(history) > _AP_MAX_HISTORY:
        _sg_fail(bad)
    for h in history:
        if type(h) is not dict or set(h) != _AP_HIST_KEYS:
            _sg_fail(bad)
        k, pid = step(h)
        acc, fc, pr = h['accepted'], h['failure_code'], h['proof_sha256']
        if type(acc) is not bool:
            _sg_fail(bad)
        if acc:
            if fc is not None or not _is_hash(pr):
                _sg_fail(bad)
        elif pr is not None:
            _sg_fail(bad)
        if k == 'verify_path':
            if not acc and (type(fc) is not str or fc not in _AP_VERIFY_FAILURES):
                _sg_fail(bad)
            if acc and paths[pid]['status'] != 'ready':
                _sg_fail(bad)
            if (not acc and paths[pid]['status'] != 'ready'
                    and fc not in (paths[pid]['status'], 'authority_unavailable')):
                _sg_fail(bad)
            tried.add(pid)
            if acc:
                verified.add(pid)
        else:
            if not acc and (type(fc) is not str or fc != 'native_execution_failed'):
                _sg_fail(bad)
            executed[0] = acc
    if pending is not None:
        if type(pending) is not dict or set(pending) != _AP_ACTION_KEYS:
            _sg_fail(bad)
        step(pending)
    if reason is not None and (type(reason) is not str or reason not in _AP_REASONS):
        _sg_fail(bad)
    if executed[0] is True and reason is not None:
        _sg_fail(bad)
    if (executed[0] is False) != (reason == 'native_execution_failed'):
        _sg_fail(bad)
    if reason == 'interrupted' and pending is None:
        _sg_fail(bad)
    if pending is not None and reason not in (None, 'interrupted', 'stale_binding'):
        _sg_fail(bad)
    return used, executed[0]


def _ap_graph(status, plan, history, pending):
    gs = 'resolved' if status == 'completed' else ('blocked' if status == 'blocked' else 'open')
    nodes = [{'id': 'goal0', 'kind': 'goal', 'status': gs}]
    edges = []
    for p in plan['paths']:
        nodes.append({'id': p['path_id'], 'kind': 'path', 'rule_ids': list(p['rule_ids']),
                      'status': p['status']})
        edges.append({'source': 'goal0', 'target': p['path_id'], 'relation': 'alternative'})
    for i, h in enumerate(history):
        oid = 'op%d' % i
        nodes.append({'id': oid, 'kind': 'operation', 'operation': h['kind'],
                      'operation_id': h['operation_id'], 'accepted': h['accepted']})
        edges.append({'source': h['path_id'], 'target': oid, 'relation': 'checked_by'})
        if h['accepted']:
            nodes.append({'id': 'proof%d' % i, 'kind': 'proof',
                          'proof_sha256': h['proof_sha256'], 'attested_by': 'runtime'})
            edges.append({'source': 'proof%d' % i, 'target': oid, 'relation': 'supports'})
        else:
            nodes.append({'id': 'failure%d' % i, 'kind': 'failure',
                          'failure_code': h['failure_code']})
            edges.append({'source': oid, 'target': 'failure%d' % i, 'relation': 'produced'})
    if pending is not None:
        nodes.append({'id': 'pending0', 'kind': 'operation', 'operation': pending['kind'],
                      'operation_id': pending['operation_id'], 'status': 'pending'})
        edges.append({'source': pending['path_id'], 'target': 'pending0',
                      'relation': 'checked_by'})
    return nodes, edges


def _ap_build(goal, binding, packets, plan, program_sha256, history, pending, reason):
    used, executed = _ap_replay(plan, history, pending, reason)
    if reason is not None:
        status = 'blocked'
    elif executed is True:
        status = 'completed'
    elif pending is not None:
        status = 'running'
    else:
        status = 'ready'
    nodes, edges = _ap_graph(status, plan, history, pending)
    if len(nodes) > _AP_MAX_NODES or len(edges) > _AP_MAX_EDGES:
        _sg_fail('invalid_work')
    work = {'schema': _AP_SCHEMA, 'goal': goal, 'binding': binding, 'packets': packets,
            'plan': plan, 'program_sha256': program_sha256, 'status': status,
            'used': {k: used[k] for k in _AP_KINDS}, 'pending': pending,
            'history': history, 'blocked_reason': reason, 'nodes': nodes, 'edges': edges}
    return _pg_detach(work, 12, 6000, _AP_MAX_BYTES, 'invalid_work')


def _ap_validate(work):
    w = _pg_detach(work, 12, 6000, _AP_MAX_BYTES, 'invalid_work')
    if (type(w) is not dict or set(w) != _AP_KEYS or type(w['schema']) is not str
            or w['schema'] != _AP_SCHEMA):
        _sg_fail('invalid_work')
    goal = _sg_goal(w['goal'])
    _pg_query(goal['query'])
    binding = _sg_binding(w['binding'])
    packets = _ap_packets(w['packets'])
    plan = _ap_plan_check(w['plan'], goal, packets)
    if not _is_hash(w['program_sha256']):
        _sg_fail('invalid_work')
    rebuilt = _ap_build(goal, binding, packets, plan, w['program_sha256'], w['history'],
                        w['pending'], w['blocked_reason'])
    if _canon(rebuilt) != _canon(w):
        _sg_fail('invalid_work')
    return rebuilt


def _ap_rebuild(w, history, pending, reason):
    return _ap_validate(_ap_build(w['goal'], w['binding'], w['packets'], w['plan'],
                                  w['program_sha256'], history, pending, reason))


def new_paths_work(goal, binding, packets, plan, program_sha256):
    g = _sg_goal(goal)
    _pg_query(g['query'])
    b = _sg_binding(binding)
    ps = _ap_packets(packets)
    p = _ap_plan_check(plan, g, ps)
    if not _is_hash(program_sha256):
        _sg_fail('invalid_program')
    return _ap_validate(_ap_build(g, b, ps, p, program_sha256, [], None, None))


def validate_paths_work(work):
    return _ap_validate(work)


def claim_paths_operation(work, program):
    w = _ap_validate(work)
    normalized = _sg_program(w, program)
    stop = {'kind': 'stop', 'operation_id': 'stop', 'path_id': None}
    if w['status'] != 'ready':
        # Terminal or pending: never cleared or advanced by a claim.
        return w, stop
    hist, plan, used = w['history'], w['plan'], w['used']
    tried = {h['path_id'] for h in hist if h['kind'] == 'verify_path'}
    rejected = any(not h['accepted'] for h in hist)
    executed = used['execute_path'] >= _AP_MAX['execute_path']
    verified = [h['path_id'] for h in hist if h['kind'] == 'verify_path' and h['accepted']]
    feasible = plan['status'] in ('paths', 'supported')
    candidate = verified[0] if (feasible and verified and not executed) else None
    untried = None
    if feasible and not executed and used['verify_path'] < _AP_MAX['verify_path']:
        for p in plan['paths']:
            if p['path_id'] not in tried:
                untried = p['path_id']
                break
    terminal = (not feasible) or (candidate is None and untried is None)
    inputs = {'verified': candidate is not None, 'untried': untried is not None,
              'rejected': rejected, 'terminal': terminal}
    result = _sg_run(normalized, inputs, budget=_SG_VM_BUDGET)
    kind = result['value'] if result['status'] == 'completed' else None
    # Host legality gates bind the exact next path; the graph chose the kind.
    action = None
    if kind == 'execute_path' and candidate is not None:
        action = {'kind': kind, 'operation_id': 'execute_path%d' % (used[kind] + 1),
                  'path_id': candidate}
    elif kind == 'verify_path' and candidate is None and untried is not None:
        action = {'kind': kind, 'operation_id': 'verify_path%d' % (used[kind] + 1),
                  'path_id': untried}
    if action is None:
        reason = {'ambiguous': 'ambiguous', 'unsupported': 'unsupported',
                  'capacity': 'capacity'}.get(plan['status'], 'no_feasible_path')
        return _ap_rebuild(w, list(hist), None, reason), stop
    return _ap_rebuild(w, list(hist), dict(action), None), action


def record_paths_result(work, result):
    w = _ap_validate(work)
    p = w['pending']
    if p is None or w['status'] != 'running':
        _sg_fail('invalid_transition')
    r = _pg_detach(result, 2, 16, 4096, 'invalid_result')
    k = p['kind']
    if type(r) is not dict or type(r.get('kind')) is not str or r['kind'] != k:
        _sg_fail('invalid_result')
    entry = {'kind': k, 'operation_id': p['operation_id'], 'path_id': p['path_id'],
             'accepted': None, 'failure_code': None, 'proof_sha256': None}
    reason = None
    if k == 'verify_path':
        if (set(r) != {'kind', 'accepted', 'failure_code', 'proof_sha256'}
                or type(r['accepted']) is not bool):
            _sg_fail('invalid_result')
        if r['accepted']:
            path = [x for x in w['plan']['paths'] if x['path_id'] == p['path_id']][0]
            if (r['failure_code'] is not None or not _is_hash(r['proof_sha256'])
                    or path['status'] != 'ready'):
                _sg_fail('invalid_result')
            entry['proof_sha256'] = r['proof_sha256']
        else:
            fc = r['failure_code']
            if (r['proof_sha256'] is not None or type(fc) is not str
                    or fc not in _AP_VERIFY_FAILURES):
                _sg_fail('invalid_result')
            path = [x for x in w['plan']['paths'] if x['path_id'] == p['path_id']][0]
            if (path['status'] != 'ready'
                    and fc not in (path['status'], 'authority_unavailable')):
                _sg_fail('invalid_result')
            entry['failure_code'] = fc
        entry['accepted'] = r['accepted']
    else:
        if (set(r) != {'kind', 'completed', 'proof_sha256'}
                or type(r['completed']) is not bool):
            _sg_fail('invalid_result')
        if r['completed']:
            if not _is_hash(r['proof_sha256']):
                _sg_fail('invalid_result')
            entry['proof_sha256'] = r['proof_sha256']
        else:
            if r['proof_sha256'] is not None:
                _sg_fail('invalid_result')
            entry['failure_code'] = 'native_execution_failed'
            reason = 'native_execution_failed'
        entry['accepted'] = r['completed']
    return _ap_rebuild(w, list(w['history']) + [entry], None, reason)


def recover_paths_work(work, *, binding, program_sha256):
    w = _ap_validate(work)
    b = _sg_binding(binding)
    if not _is_hash(program_sha256):
        _sg_fail('invalid_program')
    if w['status'] in ('blocked', 'completed'):
        return w
    if _canon(b) != _canon(w['binding']) or program_sha256 != w['program_sha256']:
        reason = 'stale_binding'
    elif w['pending'] is not None:
        reason = 'interrupted'
    else:
        return w
    return _ap_rebuild(w, list(w['history']), w['pending'], reason)
