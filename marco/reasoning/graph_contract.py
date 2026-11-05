"""Bounded graph frames with stable record IDs and exact source coordinates.

This is a data contract, not a store, parser or reasoning engine. Types,
relations and scopes are opaque model references. Validation establishes shape
and reference integrity, never semantic truth, activation or execution authority.
Frames are bounded materialized views, not a cap on the whole knowledge base.
"""
import hashlib
import json

from marco.reasoning.graph_vm import MAXIMUM_SCAN_LENGTH, RESULT_SCHEMA, run, run_recorded, validate_value


SCHEMA = 'marco-graph-frame-v1'
_KEYS = frozenset(('schema', 'nodes', 'edges', 'sources', 'spans'))
_FIELDS = ('nodes', 'edges', 'sources', 'spans')
_LEGACY_KEYS = frozenset(('frame', 'answer', 'status', 'evidence'))
_RECORDED_KEYS = _LEGACY_KEYS | {'meaning'}


def _identifier(value):
    return type(value) is str and bool(value) and len(value) <= 256


def validate_frame(frame):
    """Validate and detach one source-preserving graph frame; raise ValueError."""
    value = validate_value(frame)
    if type(value) is not dict or value.keys() != _KEYS or value['schema'] != SCHEMA:
        raise ValueError('graph_frame_schema')
    for field in ('nodes', 'edges', 'sources', 'spans'):
        if type(value[field]) is not list or len(value[field]) > MAXIMUM_SCAN_LENGTH:
            raise ValueError('graph_frame_limit')
    ids, nodes, sources = set(), set(), {}

    def register(row, keys):
        if type(row) is not dict or row.keys() != keys or not _identifier(row.get('id')):
            raise ValueError('graph_record_shape')
        if row['id'] in ids:
            raise ValueError('graph_record_duplicate')
        ids.add(row['id'])

    for row in value['nodes']:
        register(row, {'id', 'type', 'scope', 'value'})
        if not all(_identifier(row[k]) for k in ('type', 'scope')):
            raise ValueError('graph_node_reference')
        nodes.add(row['id'])
    for row in value['sources']:
        register(row, {'id', 'text', 'sha256'})
        if type(row['text']) is not str or type(row['sha256']) is not str:
            raise ValueError('graph_source_shape')
        try:
            expected = hashlib.sha256(row['text'].encode('utf-8', 'strict')).hexdigest()
        except UnicodeEncodeError:
            raise ValueError('graph_source_encoding') from None
        if expected != row['sha256']:
            raise ValueError('graph_source_hash')
        sources[row['id']] = row['text']
    for row in value['spans']:
        register(row, {'id', 'source', 'start', 'end'})
        if (type(row['source']) is not str or row['source'] not in sources
                or type(row['start']) is not int or type(row['end']) is not int
                or not 0 <= row['start'] < row['end'] <= len(sources[row['source']])):
            raise ValueError('graph_source_span')
    for row in value['edges']:
        register(row, {'id', 'source', 'relation', 'target', 'scope', 'evidence'})
        if not all(_identifier(row[k]) for k in ('source', 'relation', 'target', 'scope')):
            raise ValueError('graph_edge_reference')
        if row['source'] not in nodes or row['target'] not in nodes:
            raise ValueError('graph_edge_endpoint')
        refs = row['evidence']
        if type(refs) is not list or any(not _identifier(ref) for ref in refs):
            raise ValueError('graph_evidence_shape')
        if len(set(refs)) != len(refs):
            raise ValueError('graph_evidence_duplicate')
    # Forward references are legal. Presence is not a proof of truth or an
    # authorization to treat an edge as an accepted assertion.
    for row in value['edges']:
        if any(ref not in ids for ref in row['evidence']):
            raise ValueError('graph_evidence_reference')
    return value


def source_span(frame, span_id):
    """Resolve original Python-codepoint coordinates without normalization."""
    value = validate_frame(frame)
    sources = {row['id']: row['text'] for row in value['sources']}
    for span in value['spans']:
        if span['id'] == span_id:
            return sources[span['source']][span['start']:span['end']]
    raise ValueError('graph_span_missing')


def _canonical(value):
    # Exact JSON types: True must not compare equal to integer 1.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _reason(exc):
    reason = exc.args[0] if exc.args else None
    if type(reason) is str and reason.startswith('graph_') and len(reason) <= 64:
        return reason
    return 'graph_invalid'


