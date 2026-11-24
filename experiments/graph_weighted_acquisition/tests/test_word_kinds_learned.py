"""Where the kind of a field's word comes from: the field pack, a sentence whose form decides, an answer.

No list of such words is written ahead: there is no end to them. The file of word kinds keeps
closed classes of the language only. Public development checks; lessons are the made-up sets of
probes/reading_limits.py, the field is made up here.
"""
import importlib.util
from pathlib import Path

from experiments.graph_weighted_acquisition import learn as L
from experiments.graph_weighted_acquisition import pack as PK
from experiments.graph_weighted_acquisition import reader as R

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'probes' / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
S = '모래섬호'
SETS = ('wordings', 'modifier', 'time', 'conditional')
FACTS = {'schema': PK.FACTS, 'facts': [
    {'id': 'f1', 'subject': S, 'property': '정원', 'value': '30명', 'source': {'url': 'made-up'}},
    {'id': 'f2', 'subject': S, 'property': '기본요금', 'value': '6000원', 'source': {'url': 'made-up'}}]}
OPEN = '모래섬호는 정원이 30명이면 특급 기본요금이 얼마야?'
AFTER_TOPIC = '모래섬호는 특급 기본요금이 6000원이다.'


def system():
    _, language, _ = P.build(*SETS)
    return PK.load(language, P.FERRY, FACTS)


def test_the_list_keeps_closed_classes_only():
    _, language, _ = P.build(*SETS)
    listed = language['tables']['word_kind']
    assert '올해' in listed and '주말' in listed and '월요일' in listed
    assert not {'긴급', '특별', '단체', '임시', '할인'} & set(listed)


def test_a_sentence_whose_form_decides_teaches_the_kind_of_its_word():
    field, memory = system(), L.new_memory()
    # The word is in no list: where the form leaves its role open the reader asks, and after a topic it is passed over.
    asked = PK.ask(field, OPEN, memory)
    assert asked['status'] == 'hold' and [x['piece'] for x in asked['open_roles']] == ['특급']
    assert R.read(AFTER_TOPIC, L.overlay(field['model'], memory))['ignored'] == ['특급']
    assert memory['kinds'] == []
    # "X의 M P는": the head has its subject, so M can only be the modifier. The form decided; that is kept.
    clear = '모래섬호의 특급 기본요금은 얼마인가?'
    PK.ask(field, clear, memory)
    assert memory['kinds'] == [{'word': '특급', 'kind': 'condition', 'seen': [clear], 'told': []}]
    # Now the same word is read where it was not before, and the count names the sentence it came from.
    model = L.overlay(field['model'], memory)
    got = R.read(AFTER_TOPIC, model)
    assert got['status'] == 'complete' and not got['ignored'], got['reason']
    assert P.meaning(got['graphs'][0], AFTER_TOPIC) == [P.rel('기본요금', subject=S, when='특급', amount='6000원')]
    term = [t for t in got['readings'][got['chosen']]['terms'] if t['what'].startswith('kind of a word')]
    assert term[0]['origins'] == ['seen in: ' + clear]
    # And it is no longer taken for a thing: no question about its role.
    assert not R.read(OPEN, model).get('open_roles')
    # The field's packs and the language pack are not changed; forgetting the word undoes it.
    assert '특급' not in field['model']['tables']['word_kind']
    L.forget(memory, '특급')
    assert R.read(AFTER_TOPIC, L.overlay(field['model'], memory))['ignored'] == ['특급']


def test_the_answer_to_the_readers_question_is_one_line_and_is_used():
    field, memory = system(), L.new_memory()
    asked = PK.ask(field, OPEN, memory)
    assert asked['open_roles'][0]['between'] == ['subject', 'when']
    L.tell_kind(memory, '특급', 'condition', by='owner', at='2026-11-24')
    model = L.overlay(field['model'], memory)
    got = R.read(AFTER_TOPIC, model)
    assert got['status'] == 'complete' and P.meaning(got['graphs'][0], AFTER_TOPIC) == [
        P.rel('기본요금', subject=S, when='특급', amount='6000원')]
    assert not R.read(OPEN, model).get('open_roles')
    # Two kinds for one word are a dispute: the word is not used until one is forgotten.
    L.tell_kind(memory, '특급', 'subject', by='another', at='2026-11-24')
    assert '특급' not in L.overlay(field['model'], memory)['tables']['word_kind']


def test_a_name_the_field_states_outranks_the_list():
    # Found by the sixth blind set: a thing named 새벽, a word the list has as a part of the day.
    _, language, _ = P.build(*SETS)
    assert '새벽' in language['tables']['word_kind']
    words = dict(P.FERRY, names=P.FERRY['names'] + [{'name': '새벽', 'also': []}])
    model = PK.with_words(language, words)
    assert '새벽' not in model['tables']['word_kind'] and '새벽' in language['tables']['word_kind']
    text = '새벽의 정원은 30명이다.'
    got = R.read(text, model)
    assert got['status'] == 'complete' and P.meaning(got['graphs'][0], text) == [P.rel('정원', subject='새벽', amount='30명')]
    # Since `word_kinds: where_open` the form alone decides here ("…의" marks a subject), in any field.
    assert R.read(text, PK.with_words(language, P.FERRY))['status'] == 'complete'
    # Where the form is silent the name still outranks the list: bare in front of a property.
    bare = '새벽 정원은 30명이다.'
    got = R.read(bare, model)
    assert got['status'] == 'complete' and P.meaning(got['graphs'][0], bare) == [P.rel('정원', subject='새벽', amount='30명')]
    assert R.read(bare, PK.with_words(language, P.FERRY))['status'] != 'complete'
