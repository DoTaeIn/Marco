"""A question that is not read is put to the knowledge the other way round: which fact does it ask about?

The knowledge is finite. The things, property words and circumstances a question names, and what its
counter or question word asks for, are looked up among the plain facts. Finding one fact that fits is
not understanding the question: every other piece of it has to be accounted for. Then the answer is
given as "assumed"; otherwise the system proposes what it took the question to ask and waits for a
yes, and a yes teaches the wording. Made from the first set of an outside examiner, where answering on
one fit alone was wrong one time in five. Public development checks; the field is made up here.
"""
import importlib.util
from pathlib import Path

from experiments.graph_weighted_acquisition import answer as A
from experiments.graph_weighted_acquisition import learn as L
from experiments.graph_weighted_acquisition import pack as PK

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'probes' / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
S = '모래섬호'
FACTS = {'schema': PK.FACTS, 'facts': [
    {'id': 'f1', 'subject': S, 'property': '정원', 'value': '30명', 'source': {'url': 'made-up'}},
    {'id': 'f2', 'subject': S, 'property': '기본요금', 'value': '6000원', 'source': {'url': 'made-up'}},
    {'id': 'f3', 'subject': S, 'property': '출발항', 'value': '서쪽항', 'source': {'url': 'made-up'}},
    {'id': 'f4', 'subject': '서쪽항', 'property': '문의전화', 'value': '555-0100', 'source': {'url': 'made-up'}},
    {'id': 'f5', 'subject': '바람개비호', 'property': '정원', 'value': '50명', 'source': {'url': 'made-up'}}]}


def field():
    _, language, _ = P.build('wordings', 'endings', 'modifier', 'time', 'negation', 'conditional')
    return PK.load(language, P.FERRY, FACTS)


def test_every_piece_accounted_for_is_answered_as_an_assumption():
    f = field()
    # Particles dropped, no ending: a thing, a property word, and nothing else.
    got = PK.ask(f, '모래섬호 출발항?')
    assert got['status'] == 'assumed' and got['answers'] == [['서쪽항']] and not got['verified']
    item = got['assumed'][0]
    assert item['understood'] == {'thing': S, 'property': '출발항', 'with': {}}
    assert item['chosen_by'] == 'the property word' and item['not_accounted_for'] == []
    report = A.explain(f['text'], '모래섬호 출발항?', got)
    assert 'UNDER AN ASSUMPTION' in report.splitlines()[0] and 'It was taken to ask for the 출발항 of "모래섬호"' in report
    # A closing piece the lessons have is accounted for.
    assert PK.ask(f, '모래섬호 정원은 몇 명인가요?')['status'] == 'assumed'


def test_a_piece_left_over_is_put_to_the_user_and_a_yes_teaches_the_wording():
    f, memory = field(), L.new_memory()
    question = '모래섬호 몇 명까지 탈 수 있어요?'
    got = PK.ask(f, question, memory)
    # One fact fits (a value counted in 명), but verbs are left over: no answer, a proposal.
    assert got['status'] == 'hold' and not got['answers']
    p = got['proposal']
    assert p['understood'] == {'thing': S, 'property': '정원', 'with': {}} and p['if_confirmed'] == '30명'
    assert p['chosen_by'] == 'the counter "몇 명"' and '탈' in p['not_accounted_for']
    assert p['ask'].startswith('Did you ask for the 정원 of 모래섬호?')
    # The user says yes: the answer is given, and the wording is kept for that property.
    yes = A.confirm(got, memory, by='owner', at='2026-11-24')
    assert yes['status'] == 'assumed' and yes['answers'] == [['30명']] and yes['assumed'][0]['confirmed_by'] == 'owner'
    assert [(e['property'], set(p['not_accounted_for']) <= set(e['words'])) for e in memory['said']] == [('정원', True)]
    # Asked the same way of another thing, it is now answered; said for another property it is not.
    again = PK.ask(f, '바람개비호 몇 명까지 탈 수 있어요?', memory)
    assert again['status'] == 'assumed' and again['answers'] == [['50명']]
    assert PK.ask(f, '모래섬호 출발항 탈 수 있어요?', memory)['status'] == 'hold'


