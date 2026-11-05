import copy
import importlib
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
graph_vm = importlib.import_module('marco.reasoning.graph_vm')
try:
    from tools.graph_reasoning_audit import verify_vm_record  # optional
except ImportError:
    verify_vm_record = None

with open(os.path.join(ROOT, 'programs', 'foundation-compositional-language.json'),
          encoding='utf-8') as handle:
    SOURCE = handle.read()
PROGRAM = json.loads(SOURCE)
with open(os.path.join(ROOT, 'programs', 'foundation-ground-language.json'),
          encoding='utf-8') as handle:
    ORIGINAL = json.loads(handle.read())

CELLS = (('composition_subject_markers', 'subject_markers', 'composition_object_markers'),
         ('composition_object_markers', 'object_markers', 'composition_orders'),
         ('composition_orders', 'orders', 'composition_seed_object_marker'),
         ('composition_seed_object_marker', 'seed_object_marker', 'mode_parse'))


def compile_template(subject_markers, object_markers, orders, seed):
    program = copy.deepcopy(PROGRAM)
    values = (list(subject_markers), list(object_markers), [list(o) for o in orders], seed)
    nodes = {node['id']: node for node in program['nodes']}
    for (ident, _, _), value in zip(CELLS, values):
        nodes[ident]['value']['literal'] = value
    return program


def strip_cells(program):
    program = copy.deepcopy(program)
    for node in program['nodes']:
        if node['id'] in [cell[0] for cell in CELLS]:
            node['value']['literal'] = None
    return program


def label(ident, text):
    return {'id': ident, 'text': text}


def pat(ident, kind, relation, polarity, prefix, between, suffix):
    return {'id': ident, 'kind': kind, 'relation': relation, 'polarity': polarity,
            'prefix': prefix, 'between': between, 'suffix': suffix}


def model(labels, patterns):
    by_id = {}
    for row in labels:
        by_id.setdefault(row['id'], row['text'])
    return {'labels': labels, 'labels_by_id': by_id, 'patterns': patterns}


def meaning(kind, subject, relation, obj, polarity):
    return {'kind': kind, 'triple': [subject, relation, obj], 'polarity': polarity}


HARIN, SEOJUN, KEY, MAP = 'person:harin', 'person:seojun', 'item:key', 'item:map'
LABELS = [label(HARIN, '하린'), label(SEOJUN, '서준'), label(KEY, '열쇠'), label(MAP, '지도')]
PATTERNS = [
    pat('has:fact:True', 'fact', 'has', True, '', '은 ', '를 가지고 있다.'),
    pat('has:fact:False', 'fact', 'has', False, '', '은 ', '를 가지고 있지 않다.'),
    pat('has:query:True', 'query', 'has', True, '', '은 ', '를 가지고 있나요?'),
    pat('checks:fact:True', 'fact', 'checks', True, '', '은 ', '를 확인했다.'),
    pat('checks:fact:False', 'fact', 'checks', False, '', '은 ', '를 확인하지 않았다.'),
    pat('checks:query:True', 'query', 'checks', True, '', '은 ', '를 확인했나요?'),
    pat('uses:fact:True', 'fact', 'uses', True, '', '은 ', '를 사용할 수 있다.'),
    pat('uses:fact:False', 'fact', 'uses', False, '', '은 ', '를 사용할 수 없다.'),
    pat('uses:query:True', 'query', 'uses', True, '', '은 ', '를 사용할 수 있나요?'),
]
MODEL = model(LABELS, PATTERNS)
CANON = compile_template(['은 '], ['를'], [[0, 1, 2]], '를')
SUBJ = compile_template(['은 ', '이 '], ['를'], [[0, 1, 2]], '를')
LEARNED = compile_template(['은 ', '이'], ['를', '를 '], [[0, 1, 2], [1, 0, 2]], '를')
AMB = compile_template(['은 '], ['은 '], [[0, 1, 2], [1, 0, 2]], '를')
N = len(LABELS) ** 2


