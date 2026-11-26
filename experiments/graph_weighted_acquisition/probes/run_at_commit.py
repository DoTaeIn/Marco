"""한 체크포인트의 깨끗한 사본에서 묶음을 돌려 출력을 파일로 남긴다. 사본은 git worktree라 그 커밋의 코드만 쓴다.
인자: 저장소, 작업 목록 json [{commit, set, args, env, out, patch}]"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
REPO = Path(sys.argv[1]).resolve()
JOBS = json.loads(Path(sys.argv[2]).read_text(encoding='utf8'))
E = 'experiments/graph_weighted_acquisition'
RUNNER = E + '/probes/blind_e2e.py'
ANCHOR_OLD = "            return None\n    said = {(aliases or {}).get(c, c) for _, c in found['circumstance']}"
ANCHOR_NEW = ("            if not basic:\n                return None\n            wanted, weak = [], False\n"
              "    said = {(aliases or {}).get(c, c) for _, c in found['circumstance']}")
trees = {}
try:
    for job in JOBS:
        key = (job['commit'], job.get('patch'))
        if key not in trees:
            tree = Path(tempfile.mkdtemp(prefix='at_')) / job['commit']
            added = subprocess.run(['git', 'worktree', 'add', '--detach', str(tree), job['commit']], cwd=REPO,
                                   capture_output=True, text=True)
            assert not added.returncode, added.stderr
            shutil.copyfile(REPO / RUNNER, tree / RUNNER)
            if job.get('patch') == 'anchor':
                p = tree / E / 'answer.py'
                s = p.read_text(encoding='utf8')
                assert s.count(ANCHOR_OLD) == 1
                p.write_text(s.replace(ANCHOR_OLD, ANCHOR_NEW), encoding='utf8', newline='\n')
            if job.get('patch') == 'no_anchor':
                p = tree / E / 'answer.py'
                s = p.read_text(encoding='utf8')
                old = "            if not basic:\n                return None\n            wanted, weak = [], False"
                assert s.count(old) == 1
                p.write_text(s.replace(old, "            return None"), encoding='utf8', newline='\n')
            trees[key] = tree
        tree = trees[key]
        env = dict(os.environ, PYTHONPATH=str(tree), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', KG_ENCODER='문자',
                   **job.get('env', {}))
        done = subprocess.run([sys.executable, str(tree / RUNNER), str(REPO / E / 'probes' / job['set'])] + job.get('args', []),
                              cwd=tree, env=env, capture_output=True, text=True, encoding='utf8')
        where = subprocess.run([sys.executable, '-c', 'import experiments.graph_weighted_acquisition.answer as A; print(A.__file__)'],
                               cwd=tree, env=env, capture_output=True, text=True, encoding='utf8').stdout.strip()
        assert str(tree) in where, where
        out = REPO / E / 'probes' / job['set'] / 'by_configuration' / job['out']
        out.parent.mkdir(exist_ok=True)
        out.write_text(done.stdout + ('\n# stderr\n' + done.stderr if done.stderr.strip() else ''), encoding='utf8')
        line = next((l for l in done.stdout.splitlines() if l.startswith('   all ')), 'NO SUMMARY')
        print(job['commit'], job.get('patch') or '', job['set'], job['out'], '|', line.strip(), flush=True)
finally:
    for tree in trees.values():
        subprocess.run(['git', 'worktree', 'remove', '--force', str(tree)], cwd=REPO, capture_output=True)
        shutil.rmtree(tree.parent, ignore_errors=True)
