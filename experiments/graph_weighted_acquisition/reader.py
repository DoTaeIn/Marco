"""Piece-level, edge-scoring reader.

No sentence templates. A text is cut into pieces that were each seen in
training (connecting strings, fixed words, stem+ending words) plus free values.
Every argument then chooses a head and a role, scored by integer counts of what
that piece did in training. The best whole reading wins only with a clear,
fully observed lead; every count used is kept so the reading can be explained.

Nothing here is a neural network, an embedding or a token predictor. The model
is a JSON file of counts with the ids of the training examples behind them.
"""
import itertools
import json
import math
import unicodedata
from pathlib import Path

from experiments.graph_example_acquisition import native
from . import merge as M
from . import weights as W

SCHEMA = 'graph-piece-reader-v1'
DEFAULT_POLICY = {'alpha': [1, 2], 'margin_ratio': 3, 'beam': 16, 'max_value_chars': 40, 'max_whole_chars': 200, 'max_skip_chars': 20,
                  'max_assignments': 5000, 'origins_kept': 5}
ANY = '*'
RECIPE_FILE = Path(__file__).resolve().parent / 'data' / 'reading_recipe.json'


def default_recipe():
    """The recipe and conventions shipped as data. Copied into a language pack when it is built."""
    return json.loads(RECIPE_FILE.read_text(encoding='utf8'))


def recipe_of(model):
    """(recipe, conventions) of a pack; a pack built before recipes were data uses the shipped file."""
    if 'recipe' in model and 'conventions' in model:
        return model['recipe'], model['conventions']
    data = default_recipe()
    return data['recipe'], data['conventions']


def key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


# ---------------------------------------------------------------- building

def _covered(cue, start, structure):
    """Every character lies in text already read as structure (connectors and fixed words).

    Such an occurrence is explained by the pieces around it; only one that reaches into a
    free value is a piece left over.
    """
    return all(any(a <= i < b for a, b in structure) for i in range(start, start + len(cue)))


def occurrences(text, cue):
    out, pos = [], text.find(cue)
    while pos >= 0:
        out.append(pos)
        pos = text.find(cue, pos + 1)
    return out


def last_part(word):
    """The last part of the last character, by Unicode decomposition (for 한 that is ㄴ, for 하 it is ㅏ)."""
    import unicodedata
    return unicodedata.normalize('NFD', word[-1:])[-1:] if word else ''


def part_class(word):
    """What kind of part a word ends in, as Unicode itself names it (e.g. a final or a middle part)."""
    import unicodedata
    part = last_part(word)
    name = unicodedata.name(part, '').split(' ') if part else []
    return ' '.join(name[:2]) if len(name) > 2 else (unicodedata.category(part) if part else '')


def sentence_kind(graph, conventions):
    """What a sentence does, by the first rule of the pack's `sentence_kinds` that holds."""
    for rule in conventions['sentence_kinds']:
        when = rule.get('when', {})
        if 'has_predicate' in when and not any(p == when['has_predicate'] for _, p, _ in graph['edges']):
            continue
        if when.get('asks_for_something') and not graph['project']:
            continue
        return rule['kind']
    raise ValueError('no sentence kind applies')


def _gap_bounds(mentions, text, i):
    start = 0 if i == 0 else mentions[i - 1][0][1]
    end = len(text) if i == len(mentions) else mentions[i][0][0]
    return start, end


def _ref(span, mentions, text, arg, head):
    """Describe an evidence span relative to an argument and its head."""
    span = tuple(span)
    for name, index in (('ARG', arg), ('HEAD', head)):
        if index is None:
            continue
        if span == tuple(mentions[index][0]):
            return [name]
        for side, gap in (('LEFT', index), ('RIGHT', index + 1)):
            start, end = _gap_bounds(mentions, text, gap)
            if start <= span[0] and span[1] <= end and start < end:
                return [name + '_' + side, text[start:end], span[0] - start, span[1] - start]
    return None


