"""Bounded route work: an opaque graph chooses routes, the host runs and verifies each one.

The host validates structure, runs selected proofs against the FULL original
facts/rules/goal and re-verifies every record. It never plans, filters or
generates routes and never guesses an answer.
"""
from marco.reasoning.graph_vm import MAXIMUM_BUDGET, run_recorded, validate_value
from marco.reasoning.proof_graph import (build_available_proof_graph, build_proof_graph,
                                         build_reviewed_route_proof_graph,
                                         build_route_proof_graph, verify_proof_graph,
                                         verify_rule_counterexample)
from tools.graph_reasoning_audit import verify_vm_record

SCHEMA = 'marco-verified-route-work-v1'
_ACTIONS = frozenset(('attempt', 'confirm', 'hold'))
_MODALITIES = frozenset(('asserted', 'planned', 'conditional'))
_ERRORS = (ValueError, TypeError, KeyError, UnicodeEncodeError, RecursionError)


def _text(value, limit):
    return type(value) is str and bool(value) and len(value) <= limit


def _int(value, low, high):
    return type(value) is int and low <= value <= high


def _triple(value, ground):
    if type(value) is not list or len(value) != 3 or not all(_text(x, 128) for x in value):
        raise ValueError('triple')
    if ground and any(x.startswith('?') for x in value):
        raise ValueError('triple')


def _check_facts(facts):
    if type(facts) is not list or len(facts) > 32:
        raise ValueError('facts')
    seen = set()
    for fact in facts:
        if (type(fact) is not dict or not {'id', 'triple', 'evidence'} <= fact.keys()
                or not fact.keys() <= {'id', 'triple', 'evidence', 'polarity', 'modality'}
                or not _text(fact['id'], 64) or fact['id'] in seen):
            raise ValueError('facts')
        seen.add(fact['id'])
        _triple(fact['triple'], True)
        if 'polarity' in fact and type(fact['polarity']) is not bool:
            raise ValueError('facts')
        if 'modality' in fact and fact['modality'] not in _MODALITIES:
            raise ValueError('facts')


def _check_rules(rules):
    if type(rules) is not list or len(rules) > 16:
        raise ValueError('rules')
    ids = set()
    for rule in rules:
        if type(rule) is not dict or rule.keys() != {'id', 'version', 'body', 'head'}:
            raise ValueError('rules')
        version = rule['version']
        if (not _text(rule['id'], 64) or rule['id'] in ids
                or not (type(version) is int or _text(version, 32))
                or type(rule['body']) is not list or not 1 <= len(rule['body']) <= 3):
            raise ValueError('rules')
        ids.add(rule['id'])
        for triple in rule['body']:
            _triple(triple, False)
        _triple(rule['head'], False)


def _check_run(budget, trace_limit):
    if not _int(budget, 1, MAXIMUM_BUDGET) or not _int(trace_limit, 1, 256):
        raise ValueError('limits')


def _routes(value, known):
    if type(value) is dict and value.keys() == {'routes'}:
        value = value['routes']
    if type(value) is not list or not 1 <= len(value) <= 17:
        raise ValueError('routes')
    ids, selections = set(), set()
    for index, row in enumerate(value):
        if type(row) is not dict or row.keys() != {'id', 'rule_ids'} or not _text(row['id'], 128) \
                or row['id'] in ids:
            raise ValueError('routes')
        selected = row['rule_ids']
        if index == 0:
            ok = row['id'] == 'baseline' and selected is None
        else:
            ok = (type(selected) is list and len(selected) <= 16 and row['id'] != 'baseline'
                  and all(_text(x, 64) and x in known for x in selected)
                  and len(set(selected)) == len(selected))
        key = tuple(known) if selected is None else tuple(selected)
        if not ok or key in selections:
            raise ValueError('routes')
        ids.add(row['id'])
        selections.add(key)
    return validate_value(value)


def _fail(execution, reason):
    return {'routes': [], 'execution': execution,
            'verification': {'valid': False, 'execution_completed': False, 'reason': reason}}


def make_routes(catalog_program, rules, target, *, budget=4096, trace_limit=256):
    """Run the opaque catalog graph once, replay it once and validate its routes."""
    try:
        program = validate_value(catalog_program)
        rules = validate_value(rules)
        target = validate_value(target)
        _check_rules(rules)
        _triple(target, True)
        _check_run(budget, trace_limit)
        known = [rule['id'] for rule in rules]
    except _ERRORS:
        return _fail(None, 'invalid_input')
    inputs = {'rules': rules, 'target': target}
    try:
        execution = run_recorded(program, validate_value(inputs), budget=budget, trace_limit=trace_limit)
    except _ERRORS:
        return _fail(None, 'execution_error')
    try:
        verification = verify_vm_record(execution, program, validate_value(inputs), max_budget=budget)
    except _ERRORS:
        return _fail(execution, 'invalid_replay_budget')
    if type(verification) is not dict or verification.get('valid') is not True \
            or verification.get('execution_completed') is not True:
        return {'routes': [], 'execution': execution, 'verification': verification}
    try:
        routes = _routes(execution['result']['value'], known)
    except _ERRORS:
        return _fail(execution, 'invalid_routes')
    return {'routes': routes, 'execution': execution, 'verification': verification}


