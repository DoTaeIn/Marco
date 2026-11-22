import copy
import json

from experiments.graph_example_acquisition import v2
from experiments.graph_weighted_acquisition import driver, weights as W


def sentence(i, a, verb, b, negative=False):
    """'A sent B' or 'A did not send B': one event, two named people, a polarity literal."""
    gap = ' did not ' if negative else ' '
    text = a + gap + verb + ' ' + b
    aa = [0, len(a)]
    ee = [len(a) + len(gap), len(a) + len(gap) + len(verb)]
    bb = [len(text) - len(b), len(text)]
    graph = {'nodes': [{'id': 'a', 'type': 'person', 'anchor': aa}, {'id': 'e', 'type': 'event', 'anchor': ee},
                       {'id': 'b', 'type': 'person', 'anchor': bb}],
             'edges': [['e', 'actor', 'a'], ['e', 'object', 'b'], ['a', 'value', {'copy': aa}],
                       ['b', 'value', {'copy': bb}],
                       ['e', 'polarity', {'literal': 'negative' if negative else 'positive'}]],
             'edge_spans': [[aa, ee], [ee, bb], [aa], [bb], [[aa[1], ee[0]]]], 'project': []}
    return {'id': i, 'kind': 'passage', 'text': text, 'graph': graph}


def training():
    return [sentence('p1', 'Ann', 'sent', 'Bo'), sentence('p2', 'Cy', 'send', 'Di'),
            sentence('p3', 'Eve', 'sent', 'Flo'), sentence('n1', 'Gus', 'send', 'Hal', True),
            sentence('n2', 'Ian', 'send', 'Jo', True), sentence('n3', 'Kim', 'send', 'Lee', True)]


def polarity(graph):
    return [o['literal'] for s, p, o in graph['edges'] if p == 'polarity'][0]


def test_counts_are_integers_with_origins():
    built = W.build(training())
    assert built['schema'] == W.SCHEMA and built['examples'] == 6 and not built['skipped']
    assert built['cues']['did not']['as_cue'] == {'n': 3, 'origins': ['n1', 'n2', 'n3']}
    assert 'inside_value' not in built['cues']['did not']
    json.dumps(built)
    for table in built['tables'].values():
        for row in table.values():
            for cell in row.values():
                assert type(cell['n']) is int and cell['n'] >= len(cell['origins']) >= 1


def test_swallowed_negation_is_ambiguous_without_weights_and_resolved_with_them():
    train = training()
    grammar = v2.induce(train)['grammar']
    case = sentence('t', 'Max', 'send', 'Ned', True)
    plain = v2.parse(case['text'], grammar)
    assert plain['status'] == 'ambiguous'
    assert sorted(polarity(g) for g in plain['graphs']) == ['negative', 'positive']
    ranked = W.rank(case['text'], plain, W.build(train))
    assert ranked['status'] == 'complete' and ranked['weighted']['applied']
    assert v2.canonical(ranked['graphs'][0]) == v2.canonical(case['graph'])
    assert plain['status'] == 'ambiguous' and len(plain['graphs']) == 2


def test_small_margin_stays_ambiguous():
    train = training()
    grammar = v2.induce(train)['grammar']
    case = sentence('t', 'Max', 'send', 'Ned', True)
    strict = W.build(train, {'alpha': [1, 2], 'margin_ratio': 10 ** 9, 'require_support': True})
    ranked = W.parse(case['text'], grammar, strict)
    assert ranked['status'] == 'ambiguous' and len(ranked['graphs']) == 2
    assert ranked['weighted']['reason'] == 'margin below required ratio'


def test_unobserved_term_holds_even_with_a_large_margin():
    train = training()
    case = sentence('t', 'Max', 'send', 'Ned', True)
    good = case['graph']
    flipped = copy.deepcopy(good)
    flipped['edges'][4] = ['e', 'polarity', {'literal': 'positive'}]
    built = W.build(train)
    assert W.score(good, case['text'], built)['supported']
    assert not W.score(flipped, case['text'], built)['supported']
    assert W.score(good, case['text'], built)['score'] > W.score(flipped, case['text'], built)['score']
    # Only the unobserved reading and one worse competitor: the top is unsupported, so no resolution.
    worse = copy.deepcopy(flipped)
    worse['edges'][0][1] = 'object'
    worse['edges'][1][1] = 'actor'
    fake = {'status': 'ambiguous', 'graphs': [flipped, worse], 'complete': True, 'derivations': []}
    loose = dict(built, policy={'alpha': [1, 2], 'margin_ratio': 1, 'require_support': True})
    assert W.rank(case['text'], fake, loose)['status'] == 'ambiguous'


