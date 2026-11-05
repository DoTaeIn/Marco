import copy
import inspect
import json
import hashlib
from pathlib import Path
import unittest
from unittest import mock

from marco.runtime import graph_route_work as grw
from marco.runtime.verified_graph_turn import verified_turn
from marco.runtime import verified_graph_turn as vgt
from tools.graph_surface_compaction import build_indexes

OK = {'valid': True, 'execution_completed': True, 'reason': 'replayed'}


def policy(mode):
    def run(program, inputs, *, budget=4096, trace_limit=128):
        if mode == 'confirm':
            value = {'action': 'confirm', 'route_id': None}
        elif mode == 'repeat':
            value = {'action': 'attempt', 'route_id': 'baseline'}
        elif inputs['last_verified']:
            value = {'action': 'confirm', 'route_id': None}
        elif inputs['remaining'] == 0:
            value = {'action': 'hold', 'route_id': None}
        else:
            todo = [r['id'] for r in inputs['routes'] if r['id'] not in inputs['attempted']]
            value = {'action': 'attempt', 'route_id': todo[0]} if todo else {'action': 'hold', 'route_id': None}
        return {'result': {'schema': 't', 'status': 'completed', 'value': value, 'used': 1},
                'record': {'complete': True}}
    return run


def solve(mode='first', verdict=OK, **kw):
    facts, rules, target, routes = fixture()
    kw.setdefault('routes', routes)
    kw.setdefault('limit', 10)
    kw.setdefault('target', target)
    target = kw.pop('target')
    with mock.patch.object(grw, 'run_recorded', policy(mode)), \
            mock.patch.object(grw, 'verify_vm_record', lambda *a, **k: verdict):
        return grw.solve_verified_goal({'mode': mode}, facts, rules, target, **kw)


def fixture():
    ev = {'src': 't'}
    facts = [{'id': 'f%d' % i, 'triple': ['n%d' % i, 'p', 'n%d' % (i + 1)], 'evidence': ev} for i in range(8)]
    facts.append({'id': 'fs', 'triple': ['a', 's', 'b'], 'evidence': ev})
    rules = [{'id': 'r0', 'version': 1, 'body': [['?x', 'p', '?y'], ['?y', 'p', '?z']], 'head': ['?x', 'j', '?z']},
             {'id': 'r1', 'version': 1, 'body': [['?x', 's', '?y']], 'head': ['?x', 't', '?y']}]
    routes = [{'id': 'baseline', 'rule_ids': None}, {'id': 'rel', 'rule_ids': ['r1']}]
    return facts, rules, ['a', 't', 'b'], routes