def build(examples, policy=None, variants=None, kinds=None):
    """Count pieces over the lessons. `variants` (from variants.py) adds raw-text connector variants.
    `kinds` (a word-kinds file) lists which kind of thing some words name."""
    policy = dict(DEFAULT_POLICY, **(policy or {}))
    shipped = default_recipe()
    kept = policy['origins_kept']
    tables, cues, skipped = {}, {}, []

    def count(table, cue, label, origin, forms=()):
        """One more observation. `origin` is a training example id, or a list of them."""
        cell = tables.setdefault(table, {}).setdefault(cue, {}).setdefault(label, {'n': 0, 'origins': []})
        cell['n'] += 1
        for one in origin if isinstance(origin, list) else [origin]:
            if one not in cell['origins'] and len(cell['origins']) < kept:
                cell['origins'].append(one)
        for form in forms:
            if form not in cell.setdefault('forms', []):
                cell['forms'].append(form)

    def cue_count(cue, name, origin):
        cell = cues.setdefault(cue, {}).setdefault(name, {'n': 0, 'origins': []})
        cell['n'] += 1
        if origin not in cell['origins'] and len(cell['origins']) < kept:
            cell['origins'].append(origin)

    head_surfaces, texts, parts_seen, closed_surfaces = {}, [], {}, {}
    for kind, group in sorted((kinds or {}).get('kinds', {}).items()):
        for word in group['words']:
            count('word_kind', word, kind, 'word kinds: ' + kind)
    for ex in examples:
        try:
            graph, text, origin = ex['graph'], ex['text'], ex['id']
            mentions, gaps = W._segments(graph, text)
            opened = W._open_ids(graph)
            heads = {s for s, p, o in graph['edges'] if isinstance(o, str)}
            index_of = {}
            for i, (span, node, _) in enumerate(mentions):
                index_of.setdefault(node['id'], []).append(i)
            head_order = [i for i, (_, node, _) in enumerate(mentions) if node['id'] in heads]
            rows, used, kinds, structure = [], [], [], []
            for i, (span, node, _) in enumerate(mentions):
                surface = text[slice(*span)]
                kinds.append('head' if node['id'] in heads else 'value' if node['id'] in opened else 'closed')
                if kinds[-1] != 'value':
                    used.append((surface, span[0]))
                    structure.append(tuple(span))
                if node['id'] in heads:
                    literals = sorted([p, o['literal']] for s, p, o in graph['edges']
                                      if s == node['id'] and isinstance(o, dict) and 'literal' in o)
                    entry = key({'type': node['type'], 'literals': literals})
                    rows.append(('head', surface, entry, origin))
                    seen_in = head_surfaces.setdefault(entry, {}).setdefault(surface, [])
                    if origin not in seen_in and len(seen_in) < kept:
                        seen_in.append(origin)
                elif node['id'] in opened:
                    rows.append(('value_type', gaps[i + 1], node['type'], origin))
                    rows.append(('value_length', ANY, str(len(surface)), origin))
                else:
                    entry = key({'type': node['type'], 'project': node['id'] in graph['project']})
                    rows.append(('closed', surface, entry, origin))
                    if node['id'] not in graph['project']:
                        # A fixed word that does not ask (it checks, it denies) is a word that takes endings.
                        seen_in = closed_surfaces.setdefault(entry, {}).setdefault(surface, [])
                        if origin not in seen_in and len(seen_in) < kept:
                            seen_in.append(origin)
            for i, gap in enumerate(gaps):
                where = 'start' if i == 0 else 'end' if i == len(gaps) - 1 else 'mid'
                rows.append(('gap', where, gap, origin))
                rows.append(('gap_after', kinds[i - 1] if i else 'start', gap, origin))
                if i:
                    rows.append(('gap_after_type', mentions[i - 1][1]['type'], gap, origin))
                    # Which connector follows a word ending in this sound (last part of its last character).
                    rows.append(('gap_after_part', last_part(text[slice(*mentions[i - 1][0])]), gap, origin))
                    rows.append(('gap_after_part_class', part_class(text[slice(*mentions[i - 1][0])]), gap, origin))
                if i < len(kinds):
                    rows.append(('kind_after', gap, kinds[i], origin))
                structure.append(_gap_bounds(mentions, text, i))
                if gap.strip():
                    start = _gap_bounds(mentions, text, i)[0]
                    # The connector is counted with its spaces: '가 ' is a piece, the letter inside a name is not.
                    used.append((gap, start))
            frames = {i: [] for i in head_order}
            # A head may stand under another head ("X의 P의 Q", "…이면 …"). What marks its role is the
            # connector around its whole phrase: the head with everything under it.
            below = {}
            for s_, p_, o_ in graph['edges']:
                if s_ in heads and isinstance(o_, str):
                    below.setdefault(index_of[s_][0], []).append(index_of[o_][0])

            def phrase(i, seen=()):
                found = [i]
                for k in below.get(i, []):
                    if k not in seen:
                        found += phrase(k, seen + (i,))
                return found

            nested = {k for h_, under in below.items() for k in under if k in head_order}
            # One part under two heads ("X는 P가 V이면 Q가 W이다": X is the subject of both). It is an ordinary
            # part of the head nearer to it; for the other head it is shared through whatever joins the two.
            shared_edges, heads_of = {}, {}
            for s_, p_, o_ in graph['edges']:
                if s_ in heads and isinstance(o_, str) and o_ not in heads:
                    heads_of.setdefault(o_, set()).add(s_)
            for o_, over in heads_of.items():
                if len(over) > 1:
                    near = min(over, key=lambda x: (abs(index_of[x][0] - index_of[o_][0]), index_of[x][0]))
                    for x in over - {near}:
                        joined = [p_ for s_, p_, t_ in graph['edges'] if (s_, t_) in ((x, near), (near, x))]
                        if len(joined) != 1:
                            raise ValueError('a part under two heads that are not joined to each other')
                        shared_edges[(x, o_)] = joined[0]
            for h_ in head_order:
                rows.append(('stands', gaps[max(phrase(h_)) + 1], 'under' if h_ in nested else 'alone', origin))
            for (s, p, o), evidence in zip(graph['edges'], graph['edge_spans']):
                if s not in heads:
                    if p == 'value':
                        refs = [_ref(e, mentions, text, index_of[s][0], None) for e in evidence]
                        if None in refs:
                            raise ValueError('value evidence outside the mention')
                        rows.append(('evidence', 'value', key(refs), origin))
                    continue
                h = index_of[s][0]
                if isinstance(o, dict):
                    refs = [_ref(e, mentions, text, None, h) for e in evidence]
                    if None in refs:
                        raise ValueError('literal evidence outside the head')
                    rows.append(('evidence', 'literal:' + p, key(refs), origin))
                    continue
                places = index_of[o]
                if len(places) > 1:
                    places = [i for i in places if list(mentions[i][0]) in evidence] or places[:1]
                a = places[0]
                refs = [_ref(e, mentions, text, a, h) for e in evidence]
                if None in refs:
                    raise ValueError('role evidence outside argument and head')
                if (s, o) in shared_edges:
                    rows += [('share', shared_edges[(s, o)], p, origin), ('evidence', 'role:' + p, key(refs), origin)]
                    frames[h].append(p)
                    continue
                offset = head_order.index(h) - sum(1 for j in head_order if j < a)
                reach = phrase(a) if a in head_order else [a]
                rows += [('attach', ANY, str(offset), origin), ('role_right', gaps[max(reach) + 1], p, origin),
                         ('role_left', gaps[min(reach)], p, origin), ('evidence', 'role:' + p, key(refs), origin),
                         # Which type of thing filled this role: a node's type has to agree with its role.
                         ('fills', p, mentions[a][1]['type'], origin),
                         # On which side of its head the role was written.
                         ('side', p, 'before' if a < h else 'after', origin)]
                if mentions[a][1]['id'] not in opened:
                    rows.append(('role_surface', text[slice(*mentions[a][0])], p, origin))
                frames[h].append(p)
            for h in head_order:
                # The order in which a head and its arguments are written.
                places = sorted([(index_of[o][0] if len(index_of[o]) == 1 else
                                  ([i for i in index_of[o] if list(mentions[i][0]) in ev] or index_of[o])[0], p)
                                 for (s_, p, o), ev in zip(graph['edges'], graph['edge_spans'])
                                 if s_ == mentions[h][1]['id'] and isinstance(o, str)] + [(h, 'HEAD')])
                written = [name for _, name in places]
                rows.append(('order', key([mentions[h][1]['type'], sorted(x for x in written if x != 'HEAD')]),
                             key(written), origin))
            for h, roles in frames.items():
                span, node, _ = mentions[h]
                literals = sorted([p, o['literal']] for s, p, o in graph['edges']
                                  if s == node['id'] and isinstance(o, dict) and 'literal' in o)
                rows.append(('frame', key({'type': node['type'], 'literals': literals}), key(sorted(roles)), origin))
                parts_seen.setdefault(key({'type': node['type'], 'literals': literals}), []).append((set(roles), origin))
                rows.append(('repeat_role', ANY, 'yes' if len(set(roles)) < len(roles) else 'no', origin))
            # What this sentence does: asks for something, checks a claim, or states.
            does = sentence_kind(graph, shipped['conventions'])
            rows.append(('closes', gaps[-1], does, origin))
            for h in head_order:
                rows.append(('head_in', text[slice(*mentions[h][0])], does, origin))
            for row in rows:
                count(*row)
            texts.append((text, set(used), origin, structure))
        except (ValueError, KeyError, TypeError) as error:
            skipped.append({'example': ex.get('id'), 'reason': str(error)})
    # Part by part: how often a head had each role, and how often it stood without it. A set of
    # roles need not have been seen as a whole; each part is judged on its own.
    for entry, seen in parts_seen.items():
        every = set().union(*(roles for roles, _ in seen))
        for roles, origin in seen:
            for role in sorted(every):
                count('part', entry, ('+' if role in roles else '-') + role, origin)
    # Stem + ending: two fixed words with the same meaning that share a beginning.
    for entry, surfaces in head_surfaces.items():
        for a, b in itertools.combinations(sorted(surfaces), 2):
            n = 0
            while n < min(len(a), len(b)) and a[n] == b[n]:
                n += 1
            if 0 < n < len(a) and n < len(b):
                # Origins are the training examples the two word forms came from.
                count('stem', a[:n], entry, surfaces[a] + surfaces[b], forms=(a, b))
                count('ending', ANY, a[n:], surfaces[a], forms=(a,))
                count('ending', ANY, b[n:], surfaces[b], forms=(b,))
    # A fixed word that ends in a learned ending shares its beginning with unseen forms.
    for entry, surfaces in head_surfaces.items():
        for surface in sorted(surfaces):
            for ending in list(tables.get('ending', {}).get(ANY, {})):
                stem = surface[:len(surface) - len(ending)]
                if stem and surface.endswith(ending) and entry not in tables.get('stem', {}).get(stem, {}):
                    count('stem', stem, entry, surfaces[surface], forms=(surface,))
    # The same for fixed words that take endings, compared letter by letter: Korean writes a stem's
    # last sound and an ending's first sound into one character (아니 + ㅂ니다 = 아닙니다), so the
    # word forms are compared in Unicode's decomposed form. A stem does not stop on the first
    # letter of a syllable. Knowledge of the writing system, like the use of a word's last sound.
    for entry, surfaces in closed_surfaces.items():
        for a, b in itertools.combinations(sorted(surfaces), 2):
            x, y = unicodedata.normalize('NFD', a), unicodedata.normalize('NFD', b)
            n = 0
            while n < min(len(x), len(y)) and x[n] == y[n]:
                n += 1
            while n and '\u1100' <= x[n - 1] <= '\u115f':
                n -= 1
            if 0 < n < len(x) and n < len(y):
                count('closed_stem', x[:n], entry, surfaces[a] + surfaces[b], forms=(a, b))
                count('closed_ending', ANY, x[n:], surfaces[a], forms=(a,))
                count('closed_ending', ANY, y[n:], surfaces[b], forms=(b,))
    # Every place a known piece occurs in training text: was it used as structure or not?
    known = {cue for _, used, _, _ in texts for cue, _ in used}
    for text, used, origin, structure in texts:
        for cue in sorted(known):
            for start in occurrences(text, cue):
                if (cue, start) in used:
                    cue_count(cue, 'used', origin)
                elif not _covered(cue, start, structure):
                    cue_count(cue, 'unused', origin)
    return {'schema': SCHEMA, 'policy': policy, 'examples': len(examples) - len(skipped), 'tables': tables,
            'cues': cues, 'identity': M.identity_counts(examples), 'skipped': skipped,
            'alias': _aliases(tables, variants), 'recipe': shipped['recipe'], 'conventions': shipped['conventions']}


