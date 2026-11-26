"""Taught basic words stand between a question that was not read and the properties of a field.

A lesson ties a common word to concepts. A field explains each property in plain words. Where a
question names a thing and nothing in it points at a property by form, its pieces are put next to
those explanations. What is worked out this way is a proposal or a list of candidates, never an
answer, and without the lessons nothing changes. The lessons and the field are made up here.
"""
import importlib.util
from pathlib import Path

import pytest

from experiments.graph_weighted_acquisition import basic as B
from experiments.graph_weighted_acquisition import pack as PK

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'probes' / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
S = '모래섬호'
FACTS = {'schema': PK.FACTS, 'facts': [
    {'id': 'f1', 'subject': S, 'property': '정원', 'value': '30명', 'source': {'url': 'made-up'}},
    {'id': 'f2', 'subject': S, 'property': '기본요금', 'value': '6000원', 'source': {'url': 'made-up'}},
    {'id': 'f3', 'subject': S, 'property': '출발항', 'value': '서쪽항', 'source': {'url': 'made-up'}}]}
LESSONS = '\n'.join([
    '# 개념', '곳\t자리', '사람\t사람', '수\t세는 양', '돈\t값을 치르는 것', '아이\t덜 자란 사람', '',
    '# 낱말', '어디\t물음\t곳', '곳\t뜻\t곳', '사람\t뜻\t사람', '수\t뜻\t수; -', '돈\t뜻\t돈',
    '아이\t뜻\t사람+아이', '것\t가벼움\t-', '맞다\t뜻\t곳'])


def field(tmp_path, explained, lessons=True):
    (tmp_path / 'basic.tsv').write_text(LESSONS, encoding='utf8')
    _, language, _ = P.build('wordings', 'endings', 'modifier', 'time', 'negation', 'conditional')
    words = dict(P.FERRY, properties=[dict(p, explained=explained[p['word']]) if p['word'] in explained else p
                                      for p in P.FERRY['properties']])
    return PK.load(language, words, FACTS, B.load(tmp_path / 'basic.tsv') if lessons else None)


PLAIN = {'정원': '사람 수', '기본요금': '돈', '출발항': '곳'}


def test_a_taught_word_that_meets_one_explanation_is_proposed_not_answered(tmp_path):
    f = field(tmp_path, PLAIN)
    got = PK.ask(f, '모래섬호 어디?')
    assert got['status'] == 'hold' and not got['answers']
    p = got['proposal']
    assert p['understood'] == {'thing': S, 'property': '출발항', 'with': {}} and p['if_confirmed'] == '서쪽항'
    assert p['chosen_by'] == 'taught basic words that meet the explanation of the property'
    assert 'worked out from taught basic words' in p['ask']
    # A plain word of the explanation, said as the question, does the same.
    assert PK.ask(f, '모래섬호 사람?')['proposal']['understood']['property'] == '정원'


def test_without_the_lessons_nothing_changes(tmp_path):
    with_them, without = field(tmp_path, PLAIN), field(tmp_path, PLAIN, lessons=False)
    assert 'basic' not in without['model'] and 'field_explained' not in without['model']
    for question in ('모래섬호 어디?', '모래섬호 사람?', '모래섬호 아이 돈?'):
        assert 'proposal' not in PK.ask(without, question) and 'candidates' not in PK.ask(without, question)
    # What form already decides is not touched by the lessons: a property word still gives an assumed answer.
    for f in (with_them, without):
        got = PK.ask(f, '모래섬호 출발항?')
        assert got['status'] == 'assumed' and got['assumed'][0]['chosen_by'] == 'the property word'


def test_a_piece_the_explanation_does_not_have_is_listed_not_swallowed(tmp_path):
    f = field(tmp_path, PLAIN)
    # 아이 is taught, and it is in no explanation. 돈 points at the fee, so the fee is proposed, and 아이
    # is named as the piece that may change the answer. Nothing is answered.
    got = PK.ask(f, '모래섬호 아이 돈?')
    assert got['status'] == 'hold' and not got['answers']
    assert got['proposal']['understood']['property'] == '기본요금' and got['proposal']['not_accounted_for'] == ['아이']
    assert 'these pieces are not accounted for: "아이"' in got['proposal']['ask']
    # The same for a word no lesson knows.
    assert PK.ask(f, '모래섬호 단체 돈?')['proposal']['not_accounted_for'] == ['단체']
    # A light word alone points at nothing, and neither does a word that meets no explanation.
    assert 'proposal' not in PK.ask(f, '모래섬호 것?') and 'candidates' not in PK.ask(f, '모래섬호 것?')
    assert 'proposal' not in PK.ask(f, '모래섬호 아이?') and 'candidates' not in PK.ask(f, '모래섬호 아이?')


