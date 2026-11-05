'''Project offline distributional candidates onto an existing GraphVM seed.

Only appends nodes and model labels; relations, facts, edges, sources and spans
are untouched. Anchors are caller-supplied graph data. New labels are candidate
distributional role extensions that assume a trusted positive corpus and the
seed slot semantics; they are not proven denotations. Structural anchors cannot
detect clauses or quotes swallowed into a filler, and the generic program does
not enforce role type at query time.
'''
import hashlib
import json

from marco.reasoning.graph_contract import validate_frame
from marco.reasoning.graph_vm import MAXIMUM_SCAN_LENGTH, validate_value


PROPOSAL_SCHEMA = 'marco-surface-candidates-v1'
RECEIPT_SCHEMA = 'marco-surface-projection-v1'
GROUNDING = 'seed-slot-assumption-not-proof'
MAX_CANDIDATES = 64
MAX_SOURCES = 256
MAX_ANCHORS = 256
MAX_ITEMS = 256
MIN_SUPPORT = 3

_PROPOSAL_KEYS = frozenset(('schema', 'active', 'semantics', 'sources', 'candidates'))
_SOURCE_KEYS = frozenset(('id', 'text', 'sha256'))
_CANDIDATE_KEYS = frozenset(('id', 'prefix', 'suffix', 'fillers', 'evidence'))
_EVIDENCE_KEYS = frozenset(('source', 'start', 'end'))
_ANCHOR_KEYS = frozenset(('id', 'prefix', 'suffix', 'type', 'scope'))
_LIMITATIONS = (
    'new labels are distributional role extensions, not proven denotations',
    'structural anchors cannot detect clauses or quotes swallowed into a filler',
    'the generic program does not enforce role type at query time',
)


def _digest(parts):
    raw = json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _identifier(value):
    return type(value) is str and bool(value) and len(value) <= 256


def _proposal(proposal):
    value = validate_value(proposal)
    if type(value) is not dict or value.keys() != _PROPOSAL_KEYS:
        raise ValueError('proposal_shape')
    if value['schema'] != PROPOSAL_SCHEMA or value['active'] is not False or value['semantics'] is not None:
        raise ValueError('proposal_header')
    sources, candidates = value['sources'], value['candidates']
    if type(sources) is not list or len(sources) > MAX_SOURCES:
        raise ValueError('proposal_sources')
    if type(candidates) is not list or len(candidates) > MAX_CANDIDATES:
        raise ValueError('proposal_candidates')
    texts = {}
    for row in sources:
        if type(row) is not dict or row.keys() != _SOURCE_KEYS or any(type(v) is not str for v in row.values()):
            raise ValueError('source_shape')
        try:
            digest = hashlib.sha256(row['text'].encode('utf-8', 'strict')).hexdigest()
        except UnicodeEncodeError:
            raise ValueError('source_encoding') from None
        if digest != row['sha256'] or row['id'] != 'source:' + digest:
            raise ValueError('source_hash')
        if row['id'] in texts:
            raise ValueError('source_duplicate')
        texts[row['id']] = row['text']
    seen = set()
    for cand in candidates:
        if type(cand) is not dict or cand.keys() != _CANDIDATE_KEYS:
            raise ValueError('candidate_shape')
        prefix, suffix = cand['prefix'], cand['suffix']
        if type(prefix) is not str or type(suffix) is not str or type(cand['id']) is not str:
            raise ValueError('candidate_shape')
        if cand['id'] != 'candidate:' + _digest([prefix, suffix]):
            raise ValueError('candidate_id')
        if cand['id'] in seen:
            raise ValueError('candidate_duplicate')
        seen.add(cand['id'])
        fillers, evidence = cand['fillers'], cand['evidence']
        if type(fillers) is not list or not MIN_SUPPORT <= len(fillers) <= MAX_ITEMS:
            raise ValueError('candidate_fillers')
        if any(type(f) is not str or not f for f in fillers) or len(set(fillers)) != len(fillers):
            raise ValueError('candidate_fillers')
        if type(evidence) is not list or len(evidence) > MAX_ITEMS:
            raise ValueError('candidate_evidence')
        slices, used = set(), set()
        for ev in evidence:
            if type(ev) is not dict or ev.keys() != _EVIDENCE_KEYS:
                raise ValueError('evidence_shape')
            src, start, end = ev['source'], ev['start'], ev['end']
            if type(src) is not str or src not in texts or type(start) is not int or type(end) is not int:
                raise ValueError('evidence_shape')
            text = texts[src]
            if not 0 <= start < end <= len(text):
                raise ValueError('evidence_span')
            if (start != len(prefix) or end != len(text) - len(suffix)
                    or text[:start] != prefix or text[end:] != suffix):
                raise ValueError('evidence_reconstruction')
            if src in used:
                raise ValueError('evidence_source_duplicate')
            used.add(src)
            slices.add(text[start:end])
        if slices != set(fillers):
            raise ValueError('evidence_filler_mismatch')
    return value, texts


def _anchors(anchors):
    value = validate_value(anchors)
    if type(value) is not list or len(value) > MAX_ANCHORS:
        raise ValueError('anchor_list')
    seen = set()
    for row in value:
        if type(row) is not dict or row.keys() != _ANCHOR_KEYS:
            raise ValueError('anchor_shape')
        if not _identifier(row['id']) or type(row['prefix']) is not str or type(row['suffix']) is not str:
            raise ValueError('anchor_shape')
        if not _identifier(row['type']) or not _identifier(row['scope']):
            raise ValueError('anchor_shape')
        if row['id'] in seen:
            raise ValueError('anchor_duplicate')
        seen.add(row['id'])
    return value


