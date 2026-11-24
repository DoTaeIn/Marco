"""Probe: what the piece reader can read, now and after lessons only.

A development probe on public material: the shipped field-free lessons, made-up extra
lessons written here, and a made-up ferry vocabulary that no lesson contains. It changes no
code and no pack. It is not an evaluation: the sentences were written by the implementer.

Run from the repository root:
  PYTHONPATH=. python experiments/graph_weighted_acquisition/probes/reading_limits.py
"""
import importlib.util
import json
import time
from pathlib import Path

from experiments.graph_weighted_acquisition import pack as PK
from experiments.graph_weighted_acquisition import reader as R

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('make_language', HERE / 'packs' / 'make_language.py')
ML = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ML)
VARIANTS = json.loads((HERE / 'data' / 'connector_variants_ko.json').read_text(encoding='utf8'))
KINDS = json.loads((HERE / 'data' / 'word_kinds_ko.json').read_text(encoding='utf8'))     # since 2026-11-24

PROPS = list(ML.PROPERTIES)
SUBJ = ML.SUBJECTS
MODS = ['겨울', '여름', '새벽', '한낮', '장날', '그믐']
TIMES = ['2031년', '3월', '작년', '첫눈오는날']


def topic(word):
    return '은 ' if ML.closed(word) else '는 '


def subj(word):
    return '이 ' if ML.closed(word) else '가 '


def lesson(ident, kind, parts, edges, project=(), fixed=()):
    """parts: (node id or None, node type or None, text). edges: (head, role, node) or (head, attribute, ('lit', word))."""
    text, at, types = '', {}, {}
    for node, kind_of, piece in parts:
        if node:
            at[node], types[node] = [len(text), len(text) + len(piece)], kind_of
        text += piece
    out_edges, spans, heads = [], [], {s for s, _, _ in edges}
    for s, p, o in edges:
        if isinstance(o, tuple):
            out_edges.append([s, p, {'literal': o[1]}])
            spans.append([at[s]])
        else:
            out_edges.append([s, p, o])
            spans.append(sorted([at[s], at[o]]))      # in text order, as the shipped lessons have it
    for node in at:
        if node not in heads and node not in project and node not in fixed:
            out_edges.append([node, 'value', {'copy': at[node]}])
            spans.append([at[node]])
    return {'id': ident, 'kind': kind, 'text': text,
            'graph': {'nodes': [{'id': n, 'type': types[n], 'anchor': at[n]} for n in at],
                      'edges': out_edges, 'edge_spans': spans, 'project': list(project)}}


def value_of(p, k):
    return ML.PROPERTIES[p][1][k % 4]


def ask_of(p, k):
    asks = ML.PROPERTIES[p][0]
    return asks[k % len(asks)]


def modifier():
    """X의 M P는 V이다. / X의 M P는 무엇인가?   the modifier is one more part of the relation."""
    out = []
    for i, p in enumerate(PROPS):
        for k in range(3):
            who, m = SUBJ[(i * 3 + k * 5) % len(SUBJ)], MODS[(i + k * 2) % len(MODS)]
            lead = [('s', 'subject', who), (None, None, '의 '), ('m', 'condition', m), (None, None, ' '),
                    ('e', 'relation', p), (None, None, topic(p))]
            edges = [('e', 'subject', 's'), ('e', 'when', 'm'), ('e', 'amount', 'v'), ('e', 'kind', ('lit', p))]
            out.append(lesson('mod-%d-%d-s' % (i, k), 'passage', lead + [('v', 'amount', value_of(p, k)), (None, None, '이다.')], edges))
            out.append(lesson('mod-%d-%d-q' % (i, k), 'question', lead + [('v', 'amount', ask_of(p, k)), (None, None, '인가?')],
                              edges, project=('v',)))
    return out