def _out(goal, status, reason, attempts, decisions):
    confirmed = status == 'confirmed'
    return {'schema': SCHEMA, 'goal': goal, 'status': status,
            'conclusion': list(goal) if confirmed else None, 'reason': reason,
            'attempts': attempts, 'strategy': {'decisions': decisions}}


def _good(record, verification, goal):
    return (type(verification) is dict and verification.get('valid') is True
            and verification.get('conclusion_verified') is True
            and type(record) is dict and record.get('target') == goal)


def _review(built, facts, rules, goal, proof_limit, selected, bounds):
    failed = {'raw': [], 'verifications': [], 'complete': None, 'reason': 'malformed_wrapper'}
    try:
        built = validate_value(built)
        if (type(built) is not dict or built.keys() != {'record', 'counterexamples', 'counterexamples_complete'}
                or type(built['counterexamples']) is not list
                or type(built['counterexamples_complete']) is not bool):
            raise ValueError('wrapper')
    except _ERRORS:
        return None, failed, []
    raw = built['counterexamples']
    received_count = len(raw)
    over = received_count > proof_limit
    raw = raw[:proof_limit]
    verdicts, rows = [], []
    for cert in raw:
        verdict = {'valid': False, 'reason': 'too_many_certificates'}
        if not over:
            try:
                got = verify_rule_counterexample(cert, validate_value(facts), validate_value(rules), list(goal))
                if type(got) is not dict:
                    raise ValueError('verdict')
                reason = got.get('reason')
                verdict = {'valid': got.get('valid') is True, 'reason': reason if type(reason) is str else None}
            except _ERRORS:
                verdict = {'valid': False, 'reason': 'verifier_error'}
        if verdict['valid']:
            if type(cert) is dict and _text(cert.get('id'), 256) and _text(cert.get('rule'), 64):
                if cert.get('rule_ids') == selected and cert.get('limits') == bounds:
                    rows.append({'id': cert['id'], 'rule': cert['rule']})
                else:
                    verdict = {'valid': False, 'reason': 'attempt_mismatch'}
            else:
                verdict = {'valid': False, 'reason': 'bad_identity'}
        verdicts.append(verdict)
    feedback = {'raw': raw, 'verifications': verdicts, 'complete': built['counterexamples_complete'],
                'reason': 'too_many_certificates' if over else 'ok',
                'received_count': received_count, 'omitted_count': received_count - len(raw)}
    return built['record'], feedback, rows


