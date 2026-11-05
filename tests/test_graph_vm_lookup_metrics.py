import unittest
from types import SimpleNamespace
from unittest import mock

from marco.reasoning import graph_vm
from tools import graph_runtime_metrics as metrics


def L(ref, key, default):
    return {'compute': {'op': 'lookup', 'args': [ref, key, default]}}


def lit(v):
    return {'literal': v}


def prog(value, pre=()):
    pre = list(pre)
    nodes = []
    for i, node in enumerate(pre):
        node = dict(node)
        node['id'] = 'n%d' % i
        node['next'] = 'n%d' % (i + 1) if i + 1 < len(pre) else 'ret'
        nodes.append(node)
    nodes.append({'id': 'ret', 'op': 'return', 'value': value})
    return {'schema': graph_vm.PROGRAM_SCHEMA, 'entry': nodes[0]['id'], 'nodes': nodes}


def run(value, inputs=None, pre=(), budget=4096):
    return graph_vm.run(prog(value, pre), {} if inputs is None else inputs, budget=budget)


class LookupTests(unittest.TestCase):
    def ok(self, r, value):
        self.assertEqual(r['schema'], graph_vm.RESULT_SCHEMA)
        self.assertEqual(r['status'], 'completed')
        self.assertEqual(r['value'], value)

    def bad(self, r, used_zero=False):
        self.assertEqual(r['status'], 'invalid')
        self.assertIsNone(r['value'])
        if used_zero:
            self.assertEqual(r['used'], 0)

    def test_present_missing_default_and_none(self):
        ref = {'input': ['m']}
        self.ok(run(L(ref, lit('a'), lit(0)), {'m': {'a': 5}}), 5)
        self.ok(run(L(ref, lit('b'), lit({'x': [1]})), {'m': {'a': 5}}), {'x': [1]})
        self.ok(run(L(ref, lit('a'), lit(7)), {'m': {'a': None}}), None)
        self.ok(run(L(ref, lit('z'), lit(None)), {'m': {}}), None)

    def test_nested_unicode_empty_key_and_index_path(self):
        inputs = {'o': {'p': {'\u00e9\u9375': 'v', '': 3}}, 'l': [{'k': 1}]}
        self.ok(run(L({'input': ['o', 'p']}, lit('\u00e9\u9375'), lit(0)), inputs), 'v')
        self.ok(run(L({'input': ['o', 'p']}, lit(''), lit(0)), inputs), 3)
        self.ok(run(L({'input': ['l', 0]}, lit('k'), lit(0)), inputs), 1)

    def test_computed_key_and_default(self):
        key = {'compute': {'op': 'concat', 'args': [lit('a'), lit('b')]}}
        self.ok(run(L({'input': ['m']}, key, lit(0)), {'m': {'ab': 2}}), 2)

    def test_exact_type_refusals(self):
        self.bad(run(L({'input': ['m']}, lit('a'), lit(0)), {'m': ['a']}))
        self.bad(run(L({'input': ['m']}, lit('a'), lit(0)), {'m': 'a'}))
        self.bad(run(L({'input': ['m']}, lit(0), lit(0)), {'m': {'0': 1}}))
        self.bad(run(L({'input': ['m']}, lit(None), lit(0)), {'m': {}}))

    def test_malformed_rejected_before_execution(self):
        ref = {'input': ['m']}
        inputs = {'m': {'a': 1}}
        cases = [
            {'compute': {'op': 'lookup', 'args': [ref, lit('a')]}},
            {'compute': {'op': 'lookup', 'args': [ref, lit('a'), lit(0), lit(0)]}},
            {'compute': {'op': 'lookups', 'args': [ref, lit('a'), lit(0)]}},
            L(lit({'a': 1}), lit('a'), lit(0)),
            L({'object': {'a': lit(1)}}, lit('a'), lit(0)),
            L({'array': []}, lit('a'), lit(0)),
            L({'compute': {'op': 'get', 'args': [ref, lit('a')]}}, lit('a'), lit(0)),
            L({'input': [-1]}, lit('a'), lit(0)),
            L({'var': []}, lit('a'), lit(0)),
            L(ref, {'bogus': 1}, lit(0)),
            L(ref, lit('a'), {'var': ['']}),
        ]
        for expr in cases:
            with self.subTest(expr=expr):
                self.bad(run(expr, inputs), used_zero=True)

    def test_var_reference_and_missing_reference(self):
        pre = [{'op': 'set', 'name': 'm', 'value': lit({'q': {'a': 9}})}]
        self.ok(run(L({'var': ['m', 'q']}, lit('a'), lit(0)), pre=pre), 9)
        self.bad(run(L({'var': ['nope']}, lit('a'), lit(0)), pre=pre))
        self.bad(run(L({'var': ['m', 'missing']}, lit('a'), lit(0)), pre=pre))
        self.bad(run(L({'input': ['missing']}, lit('a'), lit(0)), {'m': {}}))
        self.bad(run(L({'input': ['m', 3]}, lit('a'), lit(0)), {'m': {}}))

    def test_output_detached_and_inputs_unmutated(self):
        inputs = {'m': {'a': {'deep': [1, 2]}}}
        r = run(L({'input': ['m']}, lit('a'), lit(0)), inputs)
        self.ok(r, {'deep': [1, 2]})
        r['value']['deep'].append(3)
        self.assertEqual(inputs, {'m': {'a': {'deep': [1, 2]}}})
        self.assertIsNot(r['value'], inputs['m']['a'])

    def test_var_map_later_append_does_not_alter_result(self):
        pre = [
            {'op': 'set', 'name': 'lst', 'value': lit([1])},
            {'op': 'set', 'name': 'm', 'value': {'object': {'k': {'var': ['lst']}}}},
            {'op': 'set', 'name': 'r', 'value': L({'var': ['m']}, lit('k'), lit(None))},
            {'op': 'append', 'name': 'lst', 'value': lit(2)},
            {'op': 'append', 'name': 'r', 'value': lit(3)},
        ]
        value = {'object': {'r': {'var': ['r']}, 'lst': {'var': ['lst']}, 'm': {'var': ['m']}}}
        self.ok(run(value, pre=pre), {'r': [1, 3], 'lst': [1, 2], 'm': {'k': [1]}})

    def test_shared_budget_and_path_charges(self):
        expr = L({'input': ['m']}, lit('a'), lit(0))
        self.assertEqual(run(expr, {'m': {'a': 1}}, budget=0), graph_vm._result('capacity', None, 0))
        full = run(expr, {'m': {'a': 1}})
        self.ok(full, 1)
        used = full['used']
        self.assertGreater(used, 1)
        low = run(expr, {'m': {'a': 1}}, budget=used - 1)
        self.assertEqual(low['status'], 'capacity')
        self.assertEqual(low['used'], used - 1)
        self.assertEqual(run(expr, {'m': {'a': 1}}, budget=used)['status'], 'completed')
        deep = run(L({'input': ['x', 'y', 'm']}, lit('a'), lit(0)), {'x': {'y': {'m': {'a': 1}}}})
        self.ok(deep, 1)
        self.assertGreater(deep['used'], used)
        long_key = 'k' * 1000
        big = run(L({'input': ['m']}, lit(long_key), lit(0)), {'m': {long_key: 1}})
        self.ok(big, 1)
        self.assertGreater(big['used'], used)
        big_value = run(expr, {'m': {'a': 'v' * 2000}})
        self.assertGreater(big_value['used'], used)

    def test_strict_get_and_literal_unchanged(self):
        get = {'compute': {'op': 'get', 'args': [{'input': ['m']}, lit('b')]}}
        self.bad(run(get, {'m': {'a': 1}}))
        get_ok = {'compute': {'op': 'get', 'args': [{'input': ['m']}, lit('a')]}}
        self.ok(run(get_ok, {'m': {'a': None}}), None)
        r = run(lit({'a': [1, None]}))
        self.assertEqual(r, graph_vm._result('completed', {'a': [1, None]}, 1))