def at_time():
    """T에 X의 P는 V이다. / T에 X의 P는 무엇인가?"""
    out = []
    for i, p in enumerate(PROPS):
        for k in range(3):
            who, t = SUBJ[(i * 5 + k * 3 + 2) % len(SUBJ)], TIMES[(i + k) % len(TIMES)]
            lead = [('t', 'time', t), (None, None, '에 '), ('s', 'subject', who), (None, None, '의 '),
                    ('e', 'relation', p), (None, None, topic(p))]
            edges = [('e', 'at', 't'), ('e', 'subject', 's'), ('e', 'amount', 'v'), ('e', 'kind', ('lit', p))]
            out.append(lesson('time-%d-%d-s' % (i, k), 'passage', lead + [('v', 'amount', value_of(p, k)), (None, None, '이다.')], edges))
            out.append(lesson('time-%d-%d-q' % (i, k), 'question', lead + [('v', 'amount', ask_of(p, k)), (None, None, '인가?')],
                              edges, project=('v',)))
    return out


def negation():
    """X의 P는 V가 아니다.   the relation is denied by a fixed word under it, the same shape as a claim check."""
    out = []
    for i, p in enumerate(PROPS):
        for k in range(4):
            who, v = SUBJ[(i * 7 + k * 5 + 1) % len(SUBJ)], value_of(p, k)
            out.append(lesson('neg-%d-%d' % (i, k), 'passage',
                              [('s', 'subject', who), (None, None, '의 '), ('e', 'relation', p), (None, None, topic(p)),
                               ('v', 'amount', v), (None, None, subj(v)), ('c', 'denial', '아니다'), (None, None, '.')],
                              [('e', 'subject', 's'), ('e', 'amount', 'v'), ('e', 'denies', 'c'), ('e', 'kind', ('lit', p))],
                              fixed=('c',)))
    return out


def conditional():
    """X의 P가 V이면 X의 Q는 W이다.   the first relation stands under the second one, as its condition."""
    out = []
    for i, p in enumerate(PROPS):
        for k in range(4):
            q = PROPS[(i + 1 + k) % len(PROPS)]
            who = SUBJ[(i * 3 + k * 7 + 4) % len(SUBJ)]
            out.append(lesson('if-%d-%d' % (i, k), 'passage',
                              [('s1', 'subject', who), (None, None, '의 '), ('e1', 'relation', p), (None, None, subj(p)),
                               ('v', 'amount', value_of(p, k)), (None, None, '이면 '),
                               ('s2', 'subject', who), (None, None, '의 '), ('e2', 'relation', q), (None, None, topic(q)),
                               ('w', 'amount', value_of(q, k + 1)), (None, None, '이다.')],
                              [('e1', 'subject', 's1'), ('e1', 'amount', 'v'), ('e1', 'kind', ('lit', p)),
                               ('e2', 'subject', 's2'), ('e2', 'amount', 'w'), ('e2', 'if', 'e1'), ('e2', 'kind', ('lit', q))]))
    return out


def shared():
    """X는 P가 V이면 Q가 W이다. / … Q가 얼마인가?   one subject, written once, for both relations."""
    out = []
    for i, p in enumerate(PROPS):
        for k in range(3):
            q = PROPS[(i + 2 + k) % len(PROPS)]
            who = SUBJ[(i * 5 + k * 3 + 1) % len(SUBJ)]
            lead = [('s', 'subject', who), (None, None, topic(who)), ('e1', 'relation', p), (None, None, subj(p)),
                    ('v', 'amount', value_of(p, k)), (None, None, '이면 '), ('e2', 'relation', q), (None, None, subj(q))]
            edges = [('e1', 'subject', 's'), ('e1', 'amount', 'v'), ('e1', 'kind', ('lit', p)),
                     ('e2', 'subject', 's'), ('e2', 'amount', 'w'), ('e2', 'if', 'e1'), ('e2', 'kind', ('lit', q))]
            out.append(lesson('share-%d-%d-s' % (i, k), 'passage', lead + [('w', 'amount', value_of(q, k + 1)), (None, None, '이다.')], edges))
            out.append(lesson('share-%d-%d-q' % (i, k), 'question', lead + [('w', 'amount', ask_of(q, k)), (None, None, '인가?')],
                              edges, project=('w',)))
    return out


