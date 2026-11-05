'''Offline, bounded syntactic-role candidate discovery over seed anchors (inactive).

Learns marker and order DATA from raw sentences, anchored on explicit seed role
markers, then compiles that data into a separately approved Graph VM template.
Limitations: seed markers and slot semantics are assumptions, not induced
meaning; support counts do not prove synonymy or truth; no facts are admitted
from the corpus; the learner never executes queries or parses evaluation text.
'''
import hashlib
import json

from marco.reasoning.graph_vm import validate_program, validate_value

SCHEMA = 'marco-graph-compositional-induction-v1'
MAX_SENTENCES = 64
MAX_CODEPOINTS = 128
MAX_UTF8_BYTES = 512
MAX_LABELS = 4
MAX_PATTERNS = 12
MAX_ROLE_MARKERS = 2
MAX_MARKER_CHARS = 16
MAX_WORK = 1000000
ORDER_SEED = (0, 1, 2)
ORDER_REVERSED = (1, 0, 2)

_PATTERN_KEYS = frozenset(('id', 'kind', 'polarity', 'relation', 'prefix', 'between', 'suffix'))
_SPECS = (
    ('composition_subject_markers', 'subject_markers', []),
    ('composition_object_markers', 'object_markers', []),
    ('composition_orders', 'orders', []),
    ('composition_seed_object_marker', 'seed_object_marker', ''),
)
_LIMITATIONS = (
    'seed role markers and slot semantics are caller assumptions, not induced meaning',
    'new markers are lexical role candidates supported by counts, not proof of synonymy or truth',
    'no facts are admitted from the corpus and no semantics are discovered',
    'sentences with ambiguous or conflicting decompositions are refused, not guessed',
    'bounded to the stated sentence, length, marker, pattern and work limits',
)


def _canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _text(value, name, empty=False):
    if type(value) is not str or (not value and not empty):
        raise ValueError('%s must be a valid string' % name)
    if len(value) > MAX_CODEPOINTS:
        raise ValueError('%s too long' % name)
    try:
        raw = value.encode('utf-8', 'strict')
    except UnicodeError:
        raise ValueError('%s has malformed unicode' % name) from None
    if len(raw) > MAX_UTF8_BYTES:
        raise ValueError('%s too large in utf-8' % name)
    return value


def _seed(seed_model):
    model = validate_value(seed_model)
    if type(model) is not dict or set(model) != {'labels', 'labels_by_id', 'patterns'}:
        raise ValueError('seed model shape')
    raw_labels = model['labels']
    if type(raw_labels) is not list or not 1 <= len(raw_labels) <= MAX_LABELS:
        raise ValueError('seed labels count')
    labels, mapping, texts = [], {}, set()
    for row in raw_labels:
        if type(row) is not dict or set(row) != {'id', 'text'}:
            raise ValueError('seed label shape')
        lid = _text(row['id'], 'label id')
        ltx = _text(row['text'], 'label text')
        if lid in mapping or ltx in texts:
            raise ValueError('duplicate seed label')
        mapping[lid] = ltx
        texts.add(ltx)
        labels.append((lid, ltx))
    if type(model['labels_by_id']) is not dict or model['labels_by_id'] != mapping:
        raise ValueError('labels_by_id is not the canonical label mapping')
    raw_patterns = model['patterns']
    if type(raw_patterns) is not list or not 2 <= len(raw_patterns) <= MAX_PATTERNS:
        raise ValueError('seed pattern count')
    patterns, ids = [], set()
    for row in raw_patterns:
        if type(row) is not dict or set(row) != _PATTERN_KEYS:
            raise ValueError('seed pattern shape')
        pid = _text(row['id'], 'pattern id')
        kind, polarity = row['kind'], row['polarity']
        if type(kind) is not str or kind not in ('fact', 'query'):
            raise ValueError('seed pattern kind')
        if type(polarity) is not bool or (kind == 'query' and polarity is not True):
            raise ValueError('seed pattern polarity')
        if pid in ids:
            raise ValueError('duplicate pattern id')
        ids.add(pid)
        patterns.append({
            'id': pid, 'kind': kind, 'polarity': polarity,
            'relation': _text(row['relation'], 'relation'),
            'prefix': _text(row['prefix'], 'prefix', True),
            'between': _text(row['between'], 'between'),
            'suffix': _text(row['suffix'], 'suffix'),
        })
    betweens = {p['between'] for p in patterns}
    if len(betweens) != 1:
        raise ValueError('patterns must agree on one initial subject marker')
    subj = next(iter(betweens))
    if len({p['relation'] for p in patterns}) < 2:
        raise ValueError('object marker needs at least two distinct relations')
    obj = patterns[0]['suffix']
    for p in patterns[1:]:
        s, n = p['suffix'], 0
        while n < len(obj) and n < len(s) and obj[n] == s[n]:
            n += 1
        obj = obj[:n]
    if not obj or not 1 <= len(subj) <= MAX_MARKER_CHARS or len(obj) > MAX_MARKER_CHARS:
        raise ValueError('seed markers must be nonempty and bounded')
    if subj == obj:
        raise ValueError('seed subject and object markers must be disjoint')
    pairs = set()
    for p in patterns:
        if len(p['suffix']) <= len(obj):
            raise ValueError('pattern suffix has no predicate remainder')
        p['predicate'] = p['suffix'][len(obj):]
        pairs.add((p['prefix'], p['predicate']))
    if len(pairs) != len(patterns):
        raise ValueError('duplicate pattern surface')
    patterns.sort(key=lambda p: p['id'])
    return {'hash': _sha(_canon(model).encode('utf-8')), 'labels': labels,
            'patterns': patterns, 'subj': subj, 'obj': obj}