def _aliases(tables, variants):
    """Connectors the lessons never showed, but whose variant they did.

    A taught connector such as '은 ' begins with a form that raw text pairs with another
    ('는'). The untaught connector '는 ' is then read with the counts of '은 '. Nothing is
    added when the lessons already contain the other form.
    """
    from . import variants as V
    table, known, out = V.lookup(variants), set(), {}
    for group in tables.get('gap', {}).values():
        known |= set(group)
    for gap in sorted(known):
        form = gap.split()[0] if gap.split() and not gap[0].isspace() else ''
        if form in table and gap.startswith(form):
            other, pair = table[form]
            new = other + gap[len(form):]
            if new not in known:
                out[new] = {'of': gap, 'forms': [other, form], 'per_thousand': pair['same_following_per_thousand'],
                            'next_best_per_thousand': pair['next_best_per_thousand'],
                            'examples_following': pair['examples_following'][:5]}
    return out


# ---------------------------------------------------------------- scoring

class _Scorer:
    def __init__(self, model):
        self.model = model
        num, den = model['policy']['alpha']
        self.alpha = num / den
        self._lengths = {}
        self.alias = model.get('alias', {})
        self.recipe, self.conventions = recipe_of(model)

    def rule(self, rule, ctx, section=None):
        """Apply one recipe rule to a context. Returns a term, or None when the rule does not apply."""
        if rule.get('special') == 'length':
            return self.length_term(ctx['surface'])
        if rule.get('needs') and ctx.get(rule['needs']) is None:
            return None
        cue = ANY if rule['given'] == ANY else ctx[rule['given']]
        if rule.get('only_if_known') and not self.row(rule['table'], cue):
            return None
        shown = rule['shown'].format(**ctx) if 'shown' in rule else None
        term = self.term(rule['what'].format(**ctx), ctx[rule['piece']], rule['table'], cue, ctx[rule['label']], shown)
        if rule.get('marks'):
            term[rule['marks']] = ctx[rule['marks']]
        if section:
            term['section'] = section
        return term

    def leaves_open(self, connector):
        """Does the connector written after a word leave its role open? It does when free values were
        seen in more than one role in front of it. Where it does not ("…이다.", "…의 ", "…에 "), the form
        has said what the word is there, and what is known about the word is not asked."""
        kinds = {kind for row in self.model['tables'].get('value_type', {}).values() for kind in row}
        fills = self.model['tables'].get('fills', {})
        return sum(1 for role, cell in self.row('role_right', connector).items()
                   if cell['n'] > 0 and kinds & set(fills.get(role, {}))) > 1

    def rules(self, rules, ctx, section=None):
        return [t for t in (self.rule(r, ctx, section) for r in rules) if t is not None]

    def canon(self, gap):
        """The taught connector whose counts stand in for this one."""
        return self.alias[gap]['of'] if gap in self.alias else gap

    def variant_term(self, gap):
        info = self.alias[gap]
        return {'what': 'connector read as a variant found in raw text', 'piece': gap,
                'decision': 'same as "%s"' % info['of'].strip(), 'given': 'raw text', 'count': info['per_thousand'],
                'of': 1000, 'origins': [], 'forms': [], 'alternatives': [], 'backoff': True,
                'log': math.log(info['per_thousand'] / 1000),
                'evidence': 'both are followed by the same words, e.g. ' + ', '.join(info['examples_following'])}

    def row(self, table, cue):
        return self.model['tables'].get(table, {}).get(cue, {})

    def term(self, what, piece, table, cue, label, shown=None):
        row = self.row(table, cue)
        seen = row.get(label, {}).get('n', 0)
        total = sum(c['n'] for c in row.values())
        value = math.log((seen + self.alpha) / (total + self.alpha * (len(row) + 1)))
        others = sorted(((c['n'], other) for other, c in row.items() if other != label), reverse=True)[:3]
        return {'what': what, 'piece': piece, 'decision': shown if shown is not None else label, 'given': cue,
                'table': table,
                'count': seen, 'of': total, 'origins': row.get(label, {}).get('origins', []),
                'forms': row.get(label, {}).get('forms', []), 'learned': row.get(label, {}).get('learned'),
                'log': value,
                'alternatives': [{'decision': other, 'count': n} for n, other in others]}

    def length_term(self, surface):
        """How likely a free value is to be this long, read from the lengths seen in training.

        A value is modelled as continuing or stopping at each character. Up to the longest
        length seen, the stop rate at each length is counted directly; past it, the overall
        stop rate per character is used. So an unseen length is allowed but costs more the
        longer it is. This term grades a reading; it never marks it as unseen.
        """
        length = len(surface)
        if length not in self._lengths:
            row = {int(k): c['n'] for k, c in self.row('value_length', ANY).items()}
            total, chars, longest = sum(row.values()), sum(k * n for k, n in row.items()), max(row, default=0)
            pooled = (total + self.alpha) / (chars + 2 * self.alpha)
            value = 0.0
            for k in range(1, length + 1):
                reached = sum(n for size, n in row.items() if size >= k)
                stop = (row.get(k, 0) + self.alpha) / (reached + 2 * self.alpha) if k <= longest else pooled
                value += math.log(stop if k == length else 1 - stop)
            self._lengths[length] = (value, row.get(length, 0), total, longest)
        value, seen, total, longest = self._lengths[length]
        cell = self.row('value_length', ANY).get(str(length), {})
        return {'what': 'length of a free value', 'piece': surface, 'decision': '%d characters' % length,
                'given': 'longest seen in training: %d' % longest, 'count': seen, 'of': total,
                'origins': cell.get('origins', []), 'forms': [], 'log': value, 'alternatives': [], 'graded': True}

    def skip_term(self, ignored):
        """Cost of passing over unknown text. No count stands behind it, by definition."""
        seen = max(1, self.model.get('examples', 1))
        return {'what': 'unknown text ignored', 'piece': ignored, 'decision': 'ignored', 'given': '',
                'count': 0, 'of': 0, 'origins': [], 'forms': [], 'alternatives': [], 'partial': True,
                'log': math.log(self.alpha / (seen + self.alpha)) - 0.1 * len(ignored)}

    def cue_term(self, cue, used):
        row = self.model['cues'].get(cue, {})
        a, b = row.get('used', {}).get('n', 0), row.get('unused', {}).get('n', 0)
        seen = a if used else b
        name = 'used' if used else 'unused'
        return {'what': 'known piece used as structure' if used else 'known piece left unused',
                'piece': cue, 'decision': name, 'given': cue, 'count': seen, 'of': a + b,
                'log': math.log((seen + self.alpha) / (a + b + 2 * self.alpha)),
                'origins': row.get(name, {}).get('origins', []),
                'alternatives': [{'decision': 'unused' if used else 'used', 'count': b if used else a}]}


# ---------------------------------------------------------------- tiling

def _stripped(text, start, end):
    """The non-blank part of a connecting string and where it starts."""
    gap = text[start:end]
    return (gap if gap.strip() else ''), start


