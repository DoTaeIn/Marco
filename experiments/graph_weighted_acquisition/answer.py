"""Answer a question from a passage and report exactly why.

Reading is done by the piece reader. The answer comes from matching the question
graph against the passage graph (match.py). The older native executor is run as
a second opinion and must agree whenever it finishes. No answer is given unless
both texts were read with a clear, fully observed lead and every condition of
the question is grounded in passage text.
"""
import argparse
import json
import re
import unicodedata
from pathlib import Path

from experiments.graph_example_acquisition import native
from experiments.graph_language_repair.questions.query_graph import execute_query_graph
from . import basic as B
from . import relate as RL
from . import learn as L
from . import match as M
from . import reader as R
from . import write as W


def answer(passage, question, model, memory=None):
    """Read the passage and the question, then answer from the passage's graph.

    `memory` (see learn.py) holds words told in conversation. It is read through an overlay;
    neither it nor the model is changed here, except that uses of a stored word are logged.
    """
    lessons_only, model = model, L.overlay(model, memory)
    p = R.read(passage, model)
    out = _blank(p, None)
    if p['status'] != 'complete':
        out['reason'] = 'the passage was not read with confidence: ' + p['reason']
        out['question'] = R.read(question, model)
        return out
    if p.get('ignored'):
        out['reason'] = 'the passage could only be read by ignoring %s; a passage is never answered from part of it' \
            % ', '.join('"%s"' % x for x in p['ignored'])
        out['question'] = R.read(question, model)
        return out
    return answer_graph(p['graphs'][0], passage, question, lessons_only, p, memory)


def _blank(passage_result, question_result):
    return {'passage': passage_result, 'question': question_result, 'answers': [], 'status': 'hold', 'evidence': [],
            'verified': False, 'executor': 'not run', 'executor_detail': '', 'partial': [], 'claim': None,
            'raw_text_variants': [], 'unknown_words': [], 'told_words': [], 'proposals': [], 'sentences': [],
            'other_names': []}


_ASKED = {}                                             # the listed ways of asking with the confirmed ones, per model and memory


def _asked_table(model, basic, memory):
    """The ways of asking the field listed, and with them every wording a user said yes to. A
    confirmed wording is one more listed way: its words then point at its property for other
    questions too, which only ever leads to something put to the user."""
    kept = tuple(sorted((e['property'], e['wording']) for e in (memory or {}).get('wordings', []) if e['yes']))
    if not kept:
        return model.get('field_asked')
    key = (id(model), kept)
    if key not in _ASKED:
        listed = {p: list(v) for p, v in model.get('field_asked_listed', {}).items()}
        for prop, text in kept:
            listed.setdefault(prop, []).append(text)
        _ASKED.clear()
        _ASKED[key] = RL.asked(basic, listed)
    return _ASKED[key]


def _claim_holds(claimed, answers, known):
    """Does the value a question states hold? True, False, or None when that cannot be said.

    What stands in front of the claim word is a stretch of text, not a value that was read
    ("사업개시일부터 20일 이내", "10%라던데"). It holds when it is the value, spaces apart. It is denied
    only when it is plainly another value: the same shape with other numbers ("15%" next to "10%"),
    or a name or value the knowledge has. Anything else may be the same value in other words, or
    the value with words after it: not said.
    """
    if len(answers) != 1 or len(answers[0]) != 1:
        return None
    value, said = ''.join(answers[0][0].split()), ''.join(claimed.split())
    if said == value:
        return True
    shape = lambda text: re.sub(r'[0-9]+', '#', text)
    if ('#' in shape(value) and shape(said) == shape(value)) or said in known:
        return False
    return None


def _claim_query(graph, text, predicate='claim'):
    """Turn "is X's P really V?" into "what is X's P?" plus the value that was claimed.

    Convention (named in the pack): an edge with the claim predicate marks a yes/no check, and the value mention
    standing right before the claim word is the one being checked.
    """
    marks = [(s, o) for s, p, o in graph['edges'] if p == predicate and isinstance(o, str)]
    if len(marks) != 1:
        return None
    anchors = {n['id']: n.get('anchor') for n in graph['nodes']}
    word = marks[0][1]
    named = [s for s, p, o in graph['edges'] if p == 'value' and anchors[s] and anchors[s][1] <= anchors[word][0]]
    if not named:
        return None
    checked = max(named, key=lambda n: anchors[n][1])
    keep = [(e, sp) for e, sp in zip(graph['edges'], graph['edge_spans'])
            if e[1] != predicate and not (e[0] == checked and e[1] == 'value')]
    query = {'nodes': [n for n in graph['nodes'] if n['id'] != word], 'edges': [e for e, _ in keep],
             'edge_spans': [sp for _, sp in keep], 'project': [checked]}
    return query, text[slice(*anchors[checked])]


def answer_graph(pgraph, ptext, question, model, passage_result=None, memory=None, aliases=None):
    """Answer a question from a given passage graph. Used by both arms."""
    lessons_only, model = model, L.overlay(model, memory)
    conventions_ = R.recipe_of(model)[1]
    if conventions_.get('reading_uses_knowledge') and pgraph is not None:
        model = _with_knowledge(model, pgraph, ptext)
    q = R.read(question, model)
    out = _blank(passage_result, q)
    if q['status'] == 'ambiguous' and conventions_.get('close_readings') == 'ask_knowledge' \
            and not q.get('open_roles') and not q.get('attachment'):
        decided = _decided_by_knowledge(pgraph, ptext, question, model, q, passage_result, aliases)
        if decided is not None:
            return decided
    if q['status'] != 'complete' and q.get('open_roles') and R.recipe_of(model)[1].get('open_role_answers') == 'assume':
        assumed = _one_reading(pgraph, ptext, question, model, q, passage_result, aliases)
        if assumed:
            if memory is not None:
                for item in assumed['assumed']:
                    L.note_assumed(memory, item['word'], item['kind'], question)
            return assumed
    if q['status'] != 'complete' and R.recipe_of(model)[1].get('unread_question_answers') == 'anchor':
        anchored = _anchor(pgraph, ptext, question, model, memory, aliases, passage_result, q)
        if anchored is not None:
            return anchored
    if q['status'] != 'complete':
        out['reason'] = 'the question was not read with confidence: ' + q['reason']
        if q.get('open_roles'):
            out['open_roles'] = q['open_roles']          # what to ask back, when the form leaves a word's role open
        if q.get('attachment'):
            out['attachment'] = q['attachment']          # what to ask back, when the form leaves a part's place open
        if q.get('unknown_words'):
            # A word that the passage also uses as a name is a name; the rest are the suspects.
            named = {ptext[slice(*o['copy'])] for s, p, o in pgraph['edges']
                     if p == 'value' and isinstance(o, dict) and 'copy' in o}
            out['unknown_words'] = [w for w in q['unknown_words'] if w not in named]
            if out['unknown_words']:
                out['reason'] = 'the question contains a word the reader does not know: %s. The sentence is ' \
                                'closed like one that %s, and it does so only if that word is not a name' \
                                % (', '.join('"%s"' % w for w in out['unknown_words']), q['expected'])
                out['proposals'] = L.propose(lessons_only, memory, question, out['unknown_words'], R.read)
        return out
    if memory is not None:
        L.note_kinds(memory, q, question)      # what the form of this question showed about its words
    return _answer_read(pgraph, ptext, question, model, q, out, passage_result, memory, aliases)


