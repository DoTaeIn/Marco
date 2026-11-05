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
    from tools.graph_reasoning_audit import verify_vm_record  # optional; not required here
except ImportError:
    verify_vm_record = None

with open(os.path.join(ROOT, 'programs', 'foundation-ground-language.json'),
          encoding='utf-8') as handle:
    SOURCE = handle.read()
PROGRAM = json.loads(SOURCE)


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


LABELS = [label('E1', '철수'), label('E2', '영희'), label('C1', '서울'), label('C2', '부산')]
PATTERNS = [
    pat('P1', 'fact', 'R_KNOWS', True, '', '이(가) ', '을(를) 안다.'),
    pat('P2', 'fact', 'R_KNOWS', False, '', '이(가) ', '을(를) 모른다.'),
    pat('P3', 'query', 'R_KNOWS', True, '', '이(가) ', '을(를) 아나요?'),
    pat('P4', 'fact', 'R_LIVES', True, '', '은(는) ', '에 산다.'),
    pat('P5', 'fact', 'R_LIVES', False, '', '은(는) ', '에 살지 않는다.'),
    pat('P6', 'query', 'R_LIVES', True, '', '은(는) ', '에 사나요?'),
]
MODEL = model(LABELS, PATTERNS)
FULL = len(LABELS) ** 2 + 2


