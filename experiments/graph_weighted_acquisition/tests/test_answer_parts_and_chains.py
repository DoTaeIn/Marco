"""Two rules of answering from knowledge given as sentences.

1. A fact answers only a question that names every part the fact has (`unasked_parts`).
2. "X의 P의 Q" is answered from two facts stated apart, joined through a name (`name_joins`).

Public development checks; lessons are the made-up sets of probes/reading_limits.py, the knowledge
is made up here.
"""
import importlib.util
from pathlib import Path

from experiments.graph_weighted_acquisition import answer as A

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'probes' / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
SETS = ('wordings', 'modifier', 'time', 'negation', 'conditional', 'chain', 'shared')


def model():
    return P.build(*SETS)[0]


def without(m, name):
    return dict(m, conventions={k: v for k, v in m['conventions'].items() if k != name})


def test_what_is_known_with_a_qualifier_does_not_answer_the_plain_question():
    m = model()
    known = ('모래섬호의 주말 기본요금은 9000원이다. 2031년에 모래섬호의 정원은 30명이다. '
             '모래섬호의 연령이 5년이면 모래섬호의 할인율은 10%이다. 모래섬호의 출발항은 서쪽항이 아니다.')
    for question, part in (('모래섬호의 기본요금은 얼마인가?', 'when'), ('모래섬호의 정원은 얼마인가?', 'at'),
                           ('모래섬호의 할인율은 얼마인가?', 'if'), ('모래섬호의 출발항은 어디인가?', 'denies')):
        got = A.answer(known, question, m)
        assert got['status'] == 'hold' and part + ' of' in got['reason'], (question, got['reason'])
    # With the part named, the same facts answer.
    assert A.answer(known, '모래섬호의 주말 기본요금은 얼마인가?', m)['answers'] == [['9000원']]
    assert A.answer(known, '2031년에 모래섬호의 정원은 얼마인가?', m)['answers'] == [['30명']]
    # The rule of before, kept for packs that carry it: the weekend fare was given for the plain question.
    old = A.answer(known, '모래섬호의 기본요금은 얼마인가?', without(m, 'unasked_parts'))
    assert old['status'] == 'answered' and old['answers'] == [['9000원']]


def test_a_chain_is_answered_from_two_sentences_joined_by_a_name():
    m = model()
    known = '모래섬호의 출발항은 서쪽항이다. 서쪽항의 문의전화는 555-0100이다. 바람개비호의 문의전화는 555-0999이다.'
    got = A.answer(known, '모래섬호의 출발항의 문의전화는 무엇인가?', m)
    assert got['status'] == 'answered' and got['answers'] == [['555-0100']]
    assert got['joined_by'] == ['서쪽항'] and not got['verified'] and got['executor'] == 'not comparable'
    texts = {t for proof in got['match']['proofs'] for fact in proof['facts'] for t in fact['text']}
    assert {'서쪽항', '555-0100', '모래섬호'} <= texts                      # both sentences stand behind the answer
    assert A.explain(known, '모래섬호의 출발항의 문의전화는 무엇인가?', got)
    # Without the convention only what one sentence states together is matched.
    assert A.answer(known, '모래섬호의 출발항의 문의전화는 무엇인가?', without(m, 'name_joins'))['status'] == 'hold'


def test_a_chain_is_not_answered_when_the_first_fact_is_missing_qualified_or_denied():
    m = model()
    question = '모래섬호의 출발항의 문의전화는 무엇인가?'
    # The thing's own phone is not the phone of its port.
    assert A.answer('모래섬호의 문의전화는 555-0001이다. 서쪽항의 문의전화는 555-0100이다.', question, m)['status'] == 'hold'
    # The port is known for one year only, or only ruled out: no join through it.
    assert A.answer('2031년에 모래섬호의 출발항은 서쪽항이다. 서쪽항의 문의전화는 555-0100이다.', question, m)['status'] == 'hold'
    assert A.answer('모래섬호의 출발항은 서쪽항이 아니다. 서쪽항의 문의전화는 555-0100이다.', question, m)['status'] == 'hold'
    # The second fact has a part the question does not state.
    assert A.answer('모래섬호의 출발항은 서쪽항이다. 서쪽항의 주말 문의전화는 555-0100이다.', question, m)['status'] == 'hold'


def test_no_sentence_is_written_for_an_answer_under_a_condition():
    # Seen on the first blind set from knowledge to answer: the value was right and the sentence said
    # "은행골의 상태가 공사중이다.", the condition as a fact.
    m = model()
    known = '모래섬호의 정원이 30명이면 모래섬호의 기본요금은 6000원이다.'
    got = A.answer(known, '모래섬호의 정원이 30명이면 모래섬호의 기본요금은 얼마인가?', m)
    assert got['status'] == 'answered' and got['answers'] == [['6000원']]
    assert [s['text'] for s in got['sentences'] if s['status'] == 'said'] == []
