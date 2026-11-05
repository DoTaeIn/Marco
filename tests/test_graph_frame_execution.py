"""Fresh host-boundary checks; no natural-language classifier or model load."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from marco.reasoning.graph_contract import SCHEMA, execute_frame


def empty_frame():
    return {'schema': SCHEMA, 'nodes': [], 'edges': [], 'sources': [], 'spans': []}


def constant_program(value):
    return {'schema': 'marco-graph-vm-program-v1', 'entry': 'return',
            'nodes': [{'id': 'return', 'op': 'return', 'value': {'literal': value}}]}


class GraphFrameExecutionTests(unittest.TestCase):
    def test_input_operation_markers_are_data_not_automatically_executed(self):
        frame = empty_frame()
        frame['nodes'].append({'id': 'node:literal', 'type': 'type:data', 'scope': 'scope:test',
                               'value': {'op': 'unrecognized', 'program': 'not-called'}})
        value = {'frame': frame, 'answer': None, 'status': 'untouched', 'evidence': ['node:literal']}
        before = deepcopy(frame)
        result = execute_frame(constant_program(value), frame, text='opaque input', source_id='source:new', model={})
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(frame, before)

    def test_existing_record_cannot_change_boolean_value_to_integer(self):
        frame = empty_frame()
        frame['nodes'].append({'id': 'node:old', 'type': 'type:data', 'scope': 'scope:test', 'value': True})
        changed = deepcopy(frame)
        changed['nodes'][0]['value'] = 1
        value = {'frame': changed, 'answer': None, 'status': 'unchanged', 'evidence': []}
        result = execute_frame(constant_program(value), frame, text='opaque', source_id='source:new', model={})
        self.assertEqual(result['status'], 'invalid')
        self.assertIsNone(result['value'])

    def test_forged_output_source_and_missing_evidence_are_not_returned(self):
        for damage in ('source', 'evidence'):
            with self.subTest(damage=damage):
                after = empty_frame()
                refs = []
                if damage == 'source':
                    import hashlib
                    after['sources'] = [{'id': 'source:forged', 'text': 'other',
                                         'sha256': hashlib.sha256(b'other').hexdigest()}]
                else:
                    refs = ['missing']
                value = {'frame': after, 'answer': None, 'status': 'opaque', 'evidence': refs}
                result = execute_frame(constant_program(value), empty_frame(), text='original',
                                       source_id='source:new', model={})
                self.assertEqual(result['status'], 'invalid')

    def test_append_only_also_preserves_existing_record_order(self):
        frame = empty_frame()
        frame['nodes'] = [{'id': 'node:'+name, 'type': 'type:data', 'scope': 'scope:test', 'value': name}
                          for name in ('a', 'b')]
        changed = deepcopy(frame)
        changed['nodes'].reverse()
        value = {'frame': changed, 'answer': None, 'status': 'opaque', 'evidence': []}
        result = execute_frame(constant_program(value), frame, text='original', source_id='source:new', model={})
        self.assertEqual(result['status'], 'invalid')

    def test_oversized_text_is_rejected_before_source_hashing(self):
        from marco.reasoning.graph_vm import MAXIMUM_PAYLOAD_UTF8_BYTES
        with patch('marco.reasoning.graph_contract.hashlib.sha256', side_effect=AssertionError('unbounded hash')):
            result = execute_frame(constant_program(None), empty_frame(),
                text='x'*(MAXIMUM_PAYLOAD_UTF8_BYTES+1), source_id='source:new', model={})
        self.assertEqual(result['status'], 'invalid')

    def test_source_identity_collision_and_zero_budget_do_not_run(self):
        frame = empty_frame()
        frame['nodes'].append({'id': 'edge:source:new', 'type': 'type:data', 'scope': 'scope:test', 'value': None})
        value = {'frame': frame, 'answer': None, 'status': 'opaque', 'evidence': []}
        result = execute_frame(constant_program(value), frame, text='original', source_id='source:new', model={})
        self.assertEqual(result['status'], 'invalid')
        result = execute_frame(constant_program(value), empty_frame(), text='original',
                               source_id='source:new', model={}, budget=0)
        self.assertEqual(result['status'], 'capacity')
        self.assertIsNone(result['value'])
