"""Run the 24 original tax questions after the held-question work, on both arms.

Not a fresh test. The wordings added to the lessons were chosen after seeing which of these
questions were held. The original trial files are read, never written.
"""
import json
import time
from pathlib import Path

from experiments.graph_weighted_acquisition import answer as A, reader as R

HERE = Path(__file__).resolve().parent
TRIAL = HERE.parent


def judge(question, result):
    wanted = [[b['value']] for b in question.get('expected_bindings', [])]
    gold = question['expected_behavior']['gold_status']
    if result['status'] != 'answered':
        return 'held as expected' if gold == 'hold' else 'held'
    if gold == 'reject_claim':
        ok = result['claim'] and not result['claim']['holds'] and result['answers'] == wanted
        return 'correct' if ok else 'wrong'
    if gold != 'answer':
        return 'answered where no plain answer was expected'
    return 'correct' if result['answers'] == wanted and not result['claim'] else 'wrong'


def main():
    lessons = json.loads((HERE / 'lessons.json').read_text(encoding='utf8'))
    context = json.loads((TRIAL / 'lessons_fix_20261119' / 'contexts.json').read_text(encoding='utf8'))[0]
    questions = json.loads((TRIAL / 'questions.json').read_text(encoding='utf8'))
    model = R.build(lessons)
    assert not model['skipped']
    rows, started = [], time.perf_counter()
    for q in questions:
        row = {'id': q['id'], 'tier': q['tier'], 'text': q['text']}
        for arm, run in (('graph', lambda: A.answer_graph(context['graph'], context['text'], q['text'], model)),
                         ('natural', lambda: A.answer(context['text'], q['text'], model))):
            t = time.perf_counter()
            result = run()
            row[arm] = {'verdict': judge(q, result), 'status': result['status'], 'answers': result['answers'],
                        'reason': result.get('reason'), 'executor': result.get('executor'),
                        'verified': result.get('verified'), 'partial': result.get('partial'),
                        'claim': result.get('claim'), 'seconds': round(time.perf_counter() - t, 4)}
            if arm == 'natural':
                row['report'] = A.explain(context['text'], q['text'], result)
        rows.append(row)
    total = time.perf_counter() - started
    (HERE / 'results.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf8')
    named = ['correct', 'held as expected', 'held', 'wrong']
    lines = ['# Tax questions after the held-question work', '',
             'Same 24 questions and 14 facts as the earlier runs, so this is not a fresh test. %d fictional lessons. '
             'The added wordings were chosen after seeing which questions were held.' % len(lessons), '',
             '| Tier | Arm | correct | held as expected | held | wrong | other |', '|---|---|---|---|---|---|---|']
    for tier in ('direct', 'paraphrase', 'boundary'):
        for arm in ('graph', 'natural'):
            verdicts = [r[arm]['verdict'] for r in rows if r['tier'] == tier]
            counts = [verdicts.count(x) for x in named] + [sum(1 for v in verdicts if v not in named)]
            lines.append('| %s | %s | %s |' % (tier, arm, ' | '.join(map(str, counts))))
    lines += ['', 'Total time for both arms on 24 questions: %.2f s. No timeouts.' % total, '',
              '| Id | Question | Natural-language arm | Trust | What the answer rests on |', '|---|---|---|---|---|']
    for r in rows:
        a = r['natural']
        shown = a['verdict'] + (': ' + ', '.join(x[0] for x in a['answers']) if a['answers'] else '')
        if a['claim']:
            shown += ' (claimed %s: %s)' % (a['claim']['claimed'], 'true' if a['claim']['holds'] else 'false')
        trust = '-' if a['status'] != 'answered' else 'verified' if a['verified'] else \
            'partial reading' if a['partial'] else 'not independently verified'
        lines.append('| %s | %s | %s | %s | %s |' % (r['id'], r['text'], shown, trust,
                                                     '; '.join(a['partial']) if a['partial'] else (a['reason'] or '')[:90]))
    (HERE / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    print('\n'.join(lines[4:12]))
    for r in rows[14:]:
        a = r['natural']
        print(r['id'], '|', a['verdict'], a['answers'], '|', a['claim'], '|', a['partial'] or a['reason'][:100])
    same = sum(r['graph']['verdict'] == r['natural']['verdict'] and r['graph']['answers'] == r['natural']['answers'] for r in rows)
    print('arms agree on', same, 'of', len(rows))


if __name__ == '__main__':
    main()