def _sentences(sentences):
    if type(sentences) is not list or len(sentences) > MAX_SENTENCES:
        raise ValueError('sentences must be a list of at most %d' % MAX_SENTENCES)
    unique = {}
    for item in sentences:
        _text(item, 'sentence')
        if item not in unique:
            unique[item] = _sha(item.encode('utf-8'))
    return sorted(unique.items(), key=lambda kv: (kv[1], kv[0]))


def _role(marker, subs, objs):
    if marker in subs:
        return 0
    if marker in objs:
        return 1
    return None


def learn(seed_model, sentences, *, min_support=2):
    if type(min_support) is not int or not 2 <= min_support <= 64:
        raise ValueError('min_support must be an int in 2..64')
    seed = _seed(seed_model)
    rows = _sentences(sentences)
    work = [0]

    def tick():
        work[0] += 1
        if work[0] > MAX_WORK:
            raise ValueError('work limit exceeded')

    labels, pats = seed['labels'], seed['patterns']
    obs, rejected = [], {}
    for text, digest in rows:
        sid = 'source:' + digest
        found = []
        for pi, pat in enumerate(pats):
            tick()
            start, pred = len(pat['prefix']), pat['predicate']
            end = len(text) - len(pred)
            if end < start or not text.startswith(pat['prefix']) or not text.endswith(pred):
                continue
            middle = text[start:end]
            for ai, (_, atext) in enumerate(labels):
                if not middle.startswith(atext):
                    continue
                off = len(atext)
                for bi, (_, btext) in enumerate(labels):
                    if bi == ai:
                        continue
                    pos = middle.find(btext, off + 1)
                    while pos != -1:
                        tick()
                        ma, mb = middle[off:pos], middle[pos + len(btext):]
                        if (ma and mb and len(ma) <= MAX_MARKER_CHARS
                                and len(mb) <= MAX_MARKER_CHARS
                                and not any(t in ma or t in mb for _, t in labels)):
                            a_end = start + off
                            b_start = start + pos
                            b_end = b_start + len(btext)
                            found.append({
                                'sid': sid, 'pi': pi, 'ai': ai, 'bi': bi, 'ma': ma, 'mb': mb,
                                'spans': {'prefix': [0, start], 'a': [start, a_end],
                                          'ma': [a_end, b_start], 'b': [b_start, b_end],
                                          'mb': [b_end, end], 'pred': [end, len(text)]},
                            })
                        pos = middle.find(btext, pos + 1)
        if len(found) > 1:
            rejected[sid] = 'ambiguous_decomposition'
        elif found:
            obs.append(found[0])

    init_s, init_o = [seed['subj']], [seed['obj']]
    cand, marks, involved = {}, {}, []
    for o in obs:
        tick()
        ra, rb = _role(o['ma'], init_s, init_o), _role(o['mb'], init_s, init_o)
        if (ra is None) == (rb is None):
            continue
        role_a = ra if ra is not None else 1 - rb
        unknown, urole = (o['ma'], role_a) if ra is None else (o['mb'], 1 - role_a)
        a_id, b_id = labels[o['ai']][0], labels[o['bi']][0]
        pair = (a_id, b_id) if role_a == 0 else (b_id, a_id)
        entry = cand.setdefault((unknown, urole), (set(), set()))
        entry[0].add(o['sid'])
        entry[1].add(pair)
        marks.setdefault(unknown, set()).add(urole)
        involved.append((o['sid'], unknown))
    conflicted = {m for m, roles in marks.items() if len(roles) > 1}
    for sid, marker in involved:
        if marker in conflicted:
            rejected.setdefault(sid, 'marker_role_conflict')
    new = [[], []]
    for (marker, role), (srcs, pairs) in cand.items():
        if marker in conflicted:
            continue
        if len(srcs) >= min_support and len(pairs) >= min_support:
            new[role].append(marker)
    final_s = init_s + sorted(new[0])
    final_o = init_o + sorted(new[1])
    if len(final_s) > MAX_ROLE_MARKERS or len(final_o) > MAX_ROLE_MARKERS:
        raise ValueError('too many supported role markers')
    if set(final_s) & set(final_o):
        raise ValueError('role markers must be disjoint')

    evidence, order_support = [], {}
    for o in obs:
        tick()
        if o['sid'] in rejected:
            continue
        ra, rb = _role(o['ma'], final_s, final_o), _role(o['mb'], final_s, final_o)
        if ra is None or rb is None:
            continue
        if ra == rb:
            rejected[o['sid']] = 'role_conflict'
            continue
        sp = o['spans']
        a_part = {'label': labels[o['ai']][0], 'span': sp['a'],
                  'marker': o['ma'], 'marker_span': sp['ma']}
        b_part = {'label': labels[o['bi']][0], 'span': sp['b'],
                  'marker': o['mb'], 'marker_span': sp['mb']}
        subject, obj = (a_part, b_part) if ra == 0 else (b_part, a_part)
        order = ORDER_SEED if ra == 0 else ORDER_REVERSED
        entry = order_support.setdefault(order, (set(), set()))
        entry[0].add(o['sid'])
        entry[1].add((subject['label'], obj['label']))
        evidence.append({'source': o['sid'], 'pattern': pats[o['pi']]['id'],
                         'order': list(order), 'subject': subject, 'object': obj,
                         'prefix_span': sp['prefix'], 'predicate_span': sp['pred']})
    evidence.sort(key=lambda e: e['source'])
    orders = [list(ORDER_SEED)]
    rev = order_support.get(ORDER_REVERSED)
    if rev and len(rev[0]) >= min_support and len(rev[1]) >= min_support:
        orders.append(list(ORDER_REVERSED))
    artifact = {
        'schema': SCHEMA,
        'active': False,
        'semantics': None,
        'min_support': min_support,
        'seed_sha256': seed['hash'],
        'sources': [{'id': 'source:' + d, 'text': t, 'sha256': d} for t, d in rows],
        'seed': {
            'subject_markers': [seed['subj']],
            'object_marker': seed['obj'],
            'orders': [list(ORDER_SEED)],
            'predicates': [{'pattern': p['id'], 'prefix': p['prefix'],
                            'predicate': p['predicate'], 'kind': p['kind'],
                            'relation': p['relation'], 'polarity': p['polarity']}
                           for p in pats],
        },
        'learned': {'subject_markers': final_s, 'object_markers': final_o, 'orders': orders},
        'evidence': evidence,
        'rejected': [{'source': s, 'reason': r} for s, r in sorted(rejected.items())],
        'limitations': list(_LIMITATIONS),
    }
    return validate_value(artifact)