def _with_knowledge(model, pgraph, ptext):
    """The model the question is read with: what the knowledge shows about its own words is added.

    A word that the knowledge uses (the name of a thing, a value, a circumstance, a time) is known as
    the kind it was read as there, with the knowledge as origin. So "단체", in no lesson and no list, is
    a circumstance for a field whose knowledge states a "단체 이용료". This outranks the general list of
    word kinds, and like every word kind it is asked only where the form of the question leaves a
    role open (convention `word_kinds: where_open`).
    """
    seen = {}
    named = {s: ptext[slice(*o['copy'])] for s, p, o in pgraph['edges'] if p == 'value' and isinstance(o, dict) and 'copy' in o}
    for node in pgraph['nodes']:
        if node['id'] in named:
            row = seen.setdefault(named[node['id']], {})
            row[node['type']] = row.get(node['type'], 0) + 1
    if not seen:
        return model
    kinds = dict(model['tables'].get('word_kind', {}))
    for word, row in seen.items():
        kinds[word] = {kind: {'n': n, 'origins': ['the knowledge uses "%s" as a %s' % (word, kind)]} for kind, n in sorted(row.items())}
    return dict(model, tables=dict(model['tables'], word_kind=kinds))


def _decided_by_knowledge(pgraph, ptext, question, model, q, passage_result, aliases):
    """The reader could not choose between readings of the question. The knowledge is asked.

    Each reading whose every piece was seen in the lessons and that passes over no word is tried:
    the knowledge is asked as if it were the reading. If the readings that are answered all give the
    same answer, that answer is returned with status "assumed", with every reading tried and how it
    went. If they give different answers, or none is answered, nothing is returned and the question
    stays held: the knowledge does not decide between two things it can both answer.
    """
    tried, answered, seen = [], [], set()
    for reading in q.get('readings', []):
        mark = json.dumps(reading['graph'], ensure_ascii=False, sort_keys=True)
        if not reading.get('supported') or reading.get('ignored') or mark in seen:
            continue
        seen.add(mark)
        as_read = dict(q, status='complete', graphs=[reading['graph']], ignored=[], variants=reading.get('variants', []),
                       told=reading.get('told', []))
        result = _answer_read(pgraph, ptext, question, model, as_read, _blank(passage_result, as_read),
                              passage_result, None, aliases)
        meaning = '; '.join(line[2:] for line in _facts(reading['graph'], question))
        ok = result['status'] == 'answered'
        tried.append({'meaning': meaning, 'result': 'the knowledge answers that way' if ok
                      else 'the knowledge has no answer that way: ' + result['reason']})
        if ok:
            answered.append(result)
    if len(tried) < 2 or not answered:
        return None
    first = answered[0]
    if any(r['answers'] != first['answers'] or (r['claim'] or {}).get('holds') != (first['claim'] or {}).get('holds')
           for r in answered[1:]):
        return None
    first.update(status='assumed', verified=False, assumed=[{'readings': tried, 'reader_said': q['reason']}],
                 reason=first['reason'] + '; the reader could not choose between readings, the knowledge answered one way only')
    return first


def _one_reading(pgraph, ptext, question, model, q, passage_result, aliases):
    """A word's role is open and nothing says what kind of word it is: try each reading against the knowledge.

    For one open word, each role the form allows is tried: the word is taken as the kind of thing
    that fills the role, the question is read again, and the knowledge is asked. A reading counts
    only if every word of the question is read and the knowledge answers it, which it can do only
    where it uses that word in that role itself. Exactly one such reading: that answer is returned
    with status "assumed" and with what was assumed. None, or more than one: nothing is returned
    and the question is put to the user as before. Nothing is stored here.
    """
    if len(q['open_roles']) != 1:
        return None
    item = q['open_roles'][0]
    tables = model['tables']
    open_kinds = {kind for row in tables.get('value_type', {}).values() for kind in row}
    tried, answered = [], []
    for role in item['between']:
        for kind in sorted(open_kinds & set(tables.get('fills', {}).get(role, {}))):
            row = {kind: {'n': 1, 'origins': ['assumed for this question']}}
            trial = dict(model, tables=dict(tables, word_kind=dict(tables.get('word_kind', {}), **{item['piece']: row})))
            reading = R.read(question, trial)
            if reading['status'] != 'complete' or reading.get('ignored'):
                tried.append({'role': role, 'kind': kind, 'result': 'the question is not read that way: ' + reading['reason']})
                continue
            result = _answer_read(pgraph, ptext, question, trial, reading, _blank(passage_result, reading),
                                  passage_result, None, aliases)
            if result['status'] != 'answered':
                tried.append({'role': role, 'kind': kind, 'result': 'the knowledge has no answer that way: ' + result['reason']})
                continue
            tried.append({'role': role, 'kind': kind, 'result': 'the knowledge answers that way'})
            answered.append((role, kind, result))
    if len(answered) != 1:
        return None
    role, kind, result = answered[0]
    result.update(status='assumed', verified=False, asked=q['open_roles'],
                  assumed=[{'word': item['piece'], 'head': item['head'], 'role': role, 'kind': kind, 'tried': tried}],
                  reason=result['reason'] + '; one word was read by assumption')
    return result


def _known_facts(pgraph, ptext, slot):
    """The plain facts of the knowledge: one thing, one property, one value, with what else was said of it."""
    names = {n['id']: sorted(M._value(pgraph, ptext, n['id'])) for n in pgraph['nodes']}
    heads = {}
    for (s, p, o), spans in zip(pgraph['edges'], pgraph['edge_spans']):
        if p == 'value':
            continue
        row = heads.setdefault(s, {'property': None, 'parts': {}, 'spans': [], 'plain': True})
        row['spans'] += [list(x) for x in spans]
        if isinstance(o, dict):
            if p == slot['attribute'] and 'literal' in o:
                row['property'] = o['literal']
        elif len(names.get(o, [])) == 1:
            row['parts'].setdefault(p, []).append(names[o][0])
        else:
            row['plain'] = False                       # a part that is itself a relation, or has no single name
    inside = {o for s, p, o in pgraph['edges'] if isinstance(o, str) and o in heads}
    out = []
    for h, row in heads.items():
        parts = row['parts']
        if h not in inside and row['plain'] and row['property'] and len(parts.get(slot['subject_role'], [])) == 1 \
                and len(parts.get(slot['value_role'], [])) == 1 and all(len(v) == 1 for v in parts.values()):
            others = {r: v[0] for r, v in parts.items() if r not in (slot['subject_role'], slot['value_role'])}
            out.append({'thing': parts[slot['subject_role']][0], 'property': row['property'],
                        'value': parts[slot['value_role']][0], 'with': others, 'spans': sorted(map(tuple, row['spans']))})
    return out


