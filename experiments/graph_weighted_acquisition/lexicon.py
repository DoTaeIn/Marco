"""One step from a field's property words through a dictionary: which words lead back to which property.

A property word is looked up, and only it: its definition ("휴무일: 직무를 보지 아니하고 쉬는 날") and the
native reading of each hanja it is written with (休務日: 쉴 휴). The words found there are one step from
the property; nothing is looked up further, so there is an end to it. A word of a question that begins
like one of them may be about that property.

A word that is no headword is cut into two headwords (대여기간: 대여, 기간). Of a word's several senses,
those that share a hanja or a definition word with the property's other words are kept (요금 with 이용료
is 料金, not 瑤琴). A stem that leads to two properties of the field says nothing and is left out.

This is a guess, like wording.py. answer._anchor uses a pointer only where the two agree, and then for
a proposal put to the user, never for an answer.

Files (plain text, kept outside the repository): the dictionary as `headword TAB hanja TAB definition`
per noun sense; hanja readings as CSV with the columns `hanja` and `meaning`.
"""
import ast
import csv
import re
import unicodedata

SCHEMA = 'graph-weighted-acquisition/dictionary-step/v1'
_HANGUL = re.compile(r'[가-힣]+')
_RIEUL = 'ᆯ'
# Final consonants an ending may add to a stem (ㄴ ㄹ ㅁ ㅂ ㅆ): 쉬- in 쉰, 쉴, 쉼, 쉽니다, 쉬었.
_ADDED = 'ᆫᆯᆷᆸᆻ'
_NOUN_OF_ONE_LETTER = ('곳', '날', '값', '돈')


def _nfd(text):
    return unicodedata.normalize('NFD', text)


def _load(dictionary, hanja, surfaces):
    wanted = {w[i:j] for w in surfaces for i in range(len(w)) for j in range(i + 1, len(w) + 1)}
    entries = {}
    with open(dictionary, encoding='utf8') as f:
        for line in f:
            head, _, rest = line.partition('\t')
            if head in wanted:
                origin, _, definition = rest.rstrip('\n').partition('\t')
                entries.setdefault(head, []).append({'origin': origin, 'def': definition})
    readings = {}
    with open(hanja, encoding='utf8') as f:
        for row in csv.DictReader(f):
            try:
                for meanings, _ in ast.literal_eval(row['meaning']):
                    readings.setdefault(row['hanja'], []).extend(re.sub(r'\[.*?\]', '', m) for m in meanings)
            except (ValueError, SyntaxError):
                continue
    return entries, readings


def _senses(word, entries):
    """The senses of a word, as groups (one group per headword it is made of)."""
    if word in entries:
        return [entries[word]]
    for cut in range(len(word) - 1, 1, -1):
        if word[:cut] in entries and (word[cut:] in entries or len(word) - cut == 1):
            return [entries[word[:cut]]] + (_senses(word[cut:], entries) if word[cut:] in entries else [])
    return []


def _keys(entry, readings):
    return {c for c in entry['origin'] if c in readings} | {t[:2] for t in _HANGUL.findall(entry['def']) if len(t) >= 2}


def _stems(entry, readings):
    """(stem, kind, where from): verb stems from readings ending in ㄹ (쉴: 쉬-) and from the "-는" words of
    the definition; nouns from the other readings and the other words of the definition."""
    out = []
    for c in dict.fromkeys(ch for ch in entry['origin'] if ch in readings):
        for m in readings[c]:
            if not m:
                continue
            if _nfd(m).endswith(_RIEUL):
                stem = m[:-1] if m.endswith('을') else unicodedata.normalize('NFC', _nfd(m)[:-1])
                out.append((stem, 'verb', '%s %s' % (c, m)))
            else:
                out.append((m, 'noun', '%s %s' % (c, m)))
    for t in _HANGUL.findall(entry['def']):
        if len(t) >= 2:
            out.append((t[:-1], 'verb', '"%s"' % t) if t.endswith('는') else (t[:2], 'noun', '"%s"' % t))
    return [x for x in out if x[0] and (x[1] == 'verb' or len(x[0]) >= 2 or x[0] in _NOUN_OF_ONE_LETTER)]


def build(dictionary, hanja, properties, source):
    """`properties` is {property: [the words the field has for it]}. Returns the table (plain data)."""
    surfaces = [w for ws in properties.values() for w in ws]
    entries, readings = _load(dictionary, hanja, surfaces)
    found = {}
    for prop, words in properties.items():
        groups = [g for w in words for g in _senses(w, entries)]
        rows = []
        for i, group in enumerate(groups):
            others = set().union(*[_keys(e, readings) for j, g in enumerate(groups) if j != i for e in g]) if len(groups) > 1 else set()
            agreeing = [e for e in group if _keys(e, readings) & others]
            for e in (agreeing or group):
                rows += _stems(e, readings)
        found[prop] = rows
    times = {}
    for prop, rows in found.items():
        for key in {(s, k) for s, k, _ in rows}:
            times[key] = times.get(key, 0) + 1
    table = {'schema': SCHEMA, 'source': source, 'properties': {}}
    for prop, rows in found.items():
        kept = {}
        for stem, kind, where in rows:
            if times[(stem, kind)] == 1:
                kept.setdefault('%s %s' % (kind, stem), []).append(where)
        table['properties'][prop] = {key: sorted(set(v))[:3] for key, v in sorted(kept.items())}
    return table


def _begins(word, stem, kind):
    if kind == 'noun':
        return word.startswith(stem)
    a, b = _nfd(stem), _nfd(word)
    if b.startswith(a):
        nxt = b[len(a):len(a) + 1]
        return not ('ᆨ' <= nxt <= 'ᇂ') or nxt in _ADDED
    return len(stem) >= 2 and len(b) >= len(a) and b.startswith(a[:-1])      # 빌리- in 빌려


def points(table, word):
    """The properties a word is one step from: {property: [where the step comes from]}."""
    out = {}
    for prop, stems in table['properties'].items():
        for key, where in stems.items():
            kind, stem = key.split(' ', 1)
            if _begins(word, stem, kind):
                out.setdefault(prop, []).extend('%s- %s' % (stem, w) for w in where[:1])
    return out
