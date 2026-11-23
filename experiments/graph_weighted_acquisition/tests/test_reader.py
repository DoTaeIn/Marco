import json

from experiments.graph_example_acquisition import native, v2
from experiments.graph_weighted_acquisition import answer as A, reader as R

VERBS = {'도왔다': ('help', 'positive'), '도왔나': ('help', 'positive'), '돕지 않았다': ('help', 'negative'),
         '돕지 않았나': ('help', 'negative'), '불렀다': ('call', 'positive'), '불렀나': ('call', 'positive')}


def particle(name, closed, opened):
    return closed if (ord(name[-1]) - 0xAC00) % 28 else opened


def clause(i, actor, obj, verb, source=None, ask=None, kind='passage'):
    """One made-up sentence in the teacher schema. `ask` replaces the actor with 누가."""
    text, nodes, edges, spans = '', [], [], []

    def add(node, surface, after):
        nonlocal text
        span = [len(text), len(text) + len(surface)]
        text += surface + after
        nodes.append({'id': node, 'type': 'event' if node == 'e' else 'person', 'anchor': span})
        return span

    src = add('s', source, '에 따르면, ') if source else None
    act = add('a', '누가', ' ') if ask else add('a', actor, particle(actor, '이 ', '가 '))
    ob = add('o', obj, particle(obj, '을 ', '를 '))
    ev = add('e', verb, '?' if kind == 'question' else '.')
    action, polarity = VERBS[verb]
    edges += [['e', 'actor', 'a'], ['e', 'object', 'o'], ['e', 'action', {'literal': action}],
              ['e', 'polarity', {'literal': polarity}]]
    spans += [[act, ev], [ev, ob], [ev], [ev]]
    if src:
        edges.append(['e', 'source', 's'])
        spans.append([src, [src[1], src[1] + 5]])
    for node, span in (('s', src), ('a', None if ask else act), ('o', ob)):
        if span:
            edges.append([node, 'value', {'copy': span}])
            spans.append([span])
    graph = {'nodes': nodes, 'edges': edges, 'edge_spans': spans, 'project': ['a'] if ask else []}
    native._check(graph, text)
    return {'id': i, 'kind': kind, 'text': text, 'graph': graph}


def training():
    people = ['가람', '나리', '다온', '라희', '마루', '바다', '사랑', '아진']
    out = []
    for n, (a, b) in enumerate(zip(people, people[1:] + people[:1])):
        src = people[(n + 3) % 8] if n % 2 else None
        out.append(clause('p%d' % n, a, b, '도왔다' if n % 3 else '돕지 않았다', src))
        out.append(clause('q%d' % n, a, b, '도왔나' if n % 3 else '돕지 않았나', src, ask=True, kind='question'))
    return out


def test_model_is_small_integer_counts_with_origins():
    model = R.build(training())
    assert model['schema'] == R.SCHEMA and not model['skipped']
    text = json.dumps(model, ensure_ascii=False)
    assert len(text.encode()) < 20000
    for name, table in model['tables'].items():
        for row in table.values():
            for cell in row.values():
                assert type(cell['n']) is int and cell['n'] >= 1 and len(cell['origins']) >= 1
                # Stems and endings count word forms; their origins are the examples behind those forms.
                assert name in ('stem', 'ending') or cell['n'] >= len(cell['origins'])
    assert set(model['tables']['stem']) >= {'도왔', '돕지 않았'}


def test_reads_unseen_names_exactly():
    model = R.build(training())
    case = clause('t', '하늘', '준서', '돕지 않았다', '유진')
    result = R.read(case['text'], model)
    assert result['status'] == 'complete', result['reason']
    assert v2.canonical(result['graphs'][0]) == v2.canonical(case['graph'])


def test_two_sentences_never_seen_together_are_read_one_at_a_time():
    model = R.build(training())
    first, second = clause('a', '하늘', '준서', '돕지 않았다', '유진'), clause('b', '소은', '준서', '도왔다', '유진')
    passage = first['text'] + ' ' + second['text']
    # No lesson joins two sentences, so the text as a whole cannot be cut ...
    assert R._read_one(passage, model)['status'] != 'complete'
    # ... but each sentence is known, and the text is read as two of them.
    reading = R.read(passage, model)
    assert reading['status'] == 'complete' and reading['sentences'] == reading['sentences_read'] == 2
    assert sum(1 for n in reading['graphs'][0]['nodes'] if n['type'] == 'event') == 2
    for span, node in ((n['anchor'], n) for n in reading['graphs'][0]['nodes']):
        assert passage[slice(*span)] in ('하늘', '소은', '준서', '유진', '돕지 않았다', '도왔다')
    result = A.answer(passage, '유진에 따르면, 누가 준서를 도왔나?', model)
    assert result['status'] == 'answered' and result['answers'] == [['소은']]
    assert {e['text'] for e in result['evidence']} >= {'소은', '도왔다'}
    assert 'read as 2 sentences' in A.explain(passage, '유진에 따르면, 누가 준서를 도왔나?', result)
    one = A.answer(first['text'], '유진에 따르면, 누가 준서를 돕지 않았나?', model)
    assert one['status'] == 'answered' and one['answers'] == [['하늘']]


def test_one_unread_sentence_holds_the_whole_passage():
    model = R.build(training())
    known = clause('a', '하늘', '준서', '도왔다')['text']
    passage = known + ' 소은이 준서를 만났다. ' + known.replace('하늘', '지안')
    reading = R.read(passage, model)
    assert reading['status'] != 'complete' and reading['graphs'] == []
    assert reading['sentences'] == 3 and '소은이 준서를 만났다.' in reading['reason']
    result = A.answer(passage, '누가 준서를 도왔나?', model)
    assert result['status'] == 'hold' and result['answers'] == []
    assert '# No answer given' in A.explain(passage, '누가 준서를 도왔나?', result)


def test_many_sentences_are_read_in_time_that_grows_with_their_number():
    import time
    model = R.build(training())
    names = ['하늘', '소은', '지안', '보라', '다혜', '민서', '서윤', '도현']
    passage = ' '.join(clause('s', n, '준서', '도왔다')['text'] for n in names * 8)
    start = time.perf_counter()
    reading = R.read(passage, model)
    assert reading['status'] == 'complete' and reading['sentences_read'] == 64
    assert time.perf_counter() - start < 2.0


