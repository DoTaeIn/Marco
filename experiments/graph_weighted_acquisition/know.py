"""Structured knowledge, first stage: look-up, joins and claim checks over typed statements.

Input is structure only (a word pack, a fact pack and a question graph); no text is read here.

  load    checks the two packs and keeps what this stage can use; everything else is listed
  ask     infers a result from the loaded knowledge
  check   a second, deliberately naive implementation that re-reads the raw packs
  final   the reported status: the inferred result judged by the check
  answer  the four together

What this stage does not do, it refuses out loud. A statement with a validity period, a
condition or a succession, any rule, and any change record are listed as not usable, and a
question that touches them gets `out_of_scope`; a qualifier is never dropped to make a fact.
A statement stated both ways, or two values for a single-valued relation, gives `conflict`.

Statuses a result can end with here: answered, no_knowledge, ambiguous_entity, conflict,
out_of_scope, limit_exceeded, unverified, verification_failed.
"""
from fractions import Fraction
from itertools import product

WORDS = 'graph-field-words-v2'
FACTS = 'graph-field-facts-v2'
QUESTION = 'graph-question-v1'
LATER = ('valid', 'where', 'supersedes')            # statement fields of later stages
LIMITS = {'search_steps': 200000, 'enumeration': 1000000}
EVERYTHING = (None, None)


def _is_var(term):
    return isinstance(term, str) and term.startswith('?')


def _touches(pattern, ground, key):
    """Could this pattern read knowledge kept under `key` = (subject or None, relation or None)?"""
    s, p = key
    return p in (None, pattern[1]) and (s is None or pattern[0] not in ground or ground[pattern[0]] == s)


# ---------------------------------------------------------------- loading

def _value(o, relation, things, units):
    """A value in one comparable form, or ValueError saying what is wrong with it."""
    kind = relation['value']
    if kind == 'truth':
        if o is not None:
            raise ValueError('a truth relation takes no value, only "holds"')
        return ('truth',)
    if not isinstance(o, dict):
        raise ValueError('the value must be an object')
    if kind == 'quantity':
        if set(o) != {'n', 'unit'}:
            raise ValueError('a quantity needs exactly "n" and "unit"')
        if o['unit'] not in units:
            raise ValueError('unit "%s" is not declared in the word pack' % o['unit'])
        base, per = units[o['unit']]
        return ('quantity', Fraction(o['n']) / per, base)
    if set(o) != {kind}:
        raise ValueError('a %s value needs exactly "%s"' % (kind, kind))
    if kind == 'thing' and o['thing'] not in things:
        raise ValueError('thing "%s" is not in the word pack' % o['thing'])
    return (kind, o[kind])


def _show(k, value):
    if value[0] == 'thing':
        return {'thing': value[1], 'name': k['things'][value[1]]['names'][0]}
    if value[0] == 'quantity':
        return {'n': str(value[1]), 'unit': value[2]}
    return True if value[0] == 'truth' else {value[0]: value[1]}


