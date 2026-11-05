import copy
import hashlib
import unittest
from unittest import mock

from marco.reasoning import proof_graph as pg


def fact(i, t, **k):
    return dict(id=i, triple=list(t), evidence={}, **k)


def rule(i, body, head):
    return dict(id=i, version=1, body=body, head=head)


FACTS = [fact('f1', 'arb'), fact('f2', 'bsc'), fact('f3', 'zzz')]
AND = rule('r1', [['?x', 'r', '?y'], ['?y', 's', '?z']], ['?x', 't', '?z'])
STEP = rule('r2', [['?x', 't', '?y']], ['?x', 'u', '?y'])


def build(facts=FACTS, rules=(AND,), target='atc', **k):
    return pg.build_proof_graph(copy.deepcopy(facts), copy.deepcopy(list(rules)), list(target), **k)


def check(rec, facts=FACTS, rules=(AND,), target='atc'):
    r = pg.verify_proof_graph(copy.deepcopy(rec), copy.deepcopy(facts),
                              copy.deepcopy(list(rules)), list(target))
    return tuple(r.values())


def vals(rec):
    return [n['value'] for n in rec['frame']['nodes'][1:]]


def forge(rec, facts, rules, edit):
    rec = copy.deepcopy(rec)
    nodes = rec['frame']['nodes']
    new, out = {}, []
    for n in nodes[1:]:
        v = n['value']
        v['parents'] = [new[p] for p in v['parents']]
        edit(v)
        new[n['id']] = 'proof:' + pg._h(v)
        out.append((new[n['id']], v))
    q = nodes[0]['value']
    q['root'] = new[q['root']]
    rec['frame'] = pg._frame(pg._c(facts), pg._c(rules), q, out)
    return rec


def derived(fn):
    return lambda v: fn(v) if v['kind'] == 'derived' else None


