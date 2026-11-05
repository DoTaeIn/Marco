"""Foundation contracts only, not natural-language comprehension tests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import unittest

from marco.reasoning.graph_contract import SCHEMA, source_span, validate_frame
from marco.reasoning.graph_vm import run


def frame():
    text = '가\u0301 나'
    return {'schema': SCHEMA,
        'nodes': [{'id': 'entity:a', 'type': 'type:opaque', 'scope': 'scope:one', 'value': 'A'},
                  {'id': 'entity:b', 'type': 'type:opaque', 'scope': 'scope:one', 'value': 'B'}],
        'edges': [{'id': 'edge:one', 'source': 'entity:a', 'relation': 'relation:one',
                   'target': 'entity:b', 'scope': 'scope:one', 'evidence': ['span:one']}],
        'sources': [{'id': 'source:one', 'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest()}],
        'spans': [{'id': 'span:one', 'source': 'source:one', 'start': 0, 'end': 2}]}


def program():
    return json.loads((Path(__file__).resolve().parents[1]/'programs/graph-frame-query.json').read_text())


def pattern(relation):
    return {'id': {'capture': 'edge'}, 'source': {'capture': 'source'}, 'relation': relation,
            'target': {'capture': 'target'}, 'scope': 'scope:one', 'evidence': {'capture': 'evidence'}}


class GraphNativeFoundationTests(unittest.TestCase):
    def test_graph_data_controls_bindings_with_original_evidence_and_no_mutation(self):
        graph = frame()
        before = deepcopy(graph)
        query = program()
        first = run(query, {'records': validate_frame(graph)['edges'], 'pattern': pattern('relation:one')})
        assert first['status'] == 'completed'
        assert first['value'] == [{'edge': 'edge:one', 'source': 'entity:a', 'target': 'entity:b', 'evidence': ['span:one']}]
        graph['edges'][0]['relation'] = 'relation:new'
        assert run(query, {'records': validate_frame(graph)['edges'], 'pattern': pattern('relation:one')})['value'] == []
        second = run(query, {'records': validate_frame(graph)['edges'], 'pattern': pattern('relation:new')})
        assert second['value'] == first['value']
        graph['edges'][0]['relation'] = 'relation:one'
        assert graph == before
        assert query == program()


    def test_source_coordinates_preserve_combining_characters_and_return_detached_data(self):
        original = frame()
        validated = validate_frame(original)
        assert source_span(validated, 'span:one') == '가\u0301'
        validated['nodes'][0]['value'] = 'changed'
        assert original['nodes'][0]['value'] == 'A'


    def test_invalid_graph_evidence_is_rejected(self):
        for damage in ('duplicate', 'endpoint', 'source_hash', 'span_bool', 'missing_evidence'):
            with self.subTest(damage=damage):
                graph = frame()
                if damage == 'duplicate':
                    graph['nodes'][1]['id'] = 'entity:a'
                elif damage == 'endpoint':
                    graph['edges'][0]['target'] = 'missing'
                elif damage == 'source_hash':
                    graph['sources'][0]['text'] += '!'
                elif damage == 'span_bool':
                    graph['spans'][0]['start'] = False
                else:
                    graph['edges'][0]['evidence'] = ['missing']
                with self.assertRaises(ValueError):
                    validate_frame(graph)


    def test_scope_matching_and_budget_do_not_silently_return_partial_success(self):
        graph = validate_frame(frame())
        graph['edges'][0]['scope'] = 'scope:other'
        assert run(program(), {'records': graph['edges'], 'pattern': pattern('relation:one')})['value'] == []
        result = run(program(), {'records': graph['edges'], 'pattern': pattern('relation:one')}, budget=2)
        assert result['status'] == 'capacity'
        assert result['value'] is None