def solve_verified_goal(strategy_program, facts, rules, target, *, routes, max_attempts=4, budget=4096,
                        trace_limit=128, limit=32, proof_limit=4, search_limit=256,
                        counterexample_feedback=False):
    """Let the graph pick routes; confirm only a record the host verified against the originals."""
    attempts, decisions = [], []
    goal = None
    try:
        candidate_goal = validate_value(target)
        _triple(candidate_goal, True)
        goal = candidate_goal
        facts = validate_value(facts)
        rules = validate_value(rules)
        _check_facts(facts)
        _check_rules(rules)
        if type(routes) is tuple:
            routes = list(routes)
        routes = _routes(validate_value(routes), [rule['id'] for rule in rules])
        program = validate_value(strategy_program)
        _check_run(budget, trace_limit)
        if (not _int(max_attempts, 1, 8) or not _int(limit, 1, 32) or not _int(proof_limit, 1, 4)
                or not _int(search_limit, 1, 1024) or type(counterexample_feedback) is not bool):
            raise ValueError('limits')
    except _ERRORS:
        return _out(goal, 'held', 'invalid_input', attempts, decisions)
    by_id = {row['id']: row for row in routes}
    attempted, last_verified = {}, False
    evidence = []
    for _ in range(max_attempts + 1):
        remaining = max_attempts - len(attempts)
        inputs = {'goal': goal, 'routes': routes, 'attempted': dict(attempted),
                  'last_verified': last_verified, 'remaining': remaining}
        if counterexample_feedback:
            inputs['rejection_evidence'] = list(evidence)
            inputs['all_rule_ids'] = [rule['id'] for rule in rules]
        execution = None
        try:
            execution = run_recorded(program, validate_value(inputs), budget=budget, trace_limit=trace_limit)
            verification = verify_vm_record(execution, program, validate_value(inputs), max_budget=budget)
        except _ERRORS:
            decisions.append({'execution': execution, 'verification': {
                'valid': False, 'execution_completed': False, 'reason': 'strategy_error'}})
            return _out(goal, 'held', 'strategy_error', attempts, decisions)
        decisions.append({'execution': execution, 'verification': verification})
        try:
            result = execution['result']
            proposal = result['value']
            replayed = (verification['valid'] is True and verification['execution_completed'] is True
                        and result['status'] == 'completed' and execution['record']['complete'] is True)
        except _ERRORS:
            replayed = False
        if not replayed:
            return _out(goal, 'held', 'strategy_replay', attempts, decisions)
        if type(proposal) is not dict or proposal.keys() != {'action', 'route_id'} \
                or type(proposal['action']) is not str or proposal['action'] not in _ACTIONS:
            return _out(goal, 'held', 'bad_proposal', attempts, decisions)
        action, route_id = proposal['action'], proposal['route_id']
        if action == 'hold':
            return _out(goal, 'held', 'strategy_hold' if route_id is None else 'bad_proposal',
                        attempts, decisions)
        if action == 'confirm':
            if route_id is not None or not last_verified or not attempts:
                return _out(goal, 'held', 'early_confirm', attempts, decisions)
            last = attempts[-1]
            try:
                again = verify_proof_graph(last['record'], validate_value(facts), validate_value(rules),
                                           list(goal))
            except _ERRORS:
                again = {}
            if not _good(last['record'], again, goal):
                return _out(goal, 'held', 'confirm_unverified', attempts, decisions)
            return _out(goal, 'confirmed', 'verified', attempts, decisions)
        if type(route_id) is not str or route_id not in by_id:
            return _out(goal, 'held', 'unknown_route', attempts, decisions)
        if route_id in attempted:
            return _out(goal, 'held', 'repeated_route', attempts, decisions)
        if remaining <= 0:
            return _out(goal, 'held', 'attempt_cap', attempts, decisions)
        attempted[route_id] = True
        selected = by_id[route_id]['rule_ids']
        bounds = {'limit': limit, 'proof_limit': proof_limit, 'search_limit': search_limit}
        feedback = None
        try:
            if counterexample_feedback:
                built = build_reviewed_route_proof_graph(
                    validate_value(facts), validate_value(rules), list(goal),
                    rule_ids=None if selected is None else list(selected), **bounds)
                record, feedback, rows = _review(built, facts, rules, goal, proof_limit, selected, bounds)
                evidence.extend(rows)
            elif selected is None:
                record = build_proof_graph(validate_value(facts), validate_value(rules), list(goal), **bounds)
            else:
                record = build_route_proof_graph(validate_value(facts), validate_value(rules), list(goal),
                                                 rule_ids=list(selected), **bounds)
            check = verify_proof_graph(record, validate_value(facts), validate_value(rules), list(goal))
        except _ERRORS:
            record = None
            check = {'valid': False, 'conclusion_verified': False, 'reason': 'attempt_error'}
            if counterexample_feedback and feedback is None:
                feedback = {'raw': [], 'verifications': [], 'complete': None, 'reason': 'builder_error'}
        last_verified = _good(record, check, goal)
        row = {'route_id': route_id, 'record': record, 'verification': check,
               'outcome': 'verified' if last_verified else 'unverified'}
        if counterexample_feedback:
            row['counterexample_feedback'] = feedback
        attempts.append(row)
    return _out(goal, 'held', 'strategy_exhausted', attempts, decisions)


import hashlib
import json

_STEP_KEYS = frozenset(('action', 'state', 'routes', 'reason'))
_STEP_ACTIONS = frozenset(('continue', 'done', 'hold'))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def _stop(steps, state, reason):
    return {'routes': [], 'state': state, 'steps': steps,
            'verification': {'valid': False, 'execution_completed': False, 'reason': reason}}


