"""One subject, written once, for two clauses: "X는 P가 V이면 Q가 W이다."

A part could belong to one head only, so the second clause had no subject and the sentence was held;
with a modifier in front of the second property, the modifier was read as its subject. Lessons now
show a part under two heads; the reader counts through what the two heads were joined (`share`) and
gives the head without the part the part of the head it is joined to. Public development checks;
lessons are the made-up sets of probes/reading_limits.py.
"""
import importlib.util
import json
from pathlib import Path

from experiments.graph_weighted_acquisition import answer as A
from experiments.graph_weighted_acquisition import reader as R

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'probes' / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
S = '모래섬호'
SETS = ('wordings', 'modifier', 'time', 'conditional', 'shared')


def test_the_subject_of_the_first_clause_is_the_subject_of_the_second():
    model, language, _ = P.build(*SETS)
    assert set(language['tables']['share']) == {'if'} and set(language['tables']['share']['if']) == {'subject'}
    text = '모래섬호는 정원이 30명이면 기본요금이 6000원이다.'
    got = R.read(text, model)
    assert got['status'] == 'complete' and not got['ignored'], got['reason']
    assert P.meaning(got['graphs'][0], text) == [P.rel('기본요금', subject=S, amount='6000원', **{'if': '정원'}),
                                                 P.rel('정원', subject=S, amount='30명')]
    graph = got['graphs'][0]
    assert len([n for n in graph['nodes'] if text[slice(*n['anchor'])] == S]) == 1       # one node, under both heads
    term = [t for t in got['readings'][got['chosen']]['terms'] if t['what'].startswith('a part shared')]
    assert len(term) == 1 and term[0]['count'] > 0 and term[0]['origins']
    # Without those lessons the sentence is held, as before.
    assert R.read(text, P.build('wordings', 'modifier', 'time', 'conditional')[0])['status'] != 'complete'


def test_a_clause_with_its_own_subject_keeps_it_and_a_listed_modifier_is_a_modifier():
    model, _, _ = P.build(*SETS)
    own = '모래섬호의 정원이 30명이면 바람개비호의 기본요금은 6000원이다.'
    got = R.read(own, model)
    assert got['status'] == 'complete' and ('subject', '바람개비호') in dict(P.meaning(got['graphs'][0], own))[('기본요금',)]
    # The misreading of the fourth blind set: the modifier was taken for the subject of the second clause.
    text = '모래섬호는 정원이 30명이면 주말 기본요금이 얼마야?'
    got = R.read(text, model)
    assert got['status'] == 'complete' and not got['ignored'], got['reason']
    assert dict(P.meaning(got['graphs'][0], text))[('기본요금',)] == (
        ('amount', 'ASK'), ('if', '정원'), ('subject', S), ('when', '주말'))


def test_a_question_that_writes_the_name_once_is_answered_from_knowledge_that_writes_it_twice():
    model, _, _ = P.build(*SETS)
    twice = '모래섬호의 정원이 30명이면 모래섬호의 기본요금은 6000원이다.'
    once = '모래섬호는 정원이 30명이면 기본요금이 얼마인가?'
    got = A.answer(twice, once, model)
    assert got['status'] == 'answered' and got['answers'] == [['6000원']] and got['executor'] == 'agrees'
    # And the other way round, and for another thing no answer.
    assert A.answer('모래섬호는 정원이 30명이면 기본요금이 6000원이다.',
                    '모래섬호의 정원이 30명이면 모래섬호의 기본요금은 얼마인가?', model)['answers'] == [['6000원']]
    assert A.answer(twice, '바람개비호는 정원이 30명이면 기본요금이 얼마인가?', model)['status'] == 'hold'
    assert A.explain(twice, once, got)                                    # the report is written without error


def test_an_unknown_word_there_is_read_both_ways_and_the_knowledge_decides():
    model, _, _ = P.build(*SETS)
    question = '모래섬호는 정원이 30명이면 특급 기본요금이 얼마야?'
    assert [x['between'] for x in R.read(question, model)['open_roles']] == [['subject', 'when']]
    as_modifier = A.answer('모래섬호의 정원이 30명이면 모래섬호의 특급 기본요금은 9000원이다.', question, model)
    assert as_modifier['status'] == 'assumed' and as_modifier['answers'] == [['9000원']]
    assert (as_modifier['assumed'][0]['role'], as_modifier['assumed'][0]['kind']) == ('when', 'condition')
    as_thing = A.answer('모래섬호의 정원이 30명이면 특급의 기본요금은 4000원이다.', question, model)
    assert as_thing['status'] == 'assumed' and as_thing['answers'] == [['4000원']]
    assert (as_thing['assumed'][0]['role'], as_thing['assumed'][0]['kind']) == ('subject', 'subject')
    # The knowledge uses the word in neither way: nothing is assumed, the question is put to the user.
    neither = A.answer('모래섬호는 정원이 30명이면 기본요금이 6000원이다.', question, model)
    assert neither['status'] == 'hold' and not neither.get('assumed') and neither['open_roles']


def test_a_pack_built_before_this_has_no_such_table():
    old = json.loads((HERE / 'packs' / 'language.json').read_text(encoding='utf8'))
    assert 'share' not in old['tables']
