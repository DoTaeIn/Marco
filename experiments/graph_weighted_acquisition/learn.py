"""Provisional memory: words the reader was told about in conversation.

When a question holds because of an unknown word, the reader proposes what the word could
be, in terms of words it already knows, and asks. A confirmed answer is stored here, never
in the lessons or the model. A stored word:

  - is provisional until enough different people have confirmed the same meaning
  - never replaces or contradicts anything the lessons teach
  - is named in every answer that relied on it
  - can be forgotten, which returns the questions it was used for

Nothing is inferred silently. The only way a word gets in is `teach` or `mark_name`.
"""
import copy
import json

SCHEMA = 'graph-provisional-memory-v1'
DEFAULT_POLICY = {'promote_after': 3, 'uses_kept': 50}


def new_memory(policy=None):
    return {'schema': SCHEMA, 'policy': dict(DEFAULT_POLICY, **(policy or {})), 'entries': [], 'names': []}


def _taught_by_lessons(model, word):
    tables = model['tables']
    gaps = {g.strip() for group in tables.get('gap', {}).values() for g in group}
    return word in tables.get('closed', {}) or word in tables.get('head', {}) or word in gaps


def _entry(memory, word):
    return next((e for e in memory['entries'] if e['word'] == word), None)


def teach(memory, model, word, meaning, by, at, context=''):
    """Record that `by` confirmed `word` means `meaning` (a fixed-word entry the model already has).

    Returns the entry. A second, different meaning for the same word puts it in dispute, and a
    disputed word is not used until it is forgotten and taught again.
    """
    if memory.get('schema') != SCHEMA:
        raise ValueError('unsupported memory')
    if not word or not word.strip() or word != word.strip():
        raise ValueError('a word must be non-empty text without surrounding blanks')
    if _taught_by_lessons(model, word):
        raise ValueError('"%s" is already taught by the lessons and cannot be re-taught here' % word)
    label = json.dumps(meaning, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    known = {m for row in model['tables'].get('closed', {}).values() for m in row}
    if label not in known:
        raise ValueError('the meaning must be one the lessons already use for a fixed word')
    memory['names'] = [n for n in memory['names'] if n['word'] != word]
    entry = _entry(memory, word)
    confirmation = {'by': by, 'at': at, 'context': context}
    if entry is None:
        entry = {'word': word, 'meaning': meaning, 'status': 'provisional', 'confirmations': [confirmation], 'uses': []}
        memory['entries'].append(entry)
    elif entry['meaning'] != meaning:
        entry['status'] = 'disputed'
        entry.setdefault('disputes', []).append(dict(confirmation, meaning=meaning))
    elif by not in [c['by'] for c in entry['confirmations']]:
        entry['confirmations'].append(confirmation)
    if entry['status'] == 'provisional' and len(entry['confirmations']) >= memory['policy']['promote_after']:
        entry['status'] = 'confirmed'
    return entry


def mark_name(memory, word, by, at):
    """Record that `word` is a name, so the reader stops reporting it as unknown."""
    if _entry(memory, word):
        raise ValueError('"%s" is stored as a fixed word; forget it first' % word)
    if word not in [n['word'] for n in memory['names']]:
        memory['names'].append({'word': word, 'by': by, 'at': at})
    return memory['names'][-1]


def forget(memory, word):
    """Remove everything stored about a word. Returns what was removed, with the questions it was used for."""
    removed = [e for e in memory['entries'] if e['word'] == word] + [n for n in memory['names'] if n['word'] == word]
    memory['entries'] = [e for e in memory['entries'] if e['word'] != word]
    memory['names'] = [n for n in memory['names'] if n['word'] != word]
    return removed


def overlay(model, memory):
    """The model as the reader should see it: lessons plus usable stored words. The model is not changed."""
    if not memory or (not memory['entries'] and not memory['names']):
        return model
    out = dict(model, tables=dict(model['tables']), cues=dict(model['cues']))
    closed = out['tables']['closed'] = dict(out['tables'].get('closed', {}))
    for entry in memory['entries']:
        if entry['status'] == 'disputed' or _taught_by_lessons(model, entry['word']):
            continue
        label = json.dumps(entry['meaning'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        people = [c['by'] for c in entry['confirmations']]
        cell = {'n': len(people), 'origins': ['told by ' + p for p in people[:5]],
                'learned': {'word': entry['word'], 'status': entry['status'], 'confirmed_by': people}}
        closed[entry['word']] = {label: cell}
        out['cues'][entry['word']] = {'used': {'n': len(people), 'origins': cell['origins']}}
    out['known_names'] = [n['word'] for n in memory['names']]
    return out


def record_use(memory, words, question):
    for word in words:
        entry = _entry(memory, word)
        if entry is not None and question not in entry['uses']:
            entry['uses'] = (entry['uses'] + [question])[-memory['policy']['uses_kept']:]


def describe(model, meaning):
    """A fixed-word meaning in plain words, with lesson words that share it."""
    label = json.dumps(meaning, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    alike = sorted(word for word, row in model['tables'].get('closed', {}).items() if label in row)
    what = 'a word that asks for a %s' % meaning['type'] if meaning.get('project') else 'a fixed word for a %s' % meaning['type']
    return what, alike


def propose(model, memory, question, unknown_words, read):
    """Meanings that would let the question be read, each with the question to put to the user.

    Every proposal is tested: the word is given the meaning in a scratch copy of the memory and
    the question is read again. Only meanings under which it reads with confidence are offered.
    """
    meanings = []
    for row in model['tables'].get('closed', {}).values():
        for label in row:
            if json.loads(label) not in meanings:
                meanings.append(json.loads(label))
    proposals = []
    for word in unknown_words:
        if _taught_by_lessons(model, word):
            continue
        for meaning in meanings:
            scratch = copy.deepcopy(memory) if memory else new_memory()
            scratch['entries'] = [e for e in scratch['entries'] if e['word'] != word]
            scratch['names'] = [n for n in scratch['names'] if n['word'] != word]
            teach(scratch, model, word, meaning, 'trial', 'trial')
            result = read(question, overlay(model, scratch))
            if result['status'] == 'complete' and not result.get('ignored'):
                what, alike = describe(model, meaning)
                proposals.append({'word': word, 'meaning': meaning, 'like': alike,
                                  'ask': 'Is "%s" %s, like %s? Or is it a name?'
                                         % (word, what, ', '.join('"%s"' % a for a in alike[:3]))})
    return proposals