def _tilings(text, model, scorer):
    """Best ways to cut the text into known pieces and free values."""
    tables, policy = model['tables'], model['policy']
    gaps = tables.get('gap', {})
    beam, n = policy['beam'], len(text)
    mid = [g for g in gaps.get('mid', {}) if g]
    mid += [g for g, info in scorer.alias.items() if info['of'] in mid]
    ends = list(gaps.get('end', {}))
    stems, endings = tables.get('stem', {}), tables.get('ending', {}).get(ANY, {})
    closed_stems, closed_endings = tables.get('closed_stem', {}), tables.get('closed_ending', {}).get(ANY, {})
    letter_at, letter_text, char_at = [], '', {}
    if closed_stems:
        # The text letter by letter, with where each character starts in it and back.
        for i, ch in enumerate(text):
            char_at[len(letter_text)] = i
            letter_at.append(len(letter_text))
            letter_text += unicodedata.normalize('NFD', ch)
        char_at[len(letter_text)] = len(text)

    def gain(cue):
        """How much better it is to use a known piece than to leave it unused."""
        if not cue or cue not in model['cues']:
            return 0.0
        return scorer.cue_term(cue, True)['log'] - scorer.cue_term(cue, False)['log']

    def gap_score(prev, gap, nxt):
        actual, gap = gap, scorer.canon(gap)
        value = gain(gap if gap.strip() else '') + scorer.term('', gap, 'gap_after', prev, gap)['log']
        if actual != gap:
            value += scorer.variant_term(actual)['log']
        if nxt:
            value += scorer.term('', nxt, 'kind_after', gap, nxt)['log']
        return value

    def skip_cost(length):
        return scorer.skip_term('x' * length)['log']

    def boundary(pos):
        return any(text.startswith(g, pos) for g in mid) or any(text[pos:] == g for g in ends)

    def mentions_at(pos):
        out = []
        for surface in tables.get('head', {}):
            if text.startswith(surface, pos):
                out.append((gain(surface), ('head', pos, pos + len(surface), 'word')))
        for stem in stems:
            if text.startswith(stem, pos):
                for ending in endings:
                    end = pos + len(stem) + len(ending)
                    if text.startswith(ending, pos + len(stem)) and text[pos:end] not in tables.get('head', {}):
                        out.append((0.0, ('head', pos, end, 'stem:' + stem)))
        for surface in tables.get('closed', {}):
            if text.startswith(surface, pos):
                out.append((gain(surface), ('closed', pos, pos + len(surface), 'word')))
        for stem in closed_stems:
            # A fixed word's stem with an ending learned from any such word; the word ends on a character.
            if letter_text.startswith(stem, letter_at[pos]):
                for ending in closed_endings:
                    stop = char_at.get(letter_at[pos] + len(stem) + len(ending))
                    if stop is not None and letter_text.startswith(ending, letter_at[pos] + len(stem)) \
                            and text[pos:stop] not in tables.get('closed', {}):
                        out.append((0.0, ('closed', pos, stop, 'stem:' + stem)))
        for end in range(pos + 1, min(n, pos + policy['max_value_chars']) + 1):
            if boundary(end):
                # A free value pays for its length, so swallowing a clause is never free.
                cost = scorer.length_term(text[pos:end])['log']
                out.append((cost, ('value', pos, end, 'value')))
        return out

    memo, cut = {}, [False]

    def cut_check(found):
        # Dropping a candidate that scores the same as one that is kept is an arbitrary pick.
        if len(found) > beam and abs(found[beam][0] - found[beam - 1][0]) < 1e-9:
            cut[0] = True

    def after_mention(pos, prev):
        if (pos, prev) in memo:
            return memo[pos, prev]
        found = []
        for gap in ends:
            if text[pos:] == gap:
                found.append((gap_score(prev, gap, None), (('gap', pos, n, 'end'),)))
        for gap in mid:
            if text.startswith(gap, pos):
                here = pos + len(gap)
                for score, piece in mentions_at(here):
                    for rest_score, rest in after_mention(piece[2], piece[0]):
                        found.append((gap_score(prev, gap, piece[0]) + score + rest_score,
                                      (('gap', pos, here, 'mid'), piece) + rest))
                # Unknown words standing before a fixed word may be passed over. This is never
                # free and never counts as seen: a reading that needs it is a partial reading.
                for stop in range(here + 1, min(n, here + policy.get('max_skip_chars', 20)) + 1):
                    if not text[stop - 1].isspace() or text[here:stop].isspace():
                        continue
                    for score, piece in mentions_at(stop):
                        if piece[0] == 'value':
                            continue
                        for rest_score, rest in after_mention(piece[2], piece[0]):
                            found.append((gap_score(prev, gap, piece[0]) + skip_cost(stop - here) + score + rest_score,
                                          (('gap', pos, here, 'mid'), ('skip', here, stop, 'ignored'), piece) + rest))
        found.sort(key=lambda item: (-item[0], item[1]))
        cut_check(found)
        memo[pos, prev] = found[:beam]
        return memo[pos, prev]

    out = []
    for gap in gaps.get('start', {}):
        if text.startswith(gap):
            for score, piece in mentions_at(len(gap)):
                for rest_score, rest in after_mention(piece[2], piece[0]):
                    out.append((gap_score('start', gap, piece[0]) + score + rest_score,
                                (('gap', 0, len(gap), 'start'), piece) + rest))
    out.sort(key=lambda item: (-item[0], item[1]))
    cut_check(out)
    return out[:beam], cut[0]


# ---------------------------------------------------------------- reading

def _resolve(refs, spans, text, arg, head, alias=None):
    """Turn a learned evidence description back into character spans."""
    out = []
    for ref in refs:
        index = arg if ref[0].startswith('ARG') else head
        if index is None:
            return None
        if len(ref) == 1:
            out.append(list(spans[index]))
            continue
        gap = index if ref[0].endswith('LEFT') else index + 1
        start = 0 if gap == 0 else spans[gap - 1][1]
        end = len(text) if gap == len(spans) else spans[gap][0]
        seen = text[start:end]
        if (alias or {}).get(seen, {}).get('of', seen) != ref[1]:
            return None
        out.append([start + ref[2], start + ref[3]])
    return out


def _evidence(model, name, spans, text, arg, head):
    """Spans for an edge from the most common learned description that fits.

    Returns (spans, tied): tied when another description that fits here was seen
    equally often and points at different text.
    """
    row = model['tables'].get('evidence', {}).get(name, {})
    fits = []
    for refs, cell in sorted(row.items(), key=lambda item: (-item[1]['n'], item[0])):
        found = _resolve(json.loads(refs), spans, text, arg, head, model.get('alias'))
        if found:
            fits.append((cell['n'], found))
    if not fits:
        return None, False
    return fits[0][1], any(n == fits[0][0] and found != fits[0][1] for n, found in fits[1:])


def _readings(text, model, scorer, tiling_score, pieces):
    policy = model['policy']
    mentions = [p for p in pieces if p[0] not in ('gap', 'skip')]
    spans = [(p[1], p[2]) for p in mentions]
    gaps = [scorer.canon(text[p[1]:p[2]]) for p in pieces if p[0] == 'gap']
    heads = [i for i, p in enumerate(mentions) if p[0] == 'head']
    if not heads:
        return []
    base, used, previous, behind = [], set(), 'start', -1
    structure = [(p[1], p[2]) for p in pieces if p[0] in ('gap', 'head', 'closed')]
    names, stated = set(model.get('field_names', ())), set(model.get('field_values', ()))
    for index, p in enumerate(pieces):
        if p[0] == 'value' and text[p[1]:p[2]] in names | stated:
            # A free value that is exactly a name or a value of the field pack explains itself and
            # whatever known piece lies inside it. A known name inside any other value is left over.
            structure.append((p[1], p[2]))
            if text[p[1]:p[2]] in names:
                used.add((text[p[1]:p[2]], p[1]))
        if p[0] == 'gap':
            actual = text[p[1]:p[2]]
            gap = scorer.canon(actual)
            if actual != gap:
                # Read through its taught variant: credit the taught connector, and say so.
                base += [scorer.variant_term(actual), scorer.cue_term(gap, True)]
            elif gap.strip():
                used.add((gap, p[1]))
            following = next((x[0] for x in pieces[index + 1:] if x[0] != 'skip'), None)
            base += scorer.rules(scorer.recipe['connector'], {'previous': previous, 'connector': gap,
                                                              'next': following, 'follows': behind})
        elif p[0] == 'skip':
            base.append(scorer.skip_term(text[p[1]:p[2]]))
        else:
            behind += 1
            previous = p[0]
            if p[0] != 'value':
                used.add((text[p[1]:p[2]], p[1]))
    for cue in model['cues']:
        for start in occurrences(text, cue):
            if (cue, start) in used:
                base.append(scorer.cue_term(cue, True))
            elif not _covered(cue, start, structure):
                base.append(scorer.cue_term(cue, False))
    # Fixed words and free values: every meaning seen in training stays a candidate, so two
    # equally common meanings end as a tie between readings and never as a silent pick.
    meanings = []
    for i, p in enumerate(mentions):
        surface = text[p[1]:p[2]]
        how = 'stem' if p[0] == 'head' and p[3] != 'word' else 'closed_stem' if p[0] == 'closed' and p[3] != 'word' else p[0]
        stem = p[3][5:] if how in ('stem', 'closed_stem') else ''
        ending = unicodedata.normalize('NFD', surface)[len(stem):] if how == 'closed_stem' else surface[len(stem):]
        if how == 'value' and 'known_kind' in scorer.recipe['meaning'] and scorer.row('word_kind', surface) \
                and (scorer.conventions.get('word_kinds') != 'where_open' or scorer.leaves_open(gaps[i + 1])):
            how = 'known_kind'                              # what is known about the word decides where the form does not
        ctx = {'surface': surface, 'stem': stem, 'ending': ending, 'right_connector': gaps[i + 1]}
        plan = scorer.recipe['meaning'][how]
        source = plan['candidates']
        labels = sorted(scorer.row(source['table'], ctx[source['given']]))
        if not labels and 'if_none' in source:
            labels = [source['if_none']]
        found = []
        for label in labels:
            meaning = {'type': label} if source.get('meaning_is') == 'type' else json.loads(label)
            found.append((meaning, scorer.rules(plan['rules'], dict(ctx, meaning=label))))
        if not found:
            return []
        meanings.append(found)
    size = 1
    for found in meanings:
        size *= len(found)
    if size > policy['max_assignments']:
        return [{'incomplete': 'too many meanings'}]
    out = []
    for combo in itertools.product(*meanings):
        entries = {i: entry for i, (entry, _) in enumerate(combo)}
        chosen = [_broaden(scorer, t, entries, mentions, text) for t in base] + [t for _, terms in combo for t in terms]
        found = _assign(text, model, scorer, pieces, mentions, spans, gaps, heads, entries, chosen)
        if found and 'incomplete' in found[0]:
            return found
        out += found
    return out


