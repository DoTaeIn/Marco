import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marco.reasoning.graph_contract import execute_frame
from tools import graph_surface_compaction as gsc


def load(rel):
    with open(ROOT / rel, encoding='utf-8') as handle:
        return json.load(handle)


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def size(value):
    return len(canon(value).encode('utf-8'))


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def make_source(text):
    digest = sha(text)
    return {'id': 'source:' + digest, 'text': text, 'sha256': digest}


def make_proposal(contexts, fillers):
    sources, candidates = [], []
    for prefix, suffix in contexts:
        evidence = []
        for filler in fillers:
            src = make_source(prefix + filler + suffix)
            sources.append(src)
            evidence.append({'source': src['id'], 'start': len(prefix),
                             'end': len(src['text']) - len(suffix)})
        candidates.append({'id': 'candidate:' + sha(canon([prefix, suffix])),
                           'prefix': prefix, 'suffix': suffix,
                           'fillers': list(fillers), 'evidence': evidence})
    return {'schema': 'marco-surface-candidates-v1', 'active': False, 'semantics': None,
            'sources': sources, 'candidates': candidates}


CONTEXTS = [('[ ', ' ]'), ('< ', ' >')]
FILLERS = ['alpha', 'beta', 'delta', 'gamma']

BASE = load('language_graphs/ko/foundation-bootstrap.json')
OLD = load('programs/foundation-registered-span.json')
NEW = load('programs/foundation-indexed-dialogue.json')


def custom(labels, **overrides):
    seed = copy.deepcopy(BASE)
    seed['frame']['nodes'] = [{'id': i, 'type': 'type:entity', 'scope': 'scope:bootstrap', 'value': t}
                              for i, t in labels]
    seed['model']['labels'] = [{'id': i, 'text': t} for i, t in labels]
    seed['model'].update(overrides)
    return seed


ASCII = dict(subject_particle='P', object_suffix='S', question_rest='?', answer_suffix='!')


def step(program, frame, model, text, number):
    return execute_frame(program, frame, text=text, source_id='turn%d' % number,
                         model=model, budget=4096)


def compare(seed, texts):
    indexed = gsc.validate_indexes(gsc.build_indexes(seed))
    old_frame = new_frame = seed['frame']
    outs = []
    for number, text in enumerate(texts):
        old = step(OLD, old_frame, seed['model'], text, number)
        new = step(NEW, new_frame, indexed['model'], text, number)
        assert old['status'] == 'completed', old
        assert new['status'] == 'completed', new
        assert old['value'] == new['value'], (text, old['value'], new['value'])
        old_frame = old['value']['frame']
        new_frame = new['value']['frame']
        outs.append((old['value'], old['used'], new['used']))
    return outs


