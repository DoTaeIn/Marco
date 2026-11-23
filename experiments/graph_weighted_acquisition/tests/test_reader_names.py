"""A name the field pack knows may not be swallowed into a longer free value.

Before this rule a free value was any text up to the next connector, so "A와 B" was read as
one name without a word of warning. Public development checks, made-up words.
"""
import importlib.util
import json
from pathlib import Path

from experiments.graph_weighted_acquisition import pack as PK
from experiments.graph_weighted_acquisition import reader as R

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('make_language', HERE / 'packs' / 'make_language.py')
ML = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ML)

SLOT = {'type': 'relation', 'attribute': 'kind', 'subject_role': 'subject', 'value_role': 'amount'}
WORDS = {'schema': PK.WORDS, 'field': 'made-up ferry line', 'slot': SLOT,
         'properties': [{'word': '정원', 'means': '정원', 'also': []}, {'word': '출발항', 'means': '출발항', 'also': []}],
         'names': [{'name': '모래섬호', 'also': ['1호선']}, {'name': '바람개비호', 'also': []},
                   {'name': '등대호', 'also': []}, {'name': '큰등대호', 'also': []}]}
SOURCE = {'url': 'made up', 'as_of': 'today', 'scope': 'test'}
FACTS = {'schema': PK.FACTS, 'facts': [
    {'id': 'F1', 'subject': '모래섬호', 'property': '정원', 'value': '120명', 'source': SOURCE},
    {'id': 'F2', 'subject': '동쪽항', 'property': '정원', 'value': '모래섬호두척', 'source': SOURCE},
    {'id': 'F3', 'subject': '큰등대호', 'property': '출발항', 'value': '동쪽항', 'source': SOURCE}]}


def _subjects(result, text):
    graph = result['graphs'][0]
    anchor = {n['id']: n['anchor'] for n in graph['nodes']}
    return [text[slice(*anchor[o])] for s, p, o in graph['edges'] if p == 'subject']


def test_a_known_name_is_not_swallowed_into_a_longer_one():
    model = PK.with_words(R.build(ML.lessons()), WORDS)
    assert set(model['field_names']) == {'모래섬호', '1호선', '바람개비호', '등대호', '큰등대호'}
    two = '모래섬호와 바람개비호의 정원은 얼마인가?'
    got = R.read(two, model)
    assert got['status'] != 'complete'
    # The reason names the piece that was left over, as for any known piece.
    worst = got['readings'][0]
    assert any(t['what'] == 'known piece left unused' and t['piece'] in ('모래섬호', '바람개비호') and t['count'] == 0
               for t in worst['terms'])
    for text, who in (('모래섬호의 정원은 얼마인가?', '모래섬호'), ('1호선의 정원은 얼마인가?', '1호선')):
        got = R.read(text, model)
        assert got['status'] == 'complete' and _subjects(got, text) == [who]


def test_a_known_name_inside_another_known_name_is_explained_by_it():
    model = PK.with_words(R.build(ML.lessons()), WORDS)
    text = '큰등대호의 정원은 얼마인가?'
    got = R.read(text, model)
    assert got['status'] == 'complete' and _subjects(got, text) == ['큰등대호']


def test_a_name_the_pack_does_not_know_is_still_read_as_a_name():
    model = PK.with_words(R.build(ML.lessons()), WORDS)
    text = '갈매기호의 정원은 얼마인가?'
    got = R.read(text, model)
    assert got['status'] == 'complete' and _subjects(got, text) == ['갈매기호']


def test_fact_subjects_are_known_names_and_fact_values_stay_readable():
    system = PK.load(R.build(ML.lessons()), WORDS, FACTS)
    # A subject that only the fact pack names is known too.
    assert '동쪽항' in system['model']['field_names'] and not system['unusable']
    # F2's value contains the known name "모래섬호"; a value the pack itself states is explained.
    assert '동쪽항의 정원은 모래섬호두척이다.' in system['text']
    assert PK.ask(system, '모래섬호의 정원은 얼마인가?')['answers'] == [['120명']]
    assert PK.ask(system, '동쪽항의 정원은 무엇인가?')['answers'] == [['모래섬호두척']]
    held = PK.ask(system, '동쪽항과 모래섬호의 정원은 얼마인가?')
    assert held['status'] == 'hold' and 'not read with confidence' in held['reason']


def test_a_pack_built_before_the_rule_reads_as_it_did():
    old = json.loads((HERE / 'packs' / 'language.json').read_text(encoding='utf8'))
    assert 'known_names' not in old['conventions']
    model = PK.with_words(old, WORDS)
    assert model.get('field_names', []) == []
    text = '모래섬호와 바람개비호의 정원은 얼마인가?'
    got = R.read(text, model)
    assert got['status'] == 'complete' and _subjects(got, text) == ['모래섬호와 바람개비호']


def test_switching_the_rule_off_is_a_pack_edit():
    language = R.build(ML.lessons())
    del language['conventions']['known_names']
    assert PK.with_words(language, WORDS).get('field_names', []) == []
