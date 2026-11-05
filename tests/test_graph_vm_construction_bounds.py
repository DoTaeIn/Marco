"""Fresh construction-boundary cases from source audit; no prior suite replay."""
import unittest

from marco.reasoning.graph_vm import PROGRAM_SCHEMA, run


def program(expression):
    return {'schema': PROGRAM_SCHEMA, 'entry': 'r',
            'nodes': [{'id': 'r', 'op': 'return', 'value': expression}]}


class GraphConstructionBoundsTests(unittest.TestCase):
    def test_large_object_key_consumes_shared_budget(self):
        small = program({'object': {'x': {'literal': None}}})
        large = program({'object': {'x'*8192: {'literal': None}}})
        baseline = run(small, {})
        self.assertEqual(baseline['status'], 'completed')
        complete = run(large, {})
        self.assertEqual(complete['status'], 'completed')
        self.assertGreater(complete['used'], baseline['used']+100)
        limited = run(large, {}, budget=baseline['used'])
        self.assertEqual(limited['status'], 'capacity')
        self.assertIsNone(limited['value'])

    def test_many_copied_items_refuse_before_success(self):
        expression = {'array': [{'input': ['items']} for _ in range(20)]}
        result = run(program(expression), {'items': [0]*500})
        self.assertEqual(result['status'], 'invalid')
        self.assertIsNone(result['value'])
