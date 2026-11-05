"""Verified graph turn: recorded execution, host checks, replay and proof.

Python only orchestrates bounded structural checks; the graph program and model
own language and intent choices. There is no parser, template, learning or
persistence here, and held turns never commit a candidate frame. VM replay
attests deterministic execution and a valid proof attests derivability from
original frame edges; neither proves that the sentence interpretation or the
real-world premises are correct.
"""
import json

from marco.reasoning.graph_contract import execute_frame_recorded, recorded_inputs, validate_frame
from marco.reasoning.graph_vm import validate_value
from marco.reasoning.proof_graph import verify_proof_graph
from marco.runtime.graph_route_work import solve_verified_goal
from tools.graph_reasoning_audit import _frame_facts, audit_frame, verify_frame_audit, verify_vm_record
from tools.graph_surface_compaction import validate_indexes


ROLES = ('unsupported', 'observed', 'answered', 'missing', 'ambiguous')
_FIELDS = ('nodes', 'edges', 'sources', 'spans')
_MEANING_KEYS = frozenset(('kind', 'subject', 'relation', 'object', 'scope'))


class _Held(Exception):
    def __init__(self, stage, reason):
        super().__init__(reason)
        self.stage, self.reason = stage, reason


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _opaque(value):
    return type(value) is str and bool(value) and len(value) <= 128


def _roles(model):
    responses = model.get('responses')
    if type(responses) is not dict:
        raise ValueError('model_roles')
    statuses = {}
    for role in ROLES:
        row = responses.get(role)
        status = row.get('status') if type(row) is dict else None
        if type(status) is not str or not status or len(status) > 256 or status in statuses:
            raise ValueError('model_roles')
        statuses[status] = role
    suffix = model.get('answer_suffix')
    if type(suffix) is not str or not suffix:
        raise ValueError('model_suffix')
    return statuses


def _meaning_ok(meaning, labels, model):
    if type(meaning) is not dict or meaning.keys() != _MEANING_KEYS:
        return False
    if meaning['kind'] not in ('observation', 'query'):
        return False
    if not _opaque(meaning['subject']) or meaning['subject'] not in labels:
        return False
    obj = meaning['object']
    if obj is None:
        if meaning['kind'] != 'query':
            return False
    elif not _opaque(obj) or obj not in labels:
        return False
    return (_opaque(meaning['relation']) and _opaque(meaning['scope'])
            and meaning['relation'] == model.get('relation')
            and meaning['scope'] == model.get('scope'))


def _observation(check, original, inputs, value, meaning, model):
    after = value['frame']
    new = {field: after[field][len(original[field]):] for field in _FIELDS}
    source = inputs['source']
    check('observation_nodes', new['nodes'] == [], 'unrelated_node')
    check('observation_source', len(new['sources']) == 1
          and _canonical(new['sources'][0]) == _canonical(source)
          and source['text'] == inputs['text'], 'observation_source')
    spans = new['spans']
    check('observation_span', len(spans) == 1 and spans[0]['source'] == source['id']
          and spans[0]['start'] == 0 and spans[0]['end'] == len(inputs['text']), 'observation_span')
    span_id = spans[0]['id']
    edges = new['edges']
    edge = edges[0] if len(edges) == 1 else None
    check('observation_edge', edge is not None
          and [edge['source'], edge['relation'], edge['target'], edge['scope']]
          == [meaning['subject'], meaning['relation'], meaning['object'], meaning['scope']]
          and edge['evidence'] == [span_id], 'observation_edge')
    evidence = value['evidence']
    check('observation_evidence', span_id in evidence
          and set(evidence) <= {span_id, edge['id'], source['id']}, 'observation_evidence')
    expected = model['responses']['observed'].get('answer')
    check('observation_answer', type(expected) is str and value['answer'] == expected, 'observation_answer')
    return after, value['answer'], 'observed'