def test_report_states_answer_counts_and_rivals():
    model = R.build(training())
    passage, question = '유진에 따르면, 하늘이 준서를 돕지 않았다.', '유진에 따르면, 누가 준서를 돕지 않았나?'
    report = A.explain(passage, question, A.answer(passage, question, model))
    for needed in ('# Answer: 하늘', 'How the passage was read', 'How the question was read', 'Seen in training',
                   'role from the piece after it', 'Rival', 'No neural network'):
        assert needed in report, needed


def test_unknown_word_gives_no_answer_and_says_why():
    model = R.build(training())
    passage, question = '하늘이 준서를 만났다.', '누가 준서를 도왔나?'
    result = A.answer(passage, question, model)
    assert result['status'] == 'hold' and result['answers'] == []
    report = A.explain(passage, question, result)
    assert '# No answer given' in report and 'passage was not read with confidence' in report


def test_wrong_condition_gives_no_answer():
    model = R.build(training())
    result = A.answer('하늘이 준서를 도왔다.', '누가 준서를 돕지 않았나?', model)
    assert result['status'] == 'hold' and 'nothing in the passage fits' in result['reason']


def test_stem_and_ending_compose_an_unseen_word_form():
    extra = [clause('c1', '가람', '나리', '불렀다'), clause('c2', '다온', '라희', '불렀다'),
             clause('c3', '마루', '바다', '불렀다', '사랑')]
    only_statements = [ex for ex in training() if ex['kind'] == 'passage']
    questions = [clause('k1', '가람', '나리', '도왔나', ask=True, kind='question'),
                 clause('k2', '다온', '라희', '도왔나', '마루', ask=True, kind='question')]
    model = R.build(only_statements + extra + questions)
    assert '불렀나' not in model['tables']['head'] and '불렀' in model['tables']['stem']
    result = A.answer('하늘이 준서를 불렀다.', '누가 준서를 불렀나?', model)
    assert result['status'] == 'answered' and result['answers'] == [['하늘']], result['reason']


def _two_sentence_training():
    """Teacher-style two-sentence passages, so the joining piece between sentences is known."""
    people = ['가람', '나리', '다온', '라희', '마루', '바다', '사랑', '아진']
    out = training()
    for n in range(4):
        first = clause('x', people[n], people[n + 1], '도왔다', people[n + 2])
        second = clause('y', people[n + 3], people[n + 4], '돕지 않았다' if n % 2 else '도왔다', people[(n + 5) % 8])
        off = len(first['text']) + 1

        def move(span):
            return [span[0] + off, span[1] + off]

        graph = {'nodes': [dict(m, id='L' + m['id']) for m in first['graph']['nodes']] +
                          [dict(m, id='R' + m['id'], anchor=move(m['anchor'])) for m in second['graph']['nodes']],
                 'edges': [], 'edge_spans': [], 'project': []}
        for side, part, shift in (('L', first, lambda s: s), ('R', second, move)):
            for (s, p, o), spans in zip(part['graph']['edges'], part['graph']['edge_spans']):
                o = side + o if isinstance(o, str) else ({'copy': shift(o['copy'])} if 'copy' in o else o)
                graph['edges'].append([side + s, p, o])
                graph['edge_spans'].append([shift(x) for x in spans])
        out.append({'id': 'two%d' % n, 'kind': 'passage', 'text': first['text'] + ' ' + second['text'], 'graph': graph})
    return out


def test_long_passage_is_answered_by_direct_matching():
    model = R.build(_two_sentence_training())
    names = ['하늘', '소은', '지안', '보라', '다혜', '민서']
    passage = ' '.join(clause('s', n, '준서', '도왔다', '유진')['text'] for n in names[:-1])
    passage += ' ' + clause('s', names[-1], '시우', '돕지 않았다', '경아')['text']
    result = A.answer(passage, '경아에 따르면, 누가 시우를 돕지 않았나?', model)
    assert result['status'] == 'answered' and result['answers'] == [['민서']], result['reason']
    assert result['executor'] == 'unavailable' and result['verified'] is False
    report = A.explain(passage, '경아에 따르면, 누가 시우를 돕지 않았나?', result)
    assert '| actor = the thing asked for |' in report and 'not independently verified' in report.splitlines()[0]
    assert '**Not independently verified.**' in report and '| the name of what was asked for | "민서" |' in report
    assert '| a name given in the question: "시우" | "시우" |' in report
    several = A.answer(passage, '유진에 따르면, 누가 준서를 도왔나?', model)
    assert several['answers'] == sorted([n] for n in names[:-1])


def test_short_passage_agrees_with_the_older_executor():
    model = R.build(training())
    result = A.answer('유진에 따르면, 하늘이 준서를 도왔다.', '유진에 따르면, 누가 준서를 도왔나?', model)
    assert result['status'] == 'answered' and result['executor'] == 'agrees' and result['verified'] is True
    assert 'Verified:' in A.explain('유진에 따르면, 하늘이 준서를 도왔다.', '유진에 따르면, 누가 준서를 도왔나?', result)


def test_event_that_fits_but_names_no_actor_blocks_the_answer():
    from experiments.graph_weighted_acquisition import match as MT
    known, asked = clause('p', '하늘', '준서', '도왔다'), clause('q', '하늘', '준서', '도왔나', ask=True, kind='question')
    assert MT.match(known['graph'], known['text'], asked['graph'], asked['text'])['answers'] == [['하늘']]
    graph = json.loads(json.dumps(known['graph']))
    graph['nodes'].append({'id': 'e2', 'type': 'event', 'anchor': known['graph']['nodes'][2]['anchor']})
    for edge, spans in list(zip(graph['edges'], graph['edge_spans'])):
        if edge[0] == 'e' and edge[1] != 'actor':
            graph['edges'].append(['e2'] + edge[1:])
            graph['edge_spans'].append(spans)
    blocked = MT.match(graph, known['text'], asked['graph'], asked['text'])
    assert blocked['status'] == 'hold' and 'does not say who' in blocked['reason']


