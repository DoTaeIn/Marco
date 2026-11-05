import hashlib
import json

from marco.reasoning.graph_contract import validate_frame
from marco.reasoning.graph_vm import validate_value

PROPOSAL_SCHEMA = 'marco-surface-candidates-v1'
SHARED_SCHEMA = 'marco-shared-surface-v1'
MAXIMUM_SOURCES = 256
MAXIMUM_CANDIDATES = 64
MAXIMUM_EVIDENCE = 256
MAXIMUM_FILLERS = 256
MAXIMUM_LABELS = 256

_PROPOSAL_KEYS = frozenset(('schema', 'active', 'semantics', 'sources', 'candidates'))
_SHARED_KEYS = frozenset(('schema', 'active', 'semantics', 'sources', 'strings', 'slots', 'candidates'))
_SOURCE_KEYS = frozenset(('id', 'text', 'sha256'))
_CANDIDATE_KEYS = frozenset(('id', 'prefix', 'suffix', 'fillers', 'evidence'))
_EVIDENCE_KEYS = frozenset(('source', 'start', 'end'))
_LABEL_KEYS = frozenset(('id', 'text'))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _digest(text):
    try:
        return hashlib.sha256(text.encode('utf-8', 'strict')).hexdigest()
    except UnicodeEncodeError:
        raise ValueError('surface_encoding') from None


def _header(value, keys, schema):
    if type(value) is not dict or value.keys() != keys:
        raise ValueError('surface_shape')
    if value['schema'] != schema or value['active'] is not False or value['semantics'] is not None:
        raise ValueError('surface_header')


def _check_proposal(value):
    _header(value, _PROPOSAL_KEYS, PROPOSAL_SCHEMA)
    rows = value['sources']
    if type(rows) is not list or len(rows) > MAXIMUM_SOURCES:
        raise ValueError('surface_sources')
    sources = {}
    for row in rows:
        if type(row) is not dict or row.keys() != _SOURCE_KEYS:
            raise ValueError('surface_source_shape')
        if any(type(row[key]) is not str for key in _SOURCE_KEYS):
            raise ValueError('surface_source_shape')
        digest = _digest(row['text'])
        if row['sha256'] != digest or row['id'] != 'source:' + digest:
            raise ValueError('surface_source_hash')
        if row['id'] in sources:
            raise ValueError('surface_source_duplicate')
        sources[row['id']] = row['text']
    candidates = value['candidates']
    if type(candidates) is not list or len(candidates) > MAXIMUM_CANDIDATES:
        raise ValueError('surface_candidates')
    seen_ids = set()
    for cand in candidates:
        if type(cand) is not dict or cand.keys() != _CANDIDATE_KEYS:
            raise ValueError('surface_candidate_shape')
        prefix, suffix = cand['prefix'], cand['suffix']
        if type(prefix) is not str or type(suffix) is not str or (prefix == '' and suffix == ''):
            raise ValueError('surface_context')
        if type(cand['id']) is not str or cand['id'] != 'candidate:' + _digest(_canonical([prefix, suffix])):
            raise ValueError('surface_candidate_hash')
        if cand['id'] in seen_ids:
            raise ValueError('surface_candidate_duplicate')
        seen_ids.add(cand['id'])
        fillers = cand['fillers']
        if type(fillers) is not list or not 3 <= len(fillers) <= MAXIMUM_FILLERS:
            raise ValueError('surface_fillers')
        if any(type(item) is not str or item == '' for item in fillers) or len(set(fillers)) != len(fillers):
            raise ValueError('surface_fillers')
        evidence = cand['evidence']
        if type(evidence) is not list or not 1 <= len(evidence) <= MAXIMUM_EVIDENCE:
            raise ValueError('surface_evidence')
        seen, slices = set(), set()
        for ev in evidence:
            if type(ev) is not dict or ev.keys() != _EVIDENCE_KEYS:
                raise ValueError('surface_evidence_shape')
            source, start, end = ev['source'], ev['start'], ev['end']
            if type(source) is not str or source not in sources:
                raise ValueError('surface_evidence_source')
            if type(start) is not int or type(end) is not int:
                raise ValueError('surface_evidence_span')
            if (source, start, end) in seen:
                raise ValueError('surface_evidence_duplicate')
            seen.add((source, start, end))
            text = sources[source]
            if not (len(text) >= len(prefix) + len(suffix) and text.startswith(prefix)
                    and text.endswith(suffix) and start == len(prefix)
                    and end == len(text) - len(suffix)):
                raise ValueError('surface_evidence_span')
            slices.add(text[start:end])
        if slices != set(fillers):
            raise ValueError('surface_fillers_evidence')


