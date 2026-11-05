import json
import pathlib

from marco.reasoning import graph_vm

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = {'id': 'baseline', 'rule_ids': None}


def _load(name):
    return json.loads((ROOT / 'programs' / name).read_text(encoding='utf-8'))


CATALOG = _load('verified-route-catalog.json')
STRATEGY = _load('verified-route-strategy.json')


def _rule(rule_id, body, head):
    return {'id': rule_id, 'version': 'v1', 'body': body, 'head': head}


def _tri(subject, predicate, obj):
    return [subject, predicate, obj]


def _h(predicate):
    return _tri('x', predicate, 'y')


def _run(program, inputs, trace=False):
    snapshot = json.loads(json.dumps(inputs))
    result = graph_vm.run(program, inputs)
    assert result['status'] == 'completed'
    assert inputs == snapshot
    if trace:
        receipt = graph_vm.run_recorded(program, inputs, trace_limit=256)
        assert receipt['result'] == result
        assert receipt['record']['complete'] is True
        assert inputs == snapshot
    return result['value']


def _catalog(rules, target):
    routes = _run(CATALOG, {'rules': rules, 'target': target}, trace=True)
    assert type(routes) is list
    assert routes[0] == BASELINE
    for route in routes:
        assert set(route) == {'id', 'rule_ids'}
    return routes


def _expected(*pairs):
    return [BASELINE] + [{'id': 'route:' + i, 'rule_ids': ids} for i, ids in pairs]


TARGET = _tri('s', 'q', 'o')


def test_baseline_only_without_matching_root():
    rules = [_rule('r1', [_h('p')], _h('w'))]
    assert _catalog(rules, TARGET) == [BASELINE]
    assert _catalog([], TARGET) == [BASELINE]


def test_root_with_one_hop_support_in_original_order():
    rules = [_rule('W', [_h('m')], _h('w')),
             _rule('A', [_h('p'), _h('w')], _h('q')),
             _rule('P', [_h('m')], _h('p'))]
    assert _catalog(rules, TARGET) == _expected(('A', ['A', 'W', 'P']))


def test_support_is_one_hop_only():
    rules = [_rule('A', [_h('p')], _h('q')),
             _rule('P', [_h('w')], _h('p')),
             _rule('Z', [_h('m')], _h('w'))]
    assert _catalog(rules, TARGET) == _expected(('A', ['A', 'P']))


def test_duplicate_support_and_root_ids_not_repeated():
    rules = [_rule('A', [_h('p'), _h('p')], _h('q')),
             _rule('P', [_h('m')], _h('p')),
             _rule('Z', [_h('m')], _h('z'))]
    assert _catalog(rules, TARGET) == _expected(('A', ['A', 'P']))
    rules = [_rule('A', [_h('q')], _h('q')),
             _rule('Z', [_h('m')], _h('z'))]
    assert _catalog(rules, TARGET) == _expected(('A', ['A']))


def test_selection_equal_to_full_list_is_skipped():
    rules = [_rule('A', [_h('p')], _h('q')),
             _rule('P', [_h('w')], _h('p'))]
    assert _catalog(rules, TARGET) == [BASELINE]
    reordered = [rules[1], rules[0]]
    assert _catalog(reordered, TARGET) == _expected(('A', ['A', 'P']))


def test_multiple_roots_in_original_order():
    rules = [_rule('A', [_h('z')], _h('q')),
             _rule('B', [_h('w')], _h('q')),
             _rule('C', [_h('m')], _h('z'))]
    assert _catalog(rules, TARGET) == _expected(('A', ['A', 'C']), ('B', ['B']))


def test_variable_predicate_yields_baseline_only():
    cases = [
        [_rule('A', [_h('p')], _h('q')), _rule('B', [_h('m')], _h('?h'))],
        [_rule('A', [_h('p')], _h('q')), _rule('B', [_h('m'), _h('?b')], _h('z'))],
        [_rule('A', [_h('?p')], _h('q')), _rule('P', [_h('m')], _h('p'))],
        [_rule('P', [_h('m')], _h('p')), _rule('A', [_h('p')], _h('q')),
         _rule('B', [_h('?r')], _h('z'))],
    ]
    for rules in cases:
        assert _catalog(rules, TARGET) == [BASELINE]


ROUTES = _expected(('A', ['A']), ('B', ['B']))
GOAL = _tri('s', 'q', 'o')


def _strategy(attempted, last_verified, remaining):
    inputs = {'goal': GOAL, 'routes': ROUTES, 'attempted': attempted,
              'last_verified': last_verified, 'remaining': remaining}
    value = _run(STRATEGY, inputs)
    assert set(value) == {'action', 'route_id'}
    return value


def test_strategy_baseline_first():
    assert _strategy({}, False, 3) == {'action': 'attempt', 'route_id': 'baseline'}
    assert _strategy({'baseline': False}, False, 3) == {'action': 'attempt', 'route_id': 'baseline'}


def test_strategy_next_unattempted():
    assert _strategy({'baseline': True}, False, 2) == {'action': 'attempt', 'route_id': 'route:A'}
    both = {'baseline': True, 'route:A': True}
    assert _strategy(both, False, 1) == {'action': 'attempt', 'route_id': 'route:B'}


def test_strategy_success_confirms_even_with_no_remaining():
    assert _strategy({'baseline': True}, True, 2) == {'action': 'confirm', 'route_id': None}
    assert _strategy({'baseline': True}, True, 0) == {'action': 'confirm', 'route_id': None}


def test_strategy_budget_exhaustion_holds():
    assert _strategy({}, False, 0) == {'action': 'hold', 'route_id': None}


def test_strategy_exhausted_routes_hold():
    done = {'baseline': True, 'route:A': True, 'route:B': True}
    assert _strategy(done, False, 2) == {'action': 'hold', 'route_id': None}