def test_the_five_wrong_answers_of_the_outside_set_are_not_given():
    f, memory = field(), L.new_memory()
    assert PK.ask(f, '모래섬호의 기본요금은 얼마인가?', memory)['status'] == 'answered'      # 얼마 has asked for 기본요금
    assert PK.ask(f, '모래섬호의 출발항은 어디인가?', memory)['status'] == 'answered'
    # 1. An unread word that may change the answer ("단체 얼마?" was given the plain fee).
    group = PK.ask(f, '모래섬호 단체 얼마?', memory)
    assert group['status'] == 'hold' and group['proposal']['not_accounted_for'] == ['단체']
    # 2. Two property words are a chain, not a choice between two facts.
    chain = PK.ask(f, '모래섬호 출발항 문의전화?', memory)
    assert chain['status'] == 'assumed' and chain['answers'] == [['555-0100']]
    assert chain['assumed'][0]['chosen_by'] == 'two property words, joined through "서쪽항"'
    assert {e['text'] for e in chain['evidence']} >= {'서쪽항', '555-0100'}
    assert PK.ask(f, '바람개비호 출발항 문의전화?', memory)['status'] == 'hold'              # no first link: nothing
    # 3. A question that states a value the knowledge has is a check, whatever its ending: it is answered
    #    with yes or no, not with the value alone ("정원이 20명인가요?" had been given "20명").
    yes = PK.ask(f, '모래섬호 정원이 30명인가요?', memory)
    assert yes['status'] == 'assumed' and yes['claim'] == {'claimed': '30명', 'holds': True}
    no = PK.ask(f, '모래섬호 정원이 50명인가요?', memory)
    assert no['status'] == 'assumed' and no['claim'] == {'claimed': '50명', 'holds': False} and no['answers'] == [['30명']]
    assert PK.ask(f, '모래섬호 30명인가요?', memory).get('assumed') is None           # no property word: nothing to check it against
    # 4. What a question word may ask for is not narrowed by what is known of the thing.
    assert PK.ask(f, '서쪽항의 문의전화는 어디인가?', memory)['status'] in ('answered', 'hold')
    L.note_ask(memory, '어디', '문의전화', 'made up for this check')
    where = PK.ask(f, '바람개비호 어디?', memory)
    assert where['status'] == 'hold' and not where.get('assumed')


def test_the_clause_of_a_condition_is_not_a_fact():
    _, language, _ = P.build('wordings', 'endings', 'modifier', 'time', 'negation', 'conditional')
    model = PK.with_words(language, P.FERRY)
    known = '모래섬호의 정원이 30명이면 모래섬호의 기본요금은 6000원이다.'
    got = A.answer(known, '모래섬호 정원?', model)
    assert got['status'] == 'hold' and not got.get('assumed') and not got.get('proposal') and not got.get('candidates')


def test_what_is_not_anchored_at_all():
    f = field()
    assert PK.ask(f, '모래섬호 주말 기본요금?').get('proposal') is None                     # a circumstance the fact does not have
    assert PK.ask(f, '모래섬호 수심은 몇 명이에요?').get('proposal') is None                 # an unknown word marked as a noun
    assert PK.ask(f, '한라호 몇 명까지 탈 수 있어요?').get('proposal') is None               # a thing the knowledge does not have
    assert PK.ask(f, '모래섬호 좋아요.').get('proposal') is None                            # nothing asked
    # The convention of before: an unread question is held and nothing is proposed.
    f['model'] = dict(f['model'], conventions={k: v for k, v in f['model']['conventions'].items() if k != 'unread_question_answers'})
    old = PK.ask(f, '모래섬호 출발항?')
    assert old['status'] == 'hold' and not old.get('proposal') and not old.get('assumed')


def test_letters_shared_with_a_property_word_or_a_value_lead_to_a_proposal_only():
    f, memory = field(), L.new_memory()
    # No property word, no counter, no known question word. "출발하는" shares letters with 출발항.
    got = PK.ask(f, '모래섬호 어느 곳에서 출발하는지 알려줘', memory)
    assert got['status'] == 'hold' and got['proposal']['understood']['property'] == '출발항'
    assert got['proposal']['chosen_by'] == 'letters an unread word shares with a property word or a value'
    assert got['proposal']['if_confirmed'] == '서쪽항'
    # After a yes, this very way of asking is answered: it was told. Shared letters alone still never give
    # an answer: other words with the same pieces accounted for are put to the user again.
    A.confirm(got, memory, by='owner', at='2026-11-24')
    again = PK.ask(f, '모래섬호 어느 곳에서 출발하는지 알려줘', memory)
    assert again['status'] == 'assumed' and again['answers'] == [['서쪽항']]
    assert again['assumed'][0]['chosen_by'] == 'a way of asking a user confirmed for this property'
    other = PK.ask(f, '모래섬호 출발하는지 어느 곳에서 알려줘', memory)
    assert other['status'] == 'hold' and other['proposal']['not_accounted_for'] == []


def test_the_last_word_of_a_question_is_its_predicate_whatever_it_ends_in():
    f = field()
    # "들어가" ends in 가, which also marks a noun. Standing last it is the predicate, and the question is not given up.
    got = PK.ask(f, '모래섬호 몇 명까지 들어가?')
    assert got['proposal']['understood']['property'] == '정원' and got['proposal']['if_confirmed'] == '30명'
    assert PK.ask(f, '모래섬호 수심은 몇 명이에요?').get('proposal') is None          # not last: still a marked noun
