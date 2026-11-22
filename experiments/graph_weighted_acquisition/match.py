"""Direct question-to-passage graph matching.

The question graph is a pattern: every node is an unknown, every edge a
condition. A match assigns each question node to a passage node so that all
conditions hold. The asked-for node's name in the passage is the answer.

Plain backtracking over typed nodes; no scoring, no learning, no generation.
It refuses to answer when a passage event fits every stated condition but lacks
the asked-for role, so a known actor is never presented as the only one.
"""


def _value(graph, text, node):
    found = {text[slice(*o['copy'])] for s, p, o in graph['edges']
             if s == node and p == 'value' and isinstance(o, dict) and 'copy' in o}
    return found


def _squeeze(name):
    return ''.join(name.split())


def name_fit(asked, names, level, aliases=None):
    """Does a name in the question fit a name in the passage, and what was overlooked?

    level 0  the same text
    level 1  the same text once blank space is removed
    level 2  the question's name ends with the passage's name after a space: words in front
             of it are treated as a description of the same thing and are reported
    """
    if asked in names:
        return {'level': 0}
    if aliases and aliases.get(asked) in names:
        # Another name for the same thing, stated in the word pack.
        return {'level': 0, 'asked': asked, 'matched': aliases[asked], 'alias': True}
    if level >= 1:
        for name in sorted(names):
            if _squeeze(asked) == _squeeze(name):
                return {'level': 1, 'asked': asked, 'matched': name}
    if level >= 2:
        for name in sorted(names, key=len, reverse=True):
            for cut in range(1, len(asked)):
                if asked[cut - 1].isspace() and _squeeze(asked[cut:]) == _squeeze(name):
                    return {'level': 2, 'asked': asked, 'matched': name, 'ignored': asked[:cut].strip()}
    return None


def _holds(edge, binding, qtext, facts, values, level=0, aliases=None):
    s, p, o = edge
    if s not in binding:
        return None
    if isinstance(o, str):
        return None if o not in binding else (binding[s], p, ('node', binding[o])) in facts
    if 'literal' in o:
        return (binding[s], p, ('literal', o['literal'])) in facts
    return name_fit(qtext[slice(*o['copy'])], values[binding[s]], level, aliases) is not None


def _search(nodes, edges, qtext, passage, facts, values, limit, level=0, aliases=None):
    """All assignments of `nodes` to passage nodes that satisfy `edges`."""
    order = sorted(nodes, key=lambda n: -sum(1 for e in edges if e[0] == n['id'] or e[2] == n['id']))
    out, steps = [], 0

    def extend(i, binding):
        nonlocal steps
        if i == len(order):
            out.append(dict(binding))
            return True
        for candidate in passage['nodes']:
            steps += 1
            if steps > limit:
                return False
            if candidate['type'] != order[i]['type']:
                continue
            binding[order[i]['id']] = candidate['id']
            if all(_holds(e, binding, qtext, facts, values, level, aliases) is not False for e in edges):
                if not extend(i + 1, binding):
                    return False
            del binding[order[i]['id']]
        return True

    complete = extend(0, {})
    return out, complete


def match(pgraph, ptext, qgraph, qtext, limit=200000, max_level=2, aliases=None, rules=None):
    """Answer tuples with the passage facts that ground them, or a reason for none."""
    if rules is not None:
        # The pack's `name_matching` list says which ways of comparing names are in use.
        names = [r['rule'] for r in rules]
        max_level = 2 if 'leading_words' in names else 1 if 'without_spaces' in names else 0
        aliases = aliases if 'other_name' in names else None
    asked = list(qgraph['project'])
    if not asked:
        return {'status': 'hold', 'reason': 'the question asks for nothing'}
    facts, grounds = set(), {}
    for (s, p, o), spans in zip(pgraph['edges'], pgraph['edge_spans']):
        if p == 'value':
            continue
        fact = (s, p, ('node', o) if isinstance(o, str) else ('literal', o['literal']))
        facts.add(fact)
        grounds[fact] = spans
    values = {n['id']: _value(pgraph, ptext, n['id']) for n in pgraph['nodes']}
    # Names are compared exactly first. Looser comparison is tried only when that finds nothing.
    for level in range(max_level + 1):
        full, done = _search(qgraph['nodes'], qgraph['edges'], qtext, pgraph, facts, values, limit, level, aliases)
        if not done:
            return {'status': 'hold', 'reason': 'search bound reached'}
        if full:
            break
    # Every passage event that fits the stated conditions must also supply the asked-for role.
    core_nodes = [n for n in qgraph['nodes'] if n['id'] not in asked]
    core_edges = [e for e in qgraph['edges'] if e[0] not in asked and e[2] not in asked]
    if core_nodes:
        core, done = _search(core_nodes, core_edges, qtext, pgraph, facts, values, limit, level, aliases)
        if not done:
            return {'status': 'hold', 'reason': 'search bound reached'}
        for partial in core:
            if not any(all(m[k] == v for k, v in partial.items()) for m in full):
                return {'status': 'hold',
                        'reason': 'a passage event fits the question but does not say who or what was asked for'}
    if not full:
        return {'status': 'none', 'reason': 'nothing in the passage fits every condition of the question'}
    value_spans = {}
    for (s_, p_, o_), spans in zip(pgraph['edges'], pgraph['edge_spans']):
        if p_ == 'value':
            value_spans.setdefault(s_, []).extend(spans)
    answers, notes = {}, []
    for m in full:
        names = []
        for node in asked:
            found = values[m[node]]
            if len(found) != 1:
                return {'status': 'hold', 'reason': 'the matched thing has no single name in the passage'}
            names.append(next(iter(found)))
        used = []
        for s_, p_, o_ in qgraph['edges']:
            if p_ == 'value':
                # A name stated in the question: the passage text carrying that name.
                spans = value_spans.get(m[s_], [])
                fit = name_fit(qtext[slice(*o_['copy'])], values[m[s_]], level, aliases)
                if fit and (fit['level'] or fit.get('alias')) and fit not in notes:
                    notes.append(fit)
            else:
                fact = (m[s_], p_, ('node', m[o_]) if isinstance(o_, str) else ('literal', o_['literal']))
                spans = grounds[fact]
            used.append({'condition': [s_, p_, o_], 'spans': spans, 'text': [ptext[a:b] for a, b in spans]})
        for node in asked:
            spans = value_spans.get(m[node], [])
            used.append({'condition': [node, 'answer name', None], 'spans': spans,
                         'text': [ptext[a:b] for a, b in spans]})
        if any(not fact['spans'] for fact in used):
            return {'status': 'hold', 'reason': 'a matched condition has no passage text behind it'}
        # Every separate place in the passage that yields this answer is kept.
        proofs = answers.setdefault(tuple(names), [])
        if used not in proofs:
            proofs.append(used)
    return {'status': 'answered', 'reason': 'every condition of the question holds in the passage',
            'answers': sorted(list(t) for t in answers), 'relaxed': level, 'notes': notes,
            'proofs': [{'answer': list(names), 'facts': facts_}
                       for names in sorted(answers) for facts_ in answers[names]]}
