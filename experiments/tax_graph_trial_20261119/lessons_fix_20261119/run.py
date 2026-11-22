"""Run the 24 original tax questions with the corrected lessons, on both arms.

Not a fresh test: the questions are the same ones already seen in the first two runs.
The original trial files are read, never written.
"""
import json
import time
from pathlib import Path

from experiments.graph_weighted_acquisition import answer as A, reader as R
from experiments.tax_graph_trial_20261119 import runner as T

HERE = Path(__file__).resolve().parent
TRIAL = HERE.parent


def judge(question, result):
    wanted = [[b['value']] for b in question.get('expected_bindings', [])]
    gold = question['expected_behavior']['gold_status']
    if result['status'] != 'answered':
        return 'held as expected' if gold == 'hold' else 'held'
    if gold != 'answer':
        return 'answered where no plain answer was expected'
    return 'correct' if result['answers'] == wanted else 'wrong'


def main():
    lessons = json.loads((HERE / 'lessons.json').read_text(encoding='utf8'))
    context = json.loads((HERE / 'contexts.json').read_text(encoding='utf8'))[0]
    questions = json.loads((TRIAL / 'questions.json').read_text(encoding='utf8'))
    model = R.build(lessons)
    assert not model['skipped']
    rows, started = [], time.perf_counter()
    for q in questions:
        row = {'id': q['id'], 'tier': q['tier'], 'text': q['text']}
        for arm, run in (('graph', lambda: T.graph_answer(context, q['text'], model)),
                         ('natural', lambda: A.answer(context['text'], q['text'], model))):
            t = time.perf_counter()
            result = run()
            row[arm] = {'verdict': judge(q, result), 'status': result['status'], 'answers': result['answers'],
                        'reason': result.get('reason'), 'executor': result.get('executor'),
                        'verified': result.get('verified'), 'seconds': round(time.perf_counter() - t, 4)}
        rows.append(row)
    total = time.perf_counter() - started
    (HERE / 'results.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf8')
    lines = ['# Tax questions with corrected lessons', '',
             'Same 24 questions and 14 facts as the first two runs, so this is not a fresh test. Changes: '
             '%d fictional lessons with the right 은/는, varied subject lengths and plain and polite endings; '
             'the context text uses 는 where it wrongly had 은 (4 characters). Model built from the lessons only.'
             % len(lessons), '',
             '| Tier | Arm | ' + ' | '.join(['correct', 'held as expected', 'held', 'wrong', 'other']) + ' |',
             '|---|---|---|---|---|---|---|']
    for tier in ('direct', 'paraphrase', 'boundary'):
        for arm in ('graph', 'natural'):
            verdicts = [r[arm]['verdict'] for r in rows if r['tier'] == tier]
            named = ['correct', 'held as expected', 'held', 'wrong']
            counts = [verdicts.count(n) for n in named] + [sum(1 for v in verdicts if v not in named)]
            lines.append('| %s | %s | %s |' % (tier, arm, ' | '.join(map(str, counts))))
    lines += ['', 'Total time for both arms on 24 questions: %.2f s. No timeouts.' % total, '',
              '| Id | Question | Graph arm | Natural-language arm |', '|---|---|---|---|']
    for r in rows:
        cell = lambda a: '%s%s%s' % (r[a]['verdict'], ': ' + ', '.join(x[0] for x in r[a]['answers']) if r[a]['answers'] else '',
                                     '' if r[a]['status'] != 'answered' else ' (executor %s)' % r[a]['executor'])
        lines.append('| %s | %s | %s | %s |' % (r['id'], r['text'], cell('graph'), cell('natural')))
    (HERE / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    print('\n'.join(lines[4:12]))
    for r in rows:
        if r['graph']['status'] != 'answered':
            print(r['id'], '|', r['graph']['reason'][:95], '||', r['natural']['reason'][:60])


if __name__ == '__main__':
    main()