def _query(check, state, original, value, meaning, model, rules, strategy_program=None, routes=(),
           budget=4096, trace_limit=128):
    check('query_frame', _canonical(value['frame']) == _canonical(original), 'query_mutated')
    check('query_object', meaning['object'] is not None, 'role_meaning_mismatch')
    target = [meaning['subject'], meaning['relation'], meaning['object']]
    scope = meaning['scope']
    if strategy_program is None:
        try:
            receipt = audit_frame(validate_value(original), validate_value(rules), list(target), asserted_scope=scope)
            state['proof'] = validate_value(receipt)
            verdict = verify_frame_audit(receipt, validate_value(original), validate_value(rules),
                                         list(target), asserted_scope=scope)
        except (ValueError, TypeError, KeyError):
            verdict = {}
    else:
        try:
            facts = _frame_facts(original, scope)[1]
            work = solve_verified_goal(strategy_program, facts, rules, list(target), routes=routes,
                                       budget=budget, trace_limit=trace_limit)
            state['proof'] = work
            verdict = {}
            if (work['status'] == 'confirmed' and work['goal'] == target
                    and work['conclusion'] == target and work['attempts']):
                verdict = verify_proof_graph(work['attempts'][-1]['record'], validate_value(facts),
                                             validate_value(rules), list(target))
        except (ValueError, TypeError, KeyError):
            verdict = {}
    check('proof', type(verdict) is dict and verdict.get('valid') is True
          and verdict.get('conclusion_verified') is True, 'proof_unverified')
    texts = model['index']['labels_by_id'].get(meaning['object'])
    expected = None
    if type(texts) is list and len(texts) == 1 and type(texts[0]) is str:
        expected = texts[0] + model['answer_suffix']
    check('realization', expected is not None and value['answer'] == expected, 'realization_mismatch')
    support = {edge['id'] for edge in original['edges']
               if [edge['source'], edge['relation'], edge['target']] == target and edge['scope'] == scope}
    evidence = value['evidence']
    check('query_evidence', bool(evidence) and all(ref in support for ref in evidence), 'evidence_mismatch')
    return validate_value(original), expected, 'answered'


def _turn(state, check, original, program, text, source_id, model, rules, budget, trace_limit,
          strategy_program=None, routes=()):
    check('input_frame', original is not None, 'invalid_input')
    try:
        if type(rules) not in (list, tuple):
            raise ValueError('rules')
        rules = validate_value(list(rules))
        program = validate_value(program)
        model = validate_indexes({'frame': original, 'model': model})['model']
        inputs = recorded_inputs(original, text=text, source_id=source_id, model=model)
        state['input_source'] = validate_value(inputs['source'])
        statuses = _roles(model)
    except (ValueError, TypeError, UnicodeEncodeError):
        check('input_snapshot', False, 'invalid_input')
    recorded = execute_frame_recorded(program, inputs['frame'], text=text, source_id=source_id,
                                      model=model, budget=budget, trace_limit=trace_limit)
    execution, host = recorded['execution'], recorded['host_validation']
    state['execution'] = execution
    check('execution', execution is not None, str(host.get('reason'))[:64])
    # Exactly one explicit verifier replay over the same pinned inputs; not a retry.
    try:
        replay = verify_vm_record(execution, program, inputs, max_budget=budget)
    except ValueError:
        replay = {'valid': False, 'reason': 'invalid_replay_budget'}
    check('replay', replay.get('valid') is True, ('replay_' + str(replay.get('reason')))[:64])
    check('execution_completed', replay.get('execution_completed') is True, 'execution_not_completed')
    check('host', host.get('valid') is True, str(host.get('reason'))[:64])
    value = validate_value(execution['result']['value'])
    role = statuses.get(value['status'])
    check('status_role', role is not None, 'status_role')
    meaning = value['meaning']
    if meaning is None:
        check('meaning', role != 'unsupported', 'unsupported', 'interpretation')
        check('meaning', False, 'meaning_missing')
    check('meaning_shape', _meaning_ok(meaning, model['index']['labels_by_id'], model), 'meaning_malformed')
    check('status_meaning', role != 'unsupported', 'realization_failed')
    if meaning['kind'] == 'observation':
        check('status_meaning', role == 'observed', 'role_meaning_mismatch')
        return _observation(check, original, inputs, value, meaning, model)
    check('status_meaning', role != 'observed', 'role_meaning_mismatch')
    if role in ('missing', 'ambiguous'):
        check('status_meaning', meaning['object'] is None, 'role_meaning_mismatch')
        check('reasoning', False, role, 'reasoning')
    return _query(check, state, original, value, meaning, model, rules, strategy_program, routes,
                  budget, trace_limit)


def verified_turn(program, frame, *, text, source_id, model, rules=(), budget=4096, trace_limit=128,
                  strategy_program=None, routes=()):
    """Return a confirmed canonical answer or a held, uncommitted original frame."""
    try:
        original = validate_frame(frame)
    except (ValueError, TypeError, UnicodeEncodeError):
        original = None
    state = {'execution': None, 'proof': None, 'checks': [], 'input_source': None}

    def check(name, ok, reason, stage='verification'):
        state['checks'].append({'check': name, 'ok': bool(ok), 'reason': reason})
        if not ok:
            raise _Held(stage, reason)

    def result(status, stage, reason, frame_value, answer):
        return {'frame': frame_value, 'answer': answer, 'status': status, 'stage': stage,
                'reason': reason, 'execution': state['execution'], 'proof': state['proof'],
                'verification': {'checks': state['checks'], 'input_source': state['input_source']}}

    try:
        frame_value, answer, reason = _turn(state, check, original, program, text, source_id,
                                            model, rules, budget, trace_limit,
                                            strategy_program, routes)
        return result('confirmed', 'complete', reason, frame_value, answer)
    except _Held as held:
        detached = None if original is None else validate_value(original)
        return result('held', held.stage, held.reason, detached, None)