def _unit(value):
    """What a value is counted in: the letters after its last digit ("12명" -> "명"), if any."""
    for i in range(len(value) - 1, -1, -1):
        if value[i].isdigit():
            return value[i + 1:]
    return ''


def _shares(a, b, least=2):
    """Do two words share a run of at least `least` characters ("관리하는" and "관리처", "요일마다" and "매주화요일")?"""
    return any(a[i:i + least] in b for i in range(len(a) - least + 1))


def word_ends(tables):
    """What the language pack has that may follow a word: its connectors, and the endings of its fixed words."""
    marks = sorted({g.strip() for g in tables.get('gap', {}).get('mid', {}) if g.strip()}, key=len, reverse=True)
    return marks, set(tables.get('closed_ending', {}).get(R.ANY, {}))


def _anchor(pgraph, ptext, question, model, memory, aliases, passage_result, q):
    """The question was not read. Which fact of the knowledge does it ask about?

    The knowledge is finite, so the question can be put to it the other way round: the things, the
    property words and the circumstances it names are looked up among what is known, and so is what
    its question word asks for (a counter, "몇 명", asks for a value counted in 명; a question word
    asks for the property it asked for in questions that were read and answered before). Two
    property words in a row are a chain: the first fact's value is the thing of the second.

    Finding one fact that fits is not understanding the question. Every piece of the question that
    was not recognised has to be accounted for: a connector or a closing piece the lessons have, or
    a word that was said before when this very property was asked for and the user said yes
    (learn.note_said). Then the value is given with status "assumed". With any other piece left,
    nothing is answered: the result is a hold with a `proposal` (what it was taken to ask, the
    pieces not accounted for, and the value to give if the user says yes).

    Not done at all when the question checks a claim or states a value the knowledge has, when it
    names a circumstance the fact does not have, or when an unread word is marked as a noun of the
    sentence. Returns a result, or None to leave the question as it was.
    """
    slot = model.get('field_slot')
    if not slot or pgraph is None:
        return None
    tables, conventions = model['tables'], R.recipe_of(model)[1]
    facts = _known_facts(pgraph, ptext, slot)
    if not facts:
        return None
    asking = [w for w, row in tables.get('closed', {}).items() if any(json.loads(label).get('project') for label in row)]
    fixed = [w for w in tables.get('closed', {}) if w not in asking] + list(tables.get('closed_stem', {}))
    if any(unicodedata.normalize('NFD', w) in unicodedata.normalize('NFD', question) for w in fixed):
        return None                                    # a check or a denial: the value in it has to be read, not guessed
    things = {f['thing'] for f in facts} | set(aliases or {})
    props = {}
    for surface in model.get('field_words', []):
        for label in tables['head'].get(surface, {}):
            props[surface] = dict(json.loads(label)['literals']).get(slot['attribute'])
    # Words known as a circumstance or a time. A word known only as a thing or a value (the knowledge's own
    # names and values are in that table too) is not one.
    plain_kinds = set(tables.get('fills', {}).get(slot['subject_role'], {})) | set(tables.get('fills', {}).get(slot['value_role'], {}))
    circumstances = {v for f in facts for v in f['with'].values()}         | {w for w, row in tables.get('word_kind', {}).items() if set(row) - plain_kinds}
    # Longest known word first; a place of the question belongs to one word only.
    stated_values = {f['value'] for f in facts} - things - circumstances
    taken, found = [False] * len(question), {'thing': [], 'property': [], 'circumstance': [], 'asks': [], 'stated': []}
    for kind, words in (('thing', things), ('property', props), ('circumstance', circumstances), ('asks', asking),
                        ('stated', stated_values)):
        for word in sorted(words, key=lambda w: (-len(w), w)):
            start = question.find(word)
            while start >= 0:
                if not any(taken[start:start + len(word)]):
                    taken[start:start + len(word)] = [True] * len(word)
                    found[kind].append((start, word))
                start = question.find(word, start + 1)
    named = {(aliases or {}).get(t, t) for _, t in found['thing']}
    counter = conventions.get('counter_question_word')
    units = set()
    at = question.find(counter) if counter else -1
    while at >= 0:
        # Every place the counter stands: "몇 시에 열어서 몇 시에 닫아요". The counter and its unit are read.
        after = at + len(counter)
        while after < len(question) and question[after] == ' ':
            after += 1
        for u in sorted({_unit(f['value']) for f in facts} - {''}, key=len, reverse=True):
            if question.startswith(u, after) and not any(taken[at:after + len(u)]):
                units.add(u)
                taken[at:after + len(u)] = [True] * (after + len(u) - at)
                break
        at = question.find(counter, at + 1)
    asks = [w for _, w in found['asks']]
    wanted = []
    for _, w in sorted(found['property']):
        if props[w] not in wanted:
            wanted.append(props[w])                    # in the order the question says them
    stated = sorted({w for _, w in found['stated']})
    if len(named) != 1 or len(wanted) > 2 or len(stated) > 1:
        return None
    thing = next(iter(named))
    # What was not recognised, piece by piece.
    marks, endings = word_ends(tables)
    basic = model.get('basic')
    hear = model.get('hear')                           # a trial: something outside that puts the properties in order
    # Words no lesson knows, where the explanation of a property places them (relate.placed).
    placed = RL.placed(basic, question, model.get('field_explained_words', {}), model.get('places')) if basic and basic.get('shape') else {}
    # Ways of asking the field listed per property (relate.asked): the wording as a whole, and its words.
    exact = None
    # What a user answered before, when this very way of asking was put to them (learn.note_wording).
    way = RL.wording(question, [w for _, w in found['thing']])
    told = [e for e in (memory or {}).get('wordings', []) if RL.same_wording(e['wording'], way)]
    yes, no = sorted({e['property'] for e in told if e['yes']}), {e['property'] for e in told if not e['yes']}
    confirmed = yes[0] if len(yes) == 1 and not stated else None
    by_user = False
    table = _asked_table(model, basic, memory) if basic and basic.get('shape') else None
    if table:
        exact, listed = RL.heard(basic, question, table, [w for _, w in found['thing']])
        for prop, row in listed.items():
            for word, how in row.items():
                placed.setdefault(prop, {}).setdefault(word, how)
    pieces_known = set(marks) | {g.strip().rstrip('?.!') for g in tables.get('gap', {}).get('end', {})} \
        | {g.strip().rstrip('?.!') for g in model.get('alias', {})}
    unread, pos, tokens = [], 0, question.split()
    for n, token in enumerate(tokens):
        start = question.index(token, pos)
        pos = start + len(token)
        left = ''.join(ch for k, ch in enumerate(token) if not taken[start + k]).strip('?.!,')
        if not left:
            continue
        bare = token.rstrip('?.!,')
        # An unknown word marked as a noun may be the property or a thing. The last word of a sentence is
        # its predicate, whatever it ends in ("들어가?"): the language puts the predicate last.
        if n < len(tokens) - 1 and not any(taken[start:start + len(token)]) \
                and any(bare.endswith(m) and len(bare) > len(m) for m in marks) \
                and not (basic and B.lookup(basic, bare, marks, endings)) and not hear and not confirmed \
                and not any(bare in row for row in placed.values()):   # a taught word, or one that was placed, is not an unknown noun
            return None
        unread.append(left)
    # A name or a property word of the field is known: only a word left whole is placed.
    placed = {p: {w: v for w, v in row.items() if w in unread or w in asks} for p, row in placed.items()}
    weak = False
    if confirmed and not wanted and not units:
        # A user said yes when this way of asking was put to them as a question about this property.
        # The same way of asking, of this thing or another, is now answered: it was told, not worked out.
        wanted, by_user = [confirmed], True
    if not wanted and not units:
        # No property word and no counter. A word that was not read may still point at a property: it shares
        # letters with a property word ("관리하는", 관리처) or with the value a fact of this thing has
        # ("요일마다", 매주화요일). This is a pointer, not a reading: it can only lead to a proposal.
        for piece in unread:
            if len(piece) < 2:
                continue
            for surface, prop in sorted(props.items()):
                if _shares(piece, surface) and prop not in wanted:
                    wanted.append(prop)
            for f in facts:
                if f['thing'] == thing and _shares(piece, f['value']) and f['property'] not in wanted:
                    wanted.append(f['property'])
        weak = bool(wanted)
        if len(wanted) > 2:
            # Shared letters point at three properties or more ("신고해야" next to 신고횟수, 신고기간,
            # 신고기한): they say nothing. With taught words or listed ways of asking, those decide;
            # without them there is nothing else to ask.
            if not basic:
                return None
            wanted, weak = [], False
    said = {(aliases or {}).get(c, c) for _, c in found['circumstance']}
    history = {e['property'] for e in (memory or {}).get('asks', []) if e['word'] in asks}
    worked = []
    if hear and not (wanted or units or history):
        # The trial: the question as a whole is put next to the words of every property by a model from
        # outside, and the properties come back nearest first. Chosen by nearness, not read and not
        # worked out: the nearest one is put to the user with every piece that was not read.
        left = [x for x in unread if x not in pieces_known]
        worked = [{'property': p, 'met': [], 'unmet': left, 'score': s, 'placed': {}} for p, s in hear(question, model.get('field_texts', {}))]
        if not worked:
            return None
    elif exact and not (wanted or units or history):
        # The question is, word for word, a way of asking the field listed for one property.
        worked = [{'property': exact, 'met': [x for x in unread if x not in pieces_known], 'unmet': [], 'placed': {}, 'exact': True}]
    elif basic and not (wanted or units or history):
        # Nothing in the question points at a property by form. Taught basic words may: the pieces that
        # were not read are put next to the plain-words explanation of every property (basic.ranked), and
        # the properties come back in order of how many pieces they meet. Worked out, not read: it can
        # only lead to a proposal or to candidates in that order.
        worked = B.ranked(basic, [x for x in unread if x not in pieces_known and x not in basic['marks']] + asks,
                          dict({p: [] for p in placed}, **model.get('field_explained', {})), marks, endings, placed)
        if not worked:
            return None
    if not (wanted or asks or units or worked):
        return None
    sure = not weak                                    # may it be answered, if every piece is accounted for?
    if len(wanted) == 2:
        # A chain: the first property's value is the thing the second property is asked of.
        first = [f for f in facts if f['thing'] == thing and f['property'] == wanted[0] and not f['with']]
        if len(first) != 1 or said:
            return None
        fits = [dict(f, spans=sorted(set(first[0]['spans']) | set(f['spans'])), through=first[0]['value'])
                for f in facts if f['thing'] == first[0]['value'] and f['property'] == wanted[1] and not f['with']]
        how = 'two property words, joined through "%s"' % first[0]['value']
        understood_thing = '%s (the %s of %s)' % (first[0]['value'], wanted[0], thing)
    else:
        fits = [f for f in facts if f['thing'] == thing and set(f['with'].values()) == said]
        understood_thing = thing
        if wanted:
            fits = [f for f in fits if f['property'] == wanted[0]]
            how = 'letters an unread word shares with a property word or a value' if weak \
                else 'a way of asking a user confirmed for this property' if by_user else 'the property word'
        elif units:
            fits = [f for f in fits if _unit(f['value']) in units]
            how = 'the counter "%s %s"' % (counter, '/'.join(sorted(units)))
        elif worked:
            order = [row['property'] for row in worked]
            fits = sorted((f for f in fits if f['property'] in order), key=lambda f: order.index(f['property']))
            whole = [f for f in fits if not worked[order.index(f['property'])]['unmet']]
            if len(whole) == 1:
                fits = whole                           # the one property that leaves no piece over
            sure = False
            how = 'taught basic words that meet the explanation of the property'
            rows = [worked[order.index(f['property'])] for f in fits]
            by_asking = lambda row: any(v[0] == 'asked' for v in row['placed'].values())
            ahead = lambda row: (len(row['met']), sum(v[2] for v in row['placed'].values()))
            if rows and rows[0].get('exact'):
                how = 'a way of asking the field listed for the property, word for word'
            elif rows and by_asking(rows[0]):
                how = 'words of the ways of asking the field listed for the property'
                if len(rows) > 1 and ahead(rows[0]) > ahead(rows[1]):
                    fits = fits[:1]                    # the first in order is the one put to the user; no number says it is right
            if hear and fits:
                scores = [worked[order.index(f['property'])]['score'] for f in fits]
                how = 'nearness by a vector model (%.2f%s)' % (scores[0], ', next %.2f' % scores[1] if len(scores) > 1 else '')
                fits = fits[:1]
        elif history:
            # What a question word may ask for is not narrowed by what happens to be known of this thing.
            fits = [f for f in fits if f['property'] in history]
            sure = len(history) == 1
            how = 'what "%s" asked for in questions read before%s' % (
                '", "'.join(asks), '' if sure else ' (it asked for %s)' % ', '.join(sorted(history)))
        else:
            return None                                # a question word with nothing known of what it asks for
    fits = [f for f in fits if f['property'] not in no]    # a user said no to this for this very way of asking
    if not fits:
        return None
    out = _blank(passage_result, q)
    recognised = sorted({w for kind in found.values() for _, w in kind}) + ['%s %s' % (counter, u) for u in sorted(units)]
    if len(fits) > 1:
        out['candidates'] = [{'thing': f['thing'], 'property': f['property'], 'with': f['with']} for f in fits]
        if worked:
            # In order, the one most pieces meet first, with what it would give and what speaks for it.
            for c, f in zip(out['candidates'], fits):
                row = worked[order.index(f['property'])]
                c.update(if_confirmed=f['value'], met=row['met'], unmet=row['unmet'], **({'placed': row['placed']} if row.get('placed') else {}))
        out['reason'] = 'the question was not read; it names "%s", and the knowledge has %d facts it could be asking for: %s' % (
            thing, len(fits), '; '.join('%s of %s' % (f['property'], f['thing']) for f in fits))
        return out
    fact = fits[0]
    if basic and not by_user and B.kinds_clash(B.asked_kinds(basic, question), B.value_kinds(basic, fact['value'])):
        # The one fact left is not of the kind the question word asks for ("몇 번" next to a date): the
        # question is about something the knowledge does not have of this thing. The kind never
        # chooses a fact and never takes one from several; it only stops this one from being put forward.
        out['reason'] = ('the question was not read; the one fact that fits what was recognised (%s of %s) is not of the kind '
                         'its question word asks for' % (fact['property'], understood_thing))
        return out
    heard = {w for e in (memory or {}).get('said', []) if e['property'] == fact['property'] for w in e['words']}
    open_pieces = worked[order.index(fact['property'])]['unmet'] if worked         else [x for x in unread if x not in pieces_known and x not in heard]
    understood = {'thing': understood_thing, 'property': fact['property'], 'with': fact['with']}
    if by_user:
        open_pieces = []
    item = {'understood': understood, 'recognised': recognised, 'unread': unread, 'chosen_by': how,
            'not_accounted_for': open_pieces, 'wording': way}
    if worked and worked[order.index(fact['property'])].get('placed'):
        # Said with the proposal: which word was taken for which, and that it is a guess by place or shape.
        item['placed'] = {w: dict({'how': h, 'as': o}, **({'number': n} if n else {})) for w, (h, o, n) in worked[order.index(fact['property'])]['placed'].items()}
    evidence = [{'span': list(sp), 'text': ptext[sp[0]:sp[1]]} for sp in fact['spans']]
    claim = None
    if stated:
        # The question states a value the knowledge has: it asks whether that is the value, whatever its ending.
        if not found['property'] or len(wanted) != 1:
            return None
        claim = {'claimed': stated[0], 'holds': stated[0] == fact['value']}
        item['claim'] = claim
    if open_pieces or not sure:
        # One fact fits what was recognised, but pieces of the question are not accounted for, and one of
        # them may be what changes the answer. Not answered: put to the user.
        why = ('these pieces are not accounted for: %s' % ', '.join('"%s"' % x for x in open_pieces)) if open_pieces \
            else 'it was chosen by nearness, not read' if hear and worked             else 'it was worked out from taught basic words, not read' if worked \
            else 'the question word has asked for more than one property'
        out['proposal'] = dict(item, if_confirmed=fact['value'], evidence=evidence,
                               ask='Did you ask %s the %s of %s%s%s? (%s)' % (
                                   'whether' if claim else 'for', fact['property'], understood_thing,
                                   ''.join(', %s: %s' % kv for kv in sorted(fact['with'].items())),
                                   ' is %s' % claim['claimed'] if claim else '', why))
        out['reason'] = 'the question was not read; one fact fits what was recognised, but ' + why
        return out
    out.update(status='assumed', answers=[[fact['value']]], verified=False, match={'proofs': []}, claim=claim,
               executor_detail='the question was not read, so there is no question graph to check',
               evidence=evidence, assumed=[item],
               reason='the question was not read; one fact of the knowledge fits it, and every piece of it is accounted for')
    return out