def load(words, facts):
    """Check both packs. Nothing is dropped silently: loaded + unusable = records given."""
    if words.get('schema') != WORDS or facts.get('schema') != FACTS:
        raise ValueError('unsupported pack')
    things, names = {}, {}
    for thing in words['things']:
        if thing['id'] in things:
            raise ValueError('thing "%s" is declared twice' % thing['id'])
        things[thing['id']] = thing
        for name in thing['names']:
            names.setdefault(name, []).append(thing['id'])
    relations = {r['p']: r for r in words['relations']}
    units = {u['unit']: (u.get('base', u['unit']), Fraction(u.get('per_base', '1'))) for u in words.get('units', [])}
    statements, unusable, blocked, seen = [], [], [], set()

    def refuse(kind, record, reason, key=None):
        unusable.append({'kind': kind, 'id': record.get('id'), 'reason': reason})
        if key is not None:
            blocked.append({'key': key, 'id': record.get('id'), 'reason': reason})

    for st in facts.get('statements', []):
        relation = relations.get(st.get('p'))
        if not isinstance(st.get('id'), str) or st['id'] in seen:
            refuse('statement', st, 'missing or repeated id')
        elif not st.get('source'):
            refuse('statement', st, 'no source')
        elif relation is None:
            refuse('statement', st, 'relation "%s" is not in the word pack' % st.get('p'))
        elif st.get('s') not in things:
            refuse('statement', st, 'subject "%s" is not in the word pack' % st.get('s'))
        elif not isinstance(st.get('holds', True), bool):
            refuse('statement', st, '"holds" must be true or false')
        elif [f for f in LATER if f in st]:
            # Known knowledge this stage cannot apply: questions about it are refused, never answered without it.
            refuse('statement', st, 'not supported yet: ' + ', '.join(f for f in LATER if f in st), (st['s'], st['p']))
        else:
            try:
                value = _value(st.get('o'), relation, things, units)
            except (ValueError, ZeroDivisionError) as error:
                refuse('statement', st, str(error))
            else:
                statements.append({'id': st['id'], 's': st['s'], 'p': st['p'], 'v': value, 'holds': st.get('holds', True)})
        if isinstance(st.get('id'), str):
            seen.add(st['id'])
    where = {st['id']: (st.get('s'), st.get('p')) for st in facts.get('statements', []) if isinstance(st.get('id'), str)}
    for rule in facts.get('rules', []):
        then = rule.get('then')
        key = (None, then[1]) if isinstance(then, list) and len(then) == 3 and then[1] in relations else EVERYTHING
        refuse('rule', rule, 'rules are not supported yet', key)
    for change in facts.get('changes', []):
        target = next((change[f] for f in ('retracts', 'corrects', 'supersedes') if f in change), None)
        refuse('change', change, 'changes are not supported yet', where.get(target, EVERYTHING))
    by_key, by_p = {}, {}
    for st in statements:
        by_key.setdefault((st['s'], st['p']), []).append(st)
        by_p.setdefault(st['p'], []).append(st)
    conflicts = {}
    for key, group in by_key.items():
        yes = {st['v'] for st in group if st['holds']}
        no = {st['v'] for st in group if not st['holds']}
        if yes & no or (relations[key[1]].get('single') and len(yes) > 1):
            conflicts[key] = sorted(st['id'] for st in group)
    return {'things': things, 'names': names, 'relations': relations, 'units': units, 'statements': statements,
            'by_p': by_p, 'unusable': unusable, 'blocked': blocked, 'conflicts': conflicts,
            'limits': dict(LIMITS, **words.get('limits', {})),
            'counts': {'given': len(facts.get('statements', [])) + len(facts.get('rules', [])) + len(facts.get('changes', [])),
                       'loaded': len(statements), 'unusable': len(unusable)}}


# ---------------------------------------------------------------- inference

def _result(status, reason, **more):
    out = {'status': status, 'reason': reason, 'answers': [], 'claim': None, 'notes': [], 'assumptions': [],
           'candidates': [], 'conflicts': [], 'blocked': []}
    out.update(more)
    return out


def _unify(binding, term, value):
    if not _is_var(term):
        return binding if term == value else None
    if term in binding:
        return binding if binding[term] == value else None
    return dict(binding, **{term: value})