def compile_program(template, artifact, seed_model, sentences, *, expected_template_sha256):
    if type(expected_template_sha256) is not str:
        raise ValueError('expected_template_sha256 must be a str')
    supplied = validate_value(template)
    if _sha(_canon(supplied).encode('utf-8')) != expected_template_sha256:
        raise ValueError('template hash mismatch')
    program = validate_program(template)
    given = validate_value(artifact)
    if type(given) is not dict or type(given.get('min_support')) is not int:
        raise ValueError('artifact shape')
    fresh = learn(seed_model, sentences, min_support=given['min_support'])
    if _canon(fresh) != _canon(given):
        raise ValueError('artifact does not match relearned canonical artifact')
    payloads = {
        'subject_markers': fresh['learned']['subject_markers'],
        'object_markers': fresh['learned']['object_markers'],
        'orders': fresh['learned']['orders'],
        'seed_object_marker': fresh['seed']['object_marker'],
    }
    nodes = program['nodes']
    for node_id, name, default in _SPECS:
        hits = [n for n in nodes if n['id'] == node_id]
        if len(hits) != 1:
            raise ValueError('template node missing or duplicated: ' + node_id)
        node = hits[0]
        if node['op'] != 'set' or node['name'] != name:
            raise ValueError('template node shape: ' + node_id)
        if len([n for n in nodes if n['op'] == 'set' and n['name'] == name]) != 1:
            raise ValueError('template name not unique: ' + name)
        value = node['value']
        if type(value) is not dict or list(value) != ['literal']:
            raise ValueError('template value must be a literal')
        if _canon(value['literal']) != _canon(default):
            raise ValueError('template default must be inert')
        node['value'] = {'literal': json.loads(_canon(payloads[name]))}
    return validate_program(program)