def test_two_explanations_that_fit_are_shown_as_candidates(tmp_path):
    f = field(tmp_path, dict(PLAIN, 기본요금='돈 곳'))
    got = PK.ask(f, '모래섬호 어디?')
    assert got['status'] == 'hold' and 'proposal' not in got
    assert sorted(c['property'] for c in got['candidates']) == ['기본요금', '출발항']


def test_candidates_come_in_order_of_how_many_pieces_they_meet(tmp_path):
    f = field(tmp_path, dict(PLAIN, 기본요금='돈 곳'))
    got = PK.ask(f, '모래섬호 사람 돈 어디?')
    assert got['status'] == 'hold' and not got['answers'] and 'proposal' not in got
    # The fee meets two pieces, the others one each. No number decides: all three are shown, in order.
    assert [(c['property'], len(c['met'])) for c in got['candidates']] == [('기본요금', 2), ('정원', 1), ('출발항', 1)]
    assert got['candidates'][0]['unmet'] == ['사람'] and got['candidates'][0]['if_confirmed'] == '6000원'
    # One property that leaves no piece over is proposed, though others meet a piece too.
    whole = PK.ask(f, '모래섬호 돈 어디?')
    assert whole['proposal']['understood']['property'] == '기본요금' and whole['proposal']['not_accounted_for'] == []


def test_a_word_is_found_in_front_of_a_connector_and_with_a_learned_ending(tmp_path):
    f = field(tmp_path, PLAIN)
    basic, tables = f['model']['basic'], f['model']['tables']
    from experiments.graph_weighted_acquisition import answer as A
    marks, endings = A.word_ends(tables)
    assert [e['word'] for e in B.lookup(basic, '사람은', marks, endings)] == ['사람']
    assert [e['word'] for e in B.lookup(basic, '맞나요', marks, endings)] == ['맞다']     # 나요 is an ending the lessons have
    assert B.lookup(basic, '맞으려면', marks, endings) == []                              # an ending they do not have


def test_the_field_is_told_which_words_of_an_explanation_were_never_taught(tmp_path):
    f = field(tmp_path, dict(PLAIN, 정원='한꺼번에 사람 수'))
    assert f['model']['field_unexplained'] == [{'property': '정원', 'words': ['한꺼번에']}]
    assert f['model']['field_explained']['정원'] == ['사람', '수']


def test_a_lesson_that_uses_an_unlisted_concept_is_refused(tmp_path):
    (tmp_path / 'bad.tsv').write_text('# 개념\n곳\t자리\n\n# 낱말\n길\t뜻\t곳+움직임\n', encoding='utf8')
    with pytest.raises(ValueError, match='움직임'):
        B.load(tmp_path / 'bad.tsv')


def test_the_teachers_lessons_load(tmp_path):
    basic = B.load(HERE / 'packs' / 'basic_words_ko.tsv')
    assert len(basic['words']) == 942 and len(basic['concepts']) == 163
    assert basic['words']['것']['kind'] == 'light' and basic['words']['어디']['kind'] == 'asks'


def test_taught_stems_and_endings_find_a_word_in_its_changed_shape():
    basic = B.load(HERE / 'packs' / 'basic_words_ko.tsv', HERE / 'packs' / 'word_ends_ko.tsv')
    found = lambda piece: sorted(e['word'] for e in B.lookup(basic, piece))
    assert found('들어가려면') == ['들어가다'] and found('쉬는') == ['쉬다']
    assert found('갔어요') == ['가다']                       # an ending written as a lone letter goes under the stem
    assert '걷다' in found('걸어요') and '걸다' in found('걸어요')   # two words, one shape: both are kept
    assert found('문을') == ['문'] and found('학교에서는') == ['학교']
    # 바다 is listed as a word that takes no endings: it is found as itself, not as a stem.
    assert found('바다') == ['바다'] and found('바고') == []
    assert found('들어가겠사옵니다') == []                   # an ending nobody taught
