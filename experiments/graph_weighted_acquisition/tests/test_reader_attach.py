"""A part that the sentence's form would equally let belong to another head is asked about.

Found by the blind test of 2026-11-23: with a time or a condition in front of a chain
("2034년에 X의 P의 Q는 …"), the reader attached it to the inner relation, every count nonzero,
nothing flagged. Korean leaves that open; a reader without sense of the world must not pick.
Public development checks; lessons are the made-up sets of probes/reading_limits.py.
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


def test_a_time_in_front_of_a_chain_is_asked_about_not_placed():
    model, _, _ = P.build('chain', 'time', 'conditional', 'modifier')
    text = '2034년에 모래섬호의 출발항의 문의전화는 0412이다.'
    got = R.read(text, model)
    assert got['status'] == 'ambiguous' and got['graphs'] != [] and 'does not say' in got['reason']
    assert got['attachment'] == [{'piece': '2034년', 'role': 'at', 'between': ['출발항', '문의전화'],
                                  'ask': 'Does "2034년" belong to "출발항" or to "문의전화"?'}]
    # The same for a condition in front of a chain: it could be the condition of either relation.
    got = R.read('승객의 연령이 65세이면 승객의 출발항의 문의전화는 0412이다.', model)
    assert got['status'] == 'ambiguous' and got['attachment'][0]['between'] == ['출발항', '문의전화']
    # And the question that would have been answered is held, with what to ask back.
    held = A.answer_graph({'nodes': [], 'edges': [], 'edge_spans': [], 'project': []}, '',
                          '2034년에 모래섬호의 출발항의 문의전화는 무엇인가?', model)
    assert held['status'] == 'hold' and held['attachment'][0]['piece'] == '2034년'


def test_where_the_form_leaves_no_choice_nothing_is_asked():
    model, _, _ = P.build('chain', 'time', 'conditional', 'modifier')
    for text, expected in (
            ('모래섬호의 출발항의 문의전화는 무엇인가?', [P.rel('출발항', subject=S), P.rel('문의전화', subject='출발항', amount='ASK')]),
            ('2034년에 모래섬호의 평일 첫출항은 언제인가?', [P.rel('첫출항', subject=S, at='2034년', when='평일', amount='ASK')]),
            # A modifier stands right before its own head; the relation before it is not a place for it.
            ('모래섬호의 출발항의 평일 문의전화는 무엇인가?',
             [P.rel('출발항', subject=S), P.rel('문의전화', subject='출발항', when='평일', amount='ASK')]),
            ('승객의 연령이 65세이면 승객의 평일 할인율은 50%이다.',
             [P.rel('연령', subject='승객', amount='65세'), P.rel('할인율', **{'if': '연령'}, subject='승객', when='평일', amount='50%')])):
        got = R.read(text, model)
        assert got['status'] == 'complete' and not got['ignored'], (text, got['reason'])
        assert P.meaning(got['graphs'][0], text) == sorted(expected)


def test_the_check_is_a_convention_of_the_pack():
    model, _, _ = P.build('chain', 'time')
    text = '2034년에 모래섬호의 출발항의 문의전화는 0412이다.'
    off = json.loads(json.dumps(model))
    off['conventions']['attachment_check'] = False
    assert R.read(text, model)['status'] == 'ambiguous' and R.read(text, off)['status'] == 'complete'
    old = json.loads((HERE / 'packs' / 'language.json').read_text(encoding='utf8'))
    assert 'attachment_check' not in old['conventions']