class RouteWorkTests(unittest.TestCase):
    def test_fallback_confirms_and_keeps_bad_attempt(self):
        facts, rules, target, routes = fixture()
        before = copy.deepcopy((facts, rules, target, routes))
        out = solve()
        self.assertEqual(before, (facts, rules, target, routes))
        self.assertEqual(out['schema'], 'marco-verified-route-work-v1')
        self.assertEqual(out['status'], 'confirmed')
        self.assertEqual(out['conclusion'], target)
        self.assertEqual(out['goal'], target)
        self.assertEqual([a['route_id'] for a in out['attempts']], ['baseline', 'rel'])
        self.assertNotEqual(out['attempts'][0]['outcome'], 'verified')
        self.assertEqual(out['attempts'][1]['verification']['conclusion_verified'], True)
        self.assertTrue(out['strategy']['decisions'])

    def test_cap_and_all_held(self):
        out = solve(max_attempts=1)
        self.assertEqual((out['status'], out['conclusion'], len(out['attempts'])), ('held', None, 1))
        out = solve(target=['a', 't', 'zz'])
        self.assertEqual(out['status'], 'held')
        self.assertEqual(len(out['attempts']), 2)
        self.assertIsNone(out['conclusion'])

    def test_bad_inputs_hold(self):
        self.assertEqual(solve(max_attempts=9)['status'], 'held')
        self.assertEqual(solve(target=('a', 't', 'b'))['status'], 'held')
        self.assertEqual(solve(limit=0)['reason'], 'invalid_input')

    def test_duplicate_routes_rejected(self):
        base = {'id': 'baseline', 'rule_ids': None}
        same_id = [base, {'id': 'x', 'rule_ids': ['r1']}, {'id': 'x', 'rule_ids': ['r0']}]
        same_sel = [base, {'id': 'x', 'rule_ids': ['r0', 'r1']}]
        for routes in (same_id, same_sel):
            out = solve(routes=routes)
            self.assertEqual((out['status'], out['attempts']), ('held', []))

    def test_malicious_proposals(self):
        out = solve('confirm')
        self.assertEqual((out['status'], out['reason'], out['attempts']), ('held', 'early_confirm', []))
        out = solve('repeat')
        self.assertEqual((out['status'], out['reason']), ('held', 'repeated_route'))
        self.assertEqual(len(out['attempts']), 1)

    def test_tampered_strategy_receipt(self):
        out = solve(verdict={'valid': False, 'execution_completed': False, 'reason': 'replay_mismatch'})
        self.assertEqual((out['status'], out['reason']), ('held', 'strategy_replay'))
        self.assertEqual(out['attempts'], [])

    def test_make_routes_validation_and_truncation(self):
        facts, rules, target, routes = fixture()

        def make(value, status='completed', verdict=OK):
            def run(program, inputs, *, budget=4096, trace_limit=256):
                return {'result': {'schema': 't', 'status': status, 'value': value, 'used': 1},
                        'record': {'complete': True}}
            with mock.patch.object(grw, 'run_recorded', run), \
                    mock.patch.object(grw, 'verify_vm_record', lambda *a, **k: verdict):
                return grw.make_routes({'g': 1}, rules, target)
        good = make(routes)
        self.assertEqual(good['routes'], routes)
        self.assertEqual(set(good), {'routes', 'execution', 'verification'})
        bad = make([routes[1], routes[0]])
        self.assertEqual((bad['routes'], bad['verification']['reason']), ([], 'invalid_routes'))
        self.assertIsNotNone(bad['execution'])
        cut = make(routes, status='capacity',
                   verdict={'valid': True, 'execution_completed': False, 'reason': 'replayed'})
        self.assertEqual(cut['routes'], [])
        self.assertEqual(make(routes, verdict={'valid': False, 'execution_completed': False,
                                               'reason': 'replay_mismatch'})['routes'], [])
        unknown = make([routes[0], {'id': 'u', 'rule_ids': ['nope']}])
        self.assertEqual(unknown['routes'], [])

    def test_verified_turn_defaults_preserved(self):
        params = inspect.signature(verified_turn).parameters
        self.assertIsNone(params['strategy_program'].default)
        self.assertEqual(params['routes'].default, ())


class ActualRouteIntegrationTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        load = lambda name: json.loads((root / name).read_text())
        self.sentence = load('programs/foundation-verified-dialogue.json')
        self.catalog = load('programs/verified-route-catalog.json')
        self.strategy = load('programs/verified-route-strategy.json')
        seed = load('language_graphs/ko/foundation-bootstrap.json')
        for node, label in zip(seed['frame']['nodes'], ['소람', '여울', '화실', '서고']):
            node['value'] = label
        for row, label in zip(seed['model']['labels'], ['소람', '여울', '화실', '서고']):
            row['text'] = label
        seed = build_indexes(seed)
        self.model = seed['model']
        observed = verified_turn(self.sentence, seed['frame'], text='소람은 화실에 있다.',
                                 source_id='source:route-dialogue:observed', model=self.model)
        self.assertEqual(observed['status'], 'confirmed')
        self.frame = observed['frame']
        subject, other, target, unused = [x['id'] for x in seed['frame']['nodes']]
        self.target = [subject, self.model['relation'], target]
        for eid, a, rel, b in [('edge:route-noise', other, 'rel:route-spin', other),
                                ('edge:route-support', subject, 'rel:route-support', target)]:
            self.frame['edges'].append({'id': eid, 'source': a, 'relation': rel, 'target': b,
                                       'scope': self.model['scope'], 'evidence': []})
        self.rules = [
            {'id': 'route-noise', 'version': 1,
             'body': [['?x', 'rel:route-spin', '?y']], 'head': ['?x', 'rel:route-spin', '?y']},
            {'id': 'route-supported', 'version': 1,
             'body': [['?x', 'rel:route-support', '?y']],
             'head': ['?x', self.model['relation'], '?y']}]

    def query(self, **kw):
        return verified_turn(self.sentence, self.frame, text='소람은 어디에 있니?',
                             source_id='source:route-dialogue:question', model=self.model,
                             rules=self.rules, **kw)

    @staticmethod
    def literal(value):
        return {'schema': 'marco-graph-vm-program-v1', 'entry': 'return',
                'nodes': [{'id': 'return', 'op': 'return', 'value': {'literal': value}}]}

    def test_actual_sentence_same_inputs_retry_and_proof_gate(self):
        before = copy.deepcopy((self.frame, self.model, self.rules))
        old = self.query()
        self.assertEqual((old['status'], old['reason'], old['answer']),
                         ('held', 'proof_unverified', None))
        catalog = grw.make_routes(self.catalog, self.rules, self.target)
        self.assertTrue(catalog['verification']['valid'])
        with mock.patch.object(vgt, 'execute_frame_recorded', wraps=vgt.execute_frame_recorded) as sentence, \
                mock.patch.object(grw, 'build_proof_graph', wraps=grw.build_proof_graph) as baseline, \
                mock.patch.object(grw, 'build_route_proof_graph', wraps=grw.build_route_proof_graph) as alternate:
            new = self.query(strategy_program=self.strategy, routes=catalog['routes'])
        self.assertEqual(sentence.call_count, 1)
        self.assertEqual(baseline.call_count, 1)
        self.assertEqual(alternate.call_count, 1)
        self.assertEqual((new['status'], new['answer']), ('confirmed', '화실에 있다.'))
        self.assertEqual(new['proof']['goal'], self.target)
        attempts = new['proof']['attempts']
        self.assertEqual([x['route_id'] for x in attempts], ['baseline', 'route:route-supported'])
        self.assertFalse(attempts[0]['verification']['conclusion_verified'])
        self.assertTrue(attempts[1]['verification']['conclusion_verified'])
        self.assertTrue(all(x['record']['target'] == self.target for x in attempts))
        self.assertEqual(new['verification']['input_source']['text'], '소람은 어디에 있니?')
        self.assertEqual((self.frame, self.model, self.rules), before)

    def test_optin_unverified_work_cannot_publish_existing_answer(self):
        bad = self.literal({'action': 'confirm', 'route_id': None})
        out = self.query(strategy_program=bad, routes=[{'id': 'baseline', 'rule_ids': None}])
        self.assertEqual((out['status'], out['reason'], out['answer']),
                         ('held', 'proof_unverified', None))
        self.assertEqual(out['frame'], self.frame)
        self.assertEqual(out['proof']['reason'], 'early_confirm')

    def test_malformed_action_is_held(self):
        for action in ([], {}):
            out = grw.solve_verified_goal(self.literal({'action': action, 'route_id': None}),
                                         [], [], ['opaque:a', 'opaque:p', 'opaque:b'],
                                         routes=[{'id': 'baseline', 'rule_ids': None}])
            self.assertEqual((out['status'], out['reason']), ('held', 'bad_proposal'))
            self.assertEqual(out['attempts'], [])

    def test_replay_exception_preserves_actual_decision(self):
        with mock.patch.object(grw, 'verify_vm_record', side_effect=ValueError('new fixture')):
            out = grw.solve_verified_goal(self.strategy, [], [], self.target,
                                         routes=[{'id': 'baseline', 'rule_ids': None}])
        self.assertEqual((out['status'], out['reason']), ('held', 'strategy_error'))
        self.assertEqual(len(out['strategy']['decisions']), 1)
        self.assertIsNotNone(out['strategy']['decisions'][0]['execution'])
        self.assertEqual(out['attempts'], [])

    def test_duplicate_fact_ids_rejected_before_attempt(self):
        fact = {'id': 'duplicate-new', 'triple': self.target, 'evidence': []}
        out = grw.solve_verified_goal(self.strategy, [fact, copy.deepcopy(fact)], [], self.target,
                                     routes=[{'id': 'baseline', 'rule_ids': None}])
        self.assertEqual((out['status'], out['reason'], out['attempts']), ('held', 'invalid_input', []))
        self.assertEqual(out['goal'], self.target)


if __name__ == '__main__':
    unittest.main()