def _broaden(scorer, term, entries, mentions, text):
    """If a connector was never seen after this kind of piece, use what was seen after its type.

    "After a fixed word" is narrow: a fixed word for a person takes the connectors persons take.
    The broader count is used only when the exact one is zero, and the reading says so. Which
    count is the broader one is stated in the pack's recipe.
    """
    plan = scorer.recipe.get('connector_broader')
    at = term.get('follows', -1)
    if not plan or at < 0 or term['count'] > 0 or term['table'] != plan['when_unseen']:
        return term
    kind = entries[at]['type']
    wider = scorer.rule(plan, {'type': kind, 'connector': term['decision']})
    if wider['count'] == 0:
        return term
    word = text[mentions[at][1]:mentions[at][2]]
    return dict(wider, follows=at, fallback='"%s" after "%s": never seen after that kind of word in the lessons, '
                                           'seen %d times after a %s' % (term['piece'].strip(), word, wider['count'], kind))


def _assign(text, model, scorer, pieces, mentions, spans, gaps, heads, entries, base):
    policy = model['policy']
    # Every argument chooses a head and a role.
    args = [i for i in range(len(mentions)) if i not in heads]
    options = []
    for a in args:
        surface, left, right = text[slice(*spans[a])], gaps[a], gaps[a + 1]
        # Most specific evidence first, as the recipe orders it: a fixed word that was itself
        # seen in a role speaks for itself; a free value is read from the pieces around it.
        plan = scorer.recipe['argument']
        ctx = {'surface': surface, 'left_connector': left, 'right_connector': right, 'arg_type': entries[a]['type']}
        own = plan['own']['rules'] if mentions[a][0] == plan['own']['applies_to'] and all(
            scorer.row(r['table'], ctx[r['given']]) for r in plan['own']['rules']) else None
        deciding = own or plan['context']
        roles = set()
        for r in deciding:
            roles |= set(scorer.row(r['table'], ctx[r['given']]))
        found = []
        for rank, h in enumerate(heads):
            offset = str(rank - sum(1 for j in heads if j < a))
            for role in sorted(roles):
                terms = scorer.rules(plan['always'] + deciding, dict(ctx, role=role, head_offset=offset,
                                                                    side='before' if a < h else 'after',
                                                                    head_surface=text[slice(*spans[h])]))
                found.append((sum(t['log'] for t in terms), all(t['count'] > 0 for t in terms), h, role, terms))
        supported = [f for f in found if f[1]]
        by_kind = plan.get('by_kind')
        if not supported and by_kind and mentions[a][0] == 'value' and scorer.row(by_kind['table'], surface) \
                and (scorer.conventions.get('word_kinds') != 'where_open' or scorer.leaves_open(right)):
            # A word whose kind is listed is judged by fewer pieces around it (the recipe says which):
            # its kind already says what it is.
            for rank, h in enumerate(heads):
                offset = str(rank - sum(1 for j in heads if j < a))
                for role in sorted(roles):
                    terms = scorer.rules(plan['always'] + by_kind['rules'], dict(ctx, role=role, head_offset=offset,
                                                                                  side='before' if a < h else 'after',
                                                                                  head_surface=text[slice(*spans[h])]))
                    if all(t['count'] > 0 for t in terms):
                        supported.append((sum(t['log'] for t in terms), True, h, role, terms))
        found = supported or sorted(found, key=lambda f: -f[0])[:2]
        if not found:
            return []
        options.append(found)
    size = 1
    for found in options:
        size *= len(found)
    if size > policy['max_assignments']:
        return [{'incomplete': 'too many role assignments'}]
    repeat_seen = scorer.row('repeat_role', ANY).get('yes', {}).get('n', 0) > 0
    out = []
    for choice in itertools.product(*options):
        by_head = {h: [] for h in heads}
        for a, (_, _, h, role, _) in zip(args, choice):
            by_head[h].append((role, a))
        if not repeat_seen and any(len({r for r, _ in roles}) < len(roles) for roles in by_head.values()):
            continue
        flat = by_head
        for nest_terms, links in _nestings(text, scorer, spans, gaps, heads, entries, flat):
            by_head = {h: list(roles) for h, roles in flat.items()}
            for parent, role, child in links:
                by_head[parent].append((role, child))
            if links and not repeat_seen and any(len({r for r, _ in roles}) < len(roles) for roles in by_head.values()):
                continue
            terms = list(base) + nest_terms
            for parent, role, child in links:
                seen_shared = scorer.row('share', role)
                for lacking, having in ((parent, child), (child, parent)):
                    for r, a in list(by_head[having]):
                        if a not in heads and seen_shared.get(r, {}).get('n', 0) > 0 and r not in {x for x, _ in by_head[lacking]}:
                            # Joined this way, heads were seen sharing this part: the one without it has it too.
                            by_head[lacking].append((r, a))
                            terms.append(scorer.term('a part shared with the head it is joined to', text[slice(*spans[a])],
                                                     'share', role, r))
            for _, _, _, _, option_terms in choice:
                terms += option_terms
            for h, roles in by_head.items():
                entry = key({'type': entries[h]['type'], 'literals': entries[h].get('literals', [])})
                ctx = {'head_surface': text[slice(*spans[h])], 'head_meaning': entry, 'roles': key(sorted(r for r, _ in roles))}
                has = {r for r, _ in roles}
                for rule in scorer.recipe['head']:
                    if rule.get('each') != 'part':
                        terms += scorer.rules([rule], ctx)
                        continue
                    # One decision per part: the head has it, or stands without it.
                    known = {label[1:] for label in scorer.row(rule['table'], entry)}
                    for role in sorted(known | has):
                        terms += scorer.rules([rule], dict(ctx, part=('+' if role in has else '-') + role))
            graph, tied = _graph(text, model, mentions, spans, entries, by_head)
            if graph is None:
                continue
            if 'closes' in model['tables']:
                # A sentence closed like a question must ask or check something; one closed like a
                # statement must not. Read from what such sentences did in the lessons.
                does = sentence_kind(graph, scorer.conventions)
                for r in scorer.recipe['sentence']:
                    for word in ([text[slice(*spans[h])] for h in heads] if r.get('each') == 'head' else [None]):
                        terms += scorer.rules([r], {'closing': gaps[-1], 'does': does, 'head_surface': word}, 'sentence')
            merged = None
            try:
                merged = M.merge_graph(graph, text, model.get('identity', {}))
            except ValueError:
                pass
            graph = merged or graph
            score = sum(t['log'] for t in terms)
            supported = all(t['count'] > 0 for t in terms if not t.get('graded') and not t.get('partial'))
            ignored = [t['piece'].strip() for t in terms if t.get('partial')]
            variants = sorted({'"%s" read as "%s" (%s)' % (t['piece'].strip(), t['decision'][9:-1], t['evidence'])
                               for t in terms if t.get('backoff')})
            told = {t['learned']['word']: t['learned'] for t in terms if t.get('learned')}
            variants += sorted({t['fallback'] for t in terms if t.get('fallback')})
            out.append({'graph': graph, 'score': score, 'supported': supported, 'terms': terms, 'tied_evidence': tied,
                        'ignored': ignored, 'variants': variants, 'told': [told[w] for w in sorted(told)],
                        'pieces': [{'kind': p[0], 'text': text[p[1]:p[2]], 'span': [p[1], p[2]], 'how': p[3]}
                                   for p in pieces], 'merged': merged is not None})
    return out


