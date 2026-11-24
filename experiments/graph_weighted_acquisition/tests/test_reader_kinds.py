"""A word whose kind is listed (data/word_kinds_ko.json) is read as that kind.

The lessons show a modifier only as "X의 M P는": after any other piece the same word was unknown
text, and in one construction it was silently read as a subject. The file says what kind of thing
some common words name; the recipe says how that is used. Public development checks; lessons are
the made-up sets of probes/reading_limits.py.
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
SETS = ('wordings', 'modifier', 'time', 'conditional')


def test_a_listed_modifier_is_read_after_a_piece_no_lesson_showed_it_after():
    text = '모래섬호는 주말 기본요금이 6000원이다.'
    without, _, _ = P.build(*SETS, kinds=None)
    before = R.read(text, without)
    assert before['ignored'] == ['주말']                      # read in part: the word was passed over
    model, language, _ = P.build(*SETS)
    assert language['tables']['word_kind']['주말'] == {'condition': {'n': 1, 'origins': ['word kinds: condition']}}
    got = R.read(text, model)
    assert got['status'] == 'complete' and not got['ignored'], got['reason']
    assert P.meaning(got['graphs'][0], text) == [P.rel('기본요금', subject=S, when='주말', amount='6000원')]
    term = [t for t in got['readings'][got['chosen']]['terms'] if t['what'].startswith('kind of a word')]
    assert len(term) == 1 and term[0]['piece'] == '주말' and term[0]['origins'] == ['word kinds: condition']


def test_a_listed_word_is_not_read_as_a_thing():
    # Found by the fourth blind set: the modifier was read as the subject of the result clause, no flag.
    text = '모래섬호는 정원이 30명이면 주말 기본요금이 얼마야?'
    without, _, _ = P.build(*SETS, kinds=None)
    without = dict(without, conventions={k: v for k, v in without['conventions'].items() if k != 'role_check'})
    wrong = R.read(text, without)
    assert wrong['status'] == 'complete' and ('subject', '주말') in dict(P.meaning(wrong['graphs'][0], text))[('기본요금',)]
    model, _, _ = P.build(*SETS)
    got = R.read(text, model)
    assert got['status'] != 'complete'

def test_a_word_of_unknown_kind_whose_role_the_form_leaves_open_is_asked_about():
    model, _, _ = P.build(*SETS)
    # 특급 is in no list. After " " a word was seen as a subject and as a modifier; the result clause has neither.
    text = '모래섬호는 정원이 30명이면 특급 기본요금이 얼마야?'
    got = R.read(text, model)
    assert got['status'] == 'ambiguous'
    assert [(x['piece'], x['head'], x['between']) for x in got['open_roles']] == [('특급', '기본요금', ['subject', 'when'])]
    # Not asked: the head already has the other role, so the form decides.
    plain = '모래섬호의 특급 기본요금은 6000원이다.'
    assert R.read(plain, model)['status'] == 'complete'
    # Not asked: a name the field pack knows is a thing.
    named = '모래섬호는 정원이 30명이면 바람개비호 기본요금이 얼마야?'
    got = R.read(named, model)
    assert got['status'] == 'complete' and ('subject', '바람개비호') in dict(P.meaning(got['graphs'][0], named))[('기본요금',)]
    # Without the convention the role the counts prefer is taken, as before.
    before = dict(model, conventions={k: v for k, v in model['conventions'].items() if k != 'role_check'})
    wrong = R.read(text, before)
    assert wrong['status'] == 'complete' and ('subject', '특급') in dict(P.meaning(wrong['graphs'][0], text))[('기본요금',)]


def test_the_connector_after_the_word_still_decides_and_a_clash_is_held():
    model, _, _ = P.build(*SETS)
    # "에" marks a time and nothing else: the form decides, and the file (오전: a circumstance) is not asked.
    text = '오전에 모래섬호의 정원은 30명이다.'
    got = R.read(text, model)
    assert got['status'] == 'complete' and P.meaning(got['graphs'][0], text) == [P.rel('정원', subject=S, at='오전', amount='30명')]
    # A day of the week as a value, found by the tenth blind set: "…은 화요일이다" is a value by form.
    text = '모래섬호의 첫출항은 화요일이다.'
    got = R.read(text, model)
    assert got['status'] == 'complete' and P.meaning(got['graphs'][0], text) == [P.rel('첫출항', subject=S, amount='화요일')]
    # Before this convention the listed kind was used wherever the word stood, and the sentence was held.
    everywhere = dict(model, conventions={k: v for k, v in model['conventions'].items() if k != 'word_kinds'})
    assert R.read(text, everywhere)['status'] != 'complete'
    # A longer word that contains a listed one is its own word.
    text = '모래섬호의 주말권 기본요금은 6000원이다.'
    got = R.read(text, model)
    assert got['status'] == 'complete' and P.meaning(got['graphs'][0], text) == [P.rel('기본요금', subject=S, when='주말권', amount='6000원')]


def test_a_pack_built_before_this_has_no_such_table():
    old = json.loads((HERE / 'packs' / 'language.json').read_text(encoding='utf8'))
    assert 'word_kind' not in old['tables'] and 'known_kind' not in old['recipe']['meaning'] and 'by_kind' not in old['recipe']['argument']
