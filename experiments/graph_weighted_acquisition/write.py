"""Write a sentence from a meaning, using the reader's counts backwards.

A meaning is one head (its type and fixed attributes) with named arguments. The writer
picks, from what the lessons showed:

  - the order of the arguments and the head
  - the head word for that meaning in that kind of sentence (stating or asking)
  - the connector after each word: one that marks the role, fits what follows, and
    follows words ending in that sound

Every candidate sentence is then read back by the reader. A sentence is given only if the
reader, on its own, reads it as exactly the meaning that was asked for. Nothing is said
that the system could not itself understand. No text is predicted and nothing is sampled.
"""
import itertools
import json
import math

from . import reader as R

ASK = None


def key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _n(model, table, cue, label):
    return model['tables'].get(table, {}).get(cue, {}).get(label, {}).get('n', 0)


def _meanings(graph, text):
    """Each head of a reading as (type, attributes, [(role, name or ASK)]), for comparison."""
    names = {s: text[slice(*o['copy'])] for s, p, o in graph['edges']
             if p == 'value' and isinstance(o, dict) and 'copy' in o}
    out = []
    for node in graph['nodes']:
        roles = [(p, names.get(o, ASK)) for s, p, o in graph['edges'] if s == node['id'] and isinstance(o, str)]
        if roles:
            literals = sorted([p, o['literal']] for s, p, o in graph['edges']
                              if s == node['id'] and isinstance(o, dict) and 'literal' in o)
            out.append((node['type'], key(literals), tuple(sorted(roles, key=lambda r: (r[0], r[1] or '')))))
    return sorted(out, key=key)


def _head_words(model, entry, does):
    """Head words that carry this meaning, most used first, in sentences that do this."""
    found = []
    for word, row in model['tables'].get('head', {}).items():
        if entry in row and _n(model, 'head_in', word, does):
            found.append((row[entry]['n'], word))
    return [w for _, w in sorted(found, reverse=True)]


def _ask_words(model, kind, role):
    """Fixed words that ask for a thing of this type, preferring ones seen in this role."""
    label = key({'project': True, 'type': kind})
    found = [(_n(model, 'role_surface', word, role), row[label]['n'], word)
             for word, row in model['tables'].get('closed', {}).items() if label in row]
    return [w for seen, _, w in sorted(found, reverse=True) if seen or not any(f[0] for f in found)]


def _connectors(model, before, after, where):
    """Connectors that may stand here, with the counts that speak for each."""
    gaps = model['tables'].get('gap', {}).get(where, {})
    out = []
    for gap in gaps:
        reasons, ok = [], True
        exact = True
        if before:
            seen = _n(model, 'gap_after', before['kind'], gap)
            if not seen:
                # Never seen after this kind of word; allowed only if seen after its type,
                # and only when no connector with an exact count exists for this place.
                seen, exact = _n(model, 'gap_after_type', before['type'], gap), False
            ok &= seen > 0
            reasons.append(('follows a %s' % before['type'], seen))
            if before.get('role'):
                marks = _n(model, 'role_right', gap, before['role'])
                if before['kind'] == 'value':
                    ok &= marks > 0
                    reasons.append(('marks the %s' % before['role'], marks))
            sound = _n(model, 'gap_after_part', R.last_part(before['text']), gap)
            alike = _n(model, 'gap_after_part_class', R.part_class(before['text']), gap)
            reasons.append(('follows a word ending in this sound', sound) if sound else
                           ('follows a word ending in this kind of sound', alike))
        else:
            sound = alike = 1
        if after:
            follows = _n(model, 'kind_after', gap, after['kind'])
            ok &= follows > 0
            reasons.append(('is followed by a %s' % after['type'], follows))
            if after.get('role') and after['kind'] == 'value':
                leads = _n(model, 'role_left', gap, after['role'])
                ok &= leads > 0
                reasons.append(('comes before the %s' % after['role'], leads))
        reasons = [r for r in reasons if r[1] or not r[0].startswith('follows a word ending')]
        if ok:
            out.append({'gap': gap, 'reasons': reasons, 'sound_seen': sound, 'alike_seen': alike, 'exact': exact,
                        'score': sum(math.log(n + 0.5) for _, n in reasons)})
    if any(c['exact'] for c in out):
        out = [c for c in out if c['exact']]
    # A connector seen after this ending sound always beats one that was not.
    if any(c['sound_seen'] for c in out):
        out = [c for c in out if c['sound_seen']]
    elif any(c['alike_seen'] for c in out):
        out = [c for c in out if c['alike_seen']]
    # Equal evidence: the connector the lessons used most, so the same choice is made every time.
    return sorted(out, key=lambda c: (-c['score'], -gaps[c['gap']]['n'], c['gap']))[:3]