class CompactionTests(unittest.TestCase):
    def test_roundtrip_order_and_sharing(self):
        proposal = make_proposal(CONTEXTS, FILLERS)
        shared = gsc.compact(proposal)
        self.assertEqual(shared['schema'], 'marco-shared-surface-v1')
        self.assertIs(shared['active'], False)
        self.assertIsNone(shared['semantics'])
        self.assertEqual(shared['sources'], proposal['sources'])
        self.assertEqual(shared['slots'], [[2, 3, 4, 5]])
        self.assertEqual([row[3] for row in shared['candidates']], [0, 0])
        self.assertEqual(shared['strings'][:2], ['[ ', ' ]'])
        self.assertEqual(gsc.expand(shared), proposal)

    def test_compression_is_positive(self):
        proposal = make_proposal(CONTEXTS, FILLERS)
        self.assertLess(size(gsc.compact(proposal)), size(proposal))

    def test_arbitrary_order_is_preserved(self):
        proposal = make_proposal(CONTEXTS, ['gamma', 'delta', 'beta', 'alpha'])
        proposal['candidates'][1]['fillers'].reverse()
        proposal['candidates'][1]['evidence'].reverse()
        shared = gsc.compact(proposal)
        self.assertEqual(len(shared['slots']), 2)
        self.assertEqual(gsc.expand(shared), proposal)

    def test_empty_proposal(self):
        proposal = make_proposal([], FILLERS)
        shared = gsc.compact(proposal)
        self.assertEqual(shared['strings'], [])
        self.assertEqual(shared['slots'], [])
        self.assertEqual(gsc.expand(shared), proposal)

    def test_detachment(self):
        proposal = make_proposal(CONTEXTS, FILLERS)
        before = copy.deepcopy(proposal)
        shared = gsc.compact(proposal)
        shared['sources'][0]['text'] = 'changed'
        self.assertEqual(proposal, before)
        shared = gsc.compact(proposal)
        kept = copy.deepcopy(shared)
        expanded = gsc.expand(shared)
        expanded['sources'][0]['id'] = 'changed'
        expanded['candidates'][0]['fillers'].append('x')
        self.assertEqual(shared, kept)

    def test_compact_rejects_malformed(self):
        def mutated(change):
            proposal = make_proposal(CONTEXTS, FILLERS)
            change(proposal)
            return proposal

        def dup_candidate(p):
            p['candidates'].append(copy.deepcopy(p['candidates'][0]))

        def bad_hash(p):
            p['sources'][0]['sha256'] = '0' * 64

        def bad_end(p):
            p['candidates'][0]['evidence'][0]['end'] -= 1

        def surrogate(p):
            p['candidates'][0]['fillers'][0] = chr(0xD800)

        def active(p):
            p['active'] = True

        def semantics(p):
            p['semantics'] = 'role'

        def schema(p):
            p['schema'] = 'other'

        def candidate_id(p):
            p['candidates'][0]['id'] = 'candidate:' + '0' * 64

        def unknown_source(p):
            p['candidates'][0]['evidence'][0]['source'] = 'source:' + '1' * 64

        def duplicate_filler(p):
            p['candidates'][0]['fillers'][1] = p['candidates'][0]['fillers'][0]

        def extra_filler(p):
            p['candidates'][0]['fillers'].append('omega')

        def too_few(p):
            c = p['candidates'][0]
            c['fillers'] = c['fillers'][:2]
            c['evidence'] = c['evidence'][:2]

        def extra_key(p):
            p['extra'] = 1

        for change in (dup_candidate, bad_hash, bad_end, surrogate, active, semantics, schema,
                       candidate_id, unknown_source, duplicate_filler, extra_filler, too_few, extra_key):
            with self.assertRaises(ValueError, msg=change.__name__):
                gsc.compact(mutated(change))

    def test_bool_span_rejected(self):
        proposal = make_proposal([('', ';')], FILLERS)
        gsc.compact(proposal)
        proposal['candidates'][0]['evidence'][0]['start'] = False
        with self.assertRaises(ValueError):
            gsc.compact(proposal)

    def test_expand_rejects_malformed(self):
        good = gsc.compact(make_proposal(CONTEXTS, FILLERS))

        def mutated(change):
            shared = copy.deepcopy(good)
            change(shared)
            return shared

        def bool_index(s):
            s['candidates'][0][1] = True

        def bool_source(s):
            s['candidates'][0][4][0][0] = False

        def out_of_range(s):
            s['slots'][0][0] = 99

        def dup_strings(s):
            s['strings'].append(s['strings'][0])

        def dup_slots(s):
            s['slots'].append(list(s['slots'][0]))

        def unused_string(s):
            s['strings'].append('unused')

        def unused_slot(s):
            s['slots'].append([2, 3, 4])

        def active(s):
            s['active'] = True

        def semantics(s):
            s['semantics'] = {}

        def short_row(s):
            s['candidates'][0] = s['candidates'][0][:4]

        def missing_key(s):
            del s['slots']

        def bad_span(s):
            s['candidates'][0][4][0][2] += 1

        def reorder_slot(s):
            s['slots'][0] = [2, 3, 5, 4]

        for change in (bool_index, bool_source, out_of_range, dup_strings, dup_slots, unused_string,
                       unused_slot, active, semantics, short_row, missing_key, bad_span, reorder_slot):
            with self.assertRaises(ValueError, msg=change.__name__):
                gsc.expand(mutated(change))