def test_a_refusal_or_disagreement_from_the_second_method_withholds_the_answer(monkeypatch=None):
    model = R.build(training())
    passage, question = '유진에 따르면, 하늘이 준서를 도왔다.', '유진에 따르면, 누가 준서를 도왔나?'
    original = A.native.run_pair
    try:
        A.native.run_pair = lambda *a, **k: {'passed': False, 'actual': [['소은']], 'status': 'evidence'}
        other = A.answer(passage, question, model)
        assert other['status'] == 'hold' and other['answers'] == [] and other['withheld'] == [['하늘']]
        assert other['executor'] == 'disagrees' and 'withheld' in A.explain(passage, question, other)
        A.native.run_pair = lambda *a, **k: {'passed': False, 'reason': 'relevant context has missing projected-role binding'}
        refused = A.answer(passage, question, model)
        assert refused['status'] == 'hold' and refused['executor'] == 'refuses'
    finally:
        A.native.run_pair = original


def test_two_equally_common_meanings_end_in_a_tie_not_a_pick():
    examples = training()
    twin = json.loads(json.dumps([ex for ex in examples if '도왔다' in ex['text']]))
    for ex in twin:
        ex['id'] += 'b'
        for edge in ex['graph']['edges']:
            if edge[1] == 'action':
                edge[2] = {'literal': 'assist'}
    model = R.build(examples + twin)
    result = R.read('하늘이 준서를 도왔다.', model)
    assert result['status'] == 'ambiguous' and result['margin'] < result['required_margin']
    assert result['reason'] in ('equal scores for two readings', 'two readings are too close')
    actions = {o['literal'] for g in result['graphs'] for s, p, o in g['edges'] if p == 'action'}
    assert actions == {'help', 'assist'}
    assert A.answer('하늘이 준서를 도왔다.', '누가 준서를 도왔나?', model)['status'] == 'hold'


def test_single_reading_is_not_described_as_a_lead():
    model = R.build(training())
    result = R.read('하늘이 준서를 도왔다.', model)
    assert result['status'] == 'complete'
    if result['margin'] is None:
        assert 'lead' not in result['reason'] and 'only reading' in result['reason']


def test_every_place_that_grounds_an_answer_is_kept():
    from experiments.graph_weighted_acquisition import match as MT
    model = R.build(_two_sentence_training())
    passage = '유진에 따르면, 하늘이 준서를 도왔다. 경아에 따르면, 하늘이 준서를 도왔다.'
    pg = R.read(passage, model)['graphs'][0]
    question = '누가 준서를 도왔나?'
    qg = R.read(question, model)['graphs'][0]
    found = MT.match(pg, passage, qg, question)
    assert found['answers'] == [['하늘']] and len(found['proofs']) == 2
    starts = sorted(fact['spans'][0][0] for proof in found['proofs'] for fact in proof['facts']
                    if fact['condition'][1] == 'answer name')
    assert starts[0] < len(passage) // 2 < starts[1]
    assert all(fact['spans'] for proof in found['proofs'] for fact in proof['facts'])


def _with_executor(run_pair, raw):
    """Swap the older executor and the separate search for fixed results."""
    saved = A.native.run_pair, A.execute_query_graph
    A.native.run_pair, A.execute_query_graph = (lambda *a, **k: run_pair), (lambda *a, **k: raw)
    return saved


def test_executor_refusal_stays_a_refusal_even_if_a_later_search_runs_out():
    model = R.build(training())
    passage, question = '유진에 따르면, 하늘이 준서를 도왔다.', '유진에 따르면, 누가 준서를 도왔나?'
    limit = {'status': 'hold', 'reason': 'proof_or_search_limit'}
    refusals = [{'passed': False, 'reason': 'relevant context has missing projected-role binding'},
                {'passed': False, 'reason': 'distinct structural referents share a copied value tuple'},
                {'passed': False, 'reason': 'candidate-context provenance incomplete'},
                {'passed': False, 'reason': 'projected-role witness incomplete', 'status': 'ambiguous'}]
    for refusal in refusals:
        saved = _with_executor(refusal, limit)
        try:
            result = A.answer(passage, question, model)
        finally:
            A.native.run_pair, A.execute_query_graph = saved
        assert result['status'] == 'hold' and result['executor'] == 'refuses', refusal
        assert result['answers'] == [] and result['withheld'] == [['하늘']]
    # A stop inside a search, confirmed as a budget stop, is the only "unavailable".
    saved = _with_executor({'passed': False, 'status': 'hold',
                            'reason': 'candidate-context search incomplete or no evidence'}, limit)
    try:
        result = A.answer(passage, question, model)
        assert result['status'] == 'answered' and result['executor'] == 'unavailable' and not result['verified']
        A.execute_query_graph = lambda *a, **k: {'status': 'hold', 'reason': 'ambiguous_reading'}
        assert A.answer(passage, question, model)['executor'] == 'refuses'
    finally:
        A.native.run_pair, A.execute_query_graph = saved
    saved = _with_executor({'passed': False, 'status': 'no_evidence',
                            'reason': 'native search incomplete or no evidence'}, limit)
    try:
        assert A.answer(passage, question, model)['executor'] == 'disagrees'
    finally:
        A.native.run_pair, A.execute_query_graph = saved


def test_chosen_reading_is_always_in_the_report_list():
    ranked = [{'n': i} for i in range(8)]
    for pick in (0, 4, 5, 7):
        shown, at = R._shown(ranked, ranked[pick])
        assert len(shown) == R.KEPT and shown[at] is ranked[pick]
    model = R.build(training())
    passage, question = '유진에 따르면, 하늘이 준서를 도왔다.', '유진에 따르면, 누가 준서를 도왔나?'
    result = A.answer(passage, question, model)
    late = dict(result['passage'])
    filler = [dict(r, supported=False) for r in late['readings'][:1]] * 7
    late['readings'], late['chosen'] = R._shown(filler + [result['passage']['readings'][result['passage']['chosen']]],
                                                result['passage']['readings'][result['passage']['chosen']])
    assert '# Answer: 하늘' in A.explain(passage, question, dict(result, passage=late))