def make_decomposed_routes(step_program, rules, target, *, max_steps=64, budget=4096, trace_limit=256,
                           depth_limit=6, route_limit=17):
    """Drive a graph state-transition program; the host only validates, replays and stops cycles."""
    try:
        program = validate_value(step_program)
        rules = validate_value(rules)
        target = validate_value(target)
        _check_rules(rules)
        _triple(target, True)
        _check_run(budget, trace_limit)
        if not (_int(max_steps, 1, 128) and _int(depth_limit, 1, 6) and _int(route_limit, 1, 17)):
            raise ValueError('limits')
        known = [rule['id'] for rule in rules]
    except _ERRORS:
        return _stop([], None, 'invalid_input')
    limits = {'depth_limit': depth_limit, 'route_limit': route_limit}
    state, steps, seen = None, [], set()
    for _ in range(max_steps):
        execution = None
        try:
            inputs = validate_value({'rules': rules, 'target': target, 'state': state, 'limits': limits})
            execution = run_recorded(program, inputs, budget=budget, trace_limit=trace_limit)
        except _ERRORS:
            return _stop(steps, state, 'execution_error')
        try:
            verification = verify_vm_record(execution, program, validate_value(inputs), max_budget=budget)
        except _ERRORS:
            steps.append({'execution': execution, 'verification': {
                'valid': False, 'execution_completed': False, 'reason': 'invalid_replay_budget'}})
            return _stop(steps, state, 'invalid_replay_budget')
        steps.append({'execution': execution, 'verification': verification})
        try:
            result = execution['result']
            replayed = (verification['valid'] is True and verification['execution_completed'] is True
                        and result['status'] == 'completed' and execution['record']['complete'] is True)
        except _ERRORS:
            replayed = False
        if not replayed:
            return _stop(steps, state, 'step_replay')
        try:
            out = validate_value(result['value'])
            if type(out) is not dict or out.keys() != _STEP_KEYS:
                raise ValueError('step')
            action, new, found, reason = out['action'], out['state'], out['routes'], out['reason']
            if type(action) is not str or action not in _STEP_ACTIONS:
                raise ValueError('action')
            if type(new) is not dict or 'goal' not in new or _digest(new['goal']) != _digest(target):
                raise ValueError('state')
            if type(found) is not list or not (reason is None or _text(reason, 128)):
                raise ValueError('step')
            if action != 'done' and found:
                raise ValueError('routes')
            fingerprint = _digest(new)
            routes = None
            if action == 'done':
                routes = _routes(found, known)
                if len(routes) > route_limit:
                    raise ValueError('routes')
        except _ERRORS:
            return _stop(steps, state, 'invalid_step_output')
        if action == 'done':
            return {'routes': routes, 'state': new, 'steps': steps,
                    'verification': {'valid': True, 'execution_completed': True, 'reason': 'completed'}}
        if action == 'hold':
            return _stop(steps, new, reason or 'hold')
        if fingerprint in seen:
            return _stop(steps, new, 'state_repeat')
        seen.add(fingerprint)
        state = new
    return _stop(steps, state, 'step_limit')


_IG_SCHEMA = 'marco-information-goal-work-v1'
_IG_OUTCOMES = frozenset(('positive', 'negative', 'unknown', 'conflict'))
_IG_ACTIONS = frozenset(('continue', 'inspect', 'ask', 'confirm', 'hold'))
_IG_LIMITATIONS = (
    'caller_attested replies and sha256 hashes verify structural report attribution only; they do not authenticate the source or establish real-world truth',
    'work digests are coherence pins, not identity or authentication; history is validated by verifying saved receipts and proofs',
    'ground triples only: variable terms are unsupported',
)


def _igc(value):
    return json.loads(json.dumps(value))


def _ig_env(program, facts, rules, target, context_id, limits):
    if type(program) is not dict:
        raise ValueError('program')
    program, facts, rules, target = _igc(program), _igc(facts), _igc(rules), _igc(target)
    _check_facts(facts)
    _check_rules(rules)
    _triple(target, True)
    for rule in rules:
        if any(x.startswith('?') for t in rule['body'] + [rule['head']] for x in t):
            raise ValueError('unsupported_variable')
    if not _text(context_id, 64):
        raise ValueError('context_id')
    if not _int(limits['max_questions'], 0, 4) or not _int(limits['max_steps'], 1, 128):
        raise ValueError('limits')
    _check_run(limits['budget'], limits['trace_limit'])
    if (not _int(limits['limit'], 1, 32) or not _int(limits['proof_limit'], 1, 4)
            or not _int(limits['search_limit'], 1, 256)):
        raise ValueError('limits')
    return {'program': program, 'facts': facts, 'rules': rules, 'target': target,
            'context': context_id, 'limits': dict(limits), 'pd': _digest(program),
            'od': _digest({'facts': facts, 'rules': rules, 'goal': target}),
            'ld': _digest(limits)}


def _ig_take(S, kind):
    if S['pos'] >= len(S['tape']):
        if not S['live']:
            raise ValueError('truncated_history')
        return None
    entry = S['tape'][S['pos']]
    if type(entry) is not dict or entry.get('kind') != kind:
        raise ValueError('history_order')
    S['pos'] += 1
    return entry


def _ig_emit(S, saved, entry):
    if saved is not None and _digest(saved) != _digest(entry):
        raise ValueError('history_mismatch:' + str(entry.get('kind')))
    S['out'].append(entry)


def _ig_put(S, kind, payload):
    _ig_emit(S, _ig_take(S, kind), dict(payload, kind=kind))


def _ig_verify(record, facts, rules, target):
    bad = {'valid': False, 'conclusion_verified': False, 'reason': 'proof_unverifiable'}
    if type(record) is not dict:
        return bad
    try:
        v = verify_proof_graph(_igc(record), _igc(facts), _igc(rules), _igc(target))
    except _ERRORS:
        return bad
    if type(v) is not dict:
        return bad
    return {'valid': v.get('valid') is True, 'conclusion_verified': v.get('conclusion_verified') is True,
            'reason': str(v.get('reason'))[:128]}


