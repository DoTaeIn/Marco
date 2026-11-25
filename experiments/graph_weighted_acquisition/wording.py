"""Which property an unfamiliar word of a question may be about, counted from ordinary text.

The knowledge says "the 전화 of X is ...". A question says "X에 몇 번으로 걸어요?". Nothing in the
knowledge ties 걸어요 to 전화; people's writing does: in ordinary sentences 걸- stands next to 전화
far more often than chance. This module counts that, for the property words of one field, in a file
of plain sentences (one per line), and keeps integer counts only.

No list of endings is used. Every word next to a property word is counted under its first one, two
and three letters, and a word of a question is looked up under all three (쉬, 쉬어, 쉬어요). A
longer form takes away what a shorter one says only where it had the chance to show the same and did
not ("내용" is not "내-"); that the text never had "쉬어요" beside a rare property word says nothing.

What comes out of here is a guess. answer._anchor uses it for a proposal put to the user, never for
an answer, and never to take a candidate away.
"""
import re

SCHEMA = 'graph-weighted-acquisition/wording-counts/v1'
# Set on 2026-11-25 while looking at words of the fourth outside set (exposed); not changed after that.
# A property whose words the text has in fewer than `property_seen` sentences is not pointed at: too little to count.
LEAST = {'window': 5, 'together': 5, 'seen': 50, 'times_chance': 4, 'letters': 3, 'property_seen': 100}
_EDGE = ' \t\r\n.,?!()[]{}"\'~:;/<>*-_=+|^%&#@…·“”‘’'


def _words(line):
    return [w for w in (t.strip(_EDGE) for t in line.split()) if w]


def build(path, properties, corpus, least=None):
    """Count, in the sentences of `path`, the words standing within a few words of each property word.
    `properties` is {property: [the words the field has for it]}. Returns the table (plain data)."""
    least = dict(LEAST, **(least or {}))
    surface = {w: p for p, ws in properties.items() for w in ws}
    by_length = sorted(surface, key=len, reverse=True)
    quick = re.compile('|'.join(map(re.escape, by_length)))
    span, letters = least['window'], least['letters']

    def prop_of(word):
        return next((surface[s] for s in by_length if word.startswith(s)), None)

    sentences, with_prop, together, examples = 0, dict.fromkeys(properties, 0), {}, {}
    with open(path, encoding='utf8') as f:
        for number, line in enumerate(f, 1):
            sentences += 1
            if not quick.search(line):
                continue
            words = _words(line)
            props = [prop_of(w) for w in words]
            seen = set()
            for i, p in enumerate(props):
                if p is None:
                    continue
                seen.add((None, p))
                for j in range(max(0, i - span), min(len(words), i + span + 1)):
                    if props[j] is None:
                        seen.update((words[j][:n], p) for n in range(1, min(letters, len(words[j])) + 1))
            for form, p in seen:
                if form is None:
                    with_prop[p] += 1
                else:
                    row = together.setdefault(form, {})
                    row[p] = row.get(p, 0) + 1
                    if row[p] <= 3:
                        examples.setdefault(form, {}).setdefault(p, []).append(number)
    kept = {form: {p: n for p, n in row.items() if n >= least['together']} for form, row in together.items()}
    kept = {form: row for form, row in kept.items() if row}
    first = {form[0] for form in kept}
    seen_in = {}
    with open(path, encoding='utf8') as f:
        for line in f:
            forms = {w[:n] for w in _words(line) if w[0] in first for n in range(1, min(letters, len(w)) + 1)}
            for form in forms:
                seen_in[form] = seen_in.get(form, 0) + 1
    table = {'schema': SCHEMA, 'corpus': corpus, 'sentences': sentences, 'least': least,
             'properties': {p: {'words': list(ws), 'sentences': with_prop[p]} for p, ws in properties.items()}, 'forms': {}}

    def pointing(form):
        return {p for p, n in kept.get(form, {}).items()
                if with_prop[p] >= least['property_seen'] and n * sentences >= least['times_chance'] * seen_in[form] * with_prop[p]}

    for form, n in seen_in.items():
        if n < least['seen']:
            continue
        # Kept: a form that points at a property, and a longer form the text knows well that begins with one
        # (it stops the shorter one: "내용" is not "내-").
        if pointing(form) or any(seen_in.get(form[:k], 0) >= least['seen'] and pointing(form[:k]) for k in range(1, len(form))):
            table['forms'][form] = {'n': n, 'near': dict(sorted(together.get(form, {}).items())),
                                    'lines': {p: examples[form][p] for p in sorted(kept.get(form, {}))}}
    return table


def points(table, word):
    """The properties a word may be about: {property: [how many times more often than chance the word
    stands near the property's words, the form of the word that showed it]}."""
    word, least, total = word.strip(_EDGE), table['least'], table['sentences']
    forms = [(word[:n], table['forms'][word[:n]]) for n in range(1, min(least['letters'], len(word)) + 1) if word[:n] in table['forms']]
    out = {}
    for p, prop in table['properties'].items():
        if prop['sentences'] < least['property_seen']:
            continue
        found = None
        for form, entry in forms:
            chance = entry['n'] * prop['sentences']
            together = entry['near'].get(p, 0)
            if chance and together >= least['together'] and together * total >= least['times_chance'] * chance:
                found = [together * total // chance, form]
            elif found and chance * found[0] >= least['together'] * total:
                found = None                       # it had the chance to show the same, and did not
        if found:
            out[p] = found
    return out