def _nestings(text, scorer, spans, gaps, heads, entries, by_head):
    """Ways for heads to stand under other heads: (terms, [(parent, role, child)]) for each way.

    Used only when the pack's recipe has a `nesting` part. A head with everything under it is a
    phrase; the phrase has to be one unbroken stretch, and the connectors at its two ends decide
    its role, by the same counts that decide the role of any argument. Whether a head stands
    alone or under another one is counted from the connector that closes its phrase.
    """
    plan = scorer.recipe.get('nesting')
    if not plan or len(heads) < 2:
        yield [], []
        return
    argument = scorer.recipe['argument']
    rank = {h: i for i, h in enumerate(heads)}
    for parents in itertools.product(*[[None] + [y for y in heads if y != x] for x in heads]):
        up = dict(zip(heads, parents))
        if all(p is not None for p in parents):
            continue                                    # something has to stand on its own

        def loops(x):
            seen = set()
            while up[x] is not None:
                if x in seen:
                    return True
                seen.add(x)
                x = up[x]
            return False

        if any(loops(x) for x in heads):
            continue

        def phrase(x):
            found = [x] + [a for _, a in by_head[x]]
            for child in heads:
                if up[child] == x:
                    found += phrase(child)
            return found

        ends = {x: (min(phrase(x)), max(phrase(x)), len(phrase(x))) for x in heads}
        if any(hi - lo + 1 != size for lo, hi, size in ends.values()):
            continue                                    # a phrase is one unbroken stretch: no crossing
        terms, choices = [], []
        for x in heads:
            lo, hi, _ = ends[x]
            terms += scorer.rules(plan, {'surface': text[slice(*spans[x])], 'right_connector': gaps[hi + 1],
                                         'stands': 'alone' if up[x] is None else 'under'})
            if up[x] is None:
                continue
            ctx = {'surface': text[slice(*spans[x])], 'left_connector': gaps[lo], 'right_connector': gaps[hi + 1],
                   'arg_type': entries[x]['type'], 'head_surface': text[slice(*spans[up[x]])],
                   'side': 'before' if x < up[x] else 'after',
                   'head_offset': str(rank[up[x]] - sum(1 for j in heads if j < x))}
            roles = set()
            for r in argument['context']:
                roles |= set(scorer.row(r['table'], ctx[r['given']]))
            found = []
            for role in sorted(roles):
                role_terms = scorer.rules(argument['always'] + argument['context'], dict(ctx, role=role))
                found.append((not all(t['count'] > 0 for t in role_terms), -sum(t['log'] for t in role_terms), role, role_terms))
            found = [f for f in found if not f[0]] or sorted(found, key=lambda f: f[:3])[:1]
            if not found:
                choices = None
                break
            choices.append([(up[x], f[2], x, f[3]) for f in found])
        if choices is None:
            continue
        for picked in itertools.product(*choices):
            yield terms + [t for _, _, _, role_terms in picked for t in role_terms], [(p, r, c) for p, r, c, _ in picked]


def _graph(text, model, mentions, spans, entries, by_head):
    """Build the graph of one reading. Returns (graph, tied evidence?) or (None, False)."""
    nodes, edges, evidence, project, tied = [], [], [], [], False

    def add(edge, name, arg, head):
        nonlocal tied
        found, tie = _evidence(model, name, spans, text, arg, head)
        if not found:
            return False
        tied |= tie
        edges.append(edge)
        evidence.append(found)
        return True

    for i, p in enumerate(mentions):
        nodes.append({'id': 'm%d' % i, 'type': entries[i]['type'], 'anchor': list(spans[i])})
        if entries[i].get('project'):
            project.append('m%d' % i)
    for h, roles in by_head.items():
        for role, a in roles:
            if not add(['m%d' % h, role, 'm%d' % a], 'role:' + role, a, h):
                return None, False
        for predicate, literal in entries[h].get('literals', []):
            if not add(['m%d' % h, predicate, {'literal': literal}], 'literal:' + predicate, None, h):
                return None, False
    for i, p in enumerate(mentions):
        if p[0] == 'value' and not add(['m%d' % i, 'value', {'copy': list(spans[i])}], 'value', i, None):
            return None, False
    graph = {'nodes': nodes, 'edges': edges, 'edge_spans': evidence, 'project': project}
    try:
        native._check(graph, text)
    except ValueError:
        return None, False
    return graph, tied


def _name(graph):
    """A cheap identity for a reading. Node ids follow mention order, so no search is needed."""
    return key({'nodes': graph['nodes'], 'project': graph['project'],
                'edges': sorted(key([e, s]) for e, s in zip(graph['edges'], graph['edge_spans']))})


KEPT = 5


def _unknown_words(ranked, known_names=()):
    """Free values of the best reading whose only fault is that the sentence does the wrong thing.

    Such a reading cut the text into known pieces and names, with everything seen before,
    except that a question came out asking nothing (or a statement asking something). The
    likeliest cause is a word the reader does not know, read as a name.
    """
    for reading in ranked:
        zero = [t for t in reading['terms'] if t['count'] == 0 and not t.get('graded') and not t.get('partial')]
        if zero and all(t.get('section') == 'sentence' for t in zero) and not reading['ignored']:
            usual = sorted((n, label) for t in zero for label, n in
                           ((a['decision'], a['count']) for a in t['alternatives']))
            words = [p['text'] for p in reading['pieces'] if p['kind'] == 'value' and p['text'] not in known_names]
            if words and usual:
                return {'words': words, 'expected': usual[-1][1]}
    return None


def _shown(ranked, pick, keep=KEPT):
    """The readings kept for the report, always including the chosen one, and its index there."""
    shown = list(ranked[:keep])
    if not any(r is pick for r in shown):
        shown = shown[:keep - 1] + [pick]
    return shown, next(i for i, r in enumerate(shown) if r is pick)