def _ig_classify(record, ver):
    if type(record) is not dict or not ver['valid']:
        return 'incomplete'
    s = record.get('status')
    if type(s) is not str:
        return 'incomplete'
    if s == 'proved':
        return 'supported' if ver['conclusion_verified'] else 'incomplete'
    return {'contradicted': 'opposed', 'conflict': 'conflict', 'unresolved': 'unknown'}.get(s, 'incomplete')


_IG_NEW = ('strict_record', 'search_complete', 'search_reason')

def _ig_new_ok(L, facts, rules, target, saved, strict_verification=None):
    sr, sc, why, rec = saved['strict_record'], saved['search_complete'], saved['search_reason'], saved['record']
    if type(sc) is not bool or not (why is None or (type(why) is str and len(why) <= 64)):
        return False
    if sr is None:
        return rec is None and sc is False and why == 'helper_failure'
    if type(sr) is not dict:
        return False
    sv = strict_verification if strict_verification is not None else _ig_verify(sr, facts, rules, target)
    if not (sv['valid'] or sv['reason'] in ('incomplete', 'unsafe_rule')):
        return False
    if sr.get('limits') != {'limit': L['limit'], 'proof_limit': L['proof_limit'], 'search_limit': L['search_limit']}:
        return False
    st, rs = sr.get('status'), sr.get('reason')
    cut = ('bundle_id_limit', 'proof_or_search_limit', 'graph_limit', 'closure_incomplete',
           'record_graph_limit', 'compact_id_collision')
    if st == 'invalid':
        ok = sc is False and why == 'unsafe_rule'
    elif st == 'incomplete':
        ok = ((sc and why is None and rs == 'record_graph_limit')
              or (not sc and rs == (why if why in cut else 'closure_incomplete')))
    else:
        ok = sc and why is None
    if not ok:
        return False
    if _digest(rec) == _digest(sr):
        return True
    if st != 'incomplete' or sc or type(rec) is not dict or rec.get('status') != 'proved':
        return False
    rv = _ig_verify(rec, facts, rules, target)
    return rv['valid'] and rv['conclusion_verified'] and rec.get('limits') == sr['limits']

def _ig_prove(env, S, kind, target, extra):
    L = env['limits']
    saved = _ig_take(S, kind)
    diag = {}
    ver = None
    if saved is None:
        try:
            out = build_available_proof_graph(_igc(S['facts']), _igc(env['rules']), target, limit=L['limit'],
                                              proof_limit=L['proof_limit'], search_limit=L['search_limit'])
            if type(out) is not dict or out.keys() != {'record', 'available_record', 'search_complete', 'search_reason'}:
                raise ValueError('helper_shape')
            strict, avail = _igc(out['record']), _igc(out['available_record'])
            sc, why = out['search_complete'], out['search_reason']
            if (type(strict) is not dict or type(sc) is not bool or not (avail is None or type(avail) is dict)
                    or not (why is None or type(why) is str)):
                raise ValueError('helper_shape')
            why = why[:64] if why is not None else None
        except _ERRORS:
            strict, avail, sc, why = None, None, False, 'helper_failure'
        record = strict
        if avail is not None and strict.get('status') == 'incomplete' and not sc:
            av = _ig_verify(avail, S['facts'], env['rules'], target)
            if av['valid'] and av['conclusion_verified'] and avail.get('status') == 'proved':
                record, ver = avail, av
        diag = {'strict_record': strict, 'search_complete': sc, 'search_reason': why}
    else:
        present = [k for k in _IG_NEW if k in saved]
        if present and len(present) != len(_IG_NEW):
            raise ValueError('history_shape')
        record = saved['record']
        if (record is not None and (type(record) is not dict
                or record.get('limits') != {'limit': L['limit'], 'proof_limit': L['proof_limit'],
                                             'search_limit': L['search_limit']})):
            raise ValueError('history_proof_limits')
        if present:
            if not _ig_new_ok(L, S['facts'], env['rules'], target, saved):
                raise ValueError('history_diagnostic')
            diag = {k: saved[k] for k in _IG_NEW}
    if ver is None:
        ver = _ig_verify(record, S['facts'], env['rules'], target)
    if saved is None:
        candidate_row = dict(diag, record=record)
        cached = ver if _digest(record) == _digest(diag['strict_record']) else None
        if not _ig_new_ok(L, S['facts'], env['rules'], target, candidate_row, strict_verification=cached):
            record = None
            ver = _ig_verify(None, S['facts'], env['rules'], target)
            diag = {'strict_record': None, 'search_complete': False, 'search_reason': 'helper_failure'}
    status = _ig_classify(record, ver)
    _ig_emit(S, saved, dict(extra, kind=kind, triple=target, record=record, verification=ver, status=status, **diag))
    return status, record, ver


