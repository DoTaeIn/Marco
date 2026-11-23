"""Things taught apart are read together, and a relation may stand under another relation.

Three reader rules of 2026-11-23, all switched by the pack's recipe and conventions:
  - a head's parts are judged one by one, not as a whole set seen together;
  - a head with everything under it is a phrase that may fill a role of another head;
  - a reading that goes against what the lessons showed cannot hold back a fully seen one.
Public development checks. The lessons are the made-up sets of probes/reading_limits.py; the
sentences use ferry words that no lesson contains.
"""
import importlib.util
import json
from pathlib import Path

from experiments.graph_weighted_acquisition import reader as R

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'probes' / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
S = '모래섬호'


def read(model, text):
    result = R.read(text, model)
    assert result['status'] == 'complete' and not result['ignored'], result['reason']
    return P.meaning(result['graphs'][0], text), result['graphs'][0]


def test_parts_taught_in_separate_lessons_are_read_in_one_sentence():
    model, language, _ = P.build('modifier', 'time', 'negation')
    # No lesson shows a time, a modifier and a claim check together, or any two of them.
    got, _ = read(model, '2027년에 모래섬호의 평일 첫출항은 7시가 맞나요?')
    assert got == [P.rel('첫출항', subject=S, at='2027년', when='평일', amount='7시', claim='맞나요')]
    got, _ = read(model, '2027년에 모래섬호의 주말 출발항은 서쪽항이 아니다.')
    assert got == [P.rel('출발항', subject=S, at='2027년', when='주말', amount='서쪽항', denies='아니')]
    # What must be there is still required: every lesson relation has a subject and a value.
    parts = language['tables']['part']
    assert all('-subject' not in row and '-amount' not in row and '+when' in row and '-when' in row for row in parts.values())


def test_a_relation_can_be_the_subject_of_another_relation():
    model, _, _ = P.build('chain')
    text = '모래섬호의 출발항의 문의전화는 무엇인가?'
    got, graph = read(model, text)
    assert got == sorted([P.rel('출발항', subject=S), P.rel('문의전화', subject='출발항', amount='ASK')])
    kinds = {n['id']: n['type'] for n in graph['nodes']}
    link = [(s, o) for s, p, o in graph['edges'] if p == 'subject' and isinstance(o, str) and kinds[o] == 'relation']
    assert len(link) == 1 and graph['project']
    # The plain shape is not disturbed by the lessons that teach the chain.
    got, _ = read(model, '모래섬호의 출발항은 어디인가?')
    assert got == [P.rel('출발항', subject=S, amount='ASK')]


def test_a_condition_stands_under_its_result_and_phrases_do_not_cross():
    model, _, _ = P.build('conditional', 'modifier')
    text = '승객의 연령이 65세이면 승객의 평일 할인율은 50%이다.'
    got, graph = read(model, text)
    assert got == sorted([P.rel('연령', subject='승객', amount='65세'),
                          P.rel('할인율', **{'if': '연령'}, subject='승객', when='평일', amount='50%')])
    # Each "승객" belongs to the relation next to it: the two subjects are different nodes, in order.
    place = {n['id']: n['anchor'][0] for n in graph['nodes']}
    for head, _, subject in [e for e in graph['edges'] if e[1] == 'subject']:
        others = [place[o] for s, p, o in graph['edges'] if s == head and p == 'amount']
        assert place[subject] < place[head] < others[0]


def test_each_rule_is_switched_in_the_pack_not_in_code():
    model, _, _ = P.build('conditional')
    text = '승객의 연령이 65세이면 승객의 할인율은 50%이다.'
    assert R.read(text, model)['status'] == 'complete'

    def edited(change):
        copy_ = json.loads(json.dumps(model))
        change(copy_)
        return copy_

    assert [p for _, p, o in R.read(text, model)['graphs'][0]['edges'] if p == 'if'] == ['if']
    # Without nesting in the recipe the two relations are read side by side, with nothing joining them.
    flat = R.read(text, edited(lambda m: m['recipe'].pop('nesting')))
    assert flat['status'] == 'complete' and 'if' not in [p for _, p, _ in flat['graphs'][0]['edges']]
    # With the convention of before, a higher-scoring reading that goes against the lessons holds the text.
    strict = edited(lambda m: m['conventions'].update(contradicted_reading_blocks=True))
    held = R.read(text, strict)
    assert held['status'] == 'ambiguous' and 'unseen piece' in held['reason']


def test_a_pack_built_before_these_rules_has_none_of_them():
    old = json.loads((HERE / 'packs' / 'language.json').read_text(encoding='utf8'))
    assert 'nesting' not in old['recipe'] and old['recipe']['head'][0]['table'] == 'frame'
    assert not {'contradicted_reading_blocks', 'partial_reading_blocks_whole'} & set(old['conventions'])
