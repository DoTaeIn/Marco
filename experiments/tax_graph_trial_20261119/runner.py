"""Frozen-input trial runner. Graph arm reads questions; end-to-end reads both texts."""
import argparse
import hashlib
import json
import os
import multiprocessing as mp
from pathlib import Path
import time
import traceback

from experiments.graph_example_acquisition import native
from experiments.graph_weighted_acquisition import answer as A, match as M, reader as R

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
INPUTS = ['lessons.json', 'contexts.json', 'questions.json', 'facts.json']
SOURCES = [BASE / 'runner.py', ROOT / 'relational_semantics.py'] + sorted((ROOT / 'experiments/graph_weighted_acquisition').glob('*.py')) + sorted((ROOT / 'experiments/graph_example_acquisition').glob('*.py')) + sorted((ROOT / 'experiments/graph_language_repair/questions').glob('*.py')) + sorted((ROOT / 'experiments/graph_language_repair/core').glob('*.py')) + sorted((ROOT / 'marco').rglob('*.py'))

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def read(name):
    return json.loads((BASE / name).read_text(encoding='utf8'))

def write_new(name, data):
    with (BASE / name).open('x', encoding='utf8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())

def hashes():
    return {str(p.relative_to(ROOT)): digest(p) for p in [*(BASE / x for x in INPUTS), *SOURCES]}

def freeze():
    lessons, contexts, questions = (read(x) for x in INPUTS[:3])
    ids = {c['id'] for c in contexts}
    assert len(ids) == len(contexts)
    assert len({q['id'] for q in questions}) == len(questions)
    for e in lessons:
        native._check(e['graph'], e['text'])
    for c in contexts:
        native._check(c['graph'], c['text'])
        assert c['sources'] and all(s.get('url') and s.get('as_of') and s.get('scope') for s in c['sources'])
    assert all(q['context_id'] in ids for q in questions)
    model = R.build(lessons)
    if model['skipped']:
        raise ValueError('skipped lessons: ' + repr(model['skipped']))
    write_new('model.json', model)
    write_new('manifest.json', {'sha256': hashes(), 'model_sha256': digest(BASE / 'model.json'),
                                'lesson_count': len(lessons), 'context_count': len(contexts), 'question_count': len(questions)})

def graph_answer(context, question, model):
    reading = R.read(question, model)
    result = {'question': reading, 'status': 'hold', 'answers': [], 'verified': False,
              'executor': 'not run', 'evidence': []}
    if reading['status'] != 'complete':
        result['reason'] = 'the question was not read with confidence: ' + reading['reason']
        return result
    graph = reading['graphs'][0]
    if not graph['project']:
        result['reason'] = 'the question does not ask for anything the reader recognises'
        return result
    found = M.match(context['graph'], context['text'], graph, question)
    result['match'] = found
    result['reason'] = found['reason']
    if found['status'] != 'answered':
        return result
    check = A._second_opinion(context['graph'], context['text'], graph, question, found['answers'])
    result.update(executor=check['state'], executor_detail=check['detail'], verified=check['state'] == 'agrees')
    spans = sorted({tuple(s) for proof in found['proofs'] for fact in proof['facts'] for s in fact['spans']})
    result['evidence'] = [{'span': list(s), 'text': context['text'][s[0]:s[1]]} for s in spans]
    if check['state'] in ('disagrees', 'refuses'):
        result.update(reason='the second answer method ' + check['state'] + ': ' + check['detail'], withheld=found['answers'])
    else:
        result.update(status='answered', answers=found['answers'])
    return result

def _worker(connection, arm, context, question, model):
    try:
        result = graph_answer(context, question, model) if arm == 'graph' else A.answer(context['text'], question, model)
    except Exception:
        result = {'status': 'error', 'answers': [], 'traceback': traceback.format_exc()}
    connection.send(result)
    connection.close()


def bounded_answer(arm, context, question, model):
    limit = 20 if arm == 'graph' else 10
    parent, child = mp.Pipe(duplex=False)
    process = mp.Process(target=_worker, args=(child, arm, context, question, model))
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
        result = {'status': 'timeout', 'answers': [], 'reason': f'first attempt exceeded {limit} seconds'}
    parent.close()
    return result


def run():
    manifest = read('manifest.json')
    if hashes() != manifest['sha256'] or digest(BASE / 'model.json') != manifest['model_sha256']:
        raise ValueError('Frozen input or source changed')
    contexts = {c['id']: c for c in read('contexts.json')}
    model = read('model.json')
    # Exclusive creation and per-record flush preserve the first attempt, including errors.
    with (BASE / 'first_results.jsonl').open('x', encoding='utf8') as f:
        for q in read('questions.json'):
            c = contexts[q['context_id']]
            for arm in ('graph', 'end_to_end'):
                start = time.perf_counter()
                result = bounded_answer(arm, c, q['text'], model)
                record = {'question_id': q['id'], 'question': q['text'], 'context_id': c['id'],
                          'context_text': c['text'], 'sources': c['sources'], 'arm': arm,
                          'elapsed_seconds': time.perf_counter() - start, 'manifest_sha256': digest(BASE / 'manifest.json'),
                          'model_sha256': manifest['model_sha256'], 'result': result}
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
                f.flush()
                os.fsync(f.fileno())

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['freeze', 'run'])
    args = parser.parse_args()
    {'freeze': freeze, 'run': run}[args.action]()