def _ig_world(env, S):
    index = S['wn']
    S['wn'] += 1
    S['wd'] = _digest(S['facts'])
    S['gstatus'], S['record'], S['ver'] = _ig_prove(
        env, S, 'world', env['target'], {'index': index, 'world_digest': S['wd'], 'facts': _igc(S['facts'])})


def _ig_check_output(env, out):
    if type(out) is not dict or out.keys() != {'action', 'triple', 'state', 'hypotheses', 'reason'}:
        raise ValueError('output')
    act = out['action']
    if act not in _IG_ACTIONS:
        raise ValueError('output')
    if act in ('inspect', 'ask'):
        _triple(out['triple'], True)
    elif out['triple'] is not None:
        raise ValueError('output')
    if out['state'] is not None:
        if type(out['state']) is not dict:
            raise ValueError('output')
        validate_value(out['state'])
    ids = {r['id'] for r in env['rules']}
    hyp = out['hypotheses']
    if type(hyp) is not list or len(hyp) > 16:
        raise ValueError('output')
    for h in hyp:
        if (type(h) is not dict or h.keys() != {'rule', 'missing', 'blocked'} or h['rule'] not in ids
                or type(h['blocked']) is not bool or type(h['missing']) is not list or len(h['missing']) > 3):
            raise ValueError('output')
        for t in h['missing']:
            _triple(t, True)
    if not _text(out['reason'], 128):
        raise ValueError('output')


def _ig_judge(env, inputs, record):
    try:
        if type(record) is not dict or type(record.get('record')) is not dict:
            return False, None
        if (record.get('record', {}).get('budget') != env['limits']['budget']
                or record.get('record', {}).get('trace_limit') != env['limits']['trace_limit']):
            return False, None
        r = verify_vm_record(_igc(record), _igc(env['program']), _igc(inputs),
                             max_budget=env['limits']['budget'])
        if (type(r) is not dict or r.get('valid') is not True
                or r.get('execution_completed') is not True
                or record.get('result', {}).get('status') != 'completed'
                or record.get('record', {}).get('complete') is not True):
            return False, None
        out = record['result']['value']
        _ig_check_output(env, out)
        return True, _igc(out)
    except _ERRORS:
        return False, None


def _ig_inputs_ok(inputs):
    try:
        validate_value(inputs)
        if inputs['state'] is not None:
            validate_value(inputs['state'])
        return True
    except _ERRORS:
        return False


def _ig_step(env, S, inputs):
    L = env['limits']
    saved = _ig_take(S, 'step')
    usable = _ig_inputs_ok(inputs)
    if saved is None:
        record = None
        if usable:
            try:
                record = _igc(run_recorded(_igc(env['program']), _igc(inputs), budget=L['budget'],
                                           trace_limit=L['trace_limit']))
            except _ERRORS:
                record = None
    else:
        record = saved['receipt'] if usable else None
    ok, out = _ig_judge(env, inputs, record)
    _ig_emit(S, saved, {'kind': 'step', 'index': S['steps'], 'inputs': inputs, 'receipt': record,
                        'output': out, 'ok': ok})
    return out


def _ig_question(env, S, triple):
    return {'id': _digest({'program': env['pd'], 'context_id': env['context'], 'original': env['od'],
                           'goal': env['target'], 'world': S['wd'], 'triple': triple, 'index': S['qn'],
                           'limits': env['ld']}),
            'triple': _igc(triple), 'context_id': env['context'], 'index': S['qn'],
            'world_digest': S['wd'], 'goal': env['target'], 'program_digest': env['pd'],
            'original_digest': env['od'], 'limits_digest': env['ld']}


def _ig_accept(env, S, q, r):
    if type(r) is not dict or r.keys() != {'question_id', 'context_id', 'triple', 'outcome', 'source', 'caller_attested'}:
        raise ValueError('reply_shape')
    src = r['source']
    if (r['caller_attested'] is not True or r['outcome'] not in _IG_OUTCOMES or type(src) is not dict
            or src.keys() != {'id', 'text', 'sha256'} or not _text(src['id'], 64)
            or not _text(src['text'], 1024) or not _text(src['sha256'], 64)
            or not _text(r['question_id'], 64) or not _text(r['context_id'], 64)):
        raise ValueError('reply_fields')
    _triple(r['triple'], True)
    if (r['context_id'] != env['context'] or r['question_id'] != q['id'] or r['triple'] != q['triple']
            or r['triple'] in S['asked']):
        raise ValueError('reply_stale')
    if hashlib.sha256(src['text'].encode('utf-8')).hexdigest() != src['sha256']:
        raise ValueError('reply_hash')
    evidence = {'kind': 'caller_attested_answer', 'question_id': q['id'], 'context_id': env['context'],
                'triple': _igc(r['triple']), 'outcome': r['outcome'],
                'source': {'id': src['id'], 'text': src['text'], 'sha256': src['sha256']},
                'caller_attested': True,
                'limitation': 'structural attribution only; not authenticated real-world truth'}
    polarities = {'positive': (True,), 'negative': (False,), 'conflict': (True, False), 'unknown': ()}[r['outcome']]
    added = [{'id': 'ans-' + _digest({'question_id': q['id'], 'polarity': p})[:32], 'triple': _igc(r['triple']),
              'evidence': _igc(evidence), 'polarity': p, 'modality': 'asserted'} for p in polarities]
    newf = _igc(S['facts']) + added
    _check_facts(newf)
    return newf, added