def test_every_origin_is_a_training_example_id():
    examples = training() + [clause('c1', '가람', '나리', '불렀다'), clause('c2', '다온', '라희', '불렀나', ask=True, kind='question')]
    model = R.build(examples)
    ids = {ex['id'] for ex in examples}
    cells = [cell for table in model['tables'].values() for row in table.values() for cell in row.values()]
    cells += [cell for row in model['cues'].values() for cell in row.values()]
    assert cells and all(set(cell['origins']) <= ids and cell['origins'] for cell in cells)
    stem = model['tables']['stem']['불렀']
    cell = next(iter(stem.values()))
    assert set(cell['origins']) == {'c1', 'c2'} and set(cell['forms']) == {'불렀다', '불렀나'}
    report = A.explain('하늘이 준서를 불렀다.', '누가 준서를 불렀나?',
                       A.answer('하늘이 준서를 불렀다.', '누가 준서를 불렀나?', R.build(
                           [ex for ex in examples if ex['id'] != 'c2'] +
                           [clause('k1', '가람', '나리', '도왔나', ask=True, kind='question')])))
    assert 'from word forms' in report


def test_connectors_are_counted_with_their_spaces():
    model = R.build(training())
    assert '가 ' in model['cues'] and '가' not in model['cues'] and '이' not in model['cues']
    # A name containing a connector's letter is read without any piece counted as left over.
    result = R.read('이든이 소이가를 도왔다.'.replace('소이가를', '가이를'), model)
    assert result['status'] == 'complete', result['reason']
    assert not [t for t in result['readings'][result['chosen']]['terms'] if t['what'] == 'known piece left unused']


def _giving(model):
    """The same pack with the convention of before 2026-11-23: a partial answer is given, flagged."""
    return dict(model, conventions=dict(model['conventions'], partial_answers='give'))


def test_unknown_words_before_a_fixed_word_give_a_flagged_partial_answer():
    model = R.build(training())
    passage, question = '하늘이 준서를 도왔다.', '누가 준서를 정말 도왔나?'
    reading = R.read(question, model)
    assert reading['status'] == 'complete' and reading['ignored'] == ['정말']
    assert reading['reason'].startswith('partial reading, ignoring "정말"')
    # By the pack's convention such an answer is withheld: the ignored word may be the one that matters.
    kept = A.answer(passage, question, model)
    assert kept['status'] == 'hold' and kept['answers'] == [] and kept['withheld'] == [['하늘']]
    assert 'passing over part of it' in kept['reason'] and '"정말"' in kept['reason']
    assert A.explain(passage, question, kept).startswith('# No answer given')
    model = _giving(model)
    result = A.answer(passage, question, model)
    assert result['status'] == 'answered' and result['answers'] == [['하늘']]
    assert result['verified'] is False and result['partial'] == ['words in the question were ignored: "정말"']
    report = A.explain(passage, question, result)
    assert 'partial reading' in report.splitlines()[0] and '[정말 |IGNORED]' in report
    # The same text read without ignoring anything always wins when it exists.
    assert R.read('누가 준서를 도왔나?', model)['ignored'] == []
    # A passage is never answered from a reading that ignores part of it.
    held = A.answer('하늘이 준서를 정말 도왔다.', '누가 준서를 도왔나?', model)
    assert held['status'] == 'hold' and 'ignoring "정말"' in held['reason']


def test_names_match_exactly_first_then_by_spacing_then_with_leading_words_reported():
    from experiments.graph_weighted_acquisition import match as MT
    assert MT.name_fit('준서', {'준서'}, 2) == {'level': 0}
    assert MT.name_fit('준 서', {'준서'}, 0) is None and MT.name_fit('준 서', {'준서'}, 1)['level'] == 1
    fit = MT.name_fit('옆집 준서', {'준서'}, 2)
    assert fit['level'] == 2 and fit['ignored'] == '옆집' and MT.name_fit('옆집 준서', {'준서'}, 1) is None
    assert MT.name_fit('이준서', {'준서'}, 2) is None and MT.name_fit('준서 옆집', {'준서'}, 2) is None
    model = R.build(training())
    passage = '하늘이 준서를 도왔다.'
    # Words in front of a name may be what tells two things apart, so by convention no answer is given.
    kept = A.answer(passage, '누가 옆집 준서를 도왔나?', model)
    assert kept['status'] == 'hold' and kept['withheld'] == [['하늘']] and '"옆집"' in kept['reason']
    loose = A.answer(passage, '누가 옆집 준서를 도왔나?', _giving(model))
    assert loose['status'] == 'answered' and loose['answers'] == [['하늘']] and loose['verified'] is False
    assert loose['executor'] == 'not comparable' and '"옆집"' in loose['partial'][0]
    exact = A.answer(passage, '누가 준서를 도왔나?', model)
    assert exact['partial'] == [] and exact['verified'] is True and exact['match']['relaxed'] == 0
    # An exact match elsewhere in the passage is preferred over a loose one.
    both = A.answer('하늘이 준서를 도왔다. 소은이 옆집 준서를 도왔다.', '누가 옆집 준서를 도왔나?', model)
    assert both['answers'] == [['소은']] and both['match']['relaxed'] == 0


def _fact(i, kind, who, word, value, close):
    """'X의 P은 V이다.', its question, or the yes/no check 'X의 P은 V가 맞나?'."""
    parts = [('s', who), (None, '의 '), ('e', word), (None, '은 '), ('v', value)]
    parts += [(None, '가 '), ('c', '맞나'), (None, '?')] if close == 'check' else [(None, close)]
    text, at = '', {}
    for role, piece in parts:
        if role:
            at[role] = [len(text), len(text) + len(piece)]
        text += piece
    kinds = {'s': 'subject', 'e': 'relation', 'v': 'amount', 'c': 'check'}
    edges = [['e', 'subject', 's'], ['e', 'amount', 'v'], ['e', 'kind', {'literal': word}], ['s', 'value', {'copy': at['s']}]]
    spans = [[at['s'], at['e']], [at['e'], at['v']], [at['e']], [at['s']]]
    if kind != 'ask':
        edges.append(['v', 'value', {'copy': at['v']}])
        spans.append([at['v']])
    if close == 'check':
        edges.append(['e', 'claim', 'c'])
        spans.append([at['e'], at['c']])
    graph = {'nodes': [{'id': r, 'type': kinds[r], 'anchor': at[r]} for r in at], 'edges': edges, 'edge_spans': spans,
             'project': ['v'] if kind == 'ask' else []}
    return {'id': i, 'kind': 'passage' if kind == 'say' else 'question', 'text': text, 'graph': graph}


