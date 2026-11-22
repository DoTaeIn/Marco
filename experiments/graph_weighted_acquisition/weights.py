"""Count-based weights for ranking competing readings.

Built offline from teacher examples and stored as integer counts with their
origin example ids. Nothing here is language-specific: every cue is a character
string observed between or under authored anchors, every label is read from the
authored graph. The weights never create a reading. They only order the
readings the unchanged v2 parser already produced, and they resolve an
ambiguous parse only when the top reading is ahead by the declared ratio and
every one of its terms was observed in training.
"""
import hashlib
import json
import math

from experiments.graph_example_acquisition import v2

SCHEMA = 'graph-count-weights-v1'
TABLES = ('left', 'right', 'surface')
DEFAULT_POLICY = {'alpha': [1, 2], 'margin_ratio': 3, 'require_support': True}


def key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _segments(graph, text):
    """Mentions in text order and the literal text between them.

    A mention is a node anchor, or a further exact occurrence of an open value's
    text outside every anchor: one node for a person named twice has one anchor,
    and its second mention must not be read as plain connecting text.
    """
    anchored = [n for n in graph['nodes'] if 'anchor' in n]
    if not anchored:
        raise ValueError('no anchored node')
    opened = _open_ids(graph)
    mentions = [(tuple(n['anchor']), n, True) for n in anchored]
    taken = sorted(m[0] for m in mentions)
    for node in anchored:
        if node['id'] not in opened:
            continue
        surface, pos = text[slice(*node['anchor'])], 0
        while True:
            pos = text.find(surface, pos)
            if pos < 0:
                break
            span = (pos, pos + len(surface))
            if all(span[1] <= a or span[0] >= b for a, b in taken):
                mentions.append((span, node, False))
                taken.append(span)
            pos += len(surface)
    mentions.sort(key=lambda m: m[0])
    if any(a[0][1] > b[0][0] for a, b in zip(mentions, mentions[1:])):
        raise ValueError('overlapping anchors unsupported')
    gaps, last = [], 0
    for (start, end), _, _ in mentions:
        gaps.append(text[last:start])
        last = end
    gaps.append(text[last:])
    return mentions, gaps


def _open_ids(graph):
    """Nodes whose whole anchor is an input copy: their text is a free value."""
    anchors = {n['id']: n.get('anchor') for n in graph['nodes']}
    return {s for s, p, o in graph['edges']
            if p == 'value' and isinstance(o, dict) and 'copy' in o and o['copy'] == anchors.get(s)}


def _label(graph, node, span=None):
    """What the graph says about one mention: type, incoming roles, literal attributes.

    With `span`, only roles whose authored evidence touches that mention count, so
    each mention of a shared node carries the roles it grounds.
    """
    roles = sorted(p for (s, p, o), evidence in zip(graph['edges'], graph['edge_spans'])
                   if o == node['id'] and (span is None or list(span) in evidence))
    literals = sorted([p, o['literal']] for s, p, o in graph['edges']
                      if s == node['id'] and isinstance(o, dict) and 'literal' in o)
    return key({'type': node['type'], 'roles': roles, 'literals': literals,
                'project': node['id'] in graph['project']})


def features(graph, text):
    """Decompose one reading into countable pieces.

    terms   (table, cue, label): a node label next to a gap, or under a closed surface.
    used    cue strings the reading treats as structure.
    values  free value texts, which may have swallowed a cue.
    """
    mentions, gaps = _segments(graph, text)
    opened = _open_ids(graph)
    repeated = {node['id'] for _, node, first in mentions if not first}
    terms, used, values = [], [], []
    for i, (span, node, _) in enumerate(mentions):
        label = _label(graph, node, span if node['id'] in repeated else None)
        terms.append(('left', gaps[i], label))
        terms.append(('right', gaps[i + 1], label))
        surface = text[slice(*span)]
        if node['id'] in opened:
            values.append(surface)
        else:
            terms.append(('surface', surface, label))
            if surface.strip():
                used.append(surface.strip())
    used.extend(g.strip() for g in gaps if g.strip())
    return {'terms': terms, 'used': used, 'values': values}


def _cell(row, name, origin):
    cell = row.setdefault(name, {'n': 0, 'origins': []})
    cell['n'] += 1
    if origin not in cell['origins']:
        cell['origins'].append(origin)


