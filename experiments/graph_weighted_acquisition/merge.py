"""Merge repeated mentions of one named value into one node, when training shows it.

The v2 union production keeps every mention as its own node. Authored graphs may
instead use one node for a person named twice. Whether equal value text of the
same type means one node is not assumed here: it is counted from training
examples, per node type, and the merge applies only when training showed merged
repeats and never showed two separate nodes with the same text.
"""
import copy

from experiments.graph_example_acquisition import native, v2


def _value_nodes(graph, text):
    """Open value nodes as (node, surface), in text order."""
    anchors = {n['id']: n for n in graph['nodes']}
    found = []
    for s, p, o in graph['edges']:
        if p == 'value' and isinstance(o, dict) and 'copy' in o and o['copy'] == anchors[s].get('anchor'):
            found.append((anchors[s], text[slice(*o['copy'])]))
    return sorted(found, key=lambda item: item[0]['anchor'])


def identity_counts(examples):
    """Per node type: repeats authored as one node vs. as separate nodes."""
    table = {}

    def add(kind, name, origin):
        cell = table.setdefault(kind, {}).setdefault(name, {'n': 0, 'origins': []})
        cell['n'] += 1
        if origin not in cell['origins']:
            cell['origins'].append(origin)

    for ex in examples:
        try:
            nodes = _value_nodes(ex['graph'], ex['text'])
        except (KeyError, TypeError):
            continue
        groups = {}
        for node, surface in nodes:
            groups.setdefault((node['type'], surface), []).append(node)
        for (kind, surface), members in groups.items():
            for _ in members[1:]:
                add(kind, 'separate', ex['id'])
            for _ in range(ex['text'].count(surface) - len(members)):
                add(kind, 'merged', ex['id'])
    return table


def allowed(table, kind):
    row = table.get(kind, {})
    return row.get('merged', {}).get('n', 0) > 0 and row.get('separate', {}).get('n', 0) == 0


def merge_graph(graph, text, table, force=False):
    """One node per repeated value text of a mergeable type. Evidence spans are kept."""
    groups = {}
    for node, surface in _value_nodes(graph, text):
        if force or allowed(table, node['type']):
            groups.setdefault((node['type'], surface), []).append(node['id'])
    rename = {later: ids[0] for ids in groups.values() for later in ids[1:]}
    if not rename:
        return None
    out = copy.deepcopy(graph)
    edges, spans = [], []
    for edge, evidence in zip(out['edges'], out['edge_spans']):
        s, p, o = edge
        if s in rename and p == 'value':
            continue
        edges.append([rename.get(s, s), p, rename.get(o, o) if isinstance(o, str) else o])
        spans.append(evidence)
    out['nodes'] = [n for n in out['nodes'] if n['id'] not in rename]
    out['edges'], out['edge_spans'] = edges, spans
    out['project'] = list(dict.fromkeys(rename.get(i, i) for i in out['project']))
    native._check(out, text)
    return out


def expand(text, result, weights, force=False):
    """Replace each reading by its merged form where the learned gate allows it."""
    table = weights.get('identity', {})
    graphs, changed = {}, 0
    for graph in result['graphs']:
        try:
            merged = merge_graph(graph, text, table, force)
        except ValueError:
            merged = None
        changed += merged is not None
        final = merged or graph
        graphs[v2.canonical(final)] = final
    out = dict(result)
    out['merge'] = {'applied': changed, 'forced': force}
    if changed:
        out['graphs'] = list(graphs.values())
        if result['status'] in ('ambiguous', 'complete'):
            out['status'] = 'complete' if len(graphs) == 1 else 'ambiguous'
    return out