class ProofGraphTests(unittest.TestCase):
    def test_and_premises_and_unused_fact(self):
        rec = build()
        self.assertEqual((rec['status'], rec['complete']), ('proved', True))
        with mock.patch.object(pg.inference, 'closure_with_provenance', side_effect=AssertionError('positive verifier reran engine')):
            self.assertEqual(check(rec), (True, True, 'proved'))
        d = [v for v in vals(rec) if v['kind'] == 'derived']
        self.assertEqual(len(d), 1)
        self.assertEqual((d[0]['rule'], d[0]['rule_version']), ('r1', 1))
        self.assertEqual(d[0]['bindings'], {'?x': 'a', '?y': 'b', '?z': 'c'})
        used = {v['fact_id'] for v in vals(rec) if v['kind'] == 'asserted'}
        self.assertEqual(used, {'f1', 'f2'})
        rels = sorted(e['relation'] for e in rec['frame']['edges'])
        self.assertEqual(rels, ['premise:0', 'premise:1', 'root'])
        direct = build(target='arb')
        self.assertEqual(check(direct, target='arb'), (True, True, 'proved'))
        self.assertEqual(len(vals(direct)), 1)

    def test_two_step_chain(self):
        rules = (AND, STEP)
        rec = build(rules=rules, target='auc')
        self.assertEqual(rec['status'], 'proved')
        self.assertEqual(len(vals(rec)), 4)
        self.assertEqual(check(rec, rules=rules, target='auc'), (True, True, 'proved'))

    def test_outcomes(self):
        rec = build(target='qqq')
        self.assertEqual(check(rec, target='qqq'), (True, False, 'unresolved'))
        neg = FACTS + [fact('n', 'qqq', polarity=False)]
        rec = build(neg, target='qqq')
        self.assertEqual(rec['status'], 'contradicted')
        self.assertEqual(check(rec, neg, target='qqq'), (True, False, 'contradicted'))
        both = neg + [fact('p', 'qqq')]
        rec = build(both, target='qqq')
        self.assertEqual(check(rec, both, target='qqq'), (True, False, 'conflict'))
        plan = FACTS + [fact('p', 'qqq', modality='planned')]
        self.assertEqual(build(plan, target='qqq')['status'], 'unresolved')

    def test_unsafe_and_cutoff(self):
        unsafe = rule('bad', [['?x', 'r', '?y']], ['?x', 't', '?w'])
        with mock.patch.object(pg.inference, 'closure_with_provenance') as m:
            rec = build(rules=(unsafe,))
            m.assert_not_called()
        self.assertEqual((rec['status'], rec['complete'], rec['reason']),
                         ('invalid', False, 'unsafe_rule'))
        self.assertEqual(rec['frame']['nodes'][0]['value']['failed_rules'], ['bad'])
        self.assertEqual(check(rec, rules=(unsafe,)), (False, False, 'unsafe_rule'))
        rec = build(search_limit=1)
        self.assertEqual((rec['status'], rec['complete']), ('incomplete', False))
        self.assertEqual(check(rec), (False, False, 'incomplete'))

    def test_detachment(self):
        rec = build()
        other = copy.deepcopy(FACTS)
        other[0]['triple'][0] = 'q'
        self.assertFalse(check(rec, other)[0])
        self.assertEqual(check(rec), (True, True, 'proved'))

    def test_rejected_before_closure(self):
        class Odd:
            pass

        cases = [dict(facts=[Odd()]), dict(facts=[FACTS[0], FACTS[0]]),
                 dict(facts=[fact('x', 'abc', polarity=1)]),
                 dict(facts=[fact('x', 'abc', modality='belief')]),
                 dict(target='?bc'), dict(limit=True), dict(search_limit=2000),
                 dict(rules=[dict(AND, extra=1)])]
        with mock.patch.object(pg.inference, 'closure_with_provenance') as m:
            for case in cases:
                with self.subTest(case=list(case)):
                    with self.assertRaises(ValueError):
                        build(**case)
            with self.assertRaises(ValueError):
                pg.verify_proof_graph({}, [Odd()], [], list('abc'))
            m.assert_not_called()

    def test_tamper_rehashed_nodes(self):
        rec = build()
        rules = [AND]
        self.assertTrue(check(forge(rec, FACTS, rules, lambda v: None))[0])
        edits = {
            'binding': derived(lambda v: v['bindings'].update({'?x': 'q'})),
            'head': derived(lambda v: v.update(conclusion=['a', 't', 'q'])),
            'parent': derived(lambda v: v['parents'].reverse()),
            'version': derived(lambda v: v.update(rule_version=2)),
        }
        for name, edit in edits.items():
            with self.subTest(name):
                self.assertFalse(check(forge(rec, FACTS, rules, edit))[0])

    def test_tamper_frame(self):
        rec = build()
        src = copy.deepcopy(rec)
        s = src['frame']['sources'][0]
        s['text'] += ' '
        s['sha256'] = hashlib.sha256(s['text'].encode()).hexdigest()
        qry = copy.deepcopy(rec)
        qry['frame']['nodes'][0]['value']['reason'] = 'x'
        ident = copy.deepcopy(rec)
        ident['frame']['nodes'][1]['id'] = 'proof:' + '0' * 64
        cyc = copy.deepcopy(rec)
        cyc['frame']['nodes'][1]['value']['parents'] = [cyc['frame']['nodes'][-1]['id']]
        extra = copy.deepcopy(rec)
        extra['frame']['edges'].append(dict(extra['frame']['edges'][0], id='edge:extra'))
        for name, bad in (('source', src), ('query', qry), ('id', ident),
                          ('cycle', cyc), ('edge', extra)):
            with self.subTest(name):
                self.assertFalse(check(bad)[0])


class MalformedRecordTests(unittest.TestCase):
    def test_nonstring_status_and_reason_are_rejected(self):
        rec = build()
        for field, badvalues in [('status', [[], {}, True, None]), ('reason', [[], {}, True, 1])]:
            for value in badvalues:
                with self.subTest(field=field, value=value):
                    bad = copy.deepcopy(rec)
                    bad[field] = value
                    self.assertFalse(check(bad)[0])


if __name__ == '__main__':
    unittest.main()
