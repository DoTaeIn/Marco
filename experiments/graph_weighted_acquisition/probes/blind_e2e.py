"""Blind test from knowledge to answer, 2026-11-24.

One author who saw neither the lessons nor the code invents a field, writes what is known about it
as Korean sentences, and writes questions with the answers a person would expect. This runner was
written and frozen before the items existed; it is run once and nothing is changed afterwards.

  1. Knowledge is taken in sentence by sentence. A sentence is taken only if it is read completely,
     with no word passed over; the others are refused out loud and are not knowledge.
  2. What the taken sentences showed about the kind of their words is kept (learn.note_kinds).
  3. Every question is asked against the taken sentences. Statuses are counted apart: answered,
     assumed (an answer under a stated assumption), held.

A question whose knowledge was refused in step 1 cannot be answered; it is counted on its own line.
The author is not the owner's independent examiner; this is a blind development test.

Run from the repository root:
  PYTHONPATH=. python experiments/graph_weighted_acquisition/probes/blind_e2e.py <folder with C.json>
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from experiments.graph_weighted_acquisition import answer as A
from experiments.graph_weighted_acquisition import learn as L

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('blind_test', HERE / 'blind_test.py')
BT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BT)
R, PK = BT.R, BT.PK


def take_in(model, knowledge):
    taken, refused, memory = [], [], L.new_memory()
    print('\n# 1. Knowledge taken in, sentence by sentence')
    for item in knowledge:
        try:
            got = R.read(item['text'], model)
            ok = got['status'] == 'complete' and not got.get('ignored')
            why = '' if ok else ('words passed over: %s' % got['ignored'] if got['status'] == 'complete' else got['reason'])
        except Exception as error:
            got, ok, why = None, False, repr(error)
        if ok:
            taken.append(item)
            L.note_kinds(memory, got, item['text'])
        else:
            refused.append(item['id'])
        print('%-8s %s %s%s' % ('TAKEN' if ok else 'REFUSED', item['id'], item['text'], '' if ok else '   -- ' + why[:110]))
    print('taken %d of %d. Word kinds the taken sentences showed: %s'
          % (len(taken), len(knowledge), ', '.join('%s=%s' % (k['word'], k['kind']) for k in memory['kinds']) or 'none'))
    return taken, set(refused), memory


def verdict(result, item, refused):
    if result['status'] not in ('answered', 'assumed'):
        if item['expect'] is None:
            return 'held ok'
        return 'held (its knowledge was refused)' if set(item.get('needs', [])) & refused else 'held'
    tag = 'assumed ' if result['status'] == 'assumed' else ''
    if item['expect'] is None:
        return tag + 'WRONG'
    if item['kind'] == 'check':
        return tag + ('right' if result.get('claim') is not None and result['claim']['holds'] == item['claim'] else 'WRONG')
    return tag + ('right' if result.get('claim') is None and result['answers'] == [[item['expect']]] else 'WRONG')


def shown(result):
    if result['status'] in ('answered', 'assumed'):
        said = [s['text'] for s in result.get('sentences', []) if s['status'] == 'said']
        text = (('맞다: ' if result['claim']['holds'] else '아니다: ') if result.get('claim') else '') \
            + '; '.join(', '.join(row) for row in result['answers']) + (('   (as a sentence: %s)' % said[0]) if said else '')
        for a in result.get('assumed', []):
            text += '   [assumed: "%s" read as the %s of "%s"]' % (a['word'], a['role'], a['head'])
        return text
    text = '-- ' + result['reason'][:150]
    for x in result.get('open_roles', []) + result.get('attachment', []):
        text += '   [asks: %s]' % x['ask']
    return text


def main():
    folder = Path(sys.argv[1])
    print('# Frozen before the items existed')
    for name, digest in BT.frozen().items():
        print('  %s  %s' % (digest, name))
    print('  %s  probes/blind_e2e.py' % hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16])
    print('  %s  C.json (the items)' % hashlib.sha256((folder / 'C.json').read_bytes()).hexdigest()[:16])
    data = json.loads((folder / 'C.json').read_text(encoding='utf8'))
    full, n = BT.language(BT.SETS)
    words = {'schema': PK.WORDS, 'field': data['domain'], 'slot': BT.SLOT,
             'properties': [{'word': w, 'means': w, 'also': []} for w in data['properties']],
             'names': [{'name': w, 'also': []} for w in data['names']]}
    clashes = [w for w in data['properties'] if w in full['tables'].get('closed', {})]
    if clashes:
        print('FIELD WORDS REFUSED BY THE PACK LOADER (fixed words of the language): %s' % ', '.join(clashes))
        words['properties'] = [x for x in words['properties'] if x['word'] not in clashes]
    model = PK.with_words(full, words)
    print('\nField "%s": %d property words, %d names, %d sentences of knowledge, %d questions. Language pack: %d lessons.'
          % (data['domain'], len(data['properties']), len(data['names']), len(data['knowledge']), len(data['questions']), n))
    taken, refused, memory = take_in(model, data['knowledge'])
    passage = ' '.join(item['text'] for item in taken)
    print('\n# 2. Questions and answers')
    tally = {}
    for item in data['questions']:
        try:
            result = A.answer(passage, item['text'], model, memory)
            v, text = verdict(result, item, refused), shown(result)
        except Exception as error:
            v, text = 'ERROR', repr(error)
        tally.setdefault(item['kind'], {}).setdefault(v, 0)
        tally[item['kind']][v] += 1
        expect = '(no answer)' if item['expect'] is None else \
            ('%s: %s' % ('yes' if item['claim'] else 'no', item['expect']) if item['kind'] == 'check' else item['expect'])
        print('\n%s %s [%s]\n  Q: %s\n  expected: %s\n  got:      %s' % (v.upper() if v.endswith('WRONG') else v, item['id'], item['kind'],
                                                                      item['text'], expect, text))
    print('\n# Summary')
    total = {}
    for kind in sorted(tally):
        print('   %-12s %s of %d' % (kind, ', '.join('%s %d' % kv for kv in sorted(tally[kind].items())), sum(tally[kind].values())))
        for k, v in tally[kind].items():
            total[k] = total.get(k, 0) + v
    print('   %-12s %s of %d' % ('all', ', '.join('%s %d' % kv for kv in sorted(total.items())), sum(total.values())))


if __name__ == '__main__':
    main()
