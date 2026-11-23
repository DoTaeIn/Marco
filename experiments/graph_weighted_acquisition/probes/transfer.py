"""How many sentences does one taught thing open?

Every feature below is taught on its own, in lessons with made-up words: a time in front, a
modifier before the property, a claim check, a denial, and several sentence endings. The grid
is every combination of those features on words no lesson contains. A combination that some
lesson shows as a whole is "taught"; the rest are "combined": each part was taught, the
sentence as a whole never was.

  transfer = combined sentences read exactly as meant / combined sentences

Near 0 the reader memorises sentence shapes; near 1 a lesson is worth every sentence its part
can occur in. The grid is generated, not picked, but it was designed by the implementer: a
development measure, not an evaluation.

Run from the repository root:
  PYTHONPATH=. python experiments/graph_weighted_acquisition/probes/transfer.py
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('reading_limits', HERE / 'reading_limits.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

S, PROP, V, T, M = '모래섬호', '기본요금', '6000원', '2027년', '주말'
TAILS = [   # (form, ending, text after "…기본요금은 ", extra parts of the meaning, endings the lessons show with a bare relation)
    ('state', '이다', V + '이다.', {'amount': V}),
    ('state', '입니다', V + '입니다.', {'amount': V}),
    ('state', '이야', V + '이야.', {'amount': V}),
    ('ask', '인가', '얼마인가?', {'amount': 'ASK'}),
    ('ask', '인가요', '얼마인가요?', {'amount': 'ASK'}),
    ('ask', '입니까', '얼마입니까?', {'amount': 'ASK'}),
    ('ask', '야', '얼마야?', {'amount': 'ASK'}),
    ('claim', '맞는가', V + '이 맞는가?', {'amount': V, 'claim': '맞는가'}),
    ('claim', '맞나요', V + '이 맞나요?', {'amount': V, 'claim': '맞나요'}),
    ('deny', '아니다', V + '이 아니다.', {'amount': V, 'denies': '아니'}),
    # more forms of the denying and the checking word (the `endings` set); 아닙니다 is cut inside a character
    ('deny', '아닙니다', V + '이 아닙니다.', {'amount': V, 'denies': '아니'}),
    ('deny', '아니야', V + '이 아니야.', {'amount': V, 'denies': '아니'}),
    ('deny', '아니에요', V + '이 아니에요.', {'amount': V, 'denies': '아니'}),
    ('claim', '맞아요', V + '이 맞아요?', {'amount': V, 'claim': '맞아요'}),
    ('claim', '맞죠', V + '이 맞죠?', {'amount': V, 'claim': '맞죠'}),
    ('claim', '맞습니까', V + '이 맞습니까?', {'amount': V, 'claim': '맞습니까'}),
]
# What the lesson sets show as a whole: (time?, modifier?, ending).
PLAIN = {'이다', '입니다', '이야', '인가', '인가요', '입니까', '야', '맞는가', '맞나요', '아니다',
         '아니야', '아니에요', '아닙니다', '맞아요', '맞죠', '맞습니까'}
TAUGHT = {(False, False, e) for e in PLAIN} | {(True, False, e) for e in ('이다', '인가')} \
    | {(False, True, e) for e in ('이다', '인가')}


def grid():
    for time in (False, True):
        for mod in (False, True):
            for form, ending, tail, extra in TAILS:
                text = (T + '에 ' if time else '') + S + '의 ' + (M + ' ' if mod else '') + PROP + '은 ' + tail
                roles = dict(extra, subject=S)
                if time:
                    roles['at'] = T
                if mod:
                    roles['when'] = M
                yield (time, mod, ending), form, text, [P.rel(PROP, **roles)]


def measure(model, show=True):
    tally = {'taught': [0, 0], 'combined': [0, 0]}
    for features, form, text, expected in grid():
        group = 'taught' if features in TAUGHT else 'combined'
        verdict, note = P.judge(model, text, expected)
        tally[group][0] += verdict == 'OK'
        tally[group][1] += 1
        if show:
            print('%-8s %-8s %s   %s' % (verdict, group, text, note[:70]))
    return tally


def main():
    names = ['wordings', 'endings', 'modifier', 'time', 'negation']
    model, _, n = P.build(*names)
    print('# %d lessons: the base set and %s, each feature taught on its own\n' % (n, ', '.join(names)))
    tally = measure(model)
    for group in ('taught', 'combined'):
        print('\n%-8s %d of %d read exactly as meant' % ((group,) + tuple(tally[group])))
    print('transfer = %d / %d' % tuple(tally['combined']))


if __name__ == '__main__':
    main()
