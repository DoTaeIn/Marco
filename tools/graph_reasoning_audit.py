"""Explicit graph reasoning audits; no model, learning, persistence or text replay.

Proof checking establishes derivability from supplied facts/rules, never truth
of those inputs. VM replay checks deterministic execution, not logical truth.
"""
import hashlib
import json

from marco.reasoning.graph_contract import validate_frame
from marco.reasoning.graph_vm import run_recorded, validate_value, MAXIMUM_BUDGET
from marco.reasoning.proof_graph import build_proof_graph, verify_proof_graph


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def audit_query(facts, rules, target, **limits):
    record = build_proof_graph(facts, rules, target, **limits)
    verification = verify_proof_graph(record, facts, rules, target)
    return {'record': record, 'verification': verification,
            'conclusion': list(target) if verification['conclusion_verified'] else None}


def _frame_facts(frame, asserted_scope):
    frame = validate_frame(frame)
    if type(asserted_scope) is not str or not asserted_scope or len(asserted_scope) > 256:
        raise ValueError('invalid_asserted_scope')
    facts, excluded = [], []
    for edge in frame['edges']:
        if edge['scope'] != asserted_scope:
            excluded.append(edge['id'])
            continue
        facts.append({'id': 'f:' + _sha(edge['id'])[:48],
                      'triple': [edge['source'], edge['relation'], edge['target']],
                      'evidence': {'frame_edge': edge['id'], 'source_refs': edge['evidence']},
                      'polarity': True, 'modality': 'asserted'})
    return frame, facts, excluded


def audit_frame(frame, rules, target, *, asserted_scope, **limits):
    """Caller explicitly selects positive asserted scope; no automatic scope meaning."""
    frame, facts, excluded = _frame_facts(frame, asserted_scope)
    audit = audit_query(facts, rules, target, **limits)
    return {'frame_sha256': _sha(frame), 'asserted_scope': asserted_scope,
            'excluded_scope_edges': excluded, 'audit': audit}


def verify_frame_audit(receipt, frame, rules, target, *, asserted_scope):
    frame, facts, excluded = _frame_facts(frame, asserted_scope)
    try:
        receipt = validate_value(receipt)
        if (type(receipt) is not dict or receipt.keys() !=
                {'frame_sha256', 'asserted_scope', 'excluded_scope_edges', 'audit'}
                or receipt['frame_sha256'] != _sha(frame)
                or receipt['asserted_scope'] != asserted_scope
                or receipt['excluded_scope_edges'] != excluded):
            return {'valid': False, 'conclusion_verified': False, 'reason': 'frame_mismatch'}
        audit = receipt['audit']
        if type(audit) is not dict or audit.keys() != {'record', 'verification', 'conclusion'}:
            return {'valid': False, 'conclusion_verified': False, 'reason': 'invalid_audit'}
        checked = verify_proof_graph(audit['record'], facts, rules, target)
        expected = list(target) if checked['conclusion_verified'] else None
        if audit['conclusion'] != expected or audit['verification'] != checked:
            return {'valid': False, 'conclusion_verified': False, 'reason': 'audit_mismatch'}
        return checked
    except (ValueError, KeyError, TypeError):
        return {'valid': False, 'conclusion_verified': False, 'reason': 'invalid_audit'}


def verify_vm_record(execution, program, inputs, *, max_budget=4096):
    """One explicit replay of caller-supplied authoritative program/input snapshots."""
    if type(max_budget) is not int or not 0 <= max_budget <= MAXIMUM_BUDGET:
        raise ValueError('invalid_replay_budget')
    try:
        if type(execution) is not dict or execution.keys() != {'result', 'record'}:
            return {'valid': False, 'execution_completed': False, 'reason': 'invalid_record'}
        result = validate_value(execution['result'])
        record = validate_value(execution['record'])
        if type(record) is not dict or record.get('complete') is not True:
            return {'valid': False, 'execution_completed': False, 'reason': 'incomplete'}
        budget, cap = record.get('budget'), record.get('trace_limit')
        if (type(budget) is not int or not 0 <= budget <= MAXIMUM_BUDGET
                or budget > max_budget
                or type(cap) is not int or not 1 <= cap <= 256):
            return {'valid': False, 'execution_completed': False, 'reason': 'invalid_record'}
        replay = run_recorded(program, inputs, budget=budget, trace_limit=cap)
        if _canonical(replay['record']) != _canonical(record) or _canonical(replay['result']) != _canonical(result):
            return {'valid': False, 'execution_completed': False, 'reason': 'replay_mismatch'}
        return {'valid': True, 'execution_completed': result.get('status') == 'completed',
                'reason': 'replayed'}
    except (ValueError, KeyError, TypeError):
        return {'valid': False, 'execution_completed': False, 'reason': 'invalid_record'}


def audit_vm(program, inputs, *, budget=4096, trace_limit=128):
    execution = run_recorded(program, inputs, budget=budget, trace_limit=trace_limit)
    return {'execution': execution, 'verification': verify_vm_record(execution, program, inputs, max_budget=budget)}
