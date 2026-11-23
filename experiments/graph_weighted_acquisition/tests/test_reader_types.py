"""A node's type must be one that was seen filling its role.

Before this rule the reader chose a word's type from the word or the connector alone. A
question word taught for two roles then gave two readings with the same edges and different
types, and the reader held. Public development checks, made-up words.
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

WORDS = {'schema': PK.WORDS, 'field': 'made-up ferry line',
         'slot': {'type': 'relation', 'attribute': 'kind', 'subject_role': 'subject', 'value_role': 'amount'},
         'properties': [{'word': '정원', 'means': '정원', 'also': []}], 'names': []}


def _asks_for_the_subject():
    """P가 V인 것은 무엇인가?  The same question word as the plain lessons, asking for the subject."""
    out = []
    for i, (word, (_, values)) in enumerate(ML.PROPERTIES.items()):
        for k in range(3):
            parts = [('e', word), (None, '이 ' if ML.closed(word) else '가 '), ('v', values[k]), (None, '인 것은 '),
                     ('x', '무엇'), (None, '인가?')]
            text, at = '', {}
            for node, piece in parts:
                if node:
                    at[node] = [len(text), len(text) + len(piece)]
                text += piece
            kinds = {'e': 'relation', 'v': 'amount', 'x': 'subject'}
            out.append({'id': 'inv-%d-%d' % (i, k), 'kind': 'question', 'text': text, 'graph': {
                'nodes': [{'id': n, 'type': kinds[n], 'anchor': at[n]} for n in at],
                'edges': [['e', 'amount', 'v'], ['e', 'subject', 'x'], ['e', 'kind', {'literal': word}],
                          ['v', 'value', {'copy': at['v']}]],
                'edge_spans': [[at['e'], at['v']], [at['e'], at['x']], [at['e']], [at['v']]], 'project': ['x']}})
    return out


def _types(result, text):
    graph = result['graphs'][0]
    return {text[slice(*n['anchor'])]: n['type'] for n in graph['nodes']}


def test_a_question_word_taught_for_two_roles_no_longer_makes_two_readings():
    language = R.build(ML.lessons() + _asks_for_the_subject())
    assert not language['skipped'] and 'fills' in language['tables']
    model = PK.with_words(language, WORDS)
    plain = '모래섬호의 정원은 무엇인가요?'
    got = R.read(plain, model)
    assert got['status'] == 'complete', got['reason']
    assert _types(got, plain)['무엇'] == 'amount'
    turned = '정원이 120명인 것은 무엇인가?'
    got = R.read(turned, model)
    assert got['status'] == 'complete', got['reason']
    assert _types(got, turned)['무엇'] == 'subject' and got['graphs'][0]['project']


def test_the_rule_is_shown_with_its_count_like_every_other_decision():
    model = PK.with_words(R.build(ML.lessons()), WORDS)
    got = R.read('모래섬호의 정원은 얼마인가?', model)
    terms = [t for t in got['readings'][got['chosen']]['terms'] if t['what'] == 'kind of thing that fills this role']
    assert len(terms) == 2 and all(t['count'] > 0 and t['origins'] for t in terms)


def test_a_pack_built_before_the_rule_reads_as_it_did():
    # The shipped language pack carries its own recipe and has no "fills" table.
    old = json.loads((HERE / 'packs' / 'language.json').read_text(encoding='utf8'))
    assert 'fills' not in old['tables']
    model = PK.with_words(old, WORDS)
    got = R.read('모래섬호의 정원은 얼마인가?', model)
    assert got['status'] == 'complete'
    assert not [t for t in got['readings'][got['chosen']]['terms'] if t.get('table') == 'fills']
    # The same holds for a new recipe on a pack whose table is missing: the rule is skipped, not failed.
    fresh = R.build(ML.lessons())
    del fresh['tables']['fills']
    assert R.read('푸른별의 빛깔은 무엇인가?', fresh)['status'] == 'complete'