def test_yes_no_question_is_answered_by_lookup_and_comparison():
    lessons = []
    for n, (who, value) in enumerate([('푸른별', '7%'), ('노란달', '4%'), ('하얀숲', '12%'), ('붉은꽃', '9%')]):
        lessons += [_fact('s%d' % n, 'say', who, '세율', value, '이다.'), _fact('a%d' % n, 'ask', who, '세율', '얼마', '인가?'),
                    _fact('c%d' % n, 'check', who, '세율', value, 'check')]
    model = R.build(lessons)
    assert not model['skipped']
    passage = '은빛강의 세율은 15%이다. 파란섬의 세율은 3%이다.'
    wrong = A.answer(passage, '은빛강의 세율은 3%가 맞나?', model)
    assert wrong['status'] == 'answered' and wrong['answers'] == [['15%']]
    assert wrong['claim'] == {'claimed': '3%', 'holds': False}
    assert A.explain(passage, '은빛강의 세율은 3%가 맞나?', wrong).startswith('# Answer: No. The passage says 15%, not 3%')
    right = A.answer(passage, '파란섬의 세율은 3%가 맞나?', model)
    assert right['claim'] == {'claimed': '3%', 'holds': True}
    assert A.explain(passage, '파란섬의 세율은 3%가 맞나?', right).startswith('# Answer: Yes, 3%')
    assert A.answer(passage, '보라집의 세율은 3%가 맞나?', model)['status'] == 'hold'
    plain = A.answer(passage, '은빛강의 세율은 얼마인가?', model)
    assert plain['answers'] == [['15%']] and plain['claim'] is None


def _raw_lines():
    """Made-up raw text: 은 after closed syllables, 는 after open ones, same words after both."""
    closed = ['별', '달', '숲', '꽃', '산', '강', '섬', '집', '길', '들판']
    opened = ['나무', '바다', '하늘이라', '노래', '마루', '여우', '기차', '도시', '파도', '고래']
    after = ['크다', '작다', '멀다', '좋다', '많다', '있다']
    lines = []
    for i, word in enumerate(closed + opened):
        for j, following in enumerate(after):
            lines.append('%s%s %s' % (word, '은' if word in closed else '는', following))
            # 도 follows both kinds of word, so it has no variant; 에 is followed by other words.
            lines.append('%s도 %s' % (word, after[(i + j) % len(after)]))
            lines.append('%s에 %s' % (word, ['간다', '온다', '산다'][j % 3]))
    return lines


def test_connector_variants_are_found_from_raw_text_alone():
    from experiments.graph_weighted_acquisition import variants as V
    policy = {'min_count': 20, 'min_distinct_before': 5, 'kept_endings': 50}
    found = V.pairs(V.count(_raw_lines(), policy))
    assert [p['forms'] for p in found] == [['는', '은']]
    pair = found[0]
    assert pair['same_preceding_per_thousand'] == 0 and pair['same_following_per_thousand'] == 1000
    assert pair['distinct_before']['은'] >= 5 and set(pair['examples_following']) <= {'크다', '작다', '멀다', '좋다', '많다', '있다'}
    assert V.lookup({'pairs': found})['은'][0] == '는'


def test_untaught_connector_is_read_through_its_variant_and_reported():
    from experiments.graph_weighted_acquisition import variants as V
    learned = {'pairs': V.pairs(V.count(_raw_lines(), {'min_count': 20, 'min_distinct_before': 5, 'kept_endings': 50}))}
    lessons = []
    for n, (who, value) in enumerate([('푸른별', '7%'), ('노란달', '4%'), ('하얀숲', '12%'), ('붉은꽃', '9%')]):
        lessons += [_fact('s%d' % n, 'say', who, '세율', value, '이다.'), _fact('a%d' % n, 'ask', who, '세율', '얼마', '인가?')]
    passage, question = '은빛강의 세율는 15%이다.', '은빛강의 세율는 얼마인가?'
    plain = R.build(lessons)
    assert plain['alias'] == {} and A.answer(passage, question, plain)['status'] == 'hold'
    model = R.build(lessons, variants=learned)
    assert list(model['alias']) == ['는 '] and model['alias']['는 ']['of'] == '은 '
    result = A.answer(passage, question, model)
    assert result['status'] == 'answered' and result['answers'] == [['15%']]
    assert len(result['raw_text_variants']) == 1 and '"는" read as "은"' in result['raw_text_variants'][0]
    report = A.explain(passage, question, result)
    assert 'uses raw-text variants' in report.splitlines()[0] and 'Read with help from raw text' in report
    # The taught form is still read exactly as before, with nothing borrowed.
    taught = A.answer('은빛강의 세율은 15%이다.', '은빛강의 세율은 얼마인가?', model)
    assert taught['answers'] == [['15%']] and taught['raw_text_variants'] == []
    # When the lessons already teach both forms, no variant is added.
    both = lessons + [_fact('x', 'say', '보라집', '세율', '3%', '이다.')]
    both[-1]['text'] = both[-1]['text'].replace('세율은', '세율는')
    assert R.build(both, variants=learned)['alias'] == {}


