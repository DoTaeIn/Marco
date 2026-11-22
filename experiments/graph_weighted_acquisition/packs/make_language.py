"""Field-free lessons for the language pack.

Every property word, subject and value here is made up and belongs to no field. The lessons
teach only how such sentences are built: "X의 P은/는 V이다.", its questions, polite endings and
yes/no checks. A field brings its own words in a word pack.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# made-up property word -> (ways to ask for it, made-up values)
PROPERTIES = {
    '빛깔': (['무엇', '어떤것'], ['쪽빛', '감빛', '잿빛', '풀빛']),
    '무게': (['얼마', '무엇'], ['3근', '12돈', '7.5섬', '40푼']),
    '나이': (['얼마', '무엇'], ['9살', '31살', '108살', '2살']),
    '높이': (['얼마', '무엇'], ['6자', '25길', '3.2척', '90치']),
    '절기': (['언제', '무엇'], ['첫서리무렵', '3월2일~3월9일', '다음달보름', '2031년8월1일']),
    '터전': (['어디', '무엇'], ['구름골', '별빛나루', '강변마을', '온누리재']),
    '차례': (['몇번', '무엇'], ['셋째', '연3회', '월2회', '첫째']),
    '부름말': (['무엇'], ['311', '1588', '042', '909']),
}
SUBJECTS = ['푸른별', '노란달조합', '하얀숲', '붉은꽃협동회', '초록산제2구역', '은빛강', '2031년파란섬정기모임', '보라집',
            '금빛들판', '달무리', '제7마을공동체', '새벽길']
ENDINGS = [('이다.', '인가?'), ('입니다.', '인가요?')]


def closed(word):
    return bool((ord(word[-1]) - 0xAC00) % 28) if '가' <= word[-1] <= '힣' else False


def build(ident, kind, parts, kind_word, project=None, claim=False):
    text, at = '', {}
    for role, piece in parts:
        if role:
            at[role] = [len(text), len(text) + len(piece)]
        text += piece
    types = {'s': 'subject', 'e': 'relation', 'v': 'amount', 'c': 'check'}
    nodes = [{'id': r, 'type': types[r], 'anchor': at[r]} for r in ('s', 'e', 'v', 'c') if r in at]
    edges = [['e', 'subject', 's'], ['e', 'amount', 'v'], ['e', 'kind', {'literal': kind_word}],
             ['s', 'value', {'copy': at['s']}]]
    spans = [[at['s'], at['e']], [at['e'], at['v']], [at['e']], [at['s']]]
    if project is None:
        edges.append(['v', 'value', {'copy': at['v']}])
        spans.append([at['v']])
    if claim:
        edges.append(['e', 'claim', 'c'])
        spans.append([at['e'], at['c']])
    return {'id': ident, 'kind': kind, 'text': text,
            'graph': {'nodes': nodes, 'edges': edges, 'edge_spans': spans, 'project': [project] if project else []}}


def lessons():
    out, n = [], 0
    for p, (word, (asks, values)) in enumerate(PROPERTIES.items()):
        topic = '은' if closed(word) else '는'
        for k in range(6):
            who = SUBJECTS[(p * 5 + k * 7) % len(SUBJECTS)]
            closing, asking = ENDINGS[k % 2]
            lead = [('s', who), (None, '의 '), ('e', word), (None, topic + ' ')]
            out.append(build('lang-%03d-s' % n, 'passage', lead + [('v', values[k % len(values)]), (None, closing)], word))
            out.append(build('lang-%03d-q' % n, 'question', lead + [('v', asks[k % len(asks)]), (None, asking)], word,
                             project='v'))
            n += 1
        for k in range(2):
            who, value = SUBJECTS[(p * 3 + k * 5 + 1) % len(SUBJECTS)], values[(k + 1) % len(values)]
            out.append(build('lang-%03d-c' % n, 'question',
                             [('s', who), (None, '의 '), ('e', word), (None, topic + ' '), ('v', value),
                              (None, '이 ' if closed(value) else '가 '), ('c', '맞나요' if k else '맞는가'), (None, '?')],
                             word, claim=True))
            n += 1
    return out


if __name__ == '__main__':
    data = lessons()
    assert len({x['text'] for x in data}) == len(data)
    (HERE / 'language_lessons.json').write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf8')
    print(len(data), 'lessons')
