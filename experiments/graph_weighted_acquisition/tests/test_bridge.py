"""Unfamiliar wording tied to a property by two unrelated sources that agree.

One step through a dictionary from the field's property words (lexicon.py: the definition and the native
reading of the hanja) and counts from ordinary text (wording.py). Counted on the exposed outside sets,
either alone was right about as often as wrong; where both named the same property, wrong ones nearly
vanished. Still a guess: it leads to a proposal, never to an answer, and a model without `bridge`
behaves as before. Public development checks; dictionary lines and sentences are made up here.
"""
import importlib.util
from pathlib import Path

from experiments.graph_weighted_acquisition import lexicon as LX
from experiments.graph_weighted_acquisition import pack as PK
from experiments.graph_weighted_acquisition import wording as WD

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'probes' / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
PROPS = {'문의전화': ['문의전화'], '기본요금': ['기본요금'], '출발항': ['출발항']}
S = '모래섬호'
FACTS = {'schema': PK.FACTS, 'facts': [
    {'id': 'f1', 'subject': S, 'property': '문의전화', 'value': '555-0100', 'source': {'url': 'made-up'}},
    {'id': 'f2', 'subject': S, 'property': '기본요금', 'value': '6000원', 'source': {'url': 'made-up'}},
    {'id': 'f3', 'subject': S, 'property': '출발항', 'value': '서쪽항', 'source': {'url': 'made-up'}},
    {'id': 'f4', 'subject': '서쪽항', 'property': '문의전화', 'value': '555-0200', 'source': {'url': 'made-up'}}]}
DICTIONARY = ['전화\t電話\t전화기로 말을 주고받는 일.', '전화\t轉化\t바뀌어서 달리 됨.', '문의\t問議\t물어서 의논함.',
              '요금\t料金\t대가로 치르는 돈.', '기본\t基本\t바탕.', '출발\t出發\t길을 떠남.', '항\t港\t배가 드나드는 부두.']
HANJA = ['main_sound,level,hanja,meaning', "화,7급,話,\"[[['말씀'], ['화']]]\"", "화,5급,化,\"[[['될'], ['화']]]\"",
         "료,5급,料,\"[[['헤아릴'], ['료']]]\"", "문,7급,問,\"[[['물을'], ['문']]]\"", "발,6급,發,\"[[['필'], ['발']]]\"",
         "항,4급,港,\"[[['항구'], ['항']]]\""]


def sources(tmp_path):
    (tmp_path / 'd.tsv').write_text('\n'.join(DICTIONARY) + '\n', encoding='utf8')
    (tmp_path / 'h.csv').write_text('\n'.join(HANJA) + '\n', encoding='utf8')
    lines = ['%d번 문의전화 걸어요' % i for i in range(120)] + ['기본요금 치르면 돼요 %d' % i for i in range(120)] \
        + ['부두 구경 %d 출발항' % i for i in range(120)] + ['밥 먹어요 %d' % i for i in range(1640)]
    (tmp_path / 's.txt').write_text('\n'.join(lines) + '\n', encoding='utf8')
    return {'dictionary': LX.build(str(tmp_path / 'd.tsv'), str(tmp_path / 'h.csv'), PROPS, 'made-up dictionary'),
            'text': WD.build(str(tmp_path / 's.txt'), PROPS, 'made-up sentences')}


def test_one_step_through_the_dictionary(tmp_path):
    d = sources(tmp_path)['dictionary']
    # A word that is no headword is cut into headwords; the definition's "-는" verb and the hanja reading lead back.
    assert set(LX.points(d, '치르면')) == {'기본요금'} and '치르는' in LX.points(d, '치르면')['기본요금'][0]
    assert set(LX.points(d, '헤아려')) == {'기본요금'}                          # 料 헤아릴; 헤아리- in 헤아려
    assert set(LX.points(d, '말씀해')) == {'문의전화'}                          # 話 말씀
    assert set(LX.points(d, '부두에서')) == {'출발항'}
    assert LX.points(d, '먹어요') == {} and LX.points(d, '맡아') == {}
    assert all(isinstance(w, str) for stems in d['properties'].values() for where in stems.values() for w in where)


def test_only_where_both_sources_agree_and_only_as_a_proposal(tmp_path):
    _, language, _ = P.build('wordings', 'endings')
    f = PK.load(language, P.FERRY, FACTS)
    assert PK.ask(f, '모래섬호 치르면?')['status'] == 'hold' and not PK.ask(f, '모래섬호 치르면?').get('proposal')
    f['model']['bridge'] = sources(tmp_path)
    got = PK.ask(f, '모래섬호 치르면?')
    assert got['status'] == 'hold' and not got.get('answers')
    assert got['proposal']['understood']['property'] == '기본요금' and got['proposal']['if_confirmed'] == '6000원'
    assert 'dictionary' in got['proposal']['chosen_by'] and 'text' in got['proposal']['chosen_by']
    # Text alone ("걸어요" stands near 전화) or the dictionary alone ("말씀해") is not enough.
    assert not PK.ask(f, '모래섬호 걸어요?').get('proposal')
    assert not PK.ask(f, '모래섬호 말씀해?').get('proposal')


def test_a_property_word_with_words_that_lead_elsewhere_may_be_a_chain(tmp_path):
    _, language, _ = P.build('wordings', 'endings')
    f = PK.load(language, P.FERRY, FACTS)
    f['model']['bridge'] = sources(tmp_path)
    # "부두" leads to 출발항 by both sources; the port has a phone of its own: proposed as a chain, not answered.
    got = PK.ask(f, '모래섬호 부두 문의전화?')
    assert got['status'] == 'hold' and got['proposal']['if_confirmed'] == '555-0200'
    assert got['proposal']['understood']['thing'] == '서쪽항 (the 출발항 of 모래섬호)'
    # Without the bridge the same question asks for the boat's own phone, as before.
    del f['model']['bridge']
    plain = PK.ask(f, '모래섬호 부두 문의전화?')
    assert plain.get('proposal', {}).get('if_confirmed', (plain.get('answers') or [[None]])[0][0]) == '555-0100'
