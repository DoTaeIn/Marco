import copy
import hashlib
import json
import unittest
from pathlib import Path

from marco.reasoning import graph_vm
from marco.reasoning.graph_contract import execute_frame, validate_frame

ROOT = Path(__file__).resolve().parents[1]
PROGRAM_PATH = ROOT / 'programs' / 'foundation-dialogue.json'
SEED_PATH = ROOT / 'language_graphs' / 'ko' / 'foundation-bootstrap.json'

STATE_FACT = '민준은 부엌에 있다.'
QUERY = '민준은 어디에 있니?'


def load(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


class GraphFoundationDialogueTest(unittest.TestCase):
    def setUp(self):
        self.program_bytes = PROGRAM_PATH.read_bytes()
        self.program = json.loads(self.program_bytes.decode('utf-8'))
        seed = load(SEED_PATH)
        self.frame = seed['frame']
        self.model = seed['model']

    def run_turn(self, frame, text, source_id, model=None, budget=4096):
        return execute_frame(
            self.program, frame, text=text, source_id=source_id,
            model=self.model if model is None else model, budget=budget)

    def completed(self, envelope):
        self.assertEqual(envelope['status'], 'completed')
        value = envelope['value']
        self.assertEqual(set(value), {'frame', 'answer', 'status', 'evidence'})
        validate_frame(value['frame'])
        return value

    def observe(self, frame, text, source_id, model=None):
        used = self.model if model is None else model
        value = self.completed(self.run_turn(frame, text, source_id, model))
        self.assertEqual(value['status'], used['responses']['observed']['status'])
        return value['frame']

    def test_seed_is_valid_and_empty_of_facts(self):
        frame = validate_frame(self.frame)
        self.assertEqual((frame['edges'], frame['sources'], frame['spans']), ([], [], []))
        node_ids = {row['id'] for row in frame['nodes']}
        self.assertGreaterEqual(len(node_ids), 4)
        for label in self.model['labels']:
            self.assertIn(label['id'], node_ids)

    def test_observation_then_query(self):
        first = self.run_turn(self.frame, STATE_FACT, 'source:turn1')
        value = self.completed(first)
        self.assertEqual(value['status'], 'observed')
        frame = value['frame']
        self.assertEqual(len(frame['edges']), 1)
        edge = frame['edges'][0]
        self.assertEqual(edge['id'], 'edge:source:turn1')
        self.assertEqual(edge['source'], 'node:minjun')
        self.assertEqual(edge['target'], 'node:kitchen')
        self.assertEqual(edge['relation'], self.model['relation'])
        self.assertEqual(edge['scope'], self.model['scope'])
        self.assertEqual(edge['evidence'], ['span:source:turn1'])
        self.assertEqual(value['evidence'], ['edge:source:turn1', 'span:source:turn1'])
        source = frame['sources'][0]
        self.assertEqual(source['id'], 'source:turn1')
        self.assertEqual(source['text'], STATE_FACT)
        span = frame['spans'][0]
        self.assertEqual((span['source'], span['start'], span['end']),
                         ('source:turn1', 0, len(STATE_FACT)))
        self.assertEqual(frame['nodes'], self.frame['nodes'])

        second = self.completed(self.run_turn(frame, QUERY, 'source:turn2'))
        self.assertEqual(second['status'], 'answered')
        self.assertEqual(second['answer'], '부엌에 있다.')
        self.assertEqual(second['evidence'], ['edge:source:turn1'])
        self.assertEqual(second['frame'], frame)

    def test_query_creates_no_facts(self):
        value = self.completed(self.run_turn(self.frame, QUERY, 'source:turn1'))
        self.assertEqual(value['frame'], self.frame)
        self.assertEqual(value['frame']['edges'], [])

    def test_old_records_preserved(self):
        frame = self.observe(self.frame, STATE_FACT, 'source:turn1')
        later = self.observe(frame, '서진은 거실에 있다.', 'source:turn2')
        self.assertEqual(later['edges'][0], frame['edges'][0])
        self.assertEqual(later['sources'][0], frame['sources'][0])
        self.assertEqual(later['spans'][0], frame['spans'][0])
        self.assertEqual(len(later['edges']), 2)
        value = self.completed(self.run_turn(later, '서진은 어디에 있니?', 'source:turn3'))
        self.assertEqual(value['answer'], '거실에 있다.')
        self.assertEqual(value['evidence'], ['edge:source:turn2'])

    def test_rejected_texts_leave_frame_unchanged(self):
        quote = chr(34)
        texts = [
            '도윤은 부엌에 있다.',
            '민준은 마당에 있다.',
            quote + '민준은 부엌에 있다.' + quote,
            '민준은 부엌에 없다.',
            '민준은 부엌에 있다 그리고.',
            '민준은 부엌에 있다. 서진은 거실에 있다.',
            '민준은 부엌에 있다.!',
            ' 민준은 부엌에 있다.',
            '도윤은 어디에 있니?',
            '민준은 어디에 있니',
            '민준은 어디에 없니?',
            '',
        ]
        frame = self.observe(self.frame, STATE_FACT, 'source:turn1')
        for base in (self.frame, frame):
            for text in texts:
                with self.subTest(text=text, facts=len(base['edges'])):
                    value = self.completed(self.run_turn(base, text, 'source:turn9'))
                    self.assertEqual(value['status'], 'unsupported')
                    self.assertIsNone(value['answer'])
                    self.assertEqual(value['evidence'], [])
                    self.assertEqual(value['frame'], base)

    def test_missing_fact_is_held(self):
        frame = self.observe(self.frame, STATE_FACT, 'source:turn1')
        value = self.completed(self.run_turn(frame, '서진은 어디에 있니?', 'source:turn2'))
        expected = self.model['responses']['missing']
        self.assertEqual(value['status'], expected['status'])
        self.assertEqual(value['answer'], expected['answer'])
        self.assertEqual(value['frame'], frame)

    def test_distinct_targets_are_ambiguous(self):
        frame = self.observe(self.frame, STATE_FACT, 'source:turn1')
        frame = self.observe(frame, '민준은 거실에 있다.', 'source:turn2')
        value = self.completed(self.run_turn(frame, QUERY, 'source:turn3'))
        expected = self.model['responses']['ambiguous']
        self.assertEqual(value['status'], expected['status'])
        self.assertEqual(value['answer'], expected['answer'])
        self.assertEqual(value['frame'], frame)

    def test_duplicate_facts_have_one_target(self):
        frame = self.observe(self.frame, STATE_FACT, 'source:turn1')
        frame = self.observe(frame, STATE_FACT, 'source:turn2')
        self.assertEqual(len(frame['edges']), 2)
        value = self.completed(self.run_turn(frame, QUERY, 'source:turn3'))
        self.assertEqual(value['status'], 'answered')
        self.assertEqual(value['answer'], '부엌에 있다.')
        self.assertEqual(value['evidence'], ['edge:source:turn1', 'edge:source:turn2'])

    def test_scope_and_relation_isolation(self):
        frame = self.observe(self.frame, STATE_FACT, 'source:turn1')
        for field, replacement in (('scope', 'scope:hypothetical'),
                                   ('relation', 'relation:other')):
            with self.subTest(field=field):
                changed = copy.deepcopy(frame)
                changed['edges'][0][field] = replacement
                value = self.completed(self.run_turn(changed, QUERY, 'source:turn2'))
                self.assertEqual(value['status'], 'missing')
                self.assertEqual(value['frame'], changed)

    def test_inputs_are_not_mutated(self):
        frame = self.observe(self.frame, STATE_FACT, 'source:turn1')
        for text in (QUERY, '서진은 거실에 있다.', '도윤은 부엌에 있다.'):
            frame_before = copy.deepcopy(frame)
            model_before = copy.deepcopy(self.model)
            program_before = copy.deepcopy(self.program)
            self.run_turn(frame, text, 'source:turn5')
            self.assertEqual(frame, frame_before)
            self.assertEqual(self.model, model_before)
            self.assertEqual(self.program, program_before)

    def test_zero_and_low_budget_refuse(self):
        for budget in (0, 1, 3):
            with self.subTest(budget=budget):
                envelope = self.run_turn(self.frame, STATE_FACT, 'source:turn1', budget=budget)
                self.assertNotEqual(envelope['status'], 'completed')
                self.assertIsNone(envelope['value'])

    def test_direct_vm_run(self):
        source = {'id': 'source:turn1', 'text': STATE_FACT,
                  'sha256': hashlib.sha256(STATE_FACT.encode('utf-8')).hexdigest()}
        envelope = graph_vm.run(self.program, {
            'frame': self.frame, 'text': STATE_FACT, 'source': source,
            'model': self.model}, budget=4096)
        self.assertEqual(envelope['status'], 'completed')
        value = envelope['value']
        self.assertEqual(value['status'], 'observed')
        self.assertEqual(validate_frame(value['frame'])['edges'][0]['target'], 'node:kitchen')
        self.assertEqual(value['frame']['sources'][0], source)

    def test_data_only_bootstrap_change_not_learning(self):
        # Same program bytes; only a copied declared model is edited by hand.
        changed = copy.deepcopy(self.model)
        changed['relation'] = 'relation:stays-at'
        changed['statement_end'] = '!'
        changed['object_suffix'] = '에 머문다'
        changed['question_rest'] = '어디에 머무니?'
        changed['answer_suffix'] = '에 머문다!'
        self.assertEqual(PROGRAM_PATH.read_bytes(), self.program_bytes)

        new_fact = '민준은 부엌에 머문다!'
        new_query = '민준은 어디에 머무니?'
        frame = self.observe(self.frame, new_fact, 'source:turn1', changed)
        self.assertEqual(frame['edges'][0]['relation'], 'relation:stays-at')
        value = self.completed(self.run_turn(frame, new_query, 'source:turn2', changed))
        self.assertEqual(value['status'], 'answered')
        self.assertEqual(value['answer'], '부엌에 머문다!')

        for text in (STATE_FACT, QUERY):
            with self.subTest(old_form=text):
                held = self.completed(self.run_turn(self.frame, text, 'source:turn3', changed))
                self.assertEqual(held['status'], 'unsupported')
                self.assertEqual(held['frame'], self.frame)

        old_view = self.completed(self.run_turn(frame, QUERY, 'source:turn4'))
        self.assertEqual(old_view['status'], 'missing')


if __name__ == '__main__':
    unittest.main()
