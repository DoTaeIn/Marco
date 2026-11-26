"""세금 여덟째 묶음: 일곱째의 속성 풀이·지식에 새 출제자의 질문을 붙이고, 교사의 묻는 말을 형식만 검사해 옮긴다.
인자: tax7 C.json, 질문 초안, 묻는 말 초안, 출력 폴더."""
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')
base, draft, asked, out = sys.argv[1:5]
c = json.load(open(base, encoding='utf8'))
q = json.load(open(draft, encoding='utf8'))['questions']
ids = {k['id'] for k in c['knowledge']}
value = {k['id']: k['text'] for k in c['knowledge']}
for item in q:
    assert set(item['needs']) <= ids, item
    assert (item['kind'] == 'check') == ('claim' in item), item
    if item['expect'] is not None:
        assert any(item['expect'] + '이다.' in value[n] for n in item['needs']), item
print('questions', len(q), dict(Counter(i['kind'] for i in q)))
c['questions'] = q
c['domain'] = c['domain'].replace('explanations and questions', 'explanations by the seventh set\'s examiner, questions by a second examiner')
json.dump(c, open(out + '/C.json', 'w', encoding='utf8', newline='\n'), ensure_ascii=False, indent=1)

ways = json.load(open(asked, encoding='utf8'))
banned = {p['word']: [p['word']] + p.get('also', []) for p in c['properties']}
assert set(ways) == set(banned), set(ways) ^ set(banned)
kept, dropped = {}, []
for prop, lines in ways.items():
    kept[prop] = []
    for line in lines:
        bad = line.count('X') != 1 or any(w in line.replace(' ', '') for w in banned[prop])
        (dropped if bad else kept[prop]).append(line if not bad else (prop, line))
print('ways kept', {p: len(v) for p, v in kept.items()}, 'dropped by the form rules', dropped)
json.dump(kept, open(out + '/asked.json', 'w', encoding='utf8', newline='\n'), ensure_ascii=False, indent=1)
