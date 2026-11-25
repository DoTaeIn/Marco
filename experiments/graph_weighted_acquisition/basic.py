"""Basic words: what a common word of the language points at.

A lesson ties one word to concepts, the language-free knots of meaning: 사다 -> 돈, 씀, 물건, 얻음.
A word may have several senses, each a set of concepts, and a use in which it carries no meaning
at all (`light`). The lessons are data written by a teacher (packs/basic_words_ko.tsv); nothing
here knows a word.

They are used where a question was not read: the pieces of the question and the plain-words
explanation a field gives of a property meet at concepts (answer._anchor). What is worked out
this way only adds a candidate. It never makes an answer and never removes one.
"""
import unicodedata
from pathlib import Path

KINDS = {'뜻': 'means', '물음': 'asks', '가벼움': 'light'}


FINAL = {'ㄴ': 'ᆫ', 'ㄹ': 'ᆯ', 'ㅂ': 'ᆸ', 'ㅆ': 'ᆻ', 'ㅁ': 'ᆷ'}     # a letter written alone, as the last sound of a character


def _letters(text):
    """Letter by letter. An ending that starts with a lone consonant goes under the stem's last character."""
    return FINAL.get(text[:1], text[:1]) + unicodedata.normalize('NFD', text[1:]) if text[:1] in FINAL \
        else unicodedata.normalize('NFD', text)


def load_ends(path, words):
    """Read the lessons on how a word changes its shape (packs/word_ends_ko.tsv).

    A word that takes endings has three stems, and each stem its own endings; a word that does not
    has connectors. Every stem with every ending of its kind is a form of the word. An ending of
    several words is cut at its first word: the others are words of their own ("ㄹ 수 있나요").
    Returns the forms, letter by letter, and the connectors.
    """
    blocks, name = {}, None
    for line in Path(path).read_text(encoding='utf8').splitlines():
        if line.startswith('#'):
            name = line.lstrip('# ').strip()
            blocks[name] = []
        elif line.strip() and name:
            blocks[name].append(line.strip())
    kinds = ['바탕줄기 뒤', '으줄기 뒤', '어줄기 뒤']
    endings = [sorted({_letters(e.split()[0].strip('?.!,')) for e in blocks.get(k, [])}) for k in kinds]
    forms = {}
    for n, line in enumerate(blocks.get('줄기', []), 1):
        cells = line.split('\t')
        if len(cells) != 4 or cells[0] not in words:
            raise ValueError('line %d of the stems is not a taught word with three stems' % n)
        for stems, ends in zip(cells[1:], endings):
            for stem in stems.split('/'):
                if stem != '-':
                    for end in ends:
                        forms.setdefault(unicodedata.normalize('NFD', stem) + end, set()).add(cells[0])
    return {k: sorted(v) for k, v in forms.items()}, sorted(set(blocks.get('이름씨 뒤', [])), key=len, reverse=True)


def load(path, ends=None):
    """Read the lessons. The file has a block of concepts and a block of words, tab-separated.
    With `ends`, the taught stems, endings and connectors are how a word is found in a text."""
    concepts, words, block = {}, {}, None
    for n, line in enumerate(Path(path).read_text(encoding='utf8').splitlines(), 1):
        if not line.strip():
            continue
        if line.startswith('#'):
            block = line.lstrip('# ').strip()
            continue
        cells = line.split('\t')
        if block == '개념':
            concepts[cells[0]] = cells[1] if len(cells) > 1 else ''
            continue
        if len(cells) != 3 or cells[1] not in KINDS:
            raise ValueError('line %d of the basic words is not "word, kind, senses"' % n)
        senses = [s.strip() for s in cells[2].split(';')]
        entry = {'word': cells[0], 'kind': KINDS[cells[1]], 'light': '-' in senses,
                 'senses': [sorted(s.split('+')) for s in senses if s != '-']}
        unknown = sorted({c for s in entry['senses'] for c in s} - set(concepts))
        if unknown:
            raise ValueError('line %d of the basic words uses concepts that are not listed: %s' % (n, ', '.join(unknown)))
        words[cells[0]] = entry
    if ends:
        forms, marks = load_ends(ends, words)
        return {'concepts': concepts, 'words': words, 'stems': {}, 'forms': forms, 'marks': marks}
    # Without the lessons on shapes: a word listed in its -다 form is taken to take endings (wrong for a
    # noun such as 바다), and only the endings the language pack learned are known.
    stems = {}
    for word, entry in words.items():
        if word.endswith('다') and len(word) > 1:
            stems.setdefault(unicodedata.normalize('NFD', word[:-1]), []).append(entry)
    return {'concepts': concepts, 'words': words, 'stems': stems, 'forms': {}, 'marks': []}


def lookup(basic, piece, marks=(), endings=()):
    """The lessons a piece of text may be a form of: the word itself, the word in front of a connector
    (taught, or one the language pack has), a taught stem with a taught ending, or a stem with an
    ending the language pack learned. Every one is kept."""
    out = []
    marks = list(marks) + list(basic['marks'])
    for cut in [piece] + [piece[:-len(m)] for m in marks if piece.endswith(m) and len(piece) > len(m)]:
        if cut in basic['words'] and basic['words'][cut] not in out:
            out.append(basic['words'][cut])
    letters = unicodedata.normalize('NFD', piece)
    out += [basic['words'][w] for w in basic['forms'].get(letters, []) if basic['words'][w] not in out]
    for stem, entries in basic['stems'].items():
        if letters.startswith(stem) and letters[len(stem):] in endings:
            out += [e for e in entries if e not in out]
    return out


def concepts_of(basic, text, marks=(), endings=()):
    """The concepts a plain-words explanation reaches, and the words of it that were never taught.
    A word with several senses gives all of them: nothing is chosen here."""
    reached, unknown = set(), []
    for token in text.split():
        token = token.strip('?.!,')
        entries = lookup(basic, token, marks, endings)
        if not entries:
            unknown.append(token)
        for entry in entries:
            for sense in entry['senses']:
                reached |= set(sense)
    return reached, unknown


def explained_by(basic, pieces, explanations, marks=(), endings=()):
    """The properties whose explanation accounts for every piece.

    A piece is accounted for by a property when one of its senses lies wholly inside the concepts of
    that property's explanation, or when it has a light use. A piece no lesson knows, or a known
    word whose meaning the explanation does not have ("어린이" next to a fee), is accounted for by
    nothing, so no property is found. At least one piece must meet the explanation by meaning:
    light words alone point at nothing.
    """
    read = [lookup(basic, piece, marks, endings) for piece in pieces]
    if not read or not all(read):
        return []
    out = []
    for prop, reached in sorted(explanations.items()):
        met, reached = 0, set(reached)
        for entries in read:
            if any(set(sense) <= reached for e in entries for sense in e['senses']):
                met += 1
            elif not any(e['light'] for e in entries):
                break
        else:
            if met:
                out.append(prop)
    return out
