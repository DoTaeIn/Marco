"""Where the look-up of an unread question gave up, question by question.

    PYTHONPATH=. python experiments/graph_weighted_acquisition/probes/why_held.py <the arguments of blind_e2e.py>

The runner is run as it is, with its environment (MARCO_ASKED and the rest), and nothing of the
code is changed. While it runs, every return of `answer._anchor` that gives nothing is noted with
its line. Printed for each such question: the line, the source around it, the question. A question
that is not listed either was read, or `_anchor` gave a result for it (a proposal, candidates, an
assumed answer, a hold with a reason of its own).

Under each question: what the look-up had made of it by then (the thing, property words, what the
value is counted in, circumstances, properties worked out in order, what the thing has).

This tells where, not why it is right to stop there: it is a way to turn a guess about a held
question into a fact, on a set that was already run.
"""
import contextlib
import io
import runpy
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    from experiments.graph_weighted_acquisition import answer as A
    code, stopped, notes = A._anchor.__code__, {}, {}

    def tracer(frame, event, arg):
        if frame.f_code is not code:
            return None

        def local(frame, event, arg):
            if event == 'return' and arg is None:
                seen = frame.f_locals
                stopped[seen.get('question')] = frame.f_lineno
                # What the look-up had made of the question when it gave up.
                notes[seen.get('question')] = {
                    'thing': sorted(seen.get('named') or []),
                    'property words': list(seen.get('wanted') or []),
                    'counted in': sorted(seen.get('units') or []),
                    'circumstance': sorted(seen.get('said') or []),
                    'value stated': list(seen.get('stated') or []),
                    'worked out, in order': [row['property'] for row in (seen.get('worked') or [])][:4],
                    'said no before': sorted(seen.get('no') or []),
                    'the thing has': sorted({f['property'] for f in (seen.get('facts') or []) if f['thing'] in (seen.get('named') or [])}),
                }
            return local
        return local

    sys.argv = [str(HERE / 'blind_e2e.py')] + sys.argv[1:]
    sys.settrace(tracer)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(sys.argv[0], run_name='__main__')
    finally:
        sys.settrace(None)
    source = Path(A.__file__).read_text(encoding='utf8').splitlines()

    def around(line):
        # The condition that led to the return: the nearest line above that is not a comment.
        above = next(source[k].strip() for k in range(line - 2, 0, -1) if source[k].strip() and not source[k].strip().startswith('#'))
        return above[:110]

    print('where the look-up gave up (line of answer.py, the condition above it, how many questions)')
    for line, n in Counter(stopped.values()).most_common():
        print('  %4d  %-110s  %d' % (line, around(line), n))
    print()
    for question, line in stopped.items():
        print('%4d  %s' % (line, question))
        print('      %s' % '; '.join('%s: %s' % (k, ', '.join(map(str, v))) for k, v in notes[question].items() if v))


if __name__ == '__main__':
    main()