def confirm(result, memory, by, at):
    """The user said yes to a proposal. Returns the answer, and keeps the wording: the pieces that were
    not accounted for are, from now on, pieces said when this property is asked for."""
    proposal = result.get('proposal')
    if not proposal:
        raise ValueError('there is no proposal to confirm')
    L.note_said(memory, proposal['understood']['property'], proposal['not_accounted_for'], by, at)
    if proposal.get('wording'):
        L.note_wording(memory, proposal['wording'], proposal['understood']['property'], True, by, at)
    out = dict(result, status='assumed', answers=[[proposal['if_confirmed']]], verified=False, match={'proofs': []},
               claim=proposal.get('claim'),
               evidence=proposal['evidence'], assumed=[dict(proposal, confirmed_by=by)],
               reason='the question was not read; the user confirmed what it asks for')
    out.pop('proposal')
    return out


def decline(result, memory, by, at):
    """The user said no to a proposal. Nothing is answered; this way of asking is not put to a user as
    a question about this property again."""
    proposal = result.get('proposal')
    if not proposal:
        raise ValueError('there is no proposal to decline')
    if proposal.get('wording'):
        L.note_wording(memory, proposal['wording'], proposal['understood']['property'], False, by, at)
    out = dict(result, reason='the question was not read; the user said it does not ask for what was proposed')
    out.pop('proposal')
    return out