class MetricsTests(unittest.TestCase):
    def patched(self, platform, usages, clocks):
        fake_resource = SimpleNamespace(RUSAGE_SELF=0, getrusage=mock.Mock(side_effect=usages))
        fake_time = SimpleNamespace(perf_counter=mock.Mock(side_effect=clocks))
        return (mock.patch.object(metrics, 'sys', SimpleNamespace(platform=platform)),
                mock.patch.object(metrics, 'resource', fake_resource),
                mock.patch.object(metrics, 'time', fake_time))

    def usage(self, u, s, rss):
        return SimpleNamespace(ru_utime=u, ru_stime=s, ru_maxrss=rss)

    def measure_with(self, platform, fn, rss=200):
        a, b, c = self.patched(platform,
                               [self.usage(1.0, 0.5, 100), self.usage(1.75, 0.75, rss)],
                               [10.0, 12.5])
        with a, b, c:
            return metrics.measure(fn)

    def test_linux_kib_conversion_and_value(self):
        sentinel = object()
        out = self.measure_with('linux', lambda: sentinel)
        self.assertIs(out['value'], sentinel)
        m = out['metrics']
        self.assertEqual(m['wall_seconds'], 2.5)
        self.assertEqual(m['cpu_user_seconds'], 0.75)
        self.assertEqual(m['cpu_system_seconds'], 0.25)
        self.assertEqual(m['peak_rss_bytes'], 200 * 1024)
        self.assertEqual(m['peak_rss_scope'], 'whole-process-high-water-not-stage-delta')
        self.assertEqual(m['platform'], 'linux')
        self.assertIsInstance(m['peak_rss_bytes'], int)

    def test_darwin_bytes_and_args(self):
        a, b, c = self.patched('darwin',
                               [self.usage(0.0, 0.0, 1), self.usage(0.0, 0.0, 4096)],
                               [1.0, 1.0])
        with a, b, c:
            out = metrics.measure(lambda x, y=0: [x, y], 1, y=2)
        self.assertEqual(out['value'], [1, 2])
        self.assertEqual(out['metrics']['peak_rss_bytes'], 4096)
        self.assertEqual(out['metrics']['platform'], 'darwin')

    def test_peak_not_subtracted(self):
        out = self.measure_with('linux2', lambda: None, rss=100)
        self.assertEqual(out['metrics']['peak_rss_bytes'], 100 * 1024)

    def test_unsupported_platform_refused(self):
        fn = mock.Mock()
        a, b, c = self.patched('win32', [], [])
        with a, b, c:
            with self.assertRaises(ValueError):
                metrics.measure(fn)
        fn.assert_not_called()

    def test_exception_propagates_without_retry(self):
        class Boom(Exception):
            pass
        fn = mock.Mock(side_effect=Boom('x'))
        a, b, c = self.patched('linux',
                               [self.usage(0, 0, 1), self.usage(0, 0, 1)], [0.0, 1.0])
        with a, b, c:
            with self.assertRaises(Boom):
                metrics.measure(fn)
        self.assertEqual(fn.call_count, 1)


if __name__ == '__main__':
    unittest.main()
