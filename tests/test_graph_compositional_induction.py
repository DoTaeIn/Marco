import copy
import hashlib
import json
import unittest

from marco.reasoning.graph_vm import run
from tools import graph_compositional_induction as gci

SUB = ' sa '
OBJ = ' ob '
XE = ' xe '
YO = ' yo '
Q = chr(34)
NAMES = ['zorp', 'quim', 'blax', 'vemt']


def pat(pid, kind, polarity, relation, pred):
    return {'id': pid, 'kind': kind, 'polarity': polarity, 'relation': relation,
            'prefix': '', 'between': SUB, 'suffix': OBJ + pred}


def base_patterns():
    return [pat('r1:f:T', 'fact', True, 'r1', 'ka.'), pat('r1:f:F', 'fact', False, 'r1', 'mi.'),
            pat('r2:f:T', 'fact', True, 'r2', 'to.'), pat('r2:q:T', 'query', True, 'r2', 'ne?')]


def make_seed(extra=(), names=NAMES):
    labels = [{'id': 'L:' + n, 'text': n} for n in names]
    return {'labels': labels, 'labels_by_id': {l['id']: l['text'] for l in labels},
            'patterns': base_patterns() + list(extra)}


def S(a, ma, b, mb, pred):
    return a + ma + b + mb + pred