def _answer_read(pgraph, ptext, question, model, q, out, passage_result, memory, aliases):
    """Everything after the question was read completely: match, checks, the answer as a sentence."""
    conventions = R.recipe_of(model)[1]
    query, claimed = q['graphs'][0], None
    if not query['project']:
        turned = _claim_query(query, question, conventions['claim_predicate'])
        if not turned:
            out['reason'] = 'the question does not ask for anything the reader recognises'
            return out
        query, claimed = turned
    found = M.match(pgraph, ptext, query, question, aliases=aliases, rules=conventions['name_matching'],
                    unasked_parts=conventions.get('unasked_parts'), name_joins=conventions.get('name_joins'))
    out['match'], out['query'] = found, query
    if found['status'] != 'answered':
        out['reason'] = found['reason']
        return out
    out['raw_text_variants'] = sorted(set(q.get('variants', [])) | set((passage_result or {}).get('variants', [])))
    told = {x['word']: x for x in q.get('told', []) + (passage_result or {}).get('told', [])}
    out['told_words'] = [told[w] for w in sorted(told)]
    if memory is not None and told:
        L.record_use(memory, sorted(told), question)
    for text in q.get('ignored', []):
        out['partial'].append('words in the question were ignored: "%s"' % text)
    out['other_names'] = ['"%s" is another name for "%s" (word pack)' % (n['asked'], n['matched'])
                          for n in found['notes'] if n.get('alias')]
    for note in found['notes']:
        if note.get('alias'):
            continue
        if note['level'] == 1:
            out['partial'].append('"%s" was taken as "%s" (spacing differs)' % (note['asked'], note['matched']))
        else:
            out['partial'].append('"%s" was taken as "%s"; the words "%s" in front of it were ignored'
                                  % (note['asked'], note['matched'], note['ignored']))
    spans = sorted({tuple(s) for proof in found['proofs'] for fact in proof['facts'] for s in fact['spans']})
    out['evidence'] = [{'span': list(s), 'text': ptext[s[0]:s[1]]} for s in spans]
    passed_over = q.get('ignored') or [n for n in found['notes'] if n['level'] == 2]
    if passed_over and conventions.get('partial_answers') == 'withhold':
        # Words of the question were passed over, and they may be the ones that change the answer
        # ("주말 운영시간" read as "운영시간"). The pack says such an answer is not given.
        out['reason'] = 'the question could only be answered by passing over part of it: ' + '; '.join(out['partial'])
        out['withheld'] = found['answers']
        return out
    if found.get('joined_by'):
        out['joined_by'] = found['joined_by']       # two sentences of the knowledge joined through these names
        check = {'state': 'not comparable',
                 'detail': 'two facts were joined through a name (%s), which the older executor cannot do'
                           % ', '.join(found['joined_by'])}
    elif found.get('set_aside'):
        # Other facts fit the words of the question and have a part it does not state (a weekend fee beside
        # the plain fee). They were set aside; the older executor has no such rule and would give them too.
        check = {'state': 'not comparable',
                 'detail': '%d fact(s) with a part the question does not state were set aside, which the older '
                           'executor cannot do' % found['set_aside']}
    elif found['relaxed'] == 0 and not out['other_names']:
        # A name the question wrote once for two heads is checked the way it was matched: once per place.
        check = _second_opinion(pgraph, ptext, found.get('as_matched') or query, question, found['answers'],
                                conventions['executor_search_stops'])
    else:
        # The older executor compares names exactly, so it has nothing to say about a loose match.
        check = {'state': 'not comparable',
                 'detail': 'names were matched loosely or through another name, which the older executor cannot do'}
    out['executor'], out['executor_detail'] = check['state'], check['detail']
    out['verified'] = check['state'] == 'agrees' and not out['partial'] and not out['told_words']
    if check['state'] in ('disagrees', 'refuses'):
        # The second method finished and did not confirm: that is a hold, never an answer.
        out['reason'] = 'the second answer method %s: %s' % (check['state'], check['detail'])
        out['withheld'] = found['answers']
        return out
    if claimed is not None:
        known = {''.join(v.split()) for n in pgraph['nodes'] for v in M._value(pgraph, ptext, n['id'])} | set(aliases or {})
        holds = _claim_holds(claimed, found['answers'], known)
        if holds is None:
            # Saying no is an answer too. What stands in front of the claim word was not read as one
            # value, so it is neither confirmed nor denied.
            out['reason'] = 'the question states "%s", which was not read as one value: it is neither confirmed nor denied' % claimed
            out['withheld'] = found['answers']
            return out
        out['claim'] = {'claimed': claimed, 'holds': holds}
    # The answer as a full sentence: the question's meaning with the answer put in, written from
    # the same counts and kept only if the reader reads it back as that meaning.
    heads = {s for s, p, o in query['edges'] if isinstance(o, dict) and 'literal' in o}
    if conventions.get('unasked_parts') == 'block' and any(isinstance(o, str) and o in heads for s, p, o in query['edges']):
        # One relation under another (a condition, a chain): the writer puts the answer into one clause and
        # would state the condition as a fact. No sentence is written; the value and its grounds are the answer.
        out['sentences'] = []
    else:
        out['sentences'] = W.answer_sentences(model, query, question, found['answers'], found['notes'])
    if memory is not None and claimed is None and len(query['project']) == 1:
        asked = query['project'][0]
        anchors = {n['id']: n.get('anchor') for n in query['nodes']}
        for s_, p_, o_ in query['edges']:
            if o_ == asked and anchors.get(asked):
                kinds = [o2['literal'] for s2, p2, o2 in query['edges'] if s2 == s_ and isinstance(o2, dict) and 'literal' in o2]
                if len(kinds) == 1:
                    L.note_ask(memory, question[slice(*anchors[asked])], kinds[0], question)
    out.update(status='answered', answers=found['answers'],
               reason=found['reason'] + ('' if out['verified'] else '; not independently verified')
               + ('; partial reading' if out['partial'] else ''))
    return out