def build(examples, policy=None):
    """Count pieces over training examples. Integers and provenance only."""
    tables = {t: {} for t in TABLES}
    cues, labels, skipped, parts = {}, set(), [], []
    for ex in examples:
        try:
            parts.append((ex['id'], features(ex['graph'], ex['text'])))
        except (ValueError, KeyError, TypeError) as error:
            skipped.append({'example': ex.get('id'), 'reason': str(error)})
    for origin, f in parts:
        for table, cue, label in f['terms']:
            _cell(tables[table].setdefault(cue, {}), label, origin)
            labels.add(label)
        for cue in f['used']:
            _cell(cues.setdefault(cue, {}), 'as_cue', origin)
    for origin, f in parts:
        for value in f['values']:
            for cue in cues:
                if cue in value:
                    _cell(cues[cue], 'inside_value', origin)
    source = hashlib.sha256(key(sorted([ex.get('id'), ex.get('text')] for ex in examples)).encode()).hexdigest()
    return {'schema': SCHEMA, 'policy': dict(policy or DEFAULT_POLICY), 'examples': len(parts),
            'source_sha256': source, 'label_count': len(labels), 'tables': tables, 'cues': cues,
            'identity': _identity(examples), 'skipped': skipped}


def _identity(examples):
    from . import merge
    return merge.identity_counts(examples)


def _n(row, name):
    return row.get(name, {}).get('n', 0)


def score(graph, text, weights):
    """Sum of smoothed log ratios of integer counts. Higher is better supported."""
    num, den = weights['policy']['alpha']
    alpha = num / den
    kinds = weights['label_count'] + 1
    f = features(graph, text)
    total, supported, terms = 0.0, True, []
    for table, cue, label in f['terms']:
        row = weights['tables'][table].get(cue, {})
        seen = _n(row, label)
        value = math.log((seen + alpha) / (sum(c['n'] for c in row.values()) + alpha * kinds))
        supported &= seen > 0
        total += value
        terms.append({'kind': table, 'cue': cue, 'count': seen, 'log': value})
    cues = weights['cues']
    for cue in f['used']:
        row = cues.get(cue, {})
        a, b = _n(row, 'as_cue'), _n(row, 'inside_value')
        value = math.log((a + alpha) / (a + b + 2 * alpha))
        total += value
        terms.append({'kind': 'cue_used', 'cue': cue, 'count': a, 'log': value})
    for text_value in f['values']:
        for cue, row in cues.items():
            if cue in text_value:
                a, b = _n(row, 'as_cue'), _n(row, 'inside_value')
                value = math.log((b + alpha) / (a + b + 2 * alpha))
                # A known cue never seen inside a value is an unobserved term too.
                supported &= b > 0
                total += value
                terms.append({'kind': 'cue_inside_value', 'cue': cue, 'count': b, 'log': value})
    return {'score': total, 'supported': supported, 'terms': terms}


def rank(text, result, weights):
    """Resolve an ambiguous v2 parse by count evidence, or leave it ambiguous.

    Only status 'ambiguous' is touched. Unresolved, held and already complete
    parses pass through unchanged, so weights cannot add a reading or an answer.
    """
    out = dict(result)
    if weights.get('schema') != SCHEMA:
        raise ValueError('unsupported weights schema')
    if result['status'] != 'ambiguous':
        out['weighted'] = {'applied': False, 'reason': 'status is ' + result['status']}
        return out
    scored = []
    for graph in result['graphs']:
        try:
            scored.append((score(graph, text, weights), v2.canonical(graph), graph))
        except (ValueError, KeyError, TypeError) as error:
            out['weighted'] = {'applied': False, 'reason': 'unscorable reading: ' + str(error)}
            return out
    scored.sort(key=lambda item: (-item[0]['score'], item[1]))
    margin = scored[0][0]['score'] - scored[1][0]['score']
    policy = weights['policy']
    needed = math.log(policy['margin_ratio'])
    ranking = [{'graph_key': k, 'score': s['score'], 'supported': s['supported']} for s, k, _ in scored]
    report = {'applied': False, 'margin': margin, 'required_margin': needed, 'ranking': ranking,
              'top_terms': scored[0][0]['terms']}
    if margin < needed:
        report['reason'] = 'margin below required ratio'
    elif policy.get('require_support', True) and not scored[0][0]['supported']:
        report['reason'] = 'top reading has an unobserved term'
    else:
        report['applied'] = True
        out['graphs'] = [scored[0][2]]
        out['status'] = 'complete'
    out['weighted'] = report
    return out


def parse(text, grammar, weights, force_merge=False):
    from . import merge
    return rank(text, merge.expand(text, v2.parse(text, grammar), weights, force_merge), weights)