def inverse():
    """P가 V인 것은 무엇인가? / P가 V 이상인 것은 무엇인가?   the subject is asked for."""
    out = []
    for i, p in enumerate(PROPS):
        for k in range(3):
            v = value_of(p, k)
            head = [('e', 'relation', p), (None, None, subj(p)), ('v', 'amount', v)]
            tail = [('x', 'subject', '무엇'), (None, None, '인가?')]
            edges = [('e', 'amount', 'v'), ('e', 'subject', 'x'), ('e', 'kind', ('lit', p))]
            out.append(lesson('inv-eq-%d-%d' % (i, k), 'question', head + [(None, None, '인 것은 ')] + tail, edges, project=('x',)))
            # A comparison is a fixed word under the relation; its type says which comparison.
            out.append(lesson('inv-ge-%d-%d' % (i, k), 'question',
                              head + [(None, None, ' '), ('c', 'at_least', '이상'), (None, None, '인 것은 ')] + tail,
                              edges + [('e', 'compare', 'c')], project=('x',), fixed=('c',)))
    return out


def chain():
    """X의 P의 Q는 V이다.   the second relation is about the first one's value: a head as an argument."""
    out = []
    for i, p in enumerate(PROPS):
        for k in range(3):
            q, who = PROPS[(i + 2 + k) % len(PROPS)], SUBJ[(i + k * 5) % len(SUBJ)]
            lead = [('s', 'subject', who), (None, None, '의 '), ('e1', 'relation', p), (None, None, '의 '),
                    ('e2', 'relation', q), (None, None, topic(q))]
            edges = [('e1', 'subject', 's'), ('e1', 'kind', ('lit', p)), ('e2', 'subject', 'e1'), ('e2', 'amount', 'v'),
                     ('e2', 'kind', ('lit', q))]
            out.append(lesson('chain-%d-%d-s' % (i, k), 'passage', lead + [('v', 'amount', value_of(q, k)), (None, None, '이다.')], edges))
            out.append(lesson('chain-%d-%d-q' % (i, k), 'question', lead + [('v', 'amount', ask_of(q, k)), (None, None, '인가?')],
                              edges, project=('v',)))
    return out


def wordings():
    """The plain shape in more wordings: other endings, 이/가 after the property, no 의, topic on the subject."""
    out, n = [], 0

    def add(kind, parts, p, project=()):
        nonlocal n
        out.append(lesson('word-%03d' % n, kind, parts, [('e', 'subject', 's'), ('e', 'amount', 'v'), ('e', 'kind', ('lit', p))], project))
        n += 1

    for i, p in enumerate(PROPS):
        for k in range(4):
            who, v, ask = SUBJ[(i * 5 + k * 7 + 3) % len(SUBJ)], value_of(p, k), ask_of(p, k)
            s, e = ('s', 'subject', who), ('e', 'relation', p)
            lead = [s, (None, None, '의 '), e, (None, None, topic(p))]
            said, asked = ('v', 'amount', v), ('v', 'amount', ask)
            state = [('이에요.' if ML.closed(v) else '예요.'), ('이야.' if ML.closed(v) else '야.')][k % 2]
            add('passage', lead + [said, (None, None, state)], p)
            add('question', lead + [asked, (None, None, ['입니까?', '이에요?' if ML.closed(ask) else '예요?',
                                                         '이야?' if ML.closed(ask) else '야?', '입니까?'][k])], p, ('v',))
            other = [[s, (None, None, ' '), e, (None, None, topic(p))],                        # no 의
                     [s, (None, None, topic(who)), e, (None, None, subj(p))]][k % 2]           # X는 P가
            add('passage', other + [said, (None, None, '이다.')], p)
            add('question', other + [asked, (None, None, '인가?')], p, ('v',))
    return out


def endings():
    """More forms of the denying word and the checking word, each shown whole.

    The lessons do not cut the words. The reader compares the forms of one word letter by letter
    and finds stem and ending itself (아니 + 다 / 야 / 에요 / ㅂ니다, 맞 + 나요 / 는가 / 아요 / 죠 /
    습니까). Taught on the plain shape only.
    """
    out, n = [], 0
    for i, p in enumerate(PROPS):
        for k in range(3):
            who, v = SUBJ[(i * 3 + k * 7 + 5) % len(SUBJ)], value_of(p, k)
            lead = [('s', 'subject', who), (None, None, '의 '), ('e', 'relation', p), (None, None, topic(p)),
                    ('v', 'amount', v), (None, None, subj(v))]
            base = [('e', 'subject', 's'), ('e', 'amount', 'v'), ('e', 'kind', ('lit', p))]
            form = ['아니야', '아니에요', '아닙니다'][(i + k) % 3]
            out.append(lesson('end-%03d' % n, 'passage', lead + [('c', 'denial', form), (None, None, '.')],
                              base + [('e', 'denies', 'c')], fixed=('c',)))
            form = ['맞아요', '맞죠', '맞습니까'][(i + k) % 3]
            out.append(lesson('end-%03d' % (n + 1), 'question', lead + [('c', 'check', form), (None, None, '?')],
                              base + [('e', 'claim', 'c')], fixed=('c',)))
            n += 2
    return out


