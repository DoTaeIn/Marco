"""Frozen same-question regression. Preserve every first return; no retries."""
import concurrent.futures
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time
import traceback

from experiments.tax_graph_trial_20261119 import runner as original
from experiments.graph_weighted_acquisition import answer as A, reader as R

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = original.ROOT
PREVIOUS = BASE / 'rerun_after_sentence_fix_20261119'
VARIANTS = ROOT / 'experiments/graph_weighted_acquisition/data/connector_variants_ko.json'
EXPANDED = BASE / 'helds_fix_20261119/lessons.json'
CONFIGS = ('frozen44', 'variants44', 'expanded132')


def read(p):
    return json.loads(p.read_text(encoding='utf8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    with p.open('x', encoding='utf8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())


def input_paths():
    previous = read(PREVIOUS / 'manifest.json')
    paths = [BASE / k for k in previous['inputs']]
    paths += [PREVIOUS / k for k in ('manifest.json', 'first_results.jsonl', 'postcheck.json', 'REPORT.md')]
    return paths + [VARIANTS, EXPANDED]


def hashes(paths):
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def freeze():
    assert sha(BASE / 'model.json') == 'b4a9cdeaf3fb67af41e4386480c25b490101db1f71e47e67ea73388fed0a2fda'
    assert sha(PREVIOUS / 'first_results.jsonl') == '561dcb87d0f6aee490c5c423ec628d911a2df03e7f47786d37715b57be29579c'
    previous = read(PREVIOUS / 'manifest.json')
    assert all(sha(BASE / k) == v for k, v in previous['inputs'].items())
    lessons = read(BASE / 'lessons.json')
    expanded = read(EXPANDED)
    assert len(lessons) == 44 and len(expanded) == 132
    contexts = read(BASE / 'contexts.json')
    qs = read(BASE / 'questions.json') + read(BASE / 'supplemental_questions.json')
    assert len(contexts) == 1 and len(qs) == 28 and all(q['context_id'] == 'tax-all' for q in qs)
    before = hashes(input_paths())
    (HERE / 'models').mkdir()
    shutil.copyfile(BASE / 'model.json', HERE / 'models/frozen44.json')
    for name, examples, variants in [('variants44', lessons, read(VARIANTS)), ('expanded132', expanded, None)]:
        model = R.build(examples, variants=variants)
        assert not model['skipped']
        save(HERE / 'models' / (name + '.json'), model)
    assert before == hashes(input_paths())
    sources = hashes(original.SOURCES)
    for name in sources:
        dest = HERE / 'source_snapshot' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    save(HERE / 'manifest.json', {
        'inputs': before, 'sources': sources,
        'models': {c: sha(HERE / 'models' / (c + '.json')) for c in CONFIGS},
        'runner_sha256': sha(HERE / 'run.py'), 'workers': 2,
        'timeouts': {'graph': 20, 'end_to_end': 10}, 'calls': 156,
        'method': 'Current A.answer_graph for graph arm, A.answer for end_to_end; no memory teaching. '
                  'Original question texts and ORIGINAL context bytes in every configuration. '
                  'expanded132 lessons authored after prior failures; not fresh generalization.'})


def check(m):
    return (hashes(input_paths()) == m['inputs'] and hashes(original.SOURCES) == m['sources']
            and sha(HERE / 'run.py') == m['runner_sha256']
            and all(sha(HERE / 'models' / (c + '.json')) == h for c, h in m['models'].items())
            and all(sha(HERE / 'source_snapshot' / p) == h for p, h in m['sources'].items()))


def worker(connection, arm, context, question, model):
    try:
        result = (A.answer_graph(context['graph'], context['text'], question, model)
                  if arm == 'graph' else A.answer(context['text'], question, model))
    except Exception:
        result = {'status': 'error', 'answers': [], 'traceback': traceback.format_exc()}
    connection.send(result)
    connection.close()


def bounded(arm, context, question, model, limit):
    parent, child = mp.Pipe(duplex=False)
    process = mp.Process(target=worker, args=(child, arm, context, question, model))
    process.start()
    child.close()
    if parent.poll(limit):
        try:
            result = parent.recv()
        except EOFError:
            result = {'status': 'error', 'answers': [], 'reason': 'worker exited without a result'}
        process.join()
    else:
        process.terminate()
        process.join()
        result = {'status': 'timeout', 'answers': [], 'reason': 'first attempt exceeded %d seconds' % limit}
    parent.close()
    return result


def capture():
    m = read(HERE / 'manifest.json')
    assert check(m), 'Frozen source or input changed'
    models = {c: read(HERE / 'models' / (c + '.json')) for c in CONFIGS}
    context = read(BASE / 'contexts.json')[0]
    qs = [(q, a, 'main') for q in read(BASE / 'questions.json') for a in ('graph', 'end_to_end')]
    qs += [(q, 'graph', 'supplemental') for q in read(BASE / 'supplemental_questions.json')]
    jobs = [(c, q, a, g) for c in CONFIGS for q, a, g in qs]

    def call(job):
        config, q, arm, group = job
        start = time.perf_counter()
        try:
            result = bounded(arm, context, q['text'], models[config], m['timeouts'][arm])
        except Exception:
            result = {'status': 'error', 'answers': [], 'traceback': traceback.format_exc()}
        return {'config': config, 'question_id': q['id'], 'question': q['text'], 'group': group,
                'arm': arm, 'context_id': context['id'], 'context_text': context['text'],
                'sources': context['sources'], 'elapsed_seconds': time.perf_counter() - start,
                'model_sha256': m['models'][config], 'manifest_sha256': sha(HERE / 'manifest.json'),
                'result': result}

    with (HERE / 'first_results.jsonl').open('x', encoding='utf8') as f:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for row in pool.map(call, jobs):
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
                f.flush()
                os.fsync(f.fileno())
    save(HERE / 'postcheck.json', {'inputs_models_and_sources_unchanged': check(m),
                                 'results_sha256': sha(HERE / 'first_results.jsonl')})


if __name__ == '__main__':
    import sys
    {'freeze': freeze, 'run': capture}[sys.argv[1]]()