def _read_one(text, model):
    """Read one stretch of text as a whole. Returns the chosen reading, its rivals and every count used."""
    if model.get('schema') != SCHEMA:
        raise ValueError('unsupported reader model')
    scorer = _Scorer(model)
    best, complete = {}, True
    tilings, cut_between_equals = _tilings(text, model, scorer)
    for tiling_score, pieces in tilings:
        for reading in _readings(text, model, scorer, tiling_score, pieces):
            if 'incomplete' in reading:
                complete = False
                continue
            name = _name(reading['graph'])
            if name not in best or reading['score'] > best[name]['score']:
                best[name] = reading
    ranked = sorted(best.values(), key=lambda r: (-r['score'], _name(r['graph'])))
    needed = math.log(model['policy']['margin_ratio'])
    result = {'text': text, 'readings': ranked[:KEPT], 'required_margin': needed, 'graphs': [], 'margin': None,
              'unseen_lead': None, 'cut_between_equals': cut_between_equals, 'ignored': [], 'variants': [],
              'unknown_words': [], 'expected': None, 'told': []}
    if not complete:
        result.update(status='hold', reason='search bound reached')
    elif not ranked:
        result.update(status='unresolved', reason='the text cannot be cut into known pieces')
    else:
        # Only a reading whose every piece was seen in training can be chosen. It must
        # lead the next such reading clearly, and no unseen-piece reading may lead it clearly.
        whole = [r for r in ranked if r['supported'] and not r['ignored']]
        partial = [r for r in ranked if r['supported'] and r['ignored']]
        # A reading that ignores text is used only when no reading explains all of it.
        seen = whole or partial
        # Whether a reading that ignores words may stand in the way of one that explains them all is
        # a convention of the pack. Before 2026-11-23 it always could.
        blocks = recipe_of(model)[1].get('partial_reading_blocks_whole', True)
        unseen = [r for r in ranked if not r['supported']] + (partial if whole and blocks else [])
        if recipe_of(model)[1].get('contradicted_reading_blocks', True) is False:
            # "Never seen" is two different things. A count of 0 of 0 is ignorance: nothing was observed
            # either way. A count of 0 of N is evidence: the lessons had N chances and never did this.
            # A reading that goes against such evidence (a known piece buried in a name, a clause
            # left standing alone after a connector that always joined it to another) has fewer
            # pieces to pay for and so scores high; it may not hold back a fully seen reading.
            unseen = [r for r in unseen if not any(t['count'] == 0 and t.get('of', 0) > 0 and not t.get('graded')
                                                   for t in r['terms'])]
        if not seen:
            result.update(status='ambiguous', reason='every reading uses something never seen in training')
            suspects = _unknown_words(ranked, model.get('known_names', []))
            if suspects:
                result.update(unknown_words=suspects['words'], expected=suspects['expected'],
                              reason='it is closed like a sentence that %s, but no known word in it does that; '
                                     'an unknown word may stand where one belongs: %s'
                                     % (suspects['expected'], ', '.join('"%s"' % w for w in suspects['words'])))
        else:
            margin = seen[0]['score'] - seen[1]['score'] if len(seen) > 1 else None
            behind = max((r['score'] for r in unseen), default=None)
            behind = None if behind is None else behind - seen[0]['score']
            result.update(margin=margin, unseen_lead=behind)
            if margin is not None and margin < needed:
                result.update(status='ambiguous', reason='equal scores for two readings' if margin < 1e-9
                              else 'two readings are too close')
            elif seen[0].get('tied_evidence'):
                result.update(status='ambiguous', reason='two equally common ways to ground a fact in the text')
            elif behind is not None and behind >= needed:
                result.update(status='ambiguous', reason='a reading with an unseen piece scores clearly higher')
            elif cut_between_equals and len(ranked) < 2:
                result.update(status='hold', reason='the search dropped a candidate that scored the same as one it kept')
            else:
                if margin is None:
                    why = 'the only reading whose every piece was seen in training'
                else:
                    why = 'leads the next fully seen reading by %.2f, required %.2f' % (margin, needed)
                if behind is not None and behind > 0:
                    why += '; a reading with an unseen piece scores %.2f higher, below the %.2f that would block' % (behind, needed)
                if seen[0]['ignored']:
                    why = 'partial reading, ignoring %s; %s' % (', '.join('"%s"' % x for x in seen[0]['ignored']), why)
                shown, at = _shown(ranked, seen[0])
                loose = _open_attachments(seen[0]['graph'], text, model) \
                    if recipe_of(model)[1].get('attachment_check') else []
                unsure = _open_roles(seen[0], text, model) if recipe_of(model)[1].get('role_check') and not loose else []
                if unsure:
                    # The connector after the word marks more than one role and nothing says what kind of
                    # word it is. Which role is meant is knowledge about the word, not form: asked.
                    result.update(status='ambiguous', readings=shown, open_roles=unsure,
                                  reason='the sentence alone does not say what %s' % '; '.join(
                                      '"%s" is: %s' % (x['piece'], ' or '.join(x['between'])) for x in unsure))
                elif loose:
                    # The counts picked a place, but the sentence itself leaves it open. Not accepted: asked.
                    result.update(status='ambiguous', readings=shown, attachment=loose,
                                  reason='the sentence alone does not say what %s' % '; '.join(
                                      '"%s" belongs to: %s' % (x['piece'], ' or '.join('"%s"' % c for c in x['between']))
                                      for x in loose))
                else:
                    result.update(status='complete', reason=why, graphs=[seen[0]['graph']], readings=shown, chosen=at,
                                  ignored=seen[0]['ignored'], variants=seen[0]['variants'], told=seen[0]['told'])
                    if recipe_of(model)[1].get('role_check') and not seen[0]['ignored']:
                        shown_kinds = _kinds_seen(seen[0], text, model)
                        if shown_kinds:
                            result['kinds_seen'] = shown_kinds
    if result['status'] != 'complete':
        result['graphs'] = [r['graph'] for r in ranked[:KEPT]] if result['status'] == 'ambiguous' else []
    return result


def _role_choices(reading, text, model):
    """For every free value of a reading whose own connector marks more than one role:
    (word, kind, head word, role read, other roles the connector allows, those the head does not have yet).

    Another role counts when the connector written after the word was seen marking it, it was seen
    written on that side of a head, and free values were seen filling it. A word whose kind is
    listed, a name or a value the field pack knows, is left out.
    """
    tables, graph = model['tables'], reading['graph']
    known = set(tables.get('word_kind', {})) | set(model.get('field_names', ())) | set(model.get('field_values', ()))
    after = {p['span'][0]: p['text'] for p in reading['pieces'] if p['kind'] == 'gap'}
    # Kinds a free value was ever read as: a role only fixed words filled (a comparison) is no choice for one.
    open_kinds = {kind for row in tables.get('value_type', {}).values() for kind in row}
    anchor = {n['id']: n['anchor'] for n in graph['nodes'] if 'anchor' in n}
    kind = {n['id']: n['type'] for n in graph['nodes']}
    free = {s for s, p, o in graph['edges'] if p == 'value' and isinstance(o, dict) and 'copy' in o}
    has = {}
    for s, p, o in graph['edges']:
        if isinstance(o, str):
            has.setdefault(s, set()).add(p)
    for s, p, o in graph['edges']:
        if not isinstance(o, str) or o not in free or o not in anchor or s not in anchor:
            continue
        word = text[slice(*anchor[o])]
        if word in known:
            continue
        gap = after.get(anchor[o][1], '')
        gap = model.get('alias', {}).get(gap, {}).get('of', gap)
        side = 'before' if anchor[o] < anchor[s] else 'after'
        others = sorted(r for r, cell in tables.get('role_right', {}).get(gap, {}).items()
                        if r != p and cell['n'] > 0
                        and open_kinds & set(tables.get('fills', {}).get(r, {}))
                        and tables.get('side', {}).get(r, {}).get(side, {}).get('n', 0) > 0)
        if others:
            yield word, kind[o], text[slice(*anchor[s])], p, others, [r for r in others if r not in has[s]]


def _open_roles(reading, text, model):
    """Words of a reading whose role the form of the sentence leaves open: the connector after the
    word marks another role too, and the head does not have that role yet. What decides then is
    what kind of word it is. Returns [{piece, role, between: [roles], head, ask}].
    """
    return [{'piece': word, 'role': role, 'between': [role] + left, 'head': head,
             'ask': 'What is "%s" to "%s": %s?' % (word, head, ' or '.join([role] + left))}
            for word, _, head, role, _, left in _role_choices(reading, text, model) if left]


def _kinds_seen(reading, text, model):
    """Words whose kind this sentence showed: the connector after the word leaves the role open, the
    rest of the sentence does not (the head already has the other role). [{word, kind, role, head}]."""
    return [{'word': word, 'kind': kind, 'role': role, 'head': head}
            for word, kind, head, role, _, left in _role_choices(reading, text, model) if not left]