SETS = {'wordings': wordings, 'endings': endings, 'modifier': modifier, 'time': at_time, 'negation': negation, 'conditional': conditional, 'inverse': inverse,
        'chain': chain, 'shared': shared}      # 'shared' added 2026-11-24

FERRY = {'schema': PK.WORDS, 'field': 'made-up ferry line',
         'slot': {'type': 'relation', 'attribute': 'kind', 'subject_role': 'subject', 'value_role': 'amount'},
         'properties': [{'word': w, 'means': w, 'also': []} for w in
                        ('정원', '첫출항', '기본요금', '출발항', '문의전화', '할인율', '연령')],
         'names': [{'name': '모래섬호', 'also': []}, {'name': '바람개비호', 'also': []}]}


def meaning(graph, text):
    """What a reading says, without node ids: per head, its attributes and the text in each role."""
    anchor = {n['id']: n['anchor'] for n in graph['nodes']}
    out = []
    for node in graph['nodes']:
        roles = sorted((p, 'ASK' if o in graph['project'] else 'YES' if p == 'denies' else text[slice(*anchor[o])])
                       for s, p, o in graph['edges'] if s == node['id'] and isinstance(o, str))
        literals = sorted(o['literal'] for s, p, o in graph['edges'] if s == node['id'] and isinstance(o, dict) and 'literal' in o)
        if roles or literals:
            out.append((tuple(literals), tuple(roles)))
    return sorted(out)


def rel(kind, **roles):
    if 'denies' in roles:
        roles['denies'] = 'YES'            # what matters is that it is denied, not the form of the word
    return ((kind,), tuple(sorted(roles.items())))


def judge(model, text, expected):
    result = R.read(text, model)
    if result['status'] != 'complete':
        return 'HELD', '%s: %s' % (result['status'], result['reason'][:70])
    got = meaning(result['graphs'][0], text)
    if result.get('ignored'):
        return 'PARTIAL', 'ignored %s' % result['ignored']
    if got != sorted(expected):
        return 'OTHER', 'read as %s' % got
    return 'OK', '; '.join(result.get('variants', []))[:60]


