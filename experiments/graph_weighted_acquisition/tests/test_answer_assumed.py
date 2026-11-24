"""An unknown word whose role is open: each reading is tried against the knowledge, and one survivor is answered.

The answer has its own status ("assumed"), says what was assumed and what was tried, and is
corrected by telling the reader what the word is. Public development checks; lessons are the
made-up sets of probes/reading_limits.py, the passages are made up here.
"""
import importlib.util
from pathlib import Path

from experiments.graph_weighted_acquisition import answer as A
from experiments.graph_weighted_acquisition import learn as L

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'probes' / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
SETS = ('wordings', 'modifier', 'time', 'conditional')
# 특급 is in no lesson, list or pack. After a topic and a condition clause its connector lets it be a
# thing (as 바람개비호 would be there) or a circumstance of the fare.
QUESTION = '모래섬호는 정원이 30명이면 특급 기본요금이 얼마야?'
AS_THING = '모래섬호의 정원이 30명이면 특급의 기본요금은 4000원이다.'


def model():
    # These checks are about a word nothing knows. Since 2026-11-24 a question is read with the words of the
    # knowledge (`reading_uses_knowledge`), which would make 특급 known here; that is switched off, and
    # checked on its own at the end.
    m = P.build(*SETS)[0]
    return dict(m, conventions={k: v for k, v in m['conventions'].items() if k != 'reading_uses_knowledge'})


def test_one_reading_fits_the_knowledge_and_is_answered_as_an_assumption():
    m = model()
    passage = '모래섬호의 정원이 30명이면 특급의 기본요금은 4000원이다.'     # here the knowledge has a thing called 특급
    got = A.answer(passage, QUESTION, m)
    assert got['status'] == 'assumed' and got['answers'] == [['4000원']] and not got['verified']
    item = got['assumed'][0]
    assert (item['word'], item['head'], item['role'], item['kind']) == ('특급', '기본요금', 'subject', 'subject')
    # Both readings were tried, and the report says how each went.
    assert [(t['role'], t['result'].split(':')[0]) for t in item['tried']] == [
        ('subject', 'the knowledge answers that way'), ('when', 'the question is not read that way')]
    assert got['asked'][0]['between'] == ['subject', 'when']
    report = A.explain(passage, QUESTION, got)
    assert 'UNDER AN ASSUMPTION' in report.splitlines()[0] and '## How the question was understood' in report
    assert 'If this is wrong, say what "특급" is' in report
    # With a memory, the assumption is recorded and still not used as knowledge.
    memory = L.new_memory()
    A.answer(passage, QUESTION, m, memory)
    assert [(k['word'], k['kind'], k['assumed']) for k in memory['kinds']] == [('특급', 'subject', [QUESTION])]
    assert A.answer(passage, QUESTION, m, memory)['status'] == 'assumed'      # asked again: assumed again, not known


def test_no_reading_or_two_readings_fit_and_the_question_is_put_to_the_user():
    m = model()
    # Nothing in the knowledge uses the word at all: no reading is answered, so nothing is assumed.
    got = A.answer('모래섬호의 기본요금은 6000원이다.', QUESTION, m)
    assert got['status'] == 'hold' and not got.get('assumed') and [x['piece'] for x in got['open_roles']] == ['특급']
    # The convention of before: the question is put to the user without trying anything.
    before = dict(m, conventions={k: v for k, v in m['conventions'].items() if k != 'open_role_answers'})
    got = A.answer(AS_THING, QUESTION, before)
    assert got['status'] == 'hold' and not got.get('assumed')


def test_an_assumption_is_a_record_and_being_told_is_what_teaches():
    m, memory = model(), L.new_memory()
    L.note_assumed(memory, '특급', 'condition', QUESTION)
    L.note_assumed(memory, '특급', 'condition', QUESTION)
    assert memory['kinds'] == [{'word': '특급', 'kind': 'condition', 'seen': [], 'told': [], 'assumed': [QUESTION]}]
    assert '특급' not in L.overlay(m, memory)['tables']['word_kind']        # repeating a guess confirms nothing
    L.tell_kind(memory, '특급', 'condition', by='owner', at='2026-11-24')
    assert '특급' in L.overlay(m, memory)['tables']['word_kind']
    # Corrected the other way: the told kind is used, the assumption stays a record.
    other = L.new_memory()
    L.note_assumed(other, '특급', 'condition', QUESTION)
    L.tell_kind(other, '특급', 'subject', by='owner', at='2026-11-24')
    assert list(L.overlay(m, other)['tables']['word_kind']['특급']) == ['subject']


def test_with_the_words_of_the_knowledge_the_question_is_simply_read():
    m = P.build(*SETS)[0]
    got = A.answer(AS_THING, QUESTION, m)
    assert got['status'] == 'answered' and got['answers'] == [['4000원']] and not got.get('assumed')
    reading = got['question']
    term = [t for t in reading['readings'][reading['chosen']]['terms'] if t['what'].startswith('kind of a word')]
    assert term and term[0]['piece'] == '특급' and term[0]['origins'] == ['the knowledge uses "특급" as a subject']