def recorded_inputs(frame, *, text, source_id, model):
    """Detach the exact VM inputs for one turn; raise ValueError on bad input."""
    before = validate_frame(frame)
    model = validate_value(model)
    if type(text) is not str or not _identifier(source_id):
        raise ValueError('graph_turn_input')
    text = validate_value(text)
    ids = {row['id'] for field in _FIELDS for row in before[field]}
    if any(identifier in ids for identifier in (source_id, 'span:'+source_id, 'edge:'+source_id)):
        raise ValueError('graph_turn_collision')
    try:
        digest = hashlib.sha256(text.encode('utf-8', 'strict')).hexdigest()
    except UnicodeEncodeError:
        raise ValueError('graph_source_encoding') from None
    source = {'id': source_id, 'text': text, 'sha256': digest}
    return {'frame': before, 'text': text, 'source': source, 'model': model}


def _host_check(inputs, value, keys):
    """Return the detached append-only candidate frame or raise ValueError."""
    before, source = inputs['frame'], inputs['source']
    if type(value) is not dict or value.keys() != keys:
        raise ValueError('graph_result_shape')
    if ((value['answer'] is not None and type(value['answer']) is not str)
            or not _identifier(value['status'])):
        raise ValueError('graph_result_fields')
    after = validate_frame(value['frame'])
    old_sources = {row['id'] for row in before['sources']}
    old_spans = {row['id'] for row in before['spans']}
    for field in _FIELDS:
        if _canonical(after[field][:len(before[field])]) != _canonical(before[field]):
            raise ValueError('graph_append_only')
    if any(row['id'] not in old_sources and _canonical(row) != _canonical(source) for row in after['sources']):
        raise ValueError('graph_source_append')
    if any(row['id'] not in old_spans and row['source'] != source['id'] for row in after['spans']):
        raise ValueError('graph_span_append')
    evidence = value['evidence']
    after_ids = {row['id'] for field in _FIELDS for row in after[field]}
    if (type(evidence) is not list or len(evidence) > MAXIMUM_SCAN_LENGTH
            or any(not _identifier(ref) or ref not in after_ids for ref in evidence)
            or len(set(evidence)) != len(evidence)):
        raise ValueError('graph_result_evidence')
    return after


def execute_frame(program, frame, *, text, source_id, model, budget=4096):
    """Run an explicitly selected graph program over an append-only work frame.

    This isolated caller API has no parser, semantic routing, storage effects
    or automatic program discovery. The caller chooses the program; input
    nodes are inert. Result validity attests references, not semantic truth.
    Active-pack authorization/integration remains with the existing owners.
    """
    used = 0

    def invalid():
        return {'schema': RESULT_SCHEMA, 'status': 'invalid', 'value': None, 'used': used}

    try:
        inputs = recorded_inputs(frame, text=text, source_id=source_id, model=model)
        result = run(program, inputs, budget=budget)
        used = result['used']
        if result['status'] != 'completed':
            return result
        after = _host_check(inputs, result['value'], _LEGACY_KEYS)
        # No mutation is applied here. The returned detached work frame is a
        # candidate value; existing Memory/Overlay owners control persistence.
        return {'schema': RESULT_SCHEMA, 'status': 'completed',
                'value': {**result['value'], 'frame': after}, 'used': used}
    except (ValueError, UnicodeEncodeError):
        return invalid()


def execute_frame_recorded(program, frame, *, text, source_id, model, budget=4096, trace_limit=128):
    """Run once with a replayable record; host validation never rewrites it.

    The completed value must carry exactly frame, answer, status, evidence and
    meaning. Meaning is checked by the caller. A valid host check attests
    append-only references and source pins, not semantic truth.
    """
    def envelope(execution, valid, reason):
        return {'execution': execution, 'host_validation': {'valid': valid, 'reason': reason}}

    try:
        inputs = recorded_inputs(frame, text=text, source_id=source_id, model=model)
    except (ValueError, UnicodeEncodeError) as exc:
        return envelope(None, False, _reason(exc))
    try:
        execution = run_recorded(program, inputs, budget=budget, trace_limit=trace_limit)
    except (ValueError, TypeError):
        return envelope(None, False, 'graph_run_rejected')
    result = execution['result']
    if type(result) is not dict or result.get('status') != 'completed':
        return envelope(execution, False, 'graph_execution_not_completed')
    try:
        _host_check(inputs, result['value'], _RECORDED_KEYS)
    except (ValueError, UnicodeEncodeError) as exc:
        return envelope(execution, False, _reason(exc))
    return envelope(execution, True, 'graph_host_valid')
