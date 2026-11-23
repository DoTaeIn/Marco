"""Stem and ending of a fixed word are found by the reader, letter by letter.

Lessons show the denying word and the checking word in whole forms (아니다, 아니야, 아닙니다,
맞나요, 맞죠 …). Korean writes a stem's last sound and an ending's first sound into one
character (아니 + ㅂ니다 = 아닙니다), so the forms are compared in Unicode's decomposed form.
Public development checks; lessons are the made-up sets of probes/reading_limits.py.
"""
import importlib.util
import json
import unicodedata
from pathlib import Path

from experiments.graph_weighted_acquisition import reader as R

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'probes' / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
S = '모래섬호'


def nfd(word):
    return unicodedata.normalize('NFD', word)


def test_stems_and_endings_are_found_from_whole_forms_and_question_words_are_not_cut():
    _, language, _ = P.build('negation', 'endings')
    stems = language['tables']['closed_stem']
    assert set(stems) == {nfd('맞'), nfd('아니')}
    endings = set(language['tables']['closed_ending']['*'])
    # The ending of 아닙니다 starts with the final consonant that is written into the stem's last character.
    assert {nfd('다'), nfd('야'), nfd('에요'), nfd('나요'), nfd('죠'), nfd('습니까')} <= endings
    assert any(e[0] == 'ᆸ' and e.endswith(nfd('니다')) for e in endings)
    # Every count names the lessons and the word forms it came from.
    cell = next(iter(stems[nfd('아니')].values()))
    assert cell['origins'] and set(cell['forms']) <= {'아니다', '아니야', '아니에요', '아닙니다'}
    # 무엇, 얼마, 어디, 어떤것 share a meaning and some letters; a word that asks is not a stem with endings.
    assert not [s for s in stems if unicodedata.normalize('NFC', s).startswith('어')]


def test_a_form_fused_into_one_character_is_read_and_joins_parts_taught_elsewhere():
    model, _, _ = P.build('negation', 'endings', 'time', 'modifier')
    text = '2027년에 모래섬호의 주말 기본요금은 6000원이 아닙니다.'
    got = R.read(text, model)
    assert got['status'] == 'complete' and not got['ignored'], got['reason']
    assert P.meaning(got['graphs'][0], text) == [P.rel('기본요금', subject=S, at='2027년', when='주말', amount='6000원', denies='아니')]
    word = next(n for n in got['graphs'][0]['nodes'] if n['type'] == 'denial')
    assert text[slice(*word['anchor'])] == '아닙니다'          # the node is the whole word, in the text's own characters


def test_an_ending_learned_from_one_word_is_read_on_another():
    # 죠 is shown only on the checking word (맞죠). No lesson has 아니죠.
    model, language, _ = P.build('negation', 'endings')
    assert '아니죠' not in language['tables']['closed']
    text = '모래섬호의 출발항은 서쪽항이 아니죠.'
    got = R.read(text, model)
    assert got['status'] == 'complete', got['reason']
    assert P.meaning(got['graphs'][0], text) == [P.rel('출발항', subject=S, amount='서쪽항', denies='아니')]
    ending = [t for t in got['readings'][got['chosen']]['terms'] if t['what'] == 'word ending']
    assert len(ending) == 1 and ending[0]['count'] > 0 and ending[0]['forms'] == ['맞죠']
    # A form whose ending no lesson shows on any such word is not read.
    assert R.read('모래섬호의 출발항은 서쪽항이 아니거든.', model)['status'] != 'complete'


def test_a_pack_built_before_this_has_no_such_tables():
    old = json.loads((HERE / 'packs' / 'language.json').read_text(encoding='utf8'))
    assert 'closed_stem' not in old['tables'] and 'closed_stem' not in old['recipe']['meaning']