def test_non_ambiguous_parses_pass_through_unchanged():
    train = training()
    grammar = v2.induce(train)['grammar']
    built = W.build(train)
    done = W.parse('Ann sent Bo', grammar, built)
    assert done['status'] == 'complete' and not done['weighted']['applied']
    missing = W.parse('zzz', grammar, built)
    assert missing['status'] == 'unresolved' and missing['graphs'] == [] and not missing['weighted']['applied']


def test_compare_reports_transitions_without_text_or_graphs():
    train = training()
    grammar = v2.induce(train)['grammar']
    rows = driver.compare(grammar, W.build(train), [sentence('t1', 'Max', 'send', 'Ned', True),
                                                    sentence('t2', 'Oz', 'sent', 'Pat')])
    summary = driver.summarize(rows)
    assert summary['transitions'] == {'ambiguous_gold_present -> correct': 1, 'correct -> correct': 1}
    assert summary['gold_lost'] == 0 and summary['resolved_correct'] == 1
    assert all(set(row) == {'id', 'kind', 'before', 'after', 'margin', 'reason'} for row in rows)


def test_all_candidates_swallowing_a_cue_stay_ambiguous():
    train = training()
    case = sentence('t', 'Max', 'send', 'Ned', True)
    text = case['text']
    aa, ee, bb = [0, len('Max did not')], case['graph']['nodes'][1]['anchor'], case['graph']['nodes'][2]['anchor']
    swallowed = {'nodes': [{'id': 'a', 'type': 'person', 'anchor': aa}, {'id': 'e', 'type': 'event', 'anchor': ee},
                           {'id': 'b', 'type': 'person', 'anchor': bb}],
                 'edges': [['e', 'actor', 'a'], ['e', 'object', 'b'], ['a', 'value', {'copy': aa}],
                           ['b', 'value', {'copy': bb}], ['e', 'polarity', {'literal': 'positive'}]],
                 'edge_spans': [[aa, ee], [ee, bb], [aa], [bb], [ee]], 'project': []}
    other = copy.deepcopy(swallowed)
    other['edges'][0][1], other['edges'][1][1] = 'object', 'actor'
    built = W.build(train, {'alpha': [1, 2], 'margin_ratio': 1, 'require_support': True})
    assert not W.score(swallowed, text, built)['supported']
    fake = {'status': 'ambiguous', 'graphs': [swallowed, other], 'complete': True, 'derivations': []}
    ranked = W.rank(text, fake, built)
    assert ranked['status'] == 'ambiguous' and ranked['weighted']['reason'] == 'top reading has an unobserved term'