def ask(k, question):
    """Infer a result. Its status is the inferred one; `final` gives the reported one."""
    if question.get('schema') != QUESTION:
        raise ValueError('unsupported question')
    kind, find, patterns = question.get('ask', 'value'), question.get('find', []), question['where']
    later = [f for f in ('given', 'at', 'known_at') if question.get(f)]
    if later or kind not in ('value', 'check'):
        return _result('out_of_scope', 'not supported yet: ' + ', '.join(later or ['ask=%s' % kind]))
    if kind == 'check' and (len(patterns) != 1 or find):
        return _result('out_of_scope', 'a claim check takes one statement and finds nothing')
    binding, notes = {}, []
    for var, name in sorted(question.get('names', {}).items()):
        ids = sorted(k['names'].get(name, []))
        if not ids:
            return _result('no_knowledge', 'nothing is named "%s"' % name)
        if len(ids) > 1:
            return _result('ambiguous_entity', '"%s" names more than one thing' % name,
                           candidates=[{'thing': i, 'name': k['things'][i]['names'][0]} for i in ids])
        binding[var] = ('thing', ids[0])
        if name != k['things'][ids[0]]['names'][0]:
            notes.append('"%s" is another name for "%s"' % (name, k['things'][ids[0]]['names'][0]))
    compiled = []
    for s, p, o in patterns:
        relation = k['relations'].get(p)
        if relation is None:
            return _result('no_knowledge', 'relation "%s" is not in the word pack' % p, notes=notes)
        if not _is_var(s):
            if s not in k['things']:
                return _result('no_knowledge', 'thing "%s" is not in the word pack' % s, notes=notes)
            s = ('thing', s)
        if isinstance(o, bool):
            if relation['value'] != 'truth' or (o is False and kind != 'check'):
                return _result('out_of_scope', 'true/false is only a value of a truth relation, and "false" only in a claim check')
            compiled.append((s, p, ('truth',), o))
        else:
            compiled.append((s, p, o if _is_var(o) else _value(o, relation, k['things'], k['units']), True))
    ground = {s: (binding[s][1] if _is_var(s) else s[1]) for s, _, _, _ in compiled if not _is_var(s) or s in binding}
    blocked = [b for b in k['blocked'] if any(_touches(c, ground, tuple(b['key'])) for c in compiled)]
    if blocked:
        return _result('out_of_scope', 'the knowledge this question needs uses something not supported yet',
                       blocked=[{'id': b['id'], 'reason': b['reason']} for b in blocked], notes=notes)
    conflicts = [{'subject': key[0], 'relation': key[1], 'statements': ids} for key, ids in sorted(k['conflicts'].items())
                 if any(_touches(c, ground, key) for c in compiled)]
    if conflicts:
        return _result('conflict', 'the knowledge this question needs contradicts itself', conflicts=conflicts, notes=notes)
    if kind == 'check':
        return _check_claim(k, compiled[0], binding, notes)
    if not find or any(not any(v in (s, o) for s, _, o, _ in compiled) for v in find):
        raise ValueError('every variable in "find" must occur in "where"')
    found, steps, limit = {}, 0, k['limits']['search_steps']

    def extend(i, bound, used):
        nonlocal steps
        if i == len(compiled):
            proofs = found.setdefault(tuple(bound[v] for v in find), [])
            if used not in proofs:
                proofs.append(used)
            return True
        s, p, o, _ = compiled[i]
        for st in k['by_p'].get(p, []):
            steps += 1
            if steps > limit:
                return False
            if not st['holds']:
                continue
            step = _unify(bound, s, ('thing', st['s']))
            step = step if step is None else _unify(step, o, st['v'])
            if step is not None and not extend(i + 1, step, used + [st['id']]):
                return False
        return True

    if not extend(0, binding, []):
        return _result('limit_exceeded', 'search bound reached', notes=notes)
    if not found:
        return _result('no_knowledge', 'no statement fits every condition of the question', notes=notes)
    answers = [{'values': [_show(k, v) for v in row], 'proofs': sorted(found[row])} for row in sorted(found, key=repr)]
    return _result('answered', 'every condition of the question holds', answers=answers, notes=notes)


def _check_claim(k, pattern, binding, notes):
    s, p, value, wanted = pattern
    subject = (binding[s] if _is_var(s) else s)[1] if not _is_var(s) or s in binding else None
    if subject is None or _is_var(value):
        return _result('out_of_scope', 'a claim check needs a named subject and a stated value', notes=notes)
    group = [st for st in k['by_p'].get(p, []) if st['s'] == subject]
    yes = sorted(st['id'] for st in group if st['holds'] and st['v'] == value)
    no = sorted(st['id'] for st in group if not st['holds'] and st['v'] == value)
    other = sorted(st['id'] for st in group if st['holds'] and st['v'] != value)
    relation, assumptions = k['relations'][p], []
    if yes:
        truth, steps = True, yes
    elif no:
        truth, steps = False, no
    elif relation.get('single') and other:
        truth, steps = False, other          # the relation has one value and it is another one
    elif relation.get('absent_means') == 'false':
        truth, steps = False, []
        assumptions = ['"%s" is declared complete in the word pack: not stated means false' % p]
    else:
        return _result('no_knowledge', 'nothing states this either way; that is not the same as false', notes=notes)
    return _result('answered', 'the claim was compared with what is stated', notes=notes, assumptions=assumptions,
                   claim={'holds': truth == wanted, 'steps': steps})


# ---------------------------------------------------------------- independent check

