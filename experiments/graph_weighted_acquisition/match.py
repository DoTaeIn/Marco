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


def _through(a, p, b, named, facts, values):
    """"X의 P의 Q": the question puts one relation (b) in a role (p) of another (a). The knowledge states the
    two apart: b with its value in one sentence, and something of that name in the role of a in another.
    The join is that name. b's value is the one part b has that the question does not name; with no such
    part, or more than one, there is no join. Returns (the node in a's role, b's role, b's node) or None."""
    extra = sorted((role, o[1]) for s, role, o in facts if s == b and o[0] == 'node' and role not in named)
    if len(extra) != 1:
        return None
    role, y = extra[0]
    for s, q, o in sorted(facts, key=str):
        if s == a and q == p and o[0] == 'node' and values[o[1]] and values[o[1]] == values[y]:
            return o[1], role, y
    return None


def _holds(edge, binding, qtext, facts, values, level=0, aliases=None, joins=None):
    s, p, o = edge
    if s not in binding:
        return None
    if isinstance(o, str):
        if o not in binding:
            return None
        if (binding[s], p, ('node', binding[o])) in facts:
            return True
        return joins is not None and o in joins and _through(binding[s], p, binding[o], joins[o], facts, values) is not None
    if 'literal' in o:
        return (binding[s], p, ('literal', o['literal'])) in facts
    return name_fit(qtext[slice(*o['copy'])], values[binding[s]], level, aliases) is not None


def _search(nodes, edges, qtext, passage, facts, values, limit, level=0, aliases=None, joins=None):
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
            if all(_holds(e, binding, qtext, facts, values, level, aliases, joins) is not False for e in edges):
                if not extend(i + 1, binding):
                    return False
            del binding[order[i]['id']]
        return True

    complete = extend(0, {})
    return out, complete


def _one_name_many_places(qgraph):
    """A name the question writes once for two heads ("X는 P가 V이면 Q가 얼마야?") is, for matching, the
    thing so named at each of the two places: the passage may well have written the name twice.
    Returns the graph with one node per place, and which original node each new one stands for."""
    named = {s for s, p, o in qgraph['edges'] if p == 'value' and isinstance(o, dict) and 'copy' in o}
    seen, back, nodes = {}, {}, list(qgraph['nodes'])
    edges, spans = [list(e) for e in qgraph['edges']], list(qgraph['edge_spans'])
    by_id = {n['id']: n for n in qgraph['nodes']}
    for i, (s, p, o) in enumerate(list(edges)):
        if not isinstance(o, str) or o not in named or o in qgraph['project']:
            continue
        seen[o] = seen.get(o, 0) + 1
        if seen[o] == 1:
            continue
        new = '%s~%d' % (o, seen[o])
        back[new] = o
        nodes.append(dict(by_id[o], id=new))
        edges[i] = [s, p, new]
        for (s2, p2, o2), sp in zip(qgraph['edges'], qgraph['edge_spans']):
            if s2 == o and p2 == 'value':
                edges.append([new, p2, o2])
                spans.append(sp)
    return (dict(qgraph, nodes=nodes, edges=edges, edge_spans=spans), back) if back else (qgraph, back)


def _more_than_asked(m, qgraph, facts, joins):
    """Parts the matched facts have and the question does not name: {(passage head, role)}. The one part a
    joined head supplies is what the join is made of and is not counted."""
    more = set()
    for q in {s for s, p, o in qgraph['edges'] if isinstance(o, str)}:
        if q not in m:
            continue
        asked_parts = {p for s, p, o in qgraph['edges'] if s == q and isinstance(o, str)}
        here = {(m[q], p) for s, p, o in facts if s == m[q] and o[0] == 'node' and p not in asked_parts}
        joined = joins is not None and q in joins and any(
            s2 in m and o2 == q and (m[s2], p2, ('node', m[q])) not in facts for s2, p2, o2 in qgraph['edges'])
        more |= set() if joined and len(here) == 1 else here
    return more