def _second_opinion(pgraph, ptext, qgraph, qtext, answers, search_stops):
    """Ask the older executor. Its own refusals count as refusals, not as silence.

    agrees      it finished with the same answers
    disagrees   it finished with different answers, or found nothing
    refuses     it stopped for a safety reason of its own
    unavailable it ran out of search budget, so nothing was checked

    The executor's own stop is classified first and is final. A separate search is
    consulted only to tell a budget stop from other holds, and only when the executor
    itself stopped inside a search; it can never turn a refusal into "unavailable".
    """
    result = native.run_pair(pgraph, ptext, qgraph, qtext, [])
    if 'actual' in result:
        if result.get('provenance_gaps') or result.get('ungrounded'):
            return {'state': 'refuses', 'detail': 'its evidence is incomplete'}
        same = result['actual'] == answers
        return {'state': 'agrees' if same else 'disagrees',
                'detail': 'same answers' if same else 'it answered %s' % result['actual']}
    reason = str(result.get('reason'))
    if result.get('status') == 'no_evidence':
        return {'state': 'disagrees', 'detail': 'it found no match'}
    if reason not in search_stops or result.get('status') != 'hold':
        return {'state': 'refuses', 'detail': reason}
    if str(result.get('detail', '')).endswith('_limit'):
        return {'state': 'unavailable', 'detail': 'search budget reached (%s)' % result['detail']}
    try:
        reading, program = native.compile_pair(pgraph, ptext, qgraph, qtext)
        raw = execute_query_graph(reading, program)
    except (KeyError, TypeError, ValueError) as error:
        return {'state': 'refuses', 'detail': str(error)}
    if raw.get('status') == 'hold' and str(raw.get('reason')).endswith('_limit'):
        return {'state': 'unavailable', 'detail': 'search budget reached (%s)' % raw['reason']}
    return {'state': 'refuses', 'detail': reason}