def check(words, facts, question, result):
    """Judge an inferred result with a second implementation that shares no code with `ask`.

    It reads the raw packs itself, enumerates every combination of statements instead of
    searching, and compares: are the cited steps right, and is the set of answers the same
    (nothing missing, nothing extra). The two agreeing is an internal cross-check by one
    author, not an independent evaluation.
    """
    limit = dict(LIMITS, **words.get('limits', {}))['enumeration']
    thing_ids = {t['id'] for t in words['things']}
    rel = {r['p']: r for r in words['relations']}
    scale = {u['unit']: (u.get('base', u['unit']), Fraction(u.get('per_base', '1'))) for u in words.get('units', [])}

    def plain(o):
        if o is None or isinstance(o, bool):
            return ('truth',)
        if 'thing' in o:
            return ('thing', o['thing'])
        if 'n' in o:
            return ('quantity', Fraction(o['n']) / scale[o['unit']][1], scale[o['unit']][0])
        (kind, value), = o.items()
        return (kind, value)

    good, later, seen = {}, [], set()
    for st in facts.get('statements', []):
        sid, first = st.get('id'), st.get('id') not in seen
        if isinstance(sid, str):
            seen.add(sid)
        if not (isinstance(sid, str) and first and st.get('source') and st.get('p') in rel and st.get('s') in thing_ids
                and isinstance(st.get('holds', True), bool)):
            continue
        if any(f in st for f in LATER):
            later.append((st['s'], st['p']))
            continue
        try:
            value = plain(st.get('o'))
            fits = value[0] == rel[st['p']]['value'] and (value[0] != 'thing' or value[1] in thing_ids) \
                and (value[0] != 'truth' or st.get('o') is None) \
                and (value[0] in ('truth', 'quantity') or set(st['o']) == {value[0]}) \
                and (value[0] != 'quantity' or set(st['o']) == {'n', 'unit'})
        except (AttributeError, KeyError, TypeError, ValueError, ZeroDivisionError):
            fits = False
        if fits:
            good[sid] = (st['s'], st['p'], value, st.get('holds', True))
    places = {st['id']: (st.get('s'), st.get('p')) for st in facts.get('statements', []) if isinstance(st.get('id'), str)}
    for rule in facts.get('rules', []):
        then = rule.get('then')
        later.append((None, then[1]) if isinstance(then, list) and len(then) == 3 and then[1] in rel else (None, None))
    for change in facts.get('changes', []):
        target = [change[f] for f in ('retracts', 'corrects', 'supersedes') if f in change]
        later.append(places.get(target[0], (None, None)) if target else (None, None))

    # What the result should be, worked out the slow way.
    kind, find, patterns = question.get('ask', 'value'), question.get('find', []), question['where']
    expect, answers, claim, fixed = None, {}, None, {}
    if any(question.get(f) for f in ('given', 'at', 'known_at')) or kind not in ('value', 'check') \
            or (kind == 'check' and (len(patterns) != 1 or find)):
        expect = 'out_of_scope'
    for var, name in sorted(question.get('names', {}).items()):
        ids = [t['id'] for t in words['things'] if name in t['names']]
        if expect is None and len(ids) != 1:
            expect = 'ambiguous_entity' if ids else 'no_knowledge'
        fixed[var] = ('thing', ids[0]) if ids else None
    terms = []
    for s, p, o in patterns:
        if expect is None and (p not in rel or (not _is_var(s) and s not in thing_ids)):
            expect = 'no_knowledge'
        if expect is None and isinstance(o, bool) and (rel[p]['value'] != 'truth' or (o is False and kind != 'check')):
            expect = 'out_of_scope'
        if expect is None:
            terms.append((s if _is_var(s) else ('thing', s), p, o if _is_var(o) else plain(o), o is not False))
    if expect is None:
        def reads(key):
            for s, p, _, _ in terms:
                subject = fixed.get(s) if _is_var(s) else s
                if key[1] in (None, p) and (key[0] is None or subject is None or subject[1] == key[0]):
                    return True
            return False
        clash = set()
        for sid, (s, p, value, holds) in good.items():
            for s2, p2, value2, holds2 in good.values():
                if (s, p) == (s2, p2) and ((value == value2 and holds != holds2)
                                           or (rel[p].get('single') and holds and holds2 and value != value2)):
                    clash.add((s, p))
        if any(reads(key) for key in later):
            expect = 'out_of_scope'
        elif any(reads(key) for key in clash):
            expect = 'conflict'
    if expect is None and kind == 'check':
        s, p, value, wanted = terms[0]
        subject = fixed.get(s) if _is_var(s) else s
        if subject is None or _is_var(value):
            expect = 'out_of_scope'
        else:
            mine = [(sid, st) for sid, st in good.items() if st[0] == subject[1] and st[1] == p]
            if any(st[3] and st[2] == value for _, st in mine):
                truth = True
            elif any(not st[3] and st[2] == value for _, st in mine):
                truth = False
            elif (rel[p].get('single') and any(st[3] for _, st in mine)) or rel[p].get('absent_means') == 'false':
                truth = False
            else:
                truth = None
            expect = 'no_knowledge' if truth is None else 'answered'
            claim = None if truth is None else {'holds': truth == wanted,
                                                'about': {sid for sid, _ in mine}}
    elif expect is None:
        pools = [[(sid, st) for sid, st in sorted(good.items()) if st[1] == p and st[3]] for _, p, _, _ in terms]
        size = 1
        for pool in pools:
            size *= len(pool)
        if size > limit:
            expect = 'not_checked'
        else:
            for combo in product(*pools):
                bound = dict((v, x) for v, x in fixed.items())
                for (s, _, o, _), (_, st) in zip(terms, combo):
                    for term, value in ((s, ('thing', st[0])), (o, st[2])):
                        if not _is_var(term):
                            bound = bound if bound is not None and term == value else None
                        elif bound is not None and bound.setdefault(term, value) != value:
                            bound = None
                if bound is not None and all(v in bound for v in find):
                    answers.setdefault(tuple(bound[v] for v in find), set()).add(tuple(sid for sid, _ in combo))
            expect = 'answered' if answers else 'no_knowledge'

    # Compare.
    if expect == 'not_checked':
        return {'steps': 'not_checked', 'completeness': 'not_checked',
                'cause': ['enumeration bound reached (%d combinations, bound %d)' % (size, limit)]}
    verdict = {'steps': 'agrees', 'completeness': 'agrees', 'cause': []}
    if result['status'] != expect:
        verdict['completeness'] = 'rejects'
        verdict['cause'].append('inferred status is %s, the check finds %s' % (result['status'], expect))
        if expect == 'answered' and kind == 'value':
            verdict['cause'].append('answers the check finds: %s' % sorted(answers, key=repr))
        return verdict
    if expect != 'answered':
        return verdict
    if kind == 'check':
        got = result.get('claim') or {}
        if got.get('holds') != claim['holds']:
            verdict['completeness'] = 'rejects'
            verdict['cause'].append('the claim is %s by the check' % claim['holds'])
        if not set(got.get('steps', [])) <= claim['about']:
            verdict['steps'] = 'rejects'
            verdict['cause'].append('a cited statement is not about the claim: %s' % sorted(set(got['steps']) - claim['about']))
        return verdict
    given = {}
    for item in result['answers']:
        try:
            row = tuple(plain(v) for v in item['values'])
        except (AttributeError, KeyError, TypeError, ValueError):
            row = ('unreadable', repr(item['values']))
        given[row] = item['proofs']
        for proof in item['proofs']:
            if not proof or tuple(proof) not in answers.get(row, set()):
                verdict['steps'] = 'rejects'
                verdict['cause'].append('steps %s do not give the answer %s' % (proof, item['values']))
    missing = sorted((r for r in answers if r not in given), key=repr)
    extra = sorted((r for r in given if r not in answers), key=repr)
    if missing or extra:
        verdict['completeness'] = 'rejects'
        verdict['cause'] += ['missing answer: %s' % (r,) for r in missing] + ['answer with no ground: %s' % (r,) for r in extra]
    return verdict


def final(result, verdict):
    """The reported result. A rejection outranks whatever was inferred; agreement changes nothing."""
    out = dict(result, inferred=result['status'], verification=verdict)
    if verdict is None:                       # nothing was inferred that a check could judge
        return out
    if 'rejects' in (verdict['steps'], verdict['completeness']):
        out.update(status='verification_failed', reason='the independent check rejected the result: ' + '; '.join(verdict['cause']),
                   withheld={'answers': result['answers'], 'claim': result['claim']}, answers=[], claim=None)
    elif 'not_checked' in (verdict['steps'], verdict['completeness']):
        out.update(status='unverified', reason='the result could not be checked: ' + '; '.join(verdict['cause']))
    return out


def answer(words, facts, question):
    """Load, infer, check and judge. The status is the reported one; `inferred` keeps the first one."""
    knowledge = load(words, facts)
    result = ask(knowledge, question)
    verdict = None if result['status'] == 'limit_exceeded' else check(words, facts, question, result)
    return dict(final(result, verdict), unusable=knowledge['unusable'], counts=knowledge['counts'])