class IndexTests(unittest.TestCase):
    def test_deterministic_and_structural(self):
        before = copy.deepcopy(BASE)
        first = gsc.build_indexes(BASE)
        second = gsc.build_indexes(BASE)
        self.assertEqual(BASE, before)
        self.assertEqual(canon(first), canon(second))
        index = first['model']['index']
        self.assertEqual(set(index), {'source_sha256', 'label_buckets', 'labels_by_text', 'labels_by_id'})
        self.assertEqual(index['source_sha256'], sha(canon(BASE['model']['labels'])))
        self.assertEqual(index['label_buckets']['민'], [{'id': 'node:minjun', 'text': '민준'}])
        self.assertEqual(index['labels_by_text']['부엌'], ['node:kitchen'])
        self.assertEqual(index['labels_by_id']['node:seojin'], ['서진'])
        self.assertEqual(first['frame'], BASE['frame'])
        self.assertEqual(first['frame']['edges'], [])
        self.assertEqual(first['frame']['spans'], [])
        self.assertEqual(first['frame']['sources'], [])
        self.assertEqual(list(first['model']), list(BASE['model']) + ['index'])

    def test_existing_index_is_replaced_in_place(self):
        seed = copy.deepcopy(BASE)
        seed['model']['index'] = 'junk'
        out = gsc.build_indexes(seed)
        self.assertEqual(list(out['model']), list(seed['model']))
        self.assertEqual(out['model']['index'], gsc.build_indexes(BASE)['model']['index'])

    def test_duplicate_label_text_preserved(self):
        seed = custom([('node:a', 'a'), ('node:q', 'q'), ('node:q2', 'q')], **ASCII)
        index = gsc.build_indexes(seed)['model']['index']
        self.assertEqual(index['labels_by_text']['q'], ['node:q', 'node:q2'])
        self.assertEqual(len(index['label_buckets']['q']), 2)

    def test_label_validation(self):
        def mutate(change):
            seed = copy.deepcopy(BASE)
            change(seed)
            return seed

        def text_mismatch(s):
            s['model']['labels'][0]['text'] = '다른'

        def unknown_id(s):
            s['model']['labels'][0]['id'] = 'node:none'

        def duplicate_id(s):
            s['model']['labels'][1]['id'] = s['model']['labels'][0]['id']

        def empty_text(s):
            s['model']['labels'][0]['text'] = ''
            s['frame']['nodes'][0]['value'] = ''

        for change in (text_mismatch, unknown_id, duplicate_id, empty_text):
            with self.assertRaises(ValueError, msg=change.__name__):
                gsc.build_indexes(mutate(change))

    def test_validate_indexes_accepts_and_detaches(self):
        built = gsc.build_indexes(BASE)
        checked = gsc.validate_indexes(built)
        self.assertEqual(checked, built)
        checked['model']['index']['labels_by_id'].clear()
        self.assertTrue(built['model']['index']['labels_by_id'])

    def test_validate_indexes_rejects_missing_stale_corrupt(self):
        with self.assertRaises(ValueError):
            gsc.validate_indexes(BASE)
        built = gsc.build_indexes(BASE)

        stale = copy.deepcopy(built)
        stale['model']['labels'] = stale['model']['labels'][:-1]
        with self.assertRaises(ValueError):
            gsc.validate_indexes(stale)

        corrupt = copy.deepcopy(built)
        del corrupt['model']['index']['label_buckets']['민']
        with self.assertRaises(ValueError):
            gsc.validate_indexes(corrupt)

        pin = copy.deepcopy(built)
        pin['model']['index']['source_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            gsc.validate_indexes(pin)

        order = copy.deepcopy(built)
        order['model']['index']['labels_by_id']['node:kitchen'].append('부엌')
        with self.assertRaises(ValueError):
            gsc.validate_indexes(order)


class ProgramTests(unittest.TestCase):
    def test_base_fixture_matches_original_program(self):
        quote = chr(34)
        texts = ['민준은 부엌에 있다.', '민준은 어디에 있니?', '서진은 어디에 있니?',
                 '낯선은 어디에 있니?', '', '.', quote + '민준은 부엌에 있다.' + quote,
                 '민준은 부엌에 없다.', '서진은 없는에 있다.', '민준은 어디에 있니']
        outs = compare(BASE, texts)
        values = [value for value, _, _ in outs]
        self.assertEqual(values[0]['status'], 'observed')
        self.assertEqual(values[1]['status'], 'answered')
        self.assertEqual(values[1]['answer'], '부엌에 있다.')
        self.assertEqual(len(values[1]['evidence']), 1)
        self.assertEqual(values[2]['status'], 'missing')
        for number in range(3, len(texts)):
            self.assertEqual(values[number]['status'], 'unsupported', texts[number])
            self.assertIsNone(values[number]['answer'])
            self.assertEqual(values[number]['evidence'], [])
        self.assertEqual(values[4]['frame'], values[0]['frame'])

    def test_empty_input_is_held(self):
        indexed = gsc.build_indexes(BASE)
        result = step(NEW, BASE['frame'], indexed['model'], '', 0)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['value']['status'], 'unsupported')
        self.assertIsNone(result['value']['answer'])
        self.assertEqual(result['value']['frame'], BASE['frame'])

    def test_overlapping_subject_prefix_is_ambiguous(self):
        seed = custom([('node:a', 'a'), ('node:aP', 'aP'), ('node:q', 'q')], **ASCII)
        outs = compare(seed, ['aPPqS.', 'aPqS.', 'aP?'])
        values = [value for value, _, _ in outs]
        self.assertEqual(values[0]['status'], 'unsupported')
        self.assertEqual(values[1]['status'], 'observed')
        self.assertEqual(values[2]['status'], 'answered')
        self.assertEqual(values[2]['answer'], 'q!')

    def test_duplicate_object_label_is_held(self):
        seed = custom([('node:a', 'a'), ('node:q', 'q'), ('node:q2', 'q')], **ASCII)
        outs = compare(seed, ['aPqS.'])
        self.assertEqual(outs[0][0]['status'], 'unsupported')

    def test_ambiguous_fact_is_distinct(self):
        seed = custom([('node:a', 'a'), ('node:q', 'q'), ('node:r', 'r')], **ASCII)
        outs = compare(seed, ['aPqS.', 'aPrS.', 'aP?'])
        values = [value for value, _, _ in outs]
        self.assertEqual([v['status'] for v in values], ['observed', 'observed', 'ambiguous'])
        self.assertEqual(len(values[2]['evidence']), 2)

    def test_many_labels_use_fewer_steps(self):
        names = [chr(0x4E00 + i) for i in range(40)]
        place = chr(0x5000)
        labels = [('node:n%d' % i, names[i]) for i in range(40)] + [('node:place', place)]
        seed = custom(labels)
        subject = names[39]
        texts = [subject + '은 ' + place + '에 있다.', subject + '은 어디에 있니?']
        outs = compare(seed, texts)
        self.assertEqual(outs[0][0]['status'], 'observed')
        self.assertEqual(outs[1][0]['status'], 'answered')
        self.assertEqual(outs[1][0]['answer'], place + '에 있다.')
        for _, old_used, new_used in outs:
            self.assertLess(new_used, old_used)

    def test_model_without_index_is_not_lazily_indexed(self):
        result = step(NEW, BASE['frame'], BASE['model'], '민준은 어디에 있니?', 0)
        self.assertEqual(result['status'], 'invalid')


if __name__ == '__main__':
    unittest.main()