def compact(proposal):
    value = validate_value(proposal)
    _check_proposal(value)
    table, strings = {}, []

    def intern(text):
        if text not in table:
            table[text] = len(strings)
            strings.append(text)
        return table[text]

    slot_index, slots, rows = {}, [], []
    source_index = {row['id']: position for position, row in enumerate(value['sources'])}
    for cand in value['candidates']:
        prefix = intern(cand['prefix'])
        suffix = intern(cand['suffix'])
        key = tuple(intern(item) for item in cand['fillers'])
        if key not in slot_index:
            slot_index[key] = len(slots)
            slots.append(list(key))
        refs = [[source_index[ev['source']], ev['start'], ev['end']] for ev in cand['evidence']]
        rows.append([cand['id'], prefix, suffix, slot_index[key], refs])
    return validate_value({'schema': SHARED_SCHEMA, 'active': False, 'semantics': None,
                           'sources': value['sources'], 'strings': strings,
                           'slots': slots, 'candidates': rows})


def _ref(item, size):
    if type(item) is not int or not 0 <= item < size:
        raise ValueError('surface_reference')
    return item


def expand(shared):
    value = validate_value(shared)
    _header(value, _SHARED_KEYS, SHARED_SCHEMA)
    strings, slots, sources, rows = value['strings'], value['slots'], value['sources'], value['candidates']
    if (type(strings) is not list or type(slots) is not list
            or type(sources) is not list or type(rows) is not list):
        raise ValueError('surface_shape')
    if any(type(item) is not str for item in strings) or len(set(strings)) != len(strings):
        raise ValueError('surface_strings')
    for slot in slots:
        if type(slot) is not list:
            raise ValueError('surface_slot')
        for item in slot:
            _ref(item, len(strings))
    if len({tuple(slot) for slot in slots}) != len(slots):
        raise ValueError('surface_slot_duplicate')
    for source in sources:
        if type(source) is not dict or type(source.get('id')) is not str:
            raise ValueError('surface_source_shape')
    candidates = []
    for row in rows:
        if type(row) is not list or len(row) != 5 or type(row[0]) is not str or type(row[4]) is not list:
            raise ValueError('surface_candidate_shape')
        evidence = []
        for ref in row[4]:
            if type(ref) is not list or len(ref) != 3:
                raise ValueError('surface_evidence_shape')
            evidence.append({'source': sources[_ref(ref[0], len(sources))]['id'],
                             'start': ref[1], 'end': ref[2]})
        candidates.append({'id': row[0],
                           'prefix': strings[_ref(row[1], len(strings))],
                           'suffix': strings[_ref(row[2], len(strings))],
                           'fillers': [strings[index] for index in slots[_ref(row[3], len(slots))]],
                           'evidence': evidence})
    proposal = {'schema': PROPOSAL_SCHEMA, 'active': False, 'semantics': None,
                'sources': sources, 'candidates': candidates}
    _check_proposal(proposal)
    if _canonical(compact(proposal)) != _canonical(value):
        raise ValueError('surface_noncanonical')
    return proposal


def _label_rows(value):
    if type(value) is not dict or 'frame' not in value or 'model' not in value:
        raise ValueError('surface_seed')
    frame = validate_frame(value['frame'])
    model = value['model']
    if type(model) is not dict or type(model.get('labels')) is not list:
        raise ValueError('surface_labels')
    labels = model['labels']
    if len(labels) > MAXIMUM_LABELS:
        raise ValueError('surface_labels')
    values = {node['id']: node['value'] for node in frame['nodes']}
    seen = set()
    for row in labels:
        if type(row) is not dict or row.keys() != _LABEL_KEYS:
            raise ValueError('surface_label_shape')
        label_id, text = row['id'], row['text']
        if type(label_id) is not str or type(text) is not str or text == '':
            raise ValueError('surface_label_shape')
        if label_id in seen:
            raise ValueError('surface_label_duplicate')
        seen.add(label_id)
        if label_id not in values or type(values[label_id]) is not str or values[label_id] != text:
            raise ValueError('surface_label_node')
    return labels


def build_indexes(seed):
    value = validate_value(seed)
    labels = _label_rows(value)
    buckets, by_text, by_id = {}, {}, {}
    for row in labels:
        buckets.setdefault(row['text'][0], []).append({'id': row['id'], 'text': row['text']})
        by_text.setdefault(row['text'], []).append(row['id'])
        by_id.setdefault(row['id'], []).append(row['text'])
    index = {'source_sha256': _digest(_canonical(labels)), 'label_buckets': buckets,
             'labels_by_text': by_text, 'labels_by_id': by_id}
    model = {}
    for key, item in value['model'].items():
        model[key] = index if key == 'index' else item
    if 'index' not in model:
        model['index'] = index
    out = {}
    for key, item in value.items():
        out[key] = model if key == 'model' else item
    return validate_value(out)


def validate_indexes(seed):
    value = validate_value(seed)
    model = value.get('model') if type(value) is dict else None
    if type(model) is not dict or 'index' not in model:
        raise ValueError('surface_index_missing')
    expected = build_indexes(value)['model']['index']
    if _canonical(model['index']) != _canonical(expected):
        raise ValueError('surface_index_stale')
    return value
