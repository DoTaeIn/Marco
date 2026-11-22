"""Lessons for wordings the first corrected set did not teach. All subjects and values are fictional.

Added on top of lessons_fix_20261119:
  - two other words for the rate property, and "몇 퍼센트" as a way to ask for it
  - "X은/는 언제까지 신청해야 하나요?" as a way to ask for the application deadline
  - "X을/를 온라인으로 신청하려면 어디를 이용하면 되나요?" as a way to ask for the application route
  - yes/no checks: "X의 P은/는 V가/이 맞나요?"

These wordings were chosen after seeing which trial questions were held, so a score on those
questions shows that the mechanism works, not that it generalises.
"""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('base_lessons', HERE.parent / 'lessons_fix_20261119' / 'make_lessons.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

PEOPLE = ['금빛들판', '달무리조합', '제7마을공동체', '새벽길', '푸른별', '은빛강모임', '하얀숲', '2031년파란섬정기모임']


def closed(word):
    return bool((ord(word[-1]) - 0xAC00) % 28) if '가' <= word[-1] <= '힣' else False


def build(ident, kind, parts, kind_word, project=None, claim=False):
    """parts: list of (role, text). role in s, e, v, c or None for connecting text."""
    text, at = '', {}
    for role, piece in parts:
        if role:
            at[role] = [len(text), len(text) + len(piece)]
        text += piece
    types = {'s': 'subject', 'e': 'relation', 'v': 'amount', 'c': 'check'}
    nodes = [{'id': r, 'type': types[r], 'anchor': at[r]} for r in ('s', 'e', 'v', 'c') if r in at]
    edges, spans = [['e', 'amount', 'v'], ['e', 'kind', {'literal': kind_word}]], [[at['e'], at['v']], [at['e']]]
    if 's' in at:
        edges.insert(0, ['e', 'subject', 's'])
        spans.insert(0, [at['s'], at['e']])
        edges.append(['s', 'value', {'copy': at['s']}])
        spans.append([at['s']])
    if project is None:
        edges.append(['v', 'value', {'copy': at['v']}])
        spans.append([at['v']])
    if claim:
        edges.append(['e', 'claim', 'c'])
        spans.append([at['e'], at['c']])
    return {'id': ident, 'kind': kind, 'text': text,
            'graph': {'nodes': nodes, 'edges': edges, 'edge_spans': spans, 'project': [project] if project else []}}


def lessons():
    out = list(base.lessons())
    n = 0

    def add(*args, **kwargs):
        nonlocal n
        out.append(build('more-%03d' % n, *args, **kwargs))
        n += 1

    rates = ['7%', '4%', '12%', '2.5%', '9%', '15%']
    for k, word in enumerate(['부가가치세율', '일반세율'] * 3):
        who, rate = PEOPLE[(k * 3) % len(PEOPLE)], rates[k]
        add('passage', [('s', who), (None, '의 '), ('e', word), (None, base.topic(word) + ' '), ('v', rate),
                        (None, '이다.' if k % 2 else '입니다.')], '세율')
        ask = ['몇 퍼센트', '얼마', '무엇'][k % 3]
        add('question', [('s', who), (None, '의 '), ('e', word), (None, base.topic(word) + ' '), ('v', ask),
                         (None, '인가요?' if k % 2 else '인가?')], '세율', project='v')
    for k in range(4):
        who = PEOPLE[(k * 5 + 1) % len(PEOPLE)]
        add('question', [('s', who), (None, '의 '), ('e', '세율'), (None, '은 '), ('v', '몇 퍼센트'),
                         (None, '인가요?' if k % 2 else '인가?')], '세율', project='v')
    for k in range(6):
        who = PEOPLE[(k * 3 + 2) % len(PEOPLE)]
        add('question', [('s', who), (None, base.topic(who) + ' '), ('v', '언제'), (None, '까지 '), ('e', '신청해야'),
                         (None, ' 하나요?' if k % 2 else ' 하는가?')], '신청기한', project='v')
    for k in range(6):
        who = PEOPLE[(k * 5) % len(PEOPLE)]
        mark = '을' if closed(who) else '를'
        add('question', [('s', who), (None, mark + ' 온라인으로 '), ('e', '신청하려면'), (None, ' '), ('v', '어디'),
                         (None, '를 이용하면 되나요?' if k % 2 else '를 이용하면 되는가?')], '신청경로', project='v')
    checks = [('세율', '7%'), ('일반세율', '12%'), ('과세기간', '3개월'), ('신고횟수', '연3회'), ('신청경로', '구름창구'),
              ('부가가치세율', '4%'), ('신고기한', '매월15일'), ('세율', '9%')]
    for k, (word, value) in enumerate(checks):
        who = PEOPLE[(k * 3 + 1) % len(PEOPLE)]
        kind_word = '세율' if word.endswith('세율') else word
        add('question', [('s', who), (None, '의 '), ('e', word), (None, base.topic(word) + ' '), ('v', value),
                         (None, ('이 ' if closed(value) else '가 ')), ('c', '맞나요' if k % 2 else '맞는가'), (None, '?')],
            kind_word, claim=True)
    return out


if __name__ == '__main__':
    data = lessons()
    assert len({x['text'] for x in data}) == len(data) and len({x['id'] for x in data}) == len(data)
    (HERE / 'lessons.json').write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf8')
    print(len(data), 'lessons')