class FoundationGroundLanguageTest(unittest.TestCase):
    def drive(self, mode, mdl, text, mean):
        state = None
        for call in range(1, 129):
            inputs = {'mode': mode, 'model': mdl, 'text': text, 'meaning': mean, 'state': state}
            before = copy.deepcopy(inputs)
            receipt = graph_vm.run_recorded(PROGRAM, inputs, budget=4096, trace_limit=256)
            self.assertEqual(inputs, before)
            result, record = receipt['result'], receipt['record']
            self.assertEqual(result['status'], 'completed')
            self.assertTrue(record['complete'])
            self.assertIsNone(record['reason'])
            self.assertLessEqual(result['used'], 4096)
            self.assertLessEqual(len(record['steps']), 256)
            out = result['value']
            self.assertEqual(set(out), {'action', 'state', 'meaning', 'text', 'reason'})
            if out['action'] != 'continue':
                self.assertIn(out['action'], ('done', 'hold'))
                return out, call
            self.assertIsNone(out['meaning'])
            self.assertIsNone(out['text'])
            self.assertEqual(out['reason'], 'progress')
            self.assertIsInstance(out['state'], dict)
            self.assertNotEqual(out['state'], state)
            state = out['state']
        self.fail('no termination within 128 calls')

    def parse(self, text, mdl=MODEL):
        return self.drive('parse', mdl, text, None)

    def render(self, mean, mdl=MODEL):
        return self.drive('render', mdl, '', mean)

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

    def test_program_valid_and_language_free(self):
        graph_vm.validate_program(PROGRAM)
        self.assertLessEqual(len(PROGRAM['nodes']), 256)
        self.assertTrue(all(ord(char) < 128 for char in SOURCE))

    def test_parse_full_search_and_unseen_combinations(self):
        cases = [
            ('철수이(가) 영희을(를) 안다.', meaning('fact', 'E1', 'R_KNOWS', 'E2', True)),
            ('부산이(가) 철수을(를) 안다.', meaning('fact', 'C2', 'R_KNOWS', 'E1', True)),
            ('영희은(는) 부산에 산다.', meaning('fact', 'E2', 'R_LIVES', 'C2', True)),
            ('철수은(는) 서울에 살지 않는다.', meaning('fact', 'E1', 'R_LIVES', 'C1', False)),
            ('영희이(가) 철수을(를) 모른다.', meaning('fact', 'E2', 'R_KNOWS', 'E1', False)),
            ('영희이(가) 철수을(를) 아나요?', meaning('query', 'E2', 'R_KNOWS', 'E1', True)),
            ('철수은(는) 부산에 사나요?', meaning('query', 'E1', 'R_LIVES', 'C2', True)),
        ]
        for text, mean in cases:
            out, calls = self.parse(text)
            self.assertDone(out, mean, text)
            self.assertEqual(calls, FULL)

    def test_unknown_expressions_unsupported(self):
        for text in ['민수이(가) 영희을(를) 안다.', '철수이(가) 영희을(를) 안다. ',
                     ' 철수이(가) 영희을(를) 안다.', '철수이(가)  영희을(를) 안다.',
                     '철수이(가) 영희을(를) 좋아한다.', '철수 영희', '']:
            out, calls = self.parse(text)
            self.assertHold(out, 'unsupported')
            self.assertEqual(calls, FULL)

    def test_distinct_meanings_ambiguous_even_late(self):
        late = model(LABELS + [label('E3', '영희')], PATTERNS)
        out, _ = self.parse('철수이(가) 영희을(를) 안다.', late)
        self.assertHold(out, 'ambiguous')
        twin = model(LABELS, PATTERNS + [pat('P7', 'fact', 'R_LIKES', True, '', '이(가) ', '을(를) 안다.')])
        out, _ = self.parse('철수이(가) 영희을(를) 안다.', twin)
        self.assertHold(out, 'ambiguous')

    def test_same_meaning_duplicates_dedup(self):
        dup = model(LABELS + [label('E2', '영희')], PATTERNS + [dict(PATTERNS[0], id='P1b')])
        out, calls = self.parse('철수이(가) 영희을(를) 안다.', dup)
        self.assertDone(out, meaning('fact', 'E1', 'R_KNOWS', 'E2', True))
        self.assertEqual(calls, len(dup['labels']) ** 2 + 2)

    def test_overlap_and_separator_names(self):
        grammar = [pat('Q1', 'fact', 'R_KNOWS', True, '', '', '를 안다.')]
        names = [label('K1', '가'), label('K2', '가나'), label('K3', '다')]
        out, _ = self.parse('가나다를 안다.', model(names, grammar))
        self.assertDone(out, meaning('fact', 'K2', 'R_KNOWS', 'K3', True))
        out, _ = self.parse('가나다를 안다.', model(names + [label('K4', '나다')], grammar))
        self.assertHold(out, 'ambiguous')
        odd = model([label('N1', '이(가) 영'), label('N2', '희')], PATTERNS[:1])
        out, _ = self.parse('이(가) 영이(가) 희을(를) 안다.', odd)
        self.assertDone(out, meaning('fact', 'N1', 'R_KNOWS', 'N2', True))

    def test_render_roundtrip(self):
        cases = [
            (meaning('fact', 'E1', 'R_KNOWS', 'E2', True), '철수이(가) 영희을(를) 안다.'),
            (meaning('fact', 'E1', 'R_LIVES', 'C1', False), '철수은(는) 서울에 살지 않는다.'),
            (meaning('query', 'E2', 'R_KNOWS', 'C2', True), '영희이(가) 부산을(를) 아나요?'),
            (meaning('query', 'E1', 'R_LIVES', 'C2', True), '철수은(는) 부산에 사나요?'),
        ]
        for mean, text in cases:
            out, calls = self.render(mean)
            self.assertDone(out, mean, text)
            self.assertEqual(calls, 1)
            back, _ = self.parse(out['text'])
            self.assertDone(back, mean, text)

    def test_render_canonical_label_and_first_template(self):
        alt = pat('P1x', 'fact', 'R_KNOWS', True, '', '이(가) ', '을(를) 알고 있다.')
        mdl = model([label('E1', '철수'), label('E1', '철수씨'), label('E2', '영희')],
                    [PATTERNS[0], alt])
        mean = meaning('fact', 'E1', 'R_KNOWS', 'E2', True)
        out, _ = self.render(mean, mdl)
        self.assertDone(out, mean, '철수이(가) 영희을(를) 안다.')
        back, _ = self.parse('철수씨이(가) 영희을(를) 알고 있다.', mdl)
        self.assertDone(back, mean)

    def test_render_holds(self):
        out, _ = self.render(meaning('fact', 'E9', 'R_KNOWS', 'E2', True))
        self.assertHold(out, 'unrealizable')
        out, _ = self.render(meaning('fact', 'E1', 'R_NONE', 'E2', True))
        self.assertHold(out, 'unrealizable')
        facts = model(LABELS, [row for row in PATTERNS if row['kind'] == 'fact'])
        out, _ = self.render(meaning('query', 'E1', 'R_KNOWS', 'E2', True), facts)
        self.assertHold(out, 'unrealizable')
        out, _ = self.render(meaning('query', 'E1', 'R_KNOWS', 'E2', False))
        self.assertHold(out, 'unsupported')
        out, _ = self.render({'kind': 'fact', 'triple': ['E1', 'R_KNOWS'], 'polarity': True})
        self.assertHold(out, 'malformed')

    def test_replaced_model_without_program_change(self):
        mdl = model([label('A1', '고양이'), label('A2', '쥐'), label('A3', '개')], [
            pat('C1', 'fact', 'R_CHASE', True, '', '가 ', '를 쫓는다.'),
            pat('C2', 'fact', 'R_CHASE', False, '', '가 ', '를 쫓지 않는다.'),
            pat('C3', 'query', 'R_CHASE', True, '', '가 ', '를 쫓나요?'),
            pat('C4', 'fact', 'R_FEAR', True, '', '는 ', '를 무서워한다.'),
        ])
        out, _ = self.parse('개가 고양이를 쫓지 않는다.', mdl)
        self.assertDone(out, meaning('fact', 'A3', 'R_CHASE', 'A1', False))
        mean = meaning('fact', 'A2', 'R_FEAR', 'A1', True)
        out, _ = self.render(mean, mdl)
        self.assertDone(out, mean, '쥐는 고양이를 무서워한다.')
        back, _ = self.parse(out['text'], mdl)
        self.assertDone(back, mean)

    def test_maximum_declared_workload(self):
        words = ['하나', '둘', '셋', '넷', '다섯', '여섯', '일곱', '여덟']
        labels = [label('N%d' % index, word) for index, word in enumerate(words)]
        patterns = []
        for index in range(12):
            query = index % 3 == 0
            patterns.append(pat('W%d' % index, 'query' if query else 'fact', 'R%d' % (index // 2),
                                True if query else index % 2 == 0, '', '와(과) ', '의 관계%d.' % index))
        mdl = model(labels, patterns)
        text = '여덟와(과) 일곱의 관계11.'
        mean = meaning('fact', 'N7', 'R5', 'N6', False)
        out, calls = self.parse(text, mdl)
        self.assertDone(out, mean, text)
        self.assertEqual(calls, 66)
        out, _ = self.render(mean, mdl)
        self.assertDone(out, mean, text)

    def test_malformed_inputs(self):
        out, calls = self.drive('learn', MODEL, '', None)
        self.assertHold(out, 'malformed')
        self.assertEqual(calls, 1)
        out, _ = self.drive('parse', MODEL, '철수', meaning('fact', 'E1', 'R_KNOWS', 'E2', True))
        self.assertHold(out, 'malformed')
        out, _ = self.drive('render', MODEL, '철수', meaning('fact', 'E1', 'R_KNOWS', 'E2', True))
        self.assertHold(out, 'malformed')
        negq = model(LABELS, PATTERNS + [pat('PX', 'query', 'R_KNOWS', False, '', '이(가) ', '을(를) 모르나요?')])
        out, _ = self.parse('철수이(가) 영희을(를) 안다.', negq)
        self.assertHold(out, 'unsupported')


if __name__ == '__main__':
    unittest.main()
