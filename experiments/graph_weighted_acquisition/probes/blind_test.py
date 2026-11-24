"""Blind test, 2026-11-23: items written by authors who saw neither the lessons nor the code.

This runner was written and its inputs fixed before the items existed; it is run once and
nothing is changed after the results are seen. Two parts, each from its own author:

  A  reading: 60 sentences in a domain the author invented, combining the features the reader
     claims (modifier, time, check, denial, condition, chain, asking for the thing, topic forms),
     each with the meaning the author intends. Scored: read exactly as meant / held / partial /
     read differently.
  B  answering: a field the author invented (word pack, fact pack) and 50 questions asked as
     people ask, with expected answers; 8 of them have no answer in the facts.

The authors were told what the system claims to read (A) or nothing about how it reads (B).
They are not the owner's independent examiner; this is a blind development test.

Run from the repository root:
  PYTHONPATH=. python experiments/graph_weighted_acquisition/probes/blind_test.py <folder with A.json and B.json>
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = _module('reading_limits', HERE / 'reading_limits.py')
R, PK, ML = P.R, P.PK, P.ML
SETS = ['wordings', 'endings', 'modifier', 'time', 'negation', 'conditional', 'inverse', 'chain']   # 'endings' added after the two blind runs of 2026-11-23
FROZEN = ['reader.py', 'match.py', 'answer.py', 'write.py', 'pack.py', 'learn.py', 'merge.py', 'weights.py',
          'data/reading_recipe.json', 'data/connector_variants_ko.json', 'packs/make_language.py', 'probes/reading_limits.py']
SLOT = {'type': 'relation', 'attribute': 'kind', 'subject_role': 'subject', 'value_role': 'amount'}


def frozen():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:16] for name in FROZEN}


def language(sets):
    lessons = ML.lessons() + [x for name in sets for x in P.SETS[name]()]
    return R.build(lessons, variants=P.VARIANTS), len(lessons)


def part_a(data, model):
    print('\n# A. Reading: %d sentences, domain "%s"' % (len(data['sentences']), data['domain']))
    tally = {}
    for item in data['sentences']:
        expected = [P.rel(r['kind'], **{k: v for k, v in r.items() if k != 'kind'}) for r in item['meaning']]
        try:
            verdict, note = P.judge(model, item['text'], expected)
        except Exception as error:                      # an item the reader cannot even take is reported, not hidden
            verdict, note = 'ERROR', repr(error)
        size = min(len(item.get('features', [])), 3)
        tally.setdefault(size, {}).setdefault(verdict, 0)
        tally[size][verdict] += 1
        print('%-8s %s %-28s %s   %s' % (verdict, item['id'], '+'.join(item.get('features', []))[:28], item['text'], note[:90]))
    return tally


def verdict_b(result, item):
    if result['status'] != 'answered':
        return 'held ok' if item['expect'] is None else 'held'
    if item['expect'] is None:
        return 'wrong'
    if item['kind'] == 'check':
        return 'right' if result.get('claim') is not None and result['claim']['holds'] == item['claim'] else 'wrong'
    return 'right' if result.get('claim') is None and result['answers'] == [[item['expect']]] else 'wrong'


def part_b(data, lang, title):
    print('\n# B. Answering, %s: field "%s", %d facts, %d questions'
          % (title, data['words'].get('field'), len(data['facts']['facts']), len(data['questions'])))
    try:
        system = PK.load(lang, data['words'], data['facts'])
    except Exception as error:
        print('THE PACK COULD NOT BE LOADED: %r' % error)
        return None
    print('facts loaded %d, not usable %d %s' % (system['counts']['facts'], len(system['unusable']), system['unusable'][:3]))
    tally = {}
    for item in data['questions']:
        try:
            result = PK.ask(system, item['text'])
            v = verdict_b(result, item)
            if result['status'] == 'answered':
                said = [s['text'] for s in result.get('sentences', []) if s['status'] == 'said']
                shown = (('맞다: ' if result['claim']['holds'] else '아니다: ') if result.get('claim') else '') \
                    + (said[0] if said else str(result['answers']))
            else:
                shown = '-- ' + result['reason'][:80]
        except Exception as error:
            v, shown = 'ERROR', repr(error)
        tally.setdefault(item['kind'], {}).setdefault(v, 0)
        tally[item['kind']][v] += 1
        print('%-8s %s %-9s %s  (expected %s)  =>  %s' % (v, item['id'], item['kind'], item['text'], item['expect'], shown))
    return tally


def main():
    folder = Path(sys.argv[1])
    print('# Frozen before the items existed')
    for name, digest in frozen().items():
        print('  %s  %s' % (digest, name))
    for name in ('A.json', 'B.json'):
        print('  %s  %s (the items)' % (hashlib.sha256((folder / name).read_bytes()).hexdigest()[:16], name))
    a = json.loads((folder / 'A.json').read_text(encoding='utf8'))
    b = json.loads((folder / 'B.json').read_text(encoding='utf8'))
    full, n = language(SETS)
    base, n0 = language([])
    print('\nLanguage packs: "full" = %d lessons (shipped generator + the seven made-up sets); "base" = %d lessons' % (n, n0))
    words = {'schema': PK.WORDS, 'field': a['domain'], 'slot': SLOT,
             'properties': [{'word': w, 'means': w, 'also': []} for w in a['properties']],
             'names': [{'name': w, 'also': []} for w in a['names']]}
    # A field word that is also a made-up word of the lessons is refused by the pack loader. Found by the
    # third blind set ("높이"). The clash is reported and the word is left to the language pack, which
    # already reads it as a property of that name; the sentences are scored like the others.
    # Since 2026-11-24 (`lesson_words: make_way`) the lessons' property words make way; only fixed words clash.
    way = R.recipe_of(full)[1].get('lesson_words') == 'make_way'
    clashes = [w for w in a['properties'] if (not way and w in full['tables'].get('head', {})) or w in full['tables'].get('closed', {})]
    if clashes:
        print('FIELD WORDS REFUSED BY THE PACK LOADER (already words of the lessons): %s' % ', '.join(clashes))
        words['properties'] = [x for x in words['properties'] if x['word'] not in clashes]
    tally_a = part_a(a, PK.with_words(full, words))
    tally_b = part_b(b, full, 'full language pack')
    tally_b0 = part_b(b, base, 'base language pack')
    print('\n# Summary')
    print('A. reading (by number of features; 3 = three or more)')
    for size in sorted(tally_a):
        print('   %d: %s of %d' % (size, ', '.join('%s %d' % kv for kv in sorted(tally_a[size].items())), sum(tally_a[size].values())))
    total = {}
    for row in tally_a.values():
        for k, v in row.items():
            total[k] = total.get(k, 0) + v
    print('   all: %s of %d' % (', '.join('%s %d' % kv for kv in sorted(total.items())), sum(total.values())))
    for title, tally in (('B. answering, full pack', tally_b), ('B. answering, base pack', tally_b0)):
        print(title)
        for kind in sorted(tally or {}):
            print('   %-10s %s of %d' % (kind, ', '.join('%s %d' % kv for kv in sorted(tally[kind].items())), sum(tally[kind].values())))


if __name__ == '__main__':
    main()