def match(pgraph, ptext, qgraph, qtext, limit=200000, max_level=2, aliases=None, rules=None, unasked_parts=None,
          name_joins=None):
    """Answer tuples with the passage facts that ground them, or a reason for none."""
    if rules is not None:
        # The pack's `name_matching` list says which ways of comparing names are in use.
        names = [r['rule'] for r in rules]
        max_level = 2 if 'leading_words' in names else 1 if 'without_spaces' in names else 0
        aliases = aliases if 'other_name' in names else None
    qgraph, back = _one_name_many_places(qgraph)
    set_aside = 0
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
    # Heads of the question that stand in a role of another head, with the roles the question names for them.
    joins = None
    if name_joins == 'value':
        q_heads = {s for s, p, o in qgraph['edges'] if isinstance(o, dict) and 'literal' in o}
        joins = {o: {p2 for s2, p2, o2 in qgraph['edges'] if s2 == o and isinstance(o2, str)}
                 for s, p, o in qgraph['edges'] if isinstance(o, str) and o in q_heads}
    # Names are compared exactly first. Looser comparison is tried only when that finds nothing.
    for level in range(max_level + 1):
        full, done = _search(qgraph['nodes'], qgraph['edges'], qtext, pgraph, facts, values, limit, level, aliases, joins)
        if not done:
            return {'status': 'hold', 'reason': 'search bound reached'}
        if full:
            break
    if unasked_parts == 'block' and full:
        # What the knowledge states with a circumstance, a time, a condition or a denial is not what it
        # states without one. A fact fits only if the question names every part the fact has.
        kept, extra = [], set()
        for m in full:
            more = _more_than_asked(m, qgraph, facts, joins)
            if more:
                extra |= more
            else:
                kept.append(m)
        if not kept:
            anchor = {n['id']: n.get('anchor') for n in pgraph['nodes']}
            parts = sorted({'%s of "%s"' % (p, ptext[slice(*anchor[n])]) for n, p in extra if anchor.get(n)})
            return {'status': 'none', 'reason': 'the knowledge has this only together with a part the question '
                                                 'does not state: ' + ', '.join(parts), 'unasked_parts': parts}
        set_aside = len(full) - len(kept)
        full = kept
    # Every passage event that fits the stated conditions must also supply the asked-for role.
    core_nodes = [n for n in qgraph['nodes'] if n['id'] not in asked]
    core_edges = [e for e in qgraph['edges'] if e[0] not in asked and e[2] not in asked]
    if core_nodes:
        core, done = _search(core_nodes, core_edges, qtext, pgraph, facts, values, limit, level, aliases, joins)
        if not done:
            return {'status': 'hold', 'reason': 'search bound reached'}
        if unasked_parts == 'block':
            # The same holds here: a fact that has a part the question does not state is not an event that
            # fits the question. (Without this, a plain fact and a weekend fact of the same thing held the
            # plain question: the weekend one "fitted and did not say what was asked for".)
            core = [m for m in core if not _more_than_asked(m, qgraph, facts, joins)]
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
    answers, notes, joined_by = {}, [], set()
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
                if fact in grounds:
                    spans = grounds[fact]
                else:
                    # Joined through a name: the two sentences that carry it.
                    x, role, y = _through(m[s_], p_, m[o_], joins[o_], facts, values)
                    spans = grounds[(m[o_], role, ('node', y))] + grounds[(m[s_], p_, ('node', x))]
                    joined_by.add(next(iter(values[y])))
            used.append({'condition': [back.get(s_, s_), p_, back.get(o_, o_) if isinstance(o_, str) else o_],
                         'spans': spans, 'text': [ptext[a:b] for a, b in spans]})
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
            **({'as_matched': qgraph} if back else {}), **({'joined_by': sorted(joined_by)} if joined_by else {}),
            **({'set_aside': set_aside} if set_aside else {}),
            'proofs': [{'answer': list(names), 'facts': facts_}
                       for names in sorted(answers) for facts_ in answers[names]]}
