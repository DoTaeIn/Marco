"""Three packs, one system.

  language pack   how sentences are built: counts from lessons that use made-up property
                  words, plus connector variants from raw text. Shared by every field.
  word pack       the field's vocabulary: its property words, other words for them, and
                  other names for its subjects.
  fact pack       the field's facts, each with its source and scope.

Loading puts the three into one graph. Every property word of the field becomes a word the
reader knows, with the counts the lessons gave to made-up property words, so it is read in
questions, written in sentences and found in facts without a single new lesson. The facts
are written out as sentences by the writer and read back by the reader, which gives the
knowledge graph and ties every answer to a fact and its source.

Changing the field means changing the word pack and the fact pack. The language pack stays.
"""
import json

from . import answer as A
from . import basic as B
from . import reader as R
from . import write as W

WORDS = 'graph-field-words-v1'
FACTS = 'graph-field-facts-v1'


def key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def language_pack(lessons, variants=None):
    """Counts from field-free lessons. This is an ordinary reader model."""
    return R.build(lessons, variants=variants)


def with_words(language, words, basic=None):
    """The language pack with the field's property words made readable and writable.

    A field word gets the counts that the lessons' own words of the same slot have, pooled:
    what such a word means, what sentences it appears in, and which arguments it takes.
    The language pack itself is not changed.

    With `basic` (basic.load), a property may come with `explained`, one line in plain words
    ("쉬는 날"). The concepts that line reaches are kept, and so are its words no lesson knows,
    for the one who wrote the field to see. Without `basic` nothing of this is in the model.
    """
    if words.get('schema') != WORDS:
        raise ValueError('unsupported word pack')
    kind, attribute = words['slot']['type'], words['slot']['attribute']
    tables = language['tables']
    alike = {}
    for word, row in tables.get('head', {}).items():
        for label, cell in row.items():
            entry = json.loads(label)
            if entry['type'] == kind and [p for p, _ in entry['literals']] == [attribute]:
                alike[word] = (label, cell['n'])
    if not alike:
        raise ValueError('the language pack has no lesson word in the slot %s/%s' % (kind, attribute))
    typical = max(1, sum(n for _, n in alike.values()) // len(alike))

    def pooled(table, cues):
        out = {}
        for cue in cues:
            for label, cell in tables.get(table, {}).get(cue, {}).items():
                out[label] = out.get(label, 0) + cell['n']
        return out

    in_sentences = pooled('head_in', alike)
    takes = pooled('frame', [label for label, _ in alike.values()])
    parts = pooled('part', [label for label, _ in alike.values()])
    model = dict(language, tables=dict(tables), cues=dict(language['cues']))
    for name in ('head', 'head_in', 'frame', 'part'):
        model['tables'][name] = dict(tables.get(name, {}))
    if 'word_kind' in tables:
        model['tables']['word_kind'] = dict(tables['word_kind'])
    # The lessons' own words of this slot showed the form of such a word; they are not words of the field.
    # Left readable, "절기" is a known piece inside the field's "동절기" and "높이" cannot be a field word.
    makes_way = R.recipe_of(language)[1].get('lesson_words') == 'make_way'
    if makes_way:
        for word in alike:
            for name in ('head', 'head_in'):
                model['tables'][name].pop(word, None)
            model['cues'].pop(word, None)
    added = []
    for prop in words['properties']:
        entry = key({'literals': [[attribute, prop['means']]], 'type': kind})
        for surface in [prop['word']] + prop.get('also', []):
            if surface in model['tables']['head'] or surface in tables.get('closed', {}):
                raise ValueError('"%s" is already a word of the language pack' % surface)
            origin = ['word pack: ' + surface + ('' if surface == prop['word'] else ' = ' + prop['word'])]
            # The field's main word is the one written; another word for it is read just as well.
            weight = typical if surface == prop['word'] else max(1, typical // 2)
            model['tables']['head'][surface] = {entry: {'n': weight, 'origins': origin}}
            model['tables']['head_in'][surface] = {label: {'n': n, 'origins': origin} for label, n in in_sentences.items()}
            model['cues'][surface] = {'used': {'n': typical, 'origins': origin}}
            added.append(surface)
        model['tables']['frame'][entry] = {label: {'n': n, 'origins': ['word pack: ' + prop['word']]}
                                           for label, n in takes.items()}
        if parts:
            model['tables']['part'][entry] = {label: {'n': n, 'origins': ['word pack: ' + prop['word']]}
                                              for label, n in parts.items()}
    model['field_words'] = added
    model['field_slot'] = dict(words['slot'])      # which roles carry the thing and the value: used to find the fact a question asks about
    model['field_word_weight'], model['field_names'], model['field_values'] = typical, [], []
    _know_names(model, [n for name in words.get('names', []) for n in [name['name']] + name.get('also', [])], 'word_pack')
    if basic is not None:
        marks, endings = A.word_ends(model['tables'])
        model['basic'], model['field_explained'], model['field_unexplained'] = basic, {}, []
        model['field_explained_words'] = {p['means']: p['explained'] for p in words['properties'] if p.get('explained')}
        for prop in words['properties']:
            if prop.get('explained'):
                reached, unknown = B.concepts_of(basic, prop['explained'], marks, endings)
                model['field_explained'][prop['means']] = sorted(reached)
                if unknown:
                    model['field_unexplained'].append({'property': prop['means'], 'words': unknown})
    return model


def _know_names(model, names, source):
    """Make the field's names known pieces, when the pack's conventions say so.

    The reader already refuses a reading that leaves a known piece unused in a way the lessons
    never did. A known name inside a longer free value is such a piece, so "A와 B" is no longer
    read as one name. A name that is already a word of the language pack is left alone.
    """
    rule = R.recipe_of(model)[1].get('known_names')
    if not rule or source not in rule['from']:
        return
    tables = model['tables']
    for name in names:
        # What the field states about its own word outranks the general list of word kinds.
        tables.get('word_kind', {}).pop(name, None)
        if name in model['cues'] or name in tables.get('head', {}) or name in tables.get('closed', {}):
            continue
        model['cues'][name] = {'used': {'n': model['field_word_weight'], 'origins': ['field pack: a name']}}
        model['field_names'].append(name)


def load(language, words, facts, basic=None):
    """Put the three packs together. Returns the system that `ask` and `tell` use."""
    if facts.get('schema') != FACTS:
        raise ValueError('unsupported fact pack')
    model = with_words(language, words, basic)
    kind, attribute = words['slot']['type'], words['slot']['attribute']
    subject, value = words['slot']['subject_role'], words['slot']['value_role']
    known = {p['means'] for p in words['properties']}
    _know_names(model, [fact['subject'] for fact in facts['facts']], 'fact_subjects')
    if model['field_names']:
        # A value the pack itself states is explained, even when a known name lies inside it.
        model['field_values'] = sorted({fact['value'] for fact in facts['facts']})
    sentences, placed, unusable, at = [], [], [], 0
    for fact in facts['facts']:
        if fact['property'] not in known:
            unusable.append({'fact': fact['id'], 'reason': 'property "%s" is not in the word pack' % fact['property']})
            continue
        said = W.say(model, kind, [[attribute, fact['property']]], [(subject, fact['subject']), (value, fact['value'])])
        if said['status'] != 'said':
            unusable.append({'fact': fact['id'], 'reason': said['reason']})
            continue
        placed.append({'span': [at, at + len(said['text'])], 'fact': fact, 'sentence': said['text']})
        sentences.append(said['text'])
        at += len(said['text']) + 1
    text = ' '.join(sentences)
    reading = R.read(text, model) if text else {'status': 'unresolved', 'reason': 'no usable fact', 'graphs': []}
    if text and reading['status'] != 'complete':
        raise ValueError('the facts were written but could not be read back: ' + reading['reason'])
    aliases = {}
    for name in words.get('names', []):
        for other in name.get('also', []):
            aliases[other] = name['name']
    return {'model': model, 'text': text, 'graph': reading['graphs'][0] if text else None, 'reading': reading,
            'facts': placed, 'unusable': unusable, 'aliases': aliases,
            'field': words.get('field'), 'counts': {'facts': len(placed), 'field_words': len(model['field_words'])}}


def ask(system, question, memory=None):
    """Answer a question from the loaded packs. Adds the facts and sources behind the answer."""
    if system['graph'] is None:
        return dict(A._blank(None, None), reason='no usable fact is loaded')
    result = A.answer_graph(system['graph'], system['text'], question, system['model'], system['reading'], memory,
                            aliases=system['aliases'])
    used = []
    for item in system['facts']:
        a, b = item['span']
        if any(a <= e['span'][0] < b for e in result.get('evidence', [])):
            used.append(item['fact'])
    result['facts'] = used
    return result


def tell(system, question, result):
    """The full report, with the sources of the facts the answer rests on."""
    lines = A.explain(system['text'], question, result).split('\n')
    if result.get('facts'):
        extra = ['## Sources', '']
        for fact in result['facts']:
            src = fact.get('source', {})
            extra.append('- %s: %s of %s is %s. Source: %s (as of %s). Scope: %s' % (
                fact['id'], fact['property'], fact['subject'], fact['value'], src.get('url', '-'),
                src.get('as_of', '-'), src.get('scope', '-')))
        at = lines.index('Question: `%s`' % question) if 'Question: `%s`' % question in lines else len(lines)
        lines[at:at] = extra + ['']
    return '\n'.join(lines)
