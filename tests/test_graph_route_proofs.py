import copy
import hashlib
import json
import unittest

from marco.reasoning.proof_graph import (
    build_proof_graph, build_route_proof_graph, verify_proof_graph)


def _sha(value):
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _fact(fid, triple, **extra):
    out = {'id': fid, 'triple': list(triple), 'evidence': {'src': 'syn'}}
    out.update(extra)
    return out


def _rule(rid, body, head, version=1):
    return {'id': rid, 'version': version, 'body': [list(p) for p in body], 'head': list(head)}


GOOD = _rule('zq_good', [['?a', 'zq_p', '?b']], ['?a', 'zq_t', '?b'])
NOISE1 = _rule('zq_noise1', [['?a', 'zq_x', '?b']], ['?a', 'zq_y', '?b'])
NOISE2 = _rule('zq_noise2', [['?a', 'zq_y', '?b']], ['?b', 'zq_w', '?a'], version='v2')
UNSAFE = _rule('zq_unsafe', [['?a', 'zq_x', 'k']], ['?a', 'zq_y', '?zz'])
TARGET = ['zq_m', 'zq_t', 'zq_n']
BASE = [_fact('zf1', ['zq_m', 'zq_p', 'zq_n']), _fact('zf2', ['zq_u', 'zq_x', 'zq_v'])]
RULES = [NOISE1, GOOD, NOISE2]


def _nodes(record):
    return {n['id']: n['value'] for n in record['frame']['nodes']}


def _source(record, key):
    for s in record['frame']['sources']:
        if s['id'] == 'source:' + key:
            return s
    return None


