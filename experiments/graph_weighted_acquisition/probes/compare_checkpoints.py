"""The same set of an examiner, run on the code of several checkpoints.

A change is worth what it adds on the same items; sets differ too much to compare one set's number
with another's. This runs today's runner (probes/blind_e2e.py) inside a clean copy of each named
commit, so every checkpoint answers with its own reader, lessons, recipe and matcher, and only the
runner is the same. Nothing in the working tree is touched; the copies are temporary git worktrees.

  PYTHONPATH=. python experiments/graph_weighted_acquisition/probes/compare_checkpoints.py <folder with C.json> [commit ...]

Without commits, the checkpoints of this work are used (see CHECKPOINTS), oldest first, then HEAD.
Each checkpoint's full output is kept in <folder>/by_checkpoint/. A checkpoint the runner cannot run
on is reported as such, with the reason, and is not left out.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RUNNER = 'experiments/graph_weighted_acquisition/probes/blind_e2e.py'
CHECKPOINTS = [
    ('ded9098', 'structured look-up, reader rules, lesson words make way'),
    ('728dd70', 'word kinds, open roles, assumed answers, shared subjects, chains'),
    ('05955b1', 'unread questions put to the knowledge, every piece accounted for'),
]
COLUMNS = [('right', 'answered right'), ('assumed right', 'assumed right'), ('WRONG', 'answered WRONG'),
           ('assumed WRONG', 'assumed WRONG'), ('proposed right, asks first', 'proposed right'),
           ('proposed otherwise, asks first', 'proposed otherwise'), ('held', 'held'),
           ('held (its knowledge was refused)', 'held, knowledge refused'), ('held ok', 'held, no answer exists')]


def git(*args, cwd=REPO):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, encoding='utf8')


def run_on(commit, folder, keep):
    """Run the runner inside a clean copy of the commit. Returns (short sha, subject, output text or None, note)."""
    found = git('rev-parse', '--short', commit)
    if found.returncode:
        return commit, '', None, 'no such commit'
    sha = found.stdout.strip()
    subject = git('log', '-1', '--format=%s', sha).stdout.strip()
    tree = Path(tempfile.mkdtemp(prefix='checkpoint_')) / sha
    added = git('worktree', 'add', '--detach', str(tree), sha)
    if added.returncode:
        return sha, subject, None, 'could not check out: ' + added.stderr.strip()[:200]
    try:
        shutil.copyfile(REPO / RUNNER, tree / RUNNER)          # today's runner, that checkpoint's everything else
        env = dict(os.environ, PYTHONPATH=str(tree), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        done = subprocess.run([sys.executable, str(tree / RUNNER), str(folder)], cwd=tree, env=env,
                              capture_output=True, text=True, encoding='utf8')
        text = done.stdout + ('\n# stderr\n' + done.stderr if done.stderr.strip() else '')
        (keep / ('%s.txt' % sha)).write_text(text, encoding='utf8')
        if done.returncode:
            last = [line for line in done.stderr.strip().split('\n') if line.strip()][-1:] or ['']
            return sha, subject, None, 'the runner does not run on this checkpoint: ' + last[0][:160]
        return sha, subject, text, ''
    finally:
        git('worktree', 'remove', '--force', str(tree))
        shutil.rmtree(tree.parent, ignore_errors=True)


def totals(text):
    """The 'all' line of each summary: [{verdict: count}] in the order the passes were made."""
    out = []
    for line in re.findall(r'^   all\s+(.*) of \d+$', text, flags=re.M):
        # A verdict's name may itself hold a comma ("proposed right, asks first 11"): a name ends at its count.
        out.append({name.strip(): int(count) for name, count in re.findall(r'(.+?) (\d+)(?:, |$)', line)})
    return out


def main():
    folder = Path(sys.argv[1]).resolve()
    commits = sys.argv[2:] or [c for c, _ in CHECKPOINTS] + ['HEAD']
    dirty = git('status', '--porcelain').stdout.strip()
    keep = folder / 'by_checkpoint'
    keep.mkdir(exist_ok=True)
    print('# One set, several checkpoints: %s' % folder.name)
    if dirty:
        print('NOTE: the working tree has changes that are in no commit; HEAD is the last commit, not the files on disk.')
    rows = []
    for commit in commits:
        sha, subject, text, note = run_on(commit, folder, keep)
        rows.append((sha, subject, totals(text) if text else None, note, text))
        print('ran %s  %s%s' % (sha, subject[:70], '   -- ' + note if note else ''))
    for n, title in ((0, 'As asked: no one answers the system back'), (1, 'A user answers each proposal with yes or no')):
        print('\n## ' + title)
        if n == 0:
            cols = COLUMNS
        else:
            cols = [c for c in COLUMNS if not c[0].startswith('proposed')] + [('right after a yes', 'right after a yes'),
                                                                               ('declined by the user', 'declined')]
        print('%-9s %s' % ('commit', '  '.join('%-*s' % (max(len(label), 4), label) for _, label in cols)))
        for sha, subject, passes, note, _ in rows:
            if passes is None or len(passes) <= n:
                print('%-9s %s' % (sha, note or 'this checkpoint has no such pass'))
                continue
            print('%-9s %s' % (sha, '  '.join('%-*d' % (max(len(label), 4), passes[n].get(key, 0)) for key, label in cols)))
    print('\nknowledge taken in:')
    for sha, subject, passes, note, text in rows:
        taken = re.search(r'^taken (\d+ of \d+)', text or '', flags=re.M)
        print('%-9s %s' % (sha, taken.group(1) if taken else note))
    print('\nFull outputs: %s' % keep)


if __name__ == '__main__':
    main()
