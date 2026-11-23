import sys, json, importlib.util, collections
sys.path.insert(0, '.')
spec = importlib.util.spec_from_file_location('BT', 'experiments/graph_weighted_acquisition/probes/blind_test.py')
BT = importlib.util.module_from_spec(spec); spec.loader.exec_module(BT)
P, R, PK = BT.P, BT.R, BT.PK
a = json.load(open('experiments/graph_weighted_acquisition/probes/blind_20261123/A.json', encoding='utf8'))
full, _ = BT.language(BT.SETS)
words = {'schema': PK.WORDS, 'field': 'x', 'slot': BT.SLOT, 'properties': [{'word': w, 'means': w, 'also': []} for w in a['properties']], 'names': [{'name': w, 'also': []} for w in a['names']]}
loose = PK.with_words(full, words)
strict = dict(loose, conventions=dict(loose['conventions'], partial_reading_blocks_whole=True, contradicted_reading_blocks=True))
print('properties', a['properties'], 'names', a['names'])
causes = collections.Counter(); st = collections.Counter()
for item in a['sentences']:
    exp = [P.rel(r['kind'], **{k: v for k, v in r.items() if k != 'kind'}) for r in item['meaning']]
    v, _ = P.judge(loose, item['text'], exp); vs, _ = P.judge(strict, item['text'], exp)
    st[(v, vs)] += 1
    if v == 'HELD':
        r = R.read(item['text'], loose)
        best = r['readings'][0] if r['readings'] else None
        zero = [(t['what'], t['piece'].strip(), str(t['given'])[:12]) for t in (best['terms'] if best else []) if t['count'] == 0 and not t.get('graded')]
        key = zero[0][0] + ' | ' + zero[0][1] if zero else r['reason'][:40]
        causes[key] += 1
        print(item['id'], item['text'], '=>', zero[:2] or r['reason'][:50])
print('\n(loose, strict) verdict pairs:', dict(st))
print('\nheld causes:'); [print('  %d  %s' % (n, k)) for k, n in causes.most_common()]