# ---------------------------------------------------------------- report

def _obj(graph, text, value):
    if isinstance(value, dict):
        return '"%s"' % value['literal'] if 'literal' in value else '"%s"' % text[slice(*value['copy'])]
    node = next(n for n in graph['nodes'] if n['id'] == value)
    named = [text[slice(*o['copy'])] for s, p, o in graph['edges'] if s == value and p == 'value']
    if named:
        return '"%s"' % named[0]
    return 'the thing asked for' if value in graph['project'] else '"%s"' % text[slice(*node['anchor'])]


def _facts(graph, text):
    lines = []
    for node in graph['nodes']:
        edges = [(p, o) for s, p, o in graph['edges'] if s == node['id'] and p != 'value']
        if edges:
            parts = ', '.join('%s = %s' % (p, _obj(graph, text, o)) for p, o in edges)
            lines.append('- %s "%s": %s' % (node['type'], text[slice(*node['anchor'])], parts))
    return lines


def _pieces(reading):
    names = {'gap': 'connector', 'value': 'name', 'head': 'fixed word', 'closed': 'fixed word', 'skip': 'IGNORED'}
    return ' '.join('[%s|%s]' % (p['text'], names[p['kind']]) for p in reading['pieces'] if p['text'])


def _plain(decision):
    """Show a stored label in words instead of raw JSON."""
    try:
        value = json.loads(decision)
    except (TypeError, ValueError):
        return str(decision).strip() or '(none)'
    if isinstance(value, dict):
        parts = [value.get('type', '')] + ['%s=%s' % (p, v) for p, v in value.get('literals', [])]
        if value.get('project'):
            parts.append('asked for')
        return ', '.join(x for x in parts if x)
    if isinstance(value, list):
        return ' + '.join(map(str, value)) or '(none)'
    return str(value)


def _sources(term):
    """Training example ids behind a count, plus the word forms a stem or ending came from."""
    ids = ', '.join(term['origins'][:3]) or '-'
    forms = term.get('forms') or []
    return ids + (' (from word forms %s)' % ', '.join(forms[:4]) if forms else '')


def _decisions(reading):
    rows, unused, routine = [], [], 0
    for t in reading['terms']:
        if t['what'] == 'known piece left unused':
            unused.append(t)
            continue
        if t['what'] in ('known piece used as structure', 'what follows this piece') or \
                t['what'].startswith('connecting piece'):
            routine += 1
            if t['count'] > 0:
                continue
        rows.append('| %s | %s | %s | %s | %d of %d | %s |' % (
            t['piece'].strip() or '(none)', t['what'], _plain(t['decision']),
            _plain(t['given']) if t['given'].startswith('{') else repr(t['given']), t['count'], t['of'], _sources(t)))
    lines = ['| Piece | Decision about | Chosen | Given | Seen in training | Example ids |',
             '|---|---|---|---|---|---|'] + rows
    lines.append('')
    longer = sorted({t['piece'] for t in reading['terms'] if t.get('graded') and t['count'] == 0})
    if longer:
        lines.append('Names of a length not seen in training: %s. This is allowed; it lowers the score and does '
                     'not block the reading.' % ', '.join('"%s"' % x for x in longer))
    lines.append('%d routine sequence checks also passed (each connector and what follows it was seen before).'
                 % routine)
    risky = [t for t in unused if t['count'] == 0]
    if unused:
        lines.append('%d known pieces occur in the text without being used as structure; %d of those were '
                     'never left unused in training%s.' % (len(unused), len(risky),
                     ': ' + ', '.join(sorted({repr(t['piece']) for t in risky})) if risky else ''))
    return lines


def _reading_section(title, result, text):
    lines = ['## ' + title, '', 'Text: `%s`' % text, '', 'Status: **%s** (%s).' % (result['status'], result['reason']), '']
    if not result['readings']:
        return lines + ['No way was found to cut this text into pieces seen in training.', '']
    chosen = result['readings'][result.get('chosen', 0)]
    lines += ['Pieces: ' + _pieces(chosen), '', 'What it means:'] + _facts(chosen['graph'], text) + ['']
    if chosen['graph']['project']:
        asked = [p for s, p, o in chosen['graph']['edges'] if o in chosen['graph']['project']]
        lines += ['Asked for: the ' + ' and '.join(asked) + ' of that event.', '']
    if chosen.get('merged'):
        lines += ['A name that appears twice was treated as one person, as training showed.', '']
    lines += ['Why each piece was read this way:', ''] + _decisions(chosen) + ['']
    rivals = [r for r in result['readings'] if r is not chosen]
    lines.append('Score %.2f, every piece seen in training: %s.' % (chosen['score'], 'yes' if chosen['supported'] else 'no'))
    if result.get('margin') is None:
        lines.append('No other reading has every piece seen in training, so there is no lead to report.')
    else:
        lines.append('Lead over the next fully seen reading: %.2f (required %.2f).' % (result['margin'], result['required_margin']))
    if result.get('unseen_lead') is not None and result['unseen_lead'] > 0:
        lines.append('A reading with an unseen piece scores %.2f higher than the chosen one.' % result['unseen_lead'])
    if result.get('cut_between_equals'):
        lines.append('The search dropped at least one candidate that scored the same as one it kept.')
    for rival in rivals[:2]:
        weak = sorted((t for t in rival['terms'] if t['count'] == 0), key=lambda t: t['log'])[:2]
        why = '; '.join('%s %r' % (t['what'], t['piece']) for t in weak) or 'lower counts for the same pieces'
        lines.append('- Rival (score %.2f): %s. Rejected because: %s.' % (rival['score'], _pieces(rival), why))
    return lines + ['']