def test_a_pair_is_checked_against_lessons_that_show_both_forms():
    from experiments.graph_weighted_acquisition import variants as V
    pair = {'forms': ['는', '은'], 'same_following_per_thousand': 900, 'next_best_per_thousand': 100,
            'examples_following': ['크다']}
    lessons = []
    for n, (who, value) in enumerate([('푸른별', '7%'), ('노란달', '4%'), ('하얀숲', '12%'), ('붉은꽃', '9%')]):
        lessons += [_fact('s%d' % n, 'say', who, '세율', value, '이다.'), _fact('a%d' % n, 'ask', who, '세율', '얼마', '인가?')]
    assert V.check_against_lessons({'pairs': [pair]}, lessons)[0]['status'] == 'untested'
    twins = json.loads(json.dumps(lessons[:4]))
    for ex in twins:
        ex['id'] += 'n'
        ex['text'] = ex['text'].replace('세율은', '세율는').replace('푸른별', '은빛강').replace('노란달', '파란섬')
    row = V.check_against_lessons({'pairs': [pair]}, lessons + twins)[0]
    assert row['status'] == 'passed'
    hidden = {t['hidden']: t for t in row['tests']}
    assert hidden['는'] == {'same': 4, 'different': 0, 'held': 0, 'hidden': '는', 'lessons': 4}
    # A pair that explains nothing reads nothing: that is "no evidence", not a pass.
    wrong = dict(pair, forms=['의', '은'])
    assert V.check_against_lessons({'pairs': [wrong]}, lessons + twins)[0]['status'] in ('no evidence', 'different readings')


def test_unknown_question_word_is_reported_not_read_as_a_name():
    model = R.build(training())
    assert set(model['tables']['closes']['?']) == {'asks'} and set(model['tables']['closes']['.']) == {'states'}
    passage = '유진에 따르면, 하늘이 준서를 도왔다.'
    # 누구 is not in the lessons. Read as a name, the question would ask for nothing.
    question = '누구에 따르면, 하늘이 준서를 도왔나?'
    reading = R.read(question, model)
    assert reading['status'] != 'complete'
    assert reading['unknown_words'] == ['누구', '하늘', '준서'] and reading['expected'] == 'asks'
    result = A.answer(passage, question, model)
    assert result['status'] == 'hold' and result['answers'] == []
    # Names the passage also uses are names; what is left is the unknown word.
    assert result['unknown_words'] == ['누구'] and 'does not know: "누구"' in result['reason']
    report = A.explain(passage, question, result)
    assert '## Unknown word' in report and 'Nothing was guessed about its meaning' in report
    # A known question word is still read and answered; a statement with a new name is still a statement.
    assert A.answer(passage, '유진에 따르면, 누가 준서를 도왔나?', model)['answers'] == [['하늘']]
    assert R.read('누구가 준서를 도왔다.', model)['status'] == 'complete'
    assert R.read('누구가 준서를 도왔다.', model)['unknown_words'] == []


def test_models_built_before_sentence_kinds_still_read():
    model = R.build(training())
    del model['tables']['closes'], model['tables']['head_in']
    assert A.answer('하늘이 준서를 도왔다.', '누가 준서를 도왔나?', model)['answers'] == [['하늘']]


def test_unknown_word_is_asked_about_taught_used_and_forgotten():
    from experiments.graph_weighted_acquisition import learn as LN
    model = R.build(training())
    frozen = json.dumps(model, ensure_ascii=False, sort_keys=True)
    memory = LN.new_memory()
    passage = '유진에 따르면, 하늘이 준서를 도왔다. 보라에 따르면, 소은이 준서를 도왔다.'
    question = '누구에 따르면, 소은이 준서를 도왔나?'
    held = A.answer(passage, question, model, memory)
    assert held['status'] == 'hold' and held['unknown_words'] == ['누구']
    assert len(held['proposals']) == 1 and held['proposals'][0]['meaning'] == {'project': True, 'type': 'person'}
    assert held['proposals'][0]['ask'].startswith('Is "누구" a word that asks for a person, like "누가"')
    assert memory['entries'] == [] and 'Question to put to the user' in A.explain(passage, question, held)
    entry = LN.teach(memory, model, '누구', held['proposals'][0]['meaning'], 'owner', '2026-11-19', question)
    assert entry['status'] == 'provisional'
    told = A.answer(passage, question, model, memory)
    assert told['status'] == 'answered' and told['answers'] == [['보라']] and told['verified'] is False
    assert told['told_words'] == [{'word': '누구', 'status': 'provisional', 'confirmed_by': ['owner']}]
    report = A.explain(passage, question, told)
    assert 'uses words told in conversation' in report.splitlines()[0] and '"누구": provisional, confirmed by owner' in report
    # The word works with a connector it was never shown with; the reading says what it leaned on.
    other = A.answer(passage, '유진에 따르면, 누구가 준서를 도왔나?', model, memory)
    assert other['answers'] == [['하늘']] and any('never seen after that kind of word' in x for x in other['raw_text_variants'])
    # The model and the lessons are untouched; without the memory nothing has changed.
    assert json.dumps(model, ensure_ascii=False, sort_keys=True) == frozen
    assert A.answer(passage, question, model)['status'] == 'hold'
    # Forgetting returns the questions that relied on the word, and the reader is back where it was.
    removed = LN.forget(memory, '누구')
    assert removed[0]['uses'] == [question, '유진에 따르면, 누구가 준서를 도왔나?']
    assert A.answer(passage, question, model, memory)['status'] == 'hold'


def test_stored_words_are_promoted_disputed_and_never_override_lessons():
    from experiments.graph_weighted_acquisition import learn as LN
    model = R.build(training())
    memory = LN.new_memory()
    asks = {'project': True, 'type': 'person'}
    for n, who in enumerate(['a', 'a', 'b', 'c']):
        entry = LN.teach(memory, model, '누구', asks, who, 'day%d' % n)
    assert entry['status'] == 'confirmed' and [c['by'] for c in entry['confirmations']] == ['a', 'b', 'c']
    for bad in ('누가', '도왔다', '이'):
        try:
            LN.teach(memory, model, bad, asks, 'a', 'now')
            raise AssertionError('lessons were overridden by ' + bad)
        except ValueError:
            pass
    try:
        LN.teach(memory, model, '뭐', {'project': True, 'type': 'colour'}, 'a', 'now')
        raise AssertionError('a meaning the lessons do not have was accepted')
    except ValueError:
        pass
    # Two people disagree about a word: it is put in dispute and not used.
    lessons = []
    for n, (who, value) in enumerate([('푸른별', '7%'), ('노란달', '4%'), ('하얀숲', '12%')]):
        lessons += [_fact('s%d' % n, 'say', who, '세율', value, '이다.'), _fact('a%d' % n, 'ask', who, '세율', '얼마', '인가?'),
                    _fact('c%d' % n, 'check', who, '세율', value, 'check')]
    rates = R.build(lessons)
    store = LN.new_memory()
    LN.teach(store, rates, '몇푼', {'project': True, 'type': 'amount'}, 'a', 'now')
    text, ask = '은빛강의 세율은 15%이다.', '은빛강의 세율은 몇푼인가?'
    assert A.answer(text, ask, rates, store)['answers'] == [['15%']]
    disputed = LN.teach(store, rates, '몇푼', {'project': False, 'type': 'check'}, 'b', 'later')
    assert disputed['status'] == 'disputed' and disputed['disputes'][0]['by'] == 'b'
    assert A.answer(text, ask, rates, store)['status'] == 'hold'
    passage = '하늘이 준서를 도왔다.'
    # Told that a word is a name, the reader stops reporting it as unknown.
    memory2 = LN.new_memory()
    assert A.answer(passage, '누구가 준서를 도왔나?', model, memory2)['unknown_words'] == ['누구']
    LN.mark_name(memory2, '누구', 'owner', 'now')
    after = A.answer(passage, '누구가 준서를 도왔나?', model, memory2)
    assert after['status'] == 'hold' and after['unknown_words'] == []


