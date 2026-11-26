"""Relations inside one sentence: which word hangs on which, and by what.

A sentence is made into a small graph by form alone. Every word is cut into what it is and what
follows it: a taught connector after a noun ("짐" + "을"), or a taught ending after a stem
("맡기" + "면"). A word with a connector hangs on the next word that can take endings; any other
word hangs on the next word. The language puts the head last, and nothing else is assumed.

A stem is brought back to its first shape by the ways the taught words change theirs
(basic.load_ends): "맡겨" and "맡길" both give "맡기", though no lesson has the word. A cut that
could go two ways is kept both ways.

The same cut, run over ordinary sentences, counts who stands where (`places`): the numbers sit on
the edges and only put things in order.

This is used for a word no lesson knows (`placed`). The word is put next to the plain-words
explanation of every property: it may be a word of the explanation in another shape, or it may
stand where a word of the explanation stands, under the same head and by the same connector
("짐을 맡기면" next to "물건을 맡길 때"). The second says what part the word plays, not what it
means. What comes of either is put to the user, never answered.
"""
import unicodedata

from . import basic as B


def words(basic, text):
    """The words of a text: what each may be (`keys`), what follows it (`marks`), whether it can
    take endings (`pred`), and the word it hangs on (`head`, an index, or None for the last)."""
    shape = basic['shape']
    if 'by_end' not in shape:                           # every ending, with the stems it follows
        shape['by_end'] = {}
        for k, ends in enumerate(shape['endings']):
            for end in ends:
                shape['by_end'].setdefault(end, []).append(k)
        shape['longest'] = max(map(len, shape['by_end']), default=0)
    out = []
    for token in text.split():
        token = token.strip('?.!,')
        if not token:
            continue
        letters = unicodedata.normalize('NFD', token)
        row = {'text': token, 'keys': {letters}, 'marks': set(), 'pred': False}
        mark = next((m for m in basic['marks'] if token.endswith(m) and len(token) > len(m)), None)
        if mark:
            row['keys'].add(unicodedata.normalize('NFD', token[:-len(mark)]))
            row['marks'].add(mark)
        if token in basic['words'] and not token.endswith('다'):
            pass                                        # a word the lessons list whole is that word
        elif not mark or B._letters(mark) in shape['by_end']:   # "는" follows a noun and a stem alike
            for n in range(1, min(shape['longest'], len(letters) - 1) + 1):
                end, stem = letters[-n:], letters[:-n]
                for k in shape['by_end'].get(end, ()):
                    for tail, first in shape['rules'][k]:
                        if stem.endswith(tail) and len(stem) > len(tail) - len(first):
                            row['keys'].add(stem[:len(stem) - len(tail)] + first)
                            row['marks'].add(end)
                            row['pred'] = True
        out.append(row)
    for n, row in enumerate(out):
        later = range(n + 1, len(out))
        row['head'] = next((k for k in later if out[k]['pred']), None) if row['marks'] and not row['pred'] else None
        if row['head'] is None and n + 1 < len(out):
            row['head'] = n + 1
    return out


def places(basic, sentences):
    """Who stands where, counted over ordinary sentences: {(connector, head): {noun: times}}.

    Only a word that is plainly a noun with a connector, hanging on a word that takes endings, is
    counted ("가방을 맡기면" -> (을, 맡기): 가방). Nothing is chosen: every shape the head may come
    back to is a place of its own.
    """
    out = {}
    for sentence in sentences:
        rows = words(basic, sentence)
        for row in rows:
            if row['pred'] or not row['marks'] or row['head'] is None or not rows[row['head']]['pred']:
                continue
            head = rows[row['head']]
            noun = min(row['keys'], key=len)
            for mark in row['marks']:
                for key in head['keys'] - {unicodedata.normalize('NFD', head['text'])}:
                    place = out.setdefault((mark, key), {})
                    place[noun] = place.get(noun, 0) + 1
    return out


def save(table, path, least=2):
    """One line per place and noun seen there at least `least` times."""
    with open(path, 'w', encoding='utf8', newline='\n') as f:
        for (mark, key), nouns in sorted(table.items()):
            for noun, n in sorted(nouns.items()):
                if n >= least:
                    f.write('%s\t%s\t%s\t%d\n' % (mark, key, noun, n))


def load(path):
    """The places, and for every noun the places it was seen in."""
    table, seen = {}, {}
    with open(path, encoding='utf8') as f:
        for line in f:
            mark, key, noun, n = line.rstrip('\n').split('\t')
            table.setdefault((mark, key), {})[noun] = int(n)
            seen.setdefault(noun, set()).add((mark, key))
    return {'at': table, 'of': seen}


def placed(basic, question, explanations, text=None):
    """For every property, the words of the question that no lesson knows and that its explanation
    places: {property: {word: (how, word of the explanation, number)}}.

    "same": a word of the explanation in another shape. "place": it stands where a word of the
    explanation stands. "like", only with `text` (load): ordinary text has a noun of the
    explanation in the very place the word stands in here, and the two were seen in other places
    together; the number is how many of a thousand places of either both stand in, and it only
    puts things in order.
    """
    marks = basic['marks']
    asked = words(basic, question)
    out = {}
    for prop, said in explanations.items():
        told = words(basic, said)
        for q in asked:
            if B.lookup(basic, q['text'], marks):
                continue                                # a taught word is met by its meaning, not here
            same = next((t for t in told if q['keys'] & t['keys']), None)
            if same:
                out.setdefault(prop, {})[q['text']] = ('same', same['text'], 0)
                continue
            if q['head'] is None or q['pred']:
                continue
            here = {(m, k) for m in q['marks'] for k in asked[q['head']]['keys']}
            best = None
            for t in told:
                if t['pred']:
                    continue
                if t['head'] is not None and q['marks'] & t['marks'] and asked[q['head']]['keys'] & told[t['head']]['keys']:
                    best = ('place', t['text'], 0)
                    break
                if text and not any(e['light'] for e in B.lookup(basic, t['text'], marks)):
                    noun, other = min(q['keys'], key=len), min(t['keys'], key=len)
                    if any(other in text['at'].get(place, {}) for place in here):
                        mine, theirs = text['of'].get(noun, set()), text['of'].get(other, set())
                        # Of a thousand places either stands in, how many both do: a common word shares
                        # places with everything, so the count alone would say nothing.
                        shared = 1000 * len(mine & theirs) // max(1, len(mine | theirs))
                        if shared and (best is None or shared > best[2]):
                            best = ('like', t['text'], shared)
            if best:
                out.setdefault(prop, {})[q['text']] = best
    return out