def canon(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def tpl_hash(t):
    return hashlib.sha256(canon(t).encode('utf-8')).hexdigest()


def template():
    def sn(i, name, nxt, lit):
        return {'id': i, 'op': 'set', 'name': name, 'value': {'literal': lit}, 'next': nxt}
    ret = {'object': {k: {'var': [k]} for k in
                      ('subject_markers', 'object_markers', 'orders', 'seed_object_marker', 'keep')}}
    return {'schema': 'marco-graph-vm-program-v1', 'entry': 'composition_subject_markers', 'nodes': [
        sn('composition_subject_markers', 'subject_markers', 'composition_object_markers', []),
        sn('composition_object_markers', 'object_markers', 'composition_orders', []),
        sn('composition_orders', 'orders', 'composition_seed_object_marker', []),
        sn('composition_seed_object_marker', 'seed_object_marker', 'other', ''),
        sn('other', 'keep', 'out', 7),
        {'id': 'out', 'op': 'return', 'value': ret}]}


def corpus():
    return [S('zorp', XE, 'quim', OBJ, 'ka.'), S('blax', XE, 'quim', OBJ, 'mi.'),
            S('quim', OBJ, 'zorp', SUB, 'ka.'), S('quim', OBJ, 'blax', SUB, 'mi.')]


class LearnTests(unittest.TestCase):
    def setUp(self):
        self.seed = make_seed()

    def learned(self, sents, seed=None, **kw):
        return gci.learn(seed or self.seed, sents, **kw)['learned']

    def test_ascii_seed_only(self):
        self.assertTrue(canon(self.seed).isascii())
        art = gci.learn(self.seed, [S('zorp', SUB, 'quim', OBJ, 'ka.'), S('blax', SUB, 'vemt', OBJ, 'mi.')])
        self.assertEqual(art['learned'], {'subject_markers': [SUB], 'object_markers': [OBJ],
                                          'orders': [[0, 1, 2]]})
        self.assertEqual(len(art['evidence']), 2)
        self.assertEqual(art['evidence'][0]['order'], [0, 1, 2])

    def test_new_subject_marker(self):
        art = gci.learn(self.seed, corpus()[:2])
        self.assertEqual(art['learned']['subject_markers'], [SUB, XE])
        self.assertEqual(art['learned']['object_markers'], [OBJ])
        self.assertEqual(art['learned']['orders'], [[0, 1, 2]])

    def test_reversed_order(self):
        got = self.learned(corpus()[2:])
        self.assertEqual(got['orders'], [[0, 1, 2], [1, 0, 2]])
        self.assertEqual(got['subject_markers'], [SUB])
        self.assertEqual(self.learned(corpus()[2:3])['orders'], [[0, 1, 2]])

    def test_new_object_marker_when_anchored(self):
        got = self.learned([S('zorp', SUB, 'quim', YO, 'ka.'), S('blax', SUB, 'quim', YO, 'mi.')])
        self.assertEqual(got['object_markers'], [OBJ, YO])

    def test_duplicates_are_not_support(self):
        one = S('zorp', XE, 'quim', OBJ, 'ka.')
        self.assertEqual(self.learned([one] * 3)['subject_markers'], [SUB])
        same_pair = [one, S('zorp', XE, 'quim', OBJ, 'mi.')]
        self.assertEqual(self.learned(same_pair)['subject_markers'], [SUB])

    def test_both_unknown_no_learning(self):
        sents = [S('zorp', XE, 'quim', YO, 'ka.'), S('blax', XE, 'quim', YO, 'mi.'),
                 S('vemt', XE, 'quim', YO, 'to.')]
        art = gci.learn(self.seed, sents)
        self.assertEqual(art['learned']['subject_markers'], [SUB])
        self.assertEqual(art['learned']['object_markers'], [OBJ])
        self.assertEqual(art['evidence'], [])

    def test_ambiguity_refused(self):
        sents = [S('zorp', XE, 'quim', OBJ, 'ka.'), S('blax', XE, 'quim', OBJ, 'ka.')]
        self.assertEqual(self.learned(sents)['subject_markers'], [SUB, XE])
        amb = make_seed([pat('r2:x', 'fact', True, 'r2', 'a.')])
        art = gci.learn(amb, sents)
        self.assertEqual(art['learned']['subject_markers'], [SUB])
        self.assertEqual(art['evidence'], [])
        self.assertEqual({r['reason'] for r in art['rejected']}, {'ambiguous_decomposition'})
        self.assertEqual(len(art['rejected']), 2)

    def test_marker_role_conflict_refused(self):
        sents = [S('zorp', XE, 'quim', OBJ, 'ka.'), S('blax', XE, 'quim', OBJ, 'mi.'),
                 S('zorp', SUB, 'quim', XE, 'ka.'), S('blax', SUB, 'vemt', XE, 'mi.')]
        art = gci.learn(self.seed, sents)
        self.assertEqual(art['learned']['subject_markers'], [SUB])
        self.assertEqual(art['learned']['object_markers'], [OBJ])
        self.assertEqual(len(art['rejected']), 4)
        self.assertEqual({r['reason'] for r in art['rejected']}, {'marker_role_conflict'})

    def test_repeated_and_quoted_do_not_learn(self):
        sents = [S('zorp', XE, 'quim', OBJ, 'zorp sa quim ob ka.'),
                 S('blax', XE, 'quim', OBJ, 'blax sa quim ob mi.'),
                 Q + S('zorp', SUB, 'quim', OBJ, 'ka.') + Q, 'zorp sa zorp ob ka.']
        art = gci.learn(self.seed, sents)
        self.assertEqual(art['evidence'], [])
        self.assertEqual(art['learned']['subject_markers'], [SUB])

    def test_sources_and_no_facts(self):
        sents = corpus()
        art = gci.learn(self.seed, sents)
        self.assertNotIn('facts', art)
        self.assertIsNone(art['semantics'])
        self.assertFalse(art['active'])
        self.assertEqual(len(art['sources']), 4)
        for src in art['sources']:
            digest = hashlib.sha256(src['text'].encode('utf-8')).hexdigest()
            self.assertEqual(src['sha256'], digest)
            self.assertEqual(src['id'], 'source:' + digest)
        self.assertTrue(art['limitations'])

    def test_deterministic_and_immutable(self):
        sents = corpus()
        seed_before, sents_before = copy.deepcopy(self.seed), list(sents)
        a1 = gci.learn(self.seed, sents)
        a2 = gci.learn(self.seed, sents[::-1] + sents[:2])
        self.assertEqual(canon(a1), canon(a2))
        self.assertEqual(self.seed, seed_before)
        self.assertEqual(sents, sents_before)

    def test_limits_and_invalid_input(self):
        bad = [lambda: gci.learn(self.seed, ['a'] * 65),
               lambda: gci.learn(self.seed, ['a' * 129]),
               lambda: gci.learn(self.seed, ['']),
               lambda: gci.learn(self.seed, [chr(0xD800)]),
               lambda: gci.learn(self.seed, [3]),
               lambda: gci.learn(self.seed, 'x'),
               lambda: gci.learn(self.seed, [], min_support=1),
               lambda: gci.learn(self.seed, [], min_support=True),
               lambda: gci.learn(make_seed(names=NAMES + ['wolt']), []),
               lambda: gci.learn(make_seed([pat('p%d' % i, 'fact', True, 'r1', 'k%d.' % i)
                                            for i in range(9)]), [])]
        for fn in bad:
            with self.assertRaises(ValueError):
                fn()
        old = gci.MAX_WORK
        gci.MAX_WORK = 3
        try:
            with self.assertRaises(ValueError):
                gci.learn(self.seed, corpus())
        finally:
            gci.MAX_WORK = old

    def test_seed_validation(self):
        def mutate(fn):
            s = make_seed()
            fn(s)
            with self.assertRaises(ValueError):
                gci.learn(s, [])
        mutate(lambda s: s['labels_by_id'].update({'L:zorp': 'other'}))
        mutate(lambda s: s.update({'extra': 1}))
        mutate(lambda s: s['patterns'][3].update({'polarity': False}))
        mutate(lambda s: s['patterns'][0].update({'between': 'x' * 17, 'suffix': 'y' * 17 + 'ka.'}))
        mutate(lambda s: s['patterns'][0].update({'between': ' zz '}))
        mutate(lambda s: s['patterns'][0].update({'kind': 'rule'}))
        mutate(lambda s: s['labels'][0].update({'text': ''}))
        mutate(lambda s: s['labels'].append(dict(s['labels'][0])))
        mutate(lambda s: [p.update({'relation': 'r1'}) for p in s['patterns']])


class CompileTests(unittest.TestCase):
    def setUp(self):
        self.seed = make_seed()
        self.sents = corpus()
        self.art = gci.learn(self.seed, self.sents)
        self.tpl = template()
        self.h = tpl_hash(self.tpl)

    def compile(self, **over):
        args = {'template': self.tpl, 'artifact': self.art, 'seed_model': self.seed,
                'sentences': self.sents, 'expected_template_sha256': self.h}
        args.update(over)
        return gci.compile_program(args.pop('template'), args.pop('artifact'),
                                   args.pop('seed_model'), args.pop('sentences'), **args)

    def test_only_four_literals_change(self):
        before = copy.deepcopy(self.tpl)
        prog = self.compile()
        self.assertEqual(self.tpl, before)
        expected = copy.deepcopy(before)
        lits = {'composition_subject_markers': [SUB, XE], 'composition_object_markers': [OBJ],
                'composition_orders': [[0, 1, 2], [1, 0, 2]],
                'composition_seed_object_marker': OBJ}
        for node in expected['nodes']:
            if node['id'] in lits:
                node['value'] = {'literal': lits[node['id']]}
        self.assertEqual(prog, expected)
        res = run(prog, {})
        self.assertEqual(res['status'], 'completed')
        self.assertEqual(res['value'], {'subject_markers': [SUB, XE], 'object_markers': [OBJ],
                                        'orders': [[0, 1, 2], [1, 0, 2]],
                                        'seed_object_marker': OBJ, 'keep': 7})

    def test_tampered_artifact_refused(self):
        a = copy.deepcopy(self.art)
        a['learned']['subject_markers'].append('zz')
        b = copy.deepcopy(self.art)
        b['evidence'][0]['pattern'] = 'r2:q:T'
        c = copy.deepcopy(self.art)
        c['sources'][0]['text'] = 'changed'
        d = copy.deepcopy(self.art)
        d['min_support'] = 3
        for bad in (a, b, c, d, 5, {}):
            with self.assertRaises(ValueError):
                self.compile(artifact=bad)

    def test_stale_inputs_refused(self):
        stale = make_seed([pat('r1:f:X', 'fact', True, 'r1', 'zz.')])
        with self.assertRaises(ValueError):
            self.compile(seed_model=stale)
        with self.assertRaises(ValueError):
            self.compile(sentences=self.sents[:-1])

    def test_template_refusals(self):
        with self.assertRaises(ValueError):
            self.compile(expected_template_sha256='0' * 64)
        with self.assertRaises(ValueError):
            self.compile(expected_template_sha256=None)
        changed = copy.deepcopy(self.tpl)
        changed['nodes'][4]['value'] = {'literal': 8}
        with self.assertRaises(ValueError):
            self.compile(template=changed)
        dirty = copy.deepcopy(self.tpl)
        dirty['nodes'][0]['value'] = {'literal': ['x']}
        with self.assertRaises(ValueError):
            self.compile(template=dirty, expected_template_sha256=tpl_hash(dirty))
        renamed = copy.deepcopy(self.tpl)
        renamed['nodes'][2]['name'] = 'wrong'
        with self.assertRaises(ValueError):
            self.compile(template=renamed, expected_template_sha256=tpl_hash(renamed))
        shaped = copy.deepcopy(self.tpl)
        shaped['nodes'][3]['value'] = {'var': ['keep']}
        with self.assertRaises(ValueError):
            self.compile(template=shaped, expected_template_sha256=tpl_hash(shaped))


if __name__ == '__main__':
    unittest.main()
