"""Corrected lessons for the tax trial: right particle, realistic subject lengths, plain and polite endings.

Everything here is fictional. The lessons teach the sentence shape "X의 P은/는 V이다." and its
questions; they contain no tax subject, value or question from the trial.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# property word -> (question words that fit it, fictional values)
PROPERTIES = {
    '세율': (['얼마', '무엇'], ['7%', '4%', '12%', '2.5%']),
    '과세기간': (['얼마', '무엇'], ['3개월', '1년', '9개월', '2주']),
    '신고횟수': (['몇회', '무엇'], ['연3회', '연1회', '월2회', '연6회']),
    '신고기간': (['언제', '무엇'], ['3월2일~3월9일', '다음달1일~10일', '9월1일~9월15일', '매년2월']),
    '신청기한': (['언제', '무엇'], ['개업일부터7일이내', '다음달10일', '접수후30일이내', '2031년4월2일']),
    '신청경로': (['어디', '무엇'], ['구름창구', '별빛누리', '강변민원실', '온누리센터']),
    '상담전화': (['무엇'], ['311', '1588', '042', '909']),
    '신고기한': (['언제', '무엇'], ['다음해4월30일', '2031년8월1일', '매월15일', '다음달말일']),
}
SUBJECTS = ['푸른별', '노란달조합', '하얀숲', '붉은꽃협동회', '초록산제2구역', '은빛강', '2031년파란섬정기모임', '보라집',
            '금빛들판', '달무리', '제7마을공동체', '새벽길']
ENDINGS = [('이다.', '인가?'), ('입니다.', '인가요?')]


def topic(word):
    """은 after a final consonant, 는 after a vowel."""
    return '은' if (ord(word[-1]) - 0xAC00) % 28 else '는'


def example(ident, kind, subject, prop, last, close):
    text = '%s의 %s%s %s%s' % (subject, prop, topic(prop), last, close)
    s = [0, len(subject)]
    e = [s[1] + 2, s[1] + 2 + len(prop)]
    v = [e[1] + 2, e[1] + 2 + len(last)]
    assert text[slice(*s)] == subject and text[slice(*e)] == prop and text[slice(*v)] == last
    edges = [['e', 'subject', 's'], ['e', 'amount', 'v'], ['e', 'kind', {'literal': prop}], ['s', 'value', {'copy': s}]]
    spans = [[s, e], [e, v], [e], [s]]
    if kind == 'passage':
        edges.append(['v', 'value', {'copy': v}])
        spans.append([v])
    return {'id': ident, 'kind': kind, 'text': text,
            'graph': {'nodes': [{'id': 's', 'type': 'subject', 'anchor': s}, {'id': 'e', 'type': 'relation', 'anchor': e},
                                {'id': 'v', 'type': 'amount', 'anchor': v}],
                      'edges': edges, 'edge_spans': spans, 'project': [] if kind == 'passage' else ['v']}}


def lessons():
    out, n = [], 0
    for p, (prop, (asks, values)) in enumerate(PROPERTIES.items()):
        for k in range(6):
            subject = SUBJECTS[(p * 5 + k * 7) % len(SUBJECTS)]
            closing, asking = ENDINGS[k % 2]
            out.append(example('fix-%03d-p' % n, 'passage', subject, prop, values[k % len(values)], closing))
            out.append(example('fix-%03d-q' % n, 'question', subject, prop, asks[k % len(asks)], asking))
            n += 1
    return out


if __name__ == '__main__':
    data = lessons()
    assert len({x['text'] for x in data}) == len(data)
    (HERE / 'lessons.json').write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf8')
    print(len(data), 'lessons')