def test_sentences_are_written_from_counts_and_read_back():
    from experiments.graph_weighted_acquisition import write as WR
    model = R.build(training())
    helped, not_helped = [['action', 'help'], ['polarity', 'positive']], [['action', 'help'], ['polarity', 'negative']]
    # Names the lessons never used; the connector follows the sound each name ends in.
    said = WR.say(model, 'event', helped, [('actor', '하늘'), ('object', '준서')])
    assert said['status'] == 'said' and said['text'] == '하늘이 준서를 도왔다.'
    assert WR.say(model, 'event', not_helped, [('source', '유진'), ('actor', '소라'), ('object', '지안')])['text'] \
        == '유진에 따르면, 소라가 지안을 돕지 않았다.'
    assert WR.say(model, 'event', helped, [('actor', WR.ASK), ('object', '준서')], 'asks')['text'] == '누가 준서를 도왔나?'
    # The reader, on its own, reads the sentence as the meaning that was asked for.
    back = R.read(said['text'], model)
    assert back['status'] == 'complete'
    assert WR._meanings(back['graphs'][0], said['text']) == [('event', WR.key(helped), (('actor', '하늘'), ('object', '준서')))]
    assert [s['piece'] for s in said['steps']][:2] == ['도왔다', 'actor object HEAD'] and all(s['count'] > 0 for s in said['steps'])
    # A shape or a meaning the lessons never showed is not improvised.
    assert WR.say(model, 'event', helped, [('actor', '하늘')])['status'] == 'cannot say'
    assert WR.say(model, 'event', [['action', 'greet'], ['polarity', 'positive']],
                  [('actor', '하늘'), ('object', '준서')])['status'] == 'cannot say'
    old = R.build(training())
    del old['tables']['order']
    assert WR.say(old, 'event', helped, [('actor', '하늘'), ('object', '준서')])['status'] == 'cannot say'


def test_answers_come_with_a_full_sentence():
    model = R.build(training())
    passage = '유진에 따르면, 하늘이 준서를 돕지 않았다. 유진에 따르면, 소은이 준서를 도왔다.'
    question = '유진에 따르면, 누가 준서를 돕지 않았나?'
    result = A.answer(passage, question, model)
    assert result['answers'] == [['하늘']]
    assert [s['text'] for s in result['sentences']] == ['유진에 따르면, 하늘이 준서를 돕지 않았다.']
    report = A.explain(passage, question, result)
    assert '## Answer as a sentence' in report and '> 유진에 따르면, 하늘이 준서를 돕지 않았다.' in report
    several = A.answer('하늘이 준서를 도왔다. 소은이 준서를 도왔다.', '누가 준서를 도왔나?', model)
    assert sorted(s['text'] for s in several['sentences']) == ['소은이 준서를 도왔다.', '하늘이 준서를 도왔다.']
    # A loosely matched name is written the way the passage has it.
    loose = A.answer('하늘이 준서를 도왔다.', '누가 옆집 준서를 도왔나?', _giving(model))
    assert [s['text'] for s in loose['sentences']] == ['하늘이 준서를 도왔다.']
    assert A.answer('하늘이 준서를 도왔다.', '누가 준서를 돕지 않았나?', model)['sentences'] == []


def _field_free_lessons():
    out = []
    people = ['푸른별', '노란달', '하얀숲', '붉은꽃', '초록산', '은빛강']
    for n, word in enumerate(['빛깔', '무게', '나이']):
        mark = '은' if (ord(word[-1]) - 0xAC00) % 28 else '는'
        for k in range(4):
            who, value = people[(n * 2 + k) % 6], ['쪽빛', '3근', '9살', '잿빛'][(n + k) % 4]
            for kind, last, close in (('say', value, '이다.'), ('ask', '무엇', '인가?')):
                ex = _fact('%s%d%d%s' % (word, n, k, kind), kind, who, word, last, close)
                ex['text'] = ex['text'].replace(word + '은', word + mark)
                out.append(ex)
        check = _fact('c%d' % n, 'check', people[n], word, '쪽빛', 'check')
        check['text'] = check['text'].replace(word + '은', word + mark).replace('쪽빛가', '쪽빛이')
        out.append(check)
    return out


