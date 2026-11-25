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
            if hasattr(L, 'note_kinds'):                 # an older checkpoint does not keep word kinds
                L.note_kinds(memory, got, item['text'])
        else:
            refused.append(item['id'])
        print('%-8s %s %s%s' % ('TAKEN' if ok else 'REFUSED', item['id'], item['text'], '' if ok else '   -- ' + why[:110]))
    print('taken %d of %d. Word kinds the taken sentences showed: %s'
          % (len(taken), len(knowledge), ', '.join('%s=%s' % (k['word'], k['kind']) for k in memory.get('kinds', [])) or 'none'))
    return taken, set(refused), memory


def verdict(result, item, refused):
    if result.get('proposal'):
        # Not an answer: the system says what it took the question to ask and waits for a yes.
        claim = result['proposal'].get('claim')
        if item['kind'] == 'check':
            good = claim is not None and claim['holds'] == item['claim']
        else:
            good = item['expect'] is not None and claim is None and result['proposal']['if_confirmed'] == item['expect']
        return 'proposed right, asks first' if good else 'proposed otherwise, asks first'
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
            if 'understood' in a:
                u = a['understood']
                text += '   [not read as a sentence; taken to ask for the %s of "%s"%s; chosen by %s; not read: %s]' % (
                    u['property'], u['thing'], ''.join(' %s=%s' % kv for kv in sorted(u['with'].items())), a['chosen_by'],
                    ', '.join(a['unread']) or 'nothing')
            elif 'readings' in a:
                text += '   [the reader could not choose between %d readings; the knowledge answered one way only]' % len(a['readings'])
            else:
                text += '   [assumed: "%s" read as the %s of "%s"]' % (a['word'], a['role'], a['head'])
        return text
    text = '-- ' + result['reason'][:150]
    if result.get('proposal'):
        text = '-- asks: %s   [would then answer %s]' % (result['proposal']['ask'], result['proposal']['if_confirmed'])
    for x in result.get('open_roles', []) + result.get('attachment', []):
        text += '   [asks: %s]' % x['ask']
    for c in result.get('candidates', []):
        text += '   [could be: %s of %s]' % (c['property'], c['thing'])
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
    # A property word or a name may come with other words for it ({"word": ..., "also": [...]}), or as a plain string.
    props = [x if isinstance(x, dict) else {'word': x, 'also': []} for x in data['properties']]
    names = [x if isinstance(x, dict) else {'name': x, 'also': []} for x in data['names']]
    # With a second argument, the taught basic words (packs/basic_words_ko.tsv) and the plain-words
    # explanation the examiner gave each property are used. Without it the run is as it always was.
    basic = None
    if len(sys.argv) > 2:
        from experiments.graph_weighted_acquisition import basic as B
        basic = B.load(*sys.argv[2:4])                  # the words, and how they change their shape
        for path in sys.argv[2:4]:
            print('  %s  %s (taught)' % (hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16], Path(path).name))
    words = {'schema': PK.WORDS, 'field': data['domain'], 'slot': BT.SLOT,
             'properties': [dict({'word': x['word'], 'means': x['word'], 'also': list(x.get('also', []))},
                                 **({'explained': x['explained']} if basic and x.get('explained') else {})) for x in props],
             'names': [{'name': x['name'], 'also': list(x.get('also', []))} for x in names]}
    aliases = {other: x['name'] for x in names for other in x.get('also', [])}
    clashes = [x['word'] for x in props if x['word'] in full['tables'].get('closed', {})]
    if clashes:
        print('FIELD WORDS REFUSED BY THE PACK LOADER (fixed words of the language): %s' % ', '.join(clashes))
        words['properties'] = [x for x in words['properties'] if x['word'] not in clashes]
    try:
        model = PK.with_words(full, words, basic) if basic else PK.with_words(full, words)
        if basic:
            print('Explanations taken: %d of %d properties. Words of them no lesson knows: %s' % (
                len(model['field_explained']), len(props),
                '; '.join('%s: %s' % (u['property'], ', '.join(u['words'])) for u in model['field_unexplained']) or 'none'))
    except ValueError as error:
        # An older checkpoint refuses a field word that is also a word of its lessons. Said, and the word left out.
        print('THE PACK LOADER OF THIS CHECKPOINT REFUSED THE WORD PACK: %s' % error)
        refused_words = [x['word'] for x in words['properties'] if x['word'] in full['tables'].get('head', {})]
        words['properties'] = [x for x in words['properties'] if x['word'] not in refused_words]
        model = PK.with_words(full, words)
    print('\nField "%s": %d property words, %d names, %d sentences of knowledge, %d questions. Language pack: %d lessons.'
          % (data['domain'], len(props), len(names), len(data['knowledge']), len(data['questions']), n))
    taken, refused, memory = take_in(model, data['knowledge'])
    passage = ' '.join(item['text'] for item in taken)
    read = R.read(passage, model) if passage else None
    if not read or read['status'] != 'complete':
        print('THE TAKEN SENTENCES COULD NOT BE READ TOGETHER: %s' % (read or {}).get('reason'))
    def ask_all(title, feedback, verbose):
        """One pass over the questions. With `feedback` a user answers each proposal: yes when it is what
        was asked (the wording is then kept, see answer.confirm), no otherwise. That user is played with
        the examiner's answers, so this pass is not blind to them; it shows what use would teach."""
        print('\n# ' + title)
        memory_q = L.new_memory()
        memory_q['kinds'] = [dict(k) for k in memory.get('kinds', [])]
        tally = {}
        for item in data['questions']:
            try:
                result = A.answer_graph(read['graphs'][0], passage, item['text'], model, read, memory_q, aliases=aliases) \
                    if read and read['status'] == 'complete' else A.answer(passage, item['text'], model, memory_q)
                v, text = verdict(result, item, refused), shown(result)
                if feedback and result.get('proposal'):
                    if v.startswith('proposed right'):
                        if hasattr(A, 'confirm'):
                            A.confirm(result, memory_q, 'the user', 'this run')
                        v = 'right after a yes'
                    else:
                        v = 'declined by the user'
            except Exception as error:
                v, text = 'ERROR', repr(error)
            tally.setdefault(item['kind'], {}).setdefault(v, 0)
            tally[item['kind']][v] += 1
            if verbose:
                expect = '(no answer)' if item['expect'] is None else \
                    ('%s: %s' % ('yes' if item['claim'] else 'no', item['expect']) if item['kind'] == 'check' else item['expect'])
                print('\n%s %s [%s]\n  Q: %s\n  expected: %s\n  got:      %s' % (
                    v.upper() if v.endswith('WRONG') else v, item['id'], item['kind'], item['text'], expect, text))
        print('\n## Summary: ' + title)
        total = {}
        for kind in sorted(tally):
            print('   %-12s %s of %d' % (kind, ', '.join('%s %d' % kv for kv in sorted(tally[kind].items())), sum(tally[kind].values())))
            for k, v in tally[kind].items():
                total[k] = total.get(k, 0) + v
        print('   %-12s %s of %d' % ('all', ', '.join('%s %d' % kv for kv in sorted(total.items())), sum(total.values())))

    ask_all('2. Questions and answers, as asked (no one answers the system back)', False, True)
    ask_all('3. The same questions in the same order, a user answering each proposal with yes or no', True, False)


if __name__ == '__main__':
    main()