class FoundationCompositionalLanguageTest(unittest.TestCase):
    def setUp(self):
        self.peak_used = 0
        self.peak_steps = 0

    def drive(self, program, mode, mdl, text, mean, allow_cap=False):
        state, seen = None, []
        for call in range(1, 129):
            inputs = {'mode': mode, 'model': mdl, 'text': text, 'meaning': mean, 'state': state}
            before = copy.deepcopy(inputs)
            receipt = graph_vm.run_recorded(program, inputs, budget=4096, trace_limit=256)
            self.assertEqual(inputs, before)
            result, record = receipt['result'], receipt['record']
            self.assertEqual(result['status'], 'completed')
            self.assertTrue(record['complete'])
            self.assertIsNone(record['reason'])
            self.assertLessEqual(result['used'], 4096)
            self.assertLessEqual(len(record['steps']), 256)
            self.peak_used = max(self.peak_used, result['used'])
            self.peak_steps = max(self.peak_steps, len(record['steps']))
            out = result['value']
            self.assertEqual(set(out), {'action', 'state', 'meaning', 'text', 'reason'})
            if out['action'] != 'continue':
                self.assertIn(out['action'], ('done', 'hold'))
                return out, call
            self.assertIsNone(out['meaning'])
            self.assertIsNone(out['text'])
            self.assertEqual(out['reason'], 'progress')
            self.assertIsInstance(out['state'], dict)
            self.assertNotIn(out['state'], seen)
            seen.append(out['state'])
            state = out['state']
        if allow_cap:
            return None, 128
        self.fail('no termination within 128 calls')

    def parse(self, program, text, mdl=MODEL, allow_cap=False):
        return self.drive(program, 'parse', mdl, text, None, allow_cap)

    def render(self, program, mean, mdl=MODEL):
        return self.drive(program, 'render', mdl, '', mean)

    def assertDone(self, out, mean, text=None):
        self.assertEqual(out['action'], 'done')
        self.assertEqual(out['meaning'], mean)
        self.assertEqual(out['reason'], 'complete')
        if text is not None:
            self.assertEqual(out['text'], text)

    def assertHold(self, out, reason):
        self.assertEqual(out['action'], 'hold')
        self.assertEqual(out['reason'], reason)
        self.assertIsNone(out['meaning'])
        self.assertIsNone(out['text'])

    def test_program_shape_and_language_free(self):
        graph_vm.validate_program(PROGRAM)
        self.assertLessEqual(len(PROGRAM['nodes']), 256)
        self.assertEqual(PROGRAM['entry'], 'composition_subject_markers')
        self.assertTrue(all(ord(char) < 128 for char in SOURCE))
        nodes = {node['id']: node for node in PROGRAM['nodes']}
        self.assertEqual(len(nodes), len(PROGRAM['nodes']))
        for ident, name, nxt in CELLS:
            empty = '' if name == 'seed_object_marker' else []
            self.assertEqual(nodes[ident], {'id': ident, 'op': 'set', 'name': name,
                                            'value': {'literal': empty}, 'next': nxt})
        self.assertEqual(ORIGINAL['entry'], 'mode_parse')

    def test_renderer_and_holds_preserved(self):
        nodes = {node['id']: node for node in PROGRAM['nodes']}
        kept = [node for node in ORIGINAL['nodes']
                if node['id'].startswith(('r_', 'hold_')) or node['id'] in ('mode_parse', 'mode_render')]
        self.assertTrue(kept)
        for node in kept:
            self.assertEqual(nodes[node['id']], node)

    def test_compile_patches_only_four_cells(self):
        for program in (CANON, SUBJ, LEARNED, AMB):
            graph_vm.validate_program(program)
            self.assertEqual(strip_cells(program), strip_cells(PROGRAM))

    def test_empty_template_holds(self):
        out, calls = self.parse(PROGRAM, '서준은 지도를 가지고 있다.')
        self.assertHold(out, 'unsupported')
        self.assertEqual(calls, 1)
        partial = compile_template(['은 '], ['를'], [[0, 1, 2]], '')
        out, calls = self.parse(partial, '서준은 지도를 가지고 있다.')
        self.assertHold(out, 'unsupported')
        self.assertEqual(calls, 1)
        mean = meaning('fact', SEOJUN, 'has', MAP, True)
        out, calls = self.render(PROGRAM, mean)
        self.assertDone(out, mean, '서준은 지도를 가지고 있다.')

    def test_canonical_forms(self):
        for row in PATTERNS:
            text = row['prefix'] + '서준' + row['between'] + '지도' + row['suffix']
            mean = meaning(row['kind'], SEOJUN, row['relation'], MAP, row['polarity'])
            out, calls = self.parse(CANON, text)
            self.assertDone(out, mean, text)
            self.assertEqual(calls, N + 2)
        out, calls = self.parse(LEARNED, '서준은 지도를 가지고 있다.')
        self.assertDone(out, meaning('fact', SEOJUN, 'has', MAP, True))
        self.assertEqual(calls, N * 4 + 2)

    def test_learned_subject_marker(self):
        out, calls = self.parse(SUBJ, '하린이 열쇠를 확인했다.')
        self.assertDone(out, meaning('fact', HARIN, 'checks', KEY, True))
        self.assertEqual(calls, N * 2 + 2)
        out, _ = self.parse(CANON, '하린이 열쇠를 확인했다.')
        self.assertHold(out, 'unsupported')

    def test_swapped_role_order(self):
        out, calls = self.parse(LEARNED, '지도를 서준이 가지고 있다.')
        self.assertDone(out, meaning('fact', SEOJUN, 'has', MAP, True))
        self.assertEqual(calls, N * 4 + 2)
        out, _ = self.parse(LEARNED, '열쇠를 하린이 확인했다.')
        self.assertDone(out, meaning('fact', HARIN, 'checks', KEY, True))
        out, _ = self.parse(CANON, '지도를 서준이 가지고 있다.')
        self.assertHold(out, 'unsupported')

    def test_unseen_combination_across_predicate(self):
        out, _ = self.parse(LEARNED, '지도를 서준이 사용할 수 없다.')
        self.assertDone(out, meaning('fact', SEOJUN, 'uses', MAP, False))
        out, _ = self.parse(LEARNED, '열쇠를 서준이 확인했나요?')
        self.assertDone(out, meaning('query', SEOJUN, 'checks', KEY, True))
        out, _ = self.parse(SUBJ, '열쇠이 하린를 사용할 수 있나요?')
        self.assertDone(out, meaning('query', KEY, 'uses', HARIN, True))
        out, _ = self.parse(CANON, '열쇠은 하린를 확인했다.')
        self.assertDone(out, meaning('fact', KEY, 'checks', HARIN, True))

    def test_negative_polarity_preserved(self):
        out, _ = self.parse(CANON, '서준은 지도를 가지고 있지 않다.')
        self.assertDone(out, meaning('fact', SEOJUN, 'has', MAP, False))
        out, _ = self.parse(LEARNED, '지도를 하린이 확인하지 않았다.')
        self.assertDone(out, meaning('fact', HARIN, 'checks', MAP, False))

    def test_query_not_fact(self):
        out, _ = self.parse(CANON, '서준은 지도를 사용할 수 있나요?')
        self.assertDone(out, meaning('query', SEOJUN, 'uses', MAP, True))
        self.assertNotEqual(out['meaning']['kind'], 'fact')

    def test_quote_and_unknown_unsupported(self):
        for text in ['"서준은 지도를 가지고 있다."', '서준은 지도를 먹었다.',
                     '서준은 지도를 가지고 있다', '서준은 지도를 가지고 있다. ',
                     ' 서준은 지도를 가지고 있다.', '서준은  지도를 가지고 있다.',
                     '민준은 지도를 가지고 있다.', '서준은 지도를 가지고 있지', '']:
            out, calls = self.parse(LEARNED, text)
            self.assertHold(out, 'unsupported')
            self.assertEqual(calls, N * 4 + 2)

    def test_repeated_role_ambiguous_and_alias_dedup(self):
        out, _ = self.parse(AMB, '서준은 지도은  가지고 있다.')
        self.assertHold(out, 'ambiguous')
        out, calls = self.parse(AMB, '서준은 서준은  가지고 있다.')
        self.assertDone(out, meaning('fact', SEOJUN, 'has', SEOJUN, True))
        self.assertEqual(calls, N + 2)
        alias = model(LABELS + [label(SEOJUN, '서준')], PATTERNS)
        out, calls = self.parse(CANON, '서준은 지도를 가지고 있다.', alias)
        self.assertDone(out, meaning('fact', SEOJUN, 'has', MAP, True))
        self.assertEqual(calls, 27)
        other = model(LABELS + [label('person:other', '서준')], PATTERNS)
        out, _ = self.parse(CANON, '서준은 지도를 가지고 있다.', other)
        self.assertHold(out, 'ambiguous')
        twice = compile_template(['은 ', '은 '], ['를'], [[0, 1, 2], [0, 1, 2]], '를')
        out, calls = self.parse(twice, '서준은 지도를 가지고 있다.')
        self.assertDone(out, meaning('fact', SEOJUN, 'has', MAP, True))
        self.assertEqual(calls, N * 2 + 2)

    def test_canonical_render_roundtrip(self):
        for row in PATTERNS:
            for subj, obj, stext, otext in ((SEOJUN, MAP, '서준', '지도'), (HARIN, KEY, '하린', '열쇠')):
                mean = meaning(row['kind'], subj, row['relation'], obj, row['polarity'])
                text = row['prefix'] + stext + row['between'] + otext + row['suffix']
                out, calls = self.render(LEARNED, mean)
                self.assertDone(out, mean, text)
                self.assertEqual(calls, 1)
                back, _ = self.parse(LEARNED, out['text'])
                self.assertDone(back, mean, text)

    def test_inputs_unchanged(self):
        mdl = copy.deepcopy(MODEL)
        program = copy.deepcopy(LEARNED)
        self.parse(program, '지도를 서준이 가지고 있다.', mdl)
        self.assertEqual(mdl, MODEL)
        self.assertEqual(program, LEARNED)

    def test_receipt_replay_valid(self):
        inputs = {'mode': 'parse', 'model': MODEL, 'text': '서준은 지도를 가지고 있다.',
                  'meaning': None, 'state': None}
        first = graph_vm.run_recorded(LEARNED, copy.deepcopy(inputs), budget=4096, trace_limit=256)
        state = first['result']['value']['state']
        self.assertEqual(state, {'si': 0, 'oi': 0, 'smi': 0, 'omi': 0, 'found': []})
        step = dict(inputs, state=state)
        for inp in (inputs, step):
            a = graph_vm.run_recorded(LEARNED, copy.deepcopy(inp), budget=4096, trace_limit=256)
            b = graph_vm.run_recorded(LEARNED, copy.deepcopy(inp), budget=4096, trace_limit=256)
            self.assertEqual(a, b)
            self.assertTrue(a['record']['complete'])
            if verify_vm_record is not None:
                v = verify_vm_record(copy.deepcopy(a), copy.deepcopy(LEARNED), copy.deepcopy(inp),
                                     max_budget=4096)
                self.assertIs(v.get('valid'), True)
                self.assertIs(v.get('execution_completed'), True)

    def test_budget_trace_caps(self):
        self.parse(LEARNED, '서준은 지도를 사용할 수 있나요?')
        self.parse(LEARNED, '지도를 서준이 사용할 수 없다.')
        self.parse(AMB, '서준은 서준은  가지고 있다.')
        self.assertLess(self.peak_used, 4096)
        self.assertLessEqual(self.peak_steps, 256)
        self.assertGreater(self.peak_steps, 0)

    def test_malformed_template_rejected(self):
        bad = [
            (['은 '], ['를'], [[0, 2, 1]], '를'),
            (['은 '], ['를'], [[0, 1]], '를'),
            (['은 '], ['를'], [[0, 1, 2], [1, 0, 2], [0, 1, 2]], '를'),
            (['은 ', '이 ', '가 '], ['를'], [[0, 1, 2]], '를'),
            (['은 '], ['를', '을', '도'], [[0, 1, 2]], '를'),
            (['은 '], ['를'], [[0, 1, 2]], '을'),
            (['은 '], ['를'], [[0, 1, 2]], '를 가'),
        ]
        for cells in bad:
            out, calls = self.parse(compile_template(*cells), '서준은 지도를 가지고 있다.')
            self.assertHold(out, 'malformed')
            self.assertEqual(calls, 1)
        for cells in [([], ['를'], [[0, 1, 2]], '를'), (['은 '], [], [[0, 1, 2]], '를'),
                      (['은 '], ['를'], [], '를')]:
            out, calls = self.parse(compile_template(*cells), '서준은 지도를 가지고 있다.')
            self.assertHold(out, 'unsupported')
            self.assertEqual(calls, 1)

    def test_old_checks_preserved(self):
        out, calls = self.drive(LEARNED, 'learn', MODEL, '', None)
        self.assertHold(out, 'malformed')
        self.assertEqual(calls, 1)
        out, _ = self.drive(LEARNED, 'parse', MODEL, '서준', meaning('fact', SEOJUN, 'has', MAP, True))
        self.assertHold(out, 'malformed')
        old_state = {'mode': 'parse', 'model': MODEL, 'text': '서준', 'meaning': None,
                     'state': {'si': 0, 'oi': 0, 'found': []}}
        res = graph_vm.run(LEARNED, old_state, budget=4096)
        self.assertEqual(res['value']['reason'], 'malformed')
        negq = model(LABELS, PATTERNS + [pat('PX', 'query', 'has', False, '', '은 ', '를 안 가지고 있나요?')])
        out, _ = self.parse(LEARNED, '서준은 지도를 가지고 있다.', negq)
        self.assertHold(out, 'unsupported')
        odd = model(LABELS, PATTERNS + [pat('PY', 'other', 'has', True, '', '은 ', '를 x')])
        out, _ = self.parse(LEARNED, '서준은 지도를 가지고 있다.', odd)
        self.assertHold(out, 'malformed')

    def test_termination(self):
        out, calls = self.parse(LEARNED, '하린은 열쇠를 가지고 있다.')
        self.assertDone(out, meaning('fact', HARIN, 'has', KEY, True))
        self.assertEqual(calls, N * 4 + 2)
        extra = [label('person:doyun', '도윤'), label('person:minseo', '민서'),
                 label('item:book', '책'), label('item:pen', '펜')]
        wide = model(LABELS + extra, PATTERNS)
        out, calls = self.parse(CANON, '도윤은 펜를 가지고 있다.', wide)
        self.assertDone(out, meaning('fact', 'person:doyun', 'has', 'item:pen', True))
        self.assertEqual(calls, 66)
        out, calls = self.parse(LEARNED, '도윤은 펜를 가지고 있다.', wide, allow_cap=True)
        self.assertIsNone(out)
        self.assertEqual(calls, 128)


if __name__ == '__main__':
    unittest.main()