def test_three_packs_make_one_system_and_the_field_is_swapped_without_lessons():
    from experiments.graph_weighted_acquisition import pack as PK
    language = PK.language_pack(_field_free_lessons())
    assert not language['skipped']
    slot = {'type': 'relation', 'attribute': 'kind', 'subject_role': 'subject', 'value_role': 'amount'}
    source = {'url': 'made up', 'as_of': 'today', 'scope': 'test'}
    shop_words = {'schema': PK.WORDS, 'field': 'shop', 'slot': slot,
                  'properties': [{'word': '가격', 'means': '가격', 'also': ['값']}, {'word': '재고', 'means': '재고', 'also': []}],
                  'names': [{'name': '사과', 'also': ['능금']}]}
    shop_facts = {'schema': PK.FACTS, 'facts': [
        {'id': 'S1', 'subject': '사과', 'property': '가격', 'value': '천원', 'source': source},
        {'id': 'S2', 'subject': '배', 'property': '재고', 'value': '열개', 'source': source},
        {'id': 'S3', 'subject': '배', 'property': '원산지', 'value': '나주', 'source': source}]}
    zoo_words = {'schema': PK.WORDS, 'field': 'zoo', 'slot': slot,
                 'properties': [{'word': '먹이', 'means': '먹이', 'also': []}], 'names': []}
    zoo_facts = {'schema': PK.FACTS, 'facts': [{'id': 'Z1', 'subject': '판다', 'property': '먹이', 'value': '대나무',
                                                'source': source}]}
    lesson_text = ' '.join(x['text'] for x in _field_free_lessons())
    assert not [w for w in ('가격', '값', '재고', '먹이', '사과', '판다') if w in lesson_text]
    shop, zoo = PK.load(language, shop_words, shop_facts), PK.load(language, zoo_words, zoo_facts)
    # The facts were written out by the system itself, with the right connector for each new word.
    assert shop['text'] == '사과의 가격은 천원이다. 배의 재고는 열개이다.'
    assert shop['unusable'] == [{'fact': 'S3', 'reason': 'property "원산지" is not in the word pack'}]
    assert 'head' in language['tables'] and '가격' not in language['tables']['head']
    asked = PK.ask(shop, '사과의 가격은 무엇인가?')
    assert asked['answers'] == [['천원']] and [f['id'] for f in asked['facts']] == ['S1']
    assert [s['text'] for s in asked['sentences']] == ['사과의 가격은 천원이다.']
    assert '## Sources' in PK.tell(shop, '사과의 가격은 무엇인가?', asked)
    # Another word for the property and another name for the subject, both from the word pack.
    assert PK.ask(shop, '사과의 값은 무엇인가?')['answers'] == [['천원']]
    other = PK.ask(shop, '능금의 가격은 무엇인가?')
    assert other['answers'] == [['천원']] and other['other_names'] == ['"능금" is another name for "사과" (word pack)']
    # A yes/no check works on a field word that no lesson ever showed.
    assert PK.ask(shop, '사과의 가격은 천원이 맞나?')['claim'] == {'claimed': '천원', 'holds': True}
    wrong = PK.ask(shop, '사과의 가격은 만원이 맞나?')
    assert wrong['claim'] == {'claimed': '만원', 'holds': False} and wrong['answers'] == [['천원']]
    # Each field answers its own questions and holds on the other's.
    assert PK.ask(zoo, '판다의 먹이는 무엇인가?')['answers'] == [['대나무']]
    assert PK.ask(zoo, '사과의 가격은 무엇인가?')['status'] == 'hold'
    assert PK.ask(shop, '판다의 먹이는 무엇인가?')['status'] == 'hold'
    # A field word may not take over a word of the language pack.
    clash = dict(shop_words, properties=[{'word': '빛깔', 'means': '빛깔', 'also': []}])
    try:
        PK.with_words(language, clash)
        raise AssertionError('a language word was overridden')
    except ValueError:
        pass


def test_how_the_system_reads_is_data_in_the_pack_and_editing_it_changes_behaviour():
    model = R.build(training())
    shipped = R.default_recipe()
    assert model['recipe'] == shipped['recipe'] and model['conventions'] == shipped['conventions']
    passage = '유진에 따르면, 하늘이 준서를 도왔다.'

    def edited(change):
        copy_ = json.loads(json.dumps(model))
        change(copy_)
        return copy_

    # 1. Which counts decide a role: drop "the piece before it" from the recipe.
    terms = lambda m: {t['what'] for t in R.read(passage, m)['readings'][0]['terms']}
    assert 'role from the piece before it' in terms(model)
    fewer = edited(lambda m: m['recipe']['argument'].update(context=m['recipe']['argument']['context'][:1]))
    assert 'role from the piece before it' not in terms(fewer) and R.read(passage, fewer)['status'] == 'complete'
    # 2. How names may be compared: switch off "leading words".
    loose = '유진에 따르면, 누가 옆집 준서를 도왔나?'
    # (With the convention of before 2026-11-23, where an answer that ignores words is given, flagged.)
    giving = edited(lambda m: m['conventions'].update(partial_answers='give'))
    assert A.answer(passage, loose, model)['status'] == 'hold'
    assert A.answer(passage, loose, giving)['answers'] == [['하늘']]
    strict = edited(lambda m: m['conventions'].update(
        partial_answers='give', name_matching=[r for r in m['conventions']['name_matching'] if r['rule'] != 'leading_words']))
    assert A.answer(passage, loose, strict)['status'] == 'hold'
    # 3. What a sentence must do: without the sentence rules, an unknown question word is a name again.
    unknown = '누구에 따르면, 하늘이 준서를 도왔나?'
    assert R.read(unknown, model)['unknown_words']
    blind = edited(lambda m: m['recipe'].update(sentence=[]))
    assert R.read(unknown, blind)['status'] == 'complete' and not R.read(unknown, blind)['graphs'][0]['project']
    # 4. A pack built before recipes were data still reads, with the shipped recipe.
    older = edited(lambda m: (m.pop('recipe'), m.pop('conventions')))
    assert A.answer(passage, '유진에 따르면, 누가 준서를 도왔나?', older)['answers'] == [['하늘']]


def test_the_marker_for_a_yes_no_check_is_named_in_the_pack():
    lessons = []
    for n, (who, value) in enumerate([('푸른별', '7%'), ('노란달', '4%'), ('하얀숲', '12%')]):
        lessons += [_fact('s%d' % n, 'say', who, '세율', value, '이다.'), _fact('a%d' % n, 'ask', who, '세율', '얼마', '인가?'),
                    _fact('c%d' % n, 'check', who, '세율', value, 'check')]
    model = R.build(lessons)
    text, ask = '은빛강의 세율은 15%이다.', '은빛강의 세율은 3%가 맞나?'
    assert A.answer(text, ask, model)['claim'] == {'claimed': '3%', 'holds': False}
    renamed = json.loads(json.dumps(model))
    renamed['conventions']['claim_predicate'] = 'something else'
    assert A.answer(text, ask, renamed)['status'] == 'hold'