S, ASK = '모래섬호', 'ASK'
PLAIN_Q = [rel('정원', subject=S, amount=ASK)]
PLAIN_S = [rel('정원', subject=S, amount='120명')]
WORDINGS = [   # one meaning, many ways to say it; only the first of each block is the taught shape
    ('모래섬호의 정원은 얼마인가?', PLAIN_Q), ('모래섬호의 정원은 무엇인가요?', PLAIN_Q),
    ('모래섬호의 정원은 얼마입니까?', PLAIN_Q), ('모래섬호의 정원은 얼마예요?', PLAIN_Q), ('모래섬호의 정원은 얼마야?', PLAIN_Q),
    ('모래섬호의 정원이 얼마인가?', PLAIN_Q), ('모래섬호 정원은 얼마인가?', PLAIN_Q), ('모래섬호는 정원이 얼마인가?', PLAIN_Q),
    ('모래섬호의 정원은 몇 명인가?', PLAIN_Q), ('모래섬호의 정원은?', PLAIN_Q), ('모래섬호의 정원을 알려줘.', PLAIN_Q),
    ('모래섬호의 정원이 궁금하다.', PLAIN_Q), ('모래섬호에는 몇 명이 탈 수 있나?', PLAIN_Q),
    ('모래섬호의 정원은 120명이다.', PLAIN_S), ('모래섬호의 정원은 120명입니다.', PLAIN_S), ('모래섬호의 정원은 120명이에요.', PLAIN_S),
    ('모래섬호의 정원은 120명이야.', PLAIN_S), ('모래섬호의 정원이 120명이다.', PLAIN_S), ('모래섬호 정원은 120명이다.', PLAIN_S),
    ('모래섬호는 정원이 120명이다.', PLAIN_S), ('모래섬호의 정원은 120명', PLAIN_S),
    ('모래섬호와 바람개비호의 정원은 얼마인가?', [rel('정원', subject='모래섬호', amount=ASK), rel('정원', subject='바람개비호', amount=ASK)]),
    ('모래섬호의 정원은 대략 얼마인가?', PLAIN_Q),
]
SHAPES = {   # new constructions, each with the lesson set that teaches its shape
    'modifier': [('모래섬호의 평일 첫출항은 언제인가?', [rel('첫출항', subject=S, when='평일', amount=ASK)]),
                 ('모래섬호의 주말 첫출항은 8시30분이다.', [rel('첫출항', subject=S, when='주말', amount='8시30분')]),
                 ('바람개비호의 공휴일 기본요금은 얼마인가?', [rel('기본요금', subject='바람개비호', when='공휴일', amount=ASK)])],
    'time': [('2027년에 모래섬호의 기본요금은 얼마인가?', [rel('기본요금', subject=S, at='2027년', amount=ASK)]),
             ('내년에 모래섬호의 기본요금은 6000원이다.', [rel('기본요금', subject=S, at='내년', amount='6000원')])],
    'negation': [('모래섬호의 출발항은 서쪽항이 아니다.', [rel('출발항', subject=S, amount='서쪽항', denies='아니')]),
                 ('바람개비호의 정원은 80명이 아니다.', [rel('정원', subject='바람개비호', amount='80명', denies='아니')])],
    'conditional': [('승객의 연령이 65세이면 승객의 할인율은 50%이다.',
                     [rel('연령', subject='승객', amount='65세'), rel('할인율', **{'if': '연령'}, subject='승객', amount='50%')]),
                    ('배의 정원이 120명이면 배의 기본요금은 6000원이다.',
                     [rel('정원', subject='배', amount='120명'), rel('기본요금', **{'if': '정원'}, subject='배', amount='6000원')])],
    'inverse': [('출발항이 동쪽항인 것은 무엇인가?', [rel('출발항', amount='동쪽항', subject=ASK)]),
                ('정원이 100명 이상인 것은 무엇인가?', [rel('정원', amount='100명', compare='이상', subject=ASK)])],
    'chain': [('모래섬호의 출발항의 문의전화는 무엇인가?', [rel('출발항', subject=S), rel('문의전화', subject='출발항', amount=ASK)]),
              ('모래섬호의 출발항의 문의전화는 0412이다.', [rel('출발항', subject=S), rel('문의전화', subject='출발항', amount='0412')])],
}
MIXES = [   # two taught things in one sentence; no lesson shows them together
    ('modifier + polite ending', '모래섬호의 평일 첫출항은 언제인가요?', [rel('첫출항', subject=S, when='평일', amount=ASK)]),
    ('modifier + polite statement', '모래섬호의 주말 첫출항은 8시30분입니다.', [rel('첫출항', subject=S, when='주말', amount='8시30분')]),
    ('modifier + claim check', '모래섬호의 평일 첫출항은 7시가 맞나요?', [rel('첫출항', subject=S, when='평일', amount='7시', claim='맞나요')]),
    ('time + modifier', '2027년에 모래섬호의 평일 첫출항은 언제인가?', [rel('첫출항', subject=S, at='2027년', when='평일', amount=ASK)]),
    ('time + negation', '2027년에 모래섬호의 출발항은 서쪽항이 아니다.', [rel('출발항', subject=S, at='2027년', amount='서쪽항', denies='아니')]),
    ('modifier + negation', '모래섬호의 주말 출발항은 서쪽항이 아니다.', [rel('출발항', subject=S, when='주말', amount='서쪽항', denies='아니')]),
    ('time + claim check', '2027년에 모래섬호의 기본요금은 6000원이 맞는가?', [rel('기본요금', subject=S, at='2027년', amount='6000원', claim='맞는가')]),
    ('time + inverse', '2027년에 출발항이 동쪽항인 것은 무엇인가?', [rel('출발항', at='2027년', amount='동쪽항', subject=ASK)]),
    ('conditional + modifier', '승객의 연령이 65세이면 승객의 평일 할인율은 50%이다.',
     [rel('연령', subject='승객', amount='65세'), rel('할인율', **{'if': '연령'}, subject='승객', when='평일', amount='50%')]),
    ('conditional + polite ending', '승객의 연령이 65세이면 승객의 할인율은 50%입니다.',
     [rel('연령', subject='승객', amount='65세'), rel('할인율', **{'if': '연령'}, subject='승객', amount='50%')]),
    ('conditional + negation', '승객의 연령이 65세이면 승객의 할인율은 50%가 아니다.',
     [rel('연령', subject='승객', amount='65세'), rel('할인율', **{'if': '연령'}, subject='승객', amount='50%', denies='아니')]),
    ('conditional + time', '2027년에 승객의 연령이 65세이면 승객의 할인율은 50%이다.',
     [rel('연령', subject='승객', at='2027년', amount='65세'), rel('할인율', **{'if': '연령'}, subject='승객', amount='50%')]),
]