def _ig_reverify(env, S):
    v = _ig_verify(S['record'], S['facts'], env['rules'], env['target'])
    return (v['valid'] and v['conclusion_verified'] and type(S['record']) is dict
            and S['record'].get('status') == 'proved')


def _ig_end(S, res, status, reason):
    _ig_put(S, 'stop', {'status': status, 'reason': reason})
    res['status'] = status
    res['reason'] = reason
    return res


def _ig_ask(env, S, res, triple):
    if (env['limits']['max_questions'] - S['qn'] <= 0 or triple in S['asked']
            or triple == env['target']
            or not any(o['triple'] == triple and o['status'] == 'unknown' for o in S['obs'])):
        return _ig_end(S, res, 'held', 'ask_rejected')
    replayed = S['pos'] < len(S['tape'])
    q = _ig_question(env, S, triple)
    _ig_put(S, 'question', {'question': q})
    S['qn'] += 1
    saved = _ig_take(S, 'reply') if S['pos'] < len(S['tape']) else None
    if saved is None:
        res['pending'] = q
        res['status'] = 'asking'
        res['reason'] = 'awaiting_reply'
        if not S['live']:
            claimed = S['claimed']
            if (S['pos'] != len(S['tape']) or claimed.get('status') != 'asking'
                    or _digest(claimed.get('facts')) != _digest(S['facts'])
                    or _digest(claimed.get('pending_question')) != _digest(q)):
                raise ValueError('claimed_pending_state')
        if S['reply'] is None:
            return res
        if not replayed:
            res.update(status='held', pending=None, rejected='reply_unsolicited')
            return res
        raw = S['reply']
        S['reply'] = None
        try:
            r = _igc(raw)
            newf, added = _ig_accept(env, S, q, r)
        except _ERRORS as exc:
            res.update(status='held', pending=None, rejected='reply_rejected:' + str(exc)[:96])
            return res
    else:
        r = saved['reply']
        newf, added = _ig_accept(env, S, q, r)
    if saved is None:
        S['live'] = True
    _ig_emit(S, saved, {'kind': 'reply', 'reply': r, 'added': added})
    S['facts'] = newf
    S['asked'].append(_igc(triple))
    S['state'] = None
    S['obs'] = []
    res['pending'] = None
    res['status'] = 'held'
    res['reason'] = None
    _ig_world(env, S)
    return None


def _ig_loop(env, S, res):
    L = env['limits']
    _ig_world(env, S)
    while True:
        if S['steps'] >= L['max_steps']:
            return _ig_end(S, res, 'held', 'step_limit')
        inputs = _igc({'goal': env['target'], 'rules': env['rules'], 'state': S['state'],
                       'observations': S['obs'], 'asked': S['asked'],
                       'remaining_questions': L['max_questions'] - S['qn'], 'goal_status': S['gstatus']})
        out = _ig_step(env, S, inputs)
        S['steps'] += 1
        if out is None:
            return _ig_end(S, res, 'held', 'vm_invalid')
        act = out['action']
        if act == 'continue':
            if out['state'] is None or _digest(out['state']) == _digest(S['state']):
                return _ig_end(S, res, 'held', 'no_progress')
            S['state'] = out['state']
        elif act == 'inspect':
            if any(o['triple'] == out['triple'] for o in S['obs']):
                return _ig_end(S, res, 'held', 'repeated_inspect')
            status = _ig_prove(env, S, 'probe', out['triple'], {'world': S['wn'] - 1})[0]
            if status == 'incomplete':
                return _ig_end(S, res, 'held', 'probe_incomplete')
            S['obs'].append({'triple': out['triple'], 'status': status})
            S['state'] = out['state']
        elif act == 'ask':
            done = _ig_ask(env, S, res, out['triple'])
            if done is not None:
                return done
        elif act == 'confirm':
            if S['gstatus'] != 'supported' or not _ig_reverify(env, S):
                return _ig_end(S, res, 'held', 'confirm_unverified')
            return _ig_end(S, res, 'confirmed', 'goal_supported')
        else:
            return _ig_end(S, res, 'held', 'graph_hold:' + out['reason'])