def explain(passage, question, result):
    """A full plain-text account of how the answer was reached, or why none was given."""
    answered = result['status'] in ('answered', 'assumed')
    if answered:
        shown = '; '.join(', '.join(row) for row in result['answers'])
        if result['claim']:
            said = result['claim']['claimed']
            shown = ('Yes, %s' % shown) if result['claim']['holds'] else 'No. The passage says %s, not %s' % (shown, said)
        flags = (['partial reading'] if result['partial'] else []) + (['uses raw-text variants'] if result['raw_text_variants'] else []) \
            + (['uses words told in conversation'] if result['told_words'] else []) + ([] if result['verified'] else ['not independently verified']) \
            + (['UNDER AN ASSUMPTION, see the end'] if result['status'] == 'assumed' else [])
        head = ['# Answer: %s%s' % (shown, ' (%s)' % '; '.join(flags) if flags else ''), '']
        said = [x for x in result['sentences'] if x['status'] == 'said']
        if said:
            head += ['## Answer as a sentence', ''] + ['> ' + x['text'] for x in said] + ['']
            head += ['Each sentence was built from pieces seen in the lessons and then read back by the reader, '
                     'which had to arrive at the same meaning. How the first one was built:', '',
                     '| Piece | Why it was chosen |', '|---|---|']
            head += ['| %s | %s |' % (x['piece'].strip() or '(none)', x['why']) for x in said[0]['steps']] + ['']
        for x in result['sentences']:
            if x['status'] != 'said':
                head += ['No sentence was written for %s: %s.' % (', '.join(x['answer']), x['reason']), '']
        if result['told_words']:
            head += ['Read with words told in conversation, not taught by a lesson:', '']
            head += ['- "%s": %s, confirmed by %s' % (x['word'], x['status'], ', '.join(x['confirmed_by']))
                     for x in result['told_words']] + ['']
        if result['other_names']:
            head += ['Names matched through the word pack:', ''] + ['- ' + x for x in result['other_names']] + ['']
        if result['raw_text_variants']:
            head += ['Read with help from raw text, not from a lesson:', '']
            head += ['- ' + note for note in result['raw_text_variants']] + ['']
        if result['partial']:
            head += ['**Partial reading.** This answer rests on the following, which training does not back:', '']
            head += ['- ' + note for note in result['partial']] + ['']
    else:
        head = ['# No answer given', '', 'Reason: %s.' % result['reason'], '']
        if result.get('unknown_words'):
            head += ['## Unknown word', '',
                     'Not known to the reader: %s.' % ', '.join('"%s"' % w for w in result['unknown_words']), '',
                     'It was not read as a name, because the question would then ask for nothing. Nothing was '
                     'guessed about its meaning. Telling the reader what it means (a lesson, or a confirmed '
                     'answer to "is this a name or a question word?") would let this question be read.', '']
            if result.get('proposals'):
                head += ['Question to put to the user:', ''] + ['- ' + x['ask'] for x in result['proposals']] + ['']
        if result.get('withheld'):
            head += ['The matcher found %s, with passage text %s, but the answer was withheld.' % (
                '; '.join(', '.join(row) for row in result['withheld']),
                ', '.join('"%s"' % e['text'] for e in result['evidence'])), '']
    head += ['Question: `%s`' % question, '', 'Passage: `%s`' % passage, '']
    if answered:
        head += ['## Why this answer', '',
                 'The question was turned into a small graph with one unknown. The passage graph was searched '
                 'for a place where every condition of the question holds. The unknown there is the answer.', '']
        for n, proof in enumerate(result['match']['proofs'], 1):
            head += ['Ground %d for the answer %s, each condition and the passage text that satisfies it:'
                     % (n, ', '.join(proof['answer'])), '',
                     '| Condition in the question | Passage text |', '|---|---|']
            for fact in proof['facts']:
                s, p, o = fact['condition']
                if p == 'answer name':
                    label = 'the name of what was asked for'
                elif p == 'value':
                    label = 'a name given in the question: %s' % _obj(result['query'], question, o)
                else:
                    label = '%s = %s' % (p, _obj(result['query'], question, o))
                head.append('| %s | %s |' % (label, ' + '.join('"%s"' % t for t in fact['text'])))
            head.append('')
        if result['claim']:
            head += ['This was a yes/no question. It was answered by looking up the value and comparing it with '
                     'the claimed "%s".' % result['claim']['claimed'], '']
        if result['verified']:
            head += ['Verified: the older executor reached the same answer independently.', '']
        elif result['executor'] == 'agrees':
            head += ['The older executor reached the same answer, but the reading was partial, so this is not '
                     'counted as verified.', '']
        else:
            head += ['**Not independently verified.** The older executor could not check this answer: %s.'
                     % result['executor_detail'], '']
    body = _reading_section('How the passage was read', result['passage'], passage)
    body += _reading_section('How the question was read', result['question'], question)
    tail = ['## Method', '',
            '- Reading uses integer counts from training examples only. No neural network, embedding or token prediction.',
            '- A reading is accepted only if every piece was seen in training and it leads clearly.',
            '- The answer comes from matching the question graph against the passage graph; nothing is generated.',
            '- If a passage event fits the question but does not name what was asked for, no answer is given.', '']
    for item in [x for x in result.get('assumed', []) if 'understood' in x]:
        u = item['understood']
        tail += ['## How the question was understood', '',
                 'The question was not read as a sentence. It was taken to ask for the %s of "%s"%s.'
                 % (u['property'], u['thing'], ''.join(' (%s: %s)' % kv for kv in sorted(u['with'].items()))),
                 '- recognised: %s' % ', '.join('"%s"' % w for w in item['recognised']),
                 '- chosen by: %s' % item['chosen_by'],
                 '- not read: %s' % (', '.join('"%s"' % w for w in item['unread']) or 'nothing'),
                 '', 'If this is not what was asked, say so: the answer above is withdrawn.', '']
    for item in [x for x in result.get('assumed', []) if 'readings' in x]:
        tail += ['## How the question was understood', '',
                 'The reader could not choose between readings (%s). Each was put to the knowledge:' % item['reader_said'], '']
        tail += ['- %s: %s' % (t['meaning'], t['result']) for t in item['readings']]
        tail += ['', 'If the question meant something else, say so: the answer above is withdrawn.', '']
    for item in [x for x in result.get('assumed', []) if 'understood' not in x and 'readings' not in x]:
        tail += ['## How the question was understood', '',
                 '"%s" is a word no lesson, list or pack knows. In this sentence its connector lets it be: %s.'
                 % (item['word'], ' or '.join(sorted({t['role'] for t in item['tried']}))),
                 'It was read as the %s of "%s" (a %s). Each reading was tried against the knowledge:'
                 % (item['role'], item['head'], item['kind']), '']
        tail += ['- as %s (a %s): %s' % (t['role'], t['kind'], t['result']) for t in item['tried']]
        tail += ['', 'If this is wrong, say what "%s" is: the answer above is withdrawn and the word is kept as told.'
                 % item['word'], '']
    return '\n'.join(head + body + tail)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', help='teacher examples to build the model from')
    parser.add_argument('--model', help='a model file written earlier with --save-model')
    parser.add_argument('--save-model')
    parser.add_argument('--passage', required=True)
    parser.add_argument('--question', required=True)
    args = parser.parse_args()
    if args.model:
        model = json.loads(Path(args.model).read_text(encoding='utf8'))
    else:
        model = R.build(json.loads(Path(args.train).read_text(encoding='utf8'))['examples'])
    if args.save_model:
        Path(args.save_model).write_text(json.dumps(model, ensure_ascii=False) + '\n', encoding='utf8')
    print(explain(args.passage, args.question, answer(args.passage, args.question, model)))


if __name__ == '__main__':
    main()