def _open_attachments(graph, text, model):
    """Parts of a reading that the sentence's structure would equally let belong to another head.

    A part (an argument, or a head with everything under it) could belong to another head when
    that head has no part in this role yet, heads like it were seen with such a part, the role
    was seen written on that side of its head, and moving the part there leaves every phrase one
    unbroken stretch. Which of the two is meant is then a matter of sense, not of form, and a
    reader without that sense should ask. Returns [{piece, role, between: [head words], ask}].
    """
    tables = model['tables']
    order = sorted((n for n in graph['nodes'] if 'anchor' in n), key=lambda n: n['anchor'])
    place = {n['id']: i for i, n in enumerate(order)}
    word = {n['id']: text[slice(*n['anchor'])] for n in order}
    links = [(s, p, o) for s, p, o in graph['edges'] if isinstance(o, str) and s in place and o in place]
    heads = sorted({s for s, _, _ in links} | {s for s, _, o in graph['edges'] if isinstance(o, dict) and 'literal' in o},
                   key=place.get)
    kinds = {n['id']: n['type'] for n in order}

    def entry(h):
        literals = sorted([p, o['literal']] for s, p, o in graph['edges'] if s == h and isinstance(o, dict) and 'literal' in o)
        return key({'type': kinds[h], 'literals': literals})

    def phrases(parent):
        below = {}
        for child, (h, _) in parent.items():
            below.setdefault(h, []).append(child)

        def reach(x, seen=()):
            found = [place[x]]
            for k in below.get(x, []):
                if k not in seen:
                    found += reach(k, seen + (x,))
            return found
        return {h: reach(h) for h in heads}

    def unbroken(parent):
        return all(max(found) - min(found) + 1 == len(found) for found in phrases(parent).values())

    parent, shared = {}, set()
    for s, p, o in links:
        if o in parent:
            # A part two heads share stands with the nearer one, and its place is not in question.
            shared.add(o)
            if abs(place[s] - place[o]) < abs(place[parent[o][0]] - place[o]):
                parent[o] = (s, p)
        else:
            parent[o] = (s, p)
    out = []
    for part, (head, role) in sorted(parent.items(), key=lambda item: place[item[0]]):
        if part in shared:
            continue
        inside = {order[i]['id'] for i in phrases(parent).get(part, [place[part]])}
        others = []
        for other in heads:
            if other == head or other in inside or any(h == other and r == role for h, r, _ in links):
                continue
            if tables.get('part', {}).get(entry(other), {}).get('+' + role, {}).get('n', 0) == 0:
                continue
            side = 'before' if place[part] < place[other] else 'after'
            if tables.get('side', {}).get(role, {}).get(side, {}).get('n', 0) == 0:
                continue
            if unbroken(dict(parent, **{part: (other, role)})):
                others.append(other)
        if others:
            between = [word[h] for h in sorted([head] + others, key=place.get)]
            out.append({'piece': word[part], 'role': role, 'between': between,
                        'ask': 'Does "%s" belong to %s?' % (word[part], ' or to '.join('"%s"' % b for b in between))})
    return out


# ---------------------------------------------------------------- sentences

def _sentence_spans(text, model):
    """Where the text can be cut into sentences: after a learned closing piece followed by blank space."""
    closers = [g for g in model['tables'].get('gap', {}).get('end', {}) if g.strip()]
    cuts = set()
    for piece in closers:
        for pos in occurrences(text, piece):
            end = pos + len(piece)
            if end < len(text) and text[end].isspace():
                cuts.add(end)
    spans, start = [], 0
    for end in sorted(cuts):
        following = end
        while following < len(text) and text[following].isspace():
            following += 1
        if following >= len(text) or end <= start:
            continue
        spans.append((start, end))
        start = following
    spans.append((start, len(text)))
    return spans


def _shift(reading, offset, tag):
    """Move one sentence's reading to its place in the whole text."""
    def move(span):
        return [span[0] + offset, span[1] + offset]

    graph = reading['graph']
    nodes = [dict(n, id=tag + n['id'], anchor=move(n['anchor'])) for n in graph['nodes']]
    edges = [[tag + s, p, tag + o if isinstance(o, str) else ({'copy': move(o['copy'])} if 'copy' in o else o)]
             for s, p, o in graph['edges']]
    return {'nodes': nodes, 'edges': edges, 'edge_spans': [[move(x) for x in spans] for spans in graph['edge_spans']],
            'project': [tag + i for i in graph['project']]}, \
        [dict(p, span=move(p['span'])) for p in reading['pieces']]


def read(text, model):
    """Read a text. Several sentences are read one at a time and joined.

    A sentence boundary is a closing piece seen in training followed by blank space. Each
    sentence must be read with confidence on its own; if a piece of text between two
    boundaries is not a sentence, it is tried together with the next one or two. One unread
    sentence holds the whole text, so a passage is never answered from part of it.
    """
    if model.get('schema') != SCHEMA:
        raise ValueError('unsupported reader model')
    spans = _sentence_spans(text, model)
    if len(spans) == 1:
        return _read_one(text, model)
    parts, failed, i = [], None, 0
    while i < len(spans):
        done = None
        for j in range(i, min(i + 3, len(spans))):
            start, end = spans[i][0], spans[j][1]
            result = _read_one(text[start:end], model)
            if j == i:
                first = (start, end, result)
            if result['status'] == 'complete':
                done = (start, end, result, j)
                break
        if done is None:
            failed = failed or first
            i += 1
        else:
            parts.append(done[:3])
            i = done[3] + 1
    limit = model['policy'].get('max_whole_chars', 200)
    if failed and len(text) <= limit:
        whole = _read_one(text, model)
        if whole['status'] == 'complete':
            return whole
    needed = math.log(model['policy']['margin_ratio'])
    if failed:
        start, end, result = failed
        out = dict(result, text=text, graphs=[], sentences=len(spans), sentences_read=len(parts),
                   status='hold' if result['status'] == 'hold' else 'ambiguous' if result['status'] == 'ambiguous'
                   else 'unresolved',
                   reason='%d of %d sentences could not be read; first: "%s" (%s)'
                          % (len(spans) - len(parts) if len(parts) < len(spans) else 1, len(spans),
                             text[start:end][:40], result['reason']))
        shifted = []
        for k, reading in enumerate(result['readings']):
            graph, pieces = _shift(reading, start, 's0_')
            shifted.append(dict(reading, graph=graph, pieces=pieces))
        out['readings'] = shifted
        return out
    nodes, edges, evidence, project, pieces, terms, last = [], [], [], [], [], [], 0
    score, margins, leads, merged_any = 0.0, [], [], False
    for k, (start, end, result) in enumerate(parts):
        chosen = result['readings'][result['chosen']]
        graph, moved = _shift(chosen, start, 's%d_' % k)
        if start > last:
            pieces.append({'kind': 'gap', 'text': text[last:start], 'span': [last, start], 'how': 'between sentences'})
        last = end
        nodes += graph['nodes']
        edges += graph['edges']
        evidence += graph['edge_spans']
        project += graph['project']
        pieces += moved
        terms += chosen['terms']
        score += chosen['score']
        if result['margin'] is not None:
            margins.append(result['margin'])
        if result.get('unseen_lead') is not None:
            leads.append(result['unseen_lead'])
    graph = {'nodes': nodes, 'edges': edges, 'edge_spans': evidence, 'project': project}
    try:
        joined = M.merge_graph(graph, text, model.get('identity', {}))
    except ValueError:
        joined = None
    ignored = [x for _, _, r in parts for x in r.get('ignored', [])]
    variants = sorted({x for _, _, r in parts for x in r.get('variants', [])})
    told = {x['word']: x for _, _, r in parts for x in r.get('told', [])}
    reading = {'graph': joined or graph, 'score': score, 'supported': True, 'terms': terms, 'pieces': pieces,
               'merged': joined is not None, 'tied_evidence': False, 'ignored': ignored, 'variants': variants,
               'told': [told[w] for w in sorted(told)]}
    return {'text': text, 'status': 'complete', 'graphs': [reading['graph']], 'readings': [reading], 'chosen': 0,
            'required_margin': needed, 'margin': min(margins) if margins else None,
            'unseen_lead': max(leads) if leads else None,
            'cut_between_equals': any(r.get('cut_between_equals') for _, _, r in parts),
            'sentences': len(spans), 'sentences_read': len(parts), 'ignored': ignored, 'variants': variants,
            'told': [told[w] for w in sorted(told)],
            'reason': 'read as %d sentences, each with every piece seen in training and a clear lead' % len(parts)
                      + ('; ignoring %s' % ', '.join('"%s"' % x for x in ignored) if ignored else '')}