def _ig_tape(env, work):
    if type(work) is not dict:
        raise ValueError('work')
    pins = {'schema': _IG_SCHEMA, 'context_id': env['context'], 'program_digest': env['pd'],
            'original_digest': env['od'], 'limits': env['limits'], 'goal': env['target'],
            'original_facts': env['facts'], 'original_rules': env['rules']}
    for key, value in pins.items():
        if _digest(work.get(key)) != _digest(value):
            raise ValueError('pin_' + key)
    tape = work.get('transcript')
    L = env['limits']
    if type(tape) is not list or len(tape) > 2 * L['max_steps'] + 3 * L['max_questions'] + 2:
        raise ValueError('transcript_bound')
    return _igc(tape)


def _ig_base(env, status, reason):
    return {'schema': _IG_SCHEMA, 'status': status, 'reason': reason, 'pending_question': None,
            'facts': _igc(env['facts']), 'goal': _igc(env['target']), 'goal_record': None,
            'goal_verification': None, 'goal_status': 'incomplete', 'reply_rejection': None,
            'context_id': env['context'], 'original_facts': _igc(env['facts']),
            'original_rules': _igc(env['rules']), 'program_digest': env['pd'],
            'original_digest': env['od'], 'limits_digest': env['ld'], 'limits': dict(env['limits']),
            'asked': [], 'counts': {'steps': 0, 'questions': 0, 'transcript': 0, 'worlds': 0,
                                    'probes': 0, 'replies': 0},
            'transcript': [], 'limitations': list(_IG_LIMITATIONS)}


def _ig_work(env, S, res, tape, claimed):
    if S['pos'] != len(tape):
        raise ValueError('trailing_history')
    if claimed is not None and not S['live'] and res['rejected'] is None:
        if (_digest(claimed.get('facts')) != _digest(S['facts']) or claimed.get('status') != res['status']
                or _digest(claimed.get('pending_question')) != _digest(res['pending'])):
            raise ValueError('claimed_state')
    if S['reply'] is not None and res['rejected'] is None:
        res.update(status='held', pending=None, rejected='reply_not_solicited')
    kinds = [e['kind'] for e in S['out']]
    work = _ig_base(env, res['status'], res['reason'])
    work.update({'pending_question': res['pending'] if res['status'] == 'asking' else None,
                 'facts': S['facts'], 'goal_record': S['record'], 'goal_verification': S['ver'],
                 'goal_status': S['gstatus'], 'reply_rejection': res['rejected'], 'asked': S['asked'],
                 'counts': {'steps': S['steps'], 'questions': S['qn'], 'transcript': len(kinds),
                            'worlds': kinds.count('world'), 'probes': kinds.count('probe'),
                            'replies': kinds.count('reply')},
                 'transcript': S['out']})
    return _igc(work)


def advance_information_goal(program, originalfacts, originalrules, target, context_id, *, work=None,
                             reply=None, max_questions=2, max_steps=128, budget=4096, trace_limit=256,
                             limit=32, proof_limit=4, search_limit=256):
    limits = {'max_questions': max_questions, 'max_steps': max_steps, 'budget': budget,
              'trace_limit': trace_limit, 'limit': limit, 'proof_limit': proof_limit,
              'search_limit': search_limit}
    try:
        env = _ig_env(program, originalfacts, originalrules, target, context_id, limits)
    except _ERRORS as exc:
        safe_facts, safe_goal = [], None
        try:
            _check_facts(originalfacts)
            _triple(target, True)
            safe_facts, safe_goal = _igc(originalfacts), _igc(target)
        except _ERRORS:
            pass
        return {'schema': _IG_SCHEMA, 'status': 'held', 'reason': 'invalid_input:' + str(exc)[:96],
                'pending_question': None, 'facts': safe_facts, 'goal': safe_goal, 'goal_record': None,
                'goal_verification': None, 'goal_status': 'incomplete', 'transcript': [],
                'limitations': list(_IG_LIMITATIONS)}
    tape = []
    try:
        if work is not None:
            tape = _ig_tape(env, work)
        S = {'facts': _igc(env['facts']), 'asked': [], 'qn': 0, 'steps': 0, 'wn': 0, 'out': [],
             'tape': tape, 'pos': 0, 'reply': reply, 'record': None, 'ver': None,
             'gstatus': 'incomplete', 'wd': None, 'state': None, 'obs': [],
             'live': work is None, 'claimed': work}
        res = {'status': 'held', 'reason': None, 'pending': None, 'rejected': None}
        _ig_loop(env, S, res)
        return _ig_work(env, S, res, tape, work)
    except _ERRORS as exc:
        prefix = 'invalid_history:' if work is not None else 'execution_error:'
        return _ig_base(env, 'held', prefix + str(exc)[:96])
