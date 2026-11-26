"""A word no lesson knows is placed by the sentence it stands in.

A sentence is cut by form into words, what follows each, and the word each hangs on (relate.words).
A word of the question that no lesson has may then be a word of a property's explanation in
another shape, or stand where one of its words stands. Either is a guess: it is said with the
proposal and never answered. The lessons and the field are made up here.
"""
import importlib.util
from pathlib import Path

from experiments.graph_weighted_acquisition import basic as B
from experiments.graph_weighted_acquisition import pack as PK
from experiments.graph_weighted_acquisition import relate as RL

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'probes' / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
S = '모래섬호'
FACTS = {'schema': PK.FACTS, 'facts': [
    {'id': 'f2', 'subject': S, 'property': '기본요금', 'value': '6000원', 'source': {'url': 'made-up'}},
    {'id': 'f3', 'subject': S, 'property': '출발항', 'value': '서쪽항', 'source': {'url': 'made-up'}}]}
LESSONS = '\n'.join(['# 개념', '곳\t자리', '돈\t값을 치르는 것', '물건\t만질 수 있는 것', '',
                     '# 낱말', '곳\t뜻\t곳', '돈\t뜻\t돈', '책\t뜻\t물건', '내다\t뜻\t돈', '마시다\t뜻\t물건', '때\t가벼움\t-'])
ENDS = '\n'.join(['# 줄기', '내다\t내\t내\t내', '마시다\t마시\t마시\t마셔', '# 바탕줄기 뒤', '는',
                  '# 으줄기 뒤', '면', 'ㄹ', '# 어줄기 뒤', '요', '# 이름씨 뒤', '을', '에'])
EXPLAINED = {'기본요금': '책을 빌릴 때 내는 돈', '출발항': '곳'}


def field(tmp_path):
    (tmp_path / 'basic.tsv').write_text(LESSONS, encoding='utf8')
    (tmp_path / 'ends.tsv').write_text(ENDS, encoding='utf8')
    _, language, _ = P.build('wordings', 'endings', 'modifier', 'time', 'negation', 'conditional')
    words = dict(P.FERRY, properties=[dict(p, explained=EXPLAINED[p['word']]) if p['word'] in EXPLAINED else p
                                      for p in P.FERRY['properties']])
    return PK.load(language, words, FACTS, B.load(tmp_path / 'basic.tsv', tmp_path / 'ends.tsv'))


def test_a_sentence_is_cut_by_form_and_every_word_hangs_on_a_later_one(tmp_path):
    basic = field(tmp_path)['model']['basic']
    rows = RL.words(basic, '우산을 빌리면 돈을 내요?')
    assert [(r['text'], rows[r['head']]['text'] if r['head'] is not None else None) for r in rows] == [
        ('우산을', '빌리면'), ('빌리면', '돈을'), ('돈을', '내요'), ('내요', None)]
    # 빌리다 is in no lesson. Its shapes still come back to one stem, by the ways taught words change theirs.
    assert RL.words(basic, '빌려요')[0]['keys'] & RL.words(basic, '빌릴')[0]['keys']


def test_an_unknown_word_is_placed_and_the_guess_is_said_not_answered(tmp_path):
    f = field(tmp_path)
    got = PK.ask(f, '모래섬호 우산을 빌리면 돈?')
    assert got['status'] == 'hold' and not got['answers']
    p = got['proposal']
    assert p['understood']['property'] == '기본요금' and p['if_confirmed'] == '6000원' and p['not_accounted_for'] == []
    assert p['placed'] == {'우산을': {'how': 'place', 'as': '책을'}, '빌리면': {'how': 'same', 'as': '빌릴'}}


def test_a_word_in_another_place_is_not_placed(tmp_path):
    f = field(tmp_path)
    # "우산에" hangs on the same word by another connector: it does not stand where "책을" stands.
    assert RL.placed(f['model']['basic'], '우산에 빌리면 돈?', EXPLAINED) == {'기본요금': {'빌리면': ('same', '빌릴', 0)}}
    got = PK.ask(f, '모래섬호 우산에 빌리면 돈?')
    assert not got['answers'] and 'proposal' not in got and 'candidates' not in got
    # Under another head nothing is placed either.
    assert RL.placed(f['model']['basic'], '우산을 마시면 돈?', EXPLAINED) == {}


def test_ordinary_text_says_which_word_of_the_explanation_an_unknown_word_is_like(tmp_path):
    f = field(tmp_path)
    basic = f['model']['basic']
    # Made-up text: 우산 and 책 are both borrowed and both carried; 구름 is only looked at.
    RL.save(RL.places(basic, ['우산을 빌리면', '우산을 빌리면', '책을 빌리면', '책을 빌리면', '우산을 들면', '우산을 들면',
                              '책을 들면', '책을 들면', '구름을 보면', '구름을 보면', '책을 사면', '책을 사면']), tmp_path / 'places.tsv')
    text = RL.load(tmp_path / 'places.tsv')
    # The head here ("들면") is not in the explanation, so nothing is placed without the text.
    assert RL.placed(basic, '우산을 들면 돈?', EXPLAINED) == {}
    assert RL.placed(basic, '우산을 들면 돈?', EXPLAINED, text) == {'기본요금': {'우산을': ('like', '책을', 666)}}
    # A word the text never saw where 책 stands is like nothing.
    assert RL.placed(basic, '구름을 보면 돈?', EXPLAINED, text) == {}
    f['model']['places'] = text
    got = PK.ask(f, '모래섬호 우산을 들면 돈?')
    assert not got['answers'] and got['proposal']['placed']['우산을'] == {'how': 'like', 'as': '책을', 'shared_places_per_thousand': 666}
    assert got['proposal']['not_accounted_for'] == ['들면']