CROSS = [   # a wording taught only on the plain shape, used inside a construction taught only with plain wording
    ('modifier + 입니까', '모래섬호의 평일 첫출항은 언제입니까?', [rel('첫출항', subject=S, when='평일', amount=ASK)]),
    ('modifier + 예요', '모래섬호의 주말 첫출항은 8시예요.', [rel('첫출항', subject=S, when='주말', amount='8시')]),
    ('modifier + no 의', '모래섬호 평일 첫출항은 언제인가?', [rel('첫출항', subject=S, when='평일', amount=ASK)]),
    ('time + 야', '2027년에 모래섬호의 기본요금은 얼마야?', [rel('기본요금', subject=S, at='2027년', amount=ASK)]),
    ('time + X는 P가', '2027년에 모래섬호는 기본요금이 얼마인가?', [rel('기본요금', subject=S, at='2027년', amount=ASK)]),
    ('conditional + 이에요', '승객의 연령이 65세이면 승객의 할인율은 50%예요.',
     [rel('연령', subject='승객', amount='65세'), rel('할인율', **{'if': '연령'}, subject='승객', amount='50%')]),
    ('conditional + X는 P가', '승객의 연령이 65세이면 승객은 할인율이 50%이다.',
     [rel('연령', subject='승객', amount='65세'), rel('할인율', **{'if': '연령'}, subject='승객', amount='50%')]),
]


def build(*names, recipe=None, kinds=KINDS):
    lessons = ML.lessons() + [x for name in names for x in SETS[name]()]
    language = R.build(lessons, variants=VARIANTS, kinds=kinds)
    if recipe:
        language = dict(language, recipe=recipe(json.loads(json.dumps(language['recipe']))))
    return PK.with_words(language, FERRY), language, len(lessons)


def no_frame(recipe):
    """A pack edit, no code: stop requiring that a head's whole set of parts was seen together."""
    recipe['head'] = []
    return recipe


def table(title, model, rows):
    print('\n## ' + title)
    tally = {}
    for label, text, expected in rows:
        verdict, note = judge(model, text, expected)
        tally[verdict] = tally.get(verdict, 0) + 1
        print('%-8s %-28s %s   %s' % (verdict, label[:28], text, note))
    print('-> ' + ', '.join('%s %d' % kv for kv in sorted(tally.items())) + ' of %d' % len(rows))
    return tally


def library(language):
    packs = HERE / 'packs'
    system = PK.load(language, json.loads((packs / 'library_words.json').read_text(encoding='utf8')),
                     json.loads((packs / 'library_facts.json').read_text(encoding='utf8')))
    right = wrong = held = 0
    for item in json.loads((packs / 'library_questions.json').read_text(encoding='utf8')):
        result = PK.ask(system, item['text'])
        if result['status'] != 'answered':
            held += 1 if item['expect'] is not None else 0
            right += 1 if item['expect'] is None else 0
        elif result['answers'] == [[item['expect']]]:
            right += 1
        else:
            wrong += 1
    return right, wrong, held