def project(seed, proposal, anchors):
    '''Return {'bootstrap', 'receipt'}; raise ValueError on any invalid input.'''
    seed = validate_value(seed)
    if type(seed) is not dict or seed.keys() != {'frame', 'model'}:
        raise ValueError('seed_shape')
    frame = validate_frame(seed['frame'])
    model = seed['model']
    if type(model) is not dict or type(model.get('labels')) is not list:
        raise ValueError('seed_model')
    labels = model['labels']
    if len(labels) > MAXIMUM_SCAN_LENGTH:
        raise ValueError('seed_labels')
    nodes = {row['id']: row for row in frame['nodes']}
    all_ids = {row['id'] for field in ('nodes', 'edges', 'sources', 'spans') for row in frame[field]}
    label_ids, by_text = set(), {}
    for label in labels:
        if type(label) is not dict or label.keys() != {'id', 'text'}:
            raise ValueError('seed_label')
        if type(label['id']) is not str or type(label['text']) is not str:
            raise ValueError('seed_label')
        if label['id'] in label_ids or label['id'] not in nodes or nodes[label['id']]['value'] != label['text']:
            raise ValueError('seed_label')
        label_ids.add(label['id'])
        by_text.setdefault(label['text'], []).append(label['id'])

    proposal, texts = _proposal(proposal)
    anchors = _anchors(anchors)
    by_context = {}
    for anchor in anchors:
        by_context.setdefault((anchor['prefix'], anchor['suffix']), []).append(anchor)

    held, accepted, items = [], [], []
    for cand in proposal['candidates']:
        cid = cand['id']
        if cand['prefix'] == '' and cand['suffix'] == '':
            held.append({'candidateID': cid, 'reason': 'unconstrained_context'})
            continue
        matches = by_context.get((cand['prefix'], cand['suffix']), [])
        if not matches:
            held.append({'candidateID': cid, 'reason': 'ungrounded_context'})
            continue
        if len({(a['type'], a['scope']) for a in matches}) > 1:
            held.append({'candidateID': cid, 'reason': 'ambiguous_anchor'})
            continue
        anchor = min(matches, key=lambda a: a['id'])
        for filler in cand['fillers']:
            refs = [{'source': ev['source'], 'start': ev['start'], 'end': ev['end']}
                    for ev in cand['evidence']
                    if texts[ev['source']][ev['start']:ev['end']] == filler]
            items.append({'candidate': cid, 'filler': filler, 'anchor': anchor, 'evidence': refs})

    by_filler = {}
    for item in items:
        by_filler.setdefault(item['filler'], []).append(item)

    def hold(group, reason):
        for it in group:
            held.append({'candidateID': it['candidate'], 'filler': it['filler'], 'reason': reason})

    def accept(it, node_id, is_new):
        accepted.append({'candidateID': it['candidate'], 'filler': it['filler'],
                         'anchorID': it['anchor']['id'], 'nodeID': node_id,
                         'evidence': it['evidence'], 'newNode': is_new})

    new_nodes, new_labels = {}, {}
    for filler in sorted(by_filler):
        group = by_filler[filler]
        existing = by_text.get(filler, [])
        if len(existing) > 1:
            hold(group, 'ambiguous_existing_label')
            continue
        if existing:
            node = nodes[existing[0]]
            for it in group:
                if (node['type'], node['scope']) == (it['anchor']['type'], it['anchor']['scope']):
                    accept(it, node['id'], False)
                else:
                    hold([it], 'existing_conflict')
            continue
        if len({(it['anchor']['type'], it['anchor']['scope']) for it in group}) > 1:
            hold(group, 'cross_candidate_conflict')
            continue
        kind, scope = group[0]['anchor']['type'], group[0]['anchor']['scope']
        node_id = 'node:surface:' + _digest([kind, scope, filler])
        record = {'id': node_id, 'type': kind, 'scope': scope, 'value': filler}
        if node_id in label_ids:
            raise ValueError('node_id_collision')
        if node_id in all_ids:
            if nodes.get(node_id) != record:
                raise ValueError('node_id_collision')
            is_new = False
        else:
            new_nodes[node_id] = record
            is_new = True
        new_labels[node_id] = filler
        for it in group:
            accept(it, node_id, is_new)

    if len(labels) + len(new_labels) > MAXIMUM_SCAN_LENGTH:
        raise ValueError('projection_limit')
    new_frame = {**frame, 'nodes': frame['nodes'] + [new_nodes[k] for k in sorted(new_nodes)]}
    new_model = {**model, 'labels': labels + [{'id': k, 'text': new_labels[k]} for k in sorted(new_labels)]}
    bootstrap = validate_value({'frame': validate_frame(new_frame), 'model': new_model})

    accepted.sort(key=lambda r: (r['candidateID'], r['filler']))
    held.sort(key=lambda r: (r['candidateID'], r.get('filler', ''), r['reason']))
    receipt = validate_value({
        'schema': RECEIPT_SCHEMA,
        'accepted': accepted,
        'held': held,
        'sources': proposal['sources'],
        'semantic_grounding': GROUNDING,
        'limitations': list(_LIMITATIONS),
    })
    return {'bootstrap': bootstrap, 'receipt': receipt}