def say(model, head_type, attributes, arguments, does='states', limit=200):
    """One sentence for one head. `arguments` is [(role, name)], with name ASK for the thing asked for.

    Returns {'status': 'said', 'text', 'steps', ...} or {'status': 'cannot say', 'reason'}.
    """
    if 'order' not in model['tables']:
        return {'status': 'cannot say', 'reason': 'this model was built before word order was counted'}
    entry = key({'literals': sorted(attributes), 'type': head_type})
    roles = sorted(role for role, _ in arguments)
    orders = model['tables']['order'].get(key([head_type, roles]), {})
    if not orders:
        return {'status': 'cannot say', 'reason': 'no lesson shows a %s with exactly these parts: %s'
                                                  % (head_type, ', '.join(roles))}
    order = json.loads(max(orders, key=lambda o: orders[o]['n']))
    heads = _head_words(model, entry, does)
    if not heads:
        return {'status': 'cannot say', 'reason': 'no head word for this meaning in a sentence that ' + does}
    target = [(head_type, key(sorted(attributes)), tuple(sorted(arguments, key=lambda r: (r[0], r[1] or ''))))]
    by_role = {}
    for role, name in arguments:
        by_role.setdefault(role, []).append(name)
    tried = 0
    for head in heads:
        slots, options = [], []
        for item in order:
            if item == 'HEAD':
                slots.append([{'kind': 'head', 'type': head_type, 'text': head}])
                continue
            name = by_role[item].pop(0) if by_role[item] else None
            by_role[item].append(name)
            if name is ASK:
                kinds = sorted({json.loads(m)['type'] for row in model['tables'].get('closed', {}).values() for m in row
                                if json.loads(m).get('project')})
                words = [w for k in kinds for w in _ask_words(model, k, item)]
                slots.append([{'kind': 'closed', 'type': _closed_type(model, w), 'text': w, 'role': item} for w in words])
            else:
                slots.append([{'kind': 'value', 'type': _value_type(model, item), 'text': name, 'role': item}])
        if any(not s for s in slots):
            continue
        for mentions in itertools.product(*slots):
            gaps = [_connectors(model, None, mentions[0], 'start')]
            gaps += [_connectors(model, a, b, 'mid') for a, b in zip(mentions, mentions[1:])]
            gaps.append([c for c in _connectors(model, mentions[-1], None, 'end')
                         if _n(model, 'closes', c['gap'], does)])
            if any(not g for g in gaps):
                continue
            for choice in itertools.product(*gaps):
                tried += 1
                if tried > limit:
                    return {'status': 'cannot say', 'reason': 'too many candidate sentences'}
                text = ''.join(c['gap'] + (m['text'] if i < len(mentions) else '')
                               for i, (c, m) in enumerate(zip(choice, list(mentions) + [{'text': ''}])))
                back = R.read(text, model)
                if back['status'] != 'complete' or back.get('ignored'):
                    continue
                if _meanings(back['graphs'][0], text) != target:
                    continue
                steps = [{'piece': head, 'why': 'the head word for this meaning in a sentence that ' + does,
                          'count': _n(model, 'head', head, entry)},
                         {'piece': ' '.join(order), 'why': 'the order such sentences were written in',
                          'count': orders[key(order)]['n']}]
                for i, c in enumerate(choice):
                    if c['gap'].strip():
                        after = mentions[i - 1]['text'] if i else '(start)'
                        steps.append({'piece': c['gap'], 'why': 'after "%s": %s' % (
                            after, '; '.join('%s (%d)' % r for r in c['reasons'])), 'count': min(n for _, n in c['reasons'])})
                unsure = [c['gap'].strip() for i, c in enumerate(choice)
                          if i and not c['sound_seen'] and not c['alike_seen'] and c['gap'].strip()]
                return {'status': 'said', 'text': text, 'steps': steps, 'tried': tried, 'read_back': back['reason'],
                        'form_not_confirmed': unsure}
    return {'status': 'cannot say', 'reason': 'no sentence built from known pieces reads back as this meaning'}


def _value_type(model, role):
    """The node type lessons gave to named values (the commonest one)."""
    totals = {}
    for row in model['tables'].get('value_type', {}).values():
        for kind, cell in row.items():
            totals[kind] = totals.get(kind, 0) + cell['n']
    return max(totals, key=totals.get) if totals else 'thing'


def _closed_type(model, word):
    row = model['tables'].get('closed', {}).get(word, {})
    return json.loads(max(row, key=lambda m: row[m]['n']))['type'] if row else 'thing'


def answer_sentences(model, query, question, answers, notes=()):
    claim = R.recipe_of(model)[1]['claim_predicate']
    """Each answer as a full statement: the question's own meaning with the answer put in.

    Where a name in the question was matched loosely, the passage's own name is used.
    """
    matched = {n['asked']: n['matched'] for n in notes if n.get('matched')}
    names = {s: question[slice(*o['copy'])] for s, p, o in query['edges']
             if p == 'value' and isinstance(o, dict) and 'copy' in o}
    names = {s: matched.get(name, name) for s, name in names.items()}
    out = []
    for row in answers:
        given = dict(zip(query['project'], row))
        for node in query['nodes']:
            roles = [(p, given.get(o, names.get(o))) for s, p, o in query['edges']
                     if s == node['id'] and isinstance(o, str) and p != claim]
            if not roles or any(name is None for _, name in roles):
                continue
            literals = [[p, o['literal']] for s, p, o in query['edges']
                        if s == node['id'] and isinstance(o, dict) and 'literal' in o]
            out.append(dict(say(model, node['type'], literals, roles), answer=row))
    return out