def main():
    base, base_language, n = build()
    print('# Base language pack: %d lessons, built from the shipped generator and raw-text variants' % n)
    table('1. One meaning, many wordings (base pack; only the first two wordings were taught)', base,
          [('', text, expected) for text, expected in WORDINGS])
    print('\n## 2. New constructions: before and after lessons that teach the shape (unseen words and names)')
    for name, rows in SHAPES.items():
        taught, _, n = build(name)
        before = [judge(base, text, expected)[0] for text, expected in rows]
        print('\n### %s (+%d lessons)' % (name, n - len(ML.lessons())))
        for (text, expected), was in zip(rows, before):
            verdict, note = judge(taught, text, expected)
            print('%-8s (before: %-7s) %s   %s' % (verdict, was, text, note))
    names = [n for n in SETS if n not in ('chain', 'wordings', 'endings')]
    everything, language, n = build(*names)
    print('\n# All construction sets except chain together: %d lessons' % n)
    table('3. Each construction again with every set loaded (do the sets disturb each other?)', everything,
          [(name, text, expected) for name in names for text, expected in SHAPES[name]])
    table('4. Two taught things in one sentence, never shown together', everything, MIXES)
    table('5. The wordings of table 1 again with every set loaded', everything, [('', t, e) for t, e in WORDINGS])
    print('\n## 6. Library questions (public pack, 15 questions with expected answers): right / wrong / held')
    print('base pack      %d / %d / %d' % library(base_language))
    print('every set      %d / %d / %d' % library(language))
    start = time.perf_counter()
    for _, text, _ in MIXES:
        R.read(text, everything)
    print('\n12 mixed sentences read in %.2f s with every set loaded' % (time.perf_counter() - start))

    worded, worded_language, n = build('wordings')
    print('\n# Base + wordings set: %d lessons' % n)
    table('7. The wordings of table 1 after lessons for more wordings (plain shape only)', worded,
          [('', t, e) for t, e in WORDINGS])
    full, full_language, n = build('wordings', *names)
    print('\n# Wordings + every construction set: %d lessons' % n)
    table('8. A wording and a construction taught separately, used together', full, CROSS)
    table('9. Table 1 wordings with everything loaded', full, [('', t, e) for t, e in WORDINGS])
    print('library, everything loaded      %d / %d / %d' % library(full_language))

    loose, loose_language, _ = build('wordings', *names, recipe=no_frame)
    print('\n# Same lessons, one pack edit: the "set of roles for this head" rule removed from the recipe')
    table('10. Table 4 again (two taught things together)', loose, MIXES)
    table('11. Table 8 again', loose, CROSS)
    table('12. Each construction again', loose, [(name, t, e) for name in names for t, e in SHAPES[name]])
    table('13. Table 1 wordings again', loose, [('', t, e) for t, e in WORDINGS])
    print('library, rule removed           %d / %d / %d' % library(loose_language))
    chained, _, _ = build('chain', recipe=no_frame)
    table('14. Chain with its lessons and the rule removed', chained, [('chain', t, e) for t, e in SHAPES['chain']])

    # A what-if, patched in here only to test a diagnosis; reader.py is not changed. The reader picks a
    # node's type from the word or the connector, independently of its role. This drops readings in
    # which a role is filled by a type that never filled it in the lessons.
    lessons = ML.lessons() + [x for name in ['wordings'] + names for x in SETS[name]()]
    fills = set()
    for ex in lessons:
        kinds = {node['id']: node['type'] for node in ex['graph']['nodes']}
        fills |= {(p, kinds[o]) for s, p, o in ex['graph']['edges'] if isinstance(o, str)}
    original = R._graph

    def agreeing(text, model, mentions, spans, entries, by_head):
        if any((role, entries[a]['type']) not in fills for roles in by_head.values() for role, a in roles):
            return None, False
        return original(text, model, mentions, spans, entries, by_head)

    R._graph = agreeing
    try:
        print('\n# What-if (patched in this probe only): a role must be filled by a type seen in that role')
        table('15. Table 8 (wording + construction), whole-set rule kept', full, CROSS)
        table('16. Table 4 (two constructions), whole-set rule kept', full, MIXES)
        table('17. Each construction', full, [(name, t, e) for name in names for t, e in SHAPES[name]])
        table('18. Table 1 wordings', full, [('', t, e) for t, e in WORDINGS])
        print('library, what-if                %d / %d / %d' % library(full_language))
        table('19. Table 4 with the whole-set rule removed as well', loose, MIXES)
        table('20. Each construction with the whole-set rule removed as well', loose,
              [(name, t, e) for name in names for t, e in SHAPES[name]])
    finally:
        R._graph = original


if __name__ == '__main__':
    main()