def test_blind_substitution_keeps_graphs_valid_and_pools_disjoint():
    from experiments.graph_example_acquisition import native
    from experiments.graph_weighted_acquisition import augment as A

    def ko(i, a, b):
        text = a + '이 ' + b + '를 도왔다.'
        aa, bb = [0, len(a)], [len(a) + 2, len(a) + 2 + len(b)]
        ee = [bb[1] + 2, bb[1] + 5]
        graph = {'nodes': [{'id': 'a', 'type': 'person', 'anchor': aa}, {'id': 'b', 'type': 'person', 'anchor': bb},
                           {'id': 'e', 'type': 'event', 'anchor': ee}],
                 'edges': [['e', 'actor', 'a'], ['e', 'object', 'b'], ['a', 'value', {'copy': aa}],
                           ['b', 'value', {'copy': bb}]],
                 'edge_spans': [[aa, ee], [bb, ee], [aa], [bb]], 'project': []}
        return {'id': i, 'kind': 'passage', 'text': text, 'graph': graph}

    data = {'examples': [ko('p', '수겸', '미라'), ko('q', '수겸', '미라')],
            'pairs': [{'id': 'pq', 'passage_id': 'p', 'question_id': 'q', 'expected_bindings': [['수겸']],
                       'perturbations': ['person']}]}
    data['examples'][1]['text'] = data['examples'][1]['text'].replace('.', '?')
    names = A.load_names('experiments/graph_weighted_acquisition/data/korean_given_names.txt')
    assert len(names) == 660
    train_names, test_names = A.split_names(names, 7)
    assert not set(train_names) & set(test_names) and len(train_names) + len(test_names) == 660
    out, skipped = A.augment(data, train_names, 5, 7)
    assert not skipped and len(out['examples']) == 12 and len(out['pairs']) == 6
    for ex in out['examples']:
        native._check(ex['graph'], ex['text'])
        values = [ex['text'][slice(*o['copy'])] for s, p, o in ex['graph']['edges'] if p == 'value']
        assert ex['text'] == values[0] + '이 ' + values[1] + ('를 도왔다.' if ex['id'].startswith('p') else '를 도왔다?')
        assert A.final_class(values[0]) == 'closed' and A.final_class(values[1]) == 'open'
    for pair in out['pairs'][1:]:
        passage = [e for e in out['examples'] if e['id'] == pair['passage_id']][0]
        assert passage['text'].startswith(pair['expected_bindings'][0][0])
    assert A.augment(data, train_names, 5, 7)[0] == out


def _two(i, first, second):
    """Two sentences in one text, every mention its own node, as the v2 union builds it."""
    sep = '. '
    text = first['text'] + sep + second['text']
    off = len(first['text']) + len(sep)

    def shift(span):
        return [span[0] + off, span[1] + off]

    nodes = [dict(n, id='L' + n['id']) for n in first['graph']['nodes']]
    nodes += [dict(n, id='R' + n['id'], anchor=shift(n['anchor'])) for n in second['graph']['nodes']]
    edges, spans = [], []
    for side, graph, move in (('L', first['graph'], lambda s: s), ('R', second['graph'], shift)):
        for (s, p, o), evidence in zip(graph['edges'], graph['edge_spans']):
            o = side + o if isinstance(o, str) else ({'copy': move(o['copy'])} if 'copy' in o else o)
            edges.append([side + s, p, o])
            spans.append([move(e) for e in evidence])
    return {'id': i, 'kind': 'passage', 'text': text,
            'graph': {'nodes': nodes, 'edges': edges, 'edge_spans': spans, 'project': []}}


def test_repeated_value_merges_only_when_training_showed_it():
    from experiments.graph_weighted_acquisition import merge as M
    separate = _two('u', sentence('a', 'Ann', 'sent', 'Bo'), sentence('b', 'Ann', 'sent', 'Di'))
    text, graph = separate['text'], separate['graph']
    assert M.identity_counts([separate]) == {'person': {'separate': {'n': 1, 'origins': ['u']}}}
    assert M.merge_graph(graph, text, {}) is None
    assert M.merge_graph(graph, text, M.identity_counts([separate])) is None
    merged = M.merge_graph(graph, text, {}, force=True)
    assert len(merged['nodes']) == len(graph['nodes']) - 1
    assert sum(1 for s, p, o in merged['edges'] if o == 'La') == 2 and 'Ra' not in str(merged['edges'])
    taught = dict(separate, id='m', graph=merged)
    table = M.identity_counts([taught])
    assert table == {'person': {'merged': {'n': 1, 'origins': ['m']}}} and M.allowed(table, 'person')
    again = M.merge_graph(graph, text, table)
    assert v2.canonical(again) == v2.canonical(merged)
    # Both ways seen in training: the gate stays closed.
    assert not M.allowed(M.identity_counts([taught, separate]), 'person')
    # A shared node scores by mention, so merging does not change the counted pieces.
    assert sorted(W.features(merged, text)['terms']) == sorted(W.features(graph, text)['terms'])
    fake = {'status': 'complete', 'graphs': [graph], 'complete': True, 'derivations': []}
    assert M.expand(text, fake, {'identity': {}})['graphs'] == [graph]
    out = M.expand(text, fake, {'identity': table})
    assert out['merge']['applied'] == 1 and v2.canonical(out['graphs'][0]) == v2.canonical(merged)