class RouteProofTest(unittest.TestCase):
    def run_route(self, facts, rules, target, ids, **kw):
        snap = copy.deepcopy((facts, rules, target, ids))
        rec = build_route_proof_graph(facts, rules, target, rule_ids=ids, **kw)
        self.assertEqual(snap, (facts, rules, target, ids))
        return rec

    def test_selected_rule_among_unrelated_proves_with_full_sources(self):
        rec = self.run_route(BASE, RULES, TARGET, ['zq_good'])
        self.assertEqual(rec['status'], 'proved')
        self.assertTrue(rec['complete'])
        v = verify_proof_graph(rec, BASE, RULES, TARGET)
        self.assertEqual(v, {'valid': True, 'conclusion_verified': True, 'reason': 'proved'})
        self.assertEqual(rec['rules_sha256'], _sha(RULES))
        self.assertEqual(rec['facts_sha256'], _sha(BASE))
        src = _source(rec, 'rules')
        self.assertEqual(json.loads(src['text']), RULES)
        self.assertIn('zq_noise2', src['text'])
        self.assertEqual(src['sha256'], hashlib.sha256(src['text'].encode('utf-8')).hexdigest())
        sub = verify_proof_graph(rec, BASE, [GOOD], TARGET)
        self.assertFalse(sub['valid'])
        self.assertEqual(sub['reason'], 'hash_mismatch')

    def test_unreachable_route_is_incomplete_not_unresolved(self):
        rec = self.run_route(BASE, RULES, TARGET, ['zq_noise1', 'zq_noise2'])
        self.assertEqual((rec['status'], rec['reason']), ('incomplete', 'closure_incomplete'))
        self.assertFalse(rec['complete'])
        v = verify_proof_graph(rec, BASE, RULES, TARGET)
        self.assertFalse(v['valid'])
        self.assertFalse(v['conclusion_verified'])
        self.assertEqual(v['reason'], 'incomplete')
        self.assertEqual(build_proof_graph(BASE, RULES, TARGET)['status'], 'proved')

    def test_empty_route_direct_only(self):
        facts = BASE + [_fact('zf3', TARGET)]
        rec = self.run_route(facts, RULES, TARGET, [])
        self.assertEqual(rec['status'], 'proved')
        self.assertTrue(verify_proof_graph(rec, facts, RULES, TARGET)['conclusion_verified'])
        kinds = [v.get('kind') for k, v in _nodes(rec).items() if k != 'query']
        self.assertEqual(kinds, ['asserted'])
        rec2 = self.run_route(BASE, RULES, TARGET, [])
        self.assertEqual((rec2['status'], rec2['reason']), ('incomplete', 'closure_incomplete'))

    def test_negative_and_conflict_not_bypassed(self):
        neg = BASE + [_fact('zf4', TARGET, polarity=False)]
        for ids in (['zq_good'], [], ['zq_noise1']):
            rec = self.run_route(neg, RULES, TARGET, ids)
            self.assertEqual(rec['status'], 'contradicted')
            self.assertEqual(verify_proof_graph(rec, neg, RULES, TARGET),
                             {'valid': True, 'conclusion_verified': False,
                              'reason': 'contradicted'})
        both = neg + [_fact('zf5', TARGET)]
        for ids in (['zq_good'], []):
            rec = self.run_route(both, RULES, TARGET, ids)
            self.assertEqual(rec['status'], 'conflict')
            v = verify_proof_graph(rec, both, RULES, TARGET)
            self.assertTrue(v['valid'])
            self.assertFalse(v['conclusion_verified'])

    def test_invalid_routes_reject(self):
        bad = ['zq_good', None, 7, {'zq_good': 1}, [7], [None], [['zq_good']],
               ['zq_good', 'zq_good'], ['zq_missing'], [''], ['x' * 65],
               ['zq_good'] * 17, [True], ('zq_good',)]
        for ids in bad:
            facts, rules, target = copy.deepcopy((BASE, RULES, TARGET))
            held = copy.deepcopy(ids)
            with self.assertRaises(ValueError) as cm:
                build_route_proof_graph(facts, rules, target, rule_ids=ids)
            self.assertEqual(str(cm.exception), 'invalid_route')
            self.assertEqual((facts, rules, target), (BASE, RULES, TARGET))
            self.assertEqual(ids, held)

    def test_unselected_unsafe_rule_stays_invalid(self):
        rules = RULES + [UNSAFE]
        for ids in (['zq_good'], []):
            rec = self.run_route(BASE, rules, TARGET, ids)
            self.assertEqual((rec['status'], rec['reason']), ('invalid', 'unsafe_rule'))
            q = _nodes(rec)['query']
            self.assertEqual(q['failed_rules'], ['zq_unsafe'])
            v = verify_proof_graph(rec, BASE, rules, TARGET)
            self.assertEqual(v['reason'], 'unsafe_rule')
            self.assertFalse(v['conclusion_verified'])

    def test_non_asserted_premises_not_promoted(self):
        prem = ['zq_m', 'zq_p', 'zq_n']
        for extra in ({'modality': 'planned'}, {'modality': 'conditional'},
                      {'polarity': False}):
            facts = [_fact('zf6', prem, **extra)]
            rec = self.run_route(facts, RULES, TARGET, ['zq_good'])
            self.assertEqual((rec['status'], rec['reason']), ('incomplete', 'closure_incomplete'))
            self.assertFalse(verify_proof_graph(rec, facts, RULES, TARGET)['conclusion_verified'])

    def test_small_search_cap_is_not_a_conclusion(self):
        facts = BASE + [_fact('zf7', ['zq_r', 'zq_p', 'zq_s'])]
        rec = self.run_route(facts, RULES, TARGET, ['zq_good'], search_limit=1)
        self.assertEqual(rec['status'], 'incomplete')
        self.assertEqual(rec['reason'], 'proof_or_search_limit')
        self.assertEqual(rec['limits'], {'limit': 32, 'proof_limit': 4, 'search_limit': 1})
        v = verify_proof_graph(rec, facts, RULES, TARGET)
        self.assertFalse(v['valid'])
        self.assertFalse(v['conclusion_verified'])

    def test_two_step_and_rule_derivation(self):
        facts = [_fact('ze1', ['zn1', 'zlink', 'zn2']), _fact('ze2', ['zn2', 'ztag', 'zk']),
                 _fact('ze3', ['zo', 'zother', 'zo'])]
        r_and = _rule('zr_and', [['?x', 'zlink', '?y'], ['?y', 'ztag', '?z']],
                      ['?x', 'zmid', '?z'], version='a1')
        r_step = _rule('zr_step', [['?x', 'zmid', '?z']], ['?x', 'zgoal', '?z'])
        rules = [NOISE1, r_and, r_step, NOISE2]
        target = ['zn1', 'zgoal', 'zk']
        rec = self.run_route(facts, rules, target, ['zr_step', 'zr_and'])
        self.assertEqual(rec['status'], 'proved')
        self.assertEqual(verify_proof_graph(rec, facts, rules, target),
                         {'valid': True, 'conclusion_verified': True, 'reason': 'proved'})
        nodes = _nodes(rec)
        root = nodes[nodes['query']['root']]
        self.assertEqual((root['rule'], root['rule_version']), ('zr_step', 1))
        mid = nodes[root['parents'][0]]
        self.assertEqual((mid['rule'], mid['rule_version']), ('zr_and', 'a1'))
        self.assertEqual(mid['bindings'], {'?x': 'zn1', '?y': 'zn2', '?z': 'zk'})
        self.assertEqual([nodes[p]['conclusion'] for p in mid['parents']],
                         [['zn1', 'zlink', 'zn2'], ['zn2', 'ztag', 'zk']])
        self.assertEqual([nodes[p]['fact_id'] for p in mid['parents']], ['ze1', 'ze2'])
        self.assertEqual(rec['rules_sha256'], _sha(rules))
        self.assertEqual(rec['facts_sha256'], _sha(facts))
        self.assertEqual(json.loads(_source(rec, 'rules')['text']), rules)
        self.assertEqual(json.loads(_source(rec, 'facts')['text']), facts)
        self.assertFalse(verify_proof_graph(rec, facts, [r_and, r_step], target)['valid'])
        half = self.run_route(facts, rules, target, ['zr_step'])
        self.assertEqual((half['status'], half['reason']), ('incomplete', 'closure_incomplete'))


if __name__ == '__main__':
    unittest.main()
